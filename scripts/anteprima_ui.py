#!/usr/bin/env python3
"""Fotografa ogni schermata dell'interfaccia senza toccare il dispositivo.

    python3 scripts/anteprima_ui.py [cartella] [--larghezza 1280] [--altezza 720]

Prende `index.html`, sostituisce il flusso di eventi vero con uno finto che
riproduce una sequenza di messaggi, e rende la pagina con Chromium senza
finestra. Serve per le viste che dal vetro non si raggiungono a comando: il
racconto col player, la schermata di conferma, il guasto, il caso in cui la
lingua scelta non ha una voce.

**Un limite da ricordare**: rende col font di ripiego se `fonts-ebgaramond` non
è installato sulla macchina che lo esegue. Un Garamond ha l'occhio medio molto
più piccolo di un Noto Serif, quindi a parità di corpo cambia la misura
apparente del testo e dove va a capo. La prova che conta si fa sulla board.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PAGINA = RADICE / "src" / "amelie" / "ui" / "static" / "index.html"

# Le scritte fisse arrivano dal server, quindi vanno finte anche qui.
VOLUME = {"tipo": "volume", "valore": 60, "passo": 10, "attivo": True}

LINGUA_IT = {"tipo": "lingua", "lingua": "it", "disponibili": ["it", "en"],
             "invito": "Appoggi una bottiglia", "domanda": "Quale di questi?",
             "voce_muta": False, "avviso_muto": ""}
LINGUA_EN = {"tipo": "lingua", "lingua": "en", "disponibili": ["it", "en"],
             "invito": "Place a bottle", "domanda": "Which one is it?",
             "voce_muta": False, "avviso_muto": ""}

RACCONTO_IT = [
    "Questo è il «Cannubi Barolo» di Marchesi di Barolo annata 2016.",
    "Il vitigno di Barolo e Barbaresco, nelle Langhe.",
    "Colore scarico che inganna: sotto c'è una struttura tannica fra le più "
    "longeve al mondo.",
    "È un vino di grande struttura, con bella acidità.",
    "Si accompagna bene a manzo, cacciagione e agnello.",
    "Si serve fra 17 e 19 gradi.",
]
RACCONTO_EN = [
    "This is the “Cannubi Barolo” by Marchesi di Barolo 2016 vintage.",
    "The grape of Barolo and Barbaresco, in the Langhe hills.",
    "Its pale colour is deceptive: beneath it lies one of the longest-lived "
    "tannic structures in the world.",
    "It is very full-bodied, with bright acidity.",
    "It goes well with beef, game meat and lamb.",
    "Best served between 17 and 19 degrees.",
]

SCENE: dict[str, list[dict]] = {
    "attesa": [LINGUA_IT, {"tipo": "stato", "vista": "attesa"}],

    "lavoro": [LINGUA_IT, {"tipo": "stato", "vista": "lavoro",
                           "frase": "Sto leggendo l'etichetta…"}],

    "racconto": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": False},
        {"tipo": "racconto", "origine": "template", "frasi": RACCONTO_IT},
        {"tipo": "riproduzione", "frase": 2, "posizione": 7.4, "durata": 19.0,
         "in_pausa": False, "completo": True}],

    "racconto_pausa": [
        LINGUA_EN,
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": False},
        {"tipo": "racconto", "origine": "cache", "frasi": RACCONTO_EN},
        {"tipo": "riproduzione", "frase": 1, "posizione": 4.2, "durata": 21.0,
         "in_pausa": True, "completo": True}],

    # Il caso peggiore per il titolo: 1.751 nomi su 19.358 superano la riga.
    "titolo_lungo": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "voce_muta": False,
         "titolo": "Amarone della Valpolicella Classico Riserva "
                   "Vigneto Monte Sant'Urbano",
         "sottotitolo": "Tenuta Serego Alighieri di Masi Agricola · 2015"},
        {"tipo": "racconto", "origine": "template", "frasi": [
            "Questo è l'Amarone della Valpolicella Classico Riserva.",
            "Nasce da Corvina, Corvinone e Rondinella."]},
        {"tipo": "riproduzione", "frase": 0, "posizione": 1.0, "durata": 12.0,
         "in_pausa": False}],

    "conferma": [
        LINGUA_IT, {"tipo": "stato", "vista": "conferma"},
        {"tipo": "candidati", "voci": [
            "Barolo Cannubi — Marchesi di Barolo",
            "Cannubi Barolo — Réva",
            "Barolo Bussia — Tenuta Rocca"]}],

    # La didascalia: si prova sulla schermata d'attesa, che è dove si tocca la
    # bandierina per sentire l'annuncio.
    "didascalia": [
        LINGUA_IT, {"tipo": "stato", "vista": "attesa"},
        {"tipo": "didascalia",
         "testo": "Da adesso racconto i vini in italiano."}],

    "didascalia_lunga": [
        LINGUA_IT, {"tipo": "stato", "vista": "lavoro",
                    "frase": "Sto leggendo l'etichetta…"},
        {"tipo": "didascalia",
         "testo": "Colore scarico che inganna: sotto c'è una struttura "
                  "tannica fra le più longeve al mondo."}],

    # Il comando del volume: si apre col tocco, quindi il tocco va finto.
    "volume": [LINGUA_IT, {"tipo": "stato", "vista": "attesa"}, VOLUME],
    "volume_muto": [LINGUA_IT, {"tipo": "stato", "vista": "attesa"},
                    {**VOLUME, "valore": 0}],
    # Il caso peggiore: aperto sopra il titolo di un vino, che e' cio' che sta
    # sotto quando qualcuno alza il volume a racconto in corso.
    "volume_sul_racconto": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "voce_muta": False,
         "titolo": "Amarone della Valpolicella Classico Riserva",
         "sottotitolo": "Tenuta Serego Alighieri di Masi Agricola · 2015"},
        {"tipo": "racconto", "origine": "cache", "frasi": RACCONTO_IT},
        VOLUME],

    "riposiziona": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "avviso", "simbolo": "↻", "tono": "invito",
         "frase": "Non riesco a leggere l'etichetta. Provi a girarla verso di me?"}],

    "guasto": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "avviso", "simbolo": "⚠", "tono": "errore",
         "frase": "Qualcosa non ha funzionato. Riprovo fra un istante."}],

    "senza_voce": [
        {**LINGUA_EN, "voce_muta": True,
         "avviso_muto": "In this language the story is written, not spoken."},
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": True},
        {"tipo": "racconto", "origine": "cache", "frasi": RACCONTO_EN[:3]},
        {"tipo": "riproduzione", "frase": 1, "posizione": 0, "durata": 0,
         "in_pausa": False, "senza_voce": True}],
}

# Le scene che esistono solo dopo un tocco. Il codice gira DOPO lo script della
# pagina, perche' e' in un setTimeout: al momento dell'iniezione le funzioni non
# esistono ancora.
DOPO = {
    "volume": "alternaVolume()",
    "volume_muto": "alternaVolume()",
    "volume_sul_racconto": "alternaVolume()",
}

# Sostituisce EventSource e fetch: la pagina crede di parlare col server.
FINTA = """
<script>
class EventSource {
  constructor() { setTimeout(() => MESSAGGI.forEach(m => {
    try { this.onmessage && this.onmessage({ data: JSON.stringify(m) }); }
    catch (e) { console.error(m.tipo, e); }
  }), 30); }
  close() {}
}
window.fetch = () => Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
const MESSAGGI = __MESSAGGI__;
setTimeout(() => { try { __DOPO__; } catch (e) { console.error(e); } }, 300);
</script>
"""


def trova_browser() -> str:
    for nome in ("chromium", "chromium-browser", "google-chrome",
                 "google-chrome-stable"):
        if shutil.which(nome):
            return nome
    sys.exit("nessun Chromium trovato: serve per rendere le pagine")


def ritrai(browser: str, pagina: str, uscita: Path, args) -> None:
    """Rende una pagina gia' composta e la salva come immagine."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(pagina)
        temporaneo = f.name
    subprocess.run([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--no-sandbox",
        f"--window-size={args.larghezza},{args.altezza}",
        # Il tempo virtuale deve coprire la dissolvenza fra le viste (0,4 s) e i
        # temporizzatori: con meno si fotografa la scena precedente.
        "--virtual-time-budget=4000",
        f"--screenshot={uscita}", f"file://{temporaneo}",
    ], check=False, capture_output=True)
    print(f"  {uscita.stem}: {'ok' if uscita.exists() else 'FALLITO'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cartella", nargs="?", default="anteprima")
    ap.add_argument("--larghezza", type=int, default=1280)
    ap.add_argument("--altezza", type=int, default=720)
    ap.add_argument("--solo", action="append",
                    choices=sorted([*SCENE, "avvio"]))
    args = ap.parse_args()

    browser = trova_browser()
    fuori = Path(args.cartella)
    fuori.mkdir(parents=True, exist_ok=True)
    sorgente = PAGINA.read_text(encoding="utf-8")

    # La schermata d'avvio e' un file a se': si rende com'e', spegnendo solo la
    # richiesta che la porterebbe via appena il dispositivo risponde.
    if not args.solo or "avvio" in args.solo:
        avvio = (PAGINA.parent / "avvio.html").read_text(encoding="utf-8")
        avvio = avvio.replace("fetch(PRONTO", "fetch('data:,'")
        ritrai(browser, avvio, fuori / "avvio.png", args)

    for nome in [n for n in (args.solo or SCENE) if n != "avvio"]:
        pagina = sorgente.replace(
            '<script>\n"use strict";',
            FINTA.replace("__MESSAGGI__",
                          json.dumps(SCENE[nome], ensure_ascii=False))
                 .replace("__DOPO__", DOPO.get(nome, "0"))
            + '<script>\n"use strict";')
        ritrai(browser, pagina, fuori / f"{nome}.png", args)


if __name__ == "__main__":
    main()
