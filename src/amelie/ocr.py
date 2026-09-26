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
  saturo) è sbagliata: su etichetta oro su rosso scuro — combinazione
  comunissima nei vini italiani di fascia alta — il canale blu produce **zero
  rilevamenti**, perché oro e rosso scuro riflettono entrambi poco blu. I
  modelli PP-OCR sono addestrati su tre canali e un canale replicato è un
  ingresso fuori distribuzione.

- **Ridurre `limit_side_len` non riduce niente.** Il motivo sta nel
  pacchetto: con `limit_type="min"` il ridimensionamento interviene solo
  `if min(h, w) < limit_side_len`, cioè **solo per ingrandire**. Un ritaglio
  756x1824 ha il lato corto già sopra qualunque soglia, e arriva alla rete
  intero. Misurato: 3960 ms, identici con 736 e con 160.

Per questo la lettura è **in due fasi**:

1. **si trova** dove sta il testo su un'immagine che rimpiccioliamo NOI, perché
   il costo del rilevatore va col numero di pixel: 2835 ms a 768x1824, 198 ms a
   192x480, sulla stessa rete;
2. **si legge** ogni riga ritagliata dall'immagine GRANDE. Il riconoscitore
   normalizza ogni ritaglio a 48 pixel d'altezza, quindi il suo costo non
   dipende dalla risoluzione di partenza: si può cercare sul piccolo e leggere
   sul grande senza pagare niente.

Misurato sul dispositivo, stessa etichetta: **3960 ms in una fase, 585 ms in
due**, con le stesse tre righe lette (`Leggiadro`, `Brut Rosé`, `METODO CLASSICO`).

Due trappole, da ricordare perché non danno errore:

- **I parametri si danno alla costruzione, mai alla chiamata.** Passare
  `box_thresh` o `unclip_ratio` a `motore(...)` fa ricostruire il motore a ogni
  fotogramma: 585 ms diventano 1240, e non c'è nessun avviso.
- **La larghezza dei ritagli non ha un tetto suo.** Una riga lunga diventa un
  ingresso lungo, e una sola riga di didascalia costava quanto tutta
  l'etichetta. Qui si normalizza a mano prima di leggere.

Il classificatore di orientamento è disattivato: la camera è montata di lato e
il fotogramma si raddrizza a monte, quindi l'etichetta arriva dritta, e ogni
riga risparmiata è tempo guadagnato su un Cortex-A53.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

RADICE_MODELLI = Path(__file__).resolve().parents[2] / "models"


@dataclass(frozen=True)
class ImpostazioniOCR:
    """Parametri del riconoscimento."""

    # Lato corto a cui si riduce l'immagine PRIMA di cercarci dentro il testo.
    #
    # Il numero e' misurato, non scelto. Sotto 320 il rilevatore comincia a
    # sbagliare le lettere - a 224 la stessa etichetta dà `SERARUOLS` dove a
    # 320 dà `CERASUOLO` - e sopra, a guardare UN'etichetta, costa e basta:
    #
    #     224   trova in 110 ms   `CERARUOLO` `SEARRUZZO`
    #     320   trova in 274 ms   `CERASUOLO` `DABRUZZO`
    #     756   trova in 2835 ms  le stesse due righe
    #
    # Sulle 139 etichette vere, con l'OCR della board, non e' cosi':
    #
    #                    cantina letta   nome letto   riconoscimento   tempo
    #     lato 320          112/139        72/139         87,1%        1,02 s
    #     lato 480          114/139        74/139         90,6%        1,32 s
    #
    # Trenta centesimi per tre punti e mezzo di riconoscimento, e i casi
    # «sbagliato E dichiarato certo» restano zero in tutti e due. Su una
    # bottiglia vera la differenza si vede a occhio: a 320 `APADOSEN · PALAMA
    # · SALENTO`, a 480 `PALAMÀ · NECROAMARO · VINICOLA L SALENTO`.
    #
    # Piu' su si torna a peggiorare: a 960 la stessa etichetta da' `PALAMA ·
    # VINICOLANLSALENTO`, con le parole incollate e il vitigno perso. Il
    # rilevatore ha una scala sua, e piu' pixel non vuol dire meglio.
    #
    # Pagarli solo «quando serve» - un secondo colpo da vicino se il primo
    # raccoglie poco - non serve a niente: un'etichetta che si legge da' quasi
    # sempre le tre parole che bastano, il secondo colpo non scatta mai, e la
    # misura e' identica a 320 fino all'ultima cifra. Meglio un numero solo,
    # misurato.
    lato_rilevatore: int = 480

    # Quante righe si leggono, delle tante che il rilevatore trova.
    #
    # Ogni riga costa 40 ms, e una parete dietro la bottiglia ne produce
    # trentotto. Si tengono le più ALTE: su un'etichetta la denominazione è
    # scritta grande e i solfiti sono scritti piccoli, e il tempo va speso dove
    # c'è il nome.
    righe_massime: int = 10

    # L'altezza a cui si normalizza ogni riga prima di leggerla, e il tetto
    # alla sua larghezza. È quello che il riconoscitore farebbe da sé, tranne
    # che per il tetto: senza, una riga lunga diventa un ingresso lungo e costa
    # da sola quanto tutta l'etichetta.
    altezza_riga: int = 48
    larghezza_riga: int = 320

    # Quanto deve essere sicura una regione per diventare una riga, e di quanto
    # si allarga il riquadro prima di ritagliarlo. Sono i default di PP-OCR:
    # allargare fino a 2,5 per recuperare le prime lettere mangiate («OSECCO»
    # per PROSECCO) non serve - il riquadro è già giusto, quello che manca in
    # quei casi è la risoluzione.
    soglia_riquadro: float = 0.5
    allargamento: float = 1.5

    # Le reti piccole invece di quelle normali.
    #
    # Misurato sulla stessa etichetta, a parità di tutto il resto:
    #
    #     PP-OCRv5 mobile   trova 381 ms   legge 786 ms
    #     PP-OCRv6 small    trova 374 ms   legge 905 ms
    #     PP-OCRv6 tiny     trova 261 ms   legge 255 ms
    #
    # Le tre righe lette sono le stesse. Il dizionario non c'entra:
    # sostituendo il riconoscitore cinese - seimila ideogrammi nell'ultimo
    # strato - con quello latino si risparmiano sessanta millesimi su
    # seicentonovanta. È la taglia della rete, non l'alfabeto.
    reti_piccole: bool = True

    # Quante parole utili bastano per non provare altri versi del fotogramma.
    # Tre è il minimo che sull'etichetta vera basta a un riconoscimento:
    # «ULISS CERASUOLO D'ABRUZZO». Con meno, girare costa qualche secondo e
    # può far passare il dispositivo dal non riconoscere niente al
    # riconoscere.
    parole_che_bastano: int = 3

    # Sotto quante parole utili vale la pena provare a girare il fotogramma.
    #
    # Due, ed e' il confine fra i due casi misurati sul dispositivo:
    #
    #     camera montata storta   `D'ABRUZZC`                        1 parola
    #     etichetta letta a meta' `1930 | Brunello | Affinato inboti` 2 parole
    #
    # Nel primo caso girare recupera tutto e vale i secondi che costa; nel
    # secondo non recupera niente - la lettura buona e' gia' la prima, e il
    # vino si riconosce lo stesso. Una parola sola non e' una lettura,
    # e' un frammento, e un frammento e' proprio cio' che da' un verso
    # sbagliato.
    parole_che_sono_una_lettura: int = 2

    # Oltre quante righe si smette di cercare un verso migliore. Un'etichetta
    # letta bene ne da' tre o cinque, un verso sbagliato una o tre: sopra otto
    # non si sta guardando un'etichetta, si sta guardando una stanza.
    righe_che_bastano: int = 8

    # Il classificatore di orientamento. Spento, perché la camera è montata
    # di lato e il fotogramma si raddrizza in `capture`: il testo arriva già
    # dritto, e il classificatore non ha niente da raddrizzare. Con e senza si
    # legge lo stesso - `Leggiadro`, `Brut Rosé`, `METODO CLASSICO`.
    #
    # Non è spento perché «la bottiglia sta in piedi e il testo non può essere
    # capovolto»: con la camera montata dritta quella premessa è falsa, e
    # spegnerlo costa quasi tutto. Su una bottiglia il testo dell'etichetta
    # non è quasi mai orizzontale nel fotogramma: la bottiglia è cilindrica e
    # appoggiata, la camera la guarda dal basso e di sbieco, e su un'etichetta
    # come «NERO D'AVOLA / SICILIA» scritta lungo l'asse il testo arriva
    # ruotato di novanta gradi.
    #
    # Misurato con la camera montata dritta, sugli stessi tre scatti:
    #
    #     spento    `DOLA | SILIA | NER`        vitigno, 61   6,6 s
    #     acceso    `D'AVOLA | SICILIA | NERO`  tipologia, 87 4,9 s
    #
    # Più accurato **e** più veloce: il classificatore raddrizza il ritaglio
    # prima di riconoscerlo, e un ritaglio dritto si legge meglio e prima di uno
    # storto. Lì non è un costo, è un risparmio.
    #
    # Resta collegato: con la camera montata dritta basta accendere questo
    # campo.
    usa_classificatore: bool = False

    # Sotto questa confidenza la riga è quasi sempre rumore (bordi
    # dell'etichetta, riflessi, texture della carta).
    confidenza_minima: float = 0.55

    # Righe più corte di così non portano informazione utile.
    lunghezza_minima: int = 2

    numero_thread: int = 4

    # Il contrasto si normalizza prima di leggere (CLAHE sulla luminanza).
    #
    # Misurato sul dispositivo su tre scatti della stessa etichetta, ognuno
    # portato a cinque livelli di luce - da una media di 34 su 255 a una di
    # 169 - contando le parole lette con e senza:
    #
    #     buio forte   3 contro 3      normale   5 contro 8
    #     buio         7 contro 7      chiaro    2 contro 2
    #                                  bruciato  0 contro 3
    #
    # Non perde mai e guadagna dove la luce e' troppa o troppo poca, che sono
    # i casi in cui la posa da sola non arriva. Costa trenta millesimi su un
    # ritaglio da due megapixel.
    normalizza_contrasto: bool = True

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

    @property
    def utile(self) -> bool:
        """C'e' almeno una PAROLA, non solo cifre e frammenti?

        E' la lettura che conta come lettura. Un calendario dietro al piatto
        da' cinque righe di numeri a ogni scatto: righe, ma niente da
        riconoscere. Contarle come una lettura riuscita azzererebbe i
        tentativi, e davanti a un piatto vuoto il dispositivo scandirebbe ogni
        sei secondi per sempre, con il carico a 3.
        """
        return _parole_utili(self) > 0

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

        # Tutto qui, e niente alla chiamata: passare anche un solo parametro a
        # `motore(...)` fa ricostruire il motore a ogni fotogramma. Misurato,
        # 585 ms contro 1240, senza nessun avviso.
        parametri: dict[str, Any] = {
            "Global.use_cls": self.imp.usa_classificatore,
            # L'immagine la rimpiccioliamo noi, prima: qui si dice al pacchetto
            # di non rimetterci le mani. Il lato corto che gli arriva è già
            # quello che vogliamo, e `limit_type="min"` con la stessa soglia
            # lascia il rapporto a uno.
            "Det.limit_type": "min",
            "Det.limit_side_len": self.imp.lato_rilevatore,
            "Det.box_thresh": self.imp.soglia_riquadro,
            "Det.unclip_ratio": self.imp.allargamento,
            "EngineConfig.onnxruntime.intra_op_num_threads": self.imp.numero_thread,
        }
        if self.imp.reti_piccole:
            from rapidocr.utils.typings import ModelType, OCRVersion

            v6, tiny = OCRVersion("PP-OCRv6"), ModelType("tiny")
            parametri |= {"Det.ocr_version": v6, "Det.model_type": tiny,
                          "Rec.ocr_version": v6, "Rec.model_type": tiny}
        if self.imp.modello_det:
            parametri["Det.model_path"] = str(self.imp.modello_det)
        if self.imp.modello_rec:
            parametri["Rec.model_path"] = str(self.imp.modello_rec)

        inizio = time.perf_counter()
        self._motore = RapidOCR(params=parametri)
        log.info("motore OCR caricato in %.1f s", time.perf_counter() - inizio)
        return self._motore

    def leggi(self, immagine, *, scala: float | None = None) -> Lettura:
        """Legge un'immagine **BGR nativa**, non convertita in grigio.

        `scala` e' quanto rimpicciolire l'immagine per il rilevatore. Di solito
        la decide `lato_rilevatore`; la da' chi rilegge un pezzo di un'immagine
        gia' letta, perche' il pezzo va guardato alla stessa scala del tutto.
        """
        motore = self._carica()
        inizio = time.perf_counter()
        trovate = self._trova_e_leggi(motore, immagine, scala)
        durata = time.perf_counter() - inizio

        righe = [r for r in trovate if self._tieni(r)]
        log.debug("OCR: %d righe utili in %.2f s", len(righe), durata)
        return Lettura(righe=righe, durata_s=durata)

    def _trova_e_leggi(self, motore, immagine, scala: float | None = None) -> list[Riga]:
        """Le due fasi: si cerca sul piccolo, si legge sul grande.

        Il rilevatore costa in proporzione ai pixel - 2835 ms a 768x1824, 198 ms
        a 192x480 - mentre il riconoscitore normalizza ogni ritaglio a
        un'altezza fissa e non sa nemmeno da che immagine venga. Separarli
        vuol dire pagare la risoluzione solo dove pesa, e tenerla dove serve.
        """
        import cv2
        import numpy as np
        from rapidocr.utils.process_img import get_rotate_crop_image

        if self.imp.normalizza_contrasto:
            immagine = _contrasto_normalizzato(immagine)
        if scala is None:
            scala = self._scala(immagine)
        if scala < 1.0:
            piccola = cv2.resize(
                immagine,
                (max(1, int(immagine.shape[1] * scala)),
                 max(1, int(immagine.shape[0] * scala))),
                interpolation=cv2.INTER_AREA)
        else:
            piccola, scala = immagine, 1.0

        inizio = time.perf_counter()
        trovato = motore(piccola, use_det=True, use_cls=False, use_rec=False)
        trovate_in = time.perf_counter() - inizio
        riquadri = [] if trovato is None or trovato.boxes is None else list(trovato.boxes)
        if not riquadri:
            log.debug("OCR: niente trovato in %.0f ms", trovate_in * 1000)
            return []
        # Le righe più alte per prime, e poi si taglia: su un'etichetta la
        # denominazione è scritta grande, i solfiti no, e una parete dietro la
        # bottiglia dà trentotto righe da 40 ms l'una.
        riquadri.sort(key=lambda b: -_altezza_del_riquadro(b))
        scelti = riquadri[:self.imp.righe_massime]

        ritagli = [self._normalizza_riga(
            get_rotate_crop_image(immagine, np.array(b, dtype=np.float32) / scala))
            for b in scelti]
        if self.imp.usa_classificatore:
            ritagli, _ = motore.cls_and_rotate(ritagli)
        inizio = time.perf_counter()
        letto = motore.recognize_txt(ritagli)
        # I due numeri separati, perche' si curano in modi diversi: il primo
        # scende abbassando la risoluzione del provino, il secondo leggendo
        # meno righe. Confonderli porta a girare la manopola sbagliata - vedi
        # la premessa del modulo.
        log.info("OCR: %d righe trovate in %.0f ms, %d lette in %.0f ms",
                 len(riquadri), trovate_in * 1000, len(scelti),
                 (time.perf_counter() - inizio) * 1000)

        testi = getattr(letto, "txts", None) or []
        punteggi = getattr(letto, "scores", None)
        if punteggi is None:
            punteggi = [1.0] * len(testi)
        # Il riquadro torna nelle coordinate dell'immagine grande, non in
        # quelle del provino: `Riga.altezza` serve a distinguere il nome
        # scritto grande dalla scritta piccola, e su un'immagine rimpicciolita
        # direbbe un'altra cosa.
        return [Riga(testo=str(t), confidenza=float(c),
                     riquadro=_riquadro(np.array(b, dtype=np.float32) / scala))
                for t, c, b in zip(testi, punteggi, scelti)]

    def _scala(self, immagine) -> float:
        """Quanto si rimpicciolisce un'immagine prima di cercarci il testo."""
        return self.imp.lato_rilevatore / max(1, min(immagine.shape[:2]))

    def allarga(self, lettura: Lettura, intero, posto) -> tuple[Lettura, Any]:
        """Rilegge più largo quando il ritaglio ha tagliato l'etichetta.

        Con le bottiglie tenute in mano davanti alla camera, in più di metà
        delle scansioni il titolo dell'etichetta tocca il bordo del ritaglio.
        «LAMBRUSCO GRASPAROSSA DI CASTELVETRO» arriva all'OCR come «SPAROSSA DI
        CAS», l'Asti come «STI». Il ritaglio c'è per buone ragioni - fuori c'è
        la stanza, e la stanza costa - ma quando una riga di parole ne tocca il
        bordo, il ritaglio ha sbagliato, e il fotogramma intero sta lì accanto.

        Si rilegge il ritaglio allargato fino al bordo del fotogramma, dalla
        parte dove le righe toccano, e alla stessa scala della prima lettura:
        le lettere restano grandi come prima. Rileggere solo la fascia delle
        righe tagliate non conviene: sulla board costa 1,5 s invece di 2,8,
        ma perde le righe rimaste fuori del tutto - «ASTI» sopra
        un «VINO SPUMANTE» che si leggeva - e in simulazione, su 74 scansioni
        vere ristrette apposta, riconosce 15 bottiglie invece di 18.

        Restituisce la lettura completata e l'immagine su cui ora stanno le
        sue righe: il ritaglio allargato, alto come prima. Se non c'era niente
        da allargare, la lettura com'era e `None`.
        """
        if intero is None or posto is None or not lettura.righe:
            return lettura, None
        x0, y0, x1, y1 = posto
        largo_tutto = intero.shape[1]
        bordo = max(4.0, (x1 - x0) * BORDO_CHE_TAGLIA)
        sinistra = destra = False
        tagliate = []
        for r in lettura.righe:
            if len(r.riquadro) < 3 or sum(c.isalpha() for c in r.testo) < LETTERE_DI_UNA_RIGA:
                # Le cifre non si inseguono: un calendario appeso dietro la
                # bottiglia ne mette sempre qualcuna sul bordo.
                continue
            xs = [p[0] for p in r.riquadro]
            a_sinistra = x0 > 0 and min(xs) <= bordo
            a_destra = x1 < largo_tutto and max(xs) >= (x1 - x0) - bordo
            if a_sinistra or a_destra:
                tagliate.append(r)
                sinistra, destra = sinistra or a_sinistra, destra or a_destra
        if not tagliate:
            return lettura, None

        xa = 0 if sinistra else x0
        xb = largo_tutto if destra else x1
        allargata = intero[y0:y1, xa:xb]
        scala = min(1.0, self._scala(intero[y0:y1, x0:x1]))
        nuova = self.leggi(allargata, scala=scala)

        # Le righe di prima nelle coordinate del ritaglio allargato. Si tiene
        # quella che la rilettura non ha ritrovato dentro una delle sue: un
        # pezzo di parola è meglio di nessuna parola.
        rilette = [_confrontabile(r.testo) for r in nuova.righe]
        righe = list(nuova.righe)
        for r in lettura.righe:
            chiave = _confrontabile(r.testo)
            if chiave and any(chiave in n for n in rilette):
                continue
            righe.append(Riga(testo=r.testo, confidenza=r.confidenza,
                              riquadro=tuple((x + x0 - xa, y) for x, y in r.riquadro)))
        log.info("OCR: %d righe toccavano il bordo (%s), riletto %dx%d in %.2f s: %s",
                 len(tagliate),
                 "+".join(n for n, si in (("sinistra", sinistra), ("destra", destra)) if si),
                 xb - xa, y1 - y0, nuova.durata_s,
                 " / ".join(r.testo for r in nuova.righe))
        return (Lettura(righe=righe, durata_s=lettura.durata_s + nuova.durata_s),
                allargata)

    def _normalizza_riga(self, ritaglio):
        """Una riga portata all'altezza di lettura, con un tetto alla larghezza.

        Il tetto è la parte che il pacchetto non mette: lì la larghezza segue il
        rapporto del ritaglio senza limiti, e una didascalia lunga costerebbe
        da sola quanto tutta l'etichetta. Tagliata a 320 si legge uguale - stesso
        testo, misurato riga per riga - e costa come le altre.
        """
        import cv2

        alto, largo = ritaglio.shape[:2]
        if alto < 1 or largo < 1:
            return ritaglio
        quanto = max(8, int(largo * self.imp.altezza_riga / alto))
        return cv2.resize(ritaglio,
                          (min(quanto, self.imp.larghezza_riga), self.imp.altezza_riga),
                          interpolation=cv2.INTER_AREA)

    def leggi_comunque(self, immagine) -> Lettura:
        """Legge, e se il raccolto è povero riprova girando il fotogramma.

        Il verso giusto dipende da come la camera è montata, e un montaggio
        diverso da quello che dice `ImpostazioniCamera.rotazione` basta a
        sbagliarlo. Con la rotazione sbagliata l'OCR non legge quasi niente —
        misurato sulla stessa bottiglia, stesso fotogramma:

            0 gradi     ULISS · CERASUOLO · D'ABRUZZO   -> riconosciuto, 87
            90 gradi    D'ABRUZZC                       -> niente
            180 gradi   3IMER · DRZZZO · CEAVOLO        -> niente
            270 gradi   3引8到3                          -> niente

        Un dispositivo che «non riconosce le bottiglie» può essere solo questo.
        Il parametro si corregge; ma può tornare sbagliato al prossimo
        montaggio, e allora il dispositivo ammutolisce senza dire perché.

        Qui si prova, e si prova solo QUANDO SERVE: se il primo verso dà già
        parole utili non si gira niente e non si paga nulla. Quando invece non
        dà niente, quei secondi in più si stavano per spendere comunque —
        per dire all'ospite di girare l'etichetta.
        """
        import cv2

        inizio = time.perf_counter()
        migliore = self.leggi(immagine)
        if _parole_utili(migliore) >= self.imp.parole_che_bastano:
            return migliore
        if len(migliore.righe) >= self.imp.righe_che_bastano:
            # Tante righe non sono un'etichetta girata male: sono una PARETE.
            # Misurato sul dispositivo con la bottiglia tolta e un calendario
            # dietro: trentotto righe di numeri e **39 secondi** per leggerle,
            # perche' ogni regione trovata passa poi dal modello che la
            # riconosce. Girare il fotogramma altre tre volte vorrebbe dire
            # due minuti e mezzo, e il verso non c'entra niente - qualunque
            # verso, quella parete resta piena di scritte.
            return migliore
        if _parole_utili(migliore) >= self.imp.parole_che_sono_una_lettura:
            # Due parole sono una lettura, anche se non e' completa: il verso
            # e' quello giusto, e quel che manca manca per altri motivi -
            # l'etichetta gira via col vetro, un riflesso, il nome in corsivo.
            # Girare il fotogramma non lo recupera, e costa tre letture intere.
            #
            # Misurato sul dispositivo su «Azienda Agricola Brunello 1930»:
            # letto `1930 | Brunello | Affinato inboti`, due parole utili
            # contro le tre che bastano per fermarsi. Senza questo controllo il
            # ripiego gira tre volte per 4,6 secondi - per poi tenere comunque
            # la prima lettura, che e' gia' quella che fa riconoscere il vino.
            return migliore
        if not _c_e_una_lettera(migliore):
            # Righe, ma nemmeno una lettera: numeri e frammenti. Girare il
            # fotogramma non ci scriverà parole che non ci sono.
            #
            # Misurato sul dispositivo, piatto vuoto e un calendario dietro:
            # l'OCR legge `20 21 19 22 24`, nessuna di queste conta come parola
            # utile, e senza questo controllo il ripiego gira tre volte per
            # **5,7 secondi** su una scena senza etichette. Un verso sbagliato
            # non dà cifre, dà
            # spazzatura fatta di lettere — `D'ABRUZZC`, `3IMER · DRZZZO` —
            # ed è su quella che vale la pena riprovare.
            return migliore
        if migliore.vuota:
            # NIENTE, nemmeno un frammento: davanti alla camera non c'è
            # scritto niente, e girare il fotogramma non ci scriverà nulla.
            # Il verso sbagliato non dà il vuoto, dà spazzatura - misurato:
            # `D'ABRUZZC` a 90 gradi, `3IMER · DRZZZO · CEAVOLO` a 180. Il
            # vuoto è il piatto vuoto, ed è il caso più frequente di tutti:
            # senza questa riga ogni scansione a vuoto costa quattro
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
        # Il tempo dichiarato e' quello di TUTTO, non dell'ultimo giro.
        #
        # Non e' una finezza: con la `durata_s` della sola `leggi` che ha
        # vinto, a giornale comparirebbe «1,1 s» per una lettura costata 4,6,
        # e il costo del ripiego resterebbe invisibile proprio a chi deve
        # accorgersene.
        migliore.durata_s = time.perf_counter() - inizio
        return migliore

    def _tieni(self, r: Riga) -> bool:
        return (
            r.confidenza >= self.imp.confidenza_minima
            and len(r.testo.strip()) >= self.imp.lunghezza_minima
        )


def _contrasto_normalizzato(immagine):
    """CLAHE sulla sola luminanza: il colore resta quello, il contrasto si spalma.

    Sulla luminanza e non sui tre canali: i modelli PP-OCR sono addestrati a
    colori, e toccare i canali uno per uno cambia le tinte - un'etichetta oro
    su rosso scuro diventerebbe un'altra etichetta.
    """
    import cv2

    lab = cv2.cvtColor(immagine, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


# Quanto vicino al bordo del ritaglio deve arrivare una riga per dire che il
# ritaglio l'ha tagliata, in frazione della sua larghezza. Una riga intera ha
# sempre un po' di margine attorno, e il rilevatore lo allarga ancora
# (`allargamento`); una tagliata arriva al pixel.
BORDO_CHE_TAGLIA = 0.03
# Quante lettere deve avere una riga perché valga la pena inseguirla oltre il
# bordo. Due e non tre: una parola tagliata è spesso solo il suo inizio, e
# «ST» sul bordo può essere l'«ASTI» di un'etichetta tenuta di sbieco.
LETTERE_DI_UNA_RIGA = 2


def _confrontabile(testo: str) -> str:
    """Una riga ridotta a lettere e cifre minuscole, per dire se due sono uguali."""
    return "".join(c for c in testo.lower() if c.isalnum())


def _c_e_una_lettera(lettura: "Lettura") -> bool:
    """C'è almeno una lettera in quello che si è letto?

    Distingue «etichetta messa male» da «non c'è nessuna etichetta»: la prima
    dà lettere sbagliate, la seconda dà cifre.
    """
    return any(c.isalpha() for r in lettura.righe for c in r.testo)


def _altezza_del_riquadro(b: Any) -> float:
    """Quanto è alto un riquadro, per decidere quali righe meritano i 40 ms."""
    try:
        ys = [float(p[1]) for p in b]
    except (TypeError, IndexError, ValueError):
        return 0.0
    return max(ys) - min(ys) if ys else 0.0


def _riquadro(b: Any) -> tuple[tuple[float, float], ...]:
    if b is None:
        return ()
    try:
        return tuple((float(p[0]), float(p[1])) for p in b)
    except (TypeError, IndexError, ValueError):
        return ()


class OCRNonDisponibile(RuntimeError):
    """Il motore OCR non si può caricare."""
