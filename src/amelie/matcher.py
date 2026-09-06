"""Dal testo dell'etichetta al record: chi è questo vino.

L'OCR restituisce righe rumorose. Qui si decide che cosa il dispositivo ha
davanti, e con quanta sicurezza. La risposta non è mai «non lo so»: è una
**cascata**, e si scende finché si trova qualcosa di vero da dire.

    vino commerciale  ->  «Questo è il Barolo Cannubi di Marchesi di Barolo»
    tipologia         ->  «Non leggo bene il produttore, ma è un Barolo Riserva»
    denominazione     ->  «È un Barolo»
    vitigno           ->  «È un Nebbiolo»
    niente            ->  «Prova a girare l'etichetta verso di me»

Il livello raggiunto决 decide anche il tono: sotto il primo gradino il narratore
non deve mai attribuire a un produttore sconosciuto caratteristiche che non ha
verificato.

## Come si sceglie

Due stadi, perché fanno cose diverse:

1. **FTS5 con ranking BM25** trova i candidati. BM25 pesa già i termini per
   rarità, ed è questo che risolve il problema dei token comuni: «San» compare
   in centinaia di nomi e conta pochissimo, «Sassicaia» compare una volta e
   conta moltissimo. Senza questa pesatura, «Tenuta San Guido Sassicaia»
   pescherebbe il vitigno «San Lunardo».

2. **RapidFuzz** riordina i candidati sul testo intero. FTS5 ragiona per parole,
   il fuzzy per caratteri: l'uno recupera ciò che l'altro perde quando l'OCR
   sbaglia una lettera.

Le soglie sono empiriche e vanno ritarate sulle catture reali.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from .text import estrai_annata, normalizza, parole_utili

log = logging.getLogger(__name__)

PERCORSO_DB = Path(__file__).resolve().parents[2] / "data" / "amelie.db"

# Sopra questa somiglianza il match si considera certo e si racconta il vino.
SOGLIA_CERTA = 88
# Sotto SOGLIA_CERTA ma sopra questa, si mostrano i candidati e si chiede conferma.
SOGLIA_DUBBIA = 75
# Quanti candidati chiedere a FTS5 prima di riordinarli col fuzzy.
CANDIDATI = 200
# Su quanti dei migliori rifare il calcolo della sicurezza, che costa una query
# in piu' ciascuno. Oltre la ventina non cambia mai l'esito.
VERIFICATI = 25

# Tetto alla sicurezza in funzione di quante parole utili ha restituito l'OCR.
# Con una parola sola non si puo' essere certi di NULLA: "Rosso" combacia con
# "Falco Rosso" al 100% per pura aritmetica degli insiemi, ma non identifica
# alcun vino. La certezza richiede piu' indizi indipendenti, non un indizio
# fortissimo. Indice = numero di parole utili.
TETTO_PER_PAROLE = (0.0, 60.0, 78.0, 87.0)   # 0, 1, 2, 3 parole; da 4 in su nessun tetto


class Livello(str, Enum):
    """Quanto in basso è dovuta scendere la cascata."""

    VINO = "vino"
    TIPOLOGIA = "tipologia"
    DENOMINAZIONE = "denominazione"
    VITIGNO = "vitigno"
    NULLA = "nulla"


@dataclass
class Candidato:
    ambito: str
    ambito_id: int
    testo: str
    somiglianza: float
    peso: int
    esatto: bool = False

    @property
    def punteggio(self) -> float:
        """Somiglianza, con una spinta per i record più specifici.

        A parità di somiglianza un vino commerciale vale più di una
        denominazione, perché dice molto di più. La spinta è piccola di
        proposito: non deve mai far vincere un vino palesemente diverso su una
        denominazione palesemente giusta.
        """
        # Il bonus per la corrispondenza esatta deve battere qualunque
        # differenza di peso (100 per un vino, 30 per un vitigno).
        return self.somiglianza + self.peso / 100.0 + (15.0 if self.esatto else 0.0)


@dataclass
class Fatti:
    """Tutto ciò che il dispositivo sa, e nient'altro.

    È il blocco che va al narratore. Ogni campo qui dentro viene dal database:
    se un campo è vuoto, di quella cosa non si parla. Il narratore non ha altre
    fonti.
    """

    livello: Livello = Livello.NULLA
    sicurezza: float = 0.0

    nome: str | None = None
    cantina: str | None = None
    regione: str | None = None
    annata: int | None = None

    denominazione: str | None = None
    tipo_denominazione: str | None = None      # DOP | IGP
    tipologia: str | None = None

    colore: str | None = None                  # chiave del lessico
    categoria: str | None = None               # chiave del lessico
    corpo: str | None = None
    acidita: str | None = None
    elaborazione: str | None = None
    abv: float | None = None

    # LA distinzione che impedisce di dire il falso. `vitigni` è ciò che il vino
    # contiene o che il disciplinare IMPONE; `vitigni_ammessi` è ciò che il
    # disciplinare TOLLERA e che quindi NON si può affermare presente.
    vitigni: list[str] = field(default_factory=list)
    vitigni_ammessi: list[str] = field(default_factory=list)

    abbinamenti: list[str] = field(default_factory=list)
    note_vitigno: str | None = None
    temperatura_c: str | None = None

    candidati: list[str] = field(default_factory=list)   # per la schermata di conferma

    @property
    def certo(self) -> bool:
        return self.sicurezza >= SOGLIA_CERTA

    @property
    def dubbio(self) -> bool:
        return SOGLIA_DUBBIA <= self.sicurezza < SOGLIA_CERTA

    @property
    def vuoto(self) -> bool:
        return self.livello is Livello.NULLA

    def blocco_fatti(self) -> str:
        """I fatti in forma testuale, come vanno dati al modello.

        Solo campi valorizzati, una riga ciascuno. I vitigni ammessi NON
        compaiono: il modello non deve nemmeno vederli, perché se li vede finisce
        per nominarli.
        """
        righe = []
        for etichetta, valore in (
            ("Nome", self.nome),
            ("Produttore", self.cantina),
            ("Regione", self.regione),
            ("Annata", self.annata),
            ("Denominazione", self.denominazione),
            ("Tipologia", self.tipologia),
            ("Colore", self.colore),
            ("Corpo", self.corpo),
            ("Acidità", self.acidita),
            ("Gradazione", f"{self.abv}%" if self.abv else None),
            ("Vitigni", ", ".join(self.vitigni) if self.vitigni else None),
            ("Abbinamenti", ", ".join(self.abbinamenti) if self.abbinamenti else None),
            ("Temperatura di servizio", f"{self.temperatura_c} °C" if self.temperatura_c else None),
            ("Nota sul vitigno", self.note_vitigno),
        ):
            if valore not in (None, "", []):
                righe.append(f"{etichetta}: {valore}")
        return "\n".join(righe)


class Matcher:
    """Interroga il database. Sola lettura, e non tiene stato fra una ricerca e l'altra."""

    def __init__(self, percorso: str | Path | None = None) -> None:
        self.percorso = Path(percorso) if percorso else PERCORSO_DB
        if not self.percorso.exists():
            raise DatabaseAssente(
                f"manca {self.percorso}. Costruiscilo con: python3 data/build_db.py"
            )
        # Sola lettura: il dispositivo non deve poter corrompere il proprio sapere.
        self.con = sqlite3.connect(f"file:{self.percorso}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row

    def chiudi(self) -> None:
        self.con.close()

    # ------------------------------------------------------------- ricerca

    def cerca(self, righe: Sequence[str], *, anno_massimo: int | None = None) -> Fatti:
        """Il punto d'ingresso: righe dell'OCR -> fatti."""
        testo = " ".join(righe)
        annata = estrai_annata(righe, anno_massimo=anno_massimo)
        token = parole_utili(testo)
        if not token:
            return Fatti()

        candidati = self._candidati(token, normalizza(testo))
        if not candidati:
            return Fatti()

        # Il tetto si applica DOPO la scelta: serve a dire quanto ci si puo'
        # fidare, non a cambiare quale record e' il piu' somigliante.
        if len(token) < len(TETTO_PER_PAROLE):
            tetto = TETTO_PER_PAROLE[len(token)]
            for c in candidati:
                c.somiglianza = min(c.somiglianza, tetto)

        migliore = candidati[0]
        fatti = self._componi(migliore)
        fatti.sicurezza = migliore.somiglianza
        fatti.annata = annata
        # Per la schermata di conferma servono alternative DIVERSE fra loro:
        # tre righe che dicono quasi la stessa cosa non aiutano a scegliere.
        visti = {migliore.testo}
        for c in candidati[1:]:
            if len(fatti.candidati) >= 3:
                break
            if c.testo not in visti:
                visti.add(c.testo)
                fatti.candidati.append(c.testo)
        return fatti

    def _candidati(self, token: list[str], testo_norm: str) -> list[Candidato]:
        from rapidfuzz import fuzz

        # FTS5 vuole i termini quotati: un token con un apostrofo o un trattino
        # altrimenti viene letto come sintassi.
        query = " OR ".join(f'"{t}"' for t in token)
        try:
            righe = self.con.execute(
                "SELECT testo, ambito, ambito_id, peso FROM ricerca"
                " WHERE ricerca MATCH ? ORDER BY bm25(ricerca) LIMIT ?",
                (query, CANDIDATI),
            ).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("query FTS rifiutata (%s): %r", e, query)
            return []

        grezzi = [
            Candidato(
                ambito=r["ambito"], ambito_id=r["ambito_id"], testo=r["testo"],
                # token_set_ratio ignora l'ordine e le parole in piu': l'OCR
                # restituisce le righe in ordine di posizione sull'etichetta,
                # non di importanza, e ci mette in mezzo solfiti e millilitri.
                somiglianza=fuzz.token_set_ratio(testo_norm, r["testo"]),
                peso=r["peso"],
            )
            for r in righe
        ]
        grezzi.sort(key=lambda c: c.punteggio, reverse=True)

        # Secondo passaggio, ed e' quello che evita le figuracce. token_set_ratio
        # premia le voci CORTE: "barolo" dentro l'etichetta di un Barolo fa 100,
        # e cosi' faceva 100 anche "Monte Giove" contro "Monte Antico". Ma la
        # sicurezza non e' una proprieta' della stringa: e' una proprieta'
        # dell'AFFERMAZIONE che si sta per fare. Dire "questo e' il Barolo di
        # Marchesi di Barolo" impegna il produttore, e il produttore va
        # verificato; dire "questo e' un Barolo" impegna molto meno.
        # La corrispondenza ESATTA sull'intera stringa e' la prova piu' forte che
        # esista, e va cercata su TUTTI i candidati, non solo sui primi: se
        # l'etichetta dice solo "Nebbiolo", il vitigno Nebbiolo e' sepolto sotto
        # decine di vini che hanno "Nebbiolo" nel nome e BM25 mette prima quelli.
        # La risposta onesta e' il vitigno.
        for c in grezzi:
            if c.testo == testo_norm:
                c.esatto = True
                c.somiglianza = 100.0     # esatto: nessuna scalatura per specificita'
        for c in grezzi[:VERIFICATI]:
            if not c.esatto:
                c.somiglianza = self._sicurezza_verificata(c, testo_norm)
        grezzi.sort(key=lambda c: c.punteggio, reverse=True)
        return grezzi

    def _sicurezza_verificata(self, c: Candidato, testo_norm: str) -> float:
        """Ricalcola la sicurezza in base a quanto pesa l'affermazione.

        Per un vino commerciale servono DUE conferme indipendenti, cantina e
        nome, e vale la piu' debole delle due: un nome giusto con un produttore
        sbagliato e' un vino sbagliato.
        """
        from rapidfuzz import fuzz

        if c.ambito == "vino":
            r = self.con.execute(
                "SELECT nome_norm, COALESCE(cantina_norm,'') FROM vino WHERE id = ?",
                (c.ambito_id,)).fetchone()
            if not r:
                return 0.0
            nome, cantina = r[0], r[1]
            s_nome = fuzz.token_set_ratio(testo_norm, nome) if nome else 0
            if not cantina:
                return s_nome * 0.8      # senza produttore non si e' mai certi
            s_cantina = fuzz.token_set_ratio(testo_norm, cantina)
            # La media pesata premia chi ha entrambe le conferme; il tetto sul
            # minimo impedisce che una sola, fortissima, basti da sola.
            return min(0.6 * s_cantina + 0.4 * s_nome, s_cantina * 1.15, s_nome * 1.6)

        # Per gli altri livelli l'affermazione e' piu' debole, ma resta il
        # problema delle voci corte: una denominazione di una parola sola non
        # puo' valere quanto una di tre. Si scala sulla specificita'.
        parole = len(c.testo.split())
        specificita = min(1.0, 0.55 + 0.15 * parole)
        return fuzz.token_set_ratio(testo_norm, c.testo) * specificita

    # ------------------------------------------------------------ composizione

    def _componi(self, c: Candidato) -> Fatti:
        return {
            "vino": self._fatti_vino,
            "tipologia": self._fatti_tipologia,
            "denominazione": self._fatti_denominazione,
            "vitigno": self._fatti_vitigno,
        }[c.ambito](c.ambito_id)

    def _fatti_vino(self, vid: int) -> Fatti:
        r = self.con.execute(
            "SELECT v.*, d.nome AS den_nome, d.tipo AS den_tipo"
            " FROM vino v LEFT JOIN denominazione d ON d.id = v.denominazione_id"
            " WHERE v.id = ?", (vid,)
        ).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.VINO,
            nome=r["nome"], cantina=r["cantina"], regione=r["regione"],
            denominazione=r["den_nome"], tipo_denominazione=r["den_tipo"],
            colore=r["tipo"], corpo=r["corpo"], acidita=r["acidita"],
            elaborazione=r["elaborazione"], abv=r["abv"],
        )
        f.vitigni = [x[0] for x in self.con.execute(
            "SELECT vi.nome FROM vino_vitigno vv JOIN vitigno vi ON vi.id = vv.vitigno_id"
            " WHERE vv.vino_id = ? ORDER BY vi.nome", (vid,))]
        f.abbinamenti = [x[0] for x in self.con.execute(
            "SELECT abbinamento FROM vino_abbinamento WHERE vino_id = ? LIMIT 6", (vid,))]
        self._aggiungi_nota_vitigno(f)
        return f

    def _fatti_tipologia(self, tid: int) -> Fatti:
        r = self.con.execute(
            "SELECT t.*, d.nome AS den_nome, d.tipo AS den_tipo"
            " FROM tipologia t JOIN denominazione d ON d.id = t.denominazione_id"
            " WHERE t.id = ?", (tid,)
        ).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.TIPOLOGIA,
            tipologia=r["nome"], denominazione=r["den_nome"],
            tipo_denominazione=r["den_tipo"],
            colore=r["colore"], categoria=r["categoria"],
        )
        # Solo i principali finiscono nei fatti raccontabili. Gli ammessi si
        # tengono da parte per poterli ESCLUDERE in verifica, non per dirli.
        for ruolo, dove in (("principale", f.vitigni), ("ammesso", f.vitigni_ammessi)):
            dove.extend(x[0] for x in self.con.execute(
                "SELECT vi.nome FROM tipologia_vitigno tv"
                " JOIN vitigno vi ON vi.id = tv.vitigno_id"
                " WHERE tv.tipologia_id = ? AND tv.ruolo = ? ORDER BY vi.nome",
                (tid, ruolo)))
        self._aggiungi_nota_vitigno(f)
        return f

    def _fatti_denominazione(self, did: int) -> Fatti:
        r = self.con.execute(
            "SELECT nome, tipo FROM denominazione WHERE id = ?", (did,)).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.DENOMINAZIONE,
            denominazione=r["nome"], tipo_denominazione=r["tipo"],
        )
        # Un vitigno vale come "principale della denominazione" solo se lo e' per
        # la maggioranza delle sue tipologie: altrimenti si finirebbe per
        # attribuire al Chianti generico i vitigni di una sua versione rara.
        f.vitigni = [x[0] for x in self.con.execute(
            "SELECT vi.nome FROM tipologia_vitigno tv"
            " JOIN vitigno vi ON vi.id = tv.vitigno_id"
            " JOIN tipologia t ON t.id = tv.tipologia_id"
            " WHERE t.denominazione_id = ? AND tv.ruolo = 'principale'"
            " GROUP BY vi.id"
            " HAVING count(*) >= (SELECT count(*) FROM tipologia WHERE denominazione_id = ?) / 2.0"
            " ORDER BY count(*) DESC LIMIT 5", (did, did))]
        self._aggiungi_nota_vitigno(f)
        return f

    def _fatti_vitigno(self, gid: int) -> Fatti:
        r = self.con.execute("SELECT * FROM vitigno WHERE id = ?", (gid,)).fetchone()
        if not r:
            return Fatti()
        return Fatti(
            livello=Livello.VITIGNO,
            vitigni=[r["nome"]],
            note_vitigno=r["descrizione"],
            temperatura_c=r["temperatura_c"],
            abbinamenti=[a.strip() for a in (r["abbinamenti"] or "").split(";") if a.strip()],
        )

    def _aggiungi_nota_vitigno(self, f: Fatti) -> None:
        """Aggancia la scheda scritta a mano del vitigno principale, se c'è.

        È ciò che permette di dire qualcosa di sensato anche su un vino di cui il
        database conosce solo il nome.
        """
        if not f.vitigni or f.note_vitigno:
            return
        r = self.con.execute(
            "SELECT descrizione, temperatura_c, abbinamenti FROM vitigno"
            " WHERE nome_norm = ? AND descrizione IS NOT NULL",
            (normalizza(f.vitigni[0]),),
        ).fetchone()
        if not r:
            return
        f.note_vitigno = r["descrizione"]
        f.temperatura_c = f.temperatura_c or r["temperatura_c"]
        if not f.abbinamenti:
            f.abbinamenti = [
                a.strip() for a in (r["abbinamenti"] or "").split(";") if a.strip()]


class DatabaseAssente(FileNotFoundError):
    """Il database non c'è: va costruito con data/build_db.py."""
