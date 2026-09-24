#!/usr/bin/env python3
"""Fotografa ogni schermata dell'interfaccia senza toccare il dispositivo.

    python3 scripts/anteprima_ui.py [cartella] [--larghezza 1280] [--altezza 720]

Prende `index.html`, sostituisce il flusso di eventi vero con uno finto che
riproduce una sequenza di messaggi, e rende la pagina con Chromium senza
finestra. Serve per le viste che dal vetro non si raggiungono a comando: il
racconto col player, la schermata di conferma, il guasto, il caso in cui la
lingua scelta non ha una voce.

Il carattere e' quello vero: EB Garamond viaggia con la pagina, in
`ui/static/fonts`, e qui lo si carica da li'. Prima l'anteprima usciva col font
di ripiego della macchina che la eseguiva - e il dispositivo col suo, un altro
ancora - quindi nessuna delle due mostrava il disegno. Adesso sono la stessa
cosa, e la prova sulla board serve per la luce e per il dito, non per il testo.
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

# Le scritte fisse si leggono dal lessico vero, non si ricopiano: cosi'
# l'anteprima mostra quello che il dispositivo dira', e cambiare una frase non
# lascia qui una copia vecchia.
_LESSICO = json.loads((RADICE / "data" / "lessico" / "frasi.json").read_text(encoding="utf-8"))


def _scritta(chiave: str, lingua: str) -> str:
    v = _LESSICO["schermo"][chiave][lingua]
    return v if isinstance(v, str) else v[0]


def _lingua(lingua: str) -> dict:
    return {"tipo": "lingua", "lingua": lingua, "disponibili": ["it", "en"],
            "invito": _scritta("appoggia_bottiglia", lingua),
            "domanda": _scritta("quale_di_questi", lingua),
            "voce_muta": False, "avviso_muto": "",
            "annulla": _scritta("annulla", lingua),
            "sto_scrivendo": _scritta("sto_scrivendo", lingua),
            "passi": [{"titolo": _scritta(f"passo_{p}", lingua),
                       "spiega": _scritta(f"passo_{p}_spiega", lingua)}
                      for p in ("appoggia", "riconosce", "racconta")]}


LINGUA_IT = _lingua("it")
LINGUA_EN = _lingua("en")
_CHIAVI_CORREZIONE = ("correggi_descrizione", "modifica_descrizione", "campo_titolo",
                      "campo_descrizione", "salva", "titolo_vuoto", "descrizione_vuota",
                      "correzione_spiega", "correzione_salvata", "correzione_vicine",
                      "tasto_spazio", "annulla")
for _l, _m in (("it", LINGUA_IT), ("en", LINGUA_EN)):
    _m["correzione"] = {k: _scritta(k, _l) for k in _CHIAVI_CORREZIONE}


def _frase_corpo(chiave: str, lingua: str) -> str:
    v = _LESSICO["corpo"][chiave][lingua]
    return v if isinstance(v, str) else v[0]


# Una bottiglia al posto della foto vera, che qui non c'e': la sagoma basta a
# vedere dove sta e quanto occupa.
_FOTO = ("data:image/svg+xml;utf8," +
         "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 216'>"
         "<rect width='120' height='216' fill='%23241a17'/>"
         "<path d='M50 14h20v40c0 8 22 16 22 36v112H28V90c0-20 22-28 22-36z' fill='%235a211c'/>"
         "<rect x='32' y='112' width='56' height='50' rx='4' fill='%23e8dcc8'/></svg>")

# Le scritte del pannello delle impostazioni, come le manda il server.
_CHIAVI_IMPOSTAZIONI = (
    "impostazioni", "stato_tecnico", "chiudi", "mirino", "mirino_spiega",
    "mirino_torna", "mirino_legge", "mirino_trova", "mirino_niente", "modo_titolo",
    "modo_archivio", "modo_archivio_spiega", "modo_generativa",
    "modo_generativa_spiega", "modo_carta", "modo_carta_spiega",
    "batteria_ricaricata", "batteria_spiega")
LINGUA_IT_PIENA = {**LINGUA_IT, "impostazioni": {
    k: _scritta(k, "it") for k in _CHIAVI_IMPOSTAZIONI}}

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
         "quota": 0.39, "in_pausa": False, "completo": True}],

    "racconto_pausa": [
        LINGUA_EN,
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": False},
        {"tipo": "racconto", "origine": "cache", "frasi": RACCONTO_EN},
        {"tipo": "riproduzione", "frase": 1, "posizione": 4.2, "durata": 21.0,
         "quota": 0.20, "in_pausa": True, "completo": True}],

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
         "quota": 0.08, "in_pausa": False}],

    "conferma": [
        LINGUA_IT, {"tipo": "stato", "vista": "conferma"},
        {"tipo": "candidati", "nessuno": "Nessuno di questi", "voci": [
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

    # Mentre il modello scrive: la goccia che respira al posto del testo.
    "scrivendo": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": False},
        {"tipo": "scrivendo"}],

    # Il pannello si apre col gesto da tre secondi, quindi anche qui si finge.
    "impostazioni": [
        LINGUA_IT_PIENA, {"tipo": "stato", "vista": "attesa"},
        {"tipo": "impostazioni", "modo": "archivio",
         "modi": ["archivio", "generativa", "carta"]},
        {"tipo": "mirino", "acceso": False, "disponibile": True},
        {"tipo": "salute", "tutto_bene": True, "batteria": {"tacche": 3}}],

    # La bottiglia che non e' in archivio: il racconto dice di aver fatto da se',
    # e sotto c'e' il pulsante per correggerlo.
    "fuori_archivio": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Spumante rosato metodo classico, brut",
         "sottotitolo": "", "voce_muta": False, "correzione": "correggi"},
        {"tipo": "racconto", "origine": "template", "frasi": [
            "Si tratta di uno spumante rosato metodo classico, brut.",
            "Va servito fra 6 e 8 gradi.",
            _frase_corpo("generico_limite", "it")]},
        {"tipo": "riproduzione", "frase": 2, "posizione": 9.0, "durata": 12.0,
         "quota": 0.75, "in_pausa": False}],

    # La stessa, otto secondi dopo: la frase e' piu' alta della parte leggibile,
    # e la voce e' arrivata alle ultime righe - che devono essere salite in vista.
    "fuori_archivio_fine": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Spumante rosato metodo classico, brut",
         "sottotitolo": "", "voce_muta": False, "correzione": "correggi"},
        {"tipo": "racconto", "origine": "template", "frasi": [
            "Si tratta di uno spumante rosato metodo classico, brut.",
            "Va servito fra 6 e 8 gradi.",
            _frase_corpo("generico_limite", "it")]},
        {"tipo": "riproduzione", "frase": 2, "posizione": 9.0, "durata": 18.0,
         "quota": 0.5, "in_pausa": False},
        {"tipo": "riproduzione", "frase": 2, "posizione": 17.0, "durata": 18.0,
         "quota": 0.95, "in_pausa": False}],

    # Il caso piu' alto dell'intestazione: titolo su due righe, la cantina letta
    # sull'etichetta, e il pulsante.
    "fuori_archivio_cantina": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Spumante rosato metodo classico, brut",
         "sottotitolo": "Palamà · 2021", "voce_muta": False, "correzione": "correggi"},
        {"tipo": "racconto", "origine": "template", "frasi": [
            "Si tratta di uno spumante rosato metodo classico, brut, di Palamà.",
            "Va servito fra 6 e 8 gradi.",
            _frase_corpo("generico_limite", "it")]},
        {"tipo": "riproduzione", "frase": 0, "posizione": 1.0, "durata": 12.0,
         "quota": 0.1, "in_pausa": False}],

    # Una bottiglia gia' corretta: il racconto e' quello scritto, e si puo' modificare.
    "corretta": [
        LINGUA_IT,
        {"tipo": "stato", "vista": "racconto", "titolo": "Albarossa Negroamaro Rosato",
         "sottotitolo": "", "voce_muta": False, "correzione": "modifica"},
        {"tipo": "racconto", "origine": "correzione", "frasi": [
            "Questo è l'Albarossa Negroamaro Rosato.",
            "Un rosato del Salento da uve Negroamaro, di Palamà.",
            "Fresco e sapido, con note di fragola e melograno: da aperitivo e da pesce."]},
        {"tipo": "riproduzione", "frase": 1, "posizione": 3.0, "durata": 11.0,
         "quota": 0.3, "in_pausa": False}],

    # L'editor: si apre col tocco, e la risposta del server si finge.
    "editor": [LINGUA_IT, {"tipo": "stato", "vista": "racconto", "titolo": "x",
                           "correzione": "correggi"}],
    "editor_vicine": [LINGUA_IT, {"tipo": "stato", "vista": "racconto", "titolo": "x",
                                  "correzione": "correggi"}],

    "senza_voce": [
        {**LINGUA_EN, "voce_muta": True,
         "avviso_muto": "In this language the story is written, not spoken."},
        {"tipo": "stato", "vista": "racconto", "titolo": "Cannubi Barolo",
         "sottotitolo": "Marchesi di Barolo · 2016", "voce_muta": True},
        {"tipo": "racconto", "origine": "cache", "frasi": RACCONTO_EN[:3]},
        {"tipo": "riproduzione", "frase": 1, "posizione": 0, "durata": 0,
         "quota": 0.33, "in_pausa": False, "senza_voce": True}],
}

# Le scene che esistono solo dopo un tocco. Il codice gira DOPO lo script della
# pagina, perche' e' in un setTimeout: al momento dell'iniezione le funzioni non
# esistono ancora.
DOPO = {
    "volume": "alternaVolume()",
    "volume_muto": "alternaVolume()",
    "volume_sul_racconto": "alternaVolume()",
    "impostazioni": "apriImpostazioni()",
    "editor": "apriEditor()",
    "editor_vicine": "apriEditor()",
}

# Che cosa risponde il server finto, per le scene che gli chiedono qualcosa.
RISPOSTE = {
    "editor": {"/correzione/apri": {
        "ok": True, "id": None, "lingua": "it", "titolo": "Albarossa Negroamaro",
        "descrizione": "Un rosato del Salento da uve Negroamaro, di Palamà. "
                       "Fresco e sapido, con note di fragola", "vicine": []}},
    "editor_vicine": {"/correzione/apri": {
        "ok": True, "id": None, "lingua": "it", "titolo": "", "descrizione": "",
        "vicine": [{"id": "a", "titolo": "Albarossa Negroamaro Rosato", "descrizione": ""},
                   {"id": "b", "titolo": "Metiusco Salento Rosato", "descrizione": ""}]}},
}

# Sostituisce EventSource e fetch: la pagina crede di parlare col server.
FINTA = """
<script>
// I messaggi partono a carattere caricato, come sul dispositivo, dove il
// racconto arriva secondi dopo la pagina: misurato col carattere di ripiego,
// lo scorrimento del testo si fermava a righe che col Garamond non ci sono.
class EventSource {
  constructor() {
    const manda = () => MESSAGGI.forEach(m => {
      try { this.onmessage && this.onmessage({ data: JSON.stringify(m) }); }
      catch (e) { console.error(m.tipo, e); }
    });
    document.fonts.load('50px "EB Garamond"').catch(() => {})
      .then(() => setTimeout(manda, 30));
  }
  close() {}
}
const RISPOSTE = __RISPOSTE__;
window.fetch = (url) => Promise.resolve({ json: () => Promise.resolve(
  RISPOSTE[String(url).split("?")[0]] || { ok: true }) });
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
        # Il carattere sta accanto alla pagina ma la pagina e' un file: senza,
        # Chromium rifiuta di caricarlo e l'anteprima esce col font di ripiego.
        "--allow-file-access-from-files",
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
        # Col tempo virtuale lo scorrimento morbido non parte: si scorre di colpo,
        # e la fotografia mostra dove il testo arriva.
        pagina = sorgente.replace('behavior: "smooth"', 'behavior: "instant"').replace(
            '"/correzione/foto/adesso?" + Date.now()', json.dumps(_FOTO)).replace(
            '"/correzione/foto/" + encodeURIComponent(v.id)', json.dumps(_FOTO)).replace(
            'url("/fonts/', f'url("file://{PAGINA.parent}/fonts/').replace(
            '<script>\n"use strict";',
            FINTA.replace("__MESSAGGI__",
                          json.dumps(SCENE[nome], ensure_ascii=False))
                 .replace("__DOPO__", DOPO.get(nome, "0"))
                 .replace("__RISPOSTE__", json.dumps(RISPOSTE.get(nome, {}),
                                                     ensure_ascii=False))
            + '<script>\n"use strict";')
        ritrai(browser, pagina, fuori / f"{nome}.png", args)


if __name__ == "__main__":
    main()
