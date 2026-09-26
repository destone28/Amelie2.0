"""Il mirino: cosa vede la camera, con sopra quello che decide la lettura.

Serve a mettere la camera nel punto giusto rispetto alla bottiglia, che è la
cosa che dal racconto a schermo non si vede. Non mostra il fotogramma e basta:
mostra le tre cose che decidono se l'etichetta verrà letta.

1. **Il riquadro.** Il codice ritaglia la parte centrale prima di darla all'OCR
   (`ImpostazioniCamera.ritaglio_largo` e `ritaglio_alto`): fuori da quel
   rettangolo non viene mai letto niente. Il rettangolo è disegnato dove sta
   davvero, sul fotogramma **già raddrizzato** — cioè quello che il dispositivo
   legge, non quello grezzo, che è coricato e che nessuno legge.

2. **La nitidezza**, dal vivo, calcolata **sul ritaglio** e non sull'intera
   immagine — altrimenti misurerebbe la messa a fuoco di cose che l'OCR non
   vedrà mai. La messa a fuoco è fissa: la si aggiusta spostando la camera, e
   questo numero dice quando si è arrivati.

3. **Quello che legge, e cosa ci fa.** L'OCR gira di continuo su un filo a
   parte e mostra le righe trovate, poi le passa al riconoscitore e mostra che
   cosa cerca nel database e cosa trova.

Questo modulo sta nel pacchetto, e non nello script `scripts/mirino.py`, perché
lo usa anche il dispositivo: il mirino si accende dallo schermo, dal pannello
delle impostazioni, e si vede sul vetro senza un PC e senza un cavo. Una sola
copia della logica, perché due copie divergono e quella che diverge è sempre
quella che sta sul dispositivo installato.

**L'OCR non può girare dentro al flusso video.** Su questa board costa alcuni
secondi: bloccherebbe l'immagine. Gira su un filo suo, sull'ultimo fotogramma
disponibile, e chi disegna prende l'ultimo risultato pronto — vecchio di
qualche secondo, ed è esattamente quello che serve per capire cosa sta
leggendo.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

# Ogni quanto il filo che legge torna a guardare se c'è un fotogramma nuovo.
RIPOSO_S = 0.1


class LetturaContinua:
    """L'OCR e il riconoscimento, su un filo a parte.

    Chi produce i fotogrammi ne *propone* uno e va avanti per la sua strada; se
    ne arriva un altro mentre questo filo sta ancora leggendo, il vecchio si
    butta. È voluto: si vuole sapere cosa legge ADESSO, non recuperare la coda
    di quello che avrebbe letto un minuto fa.
    """

    def __init__(self, lettore=None, matcher=None) -> None:
        self.esito: dict[str, Any] = {"stato": "attendo il primo fotogramma"}
        self._lettore = lettore
        self._matcher = matcher
        # Chi ce li presta se li riprende. Ma il caso normale è che nessuno li
        # presti: **il mirino apre i suoi**, e non è uno spreco, è correttezza.
        # Riusare quelli del dispositivo sembra un risparmio — un motore OCR
        # in meno in memoria, una connessione al database in meno — ma
        # accendendo il mirino mentre una scansione è ancora in corso, due fili
        # si troverebbero dentro allo stesso motore ONNX e alla stessa
        # connessione SQLite, che non è una cosa che si fa. Il mirino resta
        # muto, e non si capisce perché.
        self._miei = lettore is None or matcher is None
        self._ultimo = None
        self._lucchetto = threading.Lock()
        self._filo: threading.Thread | None = None
        self._vivo = False

    def avvia(self) -> None:
        if self._vivo:
            return
        self._vivo = True
        self._filo = threading.Thread(target=self._gira, daemon=True)
        self._filo.start()

    def spegni(self) -> None:
        self._vivo = False

    def proponi(self, fotogramma) -> None:
        with self._lucchetto:
            self._ultimo = fotogramma

    def _prendi(self):
        with self._lucchetto:
            fotogramma, self._ultimo = self._ultimo, None
        return fotogramma

    def _gira(self) -> None:
        lettore, matcher = self._lettore, self._matcher
        if lettore is None:
            from .ocr import Lettore

            lettore = Lettore()
        if matcher is None:
            from .matcher import Matcher

            matcher = Matcher()
        try:
            while self._vivo:
                fotogramma = self._prendi()
                if fotogramma is None:
                    time.sleep(RIPOSO_S)
                    continue
                self.esito = self._leggi(lettore, matcher, fotogramma)
        finally:
            # Si chiude quello che si e' aperto, e ci si lascia dietro la
            # memoria: spento il mirino, il secondo motore OCR non deve restare
            # in giro ad aspettare che qualcuno lo riaccenda.
            if self._miei:
                matcher.chiudi()
            lettore = matcher = None

    @staticmethod
    def _leggi(lettore, matcher, fotogramma) -> dict[str, Any]:
        inizio = time.monotonic()
        try:
            lettura = lettore.leggi(fotogramma)
            righe = [r.testo for r in lettura.righe]
            fatti = matcher.cerca(righe)
        except Exception as e:                              # noqa: BLE001
            # Un mirino che si spegne quando l'OCR inciampa non serve a
            # nessuno: proprio quello è il momento in cui lo si sta guardando.
            log.warning("mirino, lettura fallita: %s", e)
            return {"stato": f"errore: {e.__class__.__name__}: {e}"}
        return {
            "stato": "letto",
            "durata": round(time.monotonic() - inizio, 1),
            "righe": righe,
            "livello": fatti.livello.value,
            "sicurezza": round(fatti.sicurezza),
            "nome": fatti.nome or "",
            "cantina": fatti.cantina or "",
            "annata": fatti.annata or "",
            "vitigni": fatti.vitigni[:3],
            "candidati": fatti.candidati[:3],
        }


def disegna(frame, camera):
    """Sovrascrive al fotogramma quello che decide la lettura.

    Il rettangolo è **quello vero**, chiesto alla camera: se il dispositivo ha
    trovato la bottiglia, è il riquadro di quella bottiglia; se no, è quello
    fisso. Disegnarne uno diverso da quello in uso farebbe tarare
    l'inquadratura contro una linea che non decide niente.

    Restituisce `(jpeg, ritaglio, nitidezza)`. Il ritaglio è una **copia**, e
    non è un dettaglio: il ritaglio è una vista sullo stesso blocco di memoria,
    e senza la copia il rettangolo e la scritta disegnati qui finirebbero
    dentro all'immagine che l'OCR sta per leggere. La prima riga riconosciuta
    sarebbe «nitidezza 60 (soglia 40)», cioè la sovrimpressione di questo
    strumento: uno strumento di misura che misura se stesso.
    """
    import cv2

    from .capture import SOGLIA_NITIDEZZA, nitidezza

    h, w = frame.shape[:2]
    # Dove sta davvero il ritaglio dentro al fotogramma: la camera lo prende
    # centrato quando e' fisso, e sulla bottiglia quando l'ha trovata.
    x0, y0, x1, y1 = camera.posto(frame)
    ritagliato = frame[y0:y1, x0:x1]
    nh, nw = ritagliato.shape[:2]
    n = nitidezza(ritagliato)
    copia = ritagliato.copy()
    colore = (90, 220, 60) if n >= SOGLIA_NITIDEZZA else (60, 80, 240)   # BGR

    cv2.rectangle(frame, (x0, y0), (x0 + nw, y0 + nh), colore, 3)
    # Le due mezzerie: centrare l'etichetta a occhio, senza righello.
    cv2.line(frame, (w // 2, y0), (w // 2, y0 + nh), colore, 1)
    cv2.line(frame, (x0, h // 2), (x0 + nw, h // 2), colore, 1)
    cv2.putText(frame, f"nitidezza {n:.0f}  (soglia {SOGLIA_NITIDEZZA:.0f})",
                (x0 + 12, y0 + 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                colore, 2, cv2.LINE_AA)

    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return (jpg.tobytes() if ok else None), copia, n


class Mirino:
    """Tiene un filo che acquisisce, e tutti gli altri leggono l'ultimo pronto.

    I fotogrammi non li produce chi guarda il video. Se fosse così, l'OCR non
    partirebbe finché non si apre la pagina — resterebbe a «attendo il primo
    fotogramma» — e due finestre aperte si contenderebbero la camera prendendo
    mezzi fotogrammi a testa.
    """

    def __init__(self, camera, lettura: LetturaContinua | None = None,
                 regola_la_luce: bool = True, presenza=None) -> None:
        self.camera = camera
        self.lettura = lettura
        # Chi sa dove sta la bottiglia. Col mirino acceso il ciclo e' fermo e
        # nessun altro glielo chiede: glielo si chiede da qui, altrimenti il
        # rettangolo disegnato sarebbe quello fisso mentre il dispositivo, a
        # ciclo acceso, ne userebbe un altro - e si tarerebbe contro una linea
        # che non decide niente.
        self.presenza = presenza
        self.regola = regola_la_luce
        self.nitidezza = 0.0
        self._jpg: bytes | None = None
        self._filo: threading.Thread | None = None
        self._vivo = False

    @property
    def acceso(self) -> bool:
        return self._vivo

    @property
    def esito(self) -> dict[str, Any]:
        if self.lettura is None:
            return {"stato": "OCR spento"}
        return self.lettura.esito

    def accendi(self) -> None:
        if self._vivo:
            return
        self._vivo = True
        self._jpg = None
        if self.lettura is not None:
            self.lettura.avvia()
        self._filo = threading.Thread(target=self._acquisisci, daemon=True)
        self._filo.start()

    def spegni(self) -> None:
        self._vivo = False
        if self.lettura is not None:
            self.lettura.spegni()
        self._jpg = None

    def ultimo(self) -> bytes | None:
        return self._jpg

    def _acquisisci(self) -> None:
        # La posa si cerca QUI, sul filo del mirino, e non da chi ha premuto
        # l'interruttore: cercarla apre la camera e puo' aspettare che una
        # scansione in corso la lasci. Fatto da chi risponde al tocco, quello
        # e' il ciclo di eventi del server che si ferma - cioe' lo schermo, i
        # pulsanti e il racconto, tutti insieme, per una decina di secondi.
        if self.regola:
            try:
                self.camera.regola_la_luce()
            except Exception as e:                          # noqa: BLE001
                log.warning("mirino, posa non regolata: %s", e)
        while self._vivo:
            frame = self.camera.fotogramma()
            if frame is None:
                time.sleep(RIPOSO_S)
                continue
            if self.presenza is not None:
                self.presenza.guarda(self.camera.fascia(frame))
                self.camera.riquadro = self.presenza.riquadro()
            jpg, ritaglio, n = disegna(frame, self.camera)
            if jpg is None:
                continue
            self._jpg, self.nitidezza = jpg, n
            if self.lettura is not None:
                # All'OCR va il RITAGLIO, non l'intera immagine: è quello che
                # vede il dispositivo, e leggere di più qui darebbe un
                # risultato che a regime non si otterrebbe.
                self.lettura.proponi(ritaglio)
