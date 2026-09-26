#!/usr/bin/env python3
"""Costruisce il database locale dei vini.

    python3 data/build_db.py                    -> data/amelie.db, tutto
    python3 data/build_db.py --senza-racconti   solo i fatti, senza `racconto`
    python3 data/build_db.py --solo-vitigni     riapplica solo data/vitigni.json

Il dispositivo non si connette mai a nulla: tutto quello che sa deve stare qui
dentro. Il database si ricostruisce dagli snapshot versionati in data/sources/,
quindi fra un anno lo si rifà identico anche se gli endpoint non rispondono più.
Serve solo la libreria standard di Python, senza pacchetti da installare: e' il
primo passo di un'installazione pulita.

I passi, nell'ordine, e perche' l'ordine conta:

1. denominazioni e tipologie DOP da figshare;
2. vini commerciali da X-Wines, ciascuno agganciato alla sua denominazione;
3. le schede dei vitigni scritte a mano, e i nomi italiani dei vitigni di
   X-Wines che mancano («Moscato»);
4. le denominazioni del registro UE che figshare non ha - quasi tutte IGP - e la
   menzione DOCG, DOC o IGT di ognuna. Vengono DOPO i vini: l'aggancio dei vini
   resta quello alle sole DOP, e gli identificativi delle denominazioni figshare
   non si spostano;
5. la regione di ogni denominazione, dalla mappa in data/geografia.py;
6. colore, odore e sapore ufficiali di ogni tipologia, dai documenti unici UE;
7. le forme normalizzate e l'indice di ricerca (scripts/reindicizza.py);
8. il racconto composto di ogni denominazione, tipologia e vitigno, nelle due
   lingue (scripts/genera_corpus.py). Lo legge solo il modo «generativa»: il
   modo predefinito compone il racconto al momento, e senza questa tabella
   funziona uguale. `--senza-racconti` salta questo passo.

Gli identificativi dipendono solo dalle sorgenti e dall'ordine dei passi:
ricostruire con le stesse sorgenti da' gli stessi numeri. Con
`--senza-racconti`, e la stessa versione di SQLite, il file che esce e'
identico byte per byte a ogni costruzione; i racconti invece portano l'ora in
cui sono stati scritti.

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
  italiani con cantina, regione, vitigni, abbinamenti.
- `eambrosia_it_wine.tsv`, `documenti_unici.jsonl` (© Unione europea, CC BY
  4.0): il registro delle indicazioni geografiche e il testo dei documenti
  unici. Vedi data/fonti_ue.py.
- `docg.txt`: l'elenco delle DOCG, che il registro UE non distingue dalle DOC.
- `vitigni.json`: scritto a mano, perché una descrizione organolettica
  affidabile non si trova in una fonte aperta riutilizzabile.

Vedi data/sources/LEGGIMI.md e docs/it/08-attribuzioni.md per provenienza e licenze.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
import pathlib
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SORGENTI = RADICE / "data" / "sources"
USCITA = RADICE / "data" / "amelie.db"
IN_CORSO = RADICE / "data" / "amelie.db.in-corso"

FIGSHARE = SORGENTI / "PDO_wine_data_IT_FR.csv"
XWINES = SORGENTI / "xwines_italia.csv"
VITIGNI = RADICE / "data" / "vitigni.json"

sys.path.insert(0, str(RADICE / "scripts"))
sys.path.insert(0, str(RADICE / "data"))
from reindicizza import reindicizza                            # noqa: E402
import fonti_ue                                                # noqa: E402
from geografia import regione_di                               # noqa: E402

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
    ).lower()
    s = _sciogli_punti(s)
    fuori = []
    for pezzo in "".join(c if c.isalnum() else " " for c in s).split():
        fuori.append(pezzo if pezzo.isdigit() else pezzo.translate(
            str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "6": "g", "2": "z"})
        ))
    return " ".join(fuori)


def _sciogli_punti(s: str) -> str:
    """Come `amelie.text._sciogli_punti`. Vedi la' il perche'."""
    def _unisci(m) -> str:
        pezzi = [p for p in m.group(0).split(".") if p]
        if all(p.isdigit() for p in pezzi):
            return "".join(pezzi)
        fuori, sigla = [], []
        for p in pezzi:
            if len(p) == 1 or (sigla and len(p) <= 3):
                sigla.append(p)
                if len(p) > 1:
                    fuori.append("".join(sigla)); sigla = []
                continue
            if sigla:
                fuori.append("".join(sigla)); sigla = []
            fuori.append(p)
        if sigla:
            fuori.append("".join(sigla))
        return " ".join(fuori)

    return re.sub(r"[0-9a-z]+(?:\.[0-9a-z]+)*\.?", _unisci, s)


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
    codice    TEXT UNIQUE,              -- numero di fascicolo UE: PDO-IT-A0435
    nome      TEXT NOT NULL,
    nome_norm TEXT NOT NULL,
    tipo      TEXT NOT NULL,            -- DOP | IGP
    fonte_id  TEXT REFERENCES fonte(id),
    menzione  TEXT,                     -- DOCG | DOC | IGT
    regione   TEXT                      -- NULL se il nome non basta a dirla
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
    -- i campi sotto arrivano da data/vitigni.json, scritto a mano.
    -- Bilingui: la lingua si sceglie a schermo, e una descrizione tradotta a
    -- meta' produrrebbe un periodo inglese con dentro una frase italiana.
    descrizione   TEXT,
    note_sensoriali TEXT,
    temperatura_c TEXT,
    abbinamenti   TEXT,
    descrizione_en     TEXT,
    note_sensoriali_en TEXT,
    abbinamenti_en     TEXT
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
-- Per ordinare i vitigni di una denominazione per quanti suoi vini li usano.
CREATE INDEX i_vino_den ON vino(denominazione_id);

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

-- Le tipologie come le descrive il documento unico UE: colore, odore e sapore
-- scritti dal disciplinare, e i minimi di legge. Non si fondono con `tipologia`,
-- che viene da figshare: le due fonti non hanno una chiave in comune, e si
-- accostano solo per denominazione e colore (vedi il matcher).
-- `nome_incerto` = 1 quando il nome e' ricostruito o ipotizzato e non
-- distingue una tipologia dall'altra; `colore` e' Rosso | Bianco | Rosato.
CREATE TABLE tipologia_ue (
    id               INTEGER PRIMARY KEY,
    denominazione_id INTEGER REFERENCES denominazione(id),
    nome             TEXT,
    nome_incerto     INTEGER NOT NULL DEFAULT 0,
    menzione         TEXT,
    colore           TEXT,
    desc_colore      TEXT,
    desc_odore       TEXT,
    desc_sapore      TEXT,
    titolo_alcol_min REAL,
    acidita_min      REAL,
    estratto_min     REAL,
    fonte_id         TEXT REFERENCES fonte(id)
);
CREATE INDEX i_tue_den ON tipologia_ue(denominazione_id, colore);

-- I racconti pronti, indicizzati per cio' che descrivono. `modello` dice da
-- dove vengono: 'template' se composti dai fatti, altrimenti il modello.
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
    ("eambrosia", "Registro UE delle indicazioni geografiche (eAmbrosia)",
     "https://ec.europa.eu/geographical-indications-register/", "CC BY 4.0",
     "https://creativecommons.org/licenses/by/4.0/",
     "© Unione europea. Riuso ai sensi della Decisione 2011/833/UE."),
    ("documento_unico_ue", "Documenti unici delle DOP e IGP (eAmbrosia)",
     "https://ec.europa.eu/geographical-indications-register/", "CC BY 4.0",
     "https://creativecommons.org/licenses/by/4.0/",
     "© Unione europea. Il testo riproduce il disciplinare di produzione."),
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
        if cur.rowcount:                  # vedi carica_denominazioni: rowcount
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
            # Il nome della tipologia ripete quello della denominazione, a
            # volte con le maiuscole cambiate («Costa Dell'Argentario»): vale
            # la grafia della denominazione.
            for parte in r["PDOnam"].split("/"):
                parte = parte.strip()
                if parte and nome.lower().startswith(parte.lower()):
                    nome = parte + nome[len(parte):]
                    break
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
            # `rowcount`, non `lastrowid`: su una riga ignorata `lastrowid`
            # resta quello dell'ultimo inserimento sulla connessione - una riga
            # di `tipologia_vitigno` - e i vitigni del doppione finirebbero su
            # una tipologia qualunque: il Lizzano Negroamaro nascerebbe anche
            # da Aleatico.
            tid = cur.lastrowid if cur.rowcount else None
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
            if not cur.rowcount:              # WineID gia' visto
                continue
            vid = cur.lastrowid
            n += 1

            for g in lista_python(r.get("Grapes")):
                gid = self.vitigno_id(str(g))
                if gid:
                    self.con.execute(
                        "INSERT OR IGNORE INTO vino_vitigno VALUES (?,?)", (vid, gid))
            for a in lista_python(r.get("Harmonize")):
                self.con.execute(
                    "INSERT OR IGNORE INTO vino_abbinamento VALUES (?,?)", (vid, str(a)))
            # Le annate di X-Wines non si caricano: il dispositivo non le usa,
            # l'annata la legge sull'etichetta.
        return n

    # ------------------------------------------- conoscenza scritta a mano

    def arricchisci_vitigni(self) -> int:
        """Applica data/vitigni.json, alias compresi.

        Gli alias servono perche' i dataset chiamano lo stesso vitigno in modi
        diversi - «Syrah/Shiraz», «Pinot Noir», «Glera/Prosecco» - e senza
        aggancio 1.215 Prosecco restavano senza una riga da dire. Si applicano
        solo i sinonimi VERI, dichiarati a mano nel file: attaccare la
        descrizione della Barbera alla «Barbera Bianca», che e' un altro
        vitigno, sarebbe inventare.
        """
        if not VITIGNI.exists():
            print(f"  (salto le note sui vitigni: manca {VITIGNI.name})")
            return 0
        dati = json.loads(VITIGNI.read_text(encoding="utf-8"))
        n = 0
        for voce in dati.get("vitigni", []):
            campi = (
                voce.get("descrizione"),
                "; ".join(voce.get("note_sensoriali", [])) or None,
                voce.get("temperatura_c"),
                "; ".join(voce.get("abbinamenti", [])) or None,
                voce.get("descrizione_en"),
                "; ".join(voce.get("note_sensoriali_en", [])) or None,
                "; ".join(voce.get("abbinamenti_en", [])) or None,
            )
            # Il nome canonico piu' tutti i suoi alias: la stessa descrizione
            # va su ognuno, perche' sono la stessa uva scritta in modi diversi.
            nomi = [voce["nome"], *voce.get("alias", [])]
            colpito = False
            for nome in nomi:
                cur = self.con.execute(
                    "UPDATE vitigno SET descrizione=?, note_sensoriali=?,"
                    " temperatura_c=?, abbinamenti=?, descrizione_en=?,"
                    " note_sensoriali_en=?, abbinamenti_en=? WHERE nome_norm=?",
                    (*campi, normalizza(nome)))
                if cur.rowcount:
                    n += cur.rowcount
                    colpito = True
            if not colpito:
                # Un vitigno che il progetto descrive ma che i dataset non
                # nominano va inserito lo stesso: serve al fallback.
                self.con.execute(
                    "INSERT OR IGNORE INTO vitigno"
                    "(nome, nome_norm, colore_bacca, descrizione, note_sensoriali,"
                    " temperatura_c, abbinamenti, descrizione_en,"
                    " note_sensoriali_en, abbinamenti_en)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (voce["nome"], normalizza(voce["nome"]),
                     voce.get("colore_bacca"), *campi))
                n += 1
            # Il colore della bacca manca su molte voci dei dataset, e senza di
            # esso salta il controllo che impedisce di chiamare bianco un rosso.
            if voce.get("colore_bacca"):
                self.con.execute(
                    "UPDATE vitigno SET colore_bacca=? WHERE colore_bacca IS NULL"
                    f" AND nome_norm IN ({','.join('?' * len(nomi))})",
                    (voce["colore_bacca"], *(normalizza(x) for x in nomi)))
        return n

    def aggiungi_nomi_italiani(self, nomi: list[str]) -> int:
        """I nomi italiani dei vitigni di X-Wines che l'archivio non ha ancora.

        Si riapplica poi vitigni.json, perche' un nome appena aggiunto puo'
        essere l'alias di una scheda scritta a mano («Moscato» di «Moscato
        Bianco») e deve averne la descrizione.
        """
        n = fonti_ue.aggiungi_vitigni_mancanti(self.con, nomi, normalizza)
        if n:
            self.arricchisci_vitigni()
        return n

    # ------------------------------------------------------------ registro UE

    def carica_registro_ue(self, voci: list[fonti_ue.VoceRegistro]) -> int:
        """Le denominazioni che figshare non ha, e la menzione di tutte."""
        return fonti_ue.carica_registro(self.con, voci, normalizza)

    def assegna_regioni(self) -> int:
        """La regione di ogni denominazione, dal nome. Vedi data/geografia.py."""
        righe = [(regione_di(nome), did) for did, nome in
                 self.con.execute("SELECT id, nome FROM denominazione").fetchall()]
        self.con.executemany("UPDATE denominazione SET regione = ? WHERE id = ?", righe)
        return sum(1 for r, _ in righe if r)


def _numero(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def solo_vitigni() -> None:
    """Riapplica data/vitigni.json a un database gia' costruito.

    Chi aggiunge un vitigno o una traduzione non deve ricostruire tutto, e
    soprattutto non deve rifare gli identificativi, a cui sono agganciati i
    testi gia' pre-generati.
    """
    if not USCITA.exists():
        sys.exit(f"non trovo {USCITA}: serve un database gia' costruito")
    con = sqlite3.connect(USCITA)
    esistenti = {r[1] for r in con.execute("PRAGMA table_info(vitigno)")}
    for colonna in ("descrizione_en", "note_sensoriali_en", "abbinamenti_en"):
        if colonna not in esistenti:
            con.execute(f"ALTER TABLE vitigno ADD COLUMN {colonna} TEXT")
            print(f"  aggiunta la colonna {colonna}")
    n = Costruttore(con).arricchisci_vitigni()
    con.commit()
    con.close()
    print(f"  {n} voci di vitigno aggiornate")


def _togli(percorso: Path) -> None:
    for extra in ("", "-wal", "-shm", "-journal"):
        pathlib.Path(str(percorso) + extra).unlink(missing_ok=True)


def scrivi_racconti(percorso: Path) -> tuple[int, int]:
    """Riempie `racconto` con scripts/genera_corpus.py. Ritorna (scritti, saltati).

    Usa il matcher e il lessico del dispositivo, cioe' il pacchetto in src/:
    per questo si importa qui, e solo se il passo non e' saltato.
    """
    sys.path.insert(0, str(RADICE / "src"))
    import genera_corpus                                       # noqa: E402
    return genera_corpus.genera(percorso, stampa=lambda *_: None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Costruisce data/amelie.db dalle sorgenti.")
    ap.add_argument("--senza-racconti", action="store_true",
                    help="non scrive la tabella `racconto` (scripts/genera_corpus.py)")
    ap.add_argument("--solo-vitigni", action="store_true",
                    help="riapplica solo data/vitigni.json al database esistente")
    args = ap.parse_args()
    if args.solo_vitigni:
        return solo_vitigni()
    for fonte in (FIGSHARE, fonti_ue.REGISTRO, fonti_ue.DOCUMENTI):
        if not fonte.exists():
            sys.exit(f"manca {fonte}")
    inizio = time.monotonic()

    # Si costruisce a lato e si sostituisce solo a fine riuscita: una
    # costruzione che si ferma a meta' lascia al suo posto il database di
    # prima, non uno vuoto.
    _togli(IN_CORSO)
    con = sqlite3.connect(IN_CORSO)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO fonte(id,nome,url,licenza,licenza_url,attribuzione)"
        " VALUES (?,?,?,?,?,?)", FONTI)

    c = Costruttore(con)
    print("Costruzione del database:")
    nd, nt = c.carica_denominazioni()
    print(f"  {nd:>6} denominazioni DOP   {nt:>6} tipologie (figshare)")
    nv = c.carica_vini()
    print(f"  {nv:>6} vini commerciali (X-Wines)")
    ng = c.arricchisci_vitigni()
    print(f"  {ng:>6} vitigni descritti a mano")
    nomi_vitigni = fonti_ue.vitigni_xwines(XWINES)
    ni = c.aggiungi_nomi_italiani(nomi_vitigni)
    print(f"  {ni:>6} nomi italiani di vitigno aggiunti")
    voci = fonti_ue.leggi_registro()
    nr = c.carica_registro_ue(voci)
    print(f"  {nr:>6} denominazioni dal registro UE, su {len(voci)}")
    ng = c.assegna_regioni()
    print(f"  {ng:>6} denominazioni con la regione")
    nu, du = fonti_ue.carica_tipologie_ue(con, voci, nomi_vitigni)
    print(f"  {nu:>6} tipologie dai documenti unici, su {du} denominazioni")
    _, nix = reindicizza(con)
    print(f"  {nix:>6} voci nell'indice di ricerca")
    con.commit()

    if not args.senza_racconti:
        con.close()
        scritti, vuoti = scrivi_racconti(IN_CORSO)
        print(f"  {scritti:>6} racconti composti ({vuoti} saltati: nessun fatto da dire)")
        con = sqlite3.connect(IN_CORSO)

    con.execute("PRAGMA journal_mode = DELETE")   # un file solo, piu' facile da copiare
    con.execute("VACUUM")
    con.close()
    IN_CORSO.replace(USCITA)
    print(f"\n  {USCITA}  ({USCITA.stat().st_size / 1e6:.1f} MB,"
          f" {time.monotonic() - inizio:.0f} s)")


if __name__ == "__main__":
    main()
