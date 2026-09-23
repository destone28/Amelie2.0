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

- **Ridurre `limit_side_len` non riduceva niente.** Per un anno il parametro è
  stato girato da 736 a 160 senza che il tempo cambiasse di un millesimo, e il
  motivo sta nel pacchetto: con `limit_type="min"` il ridimensionamento
  interviene solo `if min(h, w) < limit_side_len`, cioè **solo per ingrandire**.
  Un ritaglio 756x1824 ha il lato corto già sopra qualunque soglia, e arrivava
  alla rete intero. Misurato: 3960 ms, identici a 736 e a 160.

Da lì la forma attuale, che è **in due fasi** e vale quattro secondi:

1. **si trova** dove sta il testo su un'immagine che rimpiccioliamo NOI, perché
   il costo del rilevatore va col numero di pixel: 2835 ms a 768x1824, 198 ms a
   192x480, sulla stessa rete;
2. **si legge** ogni riga ritagliata dall'immagine GRANDE. Il riconoscitore
   normalizza ogni ritaglio a 48 pixel d'altezza, quindi il suo costo non
   dipende dalla risoluzione di partenza: si può cercare sul piccolo e leggere
   sul grande senza pagare niente.

Misurato sul dispositivo, stessa etichetta: **3960 ms -> 585 ms**, con le
stesse tre righe lette (`Leggiadro`, `Brut Rosé`, `METODO CLASSICO`).

Due trappole trovate per strada, e vanno ricordate perché non danno errore:

- **I parametri si danno alla costruzione, mai alla chiamata.** Passare
  `box_thresh` o `unclip_ratio` a `motore(...)` fa ricostruire il motore a ogni
  fotogramma: 585 ms diventano 1240, e non c'è nessun avviso.
- **La larghezza dei ritagli non ha un tetto suo.** Una riga lunga diventa un
  ingresso lungo, e una sola riga di didascalia costava quanto tutta
  l'etichetta. Qui si normalizza a mano prima di leggere.

Il classificatore di orientamento è disattivato: la camera ora è montata di
lato e il fotogramma si raddrizza a monte, quindi sul supporto l'etichetta
arriva dritta, e ogni riga risparmiata è tempo guadagnato su un Cortex-A53.
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
    # Si chiamava `lato_massimo` e non era un massimo: finiva in
    # `Det.limit_side_len` che con `limit_type="min"` è un MINIMO, e serviva
    # solo a ingrandire. Il nome nuovo dice quello che il numero fa davvero.
    #
    # 320 è misurato, non scelto. Sotto, il rilevatore comincia a sbagliare le
    # lettere - a 224 la stessa etichetta dà `SERARUOLS` dove a 320 dà
    # `CERASUOLO` - e sopra costa e basta:
    #
    #     224   trova in 110 ms   `CERARUOLO` `SEARRUZZO`
    #     320   trova in 274 ms   `CERASUOLO` `DABRUZZO`
    #     756   trova in 2835 ms  le stesse due righe
    #
    # Quel «sopra costa e basta» veniva da UN'etichetta. Sulle 139 vere, con
    # l'OCR della board, non e' cosi':
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
    # E' stato provato anche a pagarli solo «quando serve» - un secondo colpo
    # da vicino se il primo raccoglieva poco - e non serve a niente: un
    # etichetta che si legge da' quasi sempre le tre parole che bastano, il
    # secondo colpo non scatta mai, e la misura e' identica a 320 fino
    # all'ultima cifra. Meglio un numero solo, misurato.
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
    # provato ad allargare fino a 2,5 per recuperare le prime lettere mangiate
    # («OSECCO» per PROSECCO), e non serviva - a 320 il riquadro è già giusto,
    # era la risoluzione a mancare.
    soglia_riquadro: float = 0.5
    allargamento: float = 1.5

    # Le reti piccole invece di quelle normali.
    #
    # Misurato sulla stessa etichetta, dopo aver sistemato tutto il resto:
    #
    #     PP-OCRv5 mobile   trova 381 ms   legge 786 ms
    #     PP-OCRv6 small    trova 374 ms   legge 905 ms
    #     PP-OCRv6 tiny     trova 261 ms   legge 255 ms
    #
    # Le tre righe lette sono le stesse. Il dizionario non c'entra: provato a
    # sostituire il riconoscitore cinese - seimila ideogrammi nell'ultimo
    # strato - con quello latino, e si risparmiavano sessanta millesimi su
    # seicentonovanta. È la taglia della rete, non l'alfabeto.
    reti_piccole: bool = True

    # Quante parole utili bastano per non provare altri versi del fotogramma.
    # Tre è il minimo che sull'etichetta vera ha dato un riconoscimento:
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
    # secondo non recupera niente - la lettura buona era gia' la prima, e il
    # vino e' stato riconosciuto lo stesso. Una parola sola non e' una lettura,
    # e' un frammento, e un frammento e' proprio cio' che da' un verso
    # sbagliato.
    parole_che_sono_una_lettura: int = 2

    # Oltre quante righe si smette di cercare un verso migliore. Un'etichetta
    # letta bene ne da' tre o cinque, un verso sbagliato una o tre: sopra otto
    # non si sta guardando un'etichetta, si sta guardando una stanza.
    righe_che_bastano: int = 8

    # Il classificatore di orientamento. Era spento, poi acceso, ora di nuovo
    # spento - e le tre volte per ragioni diverse, che vale la pena distinguere.
    #
    # Era spento con la motivazione che la bottiglia sta in piedi e il testo non
    # può essere capovolto.
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
    # storto. Non era un costo, era un risparmio.
    #
    # Quella misura è stata presa con la camera montata orizzontale. Ora la
    # camera è montata di lato e il fotogramma si raddrizza in `capture`: il
    # testo arriva già dritto, e il classificatore non ha più niente da
    # raddrizzare. Rimesso a spento e verificato che si legga lo stesso -
    # `Leggiadro`, `Brut Rosé`, `METODO CLASSICO` con e senza.
    #
    # Resta acceso come opzione, e resta collegato: se un giorno la camera
    # tornasse dritta, basta questo campo.
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
        riconoscere. Contarle come una lettura riuscita azzerava i tentativi,
        e il dispositivo scandiva ogni sei secondi per sempre - visto sul
        dispositivo, con carico a 3, davanti a un piatto vuoto.
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

    def leggi(self, immagine) -> Lettura:
        """Legge un'immagine **BGR nativa**, non convertita in grigio."""
        motore = self._carica()
        inizio = time.perf_counter()
        trovate = self._trova_e_leggi(motore, immagine)
        durata = time.perf_counter() - inizio

        righe = [r for r in trovate if self._tieni(r)]
        log.debug("OCR: %d righe utili in %.2f s", len(righe), durata)
        return Lettura(righe=righe, durata_s=durata)

    def _trova_e_leggi(self, motore, immagine) -> list[Riga]:
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
        scala = self.imp.lato_rilevatore / max(1, min(immagine.shape[:2]))
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
        # meno righe. Confonderli ha gia' fatto perdere un anno - vedi la
        # premessa del modulo.
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

    def _normalizza_riga(self, ritaglio):
        """Una riga portata all'altezza di lettura, con un tetto alla larghezza.

        Il tetto è la parte che il pacchetto non mette: lì la larghezza segue il
        rapporto del ritaglio senza limiti, e una didascalia lunga costava da
        sola quanto tutta l'etichetta. Tagliata a 320 si legge uguale - stesso
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
            # contro le tre che bastano per fermarsi, e il ripiego girava tre
            # volte per 4,6 secondi - per poi tenere comunque la prima lettura,
            # che era gia' quella che ha fatto riconoscere il vino.
            return migliore
        if not _c_e_una_lettera(migliore):
            # Righe, ma nemmeno una lettera: numeri e frammenti. Girare il
            # fotogramma non ci scriverà parole che non ci sono.
            #
            # Misurato sul dispositivo, piatto vuoto e un calendario dietro:
            # l'OCR legge `20 21 19 22 24`, nessuna di queste conta come parola
            # utile, e il ripiego girava tre volte per **5,7 secondi** su una
            # scena senza etichette. Un verso sbagliato non dà cifre, dà
            # spazzatura fatta di lettere — `D'ABRUZZC`, `3IMER · DRZZZO` —
            # ed è su quella che vale la pena riprovare.
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
        # Il tempo dichiarato e' quello di TUTTO, non dell'ultimo giro.
        #
        # Non e' una finezza: a giornale comparivano «1,1 s» per una lettura
        # che ne era costati 4,6, perche' `durata_s` era quella della `leggi`
        # che aveva vinto. Il costo del ripiego era invisibile proprio a chi
        # doveva accorgersene.
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
