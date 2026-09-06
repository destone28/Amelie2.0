#!/usr/bin/env python3
"""Ricalcola le forme normalizzate e l'indice di ricerca del database.

Serve quando cambia `amelie.text.normalizza`. Le colonne `*_norm` e la tabella
`ricerca` sono derivate: si ricavano dai nomi originali, che restano nel
database. Ricostruirle da lì evita di riscaricare le sorgenti (centomila vini)
e soprattutto **non tocca gli identificativi**, a cui sono agganciati i testi
già pre-generati nella cache dei racconti.

    python3 scripts/reindicizza.py [data/amelie.db]

Si può rilanciare quante volte si vuole: il risultato dipende solo dai nomi.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.text import normalizza  # noqa: E402


def main() -> None:
    percorso = Path(sys.argv[1]) if len(sys.argv) > 1 else RADICE / "data" / "amelie.db"
    if not percorso.exists():
        sys.exit(f"non trovo {percorso}")
    con = sqlite3.connect(percorso)
    con.execute("PRAGMA foreign_keys = ON")

    cambiati = 0
    for tabella, colonne in (("denominazione", ["nome"]), ("tipologia", ["nome"]),
                             ("vitigno", ["nome"]), ("vino", ["nome", "cantina"])):
        for colonna in colonne:
            for ident, valore, attuale in con.execute(
                f"SELECT id, {colonna}, {colonna}_norm FROM {tabella}"
            ).fetchall():
                atteso = normalizza(valore) if valore else (None if colonna == "cantina" else "")
                if atteso != attuale:
                    con.execute(f"UPDATE {tabella} SET {colonna}_norm = ? WHERE id = ?",
                                (atteso, ident))
                    cambiati += 1

    righe = []
    for vid, nome, cantina in con.execute(
            "SELECT id, nome, COALESCE(cantina,'') FROM vino"):
        righe.append((f"{cantina} {nome}".strip(), "vino", vid, 100))
    for tid, nome, den in con.execute(
            "SELECT t.id, t.nome, d.nome FROM tipologia t"
            " JOIN denominazione d ON d.id = t.denominazione_id"):
        righe.append((nome if normalizza(den) in normalizza(nome) else f"{den} {nome}",
                      "tipologia", tid, 70))
    for did, nome in con.execute("SELECT id, nome FROM denominazione"):
        righe.append((nome, "denominazione", did, 50))
    for gid, nome in con.execute("SELECT id, nome FROM vitigno"):
        righe.append((nome, "vitigno", gid, 30))

    con.execute("DELETE FROM ricerca")
    con.executemany(
        "INSERT INTO ricerca(testo, ambito, ambito_id, peso) VALUES (?,?,?,?)",
        [(normalizza(t), a, i, p) for t, a, i, p in righe])
    con.commit()
    con.execute("INSERT INTO ricerca(ricerca) VALUES('optimize')")
    con.commit()
    con.close()
    print(f"  {cambiati} forme normalizzate aggiornate")
    print(f"  {len(righe)} voci reinserite nell'indice di ricerca")


if __name__ == "__main__":
    main()
