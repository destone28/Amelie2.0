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

## La regola del produttore

Il primo gradino della cascata e' l'unico che nomini qualcuno, ed e' per questo
il piu' pericoloso. Su una bottiglia c'e' scritto «Primitivo di Manduria» e
basta: quel vino lo fanno centinaia di aziende, e sceglierne una vuol dire
inventare un nome davanti a un ospite seduto. Il dispositivo non lo fa. Cio'
che puo' dire e' *che cosa* e' - e lo dice bene, perche' la descrizione della
tipologia parla del vitigno, del disciplinare e della zona, ed e' vera per
tutte quelle bottiglie.

Percio': **un vino si attribuisce a un produttore solo se il produttore si e'
letto.** Non basta che il suo punteggio sia alto. Le sue parole devono essere
sull'etichetta, e devono essere parole SUE - non quelle della denominazione,
che stanno sulla bottiglia di chiunque. Senza quella prova la cascata scende
di un gradino e il nome non si pronuncia.

Il caso che l'ha imposta, misurato su 1200 etichette costruite dalle tipologie
del database e lunghe abbastanza da non essere protette dal tetto sulle parole:

    prima    1179 generiche, 21 attribuite a un produttore, 1 dichiarata CERTA
    dopo     1200 generiche,  0 attribuite,                  0 certe

La certa era «Brunello di Montalcino» dato all'azienda «Vigna Italia» con 100,
perche' la parola «vigna» - che sull'etichetta e' del disciplinare - le faceva
da firma. E su 500 etichette complete, dove il produttore c'e' davvero, il
prezzo e' piccolo: 498 riconosciute sul produttore giusto, e nessuna sul
produttore sbagliato - dove prima ce n'era una, per giunta dichiarata certa.
"""

from __future__ import annotations

import functools
import logging
import math
import re
import sqlite3
import threading
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
# Di quanto il primo classificato deve staccare un vino di un ALTRO produttore
# per potersi dire certo. Sotto questo margine non si sceglie: si chiede.
MARGINE_PRODUTTORE = 3.0
# Fra quanti dei primi cercare quel rivale.
RIVALI = 6
# Sotto questa somiglianza una parola del record NON si considera letta.
# `fuzz.ratio` fra due parole che non c'entrano nulla vale trenta o quaranta -
# "terre" contro "comune" fa 36 - e contarlo come credito parziale regalava a
# ogni produttore di tre parole una quarantina di punti che sull'etichetta non
# c'erano. Un refuso vale ottanta e passa, quindi la soglia non lo taglia.
RISCONTRO_PAROLA = 70.0

# Quanti candidati chiedere a FTS5 prima di riordinarli col fuzzy.
CANDIDATI = 200
# Su quanti dei migliori rifare il calcolo della sicurezza: su TUTTI. Vedi il
# commento in _candidati — una verifica parziale e' peggio di nessuna, perche'
# chi resta fuori conserva il punteggio gonfiato e scavalca chi e' stato
# esaminato. Le norme si leggono in una query sola, quindi non costa nulla.
VERIFICATI = CANDIDATI

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
    # Il nome del PRODUTTORE si e' ritrovato fra le parole lette? Solo se e'
    # vero il dispositivo puo' dire «questo e' il vino tale di tal altro»:
    # vedi `_prova_del_produttore`.
    produttore_letto: bool = True

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
    # Colore della bacca del vitigno: "nera", "bianca", "grigia". Non e' lo
    # stesso di `colore`, che e' il colore del VINO.
    colore_bacca: str | None = None
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

    # Le tre descrizioni ufficiali del disciplinare - colore, odore, sapore -
    # per la tipologia a cui la bottiglia appartiene. Sono la sola parte dei
    # fatti che non abbiamo scritto noi: le ha scritte il consorzio, e vanno
    # riportate con le loro parole (in inglese, tradotte: vedi
    # `amelie.organolettico`). `disciplinare_di` dice DI CHE COSA parlano, ed
    # e' necessario: il disciplinare descrive la TIPOLOGIA, non la bottiglia di
    # quel produttore, e chi racconta deve poterlo dire.
    #
    # Restano vuote quando la denominazione ha piu' descrizioni e nulla nel
    # database dice quale sia la nostra. Vuote e' la risposta giusta: mettere
    # la descrizione di un passito su un vino secco e' un errore che un
    # sommelier sente alla prima frase.
    disciplinare: dict[str, str] = field(default_factory=dict)
    disciplinare_di: str | None = None

    note_vitigno: str | None = None
    # I descrittori sensoriali tipici del vitigno. Vanno nei fatti perche'
    # altrimenti il modello se li inventa: senza, sul Chianti scriveva "sentore
    # di ciliegio e pepe nero" - plausibile, ma non verificato da noi. Dandogli
    # quelli veri, cio' che scrive e' fondato E la verifica torna a mordere.
    note_sensoriali: list[str] = field(default_factory=list)
    temperatura_c: str | None = None

    # Per la schermata di conferma: `candidati` sono le righe LEGGIBILI che
    # l'ospite vede, `riferimenti` i record a cui corrispondono, nello stesso
    # ordine. Servono entrambi: il testo dell'indice di ricerca e' normalizzato
    # (minuscolo, senza punteggiatura) e a un tavolo non si mostra
    # "barolo cannubi marchesi di barolo"; e ricercare quel testo per risalire
    # al record puo' riportare a un record DIVERSO da quello toccato.
    candidati: list[str] = field(default_factory=list)
    riferimenti: list[tuple[str, int]] = field(default_factory=list)

    # Le schede scritte a mano dei vitigni esistono in piu' lingue. I fatti se
    # le portano dietro TUTTE, invece di risolvere la lingua qui: cosi' l'ospite
    # puo' cambiarla a schermo e riascoltare lo stesso vino senza che il
    # dispositivo debba rileggere l'etichetta. I campi non tradotti - nomi,
    # annata, colore, misure - restano dove sono: non hanno una lingua.
    per_lingua: dict[str, dict] = field(default_factory=dict)

    # Da quale record vengono questi fatti: ("vino", 5993). Serve al ripiego
    # sul vino generico - un Primitivo di Manduria di un produttore qualunque
    # deve poter ricadere sul Primitivo di Manduria e basta - e quel ripiego va
    # fatto per IDENTIFICATIVO, non ricercando il nome: cercare "Primitivo di
    # Manduria" fra i nomi puo' riportare a un vino di un altro produttore.
    origine: tuple[str, int] | None = None
    # I gradini su cui ripiegare, dal piu' specifico al piu' generico. Li
    # calcola il matcher, che e' l'unico a conoscere come sono legate le
    # tabelle; il narratore si limita a percorrerli.
    ripiego: list[tuple[str, int]] = field(default_factory=list)

    def nota_in(self, lingua: str) -> str | None:
        """La scheda del vitigno nella lingua chiesta, o quella che c'e'."""
        return self.per_lingua.get(lingua, {}).get("note_vitigno") or self.note_vitigno

    def abbinamenti_in(self, lingua: str) -> list[str]:
        return self.per_lingua.get(lingua, {}).get("abbinamenti") or self.abbinamenti

    def sensoriali_in(self, lingua: str) -> list[str]:
        return (self.per_lingua.get(lingua, {}).get("note_sensoriali")
                or self.note_sensoriali)

    @property
    def certo(self) -> bool:
        return self.sicurezza >= SOGLIA_CERTA

    @property
    def dubbio(self) -> bool:
        return SOGLIA_DUBBIA <= self.sicurezza < SOGLIA_CERTA

    @property
    def vuoto(self) -> bool:
        return self.livello is Livello.NULLA

    def blocco_fatti(self, lessico=None, lingua: str = "it") -> str:
        """I fatti in forma testuale, come vanno dati al modello.

        I valori dei vocabolari controllati vanno TRADOTTI prima di arrivare al
        modello. I dataset sono in inglese, e passandoli grezzi il modello
        scriveva «un abbinamento con il beef e il blu»: prende le parole che
        legge, e se legge "Beef" scrive "beef". Non e' un problema di prompt,
        e' un problema di ingresso.

        Solo campi valorizzati, una riga ciascuno. I vitigni ammessi NON
        compaiono: il modello non deve nemmeno vederli, perché se li vede finisce
        per nominarli.
        """
        if lessico is None:
            from .lessico import carica
            lessico = carica()

        def t(vocabolario: str, valore: str | None, forma: str = "etichetta") -> str | None:
            return lessico.traduci(vocabolario, valore, lingua=lingua, forma=forma) if valore else None

        abbinamenti = (
            ", ".join(lessico.traduci_molti("abbinamento", self.abbinamenti, lingua=lingua))
            if self.abbinamenti else None
        )
        # X-Wines usa spesso la denominazione anche come "regione": ripeterla
        # non aggiunge nulla e induce il modello a trattarla come un luogo
        # diverso, inventando geografia.
        regione = self.regione
        if regione and self.denominazione and (
            regione in self.denominazione or self.denominazione in regione
            or (self.tipologia and regione in self.tipologia)):
            regione = None

        righe = []
        for etichetta, valore in (
            ("Nome", self.nome),
            ("Produttore", self.cantina),
            ("Regione", regione),
            ("Annata", self.annata),
            ("Denominazione", self.denominazione),
            ("Tipologia", self.tipologia),
            ("Colore", t("tipo", self.colore) or t("colore", self.colore)),
            ("Colore della bacca", self.colore_bacca),
            ("Categoria", t("categoria_ue", self.categoria)),
            ("Corpo", t("corpo", self.corpo, "narrativa")),
            ("Acidità", t("acidita", self.acidita, "narrativa")),
            ("Come nasce", t("elaborazione", self.elaborazione, "narrativa")),
            ("Gradazione", f"{self.abv}%" if self.abv else None),
            ("Vitigni", ", ".join(self.vitigni) if self.vitigni else None),
            ("Abbinamenti", abbinamenti),
            ("Note sensoriali tipiche",
             ", ".join(self.note_sensoriali) if self.note_sensoriali else None),
            ("Temperatura di servizio", f"{self.temperatura_c} gradi" if self.temperatura_c else None),
            ("Nota sul vitigno", self.note_vitigno),
        ):
            if valore not in (None, "", []):
                righe.append(f"{etichetta}: {valore}")
        righe.extend(self._righe_disciplinare(lingua))
        return "\n".join(righe)

    # Le citazioni stanno in fondo e separate, e la separazione e' il punto: il
    # resto dei fatti sono dati che il modello puo' riformulare, queste sono
    # parole di un atto ufficiale. Senza la divisione il modello tratta «rosso
    # granato» come un suggerimento e scrive «di un bel rosso brillante» - vero
    # forse, ma non e' cio' che dice il disciplinare.
    _INTESTAZIONE_DISCIPLINARE = {
        "it": "DAL DISCIPLINARE di {di} (parole del consorzio, da riportare):",
        "en": "FROM THE SPECIFICATION for {di} "
              "(the consortium's own words, translated from the Italian):",
    }
    _VOCI_DISCIPLINARE = {
        "it": {"colore": "Colore", "odore": "Odore", "sapore": "Sapore"},
        "en": {"colore": "Colour", "odore": "Nose", "sapore": "Palate"},
    }

    def _righe_disciplinare(self, lingua: str) -> list[str]:
        if not self.disciplinare:
            return []
        from .organolettico import carica as carica_organolettico

        voci = self._VOCI_DISCIPLINARE.get(lingua, self._VOCI_DISCIPLINARE["it"])
        vocabolario = carica_organolettico()
        dentro = []
        for ambito in ("colore", "odore", "sapore"):
            testo = self.disciplinare.get(ambito)
            if not testo:
                continue
            reso = vocabolario.rendi(testo, ambito, lingua=lingua)
            if reso:
                dentro.append(f"{voci[ambito]}: {reso.testo}")
        if not dentro:
            return []
        testa = self._INTESTAZIONE_DISCIPLINARE.get(
            lingua, self._INTESTAZIONE_DISCIPLINARE["it"])
        return ["", testa.format(di=self.disciplinare_di or self.denominazione)] + dentro


def sotto_lucchetto(f):
    """Esegue il metodo tenendo il lucchetto del database.

    Serve a una cosa sola, ed e' successa davvero: `chiudi()` chiudeva la
    connessione SQLite mentre il thread di lavoro ci stava ancora leggendo, e il
    processo moriva di segmentation fault - non un'eccezione che si cattura, un
    crash. Il lucchetto e' RIENTRANTE perche' questi metodi si chiamano fra
    loro: `cerca` chiama `_candidati`, che chiama `_norme_vino`.
    """
    @functools.wraps(f)
    def dentro(self, *a, **kw):
        with self._db:
            return f(self, *a, **kw)
    return dentro


# Il colore dei due registri e' scritto in lingue diverse: figshare in inglese,
# il documento unico in italiano. E' il vincolo che non si puo' sbagliare -
# nessuna descrizione di un bianco vale per un rosso - quindi si traduce qui e
# si applica per primo.
# In archivio convivono le due scritture, perche' convivono le due fonti.
# «Sparkling» e «Dessert» invece NON sono colori: dicono che tipo di vino e',
# non di che colore, e per un vino cosi' il vincolo non si puo' applicare.
COLORE_UE = {"Red": "Rosso", "White": "Bianco", "Rosé": "Rosato",
             "Rosso": "Rosso", "Bianco": "Bianco", "Rosato": "Rosato"}

# Parole che nel nome di una tipologia denotano un PRODOTTO DIVERSO, non una
# sfumatura: un passito non e' la versione dolce del bianco, e' un altro vino.
QUALIFICATORI = frozenset((
    "passito", "liquoroso", "spumante", "frizzante", "riserva", "superiore",
    "novello", "classico", "vendemmia", "tardiva", "stramature",
))

# La categoria UE dice la stessa cosa del nome, ma in forma di codice: serve
# quando il nome tace, «Aleatico di Puglia» che e' un liquoroso e non lo scrive.
QUALIFICATORE_DI_CATEGORIA = {
    "Wine From Raisined Grapes": "passito",
    "Wine From Overripe Grapes": "stramature",
    "Liqueur Wine": "liquoroso",
    "Sparkling Wine": "spumante",
    "Quality Sparkling Wine": "spumante",
    "Quality Aromatic Sparkling Wine": "spumante",
    "Semi-Sparkling Wine": "frizzante",
    "Aerated Semi-Sparkling Wine": "frizzante",
}

# Quando due tipologie di una denominazione si chiamano uguale, chi costruisce
# l'archivio le numera per tenerle distinte. Il numero e' un identificativo,
# non un nome: a schermo e nel racconto non ci va.
_NUMERO_IN_CODA = re.compile(r"\s*\(\d+\)\s*$")

# Il testo dei parametri di legge a volte e' colato dentro il blocco
# descrittivo del PDF. Sono pochi casi, ma basta uno per far dire al
# dispositivo «sapore armonico titolo alcolometrico volumico totale minimo».
_PARAMETRI_DI_LEGGE = re.compile(
    r"titolo\s+alcolometric|estratto\s+non\s+ridutt|zuccheri\s+ridutt|"
    r"\d+[,.]\d+\s*%\s*vol", re.I)

# Una citazione organolettica e' breve: mediana 35 caratteri, novantesimo
# percentile 79. Oltre i 120 non e' piu' una citazione, e' un paragrafo.
_CITAZIONE_MASSIMA = 120


def _citazioni_utili(r) -> dict[str, str]:
    fuori = {}
    for ambito in ("colore", "odore", "sapore"):
        v = (r[f"desc_{ambito}"] or "").strip().rstrip(".")
        if v and len(v) <= _CITAZIONE_MASSIMA and not _PARAMETRI_DI_LEGGE.search(v):
            fuori[ambito] = v
    return fuori


def _confronto(r) -> tuple:
    """Due righe dicono la stessa cosa? Si guardano le citazioni, non i nomi."""
    return tuple(sorted(_citazioni_utili(r).items()))


def _nome_leggibile(r) -> str:
    return _NUMERO_IN_CODA.sub("", (r["nome"] or "").strip())


class Matcher:
    """Interroga il database. Sola lettura, e non tiene stato fra una ricerca e l'altra."""

    # Gli unici ambiti che il dispositivo sa raccontare. L'indice di ricerca
    # vive nel database, e il database cresce: chi lo ricostruisce puo'
    # aggiungerci righe di un ambito che questo codice non conosce. Vedi
    # `_componi` e il filtro in `_candidati`.
    AMBITI = ("vino", "tipologia", "denominazione", "vitigno")

    def __init__(self, percorso: str | Path | None = None) -> None:
        self.percorso = Path(percorso) if percorso else PERCORSO_DB
        if not self.percorso.exists():
            raise DatabaseAssente(
                f"manca {self.percorso}. Costruiscilo con: python3 data/build_db.py"
            )
        # Sola lettura: il dispositivo non deve poter corrompere il proprio sapere.
        #
        # check_same_thread=False e' NECESSARIO, non una comodita': la connessione
        # nasce nel thread principale e viene usata nel thread di lavoro che
        # l'orchestratore crea per ogni scansione. Senza, ogni ricerca solleva
        # ProgrammingError e il dispositivo non riconosce nessun vino. Il lock
        # serializza gli accessi, e non costa nulla perche' la pipeline e' gia'
        # sequenziale per costruzione: un solo lavoro alla volta.
        self.con = sqlite3.connect(
            f"file:{self.percorso}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._db = threading.RLock()
        self._vitigni: tuple[str, ...] | None = None

    @sotto_lucchetto
    def chiudi(self) -> None:
        # Sotto lucchetto: chi sta leggendo in un altro thread finisce prima.
        self.con.close()

    # ------------------------------------------------------------- ricerca

    @sotto_lucchetto
    def cerca(self, righe: Sequence[str], *, anno_massimo: int | None = None) -> Fatti:
        """Il punto d'ingresso: righe dell'OCR -> fatti."""
        testo = " ".join(righe)
        annata = estrai_annata(righe, anno_massimo=anno_massimo)
        token = parole_utili(testo)
        if not token:
            return Fatti()

        testo_norm = normalizza(testo)
        candidati = self._candidati(token, testo_norm)
        if not candidati:
            return Fatti()

        # Il tetto si applica DOPO la scelta: serve a dire quanto ci si puo'
        # fidare, non a cambiare quale record e' il piu' somigliante.
        tetto = (TETTO_PER_PAROLE[len(token)] if len(token) < len(TETTO_PER_PAROLE)
                 else math.inf)      # da quattro parole in su nessun tetto
        for c in candidati:
            c.somiglianza = min(c.somiglianza, tetto)

        migliore = candidati[0]
        fatti = self._componi(migliore)
        fatti.sicurezza = migliore.somiglianza
        # La garanzia: un produttore non si nomina se non lo si e' letto.
        if not migliore.produttore_letto:
            fatti = self._senza_produttore(fatti, testo_norm, tetto)
        if self._c_e_un_altro_produttore(candidati):
            fatti.sicurezza = min(fatti.sicurezza, SOGLIA_CERTA - 0.5)
        fatti.annata = annata
        # Per la schermata di conferma servono alternative DIVERSE fra loro:
        # tre righe che dicono quasi la stessa cosa non aiutano a scegliere.
        visti = {migliore.testo}
        for c in candidati[1:]:
            if len(fatti.candidati) >= 3:
                break
            if c.testo in visti:
                continue
            visti.add(c.testo)
            fatti.candidati.append(self.etichetta(c.ambito, c.ambito_id)
                                   or c.testo)
            fatti.riferimenti.append((c.ambito, c.ambito_id))
        fatti.ripiego = self.catena_di_ripiego(fatti)
        return fatti

    def _c_e_un_altro_produttore(self, candidati: list[Candidato]) -> bool:
        """C'e' un ALTRO produttore quasi altrettanto plausibile?

        La sicurezza non e' una proprieta' della stringa vincente: e' una
        proprieta' dell'affermazione che si sta per fare a un tavolo. Su
        "Monte Antico ... Sangiovese, Merlot" il primo classificato era il
        Sangiovese-Merlot di **Monte Giove** con 90, e a 2.4 punti di distanza
        c'era il vino di **Monte Antico**, cioe' la risposta giusta. Con due
        produttori cosi' vicini il dispositivo non sta riconoscendo: sta
        tirando a indovinare quale nome stampare. Allora non si dichiara certo
        e mostra la schermata di conferma, dove una persona sceglie in un
        istante quello che l'OCR non sa distinguere.

        Il secondo classificato quasi sempre e' invece lo stesso vino visto da
        un altro record - un'altra annata, la sua tipologia - e quello non
        toglie nulla: per questo si guarda la CANTINA, non il punteggio.
        """
        primo = candidati[0]
        if primo.ambito != "vino":
            return False
        norme = self._norme_vino([c.ambito_id for c in candidati[:RIVALI]
                                  if c.ambito == "vino"])
        cantina_primo = norme.get(primo.ambito_id, ("", "", ""))[1]
        if not cantina_primo:
            return False
        for c in candidati[1:RIVALI]:
            if primo.somiglianza - c.somiglianza >= MARGINE_PRODUTTORE:
                break
            if c.ambito != "vino":
                continue
            altra = norme.get(c.ambito_id, ("", "", ""))[1]
            if altra and altra != cantina_primo:
                log.info("due produttori a pari evidenza (%r / %r): chiedo",
                         cantina_primo, altra)
                return True
        return False

    @sotto_lucchetto
    def _senza_produttore(self, f: Fatti, testo_norm: str, tetto: float) -> Fatti:
        """Scende al vino generico quando il produttore non si e' letto.

        E' la traduzione in codice di una regola sola: **se sulla bottiglia
        c'e' scritto "Primitivo di Manduria" e basta, il dispositivo non puo'
        dire di chi e'.** Puo' dire che cos'e', e quello lo dice benissimo -
        la descrizione della tipologia parla del vitigno, del disciplinare,
        della zona, e vale per ogni Primitivo di Manduria in commercio.
        Attribuirlo al viticoltore A invece che al B sarebbe inventare, e
        davanti a un ospite seduto e' esattamente cio' che non si fa.

        Il punteggio si rifa' sul record generico, che e' un'affermazione
        diversa e piu' facile da sostenere: "questo e' un Primitivo di
        Manduria" chiede molto meno di "questo e' il Primitivo di Manduria di
        tal produttore".
        """
        for ambito, ident in self.catena_di_ripiego(f)[1:]:
            generico = self._componi(Candidato(ambito=ambito, ambito_id=ident,
                                               testo="", somiglianza=0.0, peso=0))
            if generico.livello is Livello.NULLA:
                continue
            r = self.con.execute(
                "SELECT testo, peso FROM ricerca WHERE ambito = ? AND ambito_id = ?",
                (ambito, ident)).fetchone()
            if r is None:
                continue
            generico.sicurezza = min(tetto, self._sicurezza_verificata(
                Candidato(ambito=ambito, ambito_id=ident, testo=r["testo"],
                          somiglianza=0.0, peso=r["peso"]), testo_norm))
            log.info("produttore non letto: da %r si scende a %s", f.cantina, ambito)
            return generico
        # Sotto non c'e' nulla su cui ripiegare. Si tiene il record, ma il
        # produttore esce dai fatti: il narratore non ha altre fonti, e cio'
        # che non gli si passa non lo puo' dire.
        log.info("produttore non letto e nessun ripiego: %r resta senza nome", f.nome)
        f.cantina = None
        f.sicurezza = min(f.sicurezza, SOGLIA_CERTA - 0.5)
        return f

    @sotto_lucchetto
    def fatti_di(self, ambito: str, ambito_id: int) -> Fatti:
        """I fatti di un record preciso, senza ripassare dalla ricerca.

        È quello che serve quando l'ospite tocca un candidato: ha scelto UN
        record, e va composto quello, non il piu' somigliante al suo nome.
        """
        f = self._componi(Candidato(ambito=ambito, ambito_id=ambito_id,
                                    testo="", somiglianza=0.0, peso=0))
        # L'ha scelto una persona guardando la bottiglia: e' la conferma piu'
        # forte che il dispositivo possa ricevere.
        f.sicurezza = 100.0
        f.ripiego = self.catena_di_ripiego(f)
        return f

    @sotto_lucchetto
    def etichetta(self, ambito: str, ambito_id: int) -> str:
        """Come si scrive un record su uno schermo, per farlo scegliere."""
        f = self._componi(Candidato(ambito=ambito, ambito_id=ambito_id,
                                    testo="", somiglianza=0.0, peso=0))
        if f.livello is Livello.VINO and f.nome:
            return f"{f.nome} — {f.cantina}" if f.cantina else f.nome
        if f.livello is Livello.TIPOLOGIA and f.tipologia:
            return f.tipologia
        if f.livello is Livello.DENOMINAZIONE and f.denominazione:
            tipo = f.tipo_denominazione or ""
            return f"{f.denominazione} {tipo}".strip()
        if f.livello is Livello.VITIGNO and f.vitigni:
            return f.vitigni[0]
        return ""

    @sotto_lucchetto
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

        # Le righe di un ambito che non si sa raccontare non entrano nemmeno in
        # gara: se entrassero potrebbero vincere - e i pesi li decide chi
        # costruisce l'indice, non questo codice - e si finirebbe per mostrare
        # una schermata vuota al posto di un vino.
        grezzi = [
            Candidato(
                ambito=r["ambito"], ambito_id=r["ambito_id"], testo=r["testo"],
                # token_set_ratio ignora l'ordine e le parole in piu': l'OCR
                # restituisce le righe in ordine di posizione sull'etichetta,
                # non di importanza, e ci mette in mezzo solfiti e millilitri.
                somiglianza=fuzz.token_set_ratio(testo_norm, r["testo"]),
                peso=r["peso"],
            )
            for r in righe if r["ambito"] in self.AMBITI
        ]
        scartate = len(righe) - len(grezzi)
        if scartate:
            log.info("%d righe dell'indice ignorate: ambito sconosciuto", scartate)
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
        # Su TUTTI, non sui primi: la verifica ABBASSA i punteggi, e chi non
        # viene verificato conserva quello gonfiato. Fermarsi ai primi 25
        # significava che il 26esimo, mai verificato, poteva scavalcare tutti
        # dopo il riordino e presentarsi come "certo" senza aver mai superato
        # l'esame. Il costo e' una query sola e 200 confronti: nulla, accanto
        # ai secondi dell'OCR.
        norme = self._norme_vino([c.ambito_id for c in grezzi if c.ambito == "vino"])
        for c in grezzi:
            if not c.esatto:
                c.somiglianza = self._sicurezza_verificata(c, testo_norm, norme)
        grezzi.sort(key=lambda c: c.punteggio, reverse=True)
        return grezzi

    @staticmethod
    def _copertura(record: str, parole_ocr: list[str]) -> float:
        """Quanto del record si ritrova nell'etichetta, parola per parola.

        Serve perche' token_set_ratio e' tutto-o-niente sui token: da' 100 se
        OGNI parola del record compare identica, e crolla appena una ha un
        refuso. Su "TINUTA ROCCA BAROLO BUSSIA" letto da una bottiglia di
        Tenuta Rocca, il record giusto "tenuta rocca barolo bussia" prendeva
        58.8 per quella e sola nel nome della cantina, mentre il record povero
        "rocca rocca" - un altro produttore - prendeva 100 perche' la sua unica
        parola c'era esatta. Il piu' informativo perdeva contro il piu' vago.

        Qui ogni parola del record cerca il suo miglior riscontro fra quelle
        lette, e il punteggio e' la media: un refuso costa una parola, non
        tutto il record.
        """
        from rapidfuzz import fuzz

        parole = record.split()
        if not parole or not parole_ocr:
            return fuzz.token_set_ratio(" ".join(parole_ocr), record)
        # Ogni parola letta puo' confermarne UNA sola del record. Senza questo,
        # "Ca'Stella" si accontentava della "Stella Polare" stampata sulla
        # retroetichetta di un Burlotto e si dichiarava certa.
        libere = list(parole_ocr)
        totale = 0.0
        for p in sorted(parole, key=len, reverse=True):
            if not libere:
                break
            i = max(range(len(libere)), key=lambda k: fuzz.ratio(p, libere[k]))
            punti = fuzz.ratio(p, libere[i])
            # Sotto la soglia non e' un riscontro debole: e' un NON riscontro, e
            # vale zero. La parola letta resta libera, perche' non ha confermato
            # niente e potra' confermare qualcos'altro.
            if punti < RISCONTRO_PAROLA:
                continue
            totale += punti
            libere.pop(i)
        return totale / len(parole)

    @staticmethod
    def _prova_del_produttore(cantina: str, denominazione: str) -> list[str]:
        """Le parole del produttore che possono davvero provarlo.

        Non tutte lo fanno. «Terre del Barolo» e' un produttore vero, ma una
        delle sue parole e' la denominazione, e quella sta sull'etichetta di
        chiunque faccia Barolo. Contarla come prova vuol dire farsi confermare
        il produttore dalle parole del vino, ed e' successo: «Barolo del Comune
        di Serralunga d'Alba» veniva dichiarato CERTO come Barolo di Terre del
        Barolo con 88, da un'etichetta che il produttore non lo nominava.

        Restano le parole che il produttore ha di suo: via quelle della
        denominazione e via quelle che stanno su ogni bottiglia (`tenuta`,
        `cantina`, `azienda`, `podere`... - la lista e' `PAROLE_VUOTE`).

        La denominazione, e NON il nome del vino. Sembra equivalente e non lo
        e': in archivio moltissimi nomi contengono gia' il produttore -
        «Giovanni Allegrini Recioto della Valpolicella» - e togliere le parole
        del nome cancellava proprio quelle che identificano la cantina.
        Misurato: escludendo il nome restavano senza prova 164 cantine, fra
        cui Antinori, Allegrini e Bertani; escludendo la denominazione ne
        restano 31, e sono quelle che davvero si chiamano come il proprio vino.

        Un produttore senza nemmeno una parola propria - le cooperative
        battezzate come la denominazione - non e' riconoscibile dalle parole.
        Allora il dispositivo non lo afferma: racconta il vino generico.
        """
        della_zona = set(denominazione.split())
        return [p for p in parole_utili(cantina) if p not in della_zona]

    @sotto_lucchetto
    def _norme_vino(self, ids: list[int]) -> dict[int, tuple[str, str, str]]:
        """nome, cantina e denominazione normalizzati, in una query sola.

        La denominazione serve a sapere quali parole del produttore sono sue e
        quali sono di tutti: vedi `_prova_del_produttore`.
        """
        if not ids:
            return {}
        with self._db:
            righe = self.con.execute(
                "SELECT v.id, v.nome_norm, COALESCE(v.cantina_norm,''),"
                " COALESCE(d.nome_norm,'')"
                " FROM vino v LEFT JOIN denominazione d ON d.id = v.denominazione_id"
                f" WHERE v.id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r[0]: (r[1] or "", r[2], r[3]) for r in righe}

    @sotto_lucchetto
    def _sicurezza_verificata(self, c: Candidato, testo_norm: str,
                              norme: dict[int, tuple[str, str]] | None = None) -> float:
        """Ricalcola la sicurezza in base a quanto pesa l'affermazione.

        Per un vino commerciale servono DUE conferme indipendenti, cantina e
        nome, e vale la piu' debole delle due: un nome giusto con un produttore
        sbagliato e' un vino sbagliato.

        **Indipendenti davvero.** La conferma del produttore non puo' venire da
        parole che sono del vino: «BAROLO» stampato sull'etichetta provava
        insieme il vino «Barolo» e il produttore «Terre del Barolo», due
        conferme che ne erano una sola. Il produttore si misura solo sulle
        parole che ha di suo - `_prova_del_produttore` - e se nessuna di quelle
        e' sull'etichetta, non lo si e' letto e non lo si nomina.
        """
        from rapidfuzz import fuzz

        if c.ambito == "vino":
            if norme is None:
                norme = self._norme_vino([c.ambito_id])
            if c.ambito_id not in norme:
                return 0.0
            nome, cantina, denominazione = norme[c.ambito_id]
            parole_ocr = testo_norm.split()
            s_nome = self._copertura(nome, parole_ocr) if nome else 0
            if not cantina:
                return s_nome * 0.8      # senza produttore non si e' mai certi
            # Prima la domanda di identita': il produttore lo si e' LETTO?
            # Si guardano solo le parole che sono sue, perche' sono le uniche
            # che possano provarlo. Se nessuna e' sull'etichetta, questa
            # bottiglia puo' essere di chiunque e va raccontata come generica.
            # Il confronto e' con le parole UTILI dell'etichetta, non con
            # tutte: quelle che stanno su ogni bottiglia non identificano un
            # produttore piu' di quanto identifichino un vino. «Volpi» si
            # faceva confermare da «VOL» della gradazione alcolica - 75 su 100
            # per pura aritmetica delle lettere - e «Cantine Volpi» finiva
            # sull'etichetta di un Piemonte Cortese che non la nominava.
            prova = self._prova_del_produttore(cantina, denominazione)
            if not prova or self._copertura(
                    " ".join(prova), parole_utili(testo_norm)) < RISCONTRO_PAROLA:
                c.produttore_letto = False
                return s_nome * 0.8
            # Poi la domanda di grado, e quella si misura sul nome INTERO. Le
            # parole deboli devono continuare a diluire: filtrandole si finiva
            # per premiare i nomi poveri, e «Ca'Stella» tornava a dichiararsi
            # certo con 92 sulla «Stella Polare» di una retroetichetta altrui.
            s_cantina = self._copertura(cantina, parole_ocr)
            # La media pesata premia chi ha entrambe le conferme; il tetto sul
            # minimo impedisce che una sola, fortissima, basti da sola.
            punteggio = min(0.6 * s_cantina + 0.4 * s_nome,
                            s_cantina * 1.15, s_nome * 1.6)
            # E poi si scala su quanto il record SPIEGA dell'etichetta. Con la
            # copertura per parole, un record di una parola sola prende 100
            # ancora piu' facilmente: e' proprio quello che non deve bastare a
            # dire "questo e' il vino tale del produttore talaltro".
            parole = len(set(nome.split()) | set(cantina.split()))
            return punteggio * min(1.0, 0.55 + 0.15 * parole)

        # Per gli altri livelli l'affermazione e' piu' debole, ma resta il
        # problema delle voci corte: una denominazione di una parola sola non
        # puo' valere quanto una di tre. Si scala sulla specificita'.
        parole = len(c.testo.split())
        specificita = min(1.0, 0.55 + 0.15 * parole)
        return fuzz.token_set_ratio(testo_norm, c.testo) * specificita

    # ------------------------------------------------------------ composizione

    @sotto_lucchetto
    def _componi(self, c: Candidato) -> Fatti:
        """Da un candidato ai fatti. Un ambito sconosciuto non e' un errore.

        Era un `KeyError`, e non su una riga qualsiasi: `_componi` gira nel
        thread di lavoro, quindi l'eccezione diventava una schermata di guasto
        davanti all'ospite. Basta che qualcuno ricostruisca l'indice di ricerca
        con un ambito in piu' - una tabella nuova, un prodotto da scaffale - e
        ogni bottiglia che ci finisca sopra manda il dispositivo in errore.

        Il database e il codice hanno cicli di vita diversi: l'uno si rigenera,
        l'altro si aggiorna col firmware. Chi legge deve reggere un database
        piu' ricco di quanto sappia usare, e limitarsi a ignorare cio' che non
        riconosce.
        """
        costruttore = {
            "vino": self._fatti_vino,
            "tipologia": self._fatti_tipologia,
            "denominazione": self._fatti_denominazione,
            "vitigno": self._fatti_vitigno,
        }.get(c.ambito)
        if costruttore is None:
            log.warning("ambito sconosciuto nell'indice: %r (id %s), lo ignoro",
                        c.ambito, c.ambito_id)
            return Fatti()
        f = costruttore(c.ambito_id)
        if f.livello is not Livello.NULLA:
            f.origine = (c.ambito, c.ambito_id)
        return f

    # ------------------------------------------------------------ ripiego

    @sotto_lucchetto
    def catena_di_ripiego(self, f: Fatti) -> list[tuple[str, int]]:
        """Dal record trovato, giu' fino al piu' generico che sappia dire qualcosa.

        Un vino commerciale e' uno di diciannovemila: pre-generarne il testo
        sarebbe giorni di calcolo, e per quasi tutti non c'e' niente da dire che
        non sia gia' vero del suo vino generico. Quindi si scende: il Primitivo
        di Manduria della Cooperativa Produttori Vini Manduria ricade sul
        Primitivo di Manduria, e se manca anche quello sulla denominazione, e se
        manca ancora sul vitigno principale.

        Restituisce i gradini in ordine, dal piu' specifico al piu' generico.
        Chi chiama prende il primo che ha un testo pronto.
        """
        if f.origine is None:
            return []
        ambito, ident = f.origine
        catena: list[tuple[str, int]] = [f.origine]

        if ambito == "vino":
            with self._db:
                r = self.con.execute(
                    "SELECT denominazione_id, nome_norm FROM vino WHERE id = ?",
                    (ident,)).fetchone()
            if r and r["denominazione_id"]:
                tid = self._tipologia_del_vino(r["denominazione_id"], r["nome_norm"])
                if tid:
                    catena.append(("tipologia", tid))
                catena.append(("denominazione", r["denominazione_id"]))
        elif ambito == "tipologia":
            with self._db:
                r = self.con.execute(
                    "SELECT denominazione_id FROM tipologia WHERE id = ?",
                    (ident,)).fetchone()
            if r and r["denominazione_id"]:
                catena.append(("denominazione", r["denominazione_id"]))

        if ambito != "vitigno" and f.vitigni:
            with self._db:
                r = self.con.execute(
                    "SELECT id FROM vitigno WHERE nome_norm = ?"
                    " AND descrizione IS NOT NULL", (normalizza(f.vitigni[0]),)
                ).fetchone()
            if r:
                catena.append(("vitigno", r["id"]))
        return catena

    @sotto_lucchetto
    def _tipologia_del_vino(self, den_id: int, nome_norm: str) -> int | None:
        """Quale tipologia della denominazione somiglia di piu' a questo vino.

        Una denominazione ne ha spesso molte - Primitivo di Manduria e Primitivo
        di Manduria Riserva - e prendere la prima a caso significherebbe
        raccontare una Riserva per un vino base.
        """
        from rapidfuzz import fuzz

        with self._db:
            righe = self.con.execute(
                "SELECT id, nome_norm FROM tipologia WHERE denominazione_id = ?",
                (den_id,)).fetchall()
        if not righe:
            return None
        if len(righe) == 1:
            return righe[0]["id"]
        migliore = max(righe, key=lambda r: fuzz.token_set_ratio(
            nome_norm, r["nome_norm"]))
        return migliore["id"]

    def _aggiungi_disciplinare(self, f: Fatti, den_id, nome, colore, categoria=None):
        trovato = self._disciplinare(den_id, nome or "", colore, categoria)
        if trovato:
            f.disciplinare, f.disciplinare_di = trovato

    @sotto_lucchetto
    def _vitigni_noti(self) -> tuple[str, ...]:
        """I nomi dei vitigni, dal piu' lungo al piu' corto.

        Servono a leggere i nomi delle tipologie: dentro una denominazione
        larga la differenza fra due descrizioni e' quasi sempre il vitigno -
        «Trentino Superiore Chardonnay» contro «Trentino Superiore Riesling
        renano» - e senza l'elenco quelle due righe si somigliano e basta.
        """
        if self._vitigni is None:
            self._vitigni = tuple(sorted(
                (r[0] for r in self.con.execute(
                    "SELECT nome_norm FROM vitigno WHERE length(nome_norm) >= 5")),
                key=len, reverse=True))
        return self._vitigni

    def _vitigni_nel_nome(self, nome: str) -> frozenset[str]:
        dentro, resto = set(), f" {normalizza(nome)} "
        for v in self._vitigni_noti():
            if f" {v} " in resto:
                dentro.add(v)
                resto = resto.replace(f" {v} ", " ")
        return frozenset(dentro)

    @staticmethod
    def _qualificatori(nome: str, categoria: str | None = None) -> frozenset[str]:
        q = {p for p in normalizza(nome).split() if p in QUALIFICATORI}
        if categoria in QUALIFICATORE_DI_CATEGORIA:
            q.add(QUALIFICATORE_DI_CATEGORIA[categoria])
        return frozenset(q)

    @sotto_lucchetto
    def _disciplinare(self, den_id: int | None, nome: str, colore: str | None,
                      categoria: str | None = None) -> tuple[dict[str, str], str] | None:
        """Le citazioni del disciplinare per questa tipologia, o None.

        I due registri non hanno una chiave in comune - le tipologie vengono da
        figshare, le citazioni dal documento unico eAmbrosia - e accostarle per
        somiglianza del nome sbaglia: «Trentino Manzoni Bianco» si prende la
        descrizione di «Trentino Bianco» con punteggio pieno, perche' le parole
        ci sono tutte. Misurato: 729 abbinamenti su 3.315 finivano su un vino
        di un altro colore.

        Quindi si restringe, non si somiglia. Prima il colore, che e' il
        vincolo che non si puo' sbagliare; poi il vitigno e i qualificatori,
        che sono scritti sull'etichetta e quindi gia' letti. Se quel che resta
        dice tutto la stessa cosa, la si riporta. Se dice cose diverse e nulla
        distingue quale sia la nostra, si tace: il narratore ha comunque il
        resto dei fatti, e una descrizione presa a caso fra tre non e' un
        dettaglio in piu' - e' una cosa falsa detta con sicurezza.
        """
        if den_id is None or colore not in COLORE_UE:
            return None
        righe = [r for r in self.con.execute(
            """SELECT nome, nome_incerto, menzione, desc_colore, desc_odore, desc_sapore
               FROM tipologia_ue WHERE denominazione_id = ? AND colore = ?""",
            (den_id, COLORE_UE[colore])) if _citazioni_utili(r)]
        if not righe:
            return None

        miei_q = self._qualificatori(nome, categoria)
        miei_v = self._vitigni_nel_nome(nome)

        def suoi(r):
            n = _NUMERO_IN_CODA.sub("", r["nome"] or "")
            return self._qualificatori(f"{n} {r['menzione'] or ''}"), self._vitigni_nel_nome(n)

        for tiene in (lambda r: suoi(r) == (miei_q, miei_v),
                      lambda r: suoi(r)[1] == miei_v,
                      lambda r: suoi(r)[0] == miei_q,
                      lambda r: True):
            restano = [r for r in righe if tiene(r)]
            if restano and len({_confronto(r) for r in restano}) == 1:
                return _citazioni_utili(restano[0]), _nome_leggibile(restano[0])
        return None

    @sotto_lucchetto
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
        self._aggiungi_disciplinare(f, r["denominazione_id"], r["nome"], r["tipo"])
        self._aggiungi_nota_vitigno(f)
        return f

    @sotto_lucchetto
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
        self._aggiungi_disciplinare(f, r["denominazione_id"], r["nome"],
                                    r["colore"], r["categoria"])
        self._aggiungi_nota_vitigno(f)
        return f

    @sotto_lucchetto
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

    @sotto_lucchetto
    def _fatti_vitigno(self, gid: int) -> Fatti:
        r = self.con.execute("SELECT * FROM vitigno WHERE id = ?", (gid,)).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.VITIGNO,
            vitigni=[r["nome"]],
            note_vitigno=r["descrizione"],
            temperatura_c=r["temperatura_c"],
            abbinamenti=[a.strip() for a in (r["abbinamenti"] or "").split(";") if a.strip()],
        )
        # Il colore della bacca DEVE esserci: senza, il modello ha scritto che
        # la Falanghina - vitigno a bacca bianca - e' «un vino rosso» con
        # «tannicita' bassa». Non e' un'imprecisione, e' un errore che un
        # sommelier coglie all'istante.
        f.colore_bacca = r["colore_bacca"]
        spezza = lambda v: [x.strip() for x in (v or "").split(";") if x.strip()]
        if r["note_sensoriali"]:
            f.note_sensoriali = spezza(r["note_sensoriali"])
        # Le altre lingue vanno portate dietro qui come altrove, altrimenti un
        # racconto costruito a partire dal solo vitigno esce in italiano anche
        # quando lo schermo e' in inglese.
        if r["descrizione_en"]:
            f.per_lingua["en"] = {
                "note_vitigno": r["descrizione_en"],
                "abbinamenti": spezza(r["abbinamenti_en"]),
                "note_sensoriali": spezza(r["note_sensoriali_en"]),
            }
        return f

    @sotto_lucchetto
    def _aggiungi_nota_vitigno(self, f: Fatti) -> None:
        """Aggancia la scheda scritta a mano del vitigno principale, se c'è.

        È ciò che permette di dire qualcosa di sensato anche su un vino di cui il
        database conosce solo il nome.
        """
        if not f.vitigni or f.note_vitigno:
            return
        with self._db:
            r = self.con.execute(
                "SELECT descrizione, temperatura_c, abbinamenti, note_sensoriali,"
                " descrizione_en, abbinamenti_en, note_sensoriali_en"
                " FROM vitigno WHERE nome_norm = ? AND descrizione IS NOT NULL",
                (normalizza(f.vitigni[0]),),
            ).fetchone()
        if not r:
            return
        spezza = lambda v: [x.strip() for x in (v or "").split(";") if x.strip()]

        f.note_vitigno = r["descrizione"]
        f.temperatura_c = f.temperatura_c or r["temperatura_c"]
        # La scheda del vitigno SUBENTRA solo dove il vino non ha nulla di suo:
        # gli abbinamenti di una bottiglia precisa valgono piu' di quelli
        # generici dell'uva. E la sostituzione dev'essere la stessa in tutte le
        # lingue, altrimenti in italiano si sentono gli abbinamenti del vino e
        # in inglese quelli dell'uva - due risposte diverse alla stessa domanda.
        prende_sensoriali = bool(r["note_sensoriali"]) and not f.note_sensoriali
        prende_abbinamenti = not f.abbinamenti
        if prende_sensoriali:
            f.note_sensoriali = spezza(r["note_sensoriali"])
        if prende_abbinamenti:
            f.abbinamenti = spezza(r["abbinamenti"])

        if r["descrizione_en"]:
            altra = {"note_vitigno": r["descrizione_en"]}
            if prende_abbinamenti:
                altra["abbinamenti"] = spezza(r["abbinamenti_en"])
            if prende_sensoriali:
                altra["note_sensoriali"] = spezza(r["note_sensoriali_en"])
            f.per_lingua["en"] = altra


class DatabaseAssente(FileNotFoundError):
    """Il database non c'è: va costruito con data/build_db.py."""
