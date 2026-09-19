#!/usr/bin/env python3
"""Pre-genera i racconti con il modello locale, e li scrive nel database.

    python3 scripts/pregenera.py                tutto quello che manca
    python3 scripts/pregenera.py --solo vitigno
    python3 scripts/pregenera.py --limite 20    per provare

Perché in anticipo: sulla board una generazione costa decine di secondi.
Precalcolando, nel modo «generativa» il dispositivo ha un testo del modello
pronto per il record esatto quando il modello dal vivo fallisce o inventa: è
lo stesso modello, sulla stessa macchina, solo prima. Nel modo «archivio»,
quello predefinito, questi testi non si usano: lì il racconto si compone dai
fatti, senza modello.

Si genera per **denominazione** e **vitigno**, non per i 19.358 vini
commerciali: quelli sarebbero settimane di calcolo, e la cascata del matcher
arriva comunque a una denominazione nel 96% dei casi.

Lo script è **riprendibile**: salta ciò che ha già fatto, quindi si può
interrompere e rilanciare senza perdere nulla.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

import json                                                   # noqa: E402
import urllib.error                                           # noqa: E402
import urllib.request                                         # noqa: E402

from amelie.llm import Modello, ModelloNonDisponibile        # noqa: E402
from amelie.matcher import Fatti, Livello, Matcher           # noqa: E402
from amelie.narrator import (  # noqa: E402
    _ripulisci, corpo_neutro, prompt, verifica,
)

DB = RADICE / "data" / "amelie.db"
MODELLO = "gemma-3-1b-it-Q4_K_M"
STATO_APP = "http://127.0.0.1:8080/stato"


def dispositivo_in_uso() -> bool:
    """Qualcuno ha appoggiato una bottiglia proprio adesso?

    Generare occupa tutti e quattro i core, e misurato sul campo raddoppia il
    tempo dell'OCR: da 5,2 a 11 secondi. Un ospite in attesa viene prima di un
    lotto notturno, quindi il lotto si ferma da solo e riprende dopo.
    """
    try:
        with urllib.request.urlopen(STATO_APP, timeout=2) as r:
            return json.loads(r.read()).get("stato", "attesa") != "attesa"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        # L'applicazione non risponde: nessuno la sta usando.
        return False


def da_fare(con: sqlite3.Connection, ambito: str, lingua: str) -> list[tuple[int, str]]:
    """Cosa manca, ordinato per QUANTO SERVE.

    Nove ore di calcolo sono una notte intera: se si interrompe a meta', le
    voci gia' fatte devono essere quelle che il dispositivo incontrera' davvero.
    Le denominazioni si ordinano per quanti vini vi fanno riferimento - un
    Chianti si incontra ogni sera, un Valtellina Superiore Sassella molto meno.
    """
    if ambito == "denominazione":
        tutti = con.execute(
            "SELECT d.id, d.nome FROM denominazione d"
            " LEFT JOIN vino v ON v.denominazione_id = d.id"
            " GROUP BY d.id ORDER BY count(v.id) DESC, d.nome"
        ).fetchall()
    else:
        tutti = con.execute(
            "SELECT id, nome FROM vitigno WHERE descrizione IS NOT NULL"
            " ORDER BY id").fetchall()
    fatti = {r[0] for r in con.execute(
        "SELECT ambito_id FROM racconto WHERE ambito=? AND lingua=?", (ambito, lingua))}
    return [(i, n) for i, n in tutti if i not in fatti]


def fatti_per(m: Matcher, ambito: str, ident: int) -> Fatti:
    if ambito == "denominazione":
        return m._fatti_denominazione(ident)
    return m._fatti_vitigno(ident)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solo", choices=["denominazione", "vitigno"])
    ap.add_argument("--limite", type=int)
    ap.add_argument("--lingua", default="it")
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args()

    mod = Modello()
    if not mod.attendi(60):
        sys.exit("llama-server non risponde: systemctl status amelie-llm")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    m = Matcher(args.db)

    ambiti = [args.solo] if args.solo else ["vitigno", "denominazione"]
    coda: list[tuple[str, int, str]] = []
    for a in ambiti:
        coda += [(a, i, n) for i, n in da_fare(con, a, args.lingua)]
    if args.limite:
        coda = coda[: args.limite]

    print(f"da generare: {len(coda)}  (modello {MODELLO}, lingua {args.lingua})")
    if not coda:
        return

    n_ok = n_template = n_errore = 0
    t_inizio = time.monotonic()

    for k, (ambito, ident, nome) in enumerate(coda, 1):
        atteso = 0
        while dispositivo_in_uso():
            if atteso == 0:
                print("  (dispositivo in uso: mi fermo)")
            time.sleep(5)
            atteso += 5
            if atteso > 600:      # dieci minuti: qualcosa e' rimasto appeso
                break
        if atteso:
            print(f"  (ripreso dopo {atteso}s)")

        f = fatti_per(m, ambito, ident)
        if f.vuoto:
            n_errore += 1
            continue

        testo, origine = "", "template"
        try:
            for _ in (1, 2):
                grezzo = _ripulisci(mod.genera(prompt(f, per_cache=True)))
                if not grezzo:
                    continue
                ok, invenzioni = verifica(grezzo, f)
                if ok:
                    testo, origine = grezzo, "modello"
                    break
                print(f"    scartato ({nome}): {invenzioni}")  # noqa: B023
        except ModelloNonDisponibile as e:
            print(f"  modello caduto: {e}")
            break

        if not testo:
            # Il corpo da template e' vero per costruzione: meglio una frase
            # asciutta che una bella frase falsa. Si salva SENZA apertura,
            # perche' quella la compone il narratore al momento.
            testo, origine = corpo_neutro(f, lingua=args.lingua), "template"
            n_template += 1
        else:
            n_ok += 1

        con.execute(
            "INSERT OR REPLACE INTO racconto"
            "(ambito, ambito_id, lingua, testo, modello, generato_il)"
            " VALUES (?,?,?,?,?,?)",
            (ambito, ident, args.lingua, testo,
             MODELLO if origine == "modello" else "template",
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        con.commit()

        if k % 5 == 0 or k == len(coda):
            trascorso = time.monotonic() - t_inizio
            resta = trascorso / k * (len(coda) - k)
            print(f"  {k}/{len(coda)}  {nome[:34]:36} "
                  f"{trascorso/k:5.1f} s/voce  mancano ~{resta/60:.0f} min")

    print(f"\nfatti: {n_ok} dal modello, {n_template} dal template, {n_errore} saltati")
    con.close()
    m.chiudi()


if __name__ == "__main__":
    main()
