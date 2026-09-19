#!/usr/bin/env python3
"""Che cosa ESCE dal dispositivo, non che cosa scrive il modello.

    python3 scripts/prova_finale.py --url http://127.0.0.1:8092 --quanti 150

`valuta_generativa.py` misura il modello: quante volte, su un tentativo, il
testo che scrive regge la verifica. Questo misura il **prodotto**: si chiama
`Narratore.racconta` come lo chiama il dispositivo, con la sua catena intera -
il cancello che decide se il modello puo' scrivere, i due tentativi, la
verifica davanti a ognuno, il testo pronto per quel record, e la composizione
che chiude. Poi si guarda quel che ne esce.

Le due domande, e sono diverse:

1. **Esce mai qualcosa di sbagliato?** Dev'essere zero, sempre, per
   costruzione: quello che non regge la verifica non arriva allo schermo.
2. **Quanto spesso parla il modello?** E' il prezzo dell'affidabilita': ogni
   volta che il modello cade si scende alla composizione, che e' vera ma piu'
   asciutta.

Il secondo numero non e' un difetto da correggere: e' la scelta che il
dispositivo fa al posto di chi ascolta.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
sys.path.insert(0, str(RADICE / "scripts"))

from amelie.llm import ImpostazioniLLM, Modello                   # noqa: E402
from amelie.matcher import Matcher                                # noqa: E402
from amelie.narrator import (                                     # noqa: E402
    Narratore, _abbastanza_per_il_modello, spezza_in_frasi, verifica,
)
from valuta_generativa import carica_vocabolario, giudica          # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8081")
    ap.add_argument("--db", default=str(RADICE / "data" / "amelie.db"))
    ap.add_argument("--quanti", type=int, default=120)
    ap.add_argument("--seme", type=int, default=21)
    ap.add_argument("--lingua", default="it")
    ap.add_argument("--uscita")
    a = ap.parse_args()

    m = Matcher(a.db)
    modello = Modello(ImpostazioniLLM(url=a.url))
    if not modello.pronto:
        raise SystemExit(f"nessun modello su {a.url}")
    n = Narratore(genera=lambda p, g=None: modello.genera(p, g),
                  modello_addestrato=True, lingua=a.lingua)
    vocabolario = carica_vocabolario(Path.home() / "modello/parole_it.txt")

    rnd = random.Random(a.seme)
    casi = []
    for ambito in ("vino", "tipologia", "denominazione"):
        ids = [r[0] for r in m.con.execute(f"SELECT id FROM {ambito}")]
        rnd.shuffle(ids)
        presi = 0
        for i in ids:
            f = getattr(m, f"_fatti_{ambito}")(i)
            if f.vuoto:
                continue
            f.sicurezza = 95.0
            casi.append((ambito, i, f))
            presi += 1
            if presi >= a.quanti:
                break

    origini = collections.Counter()
    sbagliati, esiti = [], []
    inizio = time.perf_counter()
    for ambito, i, f in casi:
        t0 = time.perf_counter()
        r = n.racconta(f, preferisci_modello=True)
        secondi = time.perf_counter() - t0
        ok, invenzioni = verifica(r.testo, f, a.lingua)
        g = giudica(r.testo, f, a.lingua, vocabolario if a.lingua == "it" else None)
        origini[r.origine] += 1
        if not ok:
            sbagliati.append((ambito, i, r.origine, invenzioni, r.testo[:160]))
        esiti.append({"ambito": ambito, "id": i, "origine": r.origine,
                      "cancello": _abbastanza_per_il_modello(f),
                      "verifica_ok": ok, "invenzioni": invenzioni,
                      "fuori_dai_fatti": g["fuori_dai_fatti"], "refusi": g["refusi"],
                      "frasi": len(spezza_in_frasi(r.testo)),
                      "secondi": round(secondi, 1), "cosa": f.nome or f.tipologia or f.denominazione,
                      "testo": r.testo})
    durata = time.perf_counter() - inizio

    ammessi = [e for e in esiti if e["cancello"]]
    dal_modello = [e for e in esiti if e["origine"] == "modello"]
    print(f"\n{len(esiti)} bottiglie, lingua {a.lingua}, {durata/len(esiti):.1f} s l'una")
    print(f"  esce sbagliato:          {len(sbagliati)}  (dev'essere zero)")
    print(f"  ammesse dal cancello:    {len(ammessi)}/{len(esiti)} = {100*len(ammessi)/len(esiti):.0f}%")
    if ammessi:
        print(f"  di quelle, scrive il modello: {len(dal_modello)}/{len(ammessi)} = "
              f"{100*len(dal_modello)/len(ammessi):.0f}%")
    print(f"  da dove esce il racconto: {dict(origini)}")
    print(f"  frasi in media:           {sum(e['frasi'] for e in esiti)/len(esiti):.1f}")
    if dal_modello:
        print(f"  parole fuori dai fatti, quando parla il modello: "
              f"{sum(len(e['fuori_dai_fatti']) for e in dal_modello)/len(dal_modello):.1f}")
    for x in sbagliati[:10]:
        print("  SBAGLIATO", x[0], x[1], x[2], x[3], "|", x[4])
    if a.uscita:
        with open(a.uscita, "w", encoding="utf-8") as f_out:
            for e in esiti:
                f_out.write(json.dumps(e, ensure_ascii=False) + "\n")
    n.chiudi()


if __name__ == "__main__":
    main()
