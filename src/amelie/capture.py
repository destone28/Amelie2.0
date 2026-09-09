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

Il ritaglio centrale al 55-60% porta la distorsione a barile sotto l'1% e
rimuove la vignettatura, che sta agli angoli: nessuna calibrazione necessaria.
"""

from __future__ import annotations

import glob
import logging
import subprocess
import time
from dataclasses import dataclass, field
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

    # Esposizione fissa. `exposure_time_absolute` è in unità da 100 µs:
    # 300 = 30 ms. Va tarato sul campo con l'anello di luce acceso.
    esposizione: int = 300
    guadagno: int = 0
    temperatura_colore: int = 4600

    # Raffica
    fotogrammi_da_scartare: int = 5
    fotogrammi_raffica: int = 5

    # Ritaglio centrale, frazione del fotogramma tenuta per lato.
    ritaglio: float = 0.58

    # Attesa fra accensione della luce dello scatto e primo fotogramma utile.
    assestamento_luce_s: float = 0.15


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

    @property
    def percorso(self) -> str:
        """Il device della camera, risolto una volta sola e poi ricordato."""
        if self._percorso is None:
            self._percorso = self.imp.device or trova_camera(self.imp.nome_camera)
            log.info("camera: %s", self._percorso)
        return self._percorso

    def _apri(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.percorso, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise CameraNonDisponibile(f"impossibile aprire {self.percorso}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.imp.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.imp.larghezza)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.imp.altezza)
        # Un buffer corto riduce, ma non elimina, i fotogrammi vecchi: lo
        # scarto esplicito qui sotto resta necessario.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def scatta(self, *, attesa_luce: float | None = None) -> Scatto:
        """Esegue una raffica e restituisce il fotogramma più nitido.

        Il chiamante è responsabile di accendere la luce **prima** e riportarla
        com'era **dopo**: questo modulo non parla con l'MCU.
        """
        attesa = self.imp.assestamento_luce_s if attesa_luce is None else attesa_luce
        cap = self._apri()
        try:
            if attesa > 0:
                time.sleep(attesa)

            scartati = 0
            for _ in range(self.imp.fotogrammi_da_scartare):
                if cap.grab():
                    scartati += 1

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
                raise CameraNonDisponibile(
                    f"nessun fotogramma letto da {self.percorso}"
                )
        finally:
            cap.release()

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
