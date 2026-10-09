"""La voce.

Piper sintetizza **una frase alla volta**, e questo cambia tutto: si può
cominciare a parlare appena la prima frase è pronta, mentre il modello sta
ancora scrivendo la seconda. Su questa board sono venti secondi di silenzio
risparmiati — la differenza fra un dispositivo che risponde e uno che sembra
bloccato.

## La voce scelta

`it_IT-serena-medium`, e la ragione è di licenza, non di gusto. La più diffusa
`it_IT-paola-medium` dichiara nella sua scheda ufficiale di essere un
*finetuning* della voce inglese `lessac`, il cui dataset — Blizzard Challenge
2013 — vieta esplicitamente *«any commercial purpose, including the development,
marketing, commercialisation, sale or licencing of voice synthesis products»*.
Il dispositivo può essere distribuito anche a fini commerciali, e la licenza
della voce deve permetterlo. `serena` è addestrata da zero su dataset
CC BY 4.0, ha la stessa architettura e lo stesso costo di calcolo — i due file
ONNX differiscono di un byte — e chiede solo una riga di attribuzione.

## La pronuncia

Il motore fonetico se la cava benissimo con l'italiano, ma inciampa esattamente
dove un dispositivo sul vino non può permetterselo: le sigle e i nomi stranieri.
«DOCG» letto come parola è imbarazzante. Il dizionario qui sotto riscrive il
testo **prima** della sintesi: è più affidabile di qualunque markup, perché
agisce su ciò che il motore legge davvero.
"""

from __future__ import annotations

import array
import bisect
import hashlib
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger(__name__)

VOCE_PREDEFINITA = "it_IT-serena-medium"

# 16 bit, un canale: ogni campione sono due byte. Una posizione nel buffer deve
# cadere sempre all'inizio di un campione: ripartendo da un byte dispari ogni
# campione si legge a cavallo di due, il byte alto diventa basso, e la voce
# diventa un fruscio forte e spezzettato.
BYTE_PER_CAMPIONE = 2


# Il PCM e' lineare: un secondo di parlato sono sempre gli stessi byte. E' cio'
# che rende possibile un player vero - saltare avanti di cinque secondi e'
# aritmetica su un offset, non una ricerca dentro un formato compresso.
def byte_al_secondo(frequenza: int = 22050) -> int:
    return frequenza * BYTE_PER_CAMPIONE


def allinea(byte: int) -> int:
    """La posizione `byte` riportata all'inizio del suo campione."""
    return byte - byte % BYTE_PER_CAMPIONE


# Quanto si scrive ad aplay per volta. Cento millisecondi: abbastanza piccolo
# perche' una pausa si senta subito, abbastanza grande da non costare nulla.
PEZZO_S = 0.1
# Il buffer che si lascia ad ALSA. Piu' e' grande, piu' il suono sopravvive a un
# picco di carico - e questa board ha quattro core contesi da OCR e sintesi - ma
# piu' la posizione dichiarata corre avanti a quella che l'orecchio sente. Due
# decimi sono il compromesso: impercettibile, e regge l'OCR in parallelo.
BUFFER_ALSA_US = 200_000

# Il DSP di questa board non comincia a rendere il suono nell'istante in cui si
# apre il flusso, e `aplay` esce PRIMA che l'ultimo pezzo sia uscito davvero.
# Misurato qui: su ogni durata, dai tre secondi al secondo scarso, aplay
# impiega 0,35 s in meno del dovuto. Su nove secondi di racconto non si nota;
# su una frase da un secondo se ne mangia i due terzi e resta un rumorino.
#
# Il rimedio NON e' imbottire di silenzio: e' non chiudere mai il flusso. Vedi
# `Uscita`.


def silenzio(secondi: float, frequenza: int = 22050) -> bytes:
    return b"\x00\x00" * int(frequenza * secondi)


def scrivi_durevole(percorso: Path, dati: bytes) -> None:
    """Scrive un file in modo che sopravviva alla spina staccata.

    Il dispositivo si spegne togliendo corrente. Su ext4 un file NUOVO scritto e
    rinominato resta in memoria per alcuni secondi, e se la corrente salta in
    quel momento al riavvio c'e' il nome ma non il contenuto: un file lungo
    zero. Da qui i due `fsync`: uno per il contenuto, uno per la cartella, che
    e' cio' che rende durevole il nome nuovo. Il file temporaneo fa si' che un
    file troncato a meta' non prenda mai il nome buono.
    """
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_suffix(".parziale")
    with open(tmp, "wb") as f:
        f.write(dati)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(percorso)
    cartella = os.open(percorso.parent, os.O_RDONLY)
    try:
        os.fsync(cartella)
    finally:
        os.close(cartella)


# ------------------------------------------------------------------- volume

# Questa catena audio NON HA un controllo di volume hardware. Il suono esce da
# SEC_MI2S_RX, attraversa l'I2S, il ponte ANX7625 e l'HDMI, e arriva allo
# schermo: i controlli «Volume» che il mixer ALSA espone - HPHL, HPHR, RX_RX*
# - appartengono al codec delle cuffie del SoC, che sta su un altro percorso e
# non tocca questo. L'unico posto dove il volume si puo' cambiare e' il PCM,
# prima di passarlo ad aplay.
VOLUME_PREDEFINITO = 100

# Il volume e' un numero da 0 a 100, e diventa guadagno col QUADRATO. Una scala
# lineare sull'AMPIEZZA non sembra lineare all'orecchio: da 100 a 50 non si
# sente quasi niente, e sotto 20 crolla di colpo. Col quadrato, meta' corsa fa
# un quarto di ampiezza, cioe' -12 dB, che e' circa cio' che si chiama «meta'
# volume»; e un decimo di corsa fa -40 dB, cioe' un filo di voce.
def guadagno_di(volume: int) -> float:
    """Da 0-100 a un fattore fra 0 e 1. Non si sale MAI sopra 1.

    Amplificare oltre il fondo scala non e' una scelta disponibile: il PCM e'
    gia' al massimo che 16 bit possono dire, e moltiplicarlo taglierebbe le
    creste. Chi ha bisogno di piu' volume alza l'amplificatore, che e' fatto
    per quello.
    """
    v = max(0, min(100, int(volume)))
    return (v / 100.0) ** 2


def scala_pcm(dati: bytes, guadagno: float) -> bytes:
    """Moltiplica del PCM a 16 bit per un guadagno fra 0 e 1.

    Con numpy costa una decina di microsecondi ogni ottanta millisecondi di
    suono. Senza, si ricade su `array`, che su questi pezzi e' comunque
    trascurabile: serve solo a non rendere numpy obbligatorio per parlare.
    """
    if guadagno >= 1.0 or not dati:
        return dati
    if guadagno <= 0.0:
        return bytes(len(dati))
    # Un byte spaiato NON si butta via: toglierlo sfaserebbe di mezzo campione
    # tutto cio' che viene dopo, e il parlato diventerebbe fruscio. Si lascia
    # passare com'e' - nel flusso vero non capita mai, i pezzi sono pari.
    coda = dati[len(dati) - len(dati) % 2:]
    corpo = dati[:len(dati) - len(dati) % 2]
    try:
        import numpy as np
    except ImportError:
        a = array.array("h")
        a.frombytes(corpo)
        for i, c in enumerate(a):
            a[i] = int(c * guadagno)
        if a.itemsize != 2:                                 # pragma: no cover
            raise RuntimeError("array 'h' non e' a 16 bit su questa macchina")
        return a.tobytes() + coda
    campioni = np.frombuffer(corpo, dtype="<i2")
    return (campioni * guadagno).astype("<i2").tobytes() + coda


def tocco(frequenza_hz: float = 660.0, durata_s: float = 0.22,
          frequenza: int = 22050, ampiezza: float = 0.30) -> bytes:
    """Un colpetto su un calice: e' il ritorno del comando del volume.

    Serve perche' il volume si regola anche a dispositivo fermo, e senza un
    suono non si saprebbe a che livello lo si sta mettendo finche' non arriva
    una bottiglia. Ha l'attacco corto e la coda che si spegne da sola: un seno
    troncato di netto fa un click a tutte e due le estremita', e su un
    amplificatore quel click e' piu' forte della nota.
    """
    n = int(frequenza * durata_s)
    if n <= 0:
        return b""
    attacco = max(1, int(frequenza * 0.004))
    onda = array.array("h", bytes(2 * n))
    for i in range(n):
        inviluppo = min(1.0, i / attacco) * math.exp(-4.0 * i / n)
        v = ampiezza * inviluppo * math.sin(2 * math.pi * frequenza_hz * i / frequenza)
        onda[i] = int(max(-1.0, min(1.0, v)) * 32767)
    return onda.tobytes()



class Uscita:
    """Un flusso audio che si apre una volta sola e non si chiude mai.

    Il DSP di questa board impiega **circa due secondi** a cominciare a rendere
    il suono dopo l'apertura del flusso. Non e' una stima: di sei bip a un
    secondo l'uno dall'altro, appena aperto il flusso, se ne sentono
    quattro. Aprire e chiudere `aplay` a ogni frase significa pagare quei due
    secondi ogni volta - e una frase da un secondo sparisce del tutto, ne resta
    l'ultima sillaba.

    Allungare le frasi sarebbe un cerotto: i primi due secondi del racconto
    verrebbero mangiati lo stesso, e sono quelli che dicono che vino e'.

    Qui il flusso resta aperto: quando non c'e' niente da dire si versa
    silenzio, che costa quarantaquattro kilobyte al secondo e nessun problema.
    Il prezzo si paga una volta all'accensione, dove non lo sente nessuno.
    """

    # Quanto si tiene in pancia prima di far aspettare chi scrive. Serve a due
    # cose: che il suono non si interrompa se il sistema e' occupato, e che chi
    # scrive non corra troppo avanti - altrimenti la posizione dichiarata dal
    # player scappa avanti a quella che l'orecchio sente.
    RISERVA_S = 0.3
    PEZZO_S = 0.08
    # Di quanto si sta avanti a cio' che l'orecchio sente. Senza un freno non
    # lo si decide: si scrive finche' qualcuno accetta, e la pipe del sistema
    # da sola tiene 64 KB, cioe' UN SECONDO E MEZZO di parlato a 22050 mono:
    # senza freno, la voce arriverebbe dopo la didascalia di altrettanto.
    VANTAGGIO_S = 0.25
    # Se si resta indietro di piu' di cosi' - il sistema occupato, l'OCR che
    # parte - si riparte da capo col conto invece di recuperare a raffica, che
    # riempirebbe di nuovo la pipe.
    RECUPERO_MAX_S = 0.6

    def __init__(self, voce: "Voce") -> None:
        self.voce = voce
        self._bps = byte_al_secondo(voce.imp.frequenza)
        self._coda = bytearray()
        self._stato = threading.Lock()
        self._spazio = threading.Condition(self._stato)
        self._fermo = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._filo: threading.Thread | None = None
        self._versati = 0

    @property
    def aperta(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def avvia(self) -> None:
        if self.aperta:
            return
        self._fermo.clear()
        self._proc = self.voce.apri_uscita()
        self._filo = threading.Thread(target=self._versa, daemon=True)
        self._filo.start()
        log.info("uscita audio aperta e tenuta aperta")

    def scrivi(self, pcm: bytes) -> None:
        """Accoda del suono. Aspetta se la riserva e' gia' piena."""
        if not pcm:
            return
        soglia = int(self.RISERVA_S * self._bps)
        with self._spazio:
            while len(self._coda) > soglia and not self._fermo.is_set():
                self._spazio.wait(0.1)
            self._coda.extend(pcm)

    def attendi_residuo(self, residuo_s: float, tetto_s: float = 120.0) -> None:
        """Aspetta finche' manca `residuo_s` alla fine di cio' che e' in coda.

        E' il conto che fa combaciare la didascalia con la voce. `in_pancia_s`
        dice fra quanto verra' sentito l'ULTIMO byte accodato; se dopo aver
        accodato una frase lunga `d` si aspetta che ne manchi esattamente `d`,
        quel momento e' quello in cui la frase COMINCIA a sentirsi.
        """
        # Sotto la latenza non si puo' scendere: e' cio' che e' gia' partito.
        bersaglio = max(residuo_s, self.latenza_s + 0.02)
        scadenza = time.monotonic() + tetto_s
        while self.in_pancia_s() > bersaglio and time.monotonic() < scadenza:
            if self._fermo.wait(0.02):
                return

    def attendi_fine(self, tetto_s: float = 120.0) -> None:
        """Aspetta che TUTTO l'audio inviato sia stato davvero sentito.

        «Inviato» e «sentito» non sono la stessa cosa: in mezzo ci sono la
        riserva di questa coda, la pipe del sistema e il buffer di ALSA. Chi
        scrive l'ultimo pezzo di una frase ha finito il suo lavoro, ma
        l'orecchio deve ancora ricevere mezzo secondo abbondante di suono.
        """
        scadenza = time.monotonic() + tetto_s
        while (self.in_pancia_s() > self.latenza_s + 0.02
               and time.monotonic() < scadenza):
            if self._fermo.wait(0.02):
                return
        # E poi la latenza vera e propria: l'ultimo byte inviato deve ancora
        # attraversare la pipe e il buffer di ALSA.
        self._fermo.wait(min(self.latenza_s, max(0.0, scadenza - time.monotonic())))

    def svuota(self) -> None:
        """Butta via cio' che non e' ancora uscito. E' il "taci adesso"."""
        with self._spazio:
            self._coda.clear()
            self._spazio.notify_all()

    @property
    def latenza_s(self) -> float:
        """Quanto passa fra l'invio di un byte e il sentirlo."""
        return self.VANTAGGIO_S + BUFFER_ALSA_US / 1_000_000

    def in_pancia_s(self) -> float:
        """Quanto manca perche' TUTTO l'audio inviato sia stato sentito.

        Non e' solo la coda: c'e' anche cio' che e' gia' passato ad aplay e non
        e' ancora uscito. Contando solo la coda si crederebbe di aver finito
        con un secondo e mezzo di anticipo, e la didascalia correrebbe avanti
        alla voce di altrettanto.
        """
        with self._stato:
            coda = len(self._coda) / self._bps
        return coda + self.latenza_s

    def chiudi(self) -> None:
        self._fermo.set()
        with self._spazio:
            self._spazio.notify_all()
        if self._filo is not None:
            self._filo.join(timeout=3)
        with self._stato:
            proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:                               # noqa: BLE001
                pass
            try:
                proc.kill(); proc.wait(timeout=2)
            except Exception:                               # noqa: BLE001
                pass

    def _versa(self) -> None:
        """Versa a PASSO D'OROLOGIO, non a riempimento.

        Se si scrive finche' qualcuno accetta, si finisce molto avanti a cio'
        che si sente: la pipe del sistema da sola tiene 64 KB, che a 22050 mono
        sono un secondo e mezzo di parlato, e dopo c'e' il buffer di ALSA: la
        voce arriverebbe dopo la didascalia di altrettanto.

        Scrivendo al ritmo del suono, "inviato" torna a voler dire "sentito"
        a meno del vantaggio dichiarato.
        """
        pezzo = int(self.PEZZO_S * self._bps)
        muto = silenzio(self.PEZZO_S, self.voce.imp.frequenza)
        inizio = time.monotonic()
        self._versati = 0

        while not self._fermo.is_set():
            with self._spazio:
                dati = bytes(self._coda[:pezzo])
                del self._coda[:len(dati)]
                self._spazio.notify_all()
                proc = self._proc
            if proc is None:
                return
            if not dati:
                # Silenzio quando non c'e' niente da dire: e' cio' che tiene
                # sveglio il DSP e fa parlare tutto il resto all'istante. Il
                # volume non lo tocca: il silenzio moltiplicato resta silenzio.
                dati = muto
            else:
                # Il volume si applica QUI e non quando si accoda, perche' qui
                # ci passa tutto - il racconto, gli annunci, il colpetto - e
                # perche' cosi' cambiarlo si sente entro il tempo della riserva,
                # tre decimi di secondo, invece che alla frase dopo.
                dati = scala_pcm(dati, self.voce.guadagno)

            atteso = inizio + self._versati / self._bps - self.VANTAGGIO_S
            ritardo = atteso - time.monotonic()
            if ritardo > 0:
                if self._fermo.wait(ritardo):
                    return
            elif ritardo < -self.RECUPERO_MAX_S:
                # Si e' rimasti indietro sul serio: si riparte da capo col
                # conto, invece di recuperare a raffica e riempire la pipe.
                inizio = time.monotonic()
                self._versati = 0

            try:
                proc.stdin.write(dati)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                log.warning("uscita audio chiusa sotto di noi")
                return
            self._versati += len(dati)

# Una voce per lingua. La scelta e' di LICENZA prima che di gusto: vedi la nota
# in testa al modulo per l'italiano, e docs/it/08-attribuzioni.md per l'inglese.
# Se per una lingua non c'e' voce, il dispositivo mostra il testo e tace: e'
# meglio del sentire un motore italiano leggere l'inglese.
VOCI = {
    "it": "it_IT-serena-medium",
    # Addestrata DA ZERO sul dataset LJ Speech, di pubblico dominio. La scelta
    # e' la stessa dell'italiano e per la stessa ragione: le voci inglesi piu'
    # diffuse di Piper - `lessac` e tutte quelle rifinite a partire da lei,
    # `alba` e `libritts_r` comprese - poggiano sul dataset Blizzard Challenge
    # 2013, che vieta esplicitamente l'uso commerciale. Il dispositivo puo'
    # essere distribuito anche a fini commerciali, quindi non basta che la
    # scheda dica CC BY: bisogna guardare anche da CHE COSA e' stata rifinita.
    "en": "en_US-ljspeech-medium",
}
CARTELLA_CACHE = Path.home() / ".cache" / "amelie" / "voce"

# Quanti caratteri di testo stanno in un secondo di parlato, voce per voce.
# Serve a dire quanto dura un racconto PRIMA di averlo sintetizzato: la barra
# di avanzamento ha bisogno di un denominatore, e quello vero non esiste
# ancora. Vedi `Riproduttore.quota`.
#
# Misurate sintetizzando davvero, 90 frasi per voce prese dai racconti in
# archivio, 15-136 caratteri, per dieci minuti di parlato complessivi. Non
# dai file in cache: sono pochi, non sono un campione, e danno un'altra
# costante, sbagliata.
#
# Il modello e' PROPORZIONALE, senza parte fissa. Quello con l'intercetta -
# il silenzio che Piper mette in testa e in coda e' reale, e in italiano i
# minimi quadrati lo misurano in 0,22 s - vale uguale: tarando su meta'
# frasi e provando sull'altra meta', l'errore sulla somma di sei frasi e'
# 2,8% contro 2,9% in inglese e 2,7% contro 3,2% in italiano. Mezzo punto non
# paga una seconda costante per voce.
#
# (Sull'inglese quell'intercetta viene NEGATIVA, -5.179 byte, il che dice solo
# che una retta non e' la forma giusta su quel campione. Non sarebbe un
# pericolo: la stima si annullerebbe sotto 1,6 caratteri, e le frasi misurate
# vanno da 23 a 136. E' un motivo per diffidare del modello, non per temerlo.)
#
# Errore sulla somma di sei frasi, che e' cio' che conta qui: mediana 2,7% in
# italiano e 2,8% in inglese, novantesimo percentile 8,0% e 6,6%.
CARATTERI_AL_SECONDO = {
    "it_IT-serena-medium": 17.2,
    "en_US-ljspeech-medium": 14.4,
}
# Per una voce che non e' in tabella: la media delle due misurate.
CARATTERI_AL_SECONDO_RIPIEGO = 15.8

# Quanto vale una CIFRA, in caratteri parlati. «1990» sono quattro segni e
# Piper dice «millenovecentonovanta», che ne vale ventuno: contandoli per
# quattro si sottostima. Non e' un caso di bordo - annata, temperatura e
# gradazione chiudono quasi ogni racconto, cioe' sono proprio la CODA, la sola
# parte che questa stima deve coprire.
#
# Misurato sintetizzando davvero, 39 frasi con cifre fra le due voci: l'errore
# mediano su quelle frasi e' del 3,2% in tutte e due, contro il 27% (italiano)
# e il 19% (inglese) contando ogni cifra per un carattere. E il valore viene
# lo stesso per le due lingue, il che ha senso: un numero si pronuncia lungo
# in qualunque lingua.
CIFRA_VALE = 4.7


def caratteri_al_secondo(modello: str) -> float:
    return CARATTERI_AL_SECONDO.get(modello, CARATTERI_AL_SECONDO_RIPIEGO)


# --------------------------------------------------------------- pronuncia

# Sostituzioni applicate al testo prima della sintesi. La chiave è
# un'espressione regolare con i confini di parola già inclusi.
PRONUNCIA: dict[str, str] = {
    # Sigle: lette come parole diventano incomprensibili.
    r"\bD\.?O\.?C\.?G\.?\b": "denominazione di origine controllata e garantita",
    r"\bD\.?O\.?C\.?\b": "denominazione di origine controllata",
    r"\bI\.?G\.?T\.?\b": "indicazione geografica tipica",
    r"\bI\.?G\.?P\.?\b": "indicazione geografica protetta",
    r"\bD\.?O\.?P\.?\b": "denominazione di origine protetta",
    r"\bV\.?S\.?Q\.?\b": "vino spumante di qualità",
    # Nomi stranieri ricorrenti nel mondo del vino.
    r"\bCh[âa]teauneuf[- ]du[- ]Pape\b": "sciatonèf du pap",
    r"\bCh[âa]teau\b": "sciatò",
    r"\bGew[üu]rztraminer\b": "ghevürtstraminer",
    r"\bSauvignon\b": "sovignòn",
    r"\bCabernet\b": "cabernè",
    r"\bMerlot\b": "merlò",
    r"\bPinot\b": "pinò",
    r"\bSyrah\b": "sirà",
    r"\bShiraz\b": "sciràz",
    r"\bChardonnay\b": "sciardonè",
    r"\bRiesling\b": "rìsling",
    r"\bMüller[- ]Thurgau\b": "müller turgau",
    r"\bBrut\b": "brut",
    r"\bCuv[ée]e\b": "cüvè",
    # Unità e simboli.
    r"(\d+)\s*°C\b": r"\1 gradi",
    r"(\d+)\s*%": r"\1 per cento",
    r"\bcl\b": "centilitri",
    r"\bml\b": "millilitri",
}

# E la stessa tabella in inglese, perche' una sigla italiana letta dalla voce
# inglese e' due errori in uno.
#
# Con la tabella qui sopra applicata a qualunque lingua, in inglese «DOCG»
# diventerebbe «denominazione di origine controllata e garantita», e la voce
# inglese lo compiterebbe all'inglese. Una frase italiana, pronunciata male,
# in mezzo a un testo inglese.
#
# Le sigle si sciolgono anche qui, e nella loro forma inglese: sono le diciture
# che stanno sulle etichette esportate. Le respellature fonetiche NON ci sono
# di proposito: «sciardonè» serve a una voce italiana che leggerebbe
# «Chardonnay» all'italiana, mentre una voce inglese quel nome lo sa gia' dire,
# e darle «sciardonè» sarebbe peggio di non fare niente.
PRONUNCIA_EN: dict[str, str] = {
    r"\bD\.?O\.?C\.?G\.?\b": "controlled and guaranteed designation of origin",
    r"\bD\.?O\.?C\.?\b": "controlled designation of origin",
    r"\bI\.?G\.?T\.?\b": "typical geographical indication",
    r"\bI\.?G\.?P\.?\b": "protected geographical indication",
    r"\bD\.?O\.?P\.?\b": "protected designation of origin",
    r"\bV\.?S\.?Q\.?\b": "quality sparkling wine",
    r"(\d+)\s*°C\b": r"\1 degrees Celsius",
    r"(\d+)\s*%": r"\1 percent",
    r"\bcl\b": "centilitres",
    r"\bml\b": "millilitres",
}

_COMPILATE = {
    "it": [(re.compile(k, re.I), v) for k, v in PRONUNCIA.items()],
    "en": [(re.compile(k, re.I), v) for k, v in PRONUNCIA_EN.items()],
}


def lingua_del_modello(modello: str) -> str:
    """«en_US-ljspeech-medium» -> «en». Il nome della voce dice la lingua."""
    codice = (modello or "")[:2].lower()
    return codice if codice in _COMPILATE else "it"


def per_la_voce(testo: str, lingua: str = "it") -> str:
    """Riscrive il testo come va pronunciato, nella lingua in cui si parla.

    >>> per_la_voce("Un Barolo DOCG al 14%.")
    'Un Barolo denominazione di origine controllata e garantita al 14 per cento.'
    >>> per_la_voce("A Barolo DOCG at 14%.", "en")
    'A Barolo controlled and guaranteed designation of origin at 14 percent.'
    """
    # Le virgolette del nome - «Cannubi» a schermo - non si pronunciano.
    testo = re.sub(r"[«»“”\"]", "", testo)
    for pattern, sostituto in _COMPILATE.get(lingua, _COMPILATE["it"]):
        testo = pattern.sub(sostituto, testo)
    # Il trattino fra numeri si legge "meno": va sciolto. E la congiunzione
    # e' della lingua in cui si parla: «serve at 8 e 10 degrees» avrebbe una
    # parola italiana in mezzo a una frase inglese - lo stesso difetto delle
    # sigle, in piccolo.
    testo = re.sub(r"(\d)\s*-\s*(\d)",
                   r"\1 to \2" if lingua == "en" else r"\1 e \2", testo)
    # «13.0%»: in italiano il decimale si scrive con la virgola, e chi legge
    # dice «tredici punto zero» solo se glielo si scrive col punto. Il
    # separatore delle migliaia - «1.500 metri» - ha tre cifre dopo il punto
    # e non va toccato.
    if lingua != "en":
        testo = re.sub(r"(\d)\.(\d{1,2})(?!\d)", r"\1,\2", testo)
    return re.sub(r"\s+", " ", testo).strip()


def byte_stimati(frase: str, modello: str, frequenza: int = 22050) -> int:
    """Quanto audio produrra' questa frase, prima di sintetizzarla.

    Si contano i caratteri di cio' che verra' PRONUNCIATO, non di cio' che e'
    scritto. `per_la_voce` scioglie le sigle, e «DOCG» da quattro caratteri ne
    diventa quarantotto: stimare sul testo grezzo sbaglia di piu' del doppio
    proprio sulle frasi d'apertura, che sono quelle che si sentono per prime.

    E le cifre valgono per quello che si sente, non per quanti segni sono:
    vedi `CIFRA_VALE`.

    Zero per una frase che non si pronuncia: `sintetizza` restituisce b"" nello
    stesso caso, e le due cose devono dire la stessa cosa.
    """
    detto = per_la_voce(frase, lingua_del_modello(modello))
    if not detto:
        return 0
    cifre = sum(c.isdigit() for c in detto)
    lunghezza = len(detto) + (CIFRA_VALE - 1) * cifre
    return int(lunghezza / caratteri_al_secondo(modello) * byte_al_secondo(frequenza))


# ------------------------------------------------------------------- voce

@dataclass(frozen=True)
class ImpostazioniVoce:
    modello: str = VOCE_PREDEFINITA
    # Dove suonare. Sulla UNO Q l'HDMI e' il PCM 3 della scheda del SoC: non
    # esiste un device che si chiami "HDMI", e' il backend di MultiMedia4.
    # plughw, non hw: il device HDMI accetta SOLO 32000-48000 Hz e uno o due
    # canali, mentre Piper produce 22050 mono. Con `hw:` ogni riproduzione
    # fallisce con "Unable to install hw params", e non si sente niente.
    # `plughw` mette in mezzo la conversione di ALSA, che su questa board
    # costa una frazione di punto percentuale di CPU.
    device_alsa: str = "plughw:0,3"
    frequenza: int = 22050
    usa_cache: bool = True


class Voce:
    """Sintetizza e riproduce. Il modello si carica una volta sola.

    Caricare Piper costa alcuni secondi: se lo si facesse a ogni bottiglia,
    quei secondi si sommerebbero all'attesa proprio nel momento peggiore.
    """

    def __init__(self, impostazioni: ImpostazioniVoce | None = None) -> None:
        self.imp = impostazioni or ImpostazioniVoce()
        # Le voci caricate, per nome di modello. Si tengono TUTTE: caricarne una
        # costa quindici secondi su questa board, e un ospite che tocca la
        # bandierina non puo' restare quindici secondi in silenzio a chiedersi
        # se ha rotto qualcosa. Sono sessanta megabyte l'una, su tre giga e
        # mezzo: si pagano una volta e non si ripagano piu'.
        self._voci: dict[str, object] = {}
        self._lock = threading.Lock()
        # Falso quando la lingua a schermo non ha una voce: il racconto si legge
        # ma non si sente. Meglio del silenzio inspiegato, e molto meglio di un
        # motore italiano che prova a leggere l'inglese.
        self.disponibile_per_lingua = True
        # Il flusso verso lo schermo si apre una volta e resta aperto: vedi
        # `Uscita` per il perche'.
        self._uscita: Uscita | None = None
        # Quante volte si e' chiesto silenzio. Serve a chi sta parlando per
        # accorgersi che non lo deve piu' fare: vedi `zittisci` e `parla`.
        self._silenzi = 0
        # Il volume sta QUI, non nell'uscita: si regola anche a flusso ancora
        # chiuso - all'avvio, prima che qualcuno parli - e l'uscita lo legge a
        # ogni pezzo. Una sola verita', nessuna copia da tenere allineata.
        self._volume = VOLUME_PREDEFINITO
        self.guadagno = guadagno_di(self._volume)
        self.cache = CARTELLA_CACHE
        self.cache.mkdir(parents=True, exist_ok=True)
        self.ripara_cache()

    # -------------------------------------------------------------- motore

    def _carica(self, modello: str | None = None):
        nome = modello or self.imp.modello
        if (gia := self._voci.get(nome)) is not None:
            return gia
        with self._lock:
            if (gia := self._voci.get(nome)) is not None:
                return gia
            try:
                from piper import PiperVoice
            except ImportError as e:  # pragma: no cover
                raise VoceNonDisponibile(
                    "il pacchetto 'piper-tts' non è installato"
                ) from e
            percorso = self._percorso_modello(nome)
            log.info("carico la voce %s", percorso)
            self._voci[nome] = PiperVoice.load(str(percorso))
            return self._voci[nome]

    def uscita(self) -> "Uscita":
        """Il flusso sempre aperto. Si apre alla prima richiesta."""
        with self._lock:
            if self._uscita is None:
                self._uscita = Uscita(self)
        if not self._uscita.aperta:
            self._uscita.avvia()
        return self._uscita

    # -------------------------------------------------------------- volume

    @property
    def volume(self) -> int:
        """Da 0 a 100. A 0 il dispositivo continua a raccontare, in silenzio."""
        return self._volume

    @volume.setter
    def volume(self, valore: int) -> None:
        self._volume = max(0, min(100, int(valore)))
        self.guadagno = guadagno_di(self._volume)
        log.info("volume: %d", self._volume)

    def colpetto(self) -> None:
        """Fa sentire il volume adesso, senza aspettare una bottiglia.

        Non passa dalla sintesi: e' un'onda calcolata, quindi non costa niente
        e non dipende dalla voce caricata, che potrebbe non esserci.
        """
        if self._volume <= 0:
            return
        try:
            self.uscita().scrivi(tocco(frequenza=self.imp.frequenza))
        except Exception as e:                              # noqa: BLE001
            log.warning("colpetto non riuscito: %s", e)

    def scalda(self, lingue: Iterable[str] = ()) -> None:
        """Carica in anticipo le voci delle lingue indicate.

        Va chiamata all'avvio, fuori dal percorso dell'ospite: quindici secondi
        mentre nessuno guarda non li vede nessuno, gli stessi quindici secondi
        dopo un tocco sono un guasto.
        """
        for lingua in (lingue or VOCI):
            modello = VOCI.get(lingua)
            if not modello:
                continue
            try:
                self._carica(modello)
            except VoceNonDisponibile as e:
                log.warning("voce %s non caricata: %s", modello, e)

    def _percorso_modello(self, modello: str | None = None) -> Path:
        nome = modello or self.imp.modello
        for base in (Path.home() / ".local" / "share" / "piper" / "voices",
                     Path.home() / "amelie" / "models",
                     Path("/usr/share/piper-voices")):
            p = base / f"{nome}.onnx"
            if p.exists():
                return p
        raise VoceNonDisponibile(
            f"modello {nome}.onnx non trovato in {Path.home()}/amelie/models. "
            f"Lo scarica scripts/install.sh (passo «Modelli»)"
        )

    @property
    def disponibile(self) -> bool:
        try:
            self._percorso_modello()
            return True
        except VoceNonDisponibile:
            return False

    # --------------------------------------------------------------- cache

    def _chiave(self, frase: str) -> Path:
        h = hashlib.sha256(f"{self.imp.modello}|{frase}".encode()).hexdigest()[:20]
        return self.cache / f"{h}.raw"

    @staticmethod
    def _sano(dati: bytes) -> bool:
        """Un file di cache e' una frase solo se ha campioni interi da 16 bit.

        Uno vuoto, o di lunghezza dispari, e' cio' che resta di uno spegnimento
        arrivato fra la scrittura e il disco.
        """
        return len(dati) > 0 and len(dati) % 2 == 0

    def _dalla_cache(self, percorso: Path) -> bytes | None:
        """Il suono di una frase gia' detta, se il file e' sano.

        Un file rovinato non si legge come buono: `parla` salta le frasi vuote
        senza dire niente, e quella frase sparirebbe per sempre da ogni
        racconto. Si tratta come se mancasse, e la si rifa'.
        """
        try:
            dati = percorso.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            log.warning("frase in cache illeggibile (%s): la rifaccio", e)
            return None
        if not self._sano(dati):
            log.warning("frase in cache rovinata (%d byte): la rifaccio", len(dati))
            return None
        return dati

    def ripara_cache(self) -> int:
        """Toglie dalla cache i file che non sono frasi. Si fa all'avvio.

        `_dalla_cache` li rifarebbe comunque al primo uso; toglierli qui li fa
        comparire nel giornale e lascia la cartella pulita. Restituisce quanti
        ne ha tolti.
        """
        tolti = 0
        try:
            candidati = list(self.cache.glob("*.parziale"))
            candidati += [p for p in self.cache.glob("*.raw")
                          if not p.stat().st_size or p.stat().st_size % 2]
        except OSError as e:
            log.warning("cache della voce non controllata: %s", e)
            return 0
        for p in candidati:
            try:
                p.unlink()
                tolti += 1
            except OSError as e:
                log.warning("file rovinato non tolto dalla cache: %s", e)
        if tolti:
            log.warning("cache della voce: tolti %d file rovinati da uno "
                        "spegnimento, le frasi si rifanno al primo uso", tolti)
        return tolti

    # ------------------------------------------------------------ sintesi

    def sintetizza(self, frase: str) -> bytes:
        """PCM grezzo a 16 bit per una frase. Usa la cache se può.

        Un ristorante ha poche decine di etichette: alla seconda bottiglia
        uguale la voce parte istantaneamente.
        """
        frase = per_la_voce(frase, lingua_del_modello(self.imp.modello))
        if not frase:
            return b""
        percorso = self._chiave(frase)
        if self.imp.usa_cache and (pcm := self._dalla_cache(percorso)):
            return pcm

        voce = self._carica()
        pezzi = [c.audio_int16_bytes for c in voce.synthesize(frase)]
        pcm = b"".join(pezzi)
        if self.imp.usa_cache and pcm:
            try:
                scrivi_durevole(percorso, pcm)
            except OSError as e:
                # Una cache che non si scrive costa solo la prossima sintesi.
                log.warning("frase non salvata in cache: %s", e)
        return pcm

    def apri_uscita(self) -> subprocess.Popen:
        """Un aplay pronto a ricevere PCM grezzo sullo standard input.

        Il buffer ALSA e' tenuto corto di proposito: e' la distanza fra cio' che
        il dispositivo dice di star riproducendo e cio' che l'orecchio sente, e
        quando c'e' un pulsante di pausa quella distanza si nota.
        """
        if not shutil.which("aplay"):
            raise VoceNonDisponibile("aplay non è installato (pacchetto alsa-utils)")
        return subprocess.Popen(
            ["aplay", "-D", self.imp.device_alsa, "-t", "raw", "-f", "S16_LE",
             "-r", str(self.imp.frequenza), "-c", "1", "-q",
             "--buffer-time", str(BUFFER_ALSA_US), "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def parla(self, frasi: Iterable[str], *, su_frase=None) -> None:
        """Pronuncia un flusso di frasi e aspetta che siano uscite davvero.

        Versa nel flusso sempre aperto: non si apre e non si chiude niente, e
        quindi non si pagano i due secondi che il DSP impiega ad avviarsi.

        `su_frase` viene chiamata quando una frase **comincia a sentirsi**, non
        quando la si scrive. Fra le due cose c'e' tutto cio' che e' in viaggio:
        la coda di questa classe, la pipe del sistema - 64 KB, cioe' un secondo
        e mezzo di parlato - e il buffer di ALSA. Agganciata alla scrittura, la
        didascalia comparirebbe uno o due secondi prima della voce.
        """
        uscita = self.uscita()
        # Di quale silenzio siamo figli. Se `zittisci` ne dichiara un altro
        # mentre parliamo, questo discorso e' finito: vedi `zittisci`.
        with self._lock:
            mio = self._silenzi
        for frase in frasi:
            if self._silenzi != mio:
                return
            pcm = self.sintetizza(frase)
            if not pcm:
                continue
            uscita.scrivi(pcm)
            if self._silenzi != mio:
                # Zittiti mentre accodavamo: si butta anche questa, altrimenti
                # esce comunque, dopo lo svuotamento.
                uscita.svuota()
                return
            if su_frase is not None:
                # Si accoda PRIMA e si mostra DOPO: la frase comincia a sentirsi
                # quando manca esattamente la sua durata alla fine della coda.
                # Mostrandola al momento di scriverla si correrebbe avanti di
                # tutto cio' che e' ancora in viaggio - la pipe del sistema da
                # sola tiene un secondo e mezzo di parlato.
                uscita.attendi_residuo(len(pcm) / self._byte_al_secondo())
                try:
                    su_frase(frase)
                except Exception:                           # noqa: BLE001
                    log.exception("errore nella didascalia")
        self._attendi_uscita(uscita)

    def _byte_al_secondo(self) -> int:
        return byte_al_secondo(self.imp.frequenza)

    @staticmethod
    def _attendi_uscita(uscita: "Uscita", tetto_s: float = 120.0) -> None:
        """Delega a `Uscita.attendi_fine`, dove sono i numeri."""
        uscita.attendi_fine(tetto_s)

    def per_lingua(self, codice: str) -> bool:
        """Passa alla voce di quella lingua, se ce n'e' una.

        Restituisce False quando la lingua non ha voce: chi chiama lo sa e puo'
        dirlo a schermo, invece di far leggere l'inglese a un motore italiano -
        che non e' un accento, e' incomprensibile.
        """
        nuovo = VOCI.get(codice)
        if not nuovo:
            log.info("nessuna voce per %r: il racconto resta scritto", codice)
            self.disponibile_per_lingua = False
            return False
        self.disponibile_per_lingua = True
        if nuovo == self.imp.modello:
            return True
        with self._lock:
            # ImpostazioniVoce e' congelato di proposito - e' configurazione,
            # non stato - quindi se ne costruisce uno nuovo invece di mutarlo.
            self.imp = replace(self.imp, modello=nuovo)
        log.info("voce: %s", nuovo)
        return True

    def zittisci(self) -> None:
        """Interrompe qualunque riproduzione in corso.

        Serve quando si toglie la bottiglia mentre il dispositivo parla: deve
        smettere subito, non finire la frase su un tavolo vuoto.

        Si butta via cio' che non e' ancora uscito, e il flusso resta APERTO:
        chiuderlo costerebbe altri due secondi alla prossima parola.

        Ma svuotare la coda NON basta: `parla` cicla sulle frasi, e chi sta
        aspettando spazio per accodare la successiva si sveglierebbe sulla coda
        ora vuota e la farebbe sentire. Un annuncio di lingua e' di DUE frasi:
        zittendolo a meta' si sentirebbe la seconda per intero - due secondi e
        mezzo - sopra la schermata d'invito. Per questo si alza anche un
        contatore: chi sta parlando se ne accorge e smette.
        """
        with self._lock:
            self._silenzi += 1
        if self._uscita is not None:
            self._uscita.svuota()

    def chiudi(self) -> None:
        if self._uscita is not None:
            self._uscita.chiudi()
            self._uscita = None


class VoceNonDisponibile(RuntimeError):
    """Il motore o il modello vocale non ci sono."""


def prepara_cache(voce: Voce, frasi: Iterable[str]) -> int:
    """Pre-sintetizza le frasi fisse: attese, errori, inviti.

    Sono poche e sempre uguali, e pre-generarle toglie l'unico caso in cui il
    dispositivo tace proprio quando dovrebbe rassicurare.
    """
    n = 0
    for f in frasi:
        try:
            if voce.sintetizza(f):
                n += 1
        except VoceNonDisponibile:
            break
    return n


# Le frasi che il dispositivo dice sempre uguali.
FRASI_FISSE = (
    "Un attimo, sto leggendo l'etichetta.",
    "Non riesco a leggere questa etichetta. Prova a girarla verso di me.",
    "Fammi guardare meglio.",
)


# --------------------------------------------------------------- riproduzione


class Riproduttore:
    """Un racconto che si puo' governare: pausa, salto, ricomincia da capo.

    Il problema che risolve non e' far uscire il suono - per quello basta
    `Voce.parla` - ma sapere SEMPRE a che punto si e'. Un testo a schermo che
    avanza a stima, con un `sleep` proporzionale alla lunghezza della frase,
    mentre la voce va per conto suo, regge finche' si va dritti: al primo
    tocco di pausa le due cose divergono e non si riallineano piu'.

    Qui c'e' una sola verita', la POSIZIONE in byte dentro il buffer, e tutto
    si ricava da quella: i secondi trascorsi, la frase da evidenziare, dove
    ripartire dopo una pausa.

    La sintesi corre avanti in un thread suo, perche' la prima frase deve
    poter suonare dopo un paio di secondi, senza aspettare tutto il testo.
    Su questa board la sintesi va a circa il doppio del tempo reale (RTF 0,54),
    quindi dopo la prima frase resta comodamente in vantaggio sulla lettura.
    """

    def __init__(self, voce: "Voce", frasi: list[str], *,
                 su_avanzamento=None) -> None:
        self.voce = voce
        self.frasi = [f for f in frasi if f and f.strip()]
        self.su_avanzamento = su_avanzamento

        self._bps = byte_al_secondo(voce.imp.frequenza)
        self._pcm = bytearray()
        # Offset in byte a cui comincia ogni frase: e' quello che permette di
        # dire QUALE frase si sta ascoltando, invece di indovinarlo.
        self._inizi: list[int] = []
        # Quanto audio produrra' ogni frase, stimato prima di sintetizzarla.
        # E' la CODA del racconto, quella non ancora sintetizzata, a non avere
        # una durata vera: vedi `quota`.
        self._stima = [byte_stimati(f, voce.imp.modello, voce.imp.frequenza)
                       for f in self.frasi]
        # Il pavimento della barra di avanzamento. Non e' una cache: e' cio'
        # che impedisce alla barra di tremare all'indietro quando una stima
        # viene sostituita dalla durata vera. Si riabbassa dove la posizione
        # viene spostata a mano - pausa, salto, da capo - e solo li'.
        self._quota_vista = 0.0
        self._posizione = 0
        self._in_pausa = False
        self._completo = False
        self._errore: Exception | None = None

        # Il flusso e' quello sempre aperto della voce: non se ne apre uno
        # proprio, perche' aprirlo costa i due secondi di avvio del DSP - e
        # dopo ogni pausa e ogni salto si pagherebbero di nuovo.
        self._uscita = voce.uscita()
        self._stato = threading.Lock()
        self._sveglia = threading.Condition(self._stato)
        self._fermo = threading.Event()
        self._finito = threading.Event()
        self._thread: list[threading.Thread] = []

    # ------------------------------------------------------------ lettura

    @property
    def posizione_s(self) -> float:
        return self._posizione / self._bps

    @property
    def durata_s(self) -> float:
        """Quanto c'e' GIA' sintetizzato. Cresce mentre si ascolta.

        NON e' la durata del racconto, e non va usata come denominatore di una
        barra di avanzamento: per quello c'e' `quota`.
        """
        return len(self._pcm) / self._bps

    @property
    def quota(self) -> float:
        """Quanto del racconto INTERO e' stato detto, da 0 a 1.

        Dividere la posizione per `durata_s`, cioe' per i byte gia'
        sintetizzati, fa arretrare la barra a ogni frase nuova: la sintesi
        corre al doppio del tempo reale (RTF 0,54), e per tutta la prima meta'
        del racconto il denominatore cresce quasi al doppio della velocita' del
        numeratore. Dentro una frase il rapporto sale; all'arrivo della frase
        dopo precipita.

        Misurato su un racconto ricomposto da frasi con audio vero, otto frasi
        per 16,8 secondi, quel rapporto da' **sette arretramenti, il peggiore
        di 43,9 punti** - e a due secondi dall'inizio la barra segna gia' il
        56%, perche' con una sola frase sintetizzata la posizione e' quasi
        tutto il buffer.

        Qui il denominatore e' il racconto intero: i byte VERI di cio' che e'
        gia' sintetizzato piu' i byte STIMATI delle sole frasi che mancano.
        L'approssimazione copre quindi solo la CODA, che si accorcia da sola e
        a quel ritmo di sintesi sparisce verso meta' racconto. E quando non
        manca piu' niente il denominatore e' esatto, quindi la barra non puo'
        piu' arrivare a fondo scala mentre c'e' ancora testo da sintetizzare -
        cosa che dividendo per `durata_s` capita in un caso su quattro.

        Resta avanti alla voce di quel tanto che separa cio' che si INVIA
        all'uscita da cio' che l'orecchio sente: circa tre quarti di secondo,
        gli stessi che `attendi_la_coda` esiste per aspettare. Non e' un
        difetto di questa formula, e' la distanza che c'e' in tutto il modulo:
        anche la frase illuminata la ha.

        Il confronto con l'alternativa senza stime - ripartire il racconto sul
        peso in caratteri di ogni frase, denominatore costante dal primo
        istante - misurato contro la verita', cioe' la frazione di audio
        davvero trascorsa, su ottanta racconti, tarando la stima su frasi
        diverse da quelle di prova:

            peso in caratteri    0 arretramenti   scarto mediano 1,1%  peggiore 6,5%
            denominatore misto   0 arretramenti   scarto mediano 0,0%  peggiore 2,8%

        Nessuna delle due arretra; la seconda e' piu' che doppiamente fedele al
        tempo, perche' il numeratore resta la posizione in byte e non il conto
        delle lettere. Ventidue pixel di errore su una barra di 793, invece di
        cinquantadue. Il confronto va fatto con la stessa stima che gira qui,
        `byte_stimati`: con un estimatore diverso i numeri escono migliori di
        quelli veri.

        Il pavimento serve proprio a questa strada: sostituire la stima di una
        frase con la sua durata vera muove il denominatore di qualche punto, e
        senza freno si vedrebbe un tremolio all'indietro a ogni frase. Una
        costante sbagliata puo' quindi falsare il PASSO della barra, mai farla
        tornare indietro.

        Arretra ancora, e deve: `pausa`, `salta` all'indietro e `ricomincia`
        spostano la posizione, ed e' l'unico movimento all'indietro che una
        barra debba fare.
        """
        with self._stato:
            return self._quota()

    def _quota(self) -> float:
        """`quota` col lucchetto gia' preso.

        Il lucchetto non e' zelo: `_posizione`, `_pcm` e `_inizi` li muta il
        thread di sintesi, e qui si combinano. Senza, si puo' leggere `_inizi`
        con una voce in piu' e `_pcm` non ancora esteso.
        """
        reale = len(self._pcm)
        # Quando la sintesi e' finita il totale e' esatto, e questo e' anche
        # cio' che salva il caso in cui si sia ROTTA a meta': `_completo`
        # diventa vero lo stesso, con meno frasi di quelle previste, e il
        # racconto finisce dove e' arrivato. Continuare a contare le frasi mai
        # sintetizzate inchioderebbe la barra a due terzi per sempre.
        totale = reale if self._completo else reale + sum(self._stima[len(self._inizi):])
        if totale <= 0:
            return 0.0
        grezza = min(1.0, max(0.0, self._posizione / totale))
        self._quota_vista = max(self._quota_vista, grezza)
        return self._quota_vista

    @property
    def in_pausa(self) -> bool:
        return self._in_pausa

    @property
    def completo(self) -> bool:
        return self._completo

    @property
    def indice_frase(self) -> int:
        """L'ultima frase cominciata prima della posizione attuale."""
        with self._stato:
            return self._indice_frase()

    def _indice_frase(self) -> int:
        return max(0, bisect.bisect_right(self._inizi, self._posizione) - 1)

    def istantanea(self) -> dict:
        """Lo stato del racconto, tutto letto nello stesso istante.

        Sotto lucchetto perche' `quota` e `frase` si ricavano dalle stesse tre
        variabili che il thread di sintesi sta muovendo: prese in momenti
        diversi potrebbero raccontare due punti diversi del racconto.
        """
        with self._stato:
            return {"posizione": round(self._posizione / self._bps, 2),
                    "durata": round(len(self._pcm) / self._bps, 2),
                    # Tre decimali: la barra e' larga 793 pixel, un millesimo
                    # e' meno di un pixel, e ogni cambio e' animato per un
                    # quarto di secondo. Di piu' sarebbe rumore sul canale.
                    "quota": round(self._quota(), 3),
                    "frase": self._indice_frase(),
                    "in_pausa": self._in_pausa,
                    "completo": self._completo}

    # ------------------------------------------------------------ comandi

    def avvia(self) -> None:
        for bersaglio in (self._sintetizza_tutto, self._suona):
            t = threading.Thread(target=bersaglio, daemon=True)
            t.start()
            self._thread.append(t)

    def pausa(self) -> None:
        # Quello che era gia' stato inviato ma non ancora sentito va
        # riascoltato: riprendere piu' avanti taglierebbe una parola.
        indietro = self._uscita.in_pancia_s() + BUFFER_ALSA_US / 1_000_000
        with self._sveglia:
            if self._in_pausa:
                return
            self._in_pausa = True
            # Allineato al campione. I secondi da riascoltare non sono quasi
            # mai un numero pari di byte - 0,65 s a 22050 Hz sono 28.665 - e
            # la coda e' sempre pari: senza allineare, ogni pausa spostava la
            # ripresa di un byte dispari, e alla ripresa si sentiva fruscio
            # invece della voce, una volta si' e una no.
            self._posizione = allinea(
                max(0, self._posizione - int(self._bps * indietro)))
            # La barra DEVE arretrare: si riavvolge di circa tre quarti di
            # secondo per non tagliare una parola alla ripresa.
            self._quota_vista = 0.0
            self._taci()
            self._sveglia.notify_all()
        self._avvisa()

    def riprendi(self) -> None:
        with self._sveglia:
            if not self._in_pausa:
                return
            self._in_pausa = False
            self._sveglia.notify_all()
        self._avvisa()

    def alterna(self) -> bool:
        """Il tocco sul pulsante centrale. Restituisce True se ora e' in pausa."""
        if self._in_pausa:
            self.riprendi()
        else:
            self.pausa()
        return self._in_pausa

    def salta(self, secondi: float) -> None:
        """Avanti o indietro. Il limite in avanti e' cio' che e' gia' sintetizzato.

        Non e' un difetto ma un fatto: non si puo' saltare dentro un audio che
        non esiste ancora. Con la sintesi al doppio del tempo reale il caso si
        presenta solo nei primissimi secondi.
        """
        with self._sveglia:
            nuovo = self._posizione + int(secondi * self._bps)
            # Allineato al campione, come in `pausa`: un salto di secondi
            # qualunque puo' essere un numero dispari di byte.
            self._posizione = allinea(max(0, min(nuovo, len(self._pcm))))
            self._quota_vista = 0.0       # all'indietro la barra deve seguire
            self._taci()                  # si butta cio' che non e' ancora uscito
            self._sveglia.notify_all()
        self._avvisa()

    def ricomincia(self) -> None:
        with self._sveglia:
            self._posizione = 0
            self._in_pausa = False
            self._quota_vista = 0.0
            self._taci()
            self._sveglia.notify_all()
        self._avvisa()

    def attendi_la_coda(self, tetto_s: float = 10.0) -> None:
        """Aspetta che l'ultimo suono inviato sia stato davvero sentito.

        Va chiamata prima di `ferma()` quando il racconto e' finito da solo.
        `_suona` esce quando l'ultimo pezzo e' stato INVIATO all'uscita, ma
        fra l'invio e l'orecchio ci sono la riserva della coda e la latenza
        di ALSA: tre quarti di secondo abbondanti. `ferma()` li butta via, e
        chiamata subito troncherebbe il racconto mezza parola prima della fine,
        in tutte e due le lingue: non e' la voce, e' la coda.
        """
        self._uscita.attendi_fine(tetto_s)

    def ferma(self) -> None:
        """Basta, e subito: la bottiglia e' stata tolta dal tavolo."""
        self._fermo.set()
        with self._sveglia:
            self._taci()
            self._sveglia.notify_all()

    @property
    def esaurito(self) -> bool:
        """La riproduzione e' finita: i suoi due thread non ci sono piu'.

        Fra la fine e il momento in cui l'orchestratore lascia andare il
        riproduttore passano i tre quarti di secondo che servono all'ultimo
        suono per uscire davvero. In quel mezzo secondo lo schermo mostra
        ancora il racconto e i pulsanti sono accesi, ma qui dentro non c'e' piu'
        nessuno che suoni: un tocco su «indietro» sposterebbe la posizione, e
        la barra tornerebbe indietro e ci resterebbe, perche' nessuno pubblica
        piu' niente. Un pulsante che non puo' fare niente deve dirlo.
        """
        return self._finito.is_set()

    def attendi(self, timeout: float | None = None) -> bool:
        """True se il racconto e' arrivato in fondo, False se l'hanno fermato."""
        self._finito.wait(timeout)
        return self._finito.is_set() and not self._fermo.is_set()

    # ------------------------------------------------------------ interni

    def _avvisa(self) -> None:
        if self.su_avanzamento is None:
            return
        try:
            self.su_avanzamento(self.istantanea())
        except Exception:                                   # noqa: BLE001
            log.exception("errore nell'avviso di avanzamento")

    def _taci(self) -> None:
        """Butta via cio' che e' stato inviato ma non ancora sentito.

        Il flusso NON si chiude: chiuderlo costerebbe due secondi alla
        riapertura, e la ripresa dopo una pausa sarebbe muta per meta'.
        """
        self._uscita.svuota()

    def _sintetizza_tutto(self) -> None:
        try:
            for frase in self.frasi:
                if self._fermo.is_set():
                    return
                pcm = self.voce.sintetizza(frase)
                # Un byte spaiato in fondo a una frase sfaserebbe di mezzo
                # campione tutte quelle dopo: non capita, ma costa niente.
                pcm = pcm[:allinea(len(pcm))]
                with self._sveglia:
                    self._inizi.append(len(self._pcm))
                    self._pcm.extend(pcm)
                    self._sveglia.notify_all()
        except Exception as e:                              # noqa: BLE001
            log.warning("sintesi interrotta: %s", e)
            self._errore = e
        finally:
            with self._sveglia:
                self._completo = True
                self._sveglia.notify_all()

    def _suona(self) -> None:
        pezzo = int(PEZZO_S * self._bps)
        try:
            while not self._fermo.is_set():
                with self._sveglia:
                    # Si aspetta di avere qualcosa da suonare e il permesso di
                    # farlo. Il timeout tiene vivo l'avviso di avanzamento anche
                    # mentre si e' in pausa.
                    while (not self._fermo.is_set()
                           and (self._in_pausa
                                or self._posizione >= len(self._pcm))):
                        if (not self._in_pausa and self._completo
                                and self._posizione >= len(self._pcm)):
                            return                     # arrivati in fondo
                        self._sveglia.wait(0.25)
                    if self._fermo.is_set():
                        return
                    inizio = self._posizione
                    dati = bytes(self._pcm[inizio:inizio + pezzo])

                if not dati:
                    continue
                # Scrivere BLOCCA quando la riserva e' piena, ed e' quello che
                # tiene il passo: non serve un orologio, lo detta ALSA.
                self._uscita.scrivi(dati)
                with self._sveglia:
                    if self._in_pausa or self._fermo.is_set():
                        # Il permesso e' stato tolto mentre si scriveva: si
                        # butta via quel pezzo invece di farlo uscire dopo.
                        self._uscita.svuota()
                        continue
                    if self._posizione == inizio:
                        self._posizione = inizio + len(dati)
                self._avvisa()
        finally:
            self._finito.set()
            self._avvisa()
