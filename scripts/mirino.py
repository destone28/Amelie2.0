#!/usr/bin/env python3
"""Il mirino: la camera della board, in diretta sul PC.

    ssh arduino@amelie.local 'sudo systemctl stop amelie'
    ssh arduino@amelie.local 'cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/mirino.py'
    # poi dal PC, nel browser:  http://<indirizzo-della-board>:8090/

Serve a mettere la camera nel punto giusto rispetto alla bottiglia, che è la
cosa che dallo schermo del dispositivo non si vede. Non mostra il fotogramma e
basta: mostra le **tre cose che decidono se l'etichetta verrà letta**.

1. IL RIQUADRO. Il codice ritaglia il 58% centrale prima di darlo all'OCR
   (`ImpostazioniCamera.ritaglio`): fuori da quel rettangolo l'obiettivo da 130°
   distorce, e quello che ci finisce non viene mai letto. Il rettangolo è
   disegnato dove sta davvero.

2. LA NITIDEZZA, dal vivo. È la varianza del laplaciano, la stessa misura che
   `amelie.capture` usa per scegliere il fotogramma migliore della raffica, ed è
   calcolata **sul ritaglio**, non sull'intera immagine — altrimenti misurerebbe
   la messa a fuoco di cose che l'OCR non vedrà mai. Sopra la soglia il numero è
   verde. La messa a fuoco è fissa: la si aggiusta spostando la camera, e questo
   numero dice quando si è arrivati.

3. LA LUCE. Con `--luce` l'anello va a bianco come durante la raffica vera, così
   si inquadra con la luce che ci sarà davvero, non con quella della stanza.

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
 body{margin:0;background:#14100f;color:#F4EDE3;
      font-family:system-ui,sans-serif;display:flex;flex-direction:column;
      align-items:center;gap:12px;padding:16px}
 img{max-width:100%;border-radius:8px;box-shadow:0 8px 40px #0008}
 p{color:#B9A99A;margin:0;font-size:14px;line-height:1.5;max-width:60ch}
 b{color:#E3B457}
</style></head><body>
<img src="/flusso" alt="camera">
<p>Il rettangolo è il <b>58% centrale</b>: quello che sta fuori non viene mai
letto. Il numero è la <b>nitidezza</b> misurata dentro al rettangolo — verde
quando è sopra la soglia. La messa a fuoco è fissa: si aggiusta spostando la
camera, non l'obiettivo.</p>
</body></html>""".encode("utf-8")


class Mirino:
    """Tiene la camera aperta e prepara i fotogrammi per chi li chiede."""

    def __init__(self, imp, con_luce: bool) -> None:
        import cv2

        from amelie.capture import Camera, blocca_esposizione

        self.cv2 = cv2
        self.camera = Camera(imp)
        self.percorso = self.camera.percorso
        blocca_esposizione(imp, self.percorso)
        self.cap = self.camera._apri()
        self.con_luce = con_luce
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

    def spegni(self) -> None:
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

    def fotogramma(self) -> bytes | None:
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
        n = nitidezza(ritaglia_centro(frame, f))
        buona = n >= SOGLIA_NITIDEZZA
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
    lucchetto = threading.Lock()

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
            if self.path != "/flusso":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=fotogramma")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    # Un fotogramma per volta: la camera e' una sola, e due
                    # lettori che si contendono lo stesso device danno
                    # fotogrammi a meta'.
                    with lucchetto:
                        jpg = mirino.fotogramma()
                    if jpg is None:
                        time.sleep(0.05)
                        continue
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
    args = ap.parse_args()

    from dataclasses import replace

    from amelie.capture import CameraNonDisponibile, ImpostazioniCamera

    imp = ImpostazioniCamera()
    if args.esposizione:
        imp = replace(imp, esposizione=args.esposizione)

    try:
        mirino = Mirino(imp, args.luce)
    except CameraNonDisponibile as e:
        sys.exit(f"camera non disponibile: {e}\n"
                 f"Il servizio e' fermo?  sudo systemctl stop amelie")
    print(f"  camera: {mirino.percorso}")
    print(f"  posa:   {imp.esposizione} (= {imp.esposizione / 10:.0f} ms)")
    try:
        servi(mirino, args.porta)
    finally:
        mirino.spegni()


if __name__ == "__main__":
    main()
