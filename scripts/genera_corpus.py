#!/usr/bin/env python3
"""Scrive nel database il racconto di ogni vino generico, in ogni lingua.

    python3 scripts/genera_corpus.py                     tutto quel che manca
    python3 scripts/genera_corpus.py --lingua en
    python3 scripts/genera_corpus.py --rigenera          rifa' anche i fatti
    python3 scripts/genera_corpus.py --solo vitigno

Perché esiste, accanto a `pregenera.py` che usa il modello locale.

Una bottiglia che il dispositivo non riconosce fino al produttore deve comunque
avere qualcosa di **vero** da dire: il suo vino generico. Per averlo pronto in
due lingue su tutte le denominazioni, tipologie e vitigni servirebbero, col
modello da un miliardo di parametri, giorni di calcolo sulla board — e il testo
che ne esce è stato misurato: il 23% viene scartato dalla verifica
anti-invenzione, e ciò che passa è italiano che non si può far leggere a un ospite.

Il testo costruito dal template invece è **vero per costruzione**: ogni frase
nasce da un campo del database, non c'è nulla da verificare perché non c'è nulla
di inventato. Ed è istantaneo. Quindi il corpus di base si genera così, e il
modello resta quello che era previsto: una miglioria, applicabile voce per voce
dove serve e dove supera la verifica, non l'unica fonte.

La colonna `modello` distingue le due provenienze: `template` qui, il nome del
modello in `pregenera.py`. Chi vuole far riscrivere una voce al modello sa quali
sono ancora da toccare, e chi legge il database sa da dove viene ogni riga.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.lessico import carica                             # noqa: E402
from amelie.matcher import Fatti, Matcher                     # noqa: E402
from amelie.narrator import corpo_neutro                      # noqa: E402

DB = RADICE / "data" / "amelie.db"
AMBITI = ("tipologia", "denominazione", "vitigno")


def da_fare(con: sqlite3.Connection, ambito: str, lingua: str,
            rigenera: bool) -> list[tuple[int, str]]:
    """Cosa manca, ordinato per QUANTO SERVE.

    Le denominazioni e le tipologie si ordinano per quanti vini vi fanno capo:
    un Chianti si incontra ogni sera, un Valtellina Superiore Sassella molto
    meno. Se il lavoro si interrompe, ciò che è già fatto è ciò che il
    dispositivo incontrerà davvero.
    """
    if ambito == "denominazione":
        tutti = con.execute(
            "SELECT d.id, d.nome FROM denominazione d"
            " LEFT JOIN vino v ON v.denominazione_id = d.id"
            " GROUP BY d.id ORDER BY count(v.id) DESC, d.nome").fetchall()
    elif ambito == "tipologia":
        tutti = con.execute(
            "SELECT t.id, t.nome FROM tipologia t"
            " LEFT JOIN vino v ON v.denominazione_id = t.denominazione_id"
            " GROUP BY t.id ORDER BY count(v.id) DESC, t.nome").fetchall()
    else:
        # Solo i vitigni descritti a mano: sugli altri il template non avrebbe
        # nulla da dire, e una riga vuota in cache impedirebbe di scendere al
        # gradino successivo della catena di ripiego.
        tutti = con.execute(
            "SELECT id, nome FROM vitigno WHERE descrizione IS NOT NULL"
            " AND descrizione <> '' ORDER BY nome").fetchall()

    if rigenera:
        return [(i, n) for i, n in tutti]
    gia = {r[0] for r in con.execute(
        "SELECT ambito_id FROM racconto WHERE ambito=? AND lingua=?",
        (ambito, lingua))}
    return [(i, n) for i, n in tutti if i not in gia]


def fatti_per(m: Matcher, ambito: str, ident: int) -> Fatti:
    return {"tipologia": m._fatti_tipologia,
            "denominazione": m._fatti_denominazione,
            "vitigno": m._fatti_vitigno}[ambito](ident)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lingua", action="append",
                    help="ripetibile; senza, tutte quelle del lessico")
    ap.add_argument("--solo", choices=AMBITI, action="append")
    ap.add_argument("--rigenera", action="store_true",
                    help="riscrive anche le voci gia' presenti da template")
    ap.add_argument("--limite", type=int)
    args = ap.parse_args()

    if not DB.exists():
        sys.exit(f"non trovo {DB}")

    lex = carica()
    lingue = args.lingua or list(lex.lingue)
    ambiti = args.solo or list(AMBITI)

    m = Matcher(DB)
    con = sqlite3.connect(DB)
    quando = datetime.now(timezone.utc).isoformat(timespec="seconds")
    scritti = vuoti = 0

    for lingua in lingue:
        for ambito in ambiti:
            coda = da_fare(con, ambito, lingua, args.rigenera)
            if args.limite:
                coda = coda[: args.limite]
            print(f"  {lingua}/{ambito}: {len(coda)} da scrivere")
            for ident, _nome in coda:
                testo = corpo_neutro(fatti_per(m, ambito, ident), lex, lingua)
                if not testo:
                    # Nessun fatto da raccontare: meglio nessuna riga che una
                    # riga vuota, che bloccherebbe il ripiego sul gradino dopo.
                    vuoti += 1
                    continue
                con.execute(
                    "INSERT INTO racconto"
                    "(ambito, ambito_id, lingua, testo, modello, generato_il)"
                    " VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(ambito, ambito_id, lingua) DO UPDATE SET"
                    " testo=excluded.testo, modello=excluded.modello,"
                    " generato_il=excluded.generato_il"
                    # Una voce riscritta dal modello e' un miglioramento
                    # umanamente rivisto: non la si sovrascrive col template.
                    " WHERE racconto.modello = 'template'",
                    (ambito, ident, lingua, testo, "template", quando))
                scritti += 1
            con.commit()

    m.chiudi()
    totale = con.execute("SELECT count(*) FROM racconto").fetchone()[0]
    con.close()
    print(f"\n  {scritti} racconti scritti, {vuoti} saltati per mancanza di fatti")
    print(f"  {totale} righe in archivio")


if __name__ == "__main__":
    main()
