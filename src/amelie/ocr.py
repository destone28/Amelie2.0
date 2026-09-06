"""Lettura dell'etichetta.

Tesseract è l'attrezzo sbagliato per questo problema: presuppone testo piano e
raddrizzato, mentre un'etichetta avvolta su un cilindro ha righe che curvano e
caratteri progressivamente ruotati. Si usa **RapidOCR** (modelli PP-OCR su ONNX
Runtime): il rilevatore restituisce un quadrilatero per ogni riga e lo rettifica
prospetticamente prima di leggerlo, quindi la curvatura e lo scorcio spariscono
nella rettifica invece di dover essere corretti a monte.

Due decisioni contro-intuitive, entrambe misurate:

- **Si passa l'immagine a colori nativa**, non un canale singolo. L'idea di
  usare il canale blu (perché su etichetta rossa con testo bianco il rosso è
  saturo) si è rivelata sbagliata: su etichetta oro su rosso scuro — combinazione
  comunissima nei vini italiani di fascia alta — il canale blu produce **zero
  rilevamenti**, perché oro e rosso scuro riflettono entrambi poco blu. I
  modelli PP-OCR sono addestrati su tre canali e un canale replicato è un
  ingresso fuori distribuzione.

- **Il collo di bottiglia non è la rete**: i due terzi del tempo se ne vanno in
  pre e post-processing Python/OpenCV, che è mono-thread. Prima di cambiare
  modello conviene ridurre `limit_side_len` e passare un ritaglio invece del
  fotogramma intero.

Il classificatore di orientamento è disattivato: sul supporto l'etichetta è
sempre dritta, e ogni riga risparmiata è tempo guadagnato su un Cortex-A53.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger(__name__)

RADICE_MODELLI = Path(__file__).resolve().parents[2] / "models"


@dataclass(frozen=True)
class ImpostazioniOCR:
    """Parametri del riconoscimento."""

    # Lato massimo dell'immagine data al rilevatore. Più basso = più veloce e
    # meno sensibile al testo piccolo. 736 è il default di PP-OCR; su A53
    # conviene scendere se il tempo per fotogramma non regge.
    lato_massimo: int = 736

    # Il classificatore di orientamento serve quando il testo può essere
    # capovolto. Qui non può: la bottiglia sta in piedi sul supporto.
    usa_classificatore: bool = False

    # Sotto questa confidenza la riga è quasi sempre rumore (bordi
    # dell'etichetta, riflessi, texture della carta).
    confidenza_minima: float = 0.55

    # Righe più corte di così non portano informazione utile.
    lunghezza_minima: int = 2

    numero_thread: int = 4

    modello_det: Path | None = None
    modello_rec: Path | None = None


@dataclass(frozen=True)
class Riga:
    """Una riga di testo letta dall'etichetta."""

    testo: str
    confidenza: float
    riquadro: tuple[tuple[float, float], ...] = ()

    @cached_property
    def altezza(self) -> float:
        """Altezza del riquadro in pixel: una misura di quanto è grande il testo.

        Serve per pesare le righe: su un'etichetta la denominazione è scritta
        grande, i solfiti sono scritti piccoli.
        """
        if len(self.riquadro) < 3:
            return 0.0
        ys = [p[1] for p in self.riquadro]
        return max(ys) - min(ys)


@dataclass
class Lettura:
    """Il risultato completo su un fotogramma."""

    righe: list[Riga] = field(default_factory=list)
    durata_s: float = 0.0

    @property
    def testo(self) -> str:
        """Tutte le righe, una per riga, nell'ordine di lettura."""
        return "\n".join(r.testo for r in self.righe)

    @property
    def vuota(self) -> bool:
        return not self.righe

    def righe_grandi(self, *, frazione: float = 0.6) -> list[Riga]:
        """Le righe scritte in grande, dove sta la denominazione.

        `frazione` è rispetto all'altezza della riga più grande trovata.
        """
        if not self.righe:
            return []
        massima = max(r.altezza for r in self.righe)
        if massima <= 0:
            return list(self.righe)
        return [r for r in self.righe if r.altezza >= massima * frazione]


class Lettore:
    """Involucro attorno a RapidOCR.

    Il motore si carica alla prima lettura, non alla costruzione: così
    l'oggetto si può creare all'avvio senza pagare subito i secondi di
    inizializzazione di ONNX Runtime, e i test non hanno bisogno del pacchetto.
    """

    def __init__(self, impostazioni: ImpostazioniOCR | None = None) -> None:
        self.imp = impostazioni or ImpostazioniOCR()
        self._motore: Any | None = None

    def _carica(self) -> Any:
        if self._motore is not None:
            return self._motore
        try:
            from rapidocr import RapidOCR  # import pigro: pesa alcuni secondi
        except ImportError as e:  # pragma: no cover - dipende dall'ambiente
            raise OCRNonDisponibile(
                "il pacchetto 'rapidocr' non è installato "
                "(pip install rapidocr onnxruntime)"
            ) from e

        parametri: dict[str, Any] = {
            "Global.use_cls": self.imp.usa_classificatore,
            "Det.limit_side_len": self.imp.lato_massimo,
            "EngineConfig.onnxruntime.intra_op_num_threads": self.imp.numero_thread,
        }
        if self.imp.modello_det:
            parametri["Det.model_path"] = str(self.imp.modello_det)
        if self.imp.modello_rec:
            parametri["Rec.model_path"] = str(self.imp.modello_rec)

        inizio = time.perf_counter()
        self._motore = RapidOCR(params=parametri)
        log.info("motore OCR caricato in %.1f s", time.perf_counter() - inizio)
        return self._motore

    def leggi(self, immagine) -> Lettura:
        """Legge un'immagine **BGR nativa**, non convertita in grigio."""
        motore = self._carica()
        inizio = time.perf_counter()
        grezzo = motore(immagine)
        durata = time.perf_counter() - inizio

        righe = [r for r in _estrai_righe(grezzo) if self._tieni(r)]
        log.debug("OCR: %d righe utili in %.2f s", len(righe), durata)
        return Lettura(righe=righe, durata_s=durata)

    def _tieni(self, r: Riga) -> bool:
        return (
            r.confidenza >= self.imp.confidenza_minima
            and len(r.testo.strip()) >= self.imp.lunghezza_minima
        )


def _estrai_righe(risultato: Any) -> list[Riga]:
    """Normalizza l'uscita di RapidOCR, che è cambiata fra le versioni.

    RapidOCR 3.x restituisce un oggetto con gli attributi `txts`, `scores` e
    `boxes`; le versioni precedenti restituivano una lista di tuple
    `(riquadro, testo, confidenza)`. Si accettano entrambe perché il pacchetto
    installato sulla board potrebbe non essere quello del PC di sviluppo.
    """
    if risultato is None:
        return []

    # Attenzione all'ordine dei controlli: quando RapidOCR non trova nulla
    # restituisce comunque il suo oggetto, ma con txts a None. Senza questo
    # ramo si finiva nel caso "uscita non riconosciuta" e si registrava un
    # avviso a ogni scatto a vuoto - cioe' ogni volta che non c'e' la bottiglia.
    if hasattr(risultato, "txts") and getattr(risultato, "txts") is None:
        return []

    testi = getattr(risultato, "txts", None)
    if testi is not None:
        # Attenzione: `scores` e `boxes` sono array numpy. Un `or` su un array
        # numpy solleva ValueError ("truth value is ambiguous"), quindi il
        # confronto con None deve essere esplicito.
        punteggi = getattr(risultato, "scores", None)
        if punteggi is None:
            punteggi = [1.0] * len(testi)
        riquadri = getattr(risultato, "boxes", None)
        if riquadri is None:
            riquadri = [()] * len(testi)
        return [
            Riga(testo=str(t), confidenza=float(s), riquadro=_riquadro(b))
            for t, s, b in zip(testi, punteggi, riquadri)
        ]

    if isinstance(risultato, Sequence):
        righe = []
        for elemento in risultato:
            if not isinstance(elemento, Sequence) or len(elemento) < 3:
                continue
            riquadro, testo, confidenza = elemento[0], elemento[1], elemento[2]
            righe.append(
                Riga(
                    testo=str(testo),
                    confidenza=float(confidenza),
                    riquadro=_riquadro(riquadro),
                )
            )
        return righe

    log.warning("uscita OCR non riconosciuta: %r", type(risultato))
    return []


def _riquadro(b: Any) -> tuple[tuple[float, float], ...]:
    if b is None:
        return ()
    try:
        return tuple((float(p[0]), float(p[1])) for p in b)
    except (TypeError, IndexError, ValueError):
        return ()


class OCRNonDisponibile(RuntimeError):
    """Il motore OCR non si può caricare."""
