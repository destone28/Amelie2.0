"""Cattura del fotogramma dell'etichetta.

La geometria è fissa e nota: la lente sta 30 mm sopra il piano d'appoggio, 60 mm
davanti alla bottiglia, con l'asse inclinato di 53° sopra l'orizzonte: le quote
le fissano i pezzi stampati, e il montaggio è in `docs/it/03-montaggio.md`. La
distanza ottica al centro dell'etichetta è ~100 mm e la fascia a fuoco copre una
finestra di circa 60 × 36 mm, che su qualunque etichetta commerciale contiene
produttore, denominazione e annata.

Tre accorgimenti valgono più di qualunque scelta di libreria:

1. **Esposizione bloccata.** Con l'auto-esposizione servono 500-800 ms di
   assestamento dopo l'accensione della luce e i risultati non sono ripetibili.
   Con l'esposizione fissa bastano 120-200 ms. Bottiglia e camera sono entrambe
   ferme: si può permettere un tempo di posa lungo e guadagno a zero, che dà
   **molto più segnale di quanto possano darne i LED**.

   È anche il motivo per cui basta una sola sorgente di luce: l'anello, cioè
   il Modulino Pixels nella torre che illumina l'etichetta attraverso la
   finestra traslucida, sempre con la stessa luce mentre il dispositivo aspetta
   e legge. I LED non sono il fattore dominante — le misure sono in
   `ImpostazioniCamera.esposizione`.

2. **Scartare i primi fotogrammi.** Il buffer UVC contiene immagini prese
   prima che si cominciasse a guardare: il primo fotogramma letto è quasi
   sempre una di quelle. È l'errore più comune nelle pipeline OpenCV.

3. **Raffica e varianza del laplaciano.** Qualche fotogramma, e si tiene il più
   nitido: salva dai casi in cui la bottiglia oscilla ancora.

Il ritaglio centrale limita la distorsione a barile e la vignettatura, che
stanno agli angoli. La frazione è un compromesso, e va nella direzione opposta a
quella che verrebbe da pensare: stringere migliora ogni singolo carattere ma
toglie righe intere, e il riconoscimento lavora su parole, non su caratteri. Vedi
`ImpostazioniCamera.ritaglio_largo`.
"""

from __future__ import annotations

import glob
import logging
import math
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImpostazioniCamera:
    """Parametri della camera. I default valgono per InnoMaker U20CAM-1080P."""

    # NON un percorso fisso. Su questa board l'ordine di /dev/videoN cambia da un
    # avvio all'altro: il codec Venus del SoC si prende volentieri video0 e video1,
    # e la camera finisce piu' in la'. Hardcodare /dev/video0 significa, un avvio
    # su due, fare l'OCR sull'uscita di un decoder video. Si cerca per nome fra i
    # collegamenti stabili di /dev/v4l/by-id.
    nome_camera: str = "U20CAM"
    device: str | None = None          # forza un percorso, scavalcando la ricerca
    larghezza: int = 1920
    altezza: int = 1080
    fourcc: str = "MJPG"

    # Esposizione di partenza, in unità da 100 µs: 900 = 90 ms.
    #
    # **Misurato sul banco** in una stanza in penombra: a 300 non si legge
    # NIENTE, luminosità media 11 su 255 e l'OCR restituisce zero righe. A 900
    # la media sale a 30 e l'etichetta si legge; a 2000 sale a 55.
    #
    # E la luce dell'anello non c'entra quasi niente. Misurato, sempre lì:
    #
    #     anello spento          6,5
    #     anello ambra           7,5
    #     anello bianco          11,3
    #     anello bianco pieno    11,7
    #
    # Cinque livelli su 255 fra spento e acceso al massimo. La posa, invece,
    # triplica il segnale triplicandola: un tempo di posa lungo dà molto più
    # segnale di quanto possano darne i LED, e con una sola sorgente di luce è
    # la posa a decidere.
    #
    # Costa: 90 ms per fotogramma, per i fotogrammi della raffica. Ed è il primo
    # valore da alzare se il locale è buio: dal mirino, con `--esposizione`,
    # senza toccare il codice.
    esposizione: int = 900
    guadagno: int = 0
    temperatura_colore: int = 4600

    # La posa di partenza vale per la stanza in cui si è misurata. In un locale
    # la sera la stanza è un'altra, e la posa giusta cambia con lei: prima di
    # ogni raffica si guarda quanta luce c'è davvero e si corregge.
    #
    # Misurato con il dispositivo montato nella scocca, l'anello bianco e la
    # luce della stanza SPENTA — che è la condizione di un ristorante a cena:
    #
    #      900   luce 47   `` (niente)
    #     1500   luce 62   `` (niente)
    #     2200   luce 76   `ULIEET · TEITLITHE`
    #     3000   luce 88   `ULIGSA · TENUTH · CERASUOLO · D'ABRUZZO`
    #     4000   luce 99   `ULISSE · TENLITA · CERASUOLO · D'ABRUZZO`
    #
    # A 900 — la posa di partenza — non si legge NIENTE. A 3000
    # compare la denominazione, a 4000 anche il nome del produttore, che è
    # quello che decide se il racconto sarà del vino o della cantina.
    #
    # Novanta è il bersaglio, e la tolleranza tiene la banda fra 82 e 98:
    # sotto, la lettura si sfalda («ULIEET · TEITLITHE» a luce 76, e a 80 il
    # nome del produttore comincia a perdersi), sopra si brucerebbe
    # un'etichetta bianca in una sala illuminata.
    luce_cercata: float = 90.0
    luce_tollerata: float = 8.0
    # Quante correzioni al massimo, e quanto è ripida la correzione.
    #
    # La luce NON è proporzionale alla posa: il sensore satura sui punti
    # chiari, e raddoppiare il tempo non raddoppia la media. Misurato su
    # questa camera, stessa scena, quattro pose:
    #
    #      900   luce 47
    #     2000   luce 73
    #     3000   luce 89
    #     4000   luce 99
    #
    # che è `luce ∝ posa^0,54`. Correggere in proporzione diretta, come
    # verrebbe naturale, sottostima ogni volta: da 47 a 90 servirebbero tre
    # giri.
    #
    # L'esponente qui è 1,5 e non 1,85 — cioè meno di quanto la misura
    # chiederebbe — perché quel 0,54 è una proprietà della scena, non solo
    # della camera: una scena senza punti chiari risponde quasi in modo
    # lineare, e la correzione piena la brucerebbe. Con 1,5 si arriva in uno o
    # due giri in tutti e due i casi, senza mai passare oltre.
    ritocchi_posa: int = 3
    esponente_posa: float = 1.5
    # Quanti fotogrammi al massimo si aspetta perché la posa nuova arrivi al
    # sensore. Misurati, sono tre su uno stream letto senza pause; ma nel
    # servizio lo stream sta fermo fra una sbirciata e l'altra, e contarli non
    # basta — vedi `_aspetta_la_posa`, che guarda invece di contare. Otto è il
    # tetto oltre il quale non si sta aspettando, si sta sperando: il caso
    # normale ne consuma cinque, tre di posa vecchia più due che si accordano.
    fotogrammi_di_attesa: int = 8
    # I due estremi entro cui si può andare. Il minimo è dieci millesimi:
    # sotto, le lampade a 50 Hz, che sfarfallano cento volte al secondo,
    # darebbero bande sull'etichetta. Non di più, perché un'etichetta chiara
    # vicino all'anello al massimo si brucia: misurata sul dispositivo, di
    # giorno, luce 174 già a 300. Sopra il massimo la raffica costa più del
    # racconto, e una bottiglia che oscilla viene mossa.
    posa_minima: int = 100
    # NON il massimo della camera. `v4l2-ctl` dice `exposure_time_absolute
    # max=5000`, e in una sala a luci basse la regolazione arriva davvero oltre
    # il 4000. Ma a 5000 la camera SI FERMA: smette di dare fotogrammi, ogni
    # bottiglia diventa un guasto, e riaprire lo stream non la sblocca,
    # perche' ogni riapertura riapplica la stessa posa. Misurato a camera
    # sola, otto fotogrammi per posa: fino a 4900 arrivano (lenti, uno al
    # secondo), a 4999 e a 5000 nessuno in dodici secondi. 4500 lascia un
    # margine; e se su un'altra camera la soglia fosse piu' bassa, vedi
    # `_a_vuoto`.
    posa_massima: int = 4500
    # La posa da cui si riparte quando lo stream resta muto: quella di
    # partenza, che al buio legge poco ma legge.
    posa_sicura: int = 900

    # Raffica: quanti fotogrammi si buttano e quanti se ne guardano. A 90 ms
    # l'uno, cinque e cinque costerebbero quasi un secondo, e la scena è FERMA:
    # bottiglia e camera non si muovono, quindi i fotogrammi si somigliano
    # tutti e tenerne tre invece di cinque non cambia quale si sceglie. Lo
    # scarto serve a buttare via il buffer USB, non a mediare.
    fotogrammi_da_scartare: int = 3
    fotogrammi_raffica: int = 3

    # Il ritaglio, in due frazioni: quanto si tiene in LARGHEZZA e quanto in
    # ALTEZZA. Due, e non una, perché una bottiglia non è quadrata.
    #
    # Con una frazione sola ogni valore è un compromesso sbagliato. Stretta —
    # 0,58, che tiene la distorsione a barile sotto l'1% — le etichette non si
    # riconoscono nemmeno quando sono nitide e ben illuminate, perché cadono
    # fuori le prime e le ultime lettere e il riconoscimento lavora su PAROLE
    # INTERE. Larga — 0,80 o 0,85 — entra la stanza dietro, e la stanza costa
    # cara: il rilevatore trova una regione di testo per ogni numero di un
    # calendario appeso al muro, e ognuna passa poi dal modello che la legge.
    #
    # Con due frazioni il compromesso sparisce, perché i due mestieri stanno su
    # assi diversi: in larghezza si stringe per buttare fuori la parete, in
    # altezza si tiene quasi tutto, perché è lì che sta l'etichetta.
    #
    # MISURATO con la camera in piedi, stessa bottiglia, stesso fotogramma:
    #
    #     1,00 x 1,00   9,7 s   8 righe   `LISE · Leggiadro · Brut Rosé · METODO CLASSICO`
    #     0,85 x 0,85   5,3 s   7 righe   `MOLISE · Leggiadro · ...`
    #     0,80 x 1,00   5,4 s   5 righe   `OLISE · Leggiadro · ...`
    #     0,70 x 0,95   4,3 s   4 righe   `Leggiadro · Brut Rosé · METODO CLASSICO`
    #     0,60 x 0,90   4,2 s   4 righe   `... · METODO CLASSICC`  <- si sfalda
    #
    # A 0,70 sparisce «MOLISE», che non è sulla bottiglia: è il calendario
    # appeso dietro. A 0,60 comincia a sfaldarsi la parola sull'etichetta.
    #
    # Si regolano dal mirino senza toccare il codice: `--ritaglio 0.8`.
    ritaglio_largo: float = 0.70
    ritaglio_alto: float = 0.95

    # Di quanto si allarga ai lati il riquadro trovato sulla bottiglia vera,
    # in frazione della sua larghezza.
    #
    # Si allarga, e non si stringe, anche se il bordo e' dove il vetro curva
    # via e le lettere che stanno li' sembrano perse comunque: con le bottiglie
    # tenute in mano davanti alla camera sono proprio quelle che mancano.
    # Stringendo del 6 %, «GRASPAROSSA DI CASTELVETRO» arriva all'OCR come
    # «SPAROSSA DI CASTEL», e la carta non la riconosce. E la sagoma, con una
    # mano che regge il collo, puo' finire spostata di lato: stringerla vuol
    # dire tagliare l'etichetta due volte.
    #
    # Allargando un poco si lascia all'etichetta il suo bordo. Quello che
    # resta tagliato lo recupera `Lettore.allarga`, che quando una riga di
    # parole tocca il bordo rilegge il ritaglio allargato fino al bordo del
    # fotogramma da quella parte.
    allarga_riquadro: float = 0.08

    # Di quanto ruotare il fotogramma prima di guardarlo, in gradi orari.
    #
    # Novanta, e la camera e' montata di lato apposta: una bottiglia e' alta e
    # stretta, e un sensore 16:9 girato di fianco la inquadra per il lungo. Il
    # fotogramma nativo ha la bottiglia coricata col collo a sinistra; qui si
    # rimette in piedi, e il testo dell'etichetta torna orizzontale.
    #
    # Perche' di lato e non dritta:
    #
    #                    largo    alto     tolleranza laterale
    #     camera dritta   200 mm  112 mm   +-60 mm
    #     camera di lato  112 mm  200 mm   +-18 mm
    #
    # Un'etichetta da vino e' alta un centinaio di millimetri, piu' il
    # collarino: 112 mm di campo verticale non bastano - la denominazione cade
    # sotto il bordo e il dispositivo racconta il vino sbagliato. E i 200 mm
    # di campo orizzontale che si perdono sono campo che si PAGA: e' li' che
    # sta la parete che il rilevatore legge come testo.
    #
    # Un verso sbagliato non degrada la lettura: la annulla. Se questo numero
    # non corrisponde al montaggio, `Lettore.leggi_comunque` prova gli altri
    # versi e il dispositivo continua a leggere, piu' lentamente, invece di
    # ammutolire.
    rotazione: int = 90

    # Quanto si aspetta, a stream appena acceso, prima di buttare i fotogrammi
    # vecchi: il tempo perche' una luce accesa subito prima dello scatto - lo
    # fanno gli script di prova, che la accendono solo per scattare - arrivi
    # sui fotogrammi. Sul dispositivo la luce e' gia' accesa, e l'attesa si
    # paga solo quando lo stream era spento.
    assestamento_luce_s: float = 0.15

    # La fascia del fotogramma dove sta la bottiglia, in frazioni di larghezza.
    #
    # La camera è fissa e la bottiglia arriva sempre nello stesso posto: in
    # piedi, al centro, dal bordo di sopra a quello di sotto. Misurata sul
    # fotogramma vero, occupa da 0,32 a 0,70 della larghezza; qui si tiene un
    # po' più larga perché l'ospite la posa «poco più a destra o a sinistra».
    #
    # Guardare solo questa fascia non è un'ottimizzazione: è la differenza fra
    # accorgersi di una bottiglia e accorgersi di un cameriere che passa.
    fascia_bottiglia: tuple[float, float] = (0.28, 0.72)

    # A quanto si rimpicciolisce la fascia prima di confrontarla.
    #
    # Novantasei per centosettanta: circa un undicesimo di lato. Piccola
    # apposta - a questa scala un tremolio del tavolo sposta la scena di un
    # decimo di pixel e sparisce, mentre una bottiglia resta grande come prima.
    # Largo per alto, e la proporzione e' quella del fotogramma raddrizzato
    # (1080x1920, cioe' 9:16): la sbirciata e' tutto il fotogramma rimpicciolito,
    # e deformarla vorrebbe dire misurare distanze che sull'immagine vera non
    # esistono - serve anche a dire DOVE sta la bottiglia, non solo SE c'e'.
    sbirciata: tuple[int, int] = (96, 170)


@dataclass
class Scatto:
    """Il risultato di una raffica."""

    immagine: np.ndarray                     # BGR, già ritagliata
    nitidezza: float                         # varianza del laplaciano
    scartati: int = 0
    nitidezze: list[float] = field(default_factory=list)
    # Il fotogramma intero, già in piedi, e dove ci sta il ritaglio: (x0, y0,
    # x1, y1) in pixel. Servono a rileggere più largo quando l'etichetta
    # esce dal ritaglio - vedi `Lettore.allarga`. `None` quando lo scatto non
    # viene da una camera vera.
    intero: np.ndarray | None = None
    posto: tuple[int, int, int, int] | None = None

    @property
    def sospetto_mosso(self) -> bool:
        """Vero se anche il fotogramma migliore è poco nitido.

        La soglia è empirica e va ritarata sul campo con l'ottica reale: serve
        a distinguere "bottiglia ancora in movimento" da "etichetta a fuoco".
        """
        return self.nitidezza < SOGLIA_NITIDEZZA


SOGLIA_NITIDEZZA = 40.0

# Di quanto deve muoversi la luce media perché si possa dire che la posa nuova
# è arrivata al sensore. Due livelli su 255: il rumore fra due fotogrammi della
# stessa scena ferma sta sotto mezzo livello, misurato.
SCARTO_DI_POSA = 2.0

# Quanto vecchio può essere un fotogramma e valere ancora come «adesso».
#
# Mezzo secondo: un fotogramma più vecchio di così non è quello che il
# dispositivo avrebbe preso guardando adesso, ed è il tempo entro cui una mano
# che passa davanti alla camera è ancora lì.
FRESCHEZZA_S = 0.5

# Ogni quanto il guardiano guarda quanta luce c'è: in secondi, non in
# fotogrammi. Con le pose lunghe di una sala buia lo stream scende a due
# fotogrammi al secondo, e contando i fotogrammi si ritoccherebbe meno proprio
# quando serve di più. Mezzo secondo: misurare costa quindici millesimi fra
# raddrizzo, ritaglio e conversione in grigio, e una sala che cambia luce - una
# lampada accesa, il sole che cala - si insegue in due o tre passi, prima che
# arrivi la bottiglia.
INTERVALLO_MISURA_S = 0.5

# Il ritocco fa questa parte della strada verso la luce cercata, e il resto al
# passo dopo: la risposta della scena si stima da due punti, ed e' rumorosa.
SMORZAMENTO_POSA = 0.8
# Fra quali estremi si crede alla risposta stimata, `luce ∝ posa^k`. Fuori, la
# stima viene da una scena cambiata fra le due misure, non dalla camera.
ESPONENTE_SCENA_MIN = 0.3
ESPONENTE_SCENA_MAX = 1.6


def posa_verso(imp: "ImpostazioniCamera", posa: int, luce: float,
               precedente: tuple[int, float] | None = None) -> int:
    """La posa nuova: un passo verso la luce cercata.

    La luce non segue la posa sempre allo stesso modo, dipende dalla scena.
    Sul banco `luce ∝ posa^0,54`; sul dispositivo, con un'etichetta chiara
    vicino all'anello, il 20% di posa in piu' ha dato il 30% di luce in piu'.
    Un esponente fisso tarato sul primo caso, nel secondo salterebbe oltre la
    banda buona a ogni passo, avanti e indietro: fra luce 78 e 101, un ritocco
    al secondo per ore.

    Quindi la risposta si misura sulla scena, dagli ultimi due punti, quando la
    posa e' cambiata abbastanza da dire qualcosa; altrimenti vale quella di
    progetto, `1 / esponente_posa`. E il passo si smorza: si fa l'ottanta per
    cento della strada, e il resto al passo dopo.
    """
    k = 1.0 / imp.esponente_posa
    if precedente is not None:
        p0, l0 = precedente
        if p0 > 0 and l0 > 0 and luce > 0 and abs(math.log(posa / p0)) > 0.05:
            stimato = math.log(luce / l0) / math.log(posa / p0)
            if stimato > 0:
                k = min(ESPONENTE_SCENA_MAX, max(ESPONENTE_SCENA_MIN, stimato))
    passo = SMORZAMENTO_POSA * math.log(imp.luce_cercata / max(luce, 1.0)) / k
    nuova = int(round(posa * math.exp(passo)))
    return max(imp.posa_minima, min(imp.posa_massima, nuova))

# Quanto deve essere cambiata una riga o una colonna per contare come sagoma
# della bottiglia. Un pixel isolato è rumore; mezza colonna è un bordo vero.
FRAZIONE_SAGOMA = 0.25
# Sotto queste frazioni del fotogramma la sagoma non è una bottiglia: è una
# macchia. Si torna al riquadro fisso, che è largo e non taglia niente.
LARGHEZZA_MINIMA = 0.12
ALTEZZA_MINIMA = 0.30
# Sopra questa frazione di fotogramma cambiato non c'è nessuna sagoma da
# ritagliare: è cambiata la scena, o la luce, e il riquadro fisso è più sicuro.
SAGOMA_MASSIMA = 0.70


def nitidezza(immagine: np.ndarray) -> float:
    """Varianza del laplaciano: più alta, più l'immagine è a fuoco.

    Si calcola sul grigio perché è una misura di contrasto locale, non di
    colore. Attenzione: il grigio serve *solo* qui. All'OCR va passata
    l'immagine a colori nativa — su etichetta oro su rosso scuro il canale blu
    non rileva nulla e il grigio perde informazione che i modelli PP-OCR,
    addestrati su tre canali, sanno invece usare.
    """
    grigio = cv2.cvtColor(immagine, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grigio, cv2.CV_64F).var())


def ritaglia_centro(immagine: np.ndarray, largo: float,
                    alto: float | None = None) -> np.ndarray:
    """Tiene la porzione centrale del fotogramma.

    Due frazioni, non una, e per una ragione misurata: **una bottiglia non è
    quadrata**. Il ritaglio serve a due mestieri opposti — togliere la
    distorsione ai bordi, che cresce col cubo del raggio, e togliere la stanza,
    che il rilevatore legge come testo — e i due mestieri stanno su assi
    diversi. In larghezza si stringe per buttare fuori la parete; in altezza si
    tiene quasi tutto, perché è lì che sta l'etichetta.

    Con una frazione sola si è costretti a scegliere: stringendo si perde la
    denominazione, allargando entra il calendario. Vedi
    `ImpostazioniCamera.ritaglio_largo`.

    Se `alto` non si dice, vale `largo`: la stessa frazione sui due assi.
    """
    alto = largo if alto is None else alto
    for nome, f in (("largo", largo), ("alto", alto)):
        if not 0 < f <= 1:
            raise ValueError(f"frazione {nome} fuori range: {f}")
    h, w = immagine.shape[:2]
    nh, nw = int(h * alto), int(w * largo)
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    return immagine[y0 : y0 + nh, x0 : x0 + nw]


def quanto_diverso(a: np.ndarray, b: np.ndarray, tolleranza: float = 20.0) -> float:
    """Che frazione della fascia è cambiata, senza farsi ingannare dalla luce.

    Confrontare due fotogrammi pixel per pixel sembra ovvio e non funziona: in
    un locale la luce cambia, e una differenza di luce si presenta come una
    differenza di scena. Misurato sulla fascia vera, abbassando la luce del 20 %
    l'80 % dei pixel cambiava di più di venti livelli — con la scena identica.

    Quindi prima si riporta `b` alla luce di `a` — stessa media, stessa
    deviazione — e solo dopo si contano i pixel diversi. Un cambio di luce è
    proprio una trasformazione di questo tipo, e dopo la normalizzazione
    scompare. Misurato, stessa fascia:

        scena ferma                       0,2 %
        luce ×0,7 · ×0,85 · +40 livelli   0,0-2,2 %
        luce ×1,3                         4,4 %   (qui il bianco satura)
        bottiglia spostata di 2 mm        14,6 %
        bottiglia spostata di 16 mm       53,3 %
        al posto della bottiglia, la stanza   61-75 %

    Fra «la luce è cambiata» e «al posto della bottiglia c'è la stanza» ci sono
    più di quindici volte, ed è lì che sta la soglia.
    """
    if a.shape != b.shape:
        raise ValueError(f"fasce di forma diversa: {a.shape} e {b.shape}")
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    sa, sb = float(a.std()), float(b.std())
    # Una fascia senza contrasto — un muro bianco, il buio pieno — non si può
    # normalizzare senza moltiplicare il rumore per il proprio contrario. Lì
    # l'unica cosa che si può confrontare è quanto è chiara.
    if sa < 1.0 or sb < 1.0:
        return float(abs(a.mean() - b.mean()) > tolleranza)
    b = (b - b.mean()) * (sa / sb) + a.mean()
    return float((np.abs(a - b) > tolleranza).mean())


class PresenzaOttica:
    """Il piatto visto dalla camera: che cosa c'e' davanti, e dove sta.

    Che una bottiglia ci sia lo decide il sensore di distanza (vedi
    `amelie.bridge.Presenza`). Questa classe fa il resto: impara com'e' il
    piatto vuoto e, per differenza, trova la sagoma di cio' che e' arrivato,
    cosi' all'OCR va il riquadro di QUESTA bottiglia invece di uno fisso (vedi
    `riquadro`). Le soglie qui sotto non fanno partire nessuna lettura:
    servono a sapere quando la scena e' tornata il piatto vuoto, per
    aggiornarne lo sfondo, e a non imparare come sfondo una bottiglia.

    Non si riconosce «una bottiglia»: si riconosce che al posto della stanza
    c'è **qualcosa d'altro**. È una distinzione onesta — il dispositivo non sa
    dire se sia una bottiglia o un vaso — e non è un problema, perché chi
    decide davvero è l'OCR subito dopo: se non c'è un'etichetta, non c'è nulla
    da raccontare.

    L'isteresi è **asimmetrica**, come sul sensore: per dire che è arrivata
    basta che la scena sia cambiata; per dire che è andata via bisogna che la
    scena sia tornata quella di prima. Una bottiglia spostata di un dito cambia
    la fascia del 15-30 %, abbastanza da non somigliare più allo sfondo ma non
    abbastanza da somigliargli di nuovo, e resta una bottiglia: finché c'è, lo
    sfondo non si aggiorna.
    """

    def __init__(
        self,
        soglia_arrivo: float = 0.45,
        soglia_uscita: float = 0.20,
        letture_per_arrivare: int = 2,
        letture_per_andarsene: int = 3,
        soglia_fermo: float = 0.20,
        tolleranza: float = 20.0,
        fascia: tuple[float, float] = (0.28, 0.72),
    ) -> None:
        self.soglia_arrivo = soglia_arrivo
        self.soglia_uscita = soglia_uscita
        self.soglia_fermo = soglia_fermo
        self.fascia = fascia
        self.n_arrivo, self.n_uscita = letture_per_arrivare, letture_per_andarsene
        self.tolleranza = tolleranza
        self.presente = False
        self.differenza = 0.0            # l'ultima misura, per la diagnostica
        # Lo sfondo è il fotogramma INTERO com'è quando sul piatto non c'è
        # niente. La striscia centrale — quella su cui si decide — si ricava da
        # qui quando serve: una sola immagine, due domande diverse. `None`
        # vuol dire «non lo so ancora»: all'accensione, finché non arriva la
        # prima sbirciata, e dopo `reimposta` o `c_e_qualcosa`.
        self._sfondo: np.ndarray | None = None
        self._intera: np.ndarray | None = None
        # La scena con la bottiglia, usata solo finché lo sfondo è ignoto.
        self._scena: np.ndarray | None = None
        self._ultima: np.ndarray | None = None
        self._diverse = 0
        self._uguali = 0

    def _centro(self, sbirciata: np.ndarray) -> np.ndarray:
        """La striscia dove sta la bottiglia, ritagliata dalla sbirciata intera.

        La DECISIONE guarda solo qui, e le soglie sono misurate qui: fuori da
        questa striscia c'è la stanza, e un cameriere che passa non deve
        sembrare una bottiglia. Il resto del fotogramma serve a un'altra
        domanda — dove sta la bottiglia — e quella la fa `riquadro`.
        """
        da, a = self.fascia
        w = sbirciata.shape[1]
        return sbirciata[:, int(w * da) : int(w * a)]

    def aggiorna(self, sbirciata: np.ndarray) -> bool:
        """Aggiunge una sbirciata e restituisce se ora la bottiglia c'è."""
        self._intera = sbirciata
        precedente, self._ultima = self._ultima, sbirciata
        if precedente is None:
            if self._sfondo is None and not self.presente:
                self._sfondo = sbirciata
            return self.presente

        # Una scena che si sta ancora muovendo non si giudica: è la mano che
        # posa la bottiglia, e aspettarla costa una sbirciata di ritardo.
        if self._diverso(sbirciata, precedente) >= self.soglia_fermo:
            self._diverse = self._uguali = 0
            return self.presente

        if self._sfondo is None:
            return self._aspetta_che_se_ne_vada(sbirciata)

        self.differenza = self._diverso(sbirciata, self._sfondo)
        if self.differenza >= self.soglia_arrivo:
            self._diverse += 1
            self._uguali = 0
        elif self.differenza < self.soglia_uscita:
            self._uguali += 1
            self._diverse = 0
            if not self.presente:
                # Il piatto è vuoto e si vede: si aggiorna lo sfondo, così la
                # luce che cala nel pomeriggio, la tovaglia cambiata e il
                # calendario girato di pagina non diventano una bottiglia.
                self._sfondo = sbirciata
        else:
            # Fra le due soglie non si cambia idea: è la zona morta.
            self._diverse = self._uguali = 0

        return self._decidi()

    def _decidi(self) -> bool:
        if not self.presente and self._diverse >= self.n_arrivo:
            self.presente = True
        elif self.presente and self._uguali >= self.n_uscita:
            self.presente = False
        return self.presente

    def _aspetta_che_se_ne_vada(self, sbirciata: np.ndarray) -> bool:
        """Il caso in cui non si è mai visto il piatto vuoto.

        Succede dopo `c_e_qualcosa`, che butta lo sfondo imparato perché
        sbagliato: finché la bottiglia non viene tolta non c'è modo di
        conoscerlo. Nel frattempo l'unica cosa che si può riconoscere è il
        momento in cui quella scena cambia del tutto — e cioè quando la
        bottiglia se ne va, lasciando in vista proprio lo sfondo che mancava.
        """
        if self._scena is None:
            self._scena = sbirciata
            return self.presente
        self.differenza = self._diverso(sbirciata, self._scena)
        if self.differenza >= self.soglia_arrivo:
            self.presente = False
            self._sfondo = sbirciata
            self._scena = None
            self._diverse = self._uguali = 0
        return self.presente

    def riquadro(self) -> tuple[float, float, float, float] | None:
        """Dove sta la bottiglia nel fotogramma, in frazioni: (x0, y0, x1, y1).

        È la sua SAGOMA contro lo sfondo imparato: i pixel che sono cambiati
        sono la bottiglia, perché è l'unica cosa che è arrivata. Serve a dare
        all'OCR il riquadro di QUESTA bottiglia invece di un riquadro fisso —
        una renana alta e stretta e una borgognona larga non occupano la stessa
        parte del fotogramma, e un riquadro buono per l'una taglia l'altra o le
        lascia dentro mezza stanza.

        Restituisce `None` ogni volta che la sagoma non è credibile, e chi
        chiama torna al riquadro fisso. Non è prudenza generica: una sagoma
        sbagliata non si vede — taglia l'etichetta e basta.

        Non chiede se la bottiglia «c'è»: a piatto vuoto la maschera è vuota da
        sé, e i controlli qui sotto bastano. Così il mirino può disegnare il
        riquadro vero anche a ciclo fermo, che è il momento in cui si sta
        tarando l'inquadratura e serve vederlo.
        """
        if self._sfondo is None or self._intera is None:
            return None
        if self._sfondo.shape != self._intera.shape:
            return None
        # Differenza NUDA, senza la normalizzazione della luce che usa la
        # decisione. Quella riporta il fotogramma alla luce dello sfondo
        # guardando media e deviazione di TUTTA l'immagine, e va benissimo
        # finché a cambiare è una striscia; ma una bottiglia larga cambia metà
        # fotogramma, le statistiche si spostano dietro di lei, e la
        # correzione va a riscalare anche lo sfondo che non è cambiato.
        # Misurato: con la normalizzazione la maschera passa dal 13 % al 93 %,
        # cioè da una sagoma a una macchia grande quanto il vetro.
        #
        # Qui non serve: fra lo sfondo imparato e adesso la posa è la stessa e
        # la luce è quella di un attimo fa. E se davvero è cambiata, la
        # maschera esplode, la sagoma non è credibile e si torna al riquadro
        # fisso — che è il comportamento giusto.
        maschera = np.abs(self._sfondo - self._intera) > self.tolleranza
        h, w = maschera.shape
        if maschera.mean() > SAGOMA_MASSIMA:
            # Non è una bottiglia che è arrivata: è la scena che è cambiata.
            return None
        # PRIMA le colonne, POI le righe dentro quelle colonne. Una colonna
        # della bottiglia è cambiata quasi tutta, perché la bottiglia va dal
        # piatto in su; ma una riga della bottiglia è cambiata solo per quanto
        # la bottiglia è larga — su una renana stretta il venti per cento — e
        # misurarla sul fotogramma intero la fa sparire sotto la soglia. La
        # riga si misura dentro la sagoma, dove il conto ha senso.
        colonne = np.flatnonzero(maschera.mean(axis=0) >= FRAZIONE_SAGOMA)
        if colonne.size < w * LARGHEZZA_MINIMA:
            return None
        dentro = maschera[:, colonne[0] : colonne[-1] + 1]
        righe = np.flatnonzero(dentro.mean(axis=1) >= FRAZIONE_SAGOMA)
        if righe.size < h * ALTEZZA_MINIMA:
            return None
        x0, x1 = colonne[0] / w, (colonne[-1] + 1) / w
        y0, y1 = righe[0] / h, (righe[-1] + 1) / h
        # Una bottiglia è più alta che larga, e sta in piedi sul piatto: una
        # sagoma che non lo è non è una bottiglia, è una scena che è cambiata.
        if (x1 - x0) >= (y1 - y0):
            return None
        return (x0, y0, x1, y1)

    def guarda(self, sbirciata: np.ndarray) -> None:
        """Aggiorna cosa si sta vedendo, senza decidere niente.

        Serve al mirino: lì il ciclo è fermo e nessuno chiama `aggiorna`, ma il
        riquadro da disegnare deve essere quello di ADESSO. Non tocca ne' i
        contatori ne' la convinzione: guardare non è decidere.
        """
        self._intera = sbirciata

    def c_e_qualcosa(self) -> None:
        """Sul piatto c'è qualcosa, comunque stessero le cose fin qui.

        Lo dice chi sa che quello che si vede non è lo sfondo — un'etichetta
        letta, per esempio. Allora lo sfondo che il rivelatore ha in mano è
        sbagliato: se il dispositivo si è acceso con la bottiglia già posata,
        ha imparato quella, e da lì in poi il piatto gli sembrerebbe vuoto. Si
        butta, e si tornerà a conoscerlo quando la bottiglia verrà tolta.
        """
        self.presente = True
        self._sfondo = self._scena = None
        self._diverse = self._uguali = 0

    def non_e_una_bottiglia(self, fascia: np.ndarray) -> None:
        """Quel che si vede non è una bottiglia con un'etichetta: diventa lo sfondo.

        Lo dicono due voci. Il sensore di distanza, quando sul piatto non c'è
        niente (vedi `Amelie._guarda_il_piatto`); e l'OCR, quando ha guardato e
        riguardato senza trovare niente da leggere.

        Serve a sbloccarsi. Lo sfondo che il rivelatore ha in mano può essere
        sbagliato — ricaricato da un'installazione precedente, imparato con una
        bottiglia davanti — e allora la sagoma della bottiglia non si trova, e
        all'OCR arriva il ritaglio fisso con dentro mezza stanza.

        Se invece era una bottiglia con l'etichetta girata, lo sfondo torna
        quello giusto appena la si toglie: il sensore dice che il piatto è
        vuoto, e quel che si vede lo è davvero.
        """
        self.presente = False
        self.differenza = 0.0
        self._sfondo = fascia
        self._scena = None
        self._diverse = self._uguali = 0

    @property
    def sfondo(self) -> np.ndarray | None:
        """Il piatto vuoto, per chi lo vuole ricordare fra un avvio e l'altro."""
        return None if self.presente else self._sfondo

    def ricorda(self, sfondo: np.ndarray) -> None:
        """Riparte da uno sfondo conosciuto, invece che da quello che si vede.

        Il piatto vuoto è una proprietà dell'installazione, non del processo:
        se non si ricorda, un dispositivo acceso con la bottiglia già posata
        impara quella come sfondo, e finché non la si toglie il riquadro della
        sua etichetta non si trova.
        """
        self.presente = False
        self._sfondo = sfondo
        self._scena = self._ultima = None
        self._diverse = self._uguali = 0

    def reimposta(self) -> None:
        self.presente = False
        self.differenza = 0.0
        self._sfondo = self._scena = self._ultima = None
        self._diverse = self._uguali = 0

    def _diverso(self, a: np.ndarray, b: np.ndarray) -> float:
        """Quanto sono diverse due sbirciate, guardando SOLO la striscia.

        Le soglie sono misurate sulla striscia centrale e li' devono restare:
        allargare il confronto a tutto il fotogramma vorrebbe dire che un
        cameriere che passa sullo sfondo pesa quanto una bottiglia posata.
        """
        return quanto_diverso(self._centro(a), self._centro(b), self.tolleranza)


def trova_camera(nome: str = "U20CAM") -> str:
    """Restituisce il percorso stabile della camera, cercandola per nome.

    `/dev/v4l/by-id/` contiene collegamenti costruiti su vendor, modello e numero
    di serie: sopravvivono ai riavvii e all'ordine di enumerazione. Si prende
    l'`index0`, che e' il nodo di cattura; l'`index1` dei dispositivi UVC e' il
    nodo di soli metadati e non produce fotogrammi.
    """
    candidati = sorted(glob.glob("/dev/v4l/by-id/*"))
    per_nome = [c for c in candidati if nome.lower() in c.lower()]
    cattura = [c for c in per_nome if c.endswith("index0")] or per_nome
    if cattura:
        return cattura[0]

    # Nessun collegamento by-id: si ripiega sull'interrogazione diretta dei nodi,
    # perche' by-id manca se udev non ha ancora girato.
    for nodo in sorted(glob.glob("/dev/video*")):
        try:
            r = subprocess.run(
                ["v4l2-ctl", "-d", nodo, "--info"],
                capture_output=True, text=True, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if nome.lower() in r.stdout.lower():
            return nodo

    disponibili = ", ".join(candidati) or "nessuno"
    raise CameraNonDisponibile(
        f"nessuna camera che contenga {nome!r}. Collegamenti by-id: {disponibili}"
    )


def _v4l2(device: str, *controlli: str) -> None:
    """Imposta controlli V4L2, senza far fallire la cattura se non esistono.

    Non tutte le camere UVC espongono gli stessi nomi di controllo: se uno
    manca si registra e si va avanti, perché un'esposizione non bloccata
    peggiora la ripetibilità ma non impedisce di scattare.
    """
    for c in controlli:
        cmd = ["v4l2-ctl", "-d", device, "--set-ctrl", c]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                log.warning("controllo V4L2 rifiutato (%s): %s", c, r.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("v4l2-ctl non eseguibile per %s: %s", c, e)


def blocca_esposizione(imp: ImpostazioniCamera, device: str | None = None) -> None:
    """Disattiva auto-esposizione e bilanciamento del bianco.

    Da chiamare una volta all'avvio, non a ogni scatto: alcuni driver UVC
    reimpostano i valori a ogni riapertura del device.
    """
    _v4l2(
        device or imp.device or trova_camera(imp.nome_camera),
        "auto_exposure=1",                      # 1 = manuale
        f"exposure_time_absolute={imp.esposizione}",
        "white_balance_automatic=0",
        f"white_balance_temperature={imp.temperatura_colore}",
        f"gain={imp.guadagno}",
    )


def imposta_posa(device: str, centesimi_di_ms: int) -> None:
    """Cambia il solo tempo di posa, lasciando stare tutto il resto."""
    _v4l2(device, f"exposure_time_absolute={centesimi_di_ms}")


class Camera:
    """La camera: stream acceso mentre si guarda, spento mentre si parla.

    Con il DisplayPort attivo il link USB scende a 2.0 e camera e audio si
    dividono un solo bus. Chiudendo lo stream prima di parlare (`chiudi`), il
    problema della banda isocrona non si pone proprio — e la pipeline è
    comunque sequenziale. Fra una sbirciata e l'altra, invece, lo stream resta
    acceso: vedi `_apri` per il conto.
    """

    def __init__(self, impostazioni: ImpostazioniCamera | None = None) -> None:
        self.imp = impostazioni or ImpostazioniCamera()
        self._percorso: str | None = None
        # Lo stream, quando è acceso. Lo condividono la sbirciata e lo scatto,
        # e il lucchetto serve perché arrivano da due thread diversi.
        self._cap: cv2.VideoCapture | None = None
        self._lucchetto = threading.Lock()
        # Il riquadro di QUESTA bottiglia, quando si sa dov'e': (x0,y0,x1,y1)
        # in frazioni. Lo mette chi guarda il piatto - vedi
        # `PresenzaOttica.riquadro` - e quando e' `None` si usa quello fisso.
        self.riquadro: tuple[float, float, float, float] | None = None
        # L'ultimo fotogramma che il guardiano ha preso, con l'istante in cui
        # l'ha preso. Grezzo, non raddrizzato: raddrizzare costa, e la maggior
        # parte dei fotogrammi che passano di qui non li guarda nessuno.
        self._recente: tuple[float, np.ndarray] | None = None
        self._guardiano: threading.Thread | None = None
        self._basta = threading.Event()
        self._in_pausa = threading.Event()
        # Quanti fotogrammi saltare prima di rifidarsi della luce, dopo aver
        # cambiato la posa: il driver la applica con tre fotogrammi di ritardo.
        self._da_saltare = 0
        # Quando il guardiano guardera' di nuovo la luce, e l'ultima misura
        # fatta - posa e luce - per stimare come risponde la scena.
        self._prossima_misura = 0.0
        self._punto_precedente: tuple[int, float] | None = None
        # Letture di fila senza fotogramma. Vedi `_a_vuoto`.
        self._vuoti = 0
        # Quando la camera ha dato l'ultimo fotogramma, per qualunque strada:
        # guardiano, mirino o scatto. A differenza di `_recente` non si azzera
        # quando lo stream si spegne: non dice se la camera e' accesa adesso,
        # dice se funziona. Lo legge `/stato`.
        self.ultimo_fotogramma: float | None = None

    @property
    def percorso(self) -> str:
        """Il device della camera, risolto una volta sola e poi ricordato."""
        if self._percorso is None:
            self._percorso = self.imp.device or trova_camera(self.imp.nome_camera)
            log.info("camera: %s", self._percorso)
        return self._percorso

    def _apri(self) -> cv2.VideoCapture:
        """Accende lo stream, se non è già acceso.

        Lo stream si tiene acceso fra una sbirciata e l'altra, e il motivo è
        una misura: **aprire costa più di cento fotogrammi**. Sulla board,
        stesso device, stessa risoluzione:

            apri + leggi + chiudi, ogni volta     1,4 s
            stream già acceso, un fotogramma      0,09 s

        Il primo fotogramma dopo l'accensione ne costa 1,1 da solo: è il tempo
        che ci mette il sensore a partire, e si paga una volta. Tenerlo acceso
        costa invece **0,9 % di CPU e nessun grado** — misurato con lo stream
        aperto dodici secondi senza leggere niente, e la temperatura non si è
        mossa da 48 °C. Su una board senza ventola il timore sarebbe il carico;
        il conto dice che carica molto di più riaprire ogni volta.

        Si spegne quando parla la voce (`chiudi`): lì la banda USB serve
        all'audio.
        """
        if self._cap is not None:
            return self._cap
        cap = cv2.VideoCapture(self.percorso, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise CameraNonDisponibile(f"impossibile aprire {self.percorso}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.imp.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.imp.larghezza)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.imp.altezza)
        # Un buffer corto riduce, ma non elimina, i fotogrammi vecchi: lo
        # scarto esplicito qui sotto resta necessario.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # La posa si riafferma a ogni accensione. Alcuni driver UVC
        # reimpostano i controlli quando il device si riapre, e la ricerca
        # della posa fa i suoi conti a partire da quella che CREDE di avere:
        # se l'hardware ne ha un'altra, il primo passo va nella direzione
        # giusta ma della misura sbagliata.
        imposta_posa(self.percorso, self.imp.esposizione)
        self._cap = cap
        return cap

    def chiudi(self) -> None:
        """Spegne lo stream. Si riaccende da solo alla prossima richiesta.

        Ferma anche il guardiano, e lo ferma PRIMA di prendere il lucchetto:
        al contrario, il guardiano lo terrebbe per i novanta millesimi del suo
        fotogramma e chi chiude aspetterebbe lui.
        """
        self._basta.set()
        g = self._guardiano
        if g is not None and g is not threading.current_thread():
            g.join(timeout=2.0)
        self._guardiano = None
        with self._lucchetto:
            self._recente = None
            # Alla riaccensione la scena puo' essere un'altra: la misura vecchia
            # non dice piu' come risponde, e la prima si fa subito.
            self._punto_precedente = None
            self._prossima_misura = 0.0
            self._spegni()

    def _spegni(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _a_vuoto(self) -> None:
        """Una lettura senza fotogramma, col lucchetto preso.

        Riaccendere lo stream basta quando si e' inceppato il flusso; non basta
        quando e' la POSA a fermare la camera, perche' ogni riaccensione la
        riapplica. Alla seconda lettura a vuoto di fila con una posa lunga si
        riparte dalla posa sicura: al buio si leggera' meno, ma si leggera', e
        la regolazione risale da li' - fino al tetto, che sta sotto la soglia in
        cui questa camera si ferma (vedi `ImpostazioniCamera.posa_massima`).
        """
        self._vuoti += 1
        if self._vuoti >= 2 and self.imp.esposizione > self.imp.posa_sicura:
            log.warning("camera muta con posa %d: riparto da %d",
                        self.imp.esposizione, self.imp.posa_sicura)
            self.imp = replace(self.imp, esposizione=self.imp.posa_sicura)
            self._da_saltare = self.imp.fotogrammi_da_scartare

    def ripristina(self) -> None:
        """Rimette la camera com'era all'accensione, senza riaccendere niente.

        Stream spento e guardiano fermo, posa di partenza, nessun riquadro, e
        il device si ricerca da capo - dopo un inceppamento USB puo' tornare
        con un nome diverso. Alla prossima richiesta si riapre tutto.
        """
        self.chiudi()
        with self._lucchetto:
            self._vuoti = 0
            self._da_saltare = 0
            self.imp = replace(self.imp, esposizione=self.imp.posa_sicura)
            self.riquadro = None
            if not self.imp.device:
                self._percorso = None

    def sorveglia(self) -> None:
        """Tiene lo stream in moto, perché scattare non costi niente.

        Uno scatto a camera ferma (`scatta`) costa settecento millesimi e li
        spende quasi tutti ad aspettare: centocinquanta perché la luce si
        assesti, tre fotogrammi buttati per svuotare il buffer USB, la ricerca
        della posa, e infine i tre della raffica. Novanta millesimi l'uno, e
        tutti dopo che la bottiglia è già lì.

        Con la camera già in moto non c'è niente da svuotare e niente da
        assestare: il fotogramma buono è quello che sta arrivando comunque, e
        prenderlo costa il tempo di aspettarne uno — al massimo novanta
        millesimi, spesso zero.

        Costa tenere aperto uno stream che per lo più nessuno guarda. Il conto
        è in `_apri`: dodici secondi di stream aperto, temperatura ferma a
        48 °C.
        """
        if self._guardiano is not None and self._guardiano.is_alive():
            return
        self._basta.clear()
        self._guardiano = threading.Thread(target=self._veglia, name="camera",
                                           daemon=True)
        self._guardiano.start()

    @property
    def sorvegliata(self) -> bool:
        return self._guardiano is not None and self._guardiano.is_alive()

    @contextmanager
    def in_pausa(self):
        """Ferma il guardiano per il tempo di un blocco, e poi lo rimette.

        Serve durante la lettura. Prendere un fotogramma da questa camera vuol
        dire decodificare un MJPEG da due megapixel, undici volte al secondo,
        e l'OCR gira su quattro thread sugli stessi quattro core: misurato
        sulla board, la rilevazione passa da 274 a oltre mille millesimi
        quando qualcun altro lavora.

        Il fotogramma buono e' gia' stato preso: durante la lettura il
        guardiano non serve a nessuno, e quello che risparmia lo restituisce
        all'unica cosa che in quel momento ha fretta.
        """
        self._in_pausa.set()
        try:
            yield
        finally:
            self._in_pausa.clear()

    def _veglia(self) -> None:
        """Il giro del guardiano: un fotogramma, e ogni tanto un ritocco."""
        while not self._basta.is_set():
            if self._in_pausa.is_set():
                self._basta.wait(0.02)
                continue
            try:
                with self._lucchetto:
                    if self._basta.is_set():
                        return
                    cap = self._apri()
                    ok, frame = cap.read()
            except CameraNonDisponibile as e:
                log.warning("guardiano: %s", e)
                self._basta.wait(1.0)
                continue
            except Exception:                               # noqa: BLE001
                log.exception("guardiano: fotogramma perso")
                self._basta.wait(1.0)
                continue
            if not ok or frame is None:
                # Uno stream che non dà più fotogrammi non guarisce da solo.
                log.warning("guardiano: fotogramma a vuoto, riaccendo")
                with self._lucchetto:
                    self._a_vuoto()
                    self._spegni()
                self._basta.wait(0.5)
                continue
            self._vuoti = 0
            self._recente = (time.monotonic(), frame)
            self.ultimo_fotogramma = self._recente[0]
            self._ritocca_la_posa(frame)

    def _ritocca_la_posa(self, frame) -> None:
        """Un passo verso la posa giusta, mentre lo stream scorre.

        E' la regolazione della luce in background: il guardiano gira finche'
        il dispositivo aspetta o legge, e ogni mezzo secondo guarda quanta luce
        c'e' dove guardera' l'OCR e, se serve, corregge la posa di un passo.
        Cosi' la camera segue la sala - le luci abbassate a cena, il sole che
        cala - e la bottiglia trova la posa gia' quasi giusta, invece di
        pagarne la ricerca da appoggiata.

        `_cerca_la_posa` fa la stessa cosa in un colpo, ma aspettando: cambia
        la posa e poi legge fotogrammi finche' la luce non si ferma, e quei
        fotogrammi si pagano tutti nel momento peggiore. Qui il tempo c'e':
        si corregge di un passo, si saltano i tre fotogrammi che il driver
        impiega ad applicarla, e si riguarda.
        """
        if self._da_saltare > 0:
            self._da_saltare -= 1
            return
        ora = time.monotonic()
        if ora < self._prossima_misura:
            return
        self._prossima_misura = ora + INTERVALLO_MISURA_S
        imp = self.imp
        luce = float(cv2.cvtColor(self.ritaglia(self._raddrizza(frame)),
                                  cv2.COLOR_BGR2GRAY).mean())
        precedente = self._punto_precedente
        self._punto_precedente = (imp.esposizione, luce)
        if abs(luce - imp.luce_cercata) <= imp.luce_tollerata:
            return
        nuova = posa_verso(imp, imp.esposizione, luce, precedente)
        if nuova == imp.esposizione:
            return
        imposta_posa(self.percorso, nuova)
        self.imp = replace(imp, esposizione=nuova)
        self._da_saltare = self.imp.fotogrammi_da_scartare
        log.info("posa %d -> %d (luce %.0f)", imp.esposizione, nuova, luce)

    def guarda_subito(self) -> None:
        """La prossima misura della luce al prossimo fotogramma, senza aspettare
        il mezzo secondo: la scena e' appena cambiata, e' arrivata una
        bottiglia."""
        self._prossima_misura = 0.0

    def pronto(self, *, dopo: float = 0.0, attesa: float = 0.5):
        """Il primo fotogramma preso DOPO un certo istante, già raddrizzato.

        `dopo` è quello che rende onesta la fretta: la bottiglia si è appoggiata
        a un certo istante, e un fotogramma di prima mostra il piatto vuoto con
        una mano sopra. Si aspetta il primo che venga dopo, e sono novanta
        millesimi al massimo.
        """
        scadenza = time.monotonic() + attesa
        while True:
            recente = self._recente
            if recente is not None and recente[0] >= dopo:
                return self._raddrizza(recente[1])
            if not self.sorvegliata or time.monotonic() >= scadenza:
                return None
            time.sleep(0.01)

    def al_volo(self, *, dopo: float = 0.0, attesa: float = 1.0) -> "Scatto | None":
        """Lo scatto quando la camera è già in moto: si prende, non si fa.

        Si prende il primo fotogramma abbastanza nitido, e se non ne arriva
        nessuno si tiene il migliore visto. **È l'assestamento fatto
        guardando**, al posto di un'attesa fissa: una bottiglia appoggiata
        piano è ferma subito e non si aspetta niente, una appoggiata di slancio
        oscilla e si aspetta lei — invece di aspettare sempre, per il caso
        peggiore, anche quando non serve.

        L'attesa è un tetto, non un costo: ci si ferma al primo fotogramma
        nitido, e una bottiglia appoggiata da una mano ferma lo dà subito. Un
        secondo e non un quarto: un quarto di secondo, due o tre fotogrammi,
        basta per le bottiglie posate, non per quelle tenute in mano davanti
        alla camera. Lì in un quarto di secondo non arriva nessun fotogramma
        fermo, e si legge il migliore dei mossi: «ASTI» grande come mezza
        etichetta e nemmeno una riga trovata. In un secondo i fotogrammi sono
        dieci, e fra dieci uno fermo c'è quasi sempre. Il prezzo si paga solo
        quando la scena non arriva mai a fuoco - davanti a un piatto vuoto la
        nitidezza resta a 11 - ed è tre quarti di secondo su una scansione che
        comunque non troverà niente.

        E la luce. All'arrivo della bottiglia la posa e' quella che il
        guardiano ha trovato sulla sala, e l'etichetta, vicina all'anello, puo'
        essere piu' chiara: si chiede subito una misura (`guarda_subito`), e ci
        si ferma al primo fotogramma nitido CON la luce giusta. Uno nitido ma
        bruciato si tiene solo se l'altro non arriva in tempo.

        `None` vuol dire che il guardiano non sta girando o non ha ancora un
        fotogramma abbastanza nuovo: chi chiama torna a `scatta`, che la camera
        se la apre da sé.
        """
        self.guarda_subito()
        scadenza = time.monotonic() + attesa
        migliore: Scatto | None = None
        in_luce: Scatto | None = None
        viste: list[float] = []
        while True:
            frame = self.pronto(dopo=dopo, attesa=max(0.0, scadenza - time.monotonic()))
            if frame is None:
                break
            posto = self.posto(frame)
            ritaglio = frame[posto[1]:posto[3], posto[0]:posto[2]]
            # La nitidezza si misura sul RITAGLIO e non sul fotogramma intero:
            # costa meno, e dice quello che conta davvero, cioè se è a fuoco
            # dove si legge. Sul fotogramma intero, una stanza nitida dietro
            # una bottiglia mossa fa un numero alto e una lettura vuota.
            n = nitidezza(ritaglio)
            viste.append(n)
            scatto = Scatto(immagine=ritaglio, nitidezza=n, scartati=0,
                            nitidezze=[], intero=frame, posto=posto)
            luce_giusta = self._luce_giusta(ritaglio)
            if migliore is None or n > migliore.nitidezza:
                migliore = scatto
            if luce_giusta and (in_luce is None or n > in_luce.nitidezza):
                in_luce = scatto
            if (n >= SOGLIA_NITIDEZZA and luce_giusta) or time.monotonic() >= scadenza:
                break
            # Il prossimo dev'essere un altro fotogramma, non lo stesso
            # riguardato: `dopo` si sposta a ora.
            dopo = time.monotonic()
        scelto = in_luce or migliore
        if scelto is not None:
            scelto.nitidezze = viste
        return scelto

    def _luce_giusta(self, ritaglio) -> bool:
        """La luce del ritaglio basta a leggere bene, o non si puo' migliorare.

        Il doppio della tolleranza del guardiano: lui insegue il bersaglio, qui
        basta che l'OCR legga. E se la posa e' gia' a un estremo, aspettare un
        fotogramma migliore non serve: non arrivera'.
        """
        imp = self.imp
        if imp.esposizione in (imp.posa_minima, imp.posa_massima):
            return True
        grigio = cv2.cvtColor(ritaglio, cv2.COLOR_BGR2GRAY) if ritaglio.ndim == 3 else ritaglio
        return abs(float(grigio.mean()) - imp.luce_cercata) <= 2 * imp.luce_tollerata

    def fascia(self, frame) -> np.ndarray:
        """Il fotogramma INTERO, in grigio e piccolo.

        Non solo la striscia centrale, anche se per decidere se c'e' una
        bottiglia quella basta: la striscia se la ritaglia chi decide, perche'
        la stessa immagine serve a una seconda cosa - capire DOVE sta la
        bottiglia, per dare all'OCR il suo riquadro invece di un riquadro
        fisso. Vedi `PresenzaOttica.riquadro`.

        Il fotogramma arriva gia' in piedi: raddrizzarlo e' compito di chi lo
        legge dal device, una volta sola. Vedi `_fotogramma`.
        """
        grigio = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(grigio, self.imp.sbirciata).astype(np.float32)

    def fotogramma(self):
        """Un fotogramma, gia' in piedi, per chi vuole guardare invece di leggere.

        Lo usa il mirino, che ne consuma qualcuno al secondo. Aspetta il suo
        turno: la camera si apre un processo per volta, e dentro al processo un
        filo per volta.

        **Gia' raddrizzato**, e non e' un dettaglio estetico: il mirino serve a
        far vedere cosa legge il dispositivo, e il dispositivo legge il
        fotogramma raddrizzato. Mostrando quello grezzo si tarerebbe
        l'inquadratura guardando un'immagine che nessuno legge - coricata,
        mentre la bottiglia sta in piedi.
        """
        return self._fotogramma(bloccante=True)

    def _fotogramma(self, *, bloccante: bool):
        """Un fotogramma raddrizzato, o `None`.

        Con `bloccante` falso si rinuncia se la camera e' occupata: una
        sbirciata saltata non e' un guasto, e chi guarda non deve mai mettersi
        in coda dietro a chi lavora.
        """
        # Se il guardiano sta girando, il fotogramma c'è già: metterglisi in
        # coda vorrebbe dire aspettare il suo, per poi chiederne un altro.
        recente = self._recente
        if recente is not None and time.monotonic() - recente[0] <= FRESCHEZZA_S:
            return self._raddrizza(recente[1])
        if not self._lucchetto.acquire(blocking=bloccante):
            return None
        try:
            cap = self._apri()
            ok, frame = cap.read()
            if not ok or frame is None:
                # Uno stream che non da' piu' fotogrammi non guarisce da solo:
                # si spegne, e la prossima richiesta lo riaccende.
                log.warning("fotogramma a vuoto: riaccendo lo stream")
                self._a_vuoto()
                self._spegni()
                return None
            self._vuoti = 0
            self.ultimo_fotogramma = time.monotonic()
            return self._raddrizza(frame)
        except CameraNonDisponibile as e:
            log.warning("camera non disponibile: %s", e)
            return None
        finally:
            self._lucchetto.release()

    def regola_la_luce(self) -> float:
        """Cerca la posa e basta, senza scattare.

        Serve al mirino: si guarda l'etichetta con la stessa posa con cui la
        leggerà il dispositivo, altrimenti si sta calibrando un'inquadratura
        che a regime non esiste.
        """
        with self._lucchetto:
            cap = self._apri()
            for _ in range(self.imp.fotogrammi_da_scartare):
                cap.grab()
            return self._cerca_la_posa(cap)

    def sbircia(self) -> np.ndarray | None:
        """Un fotogramma solo, intero, in grigio e piccolo: vedi `fascia`.

        Restituisce `None` quando la camera è occupata dallo scatto: una
        sbirciata saltata non è un guasto, è una sbirciata saltata. Chi guarda
        non deve mai mettersi in coda dietro a chi lavora.
        """
        frame = self._fotogramma(bloccante=False)
        return None if frame is None else self.fascia(frame)

    def _raddrizza(self, frame):
        """Rimette il fotogramma per il verso in cui si legge."""
        if self.imp.rotazione == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if self.imp.rotazione == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if self.imp.rotazione == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _luce(self, cap) -> float | None:
        """Quanta luce c'è in un fotogramma, misurata dove guarderà l'OCR.

        Raddrizzato e poi ritagliato, come lo vedrà l'OCR. Gli angoli scuri del
        fotogramma intero abbasserebbero la media di una luce che
        sull'etichetta c'è; e misurare il ritaglio del fotogramma NON
        raddrizzato prenderebbe addirittura la fascia sbagliata della scena —
        con la camera di lato, una striscia di parete invece della bottiglia.
        """
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        imp = self.imp
        return float(cv2.cvtColor(self.ritaglia(self._raddrizza(frame)),
                                  cv2.COLOR_BGR2GRAY).mean())

    def _aspetta_la_posa(self, cap, prima: float) -> float | None:
        """Legge finché la luce non si è **fermata** sul valore nuovo.

        Il driver applica la posa nuova con qualche fotogramma di ritardo —
        misurato: tre, nei due versi, su uno stream letto senza pause. Contarli
        non basta: nel servizio, dove lo stream sta fermo fra una sbirciata e
        l'altra, il fotogramma dopo i tre scarti può tornare ancora con la posa
        vecchia. Senza aspettare, la ricerca rimisura, corregge una seconda
        volta nello stesso verso, e finisce contro il tetto **qualunque sia la
        luce** — e sembra pure funzionare, perché al buio il tetto è la
        risposta giusta.

        Aspettare che la luce *cominci* a muoversi non basta neanche: il
        primo fotogramma diverso può essere ancora a metà strada, e una misura
        presa a metà strada porta la correzione successiva ancora più in là.
        Si aspetta che due fotogrammi di fila dicano la stessa cosa.

        Se non si ferma, o si ferma dov'era, la posa non sta arrivando al
        sensore: si restituisce `None` e la ricerca smette, invece di sommare
        correzioni su una misura mai verificata.
        """
        precedente = None
        for _ in range(self.imp.fotogrammi_di_attesa):
            luce = self._luce(cap)
            if luce is None:
                return None
            ferma = (precedente is not None
                     and abs(luce - precedente) <= SCARTO_DI_POSA)
            precedente = luce
            # Ferma sul valore di prima vuol dire che la posa nuova non e'
            # ancora arrivata: sono i fotogrammi vecchi, e si continua ad
            # aspettare. Ferma su un valore diverso vuol dire che e' arrivata.
            if ferma and abs(luce - prima) > SCARTO_DI_POSA:
                return luce
        log.warning("la posa non arriva al sensore: luce ferma a %.0f",
                    precedente if precedente is not None else -1)
        return None

    def ritaglia(self, frame):
        """Il pezzo di fotogramma che va all'OCR: quello della bottiglia.

        Se si sa dove sta la bottiglia si prende il suo riquadro; altrimenti si
        torna alle frazioni fisse, che sono larghe e non tagliano niente. Una
        renana alta e stretta e una borgognona larga non occupano la stessa
        parte del fotogramma: un riquadro fisso o taglia l'una o lascia dentro
        mezza stanza per l'altra. Dove, esattamente, lo dice `posto`.
        """
        x0, y0, x1, y1 = self.posto(frame)
        return frame[y0:y1, x0:x1]

    def posto(self, frame) -> tuple[int, int, int, int]:
        """Dove sta il ritaglio nel fotogramma: (x0, y0, x1, y1) in pixel.

        Una funzione sola per tre chiamanti - il ritaglio, il mirino che lo
        disegna e la rilettura che lo allarga - perche' tre copie dello stesso
        conto finiscono per non essere piu' lo stesso conto.

        Il riquadro della bottiglia si allarga un poco ai lati: vedi
        `ImpostazioniCamera.allarga_riquadro`.
        """
        h, w = frame.shape[:2]
        r = self.riquadro
        if r is not None:
            x0, y0, x1, y1 = r
            largo = (x1 - x0) * self.imp.allarga_riquadro
            px0, px1 = int(w * max(0.0, x0 - largo)), int(w * min(1.0, x1 + largo))
            py0, py1 = int(h * max(0.0, y0)), int(h * min(1.0, y1))
            if px1 - px0 >= 2 and py1 - py0 >= 2:
                return px0, py0, px1, py1
        nh, nw = int(h * self.imp.ritaglio_alto), int(w * self.imp.ritaglio_largo)
        y0, x0 = (h - nh) // 2, (w - nw) // 2
        return x0, y0, x0 + nw, y0 + nh

    def _cerca_la_posa(self, cap) -> float:
        """Regola il tempo di posa sulla luce che c'è davvero, ora, qui.

        La posa non è automatica: con l'auto-esposizione servono 500-800 ms di
        assestamento dopo ogni cambio di luce e i risultati non sono
        ripetibili. Ma una posa fissa è fissa alla stanza in cui si è misurata,
        e il dispositivo va in una sala che la sera abbassa le luci. Misurato
        al buio con l'anello bianco, a posa 900 l'OCR non legge **niente**; a
        3000 legge la denominazione.

        Quindi la posa resta manuale — si sa sempre qual è e non cambia durante
        la raffica — ma si sceglie guardando: un fotogramma, la sua luce media,
        un ritocco, e la verifica che il ritocco sia arrivato.

        La posa trovata si ricorda: la bottiglia dopo arriva nella stessa sala,
        e quasi sempre il primo fotogramma è già dentro la banda buona.
        """
        imp = self.imp
        posa = imp.esposizione
        luce = self._luce(cap)
        if luce is None:
            return 0.0
        precedente: tuple[int, float] | None = None
        for _ in range(imp.ritocchi_posa):
            if abs(luce - imp.luce_cercata) <= imp.luce_tollerata:
                break
            nuova = posa_verso(imp, posa, luce, precedente)
            if nuova == posa:
                break
            imposta_posa(self.percorso, nuova)
            arrivata = self._aspetta_la_posa(cap, luce)
            precedente = (posa, luce)
            posa = nuova
            if arrivata is None:
                break
            luce = arrivata
        if posa != imp.esposizione:
            log.info("posa %d -> %d (luce %.0f)", imp.esposizione, posa, luce)
            self.imp = replace(imp, esposizione=posa)
        return luce

    def scatta(self, *, attesa_luce: float | None = None) -> Scatto:
        """Esegue una raffica e restituisce il fotogramma più nitido.

        La luce non la tocca: questo modulo non parla con l'MCU. Sul
        dispositivo è quella dello stato, già accesa; uno script che la accende
        solo per scattare lo fa prima di chiamarlo.
        """
        attesa = self.imp.assestamento_luce_s if attesa_luce is None else attesa_luce
        # Qui si aspetta, invece di rinunciare come fa la sbirciata: lo scatto
        # è il lavoro, e una sbirciata dura novanta millesimi.
        with self._lucchetto:
            cap = self._apri()
            if attesa > 0:
                time.sleep(attesa)

            scartati = 0
            for _ in range(self.imp.fotogrammi_da_scartare):
                if cap.grab():
                    scartati += 1
            # PRIMA si buttano i fotogrammi vecchi, POI si misura la luce. Al
            # contrario, la prima misura cadrebbe su un fotogramma rimasto nel
            # buffer - preso prima che lo stream si fermasse, o prima che una
            # luce di prova si accendesse - e la posa partirebbe da una luce
            # che adesso non c'è.
            self._cerca_la_posa(cap)

            migliore: np.ndarray | None = None
            migliore_n = -1.0
            tutte: list[float] = []
            for _ in range(self.imp.fotogrammi_raffica):
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                n = nitidezza(frame)
                tutte.append(n)
                if n > migliore_n:
                    migliore_n, migliore = n, frame

            if migliore is None:
                # Lo stream resta acceso fra uno scatto e l'altro, ma uno che
                # non dà fotogrammi non è uno stream: si spegne, e il
                # prossimo tentativo riparte da zero invece di insistere.
                self._a_vuoto()
                self._spegni()
                raise CameraNonDisponibile(
                    f"nessun fotogramma letto da {self.percorso}"
                )
            self.ultimo_fotogramma = time.monotonic()

        # Prima si raddrizza, poi si ritaglia: il ritaglio si misura sul
        # fotogramma in piedi, e su un'immagine coricata terrebbe la fascia
        # sbagliata della bottiglia.
        migliore = self._raddrizza(migliore)
        posto = self.posto(migliore)
        return Scatto(
            immagine=migliore[posto[1]:posto[3], posto[0]:posto[2]],
            nitidezza=migliore_n,
            scartati=scartati,
            nitidezze=tutte,
            intero=migliore,
            posto=posto,
        )


class CameraNonDisponibile(RuntimeError):
    """La camera non risponde: cavo, hub, o host mode USB non attivo."""


def salva(scatto: Scatto, percorso: str | Path) -> Path:
    """Salva il fotogramma su disco, per il debug e per il set di regressione."""
    p = Path(percorso)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(p), scatto.immagine):
        raise OSError(f"scrittura fallita: {p}")
    return p
