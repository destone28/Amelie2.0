#!/usr/bin/env python3
"""Il mirino: la camera della board, in diretta sul PC, con quello che legge.

    ssh -t arduino@amelie.local 'sudo systemctl stop amelie'
    ssh arduino@amelie.local 'cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/mirino.py'
    # poi dal PC, nel browser:  http://<indirizzo-della-board>:8090/

**Lo stesso mirino sta anche sul dispositivo**, e si accende dal vetro: angolo
in basso a destra tenuto tre secondi, poi l'interruttore «Debug camera». Quello non
richiede di fermare il servizio ne' di avere un PC, ed e' la strada normale.
Questo script serve a chi vuole guardare da lontano, su uno schermo grande,
con la posa o il ritaglio cambiati da riga di comando senza toccare il codice.

La logica e' la stessa: `amelie.mirino`. Qui attorno c'e' solo cio' che vale al
banco - l'anello acceso a mano e un server che non e' quello del dispositivo.

Serve a mettere la camera nel punto giusto rispetto alla bottiglia, che è la
cosa che dallo schermo del dispositivo non si vede. Non mostra il fotogramma e
basta: mostra le **tre cose che decidono se l'etichetta verrà letta**.

1. IL RIQUADRO. Il codice ritaglia la parte centrale prima di darla all'OCR
   (`ImpostazioniCamera.ritaglio_largo` e `ritaglio_alto`): fuori da quel
   rettangolo non viene mai letto niente. Il rettangolo è disegnato dove sta
   davvero, e con `--ritaglio` e `--ritaglio-alto` si può stringere o allargare
   per capire quanto conta.

2. LA NITIDEZZA, dal vivo. È la varianza del laplaciano, la stessa misura che
   `amelie.capture` usa per scegliere il fotogramma migliore della raffica, ed è
   calcolata **sul ritaglio**, non sull'intera immagine — altrimenti misurerebbe
   la messa a fuoco di cose che l'OCR non vedrà mai. Sopra la soglia il numero è
   verde. La messa a fuoco si regola ruotando l'obiettivo M12 nel suo supporto, e
   questo numero dice quando si è arrivati.

3. LA LUCE. Con `--luce` l'anello va a bianco come durante la raffica vera, così
   si inquadra con la luce che ci sarà davvero, non con quella della stanza.

4. QUELLO CHE LEGGE, e cosa ci fa. Con `--ocr` gira l'OCR di continuo su un filo
   a parte e mostra le righe trovate, poi le passa al riconoscitore e mostra
   **che cosa cerca nel database e cosa trova**: il livello, la sicurezza, il
   vino, e i candidati quando è in dubbio.

   L'OCR costa alcuni secondi a giro su questa board, quindi non va a ogni
   fotogramma: gira sull'ultimo disponibile e aggiorna quando ha finito. Il
   video resta fluido.

**Va lanciato a servizio FERMO**: la camera si apre un processo per volta, e il
dispositivo, che riconosce la bottiglia sul piatto con la camera, tiene lo
stream acceso fra una sbirciata e l'altra. A servizio acceso questo mirino non
vede niente.

**E cambia l'esposizione**: la mette in manuale come fa il dispositivo, con gli
stessi valori. Quando si chiude, il servizio la rimette da sé al primo scatto.
"""
from __future__ import annotations

import argparse
import socket
import sys
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
 sopra la soglia. La messa a fuoco si regola ruotando l'obiettivo M12.</p>
 <div id="lettura"></div>
</aside>
<script>
async function aggiorna() {
  try {
    const d = await (await fetch("/lettura", {cache: "no-store"})).json();
    const e = document.getElementById("lettura");
    if (d.stato !== "letto") { e.innerHTML = "<h2>OCR</h2><p>" + d.stato + "</p>"; return; }
    const cl = d.fascia || "nulla";
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


class MirinoDaBanco:
    """Il mirino con attorno quello che serve a usarlo da un PC.

    Il mirino vero e proprio sta in `amelie.mirino`, ed è lo stesso che il
    dispositivo mostra sul suo vetro: una copia sola, perché due copie
    divergono, e quella che resta indietro è sempre quella sul dispositivo.
    Qui restano le due cose che valgono solo al banco — accendere l'anello a
    mano e dire a voce alta cosa si sta guardando.
    """

    def __init__(self, imp, con_luce: bool, con_ocr: bool) -> None:
        from amelie.capture import Camera, blocca_esposizione
        from amelie.mirino import LetturaContinua, Mirino

        self.camera = Camera(imp)
        self.percorso = self.camera.percorso
        blocca_esposizione(imp, self.percorso)
        # La posa NON si ricerca: qui la sceglie chi ha lanciato il comando,
        # con `--esposizione`, e ricercarla vorrebbe dire scavalcarlo. Sul
        # dispositivo e' il contrario: li' nessuno la sceglie, e il mirino deve
        # mostrare l'inquadratura con la posa che ci sara' davvero.
        self.mirino = Mirino(self.camera,
                             LetturaContinua() if con_ocr else None,
                             regola_la_luce=False)
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
        self.mirino.accendi()

    def ultimo(self):
        return self.mirino.ultimo()

    @property
    def esito(self) -> dict:
        return self.mirino.esito

    def spegni(self) -> None:
        self.mirino.spegni()
        self.camera.chiudi()
        if self._ponte is not None:
            from amelie.bridge import AMBRA
            try:
                self._ponte.anello(AMBRA)
            except Exception:                               # noqa: BLE001
                pass


def indirizzo_locale() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))        # non manda niente: serve la rotta
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def servi(mirino: MirinoDaBanco, porta: int) -> None:
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
                esito = mirino.esito
                if esito.get("stato") == "OCR spento":
                    esito = {"stato": "OCR spento: rilancia con --ocr"}
                corpo = json.dumps(esito, ensure_ascii=False).encode("utf-8")
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
                    help="frazione di LARGHEZZA che va all'OCR (predefinita da "
                         "ImpostazioniCamera)")
    ap.add_argument("--ritaglio-alto", type=float,
                    help="frazione di ALTEZZA che va all'OCR")
    args = ap.parse_args()

    from dataclasses import replace

    from amelie.capture import CameraNonDisponibile, ImpostazioniCamera

    imp = ImpostazioniCamera()
    if args.esposizione:
        imp = replace(imp, esposizione=args.esposizione)
    if args.ritaglio:
        imp = replace(imp, ritaglio_largo=args.ritaglio)
    if args.ritaglio_alto:
        imp = replace(imp, ritaglio_alto=args.ritaglio_alto)

    if args.ocr:
        print("  OCR acceso: il primo giro richiede qualche secondo")

    try:
        mirino = MirinoDaBanco(imp, args.luce, args.ocr)
    except CameraNonDisponibile as e:
        sys.exit(f"camera non disponibile: {e}\n"
                 f"Il servizio e' fermo?  sudo systemctl stop amelie")
    mirino.avvia()
    print(f"  camera:   {mirino.percorso}")
    print(f"  posa:     {imp.esposizione} (= {imp.esposizione / 10:.0f} ms)")
    print(f"  ritaglio: {imp.ritaglio_largo:.0%} in larghezza, "
          f"{imp.ritaglio_alto:.0%} in altezza")
    try:
        servi(mirino, args.porta)
    finally:
        mirino.spegni()


if __name__ == "__main__":
    main()
