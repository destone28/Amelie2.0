"""Quanta batteria resta, senza che la batteria lo dica.

Il power bank non espone niente: nessuna tensione, nessuna percentuale, nessun
filo in piu' da tirare. Quello che il dispositivo sa e' da quanto e' acceso e
quanto ha lavorato. Da li' si stima l'energia spesa, e si dice quanto ne resta.

## Il conto

Il Charmast e' dichiarato 26.800 mAh a 3,7 V, cioe' 99 Wh nominali. Un power
bank ne restituisce a 5 V molto meno - conversione, taratura ottimistica,
celle non nuove - e per questi da scaffale il reso vero sta fra il sessanta e
il settanta per cento. Qui si prendono **60 Wh**: e' la parte bassa della
forbice, che e' quello che si vuole da una stima che non puo' misurare. Non
piu' bassa, perche' una tacca vuota con tre ore di autonomia davanti insegna
a non guardarla.

La potenza si stima come una base fissa piu' una parte che segue la CPU:

    base       5,0 W   SoC a riposo ~1,8, schermo 1,5 (misurato dal
                       costruttore: 0,30 A a 5 V), hub e camera in moto ~1,2,
                       anello e amplificatore a riposo ~0,5
    CPU piena +2,5 W   quattro Cortex-A53 a pieno carico
    voce      +0,6 W   amplificatore che suona

La base e' stimata a progetto (~5 W medi, oltre 12 ore di autonomia), non
misurata col tester USB: una misura vera va messa qui al suo posto, e basta.
La CPU si legge da `/proc/stat`, che e' l'unica misura vera che la board
offre di quanto sta lavorando - e il modello linguistico, l'OCR e la sintesi
vocale passano tutti di li'.

## Quando si azzera

Il dispositivo non si spegne con un comando: si stacca la corrente a fine
servizio, e si ricarica di notte. Quindi si scrive su disco ogni pochi secondi
l'energia spesa e l'ora, e all'accensione si guarda da quanto si era fermi:
piu' di tre ore vuol dire una notte, e una notte vuol dire ricaricato. Meno,
vuol dire un riavvio in mezzo al servizio, e la stima riprende da dov'era.

Se l'orologio della board non e' affidabile all'avvio - senza rete puo'
ripartire da una data qualunque - il salto risulta negativo o assurdo, e si
tiene la stima di prima: e' l'errore che costa meno.

E c'e' un modo a mano, dalle impostazioni: «batteria ricaricata». Serve a chi
la ricarica di giorno, e a chi non si fida.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

CAPACITA_WH = 60.0
POTENZA_BASE_W = 5.0
POTENZA_CPU_W = 2.5
POTENZA_VOCE_W = 0.6

# Fermo per piu' di cosi' vuol dire ricaricato.
RICARICATA_DOPO_S = 3 * 3600.0
# Oltre questo il salto dell'orologio non e' una notte, e' un orologio rotto.
SALTO_ASSURDO_S = 60 * 86400.0

# Le tacche dell'icona, dalla frazione che resta. L'ultima tacca sparisce
# all'otto per cento e non allo zero: sotto, il power bank puo' spegnersi da
# solo senza avvisare, e una tacca accesa sarebbe una bugia.
TACCHE = ((0.75, 4), (0.50, 3), (0.25, 2), (0.08, 1))


def cpu_occupata() -> tuple[int, int] | None:
    """(tempo occupato, tempo totale) in tick, da `/proc/stat`."""
    try:
        with open("/proc/stat", encoding="ascii") as f:
            campi = f.readline().split()
    except OSError:
        return None
    if len(campi) < 5 or campi[0] != "cpu":
        return None
    valori = [int(x) for x in campi[1:]]
    riposo = valori[3] + (valori[4] if len(valori) > 4 else 0)   # idle + iowait
    return sum(valori) - riposo, sum(valori)


class Batteria:
    """La stima, e come si aggiorna."""

    def __init__(self, percorso: str | Path, *,
                 capacita_wh: float = CAPACITA_WH,
                 ora: Callable[[], float] = time.time,
                 cpu: Callable[[], tuple[int, int] | None] = cpu_occupata) -> None:
        self.percorso = Path(percorso)
        self.capacita = capacita_wh
        self._ora = ora
        self._cpu = cpu
        self.consumato_wh = 0.0
        self._ultimo_t: float | None = None
        self._ultima_cpu: tuple[int, int] | None = None

    # ------------------------------------------------------------ avvio

    def avvia(self) -> None:
        """Riprende la stima da disco, o riparte da carica se e' passata una notte."""
        adesso = self._ora()
        try:
            d = json.loads(self.percorso.read_text(encoding="utf-8"))
            consumato = float(d.get("consumato_wh", 0.0))
            ultimo = float(d.get("ultimo_vivo", 0.0))
        except (OSError, ValueError, TypeError):
            log.info("batteria: nessuna stima salvata, si parte da carica")
            consumato, ultimo = 0.0, adesso
        fermo = adesso - ultimo
        if RICARICATA_DOPO_S <= fermo <= SALTO_ASSURDO_S:
            log.info("batteria: ferma da %.1f ore, la considero ricaricata", fermo / 3600)
            consumato = 0.0
        elif fermo < 0 or fermo > SALTO_ASSURDO_S:
            log.warning("batteria: orologio inattendibile (salto di %.0f s), "
                        "tengo la stima di prima", fermo)
        self.consumato_wh = max(0.0, consumato)
        self._ultimo_t = adesso
        self._ultima_cpu = self._cpu()

    # ------------------------------------------------------------ stima

    def aggiorna(self, *, voce_accesa: bool = False) -> None:
        """Somma l'energia spesa dall'ultima chiamata."""
        adesso = self._ora()
        if self._ultimo_t is None:
            self.avvia()
            return
        dt = adesso - self._ultimo_t
        if dt <= 0:
            self._ultimo_t = adesso
            return
        quota_cpu = 0.0
        cpu = self._cpu()
        if cpu is not None and self._ultima_cpu is not None:
            occupato = cpu[0] - self._ultima_cpu[0]
            totale = cpu[1] - self._ultima_cpu[1]
            if totale > 0:
                quota_cpu = max(0.0, min(1.0, occupato / totale))
        self._ultima_cpu = cpu
        watt = POTENZA_BASE_W + POTENZA_CPU_W * quota_cpu
        if voce_accesa:
            watt += POTENZA_VOCE_W
        self.consumato_wh += watt * dt / 3600.0
        self._ultimo_t = adesso

    @property
    def frazione(self) -> float:
        """Quanta ne resta, da 0 a 1."""
        return max(0.0, min(1.0, 1.0 - self.consumato_wh / self.capacita))

    @property
    def tacche(self) -> int:
        f = self.frazione
        for soglia, n in TACCHE:
            if f >= soglia:
                return n
        return 0

    @property
    def ore_rimaste(self) -> float:
        """Alla potenza di base: e' una stima della stima, serve al giornale."""
        return (self.capacita - self.consumato_wh) / POTENZA_BASE_W

    def ricaricata(self) -> None:
        """Qualcuno l'ha messa in carica e lo dice: si riparte da piena."""
        self.consumato_wh = 0.0
        self._ultimo_t = self._ora()
        self._ultima_cpu = self._cpu()
        self.salva()

    # ------------------------------------------------------------ disco

    def salva(self) -> None:
        """Scrive la stima in modo che sopravviva alla spina staccata.

        Rename atomica e fsync: fra la scrittura e il disco possono passare
        secondi, e il dispositivo si spegne staccando la corrente.
        """
        try:
            self.percorso.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.percorso.with_suffix(".parziale")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"consumato_wh": round(self.consumato_wh, 3),
                           "ultimo_vivo": self._ora()}, f)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.percorso)
            cartella = os.open(self.percorso.parent, os.O_RDONLY)
            try:
                os.fsync(cartella)
            finally:
                os.close(cartella)
        except OSError as e:
            log.warning("batteria: stima non salvata: %s", e)
