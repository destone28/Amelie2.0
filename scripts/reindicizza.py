#!/usr/bin/env python3
"""Ricalcola le forme normalizzate e l'indice di ricerca del database.

Serve quando cambia `amelie.text.normalizza`. Le colonne `*_norm` e la tabella
`ricerca` sono derivate: si ricavano dai nomi originali, che restano nel
database. Ricavarle di nuovo da lì evita di rifare il database dalle sorgenti
(centomila vini) e soprattutto **non tocca gli identificativi**, a cui sono
agganciati i racconti pronti della tabella `racconto` (vedi
`scripts/genera_corpus.py`) e le correzioni collegate a una bottiglia
dell'archivio.

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

# Il peso di ogni ambito nell'indice. Il matcher lo somma alla somiglianza, in
# centesimi: vedi `Candidato.punteggio`.
PESO = {"vino": 100, "denominazione": 70, "tipologia": 50, "vitigno": 30}


def reindicizza(con: sqlite3.Connection) -> tuple[int, int]:
    """Rifa' le forme normalizzate e l'indice. Non chiude la connessione.

    Sta qui e non in `data/build_db.py` perche' serve anche da sola, quando
    cambia `normalizza` e non si vuole ricostruire tutto. Chi costruisce la
    chiama come ultimo passo.
    """
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

    # L'indice e' l'accordo fra chi costruisce il database e il matcher.
    # Il testo e' normalizzato come lo normalizza il dispositivo, e il peso
    # dice quanto il record e' specifico: a parita' di somiglianza un vino
    # batte una denominazione, e la denominazione batte le sue tipologie -
    # «Barolo» letto su un'etichetta e' la denominazione, non la prima delle
    # sue tipologie. Ogni record si indicizza col suo nome e basta.
    righe = []
    for vid, nome, cantina in con.execute(
            "SELECT id, nome, COALESCE(cantina,'') FROM vino"):
        righe.append((f"{cantina} {nome}".strip(), "vino", vid, PESO["vino"]))
    for did, nome in con.execute("SELECT id, nome FROM denominazione"):
        righe.append((nome, "denominazione", did, PESO["denominazione"]))
    for tid, nome in con.execute("SELECT id, nome FROM tipologia"):
        righe.append((nome, "tipologia", tid, PESO["tipologia"]))
    for gid, nome in con.execute("SELECT id, nome FROM vitigno"):
        righe.append((nome, "vitigno", gid, PESO["vitigno"]))

    con.execute("DELETE FROM ricerca")
    con.executemany(
        "INSERT INTO ricerca(testo, ambito, ambito_id, peso) VALUES (?,?,?,?)",
        [(normalizza(t), a, i, p) for t, a, i, p in righe])
    con.commit()
    con.execute("INSERT INTO ricerca(ricerca) VALUES('optimize')")
    con.commit()
    return cambiati, len(righe)


def main() -> None:
    percorso = Path(sys.argv[1]) if len(sys.argv) > 1 else RADICE / "data" / "amelie.db"
    if not percorso.exists():
        sys.exit(f"non trovo {percorso}")
    con = sqlite3.connect(percorso)
    cambiati, voci = reindicizza(con)
    con.close()
    print(f"  {cambiati} forme normalizzate aggiornate")
    print(f"  {voci} voci reinserite nell'indice di ricerca")


if __name__ == "__main__":
    main()
