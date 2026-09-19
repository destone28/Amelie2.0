#!/usr/bin/env python3
"""Quanto ci si puo' fidare del modello: lo stesso metro, ogni volta.

    python3 scripts/valuta_generativa.py --url http://127.0.0.1:8091
    python3 scripts/valuta_generativa.py --temperatura 0.7 --temperatura 0.2 --temperatura 0
    python3 scripts/valuta_generativa.py --quanti 60 --seme 3 --lingua en --uscita esiti.jsonl

Serve a una cosa sola: sapere se un cambiamento - un modello nuovo, una
temperatura, un prompt - rende i testi PIU' o MENO affidabili, con un numero e
non con un'impressione. Si campionano sempre gli stessi vini (stesso seme), si
genera con le impostazioni date, e ogni testo passa da tre controlli:

1. `verifica`, quella del dispositivo: numeri, nomi propri, colori, uve che
   non lo sono, cibi e provenienze inventate, ripetizioni;
2. le PAROLE FUORI DAI FATTI: le parole di contenuto che non stanno ne' nei
   fatti ne' nel lessico delle formule. Non e' un veto - una parola generica
   come «avvolgente» non e' una bugia - ma e' la pressione a inventare, e va
   giu' o su con le impostazioni. Si stampano, perche' vanno lette;
3. l'ORTOGRAFIA: parole che non stanno nel vocabolario italiano ne' nei fatti
   («dieciotto», «tanninare»). Un modello che sbaglia le parole sbaglia anche i
   fatti, e queste si vedono prima.

Il modello si interroga via llama-server, sul PC o sul dispositivo: la stessa
catena che il dispositivo usa, `prompt_addestrato` e `_ripulisci` comprese.
Cambiare metro fra una prova e l'altra e' il modo piu' rapido di non sapere
niente.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.llm import ImpostazioniLLM                            # noqa: E402
from amelie.matcher import Matcher                                # noqa: E402
from amelie.narrator import (                                     # noqa: E402
    _ripulisci, prompt_addestrato, spezza_in_frasi, verifica,
)

# Parole che una scheda di sala usa senza affermare niente del vino: verbi di
# presentazione, parti del bicchiere, congiunzioni lunghe. Chi giudica le
# «parole fuori dai fatti» deve saperle scontare, altrimenti ogni testo
# fluente sembra un'invenzione. Si tiene corto apposta: un lessico largo
# nasconde le invenzioni vere.
_GENERICHE = set("""
nasce nascono viene vengono ottiene produce dona regala offre porta esprime
mostra presenta rivela ricorda richiama accompagna accompagnano abbina abbinano
serve servire servito servita servono bicchiere calice bocca naso palato
olfatto sorso finale retrogusto struttura corpo acidita tannino tannini
persistenza equilibrio armonia colore profumo profumi aroma aromi sentori note
nota sapore gusto vino vini bottiglia etichetta annata vitigno vitigni uva uve
disciplinare denominazione tipologia regione territorio zona colline collina
vigneto vigneti cantina produttore produce tavola piatto piatti cucina
gradi temperatura fresco fresca fredda freddo caldo calda ambiente carattere
tipico tipica tipiche tipici caratteristico caratteristica intenso intensa
delicato delicata morbido morbida fine elegante pieno piena secco secca
asciutto asciutta armonico armonica fruttato fruttata floreale speziato
speziata sapido sapida fragrante persistente vellutato vellutata rotondo
rotonda leggero leggera medio media grande buona buono bella bello giovane
maturo matura invecchiamento affinamento riposa lieve leggermente talvolta
ancora anche dove quando mentre insieme accanto abbinato durante dopo prima
questo questa questi queste quello quella sotto sopra verso tutto tutta
perfetto perfetta ideale adatto adatta bene molto meno molta molti poco
italia italiano italiana italiani italiane
sulla sulle sullo sugli della delle dello degli dalla dalle dallo dagli nella
nelle nello negli dell dall nell sull quell
vuole vogliono prevede prevedono descrive descrivono richiede richiedono
purezza essenza mezzo temperature servizio conferisce conferiscono dona donano
regala regalano esprime esprimono creano formano danno idealmente benissimo
accompagnare accompagnando accompagnamento abbinare abbinarsi abbinamento
prodotto prodotti produce producono deriva derivano nascono viene vengono
caratterizzato caratterizzata sfumature riflessi consistenza prevalenza
diffuso diffusa diffusi diffuse protagonista protagonisti generoso generosa
generosi robusto robusta strutturato strutturata equilibrato equilibrata
ricco ricca ampio ampia chiaro chiara scarico scarica carico carica
""".split())

# I numeri detti in lettere: la voce sintetica li vuole cosi', il corpus li
# scrive cosi', e i fatti li hanno in cifre. Si riportano a cifre e si
# confrontano con quelle, invece di contarli come parole inventate.
_IN_LETTERE = {
    "cinque": 5, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11,
    "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15, "sedici": 16,
    "diciassette": 17, "diciotto": 18, "diciannove": 19, "venti": 20,
}
# Le provenienze - «piemontese», «borgognone» - le giudica gia' `verifica`,
# che sa quando stanno nei fatti: qui non si contano due volte.
_PROVENIENZA = re.compile(
    r"^(?:piemontes|toscan|sicilian|abruzzes|puglies|venet|umbr|lazial|marchigian|"
    r"sard|calabres|campan|lombard|ligur|friulan|trentin|altoatesin|emilian|"
    r"romagnol|borgognon|bordoles|frances|spagnol|tedesc|austriac|indigen|autocton)")

_PAROLA = re.compile(r"[a-zà-ÿ']{5,}")


def _piatto(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c)).replace("'", " ")


def _parole(s: str) -> set[str]:
    return {w.strip("'") for w in _PAROLA.findall(_piatto(s)) if len(w.strip("'")) >= 5}


def carica_vocabolario(percorso: Path | None) -> set[str] | None:
    if not percorso or not percorso.exists():
        return None
    return {_piatto(r.strip()) for r in percorso.read_text(encoding="utf-8").splitlines() if r.strip()}


def campiona(m: Matcher, quanti: int, seme: int):
    """Gli stessi vini ogni volta, a parita' di seme, dai tre gradini che il
    dispositivo racconta davvero."""
    rnd = random.Random(seme)
    casi = []
    for ambito in ("vino", "tipologia", "denominazione"):
        ids = [r[0] for r in m.con.execute(f"SELECT id FROM {ambito}")]
        rnd.shuffle(ids)
        presi = 0
        for i in ids:
            f = getattr(m, f"_fatti_{ambito}")(i)
            if f.vuoto or not (f.vitigni or f.disciplinare or f.corpo):
                continue
            f.sicurezza = 95.0
            casi.append((ambito, i, f))
            presi += 1
            if presi >= quanti:
                break
    return casi


def genera(url: str, prompt: str, imp: ImpostazioniLLM, temperatura: float,
           top_p: float, ripetizione: float, grammatica: str | None) -> tuple[str, float]:
    corpo = {"prompt": prompt, "n_predict": imp.max_token, "temperature": temperatura,
             "top_p": top_p, "repeat_penalty": ripetizione, "stop": list(imp.stop),
             "cache_prompt": True}
    if grammatica:
        corpo["grammar"] = grammatica
    req = urllib.request.Request(f"{url}/completion", data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"})
    inizio = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return d.get("content", ""), time.perf_counter() - inizio


def gabbia(f, lingua: str, lessico: set[str]) -> str:
    """Una grammatica GBNF che lascia al modello SOLO le parole ammesse.

    Le parole dei fatti di questa bottiglia, piu' un lessico chiuso di parole
    di raccordo - quelle che i testi verificati usano oltre ai fatti - piu'
    cifre e punteggiatura. Il modello sceglie e combina, non puo' nominare
    niente che non stia qui dentro: e' la gabbia, e la garanzia e' strutturale.
    Non protegge dai RAPPORTI sbagliati fra parole vere («Sangiovese e
    Amarena»): a quelli pensa `verifica`, dopo.
    """
    parole = set()
    for w in re.findall(r"[A-Za-zÀ-ÿ']+", fatti_come_testo(f, lingua)):
        w = w.strip("'")
        if w:
            parole.update((w, w.lower(), w.capitalize()))
    for w in lessico:
        parole.update((w, w.capitalize()))
    parole.update(("d'", "l'", "un'", "dell'", "all'", "nell'", "dall'", "sull'", "è", "È"))
    alternative = " | ".join(json.dumps(w, ensure_ascii=False)
                             for w in sorted(parole, key=lambda x: (-len(x), x)))
    numero = '[0-9]+ ("." [0-9]+)?'
    return "\n".join([
        'root ::= frase (" " frase){1,5}',
        'frase ::= pezzo (" " pezzo){2,40} "."',
        'pezzo ::= parola ("," | ";" | ":")?',
        f'parola ::= numero | {alternative}',
        f'numero ::= {numero}',
    ])


def carica_lessico(percorso: Path | None) -> set[str]:
    if not percorso or not percorso.exists():
        return set()
    return {r.strip() for r in percorso.read_text(encoding="utf-8").splitlines() if r.strip()}


def fatti_come_testo(f, lingua: str) -> str:
    return " ".join(filter(None, [
        f.blocco_fatti(lingua=lingua), " ".join(f.vitigni), f.nota_in(lingua) or "",
        f.note_vitigno or "", " ".join(f.sensoriali_in(lingua)),
        " ".join(f.abbinamenti_in(lingua)), f.denominazione or "", f.tipologia or "",
        f.nome or "", f.cantina or "", f.regione or "", str(f.annata or ""),
        f.temperatura_c or "", " ".join(f.note_sensoriali),
        " ".join(f.disciplinare.values()) if f.disciplinare else "",
    ]))


def giudica(testo: str, f, lingua: str, vocabolario: set[str] | None) -> dict:
    ok, invenzioni = verifica(testo, f, lingua)
    fatti_testo = fatti_come_testo(f, lingua)
    nei_fatti = _parole(fatti_testo)
    numeri_nei_fatti = set(re.findall(r"\d+", fatti_testo))
    nel_testo = _parole(testo)
    fuori = sorted(
        w for w in nel_testo - nei_fatti
        if w not in _GENERICHE and not _PROVENIENZA.match(w)
        and not (w in _IN_LETTERE and str(_IN_LETTERE[w]) in numeri_nei_fatti))
    refusi = []
    if vocabolario is not None and lingua == "it":
        refusi = sorted(w for w in nel_testo - nei_fatti
                        if w not in vocabolario and w not in _GENERICHE)
    frasi = spezza_in_frasi(testo)
    return {
        "verifica_ok": ok, "invenzioni": invenzioni, "fuori_dai_fatti": fuori,
        "refusi": refusi, "frasi": len(frasi),
        "tronco": not testo.rstrip().endswith((".", "!", "?", "…")),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8081")
    ap.add_argument("--db", default=str(RADICE / "data" / "amelie.db"))
    ap.add_argument("--quanti", type=int, default=12, help="per gradino: vino, tipologia, denominazione")
    ap.add_argument("--seme", type=int, default=7)
    ap.add_argument("--lingua", default="it")
    ap.add_argument("--temperatura", type=float, action="append",
                    help="una o piu'; 0 = scelta sempre la parola piu' probabile")
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--ripetizione", type=float, default=1.0, help="repeat_penalty")
    ap.add_argument("--vocabolario", default=str(Path.home() / "modello/parole_it.txt"))
    ap.add_argument("--uscita", help="JSONL con ogni testo e il suo giudizio")
    ap.add_argument("--etichetta", default="", help="un nome per questa prova, nei risultati")
    ap.add_argument("--gabbia", metavar="LESSICO.txt",
                    help="vincola la generazione alle parole dei fatti piu' a questo lessico")
    a = ap.parse_args()
    lessico = carica_lessico(Path(a.gabbia)) if a.gabbia else None

    temperature = a.temperatura or [0.7]
    imp = ImpostazioniLLM()
    m = Matcher(a.db)
    casi = campiona(m, a.quanti, a.seme)
    vocabolario = carica_vocabolario(Path(a.vocabolario))
    print(f"{len(casi)} vini (seme {a.seme}), lingua {a.lingua}, modello su {a.url}")
    uscita = open(a.uscita, "a", encoding="utf-8") if a.uscita else None

    for t in temperature:
        esiti = []
        for ambito, ident, f in casi:
            grammatica = gabbia(f, a.lingua, lessico) if lessico is not None else None
            grezzo, secondi = genera(a.url, prompt_addestrato(f, a.lingua), imp, t,
                                     a.top_p, a.ripetizione, grammatica)
            testo = _ripulisci(grezzo.strip())
            g = giudica(testo, f, a.lingua, vocabolario)
            g.update({"ambito": ambito, "id": ident, "cosa": f.nome or f.tipologia or f.denominazione,
                      "secondi": round(secondi, 1), "testo": testo, "temperatura": t,
                      "etichetta": a.etichetta})
            esiti.append(g)
            if uscita:
                uscita.write(json.dumps(g, ensure_ascii=False) + "\n"); uscita.flush()
        n = len(esiti)
        ok = sum(e["verifica_ok"] for e in esiti)
        fuori = sum(len(e["fuori_dai_fatti"]) for e in esiti)
        refusi = sum(len(e["refusi"]) for e in esiti)
        tronchi = sum(e["tronco"] for e in esiti)
        sec = sum(e["secondi"] for e in esiti) / max(n, 1)
        print(f"\n=== temperatura {t}  {a.etichetta}")
        print(f"verifica: {ok}/{n} passano   parole fuori dai fatti: {fuori / n:.1f} per testo"
              f"   refusi: {refusi}   tronchi: {tronchi}   {sec:.1f} s/testo")
        for e in esiti:
            segni = []
            if not e["verifica_ok"]:
                segni.append("BOCCIATO " + "; ".join(e["invenzioni"])[:90])
            if e["refusi"]:
                segni.append("refusi " + ", ".join(e["refusi"][:4]))
            if e["fuori_dai_fatti"]:
                segni.append("fuori " + ", ".join(e["fuori_dai_fatti"][:6]))
            print(f"  {e['cosa'][:34]:34s} {' | '.join(segni)[:150]}")


if __name__ == "__main__":
    main()
