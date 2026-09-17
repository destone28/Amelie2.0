"""Cattura del fotogramma dell'etichetta.

La geometria è fissa e nota: la lente sta 30 mm sopra il piano d'appoggio, 60 mm
davanti alla bottiglia, con l'asse inclinato di 53° sopra l'orizzonte. I disegni
da cui vengono questi numeri stanno fuori dal repo, in `Project/Amelie2.0/`
insieme al CAD; le quote che servono a montare sono in
`docs/06-ASSEMBLAGGIO-BANCO.md`. La distanza ottica al centro dell'etichetta è ~100 mm e la fascia a
fuoco copre una finestra di circa 60 × 36 mm, che su qualunque etichetta
commerciale contiene produttore, denominazione e annata.

Tre accorgimenti valgono più di qualunque scelta di libreria:

1. **Esposizione bloccata.** Con l'auto-esposizione servono 500-800 ms di
   assestamento dopo l'accensione della luce e i risultati non sono ripetibili.
   Con l'esposizione fissa bastano 120-200 ms. Bottiglia e camera sono entrambe
   ferme: si può permettere un tempo di posa lungo e guadagno a zero, che dà
   **molto più segnale di quanto possano darne i LED**.

   È anche il motivo per cui togliere il secondo Modulino Pixels — quello che
   faceva da flash — costa meno di quanto sembri: la luce non era il fattore
   dominante. Resta l'anello alla base, che sale a bianco per la durata della
   raffica. Quanto basti va misurato sul banco, con l'etichetta vera e la luce
   del locale.

2. **Scartare i primi fotogrammi.** Il buffer UVC contiene immagini precedenti
   all'accensione della luce. Il primo fotogramma letto dopo è quasi sempre
   vecchio: è l'errore più comune nelle pipeline OpenCV.

3. **Raffica e varianza del laplaciano.** Cinque fotogrammi, si tiene il più
   nitido. Costa 200 ms e salva dai casi in cui la bottiglia oscilla ancora.

Il ritaglio centrale limita la distorsione a barile e la vignettatura, che
stanno agli angoli. La frazione è un compromesso, e va nella direzione opposta a
quella che verrebbe da pensare: stringere migliora ogni singolo carattere ma
toglie righe intere, e il riconoscimento lavora su parole, non su caratteri. Vedi
`ImpostazioniCamera.ritaglio`.
"""

from __future__ import annotations

import glob
import logging
import subprocess
import threading
import time
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

    # Esposizione fissa, in unità da 100 µs: 900 = 90 ms.
    #
    # Era 300, e **misurato sul banco** in una stanza in penombra quella posa
    # non leggeva NIENTE: luminosità media 11 su 255, e l'OCR restituiva zero
    # righe. A 900 la media sale a 30 e l'etichetta si legge; a 2000 sale a 55.
    #
    # E la luce dell'anello non c'entra quasi niente. Misurato, sempre lì:
    #
    #     anello spento          6,5
    #     anello ambra           7,5
    #     anello bianco          11,3
    #     anello bianco pieno    11,7
    #
    # Cinque livelli su 255 fra spento e acceso al massimo. La posa, invece,
    # triplica il segnale triplicandola. È quello che questo modulo dichiarava
    # fin dall'inizio — «un tempo di posa lungo dà molto più segnale di quanto
    # possano darne i LED» — e che aver tolto il flash ha reso decisivo.
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
    # Misurato sul dispositivo nella scocca, con l'anello bianco e la luce
    # della stanza SPENTA — che è la condizione di un ristorante a cena:
    #
    #      900   luce 47   `` (niente)
    #     1500   luce 62   `` (niente)
    #     2200   luce 76   `ULIEET · TEITLITHE`
    #     3000   luce 88   `ULIGSA · TENUTH · CERASUOLO · D'ABRUZZO`
    #     4000   luce 99   `ULISSE · TENLITA · CERASUOLO · D'ABRUZZO`
    #
    # A 900 — la posa che il dispositivo aveva — non si legge NIENTE. A 3000
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
    # giri, e il primo tentativo fatto così finiva sempre contro il tetto.
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
    # I due estremi entro cui si può andare. Sotto il minimo non si legge
    # nemmeno in pieno giorno; sopra il massimo la raffica costa più del
    # racconto, e una bottiglia che oscilla viene mossa.
    posa_minima: int = 300
    posa_massima: int = 4000

    # Raffica. Erano cinque e cinque, scelti quando un fotogramma costava 30 ms.
    # A 90 ms costavano un secondo intero, e la scena è FERMA: bottiglia e
    # camera non si muovono, quindi i fotogrammi si somigliano tutti e tenerne
    # tre invece di cinque non cambia quale si sceglie. Lo scarto serve a
    # buttare via il buffer USB, non a mediare.
    fotogrammi_da_scartare: int = 3
    fotogrammi_raffica: int = 3

    # Ritaglio centrale, frazione del fotogramma tenuta per lato.
    #
    # Era 0,58, scelto per tenere la distorsione a barile sotto l'1% e togliere
    # la vignettatura. Ma sul banco le etichette non venivano riconosciute
    # ANCHE quando erano nitide, illuminate e ben visibili dentro al riquadro:
    # il collo di bottiglia non era la qualità dell'immagine, era la quantità
    # di testo che entrava nel ritaglio. Un'etichetta commerciale distribuisce
    # produttore, denominazione e annata su tutta la sua altezza, e a 0,58 ne
    # entrava la fascia centrale — spesso proprio quella con meno parole utili.
    #
    # A 0,80 l'area utile quasi raddoppia. MISURATO su tre scatti veri della
    # stessa etichetta, a parità di tutto il resto:
    #
    #     0,58   `'AVO | SICILIA`             tipologia, 78
    #     0,70   `'AVOL | SICILIA | ERO`      tipologia, 87
    #     0,80   `D'AVOLA | SICILIA | NERO`   tipologia, 87
    #
    # Non è la qualità dei caratteri a cambiare: sono le PAROLE INTERE. A 0,58
    # la prima e l'ultima lettera cadevano fuori dal ritaglio, e il
    # riconoscimento lavora su parole.
    #
    # Si regola dal mirino senza toccare il codice: `--ritaglio 0.9`.
    #
    # Ora è 0,85, e il motivo è il TEMPO, non la qualità. Misurato nella scocca
    # sulla stessa bottiglia, stesso fotogramma:
    #
    #     1,00   14,0 s   `UUISS | CERASUOLO | D'ABRUZZO`   87
    #     0,85    6,1 s   `UUISS | CERASUOLO | D'ABRUZZO`   87
    #     0,70    3,0 s   `CERASUOLO | D'ABRUZZO`           78
    #     0,55    2,6 s   `D'ABRUZZO`                       60
    #
    # A 0,85 si legge **la stessa cosa in meno della metà del tempo**: quello
    # che si taglia non è etichetta, è la stanza dietro. E la stanza costa cara
    # perché il rilevatore trova una regione di testo per ogni numero di un
    # calendario appeso al muro, e ognuna passa poi dal modello che le legge.
    #
    # Sotto 0,85 si scende, e si scende per la ragione di sempre: cadono fuori
    # le prime e le ultime lettere, e il riconoscimento lavora su parole intere.
    ritaglio: float = 0.85

    # Di quanto ruotare il fotogramma prima di guardarlo, in gradi orari.
    #
    # ZERO, e viene dal montaggio: nella scocca stampata la camera guarda la
    # bottiglia di fianco, e il testo dell'etichetta nel fotogramma nativo e'
    # già orizzontale. Raddrizzarlo lo corica, ed è esattamente il contrario
    # di cio' che serve.
    #
    # Era 90 per il banco, dove la camera stava girata di lato. Misurato sulla
    # scocca, stessa bottiglia e stesso fotogramma, dando all'OCR i quattro
    # versi:
    #
    #      0°    `ULISS | CERASUOLO | D'ABRUZZO`   riconosciuto, sicurezza 87
    #     90°    `D'ABRUZZC`                       niente
    #    180°    `3IMER | DRZZZO | CEAVOLO`        niente
    #    270°    `3引8到3`                          niente
    #
    # Un dispositivo che «non riconosce le bottiglie» era questo, e nient'altro.
    # Un verso sbagliato non degrada la lettura: la annulla.
    #
    # Il verso e il ritaglio si leggono insieme: coricata, la bottiglia occupa
    # il fotogramma per il lungo, e ciò che avanza ai bordi non è etichetta.
    rotazione: int = 0

    # Attesa fra accensione della luce dello scatto e primo fotogramma utile.
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
    # Novantasei per centoventotto: un ventesimo di lato. Piccola apposta - a
    # questa scala un tremolio del tavolo sposta la scena di un decimo di pixel
    # e sparisce, mentre una bottiglia resta grande come prima.
    sbirciata: tuple[int, int] = (96, 128)


@dataclass
class Scatto:
    """Il risultato di una raffica."""

    immagine: np.ndarray                     # BGR, già ritagliata
    nitidezza: float                         # varianza del laplaciano
    scartati: int = 0
    nitidezze: list[float] = field(default_factory=list)

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


def ritaglia_centro(immagine: np.ndarray, frazione: float) -> np.ndarray:
    """Tiene la porzione centrale del fotogramma.

    Fuori da questa finestra la distorsione a barile cresce col cubo del raggio
    e compare la vignettatura: entrambe peggiorano l'OCR senza aggiungere nulla,
    perché l'etichetta a fuoco sta comunque al centro.
    """
    if not 0 < frazione <= 1:
        raise ValueError(f"frazione fuori range: {frazione}")
    h, w = immagine.shape[:2]
    nh, nw = int(h * frazione), int(w * frazione)
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
    """Decide se c'è una bottiglia guardandola, invece di misurarne la distanza.

    Il sensore di distanza faceva questo lavoro e lo faceva male: il fondo di
    una bottiglia è quasi speculare e il lobo riflesso esce dal cono di
    ricezione appena la bottiglia non è centrata, così la misura salta. La
    camera invece la bottiglia la vede, e la vede grande: a dieci centimetri
    dalla lente occupa quasi tutta la fascia centrale del fotogramma.

    Non si riconosce «una bottiglia»: si riconosce che al posto della stanza
    c'è **qualcosa d'altro**. È una distinzione onesta — il dispositivo non sa
    dire se sia una bottiglia o un vaso — e non è un problema, perché chi
    decide davvero è l'OCR subito dopo: se non c'è un'etichetta, non c'è nulla
    da raccontare.

    L'isteresi resta **asimmetrica**, come sul sensore e per lo stesso motivo:
    per dire che è arrivata basta che la scena sia cambiata; per dire che è
    andata via bisogna che la scena sia tornata quella di prima. Una bottiglia
    spostata di un dito cambia la fascia del 15-30 %, abbastanza da non
    somigliare più allo sfondo ma non abbastanza da somigliargli di nuovo:
    così un racconto non si interrompe perché qualcuno ha versato da bere.
    """

    def __init__(
        self,
        soglia_arrivo: float = 0.45,
        soglia_uscita: float = 0.20,
        letture_per_arrivare: int = 2,
        letture_per_andarsene: int = 3,
        soglia_fermo: float = 0.20,
        tolleranza: float = 20.0,
    ) -> None:
        self.soglia_arrivo = soglia_arrivo
        self.soglia_uscita = soglia_uscita
        self.soglia_fermo = soglia_fermo
        self.n_arrivo, self.n_uscita = letture_per_arrivare, letture_per_andarsene
        self.tolleranza = tolleranza
        self.presente = False
        self.differenza = 0.0            # l'ultima misura, per la diagnostica
        # Lo sfondo: la fascia com'è quando sul piatto non c'è niente. `None`
        # vuol dire «non lo so ancora», e capita due volte: all'accensione, e
        # quando si scopre che la bottiglia c'era già prima di accendere.
        self._sfondo: np.ndarray | None = None
        # La scena con la bottiglia, usata solo finché lo sfondo è ignoto.
        self._scena: np.ndarray | None = None
        self._ultima: np.ndarray | None = None
        self._diverse = 0
        self._uguali = 0

    def aggiorna(self, fascia: np.ndarray) -> bool:
        """Aggiunge una sbirciata e restituisce se ora la bottiglia c'è."""
        precedente, self._ultima = self._ultima, fascia
        if precedente is None:
            if self._sfondo is None and not self.presente:
                self._sfondo = fascia
            return self.presente

        # Una scena che si sta ancora muovendo non si giudica: è la mano che
        # posa la bottiglia. Costa una sbirciata di ritardo e vale
        # l'assestamento che prima si aspettava a tempo.
        if self._diverso(fascia, precedente) >= self.soglia_fermo:
            self._diverse = self._uguali = 0
            return self.presente

        if self._sfondo is None:
            return self._aspetta_che_se_ne_vada(fascia)

        self.differenza = self._diverso(fascia, self._sfondo)
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
                self._sfondo = fascia
        else:
            # Fra le due soglie non si cambia idea: è la zona morta.
            self._diverse = self._uguali = 0

        return self._decidi()

    def aggiorna_a_mano(self, c_e: bool) -> bool:
        """Come `aggiorna`, ma la scena la dichiara chi prova invece della camera.

        Serve al banco e ai test: su un portatile la camera non c'è, e quello
        che si vuole provare è il ciclo, non il rivelatore. Passa per la stessa
        isteresi, altrimenti proverebbe qualcosa che il dispositivo non fa.
        """
        if c_e:
            self._diverse += 1
            self._uguali = 0
        else:
            self._uguali += 1
            self._diverse = 0
        return self._decidi()

    def _decidi(self) -> bool:
        if not self.presente and self._diverse >= self.n_arrivo:
            self.presente = True
        elif self.presente and self._uguali >= self.n_uscita:
            self.presente = False
        return self.presente

    def _aspetta_che_se_ne_vada(self, fascia: np.ndarray) -> bool:
        """Il caso in cui non si è mai visto il piatto vuoto.

        Succede quando il dispositivo si accende con una bottiglia già posata:
        `c_e_qualcosa` ha buttato lo sfondo imparato, che era sbagliato, e finché la
        bottiglia non viene tolta non c'è modo di conoscerlo. Nel frattempo
        l'unica cosa che si può riconoscere è il momento in cui quella scena
        cambia del tutto — e cioè quando la bottiglia se ne va, lasciando in
        vista proprio lo sfondo che mancava.
        """
        if self._scena is None:
            self._scena = fascia
            return self.presente
        self.differenza = self._diverso(fascia, self._scena)
        if self.differenza >= self.soglia_arrivo:
            self.presente = False
            self._sfondo = fascia
            self._scena = None
            self._diverse = self._uguali = 0
        return self.presente

    def c_e_qualcosa(self) -> None:
        """Sul piatto c'è qualcosa, comunque stessero le cose fin qui.

        Lo dicono due voci, ed è la stessa notizia. L'OCR, quando legge
        un'etichetta: quello che si vede non è lo sfondo. E l'accensione di una
        installazione nuova, quando il dispositivo decide di guardare per bene
        invece di indovinare.

        In tutti e due i casi lo sfondo che il rivelatore ha in mano è
        sbagliato — se il dispositivo si è acceso con la bottiglia già posata,
        ha imparato quella, e da lì in poi il piatto gli sembrerebbe vuoto per
        sempre. Si butta, e si tornerà a conoscerlo quando la bottiglia verrà
        tolta.
        """
        self.presente = True
        self._sfondo = self._scena = None
        self._diverse = self._uguali = 0

    def non_e_una_bottiglia(self, fascia: np.ndarray) -> None:
        """L'OCR ha guardato e riguardato e non ha trovato niente da leggere.

        Serve a sbloccarsi. Lo sfondo che il rivelatore ha in mano può essere
        sbagliato — ricaricato da un'installazione precedente, imparato con una
        bottiglia davanti — e allora la differenza resta alta per sempre e il
        dispositivo crede di avere una bottiglia davanti che non c'è. Qui si
        dichiara che qualunque cosa ci sia, non è una bottiglia con
        un'etichetta, e quel che si vede diventa lo sfondo.

        Se invece era una bottiglia con l'etichetta girata, si paga una
        scansione in più quando verrà tolta: la scena cambierà, non ci sarà
        niente da leggere, e lo sfondo tornerà quello giusto. Meglio una
        scansione di troppo che un dispositivo fermo.
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
        impara quella come sfondo e resta fermo a guardarla per sempre.
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
        return quanto_diverso(a, b, self.tolleranza)


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
    """Apre il device solo per il tempo dello scatto.

    Tenere `/dev/video0` aperto non serve e costa: con il DisplayPort attivo il
    link USB scende a 2.0 e camera e audio si dividono un solo bus. Chiudendo
    lo stream prima di parlare, il problema della banda isocrona non si pone
    proprio — e la pipeline è comunque sequenziale.
    """

    def __init__(self, impostazioni: ImpostazioniCamera | None = None) -> None:
        self.imp = impostazioni or ImpostazioniCamera()
        self._percorso: str | None = None
        # Lo stream, quando è acceso. Lo condividono la sbirciata e lo scatto,
        # e il lucchetto serve perché arrivano da due thread diversi.
        self._cap: cv2.VideoCapture | None = None
        self._lucchetto = threading.Lock()

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
        mossa da 48 °C. Il timore era di caricare una board senza ventola; il
        conto dice che caricava molto di più riaprire ogni volta.

        Si spegne quando parla la voce (`chiudi`): lì la banda USB serve
        all'audio, ed è la ragione per cui questo modulo apriva e chiudeva.
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
        """Spegne lo stream. Si riaccende da solo alla prossima richiesta."""
        with self._lucchetto:
            self._spegni()

    def _spegni(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def fascia(self, frame) -> np.ndarray:
        """La striscia verticale dove sta la bottiglia, in grigio e piccola."""
        frame = self._raddrizza(frame)
        grigio = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        da, a = self.imp.fascia_bottiglia
        w = grigio.shape[1]
        striscia = grigio[:, int(w * da) : int(w * a)]
        return cv2.resize(striscia, self.imp.sbirciata).astype(np.float32)

    def sbircia(self) -> np.ndarray | None:
        """Un fotogramma solo, ridotto alla fascia della bottiglia.

        Restituisce `None` quando la camera è occupata dallo scatto: una
        sbirciata saltata non è un guasto, è una sbirciata saltata. Chi guarda
        non deve mai mettersi in coda dietro a chi lavora.
        """
        if not self._lucchetto.acquire(blocking=False):
            return None
        try:
            cap = self._apri()
            ok, frame = cap.read()
            if not ok or frame is None:
                # Uno stream che non dà più fotogrammi non guarisce da solo:
                # si spegne, e la prossima sbirciata lo riaccende.
                log.warning("sbirciata a vuoto: riaccendo lo stream")
                self._spegni()
                return None
            return self.fascia(frame)
        except CameraNonDisponibile as e:
            log.warning("sbirciata impossibile: %s", e)
            return None
        finally:
            self._lucchetto.release()

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

        Sul ritaglio, non sul fotogramma intero: gli angoli scuri
        abbasserebbero la media di una luce che sull'etichetta c'è.
        """
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        return float(cv2.cvtColor(ritaglia_centro(frame, self.imp.ritaglio),
                                  cv2.COLOR_BGR2GRAY).mean())

    def _aspetta_la_posa(self, cap, prima: float) -> float | None:
        """Legge finché la luce non si è **fermata** sul valore nuovo.

        Il driver applica la posa nuova con qualche fotogramma di ritardo —
        misurato: tre, nei due versi, su uno stream letto senza pause. Contarli
        non basta, e nel servizio, dove lo stream sta fermo fra una sbirciata e
        l'altra, il fotogramma dopo i tre scarti tornava ancora con la posa
        vecchia: la ricerca rimisurava, correggeva una seconda volta nello
        stesso verso, e finiva contro il tetto **qualunque fosse la luce** —
        sembrando pure funzionare, perché al buio il tetto è la risposta
        giusta.

        Aspettare che la luce *cominci* a muoversi non bastava neanche: il
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

    def _cerca_la_posa(self, cap) -> float:
        """Regola il tempo di posa sulla luce che c'è davvero, ora, qui.

        La posa fissa era la scelta giusta e resta giusta: con
        l'auto-esposizione servono 500-800 ms di assestamento dopo ogni cambio
        di luce e i risultati non sono ripetibili. Ma «fissa» voleva dire fissa
        alla stanza in cui si è misurata, e il dispositivo va in una sala che
        la sera abbassa le luci. Misurato al buio con l'anello bianco, a posa
        900 l'OCR non leggeva **niente**; a 3000 leggeva la denominazione.

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
        for _ in range(imp.ritocchi_posa):
            if abs(luce - imp.luce_cercata) <= imp.luce_tollerata:
                break
            nuova = int(posa * (imp.luce_cercata / max(luce, 1.0))
                        ** imp.esponente_posa)
            nuova = max(imp.posa_minima, min(imp.posa_massima, nuova))
            if nuova == posa:
                break
            imposta_posa(self.percorso, nuova)
            arrivata = self._aspetta_la_posa(cap, luce)
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

        Il chiamante è responsabile di accendere la luce **prima** e riportarla
        com'era **dopo**: questo modulo non parla con l'MCU.
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
            # contrario, la prima misura cadeva su un fotogramma catturato
            # mentre l'anello era ancora spento, e la posa partiva da un buio
            # che non c'era.
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
                self._spegni()
                raise CameraNonDisponibile(
                    f"nessun fotogramma letto da {self.percorso}"
                )

        # Prima si raddrizza, poi si ritaglia: il ritaglio è centrato, e su
        # un'immagine coricata terrebbe la fascia sbagliata della bottiglia.
        migliore = self._raddrizza(migliore)
        return Scatto(
            immagine=ritaglia_centro(migliore, self.imp.ritaglio),
            nitidezza=migliore_n,
            scartati=scartati,
            nitidezze=tutte,
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
