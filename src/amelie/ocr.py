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

    # Lato massimo dell'immagine data al rilevatore. 736 è il default di PP-OCR.
    #
    # Verrebbe da alzarlo, e sarebbe sbagliato: **misurato** su tre scatti veri
    # della stessa etichetta, 736 legge `D'AVOLA | SICILIA | NERO` in 4,9 s,
    # mentre 1536 legge `AVOLA | SICILIA | (0 | 10 | NERO` in 12,0 s. Più
    # risoluzione ha dato più spazzatura e il doppio del tempo: il modello di
    # riconoscimento lavora su ritagli normalizzati, e il collo di bottiglia
    # non era la risoluzione.
    lato_massimo: int = 736

    # Quante parole utili bastano per non provare altri versi del fotogramma.
    # Tre è il minimo che sull'etichetta vera ha dato un riconoscimento:
    # «ULISS CERASUOLO D'ABRUZZO». Con meno, girare costa qualche secondo e
    # può far passare il dispositivo dal non riconoscere niente al
    # riconoscere.
    parole_che_bastano: int = 3

    # Il classificatore di orientamento. Era spento, con la motivazione che la
    # bottiglia sta in piedi e il testo non può essere capovolto.
    #
    # **La motivazione era sbagliata, e spegnerlo costava quasi tutto.** Su una
    # bottiglia il testo dell'etichetta non è quasi mai orizzontale nel
    # fotogramma: la bottiglia è cilindrica e appoggiata, la camera la guarda
    # dal basso e di sbieco, e su un'etichetta come «NERO D'AVOLA / SICILIA»
    # scritta lungo l'asse il testo arriva ruotato di novanta gradi.
    #
    # Misurato sugli stessi tre scatti:
    #
    #     spento    `DOLA | SILIA | NER`        vitigno, 61   6,6 s
    #     acceso    `D'AVOLA | SICILIA | NERO`  tipologia, 87 4,9 s
    #
    # Più accurato **e** più veloce: il classificatore raddrizza il ritaglio
    # prima di riconoscerlo, e un ritaglio dritto si legge meglio e prima di uno
    # storto. Non è un costo, è un risparmio.
    usa_classificatore: bool = True

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


def _parole_utili(lettura: "Lettura") -> int:
    """Quante righe sono parole, non cifre o frammenti.

    Le cifre non contano: un calendario appeso dietro la bottiglia ne produce
    a decine, e su quelle il riconoscitore non ci fa niente.
    """
    return sum(1 for r in lettura.righe
               if len(r.testo.strip()) >= 3 and not r.testo.strip().isdigit())


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

    def leggi_comunque(self, immagine) -> Lettura:
        """Legge, e se il raccolto è povero riprova girando il fotogramma.

        Il verso giusto dipende da come la camera è montata, e il montaggio
        cambia: sul banco era una cosa, nella scocca stampata un'altra. Con la
        rotazione sbagliata l'OCR non legge quasi niente — misurato sulla
        stessa bottiglia, stesso fotogramma:

            0 gradi     ULISS · CERASUOLO · D'ABRUZZO   -> riconosciuto, 87
            90 gradi    D'ABRUZZC                       -> niente
            180 gradi   3IMER · DRZZZO · CEAVOLO        -> niente
            270 gradi   3引8到3                          -> niente

        Un'ora di dispositivo che «non riconosce le bottiglie» era questo. Si
        può correggere il parametro, e si fa; ma il parametro può tornare
        sbagliato al prossimo montaggio, e allora il dispositivo torna muto
        senza dire perché.

        Qui si prova, e si prova solo QUANDO SERVE: se il primo verso dà già
        parole utili non si gira niente e non si paga nulla. Quando invece non
        dà niente, quei secondi in più si stavano per spendere comunque —
        per dire all'ospite di girare l'etichetta.
        """
        import cv2

        migliore = self.leggi(immagine)
        if _parole_utili(migliore) >= self.imp.parole_che_bastano:
            return migliore
        if migliore.vuota:
            # NIENTE, nemmeno un frammento: davanti alla camera non c'è
            # scritto niente, e girare il fotogramma non ci scriverà nulla.
            # Il verso sbagliato non dà il vuoto, dà spazzatura - misurato:
            # `D'ABRUZZC` a 90 gradi, `3IMER · DRZZZO · CEAVOLO` a 180. Il
            # vuoto è il piatto vuoto, ed è il caso più frequente di tutti:
            # senza questa riga ogni scansione a vuoto costava quattro
            # passaggi di OCR invece di uno, e sul dispositivo sono ventiquattro
            # secondi contro sei - abbastanza da far scadere la scansione e
            # dichiarare un guasto al posto di un piatto vuoto.
            return migliore
        for codice in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180,
                       cv2.ROTATE_90_COUNTERCLOCKWISE):
            altra = self.leggi(cv2.rotate(immagine, codice))
            if _parole_utili(altra) > _parole_utili(migliore):
                migliore = altra
                if _parole_utili(migliore) >= self.imp.parole_che_bastano:
                    break
        return migliore

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
