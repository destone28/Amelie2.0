#!/usr/bin/env python3
"""Costruisce il database locale dei vini.

    python3 data/build_db.py            -> data/amelie.db

Il dispositivo non si connette mai a nulla: tutto quello che sa deve stare qui
dentro. Il database si ricostruisce dagli snapshot versionati in data/sources/,
quindi fra un anno lo si rifà identico anche se gli endpoint non rispondono più.

## La scelta che regge tutto: i fatti separati dallo stile

Un modello da 0,8 miliardi di parametri non sa nulla di vino. Se gli si chiede di
raccontare un Sagrantino inventa premi, punteggi e note di degustazione. Per
questo i FATTI vengono da qui e il modello si limita alla PROSA.

E i fatti vanno tenuti separati anche fra loro. Il disciplinare dell'Amarone
IMPONE Corvina, Corvinone e Rondinella, e AMMETTE anche Croatina, Barbera,
Cabernet e altri trenta. Appiattire le due liste in una sola fa dire al modello
che quell'Amarone contiene Croatina — che è falso, e in sala è una figuraccia.
Per questo `tipologia_vitigno` ha una colonna `ruolo`, e il narratore usa solo
i vitigni `principale`.

## Le fonti

- `PDO_wine_data_IT_FR.csv` (CC BY 4.0, Candiago et al. 2024): denominazioni e
  tipologie italiane con colore, categoria, vitigni imposti e ammessi, rese.
- `xwines_italia.csv` (X-Wines, dal repository ufficiale): i vini commerciali
  italiani con cantina, regione, vitigni, abbinamenti, annate.
- `vitigni.json`: scritto a mano, perché una descrizione organolettica
  affidabile non si trova in una fonte aperta riutilizzabile.

Vedi docs/ATTRIBUZIONI.md per le licenze.
"""

from __future__ import annotations

import ast
import csv
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SORGENTI = RADICE / "data" / "sources"
USCITA = RADICE / "data" / "amelie.db"

FIGSHARE = SORGENTI / "PDO_wine_data_IT_FR.csv"
XWINES = SORGENTI / "xwines_italia.csv"
VITIGNI = RADICE / "data" / "vitigni.json"

# Suffisso di colore della bacca nei nomi del registro UE: "Corvina N".
COLORE_BACCA = {
    "N": "nera", "B": "bianca", "G": "grigia", "Rs": "rosata", "R": "rosata",
}


# --------------------------------------------------------------- normalizzazione

def normalizza(s: str) -> str:
    """Stessa normalizzazione di `amelie.text`, ripetuta qui di proposito.

    Questo script deve poter girare senza il pacchetto installato — è il primo
    passo di un'installazione pulita — quindi non importa da `amelie`. Le due
    implementazioni sono tenute allineate da `tests/test_build_db.py`.
    """
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower().replace(".", "")
    fuori = []
    for pezzo in "".join(c if c.isalnum() else " " for c in s).split():
        fuori.append(pezzo if pezzo.isdigit() else pezzo.translate(
            str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "6": "g", "2": "z"})
        ))
    return " ".join(fuori)


def pulisci_vitigno(grezzo: str) -> tuple[str, str | None]:
    """"Corvina N" -> ("Corvina", "nera"). Il suffisso è il colore della bacca."""
    parti = grezzo.strip().split()
    if len(parti) > 1 and parti[-1] in COLORE_BACCA:
        return " ".join(parti[:-1]), COLORE_BACCA[parti[-1]]
    return grezzo.strip(), None


def elenco(grezzo: str) -> list[str]:
    """I vitigni sono separati da punto e virgola nel dataset UE."""
    return [v.strip() for v in (grezzo or "").split(";") if v.strip()]


def lista_python(grezzo: str) -> list:
    """X-Wines serializza le liste come repr Python: "['Corvina', 'Rondinella']"."""
    if not grezzo:
        return []
    try:
        valore = ast.literal_eval(grezzo)
        return list(valore) if isinstance(valore, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []


# --------------------------------------------------------------------- schema

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE fonte (
    id           TEXT PRIMARY KEY,
    nome         TEXT NOT NULL,
    url          TEXT,
    licenza      TEXT NOT NULL,
    licenza_url  TEXT,
    attribuzione TEXT
);

CREATE TABLE denominazione (
    id        INTEGER PRIMARY KEY,
    codice    TEXT UNIQUE,              -- PDO-IT-A0435
    nome      TEXT NOT NULL,
    nome_norm TEXT NOT NULL,
    tipo      TEXT NOT NULL,            -- DOP | IGP
    fonte_id  TEXT REFERENCES fonte(id)
);
CREATE INDEX i_den_norm ON denominazione(nome_norm);

CREATE TABLE tipologia (
    id               INTEGER PRIMARY KEY,
    denominazione_id INTEGER NOT NULL REFERENCES denominazione(id),
    nome             TEXT NOT NULL,     -- "Amarone della Valpolicella Classico"
    nome_norm        TEXT NOT NULL,
    colore           TEXT,              -- Red | White | Rosé  (chiave del lessico)
    categoria        TEXT,              -- Wine | Sparkling Wine | ...
    resa_max_hl      REAL,
    densita_min      REAL,
    url_ue           TEXT,
    fonte_id         TEXT REFERENCES fonte(id),
    UNIQUE(denominazione_id, nome, colore, categoria)
);
CREATE INDEX i_tip_norm ON tipologia(nome_norm);

CREATE TABLE vitigno (
    id            INTEGER PRIMARY KEY,
    nome          TEXT UNIQUE NOT NULL,
    nome_norm     TEXT NOT NULL,
    colore_bacca  TEXT,
    -- i campi sotto arrivano da data/vitigni.json, scritto a mano
    descrizione   TEXT,
    note_sensoriali TEXT,
    temperatura_c TEXT,
    abbinamenti   TEXT
);
CREATE INDEX i_vit_norm ON vitigno(nome_norm);

-- LA tabella che impedisce di dire il falso: 'principale' e' cio' che il
-- disciplinare IMPONE, 'ammesso' cio' che TOLLERA. Il narratore usa solo il primo.
CREATE TABLE tipologia_vitigno (
    tipologia_id INTEGER NOT NULL REFERENCES tipologia(id),
    vitigno_id   INTEGER NOT NULL REFERENCES vitigno(id),
    ruolo        TEXT NOT NULL CHECK (ruolo IN ('principale','ammesso')),
    PRIMARY KEY (tipologia_id, vitigno_id, ruolo)
);
CREATE INDEX i_tv_tip ON tipologia_vitigno(tipologia_id, ruolo);

CREATE TABLE vino (
    id               INTEGER PRIMARY KEY,
    codice           TEXT UNIQUE,       -- WineID di X-Wines
    nome             TEXT NOT NULL,
    nome_norm        TEXT NOT NULL,
    cantina          TEXT,
    cantina_norm     TEXT,
    regione          TEXT,
    tipo             TEXT,              -- Red | White | ... (chiave del lessico)
    elaborazione     TEXT,
    abv              REAL,
    corpo            TEXT,
    acidita          TEXT,
    sito             TEXT,
    denominazione_id INTEGER REFERENCES denominazione(id),
    fonte_id         TEXT REFERENCES fonte(id)
);
CREATE INDEX i_vino_norm ON vino(nome_norm);
CREATE INDEX i_vino_cantina ON vino(cantina_norm);

CREATE TABLE vino_vitigno (
    vino_id    INTEGER NOT NULL REFERENCES vino(id),
    vitigno_id INTEGER NOT NULL REFERENCES vitigno(id),
    PRIMARY KEY (vino_id, vitigno_id)
);
CREATE TABLE vino_abbinamento (
    vino_id     INTEGER NOT NULL REFERENCES vino(id),
    abbinamento TEXT NOT NULL,          -- chiave del lessico
    PRIMARY KEY (vino_id, abbinamento)
);
CREATE TABLE vino_annata (
    vino_id INTEGER NOT NULL REFERENCES vino(id),
    anno    INTEGER NOT NULL,
    PRIMARY KEY (vino_id, anno)
);

-- I racconti pre-generati dall'LLM locale, indicizzati per cio' che descrivono.
CREATE TABLE racconto (
    id          INTEGER PRIMARY KEY,
    ambito      TEXT NOT NULL CHECK (ambito IN ('vino','tipologia','denominazione','vitigno')),
    ambito_id   INTEGER NOT NULL,
    lingua      TEXT NOT NULL,
    testo       TEXT NOT NULL,
    modello     TEXT,
    generato_il TEXT,
    UNIQUE(ambito, ambito_id, lingua)
);

-- Indice full-text unico su cui gira la ricerca. 'peso' distingue quanto un
-- record e' specifico: un vino commerciale batte una denominazione a parita'
-- di somiglianza, perche' dice di piu'.
CREATE VIRTUAL TABLE ricerca USING fts5(
    testo,
    ambito UNINDEXED,
    ambito_id UNINDEXED,
    peso UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);
"""

FONTI = [
    ("figshare_pdo", "Quality wines in Italy and France: PDO specifications",
     "https://doi.org/10.6084/m9.figshare.25393261", "CC BY 4.0",
     "https://creativecommons.org/licenses/by/4.0/",
     "Candiago, Tscholl, Bassani, Fraga, Egarter Vigl (2024)"),
    ("xwines", "X-Wines",
     "https://github.com/rogerioxavier/X-Wines", "vedi LICENSE del repository",
     "https://github.com/rogerioxavier/X-Wines/blob/main/LICENSE",
     "de Azambuja, Morais, Filipe (2023), Big Data Cogn. Comput. 7(1):20"),
    ("amelie", "Conoscenza enologica del progetto",
     None, "GPL-3.0 / CC BY 4.0", None, "Emilio Destratis"),
]


class Costruttore:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.vitigni: dict[str, int] = {}     # nome pulito -> id

    # ---------------------------------------------------------------- vitigni

    def vitigno_id(self, grezzo: str) -> int | None:
        nome, colore = pulisci_vitigno(grezzo)
        if not nome:
            return None
        chiave = normalizza(nome)
        if chiave in self.vitigni:
            return self.vitigni[chiave]
        cur = self.con.execute(
            "INSERT OR IGNORE INTO vitigno(nome, nome_norm, colore_bacca) VALUES (?,?,?)",
            (nome, chiave, colore),
        )
        if cur.lastrowid:
            self.vitigni[chiave] = cur.lastrowid
        else:
            (vid,) = self.con.execute(
                "SELECT id FROM vitigno WHERE nome_norm = ?", (chiave,)
            ).fetchone()
            self.vitigni[chiave] = vid
        return self.vitigni[chiave]

    # ------------------------------------------------------- denominazioni UE

    def carica_denominazioni(self) -> tuple[int, int]:
        if not FIGSHARE.exists():
            sys.exit(f"manca {FIGSHARE}")
        with FIGSHARE.open(encoding="utf-8-sig", newline="") as f:
            righe = [r for r in csv.DictReader(f, delimiter=";") if r["Country"] == "IT"]

        den_id: dict[str, int] = {}
        n_tip = 0
        for r in righe:
            codice = r["PDOid"].strip()
            if codice not in den_id:
                cur = self.con.execute(
                    "INSERT INTO denominazione(codice, nome, nome_norm, tipo, fonte_id)"
                    " VALUES (?,?,?,?,?)",
                    (codice, r["PDOnam"].strip(), normalizza(r["PDOnam"]),
                     "IGP" if codice.startswith("PGI") else "DOP", "figshare_pdo"),
                )
                den_id[codice] = cur.lastrowid

            nome = r["WineNam"].strip()
            if not nome:
                continue
            # Il dataset ripete la stessa tipologia con categorie diverse: la
            # chiave UNIQUE la deduplica, e l'INSERT OR IGNORE non fallisce.
            cur = self.con.execute(
                "INSERT OR IGNORE INTO tipologia"
                "(denominazione_id, nome, nome_norm, colore, categoria,"
                " resa_max_hl, densita_min, url_ue, fonte_id)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (den_id[codice], nome, normalizza(nome),
                 r["Color"] or None, r["Category"] or None,
                 _numero(r["Max_yield_hl"]), _numero(r["Min_density"]),
                 (r.get("Info") or "").strip() or None, "figshare_pdo"),
            )
            tid = cur.lastrowid
            if not tid:
                riga = self.con.execute(
                    "SELECT id FROM tipologia WHERE denominazione_id=? AND nome=?"
                    " AND colore IS ? AND categoria IS ?",
                    (den_id[codice], nome, r["Color"] or None, r["Category"] or None),
                ).fetchone()
                if not riga:
                    continue
                tid = riga[0]
            else:
                n_tip += 1

            for ruolo, campo in (("principale", "Main_var"), ("ammesso", "Second_var")):
                for grezzo in elenco(r[campo]):
                    vid = self.vitigno_id(grezzo)
                    if vid:
                        self.con.execute(
                            "INSERT OR IGNORE INTO tipologia_vitigno"
                            "(tipologia_id, vitigno_id, ruolo) VALUES (?,?,?)",
                            (tid, vid, ruolo),
                        )
        return len(den_id), n_tip

    # ------------------------------------------------------ vini commerciali

    def carica_vini(self) -> int:
        if not XWINES.exists():
            print(f"  (salto i vini commerciali: manca {XWINES.name})")
            return 0
        csv.field_size_limit(10 ** 7)
        with XWINES.open(encoding="utf-8-sig", newline="") as f:
            righe = list(csv.DictReader(f))

        # Per agganciare un vino alla sua denominazione: il nome della
        # denominazione compare quasi sempre dentro il nome del vino o della
        # regione ("Barolo", "Chianti Classico"). Si prende la corrispondenza
        # piu' LUNGA, perche' "Chianti Classico" batte "Chianti".
        denominazioni = sorted(
            self.con.execute("SELECT id, nome_norm FROM denominazione").fetchall(),
            key=lambda x: -len(x[1]),
        )

        n = 0
        for r in righe:
            nome = (r.get("WineName") or "").strip()
            if not nome:
                continue
            nome_norm = normalizza(nome)
            regione_norm = normalizza(r.get("RegionName") or "")
            den = None
            for did, dnorm in denominazioni:
                if len(dnorm) < 4:
                    continue
                if dnorm in nome_norm or dnorm in regione_norm:
                    den = did
                    break

            cur = self.con.execute(
                "INSERT OR IGNORE INTO vino"
                "(codice, nome, nome_norm, cantina, cantina_norm, regione, tipo,"
                " elaborazione, abv, corpo, acidita, sito, denominazione_id, fonte_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("WineID"), nome, nome_norm,
                 r.get("WineryName"), normalizza(r.get("WineryName") or ""),
                 r.get("RegionName"), r.get("Type"), r.get("Elaborate"),
                 _numero(r.get("ABV")), r.get("Body"), r.get("Acidity"),
                 r.get("Website"), den, "xwines"),
            )
            vid = cur.lastrowid
            if not vid:
                continue
            n += 1

            for g in lista_python(r.get("Grapes")):
                gid = self.vitigno_id(str(g))
                if gid:
                    self.con.execute(
                        "INSERT OR IGNORE INTO vino_vitigno VALUES (?,?)", (vid, gid))
            for a in lista_python(r.get("Harmonize")):
                self.con.execute(
                    "INSERT OR IGNORE INTO vino_abbinamento VALUES (?,?)", (vid, str(a)))
            for anno in lista_python(r.get("Vintages")):
                if isinstance(anno, int) or (isinstance(anno, str) and anno.isdigit()):
                    self.con.execute(
                        "INSERT OR IGNORE INTO vino_annata VALUES (?,?)", (vid, int(anno)))
        return n

    # ------------------------------------------- conoscenza scritta a mano

    def arricchisci_vitigni(self) -> int:
        if not VITIGNI.exists():
            print(f"  (salto le note sui vitigni: manca {VITIGNI.name})")
            return 0
        dati = json.loads(VITIGNI.read_text(encoding="utf-8"))
        n = 0
        for voce in dati.get("vitigni", []):
            chiave = normalizza(voce["nome"])
            cur = self.con.execute(
                "UPDATE vitigno SET descrizione=?, note_sensoriali=?,"
                " temperatura_c=?, abbinamenti=? WHERE nome_norm=?",
                (voce.get("descrizione"),
                 "; ".join(voce.get("note_sensoriali", [])) or None,
                 voce.get("temperatura_c"),
                 "; ".join(voce.get("abbinamenti", [])) or None,
                 chiave),
            )
            if cur.rowcount:
                n += cur.rowcount
            else:
                # Un vitigno che il progetto descrive ma che i dataset non
                # nominano va inserito lo stesso: serve al fallback.
                self.con.execute(
                    "INSERT OR IGNORE INTO vitigno"
                    "(nome, nome_norm, colore_bacca, descrizione, note_sensoriali,"
                    " temperatura_c, abbinamenti) VALUES (?,?,?,?,?,?,?)",
                    (voce["nome"], chiave, voce.get("colore_bacca"),
                     voce.get("descrizione"),
                     "; ".join(voce.get("note_sensoriali", [])) or None,
                     voce.get("temperatura_c"),
                     "; ".join(voce.get("abbinamenti", [])) or None),
                )
                n += 1
        return n

    # ------------------------------------------------------------- ricerca

    def costruisci_indice(self) -> int:
        """Un solo indice per tutto, con un peso che dice quanto è specifico.

        L'ordine dei pesi è la cascata del fallback: se l'OCR permette di
        arrivare al vino esatto si racconta quello; altrimenti la tipologia,
        poi la denominazione, poi il vitigno. Si scende, non si tace.
        """
        righe = []
        for vid, nome, cantina in self.con.execute(
            "SELECT id, nome, COALESCE(cantina,'') FROM vino"
        ):
            righe.append((f"{cantina} {nome}".strip(), "vino", vid, 100))
        for tid, nome, den in self.con.execute(
            "SELECT t.id, t.nome, d.nome FROM tipologia t"
            " JOIN denominazione d ON d.id = t.denominazione_id"
        ):
            testo = nome if normalizza(den) in normalizza(nome) else f"{den} {nome}"
            righe.append((testo, "tipologia", tid, 70))
        for did, nome in self.con.execute("SELECT id, nome FROM denominazione"):
            righe.append((nome, "denominazione", did, 50))
        for gid, nome in self.con.execute("SELECT id, nome FROM vitigno"):
            righe.append((nome, "vitigno", gid, 30))

        self.con.executemany(
            "INSERT INTO ricerca(testo, ambito, ambito_id, peso) VALUES (?,?,?,?)",
            [(normalizza(t), a, i, p) for t, a, i, p in righe],
        )
        return len(righe)


def _numero(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def main() -> None:
    if USCITA.exists():
        USCITA.unlink()
    for extra in (".db-wal", ".db-shm"):
        p = USCITA.with_suffix(extra)
        p.unlink(missing_ok=True)

    con = sqlite3.connect(USCITA)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO fonte(id,nome,url,licenza,licenza_url,attribuzione)"
        " VALUES (?,?,?,?,?,?)", FONTI)

    c = Costruttore(con)
    print("Costruzione del database:")
    nd, nt = c.carica_denominazioni()
    print(f"  {nd:>6} denominazioni   {nt:>6} tipologie")
    nv = c.carica_vini()
    print(f"  {nv:>6} vini commerciali")
    ng = c.arricchisci_vitigni()
    print(f"  {ng:>6} vitigni descritti a mano")
    ni = c.costruisci_indice()
    print(f"  {ni:>6} voci nell'indice di ricerca")

    con.commit()
    con.execute("PRAGMA journal_mode = DELETE")   # un file solo, piu' facile da copiare
    con.execute("VACUUM")
    con.close()
    print(f"\n  {USCITA}  ({USCITA.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
