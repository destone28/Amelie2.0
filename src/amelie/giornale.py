"""Il giornale di bordo: cosa ha visto il dispositivo, e cosa ne ha concluso.

Quando una bottiglia non viene riconosciuta, il caso sparisce. L'ospite tocca
qualcosa o se ne va, il tavolo dopo arriva con un'altra bottiglia, e chi deve
correggere non sa nemmeno che è successo. Il pulsante «nessuno di questi»
copre il caso in cui qualcuno se ne accorge e lo segnala; questo copre tutti
gli altri, che sono la maggioranza.

Si annota **ogni** scansione, riuscita o no. Una riga per scansione in un file
che si legge da fuori, e accanto il fotogramma vero: senza l'immagine si sa
che ha sbagliato, non perché.

Tre vincoli, tutti e tre per la stessa ragione — questo gira su una board con
memoria flash e nessuno che la sorvegli:

- **le immagini hanno un tetto** e le più vecchie se ne vanno. Centoventi
  scansioni sono una serata intera, e a un quarto di megabyte l'una fanno
  trenta megabyte: si notano sul disco, non si notano sulla vita della flash;
- **il giornale ruota** quando diventa grosso, e se ne tiene una copia sola;
- **niente qui solleva.** Un dispositivo che smette di raccontare vini perché
  non è riuscito a scrivere una riga di diagnostica ha invertito le priorità.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Quante scansioni si tengono in fotografia. Le più vecchie se ne vanno.
IMMAGINI_TENUTE = 120
# Oltre questa taglia il giornale ruota. Con una riga da mezzo chilobyte sono
# circa ottomila scansioni, cioè mesi di servizio.
TAGLIA_MASSIMA = 4 * 1024 * 1024


class Giornale:
    """Annota le scansioni. Non solleva mai, e non blocca mai chi racconta."""

    def __init__(self, cartella: Path, immagini_tenute: int = IMMAGINI_TENUTE) -> None:
        self.cartella = Path(cartella)
        self.immagini_tenute = immagini_tenute

    @property
    def percorso(self) -> Path:
        return self.cartella / "giornale.jsonl"

    def annota(self, voce: dict[str, Any], immagine=None) -> str | None:
        """Scrive una scansione. Restituisce il nome dell'immagine, se c'è."""
        quando = datetime.now()
        voce = {"quando": quando.isoformat(timespec="seconds"), **voce}
        nome = None
        try:
            self.cartella.mkdir(parents=True, exist_ok=True)
            if immagine is not None:
                nome = self._salva_immagine(quando, immagine)
                voce["immagine"] = nome
            self._ruota()
            with open(self.percorso, "a", encoding="utf-8") as f:
                f.write(json.dumps(voce, ensure_ascii=False) + "\n")
        except (OSError, ValueError, TypeError) as e:
            log.warning("giornale non scritto: %s", e)
            return None
        return nome

    def ultime(self, quante: int = 20) -> list[dict[str, Any]]:
        """Le ultime scansioni, la più recente per prima.

        Legge tutto il file: con il tetto di sopra sono pochi megabyte, e
        leggerlo a ritroso a blocchi sarebbe codice in più per un caso che non
        si presenta.
        """
        try:
            righe = self.percorso.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        fuori: list[dict[str, Any]] = []
        for riga in reversed(righe):
            if len(fuori) >= quante:
                break
            riga = riga.strip()
            if not riga:
                continue
            try:
                fuori.append(json.loads(riga))
            except ValueError:
                # Una riga tronca da uno spegnimento a metà scrittura: è
                # l'ultima, si butta, e il resto del giornale resta buono.
                continue
        return fuori

    def immagine(self, nome: str) -> Path | None:
        """Il percorso di un'immagine, se il nome è uno dei nostri.

        Il nome arriva da fuori, e un nome che arriva da fuori non si
        concatena a un percorso senza guardarlo: `../../etc/qualcosa` è un
        nome valido per chiunque non controlli.
        """
        if not nome.endswith(".jpg") or "/" in nome or ".." in nome:
            return None
        percorso = self.cartella / nome
        return percorso if percorso.is_file() else None

    # ------------------------------------------------------------ interni

    def _salva_immagine(self, quando: datetime, immagine) -> str | None:
        import cv2

        nome = quando.strftime("%Y%m%d-%H%M%S-%f")[:-3] + ".jpg"
        if not cv2.imwrite(str(self.cartella / nome), immagine,
                           [cv2.IMWRITE_JPEG_QUALITY, 80]):
            return None
        self._pota()
        return nome

    def _pota(self) -> None:
        immagini = sorted(self.cartella.glob("*.jpg"))
        for vecchia in immagini[: max(0, len(immagini) - self.immagini_tenute)]:
            try:
                vecchia.unlink()
            except OSError:
                pass

    def _ruota(self) -> None:
        try:
            if self.percorso.stat().st_size < TAGLIA_MASSIMA:
                return
        except OSError:
            return
        precedente = self.cartella / "giornale.1.jsonl"
        try:
            os.replace(self.percorso, precedente)
        except OSError as e:
            log.warning("giornale non ruotato: %s", e)
