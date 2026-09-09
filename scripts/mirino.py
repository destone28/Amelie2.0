#!/usr/bin/env python3
"""Il mirino: la camera della board, in diretta sul PC, con quello che legge.

    ssh arduino@amelie.local 'sudo systemctl stop amelie'
    ssh arduino@amelie.local 'cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/mirino.py'
    # poi dal PC, nel browser:  http://<indirizzo-della-board>:8090/

Serve a mettere la camera nel punto giusto rispetto alla bottiglia, che è la
cosa che dallo schermo del dispositivo non si vede. Non mostra il fotogramma e
basta: mostra le **tre cose che decidono se l'etichetta verrà letta**.

1. IL RIQUADRO. Il codice ritaglia la parte centrale prima di darla all'OCR
   (`ImpostazioniCamera.ritaglio`, oggi l'80%): fuori da quel rettangolo non
   viene mai letto niente. Il rettangolo è disegnato dove sta davvero, e con
   `--ritaglio` si può stringere o allargare per capire quanto conta.

2. LA NITIDEZZA, dal vivo. È la varianza del laplaciano, la stessa misura che
   `amelie.capture` usa per scegliere il fotogramma migliore della raffica, ed è
   calcolata **sul ritaglio**, non sull'intera immagine — altrimenti misurerebbe
   la messa a fuoco di cose che l'OCR non vedrà mai. Sopra la soglia il numero è
   verde. La messa a fuoco è fissa: la si aggiusta spostando la camera, e questo
   numero dice quando si è arrivati.

3. LA LUCE. Con `--luce` l'anello va a bianco come durante la raffica vera, così
   si inquadra con la luce che ci sarà davvero, non con quella della stanza.

4. QUELLO CHE LEGGE, e cosa ci fa. Con `--ocr` gira l'OCR di continuo su un filo
   a parte e mostra le righe trovate, poi le passa al riconoscitore e mostra
   **che cosa cerca nel database e cosa trova**: il livello, la sicurezza, il
   vino, e i candidati quando è in dubbio.

   L'OCR costa alcuni secondi a giro su questa board, quindi non va a ogni
   fotogramma: gira sull'ultimo disponibile e aggiorna quando ha finito. Il
   video resta fluido.

**Va lanciato a servizio FERMO.** La camera si apre un processo per volta, e
`amelie.capture` la apre solo per il tempo dello scatto proprio per questo.

**E cambia l'esposizione**: la mette in manuale come fa il dispositivo, con gli
stessi valori. Quando si chiude, il servizio la rimette da sé al primo scatto.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

PAGINA = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Amelie - mirino</title><style>
 body{margin:0;background:#14100f;color:#F4EDE3;font-family:system-ui,sans-serif;
      display:flex;gap:16px;padding:16px;align-items:flex-start;flex-wrap:wrap}
 img{max-width:min(62vw,900px);border-radius:8px;box-shadow:0 8px 40px #0008}
 aside{flex:1;min-width:300px;max-width:44ch;font-size:14px;line-height:1.5}
 h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;
    color:#8A6B30;margin:18px 0 6px;font-weight:600}
 h2:first-child{margin-top:0}
 p{color:#B9A99A;margin:0}
 b{color:#E3B457}
 ul{margin:0;padding-left:18px;color:#F4EDE3}
 li{margin:2px 0}
 code{color:#F4EDE3;background:#2A0F0C;padding:1px 5px;border-radius:4px}
 .certo{color:#5CDC7A}.dubbio{color:#FF9628}.nulla{color:#EE5F4F}
</style></head><body>
<img src="/flusso" alt="camera">
<aside>
 <h2>Come si legge</h2>
 <p>Il rettangolo è la parte che va all'OCR: fuori di lì non viene mai letto
 niente. Il numero è la <b>nitidezza</b> misurata dentro al rettangolo, verde
 sopra la soglia. La messa a fuoco è fissa: si aggiusta spostando la camera.</p>
 <div id="lettura"></div>
</aside>
<script>
async function aggiorna() {
  try {
    const d = await (await fetch("/lettura", {cache: "no-store"})).json();
    const e = document.getElementById("lettura");
    if (d.stato !== "letto") { e.innerHTML = "<h2>OCR</h2><p>" + d.stato + "</p>"; return; }
    const cl = d.livello === "certo" ? "certo"
             : d.livello === "dubbio" ? "dubbio" : "nulla";
    e.innerHTML =
      "<h2>Cosa legge (" + d.durata + " s)</h2>" +
      (d.righe.length ? "<ul>" + d.righe.map(r =>
          "<li><code>" + r.replace(/[<&]/g, c => c === "<" ? "&lt;" : "&amp;")
          + "</code></li>").join("") + "</ul>"
        : "<p>nessuna riga di testo</p>") +
      "<h2>Cosa trova nel database</h2>" +
      "<p><b class=" + cl + ">" + d.livello + "</b> · sicurezza "
        + d.sicurezza + "</p>" +
      (d.nome ? "<p><b>" + d.nome + "</b><br>" + d.cantina
        + (d.annata ? " · " + d.annata : "") + "</p>" : "<p>nessun vino</p>") +
      (d.vitigni.length ? "<p>vitigni: " + d.vitigni.join(", ") + "</p>" : "") +
      (d.candidati.length ? "<h2>Candidati</h2><ul>" +
        d.candidati.map(c => "<li>" + c + "</li>").join("") + "</ul>" : "");
  } catch (e) { /* la board sta rispondendo a qualcos'altro */ }
}
aggiorna(); setInterval(aggiorna, 1200);
</script>
</body></html>""".encode("utf-8")


class Lettura:
    """L'OCR e il riconoscimento, su un filo a parte.

    Su questa board l'OCR costa alcuni secondi: farlo dentro al flusso video
    lo bloccherebbe. Gira qui in continuo sull'ultimo fotogramma disponibile, e
    chi disegna prende l'ultimo risultato pronto — che è vecchio di qualche
    secondo, ed è esattamente quello che serve per capire cosa sta leggendo.
    """

    def __init__(self) -> None:
        self.esito: dict = {"stato": "attendo il primo fotogramma"}
        self._ultimo = None
        self._lucchetto = threading.Lock()
        self._filo = threading.Thread(target=self._gira, daemon=True)
        self._vivo = True

    def avvia(self) -> None:
        self._filo.start()

    def proponi(self, frame) -> None:
        with self._lucchetto:
            self._ultimo = frame

    def _gira(self) -> None:
        from amelie.matcher import Matcher
        from amelie.ocr import Lettore

        lettore, matcher = Lettore(), Matcher()
        try:
            while self._vivo:
                with self._lucchetto:
                    frame = self._ultimo
                    self._ultimo = None
                if frame is None:
                    time.sleep(0.1)
                    continue
                t = time.monotonic()
                try:
                    lettura = lettore.leggi(frame)
                    righe = [r.testo for r in lettura.righe]
                    fatti = matcher.cerca(righe)
                    self.esito = {
                        "stato": "letto",
                        "durata": round(time.monotonic() - t, 1),
                        "righe": righe,
                        "livello": fatti.livello.value,
                        "sicurezza": round(fatti.sicurezza),
                        "nome": fatti.nome or "",
                        "cantina": fatti.cantina or "",
                        "annata": fatti.annata or "",
                        "vitigni": fatti.vitigni[:3],
                        "candidati": fatti.candidati[:3],
                    }
                except Exception as e:                      # noqa: BLE001
                    self.esito = {"stato": f"errore: {e.__class__.__name__}: {e}"}
        finally:
            matcher.chiudi()

    def spegni(self) -> None:
        self._vivo = False


class Mirino:
    """Tiene la camera aperta e prepara i fotogrammi per chi li chiede."""

    def __init__(self, imp, con_luce: bool, lettura=None) -> None:
        import cv2

        from amelie.capture import Camera, blocca_esposizione

        self.cv2 = cv2
        self.lettura = lettura
        self.camera = Camera(imp)
        self.percorso = self.camera.percorso
        blocca_esposizione(imp, self.percorso)
        self.cap = self.camera._apri()
        self.con_luce = con_luce
        self._vivo = False
        self._jpg: bytes | None = None
        self._filo = None
        self._ponte = None
        if con_luce:
            self._accendi()

    def _accendi(self) -> None:
        from amelie.bridge import BIANCO_SCATTO, Ponte

        try:
            self._ponte = Ponte(timeout=2.0)
            self._ponte.anello(BIANCO_SCATTO)
            print("  anello a bianco, come durante la raffica")
        except Exception as e:                              # noqa: BLE001
            self._ponte = None
            print(f"  anello non acceso ({e.__class__.__name__}): "
                  f"stai inquadrando con la sola luce della stanza")

    def avvia(self) -> None:
        """Un filo solo acquisisce, e tutti gli altri leggono l'ultimo pronto.

        Prima i fotogrammi li produceva chi guardava il video, e da lì venivano
        due difetti: l'OCR non partiva finché non si apriva la pagina — restava
        a «attendo il primo fotogramma» — e due finestre aperte si contendevano
        la camera prendendo mezzi fotogrammi a testa.
        """
        self._vivo = True
        self._jpg = None
        self._filo = threading.Thread(target=self._acquisisci, daemon=True)
        self._filo.start()

    def _acquisisci(self) -> None:
        while self._vivo:
            jpg = self._prepara()
            if jpg is None:
                time.sleep(0.05)
                continue
            self._jpg = jpg

    def ultimo(self) -> bytes | None:
        return self._jpg

    def spegni(self) -> None:
        self._vivo = False
        try:
            self.cap.release()
        except Exception:                                   # noqa: BLE001
            pass
        if self._ponte is not None:
            from amelie.bridge import AMBRA
            try:
                self._ponte.anello(AMBRA)
            except Exception:                               # noqa: BLE001
                pass

    def _prepara(self) -> bytes | None:
        from amelie.capture import SOGLIA_NITIDEZZA, nitidezza, ritaglia_centro

        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        cv2 = self.cv2
        h, w = frame.shape[:2]
        f = self.camera.imp.ritaglio
        nh, nw = int(h * f), int(w * f)
        y0, x0 = (h - nh) // 2, (w - nw) // 2

        # La nitidezza si misura DENTRO il ritaglio: fuori di li' l'OCR non
        # guarda, e includerlo darebbe un numero che non decide niente.
        ritagliato = ritaglia_centro(frame, f)
        n = nitidezza(ritagliato)
        buona = n >= SOGLIA_NITIDEZZA
        # All'OCR va il RITAGLIO, non l'intera immagine: e' quello che vede il
        # dispositivo, e leggere di piu' qui darebbe un risultato che a regime
        # non si otterrebbe.
        #
        # E va una COPIA. `ritaglia_centro` restituisce una vista sullo stesso
        # blocco di memoria, quindi il rettangolo e la scritta disegnati qui
        # sotto finivano dentro all'immagine che l'OCR stava per leggere: la
        # prima riga riconosciuta era «nitidezza 60 (soglia 40)», cioe' la
        # sovrimpressione di questo strumento. Uno strumento di misura che
        # misura se stesso.
        if self.lettura is not None:
            self.lettura.proponi(ritagliato.copy())
        colore = (90, 220, 60) if buona else (60, 80, 240)      # BGR

        cv2.rectangle(frame, (x0, y0), (x0 + nw, y0 + nh), colore, 3)
        # Le due mezzerie: centrare l'etichetta a occhio, senza righello.
        cv2.line(frame, (w // 2, y0), (w // 2, y0 + nh), colore, 1)
        cv2.line(frame, (x0, h // 2), (x0 + nw, h // 2), colore, 1)
        cv2.putText(frame, f"nitidezza {n:.0f}  (soglia {SOGLIA_NITIDEZZA:.0f})",
                    (x0 + 12, y0 + 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    colore, 2, cv2.LINE_AA)

        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return jpg.tobytes() if ok else None


def indirizzo_locale() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))        # non manda niente: serve la rotta
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def servi(mirino: Mirino, porta: int) -> None:
    class Gestore(BaseHTTPRequestHandler):
        def log_message(self, *a):        # niente rumore a ogni fotogramma
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(PAGINA)))
                self.end_headers()
                self.wfile.write(PAGINA)
                return
            if self.path == "/lettura":
                import json
                corpo = json.dumps(
                    mirino.lettura.esito if mirino.lettura is not None
                    else {"stato": "OCR spento: rilancia con --ocr"},
                    ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
                return
            if self.path != "/flusso":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=fotogramma")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                ultimo = None
                while True:
                    jpg = mirino.ultimo()
                    if jpg is None or jpg is ultimo:
                        time.sleep(0.02)
                        continue
                    ultimo = jpg
                    self.wfile.write(b"--fotogramma\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(
                        f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass                       # la finestra e' stata chiusa

    server = ThreadingHTTPServer(("0.0.0.0", porta), Gestore)
    server.daemon_threads = True
    print(f"\n  mirino su  http://{indirizzo_locale()}:{porta}/")
    print("  Ctrl-C per chiudere.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  chiudo.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--porta", type=int, default=8090)
    ap.add_argument("--luce", action="store_true",
                    help="anello a bianco, come durante la raffica vera")
    ap.add_argument("--esposizione", type=int,
                    help="tempo di posa in unita' da 100 us (300 = 30 ms)")
    ap.add_argument("--ocr", action="store_true",
                    help="legge di continuo e mostra cosa trova nel database")
    ap.add_argument("--ritaglio", type=float,
                    help="frazione del fotogramma che va all'OCR (predefinita "
                         "da ImpostazioniCamera)")
    args = ap.parse_args()

    from dataclasses import replace

    from amelie.capture import CameraNonDisponibile, ImpostazioniCamera

    imp = ImpostazioniCamera()
    if args.esposizione:
        imp = replace(imp, esposizione=args.esposizione)
    if args.ritaglio:
        imp = replace(imp, ritaglio=args.ritaglio)

    lettura = None
    if args.ocr:
        print("  OCR acceso: il primo giro richiede qualche secondo")
        lettura = Lettura()
        lettura.avvia()

    try:
        mirino = Mirino(imp, args.luce, lettura)
    except CameraNonDisponibile as e:
        sys.exit(f"camera non disponibile: {e}\n"
                 f"Il servizio e' fermo?  sudo systemctl stop amelie")
    mirino.avvia()
    print(f"  camera:   {mirino.percorso}")
    print(f"  posa:     {imp.esposizione} (= {imp.esposizione / 10:.0f} ms)")
    print(f"  ritaglio: {imp.ritaglio:.0%} del fotogramma")
    try:
        servi(mirino, args.porta)
    finally:
        mirino.spegni()
        if lettura is not None:
            lettura.spegni()


if __name__ == "__main__":
    main()
