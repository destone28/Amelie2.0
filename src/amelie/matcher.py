"""Dal testo dell'etichetta al record: chi è questo vino.

L'OCR restituisce righe rumorose. Qui si decide che cosa il dispositivo ha
davanti, e con quanta sicurezza. La risposta non è mai «non lo so»: è una
**cascata**, e si scende finché si trova qualcosa di vero da dire.

    vino commerciale  ->  «Questo è il Barolo Cannubi di Marchesi di Barolo»
    tipologia         ->  «Non leggo bene il produttore, ma è un Barolo Riserva»
    denominazione     ->  «È un Barolo»
    vitigno           ->  «È un Nebbiolo»
    niente            ->  «Prova a girare l'etichetta verso di me»

Il livello raggiunto decide anche il tono: sotto il primo gradino il narratore
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

L'effetto, misurato su 1200 etichette costruite dalle tipologie del database e
lunghe abbastanza da non essere protette dal tetto sulle parole:

    senza la regola   1179 generiche, 21 attribuite a un produttore, 1 dichiarata CERTA
    con la regola     1200 generiche,  0 attribuite,                  0 certe

Senza la regola, la certa e' «Brunello di Montalcino» dato all'azienda «Vigna
Italia» con 100, perche' la parola «vigna» - che sull'etichetta e' del
disciplinare - le fa da firma. E su 500 etichette complete, dove il produttore
c'e' davvero, il prezzo e' piccolo: 498 riconosciute sul produttore giusto, e
nessuna sul produttore sbagliato - contro una, per giunta dichiarata certa,
senza la regola.
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
# Sotto SOGLIA_CERTA ma sopra questa il riconoscimento e' dubbio, e non si
# chiede all'ospite di scegliere: si dice il candidato meno specifico.
# Vedi `Matcher.il_piu_generico`.
SOGLIA_DUBBIA = 75
# Di quanto il primo classificato deve staccare un vino di un ALTRO produttore
# per potersi dire certo. Sotto questo margine il riconoscimento resta dubbio:
# vedi `Matcher.il_piu_generico`.
MARGINE_PRODUTTORE = 3.0
# Fra quanti dei primi cercare quel rivale.
RIVALI = 6
# Sotto questa somiglianza una parola del record NON si considera letta.
# `fuzz.ratio` fra due parole che non c'entrano nulla vale trenta o quaranta -
# "terre" contro "comune" fa 36 - e contarlo come credito parziale regalerebbe
# a ogni produttore di tre parole una quarantina di punti che sull'etichetta
# non ci sono. Un refuso vale ottanta e passa, quindi la soglia non lo taglia.
RISCONTRO_PAROLA = 70.0
# E quanto deve valere per dire il produttore quando il vino NON si sa: qui il
# nome esce dalla bocca del dispositivo da solo, senza un vino accanto che lo
# corregga, quindi si pretende che sia letto quasi esatto. Vedi
# `_il_produttore_scritto`.
PRODUTTORE_SCRITTO = 90.0

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
    # L'etichetta si e' letta benissimo, e in archivio non c'e' niente che si
    # possa nominare senza inventare. Si dice allora **solo cio' che c'e'
    # scritto**: che e' uno spumante, che e' rosato, che e' brut. Non e' un
    # fallimento ed e' l'opposto di un'improvvisazione - e' il livello in cui
    # ogni parola detta viene dalla bottiglia. Vedi `Matcher._solo_l_etichetta`.
    GENERICO = "generico"
    NULLA = "nulla"


# Dal piu' specifico al piu' generale. Un Barolo di un produttore dice piu' di
# un Barolo, che dice piu' della denominazione Barolo, che dice piu' del
# Nebbiolo: con un riconoscimento dubbio si prende il gradino piu' in basso.
GENERALITA = {Livello.VINO: 0, Livello.TIPOLOGIA: 1, Livello.DENOMINAZIONE: 2,
              Livello.VITIGNO: 3, Livello.GENERICO: 4}
LIVELLO_DELL_AMBITO = {"vino": Livello.VINO, "tipologia": Livello.TIPOLOGIA,
                       "denominazione": Livello.DENOMINAZIONE,
                       "vitigno": Livello.VITIGNO}


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

    # Il produttore e' stato LETTO sull'etichetta, o si e' sceso al vino
    # generico perche' non c'era? Se la cantina non si e' letta, i candidati
    # che differiscono solo per quella non sono alternative.
    produttore_letto_davvero: bool = True

    note_vitigno: str | None = None
    # I descrittori sensoriali tipici del vitigno. Vanno nei fatti perche'
    # altrimenti il modello se li inventa: senza, sul Chianti scrive "sentore
    # di ciliegio e pepe nero" - plausibile, ma non verificato. Con quelli
    # veri, cio' che scrive e' fondato E la verifica ha qualcosa da confrontare.
    note_sensoriali: list[str] = field(default_factory=list)
    temperatura_c: str | None = None
    # Le parole che l'etichetta usa per dire che TIPO di vino e' - «spumante»,
    # «metodo classico», «rosato», «brut». Si riempiono solo al livello
    # GENERICO, dove sono l'unica cosa che si puo' dire, e sono tutte lette
    # dalla bottiglia: nessuna viene da noi.
    qualificatori: list[str] = field(default_factory=list)

    # Le alternative al primo classificato: `candidati` sono le righe
    # LEGGIBILI (per il giornale e per la debug camera), `riferimenti` i record
    # a cui corrispondono, nello stesso ordine. Con un riconoscimento dubbio
    # `il_piu_generico` sceglie fra queste per identificativo: ricercare il
    # testo per risalire al record puo' riportare a un record DIVERSO.
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
        modello. I dataset sono in inglese, e con i valori grezzi il modello
        scrive «un abbinamento con il beef e il blu»: prende le parole che
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

        def colore_tradotto() -> str | None:
            # Due vocabolari dicono i colori, con chiavi di due fonti: «Red»
            # per X-Wines, «Rosso» per il registro. `traduci` restituisce il
            # valore com'e' quando non lo conosce, quindi un `or` fra i due
            # non ripiega mai: si guarda CHI lo conosce. Il colore di un vino
            # viene dal registro, e senza questo uscirebbe «Colour: Rosso».
            chiave = CHIAVE_COLORE.get(self.colore or "", self.colore)
            for vocabolario in ("colore", "tipo"):
                if chiave and not lessico.manca(vocabolario, [chiave]):
                    return t(vocabolario, chiave)
            return self.colore

        abbinamenti = (
            ", ".join(lessico.traduci_molti(
                "abbinamento", self.abbinamenti_in(lingua), lingua=lingua))
            if self.abbinamenti_in(lingua) else None
        )
        # X-Wines usa spesso la denominazione anche come "regione": ripeterla
        # non aggiunge nulla e induce il modello a trattarla come un luogo
        # diverso, inventando geografia.
        regione = self.regione
        if regione and self.denominazione and (
            regione in self.denominazione or self.denominazione in regione
            or (self.tipologia and regione in self.tipologia)):
            regione = None
        regione = t("regione", regione)

        # Le etichette nella lingua del blocco. Con etichette sempre italiane,
        # in inglese il modello leggerebbe «Nome: ... Gradazione: ...» con i
        # valori tradotti: meta' e meta'. Un ingresso cosi' insegna che
        # l'italiano e' la lingua delle etichette, e nei testi inglesi
        # ricompare la forma del blocco, con le etichette tradotte a orecchio -
        # «Disgust: Red with garnet notes».
        e = _ETICHETTE_BLOCCO.get(lingua, _ETICHETTE_BLOCCO["it"])
        righe = []
        for etichetta, valore in (
            (e["nome"], self.nome),
            (e["produttore"], self.cantina),
            (e["regione"], regione),
            (e["annata"], self.annata),
            (e["denominazione"], self.denominazione),
            (e["tipologia"], self.tipologia),
            (e["colore"], colore_tradotto()),
            (e["bacca"], self.colore_bacca),
            (e["categoria"], t("categoria_ue", self.categoria)),
            (e["corpo"], t("corpo", self.corpo, "narrativa")),
            (e["acidita"], t("acidita", self.acidita, "narrativa")),
            (e["elaborazione"], t("elaborazione", self.elaborazione, "narrativa")),
            (e["gradazione"], f"{self.abv}%" if self.abv else None),
            (e["vitigni"], ", ".join(self.vitigni) if self.vitigni else None),
            (e["abbinamenti"], abbinamenti),
            # Nella lingua chiesta, come fa la riga compatta: altrimenti queste
            # due resterebbero italiane dentro un blocco inglese.
            (e["note"], ", ".join(self.sensoriali_in(lingua))
             if self.sensoriali_in(lingua) else None),
            (e["temperatura"], f"{self.temperatura_c} {e['gradi']}"
             if self.temperatura_c else None),
            (e["nota_vitigno"], self.nota_in(lingua)),
        ):
            if valore not in (None, "", []):
                righe.append(f"{etichetta}: {valore}")
        righe.extend(self._righe_disciplinare(lingua))
        return "\n".join(righe)

    def blocco_compatto(self, lessico=None, lingua: str = "it") -> str:
        """Gli stessi fatti, nella forma piu' corta che li contenga tutti.

        Serve a una cosa sola: il tempo. Sulla board il prefill va a 16 token
        al secondo e i fatti NON si possono mettere in cache - cambiano a ogni
        bottiglia - quindi ogni token del prompt e' 60 millisecondi di silenzio
        prima che il modello cominci. Il blocco esteso ne costa 230, che sono
        quattordici secondi; questo ne costa 115, che sono sette.

        Non e' il blocco esteso abbreviato: e' lo stesso contenuto senza le
        etichette, che un modello addestrato su questa forma non gli servono.
        Il blocco esteso resta per il modello generico, che le etichette le
        legge davvero.

        La `nota sul vitigno` c'e', anche se costa 40 token - due secondi e
        mezzo di attesa - e anche se il racconto la dice comunque, dal
        template. I testi del corpus di addestramento usano le sue parole:
        **498 esempi su 550 (il 91%) contengono parole che senza la nota qui
        non ci sarebbero**. Addestrare su quel corpus con un ingresso senza
        nota significa insegnare a dire cose che l'ingresso non contiene:
        l'unico modo di produrle e' inventarle. Un modello addestrato cosi'
        scrive «Catarratto, un grande abruzzese del Piemonte» - e il
        Catarratto e' siciliano - su meta' dei casi.

        Per la stessa ragione qui NON si taglia nessun elenco. Con vitigni,
        abbinamenti e note sensoriali tagliati a tre o quattro voci, mentre il
        blocco esteso li porta tutti, il 25% dei testi del corpus nomina
        qualcosa che il taglio toglie. Un tetto che fa risparmiare diciassette
        token insegna a indovinare il quarto vitigno: non e' un risparmio, e'
        un debito.

        Due secondi e mezzo di attesa sono il prezzo di un compito imparabile.
        """
        if lessico is None:
            from .lessico import carica
            lessico = carica()

        def t(vocabolario, valore):
            return lessico.traduci(vocabolario, valore, lingua=lingua) if valore else None

        regione = self.regione
        if regione and self.denominazione and (
            regione in self.denominazione or self.denominazione in regione
                or (self.tipologia and regione in self.tipologia)):
            regione = None
        regione = t("regione", regione)

        colore = CHIAVE_COLORE.get(self.colore or "", self.colore)
        for vocabolario in ("colore", "tipo"):
            if colore and not lessico.manca(vocabolario, [colore]):
                colore = lessico.traduci(vocabolario, colore, lingua=lingua)
                break

        pezzi = [
            self.nome, self.cantina, self.denominazione, self.tipologia,
            # La regione: e' il fatto che il modello inventa quando non ce
            # l'ha - «un grande abruzzese del Piemonte» - e la si conosce.
            regione,
            ", ".join(self.vitigni) or None,
            colore,
            # La categoria c'e' anche qui, e non e' un di piu': il colore e'
            # solo un colore, «spumante» e «passito» non stanno nel suo posto,
            # e senza questa riga il modello non saprebbe che quel vino ha le
            # bolle. Ma non quando e' la categoria generica - «Wine», cioe'
            # «vino» - che di quel vino non dice niente.
            t("categoria_ue", self.categoria) if self.categoria != "Wine" else None,
            f"{self.abv}%" if self.abv else None,
            f"{self.temperatura_c}\u00b0" if self.temperatura_c else None,
            # Come fa il narratore: prima la versione nella lingua chiesta -
            # gli abbinamenti di un vitigno sono prosa scritta a mano - e poi
            # il vocabolario, per quelli che sono chiavi di un dataset.
            ", ".join(lessico.traduci_molti(
                "abbinamento", self.abbinamenti_in(lingua),
                lingua=lingua)) or None,
            ", ".join(self.sensoriali_in(lingua)) or None,
        ]
        righe = [" \u00b7 ".join(str(x) for x in pezzi if x)]
        if (nota := self.nota_in(lingua)):
            righe.append("NOTA " + nota)
        if self.disciplinare:
            from .organolettico import carica as carica_organolettico

            vocabolario = carica_organolettico()
            rese = []
            for ambito in ("colore", "odore", "sapore"):
                if not (testo := self.disciplinare.get(ambito)):
                    continue
                if (reso := vocabolario.rendi(testo, ambito, lingua=lingua)):
                    rese.append(reso.testo)
            if rese:
                righe.append("DISC " + " \u00b7 ".join(rese))
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

    Serve a una cosa sola: impedire che `chiudi()` chiuda la connessione
    SQLite mentre il thread di lavoro ci sta ancora leggendo. Il processo
    morirebbe di segmentation fault - non un'eccezione che si cattura, un
    crash. Il lucchetto e' RIENTRANTE perche' questi metodi si chiamano fra
    loro: `cerca` chiama `_candidati`, che chiama `_norme_vino`.
    """
    @functools.wraps(f)
    def dentro(self, *a, **kw):
        with self._db:
            return f(self, *a, **kw)
    return dentro


# Il ponte fra le due scritture del colore. `_colore_di` risponde in italiano,
# perche' e' la lingua del registro; i vocabolari hanno le chiavi di X-Wines,
# che sono inglesi. Senza questa riga, in inglese uscirebbe «Colour: Rosso».
CHIAVE_COLORE = {"Rosso": "Red", "Bianco": "White", "Rosato": "Rosé"}

# Le etichette del blocco dei fatti, una serie per lingua.
_ETICHETTE_BLOCCO = {
    "it": {"nome": "Nome", "produttore": "Produttore", "regione": "Regione",
           "annata": "Annata", "denominazione": "Denominazione",
           "tipologia": "Tipologia", "colore": "Colore",
           "bacca": "Colore della bacca", "categoria": "Categoria",
           "corpo": "Corpo", "acidita": "Acidità", "elaborazione": "Come nasce",
           "gradazione": "Gradazione", "vitigni": "Vitigni",
           "abbinamenti": "Abbinamenti", "note": "Note sensoriali tipiche",
           "temperatura": "Temperatura di servizio", "gradi": "gradi",
           "nota_vitigno": "Nota sul vitigno"},
    "en": {"nome": "Name", "produttore": "Producer", "regione": "Region",
           "annata": "Vintage", "denominazione": "Appellation",
           "tipologia": "Type", "colore": "Colour",
           "bacca": "Berry colour", "categoria": "Category",
           "corpo": "Body", "acidita": "Acidity", "elaborazione": "How it is made",
           "gradazione": "Alcohol", "vitigni": "Grapes",
           "abbinamenti": "Pairings", "note": "Typical sensory notes",
           "temperatura": "Serving temperature", "gradi": "degrees",
           "nota_vitigno": "About the grape"},
}

# Il colore dei due registri e' scritto in lingue diverse: figshare in inglese,
# il documento unico in italiano. E' il vincolo che non si puo' sbagliare -
# nessuna descrizione di un bianco vale per un rosso - quindi si traduce qui e
# si applica per primo.
# In archivio convivono le due scritture, perche' convivono le due fonti.
# «Sparkling» e «Dessert» invece NON sono colori: dicono che tipo di vino e',
# non di che colore, e per un vino cosi' il vincolo non si puo' applicare.
COLORE_UE ={"Red": "Rosso", "White": "Bianco", "Rosé": "Rosato",
             "Rosso": "Rosso", "Bianco": "Bianco", "Rosato": "Rosato"}

# La colonna `tipo` di X-Wines mescola due cose: il colore e lo stile. «Red»,
# «White», «Rosé» sono colori; «Sparkling» e «Dessert» no, e riguardano 2.948
# vini su 19.602 - il quindici per cento. Presi per colori, finirebbero
# stampati nei fatti come «Colore: spumante», e il modello li ripeterebbe
# fedelmente: «di colore spumante».
#
# Peggio: `_disciplinare` accetta solo un colore vero, e con il `tipo` preso
# per colore quei vini non ricevono MAI una citazione del registro. Misurato:
# zero su centocinquanta spumanti e zero su centocinquanta dessert, contro il
# sessantuno per cento dei rossi. Sono i fatti migliori dell'archivio, e a un
# vino su sette non arriverebbero.
#
# Quindi il tipo dice la FAMIGLIA, e il registro dice quale membro della
# famiglia: si accetta la categoria della tipologia solo se concorda. La
# tipologia di un vino si sceglie per somiglianza di nome, e su uno spumante
# capita che peschi la versione ferma della stessa denominazione: crederle
# vorrebbe dire dichiarare fermo un vino con le bolle.
FAMIGLIA_DAL_TIPO = {
    "Sparkling": ("Sparkling Wine", "Quality Sparkling Wine",
                  "Quality Aromatic Sparkling Wine", "Semi-Sparkling Wine"),
    "Spumante": ("Sparkling Wine", "Quality Sparkling Wine",
                 "Quality Aromatic Sparkling Wine", "Semi-Sparkling Wine"),
    "Dessert": ("Wine From Raisined Grapes", "Wine Of Overripe Grapes",
                "Liqueur Wine"),
    "Dessert/Port": ("Liqueur Wine", "Wine From Raisined Grapes",
                     "Wine Of Overripe Grapes"),
    "Dolce": ("Wine From Raisined Grapes", "Wine Of Overripe Grapes",
              "Liqueur Wine"),
}

# Quanto in basso si scende nella lista cercando il colore giusto. Oltre, la
# somiglianza e' troppo lontana da quella del primo perche' il colore possa
# giustificare il salto: si starebbe raccontando un altro vino.
#
# Sedici, e non meno, perche' la lista si appiattisce: su «metodo classico»
# duecento candidati hanno tutti somiglianza 80,0, e fra loro quello del
# colore giusto puo' stare al nono posto. Ordinarli meglio non si puo' - sono
# davvero equivalenti per il testo letto - e il colore e' l'unica cosa che li
# distingue.
CANDIDATI_PER_COLORE = 16

# I vitigni che nell'archivio non sono uve ma buchi del registro. «na» e'
# collegato a 691 tipologie, a volte come vitigno principale - il Garda
# Cabernet ce l'ha come unico - e senza filtro il racconto direbbe «Si ottiene
# da na.». Si scartano qui, in ogni interrogazione che legge i vitigni: cosi'
# valgono per qualunque database, anche costruito da fonti piu' recenti.
VITIGNI_FINTI = ("na", "n.a.", "n/a", "nd", "n.d.")
_SENZA_VITIGNI_FINTI = (" AND lower(vi.nome) NOT IN ("
                        + ", ".join(f"'{v}'" for v in VITIGNI_FINTI) + ")")

# In che ordine si dicono i vitigni principali. Il registro li elenca in ordine
# alfabetico, e il primo e' quello di cui si legge la scheda: il Soave diventava
# «Nasce da Chardonnay: borgognone, ovunque nel mondo». Conta invece quanti vini
# di quella denominazione, in archivio, dichiarano quell'uva: Garganega 171,
# Chardonnay 15. Il parametro e' l'id della denominazione.
_USO_NEI_VINI = ("(SELECT count(*) FROM vino_vitigno vv JOIN vino v ON v.id = vv.vino_id"
                 " WHERE vv.vitigno_id = vi.id AND v.denominazione_id = ?)")

# La temperatura di servizio la decide la CATEGORIA, non l'uva, tutte le volte
# che il vino non e' fermo. Le schede dei vitigni in `data/vitigni.json` danno
# la temperatura del vino fermo di quell'uva - giusta per un Pinot Nero, giusta
# per un Moscato - e uno spumante di Pinot Nero la erediterebbe: un Trentodoc
# rosato da servire a QUINDICI-DICIASSETTE GRADI. Non e' un caso isolato: in
# archivio 819 tipologie su 4.300 sono spumanti o frizzanti, piu' 212 fra
# passiti e liquorosi.
#
# I valori sono quelli della pratica corrente, non una nostra opinione; e la
# categoria e' quella del registro UE, che e' il documento che dice cos'e' quel
# vino. Per i vini fermi («Wine») non c'e' nessuna regola: li' l'uva sa piu'
# della categoria, e resta la sua.
TEMPERATURA_PER_CATEGORIA = {
    "Sparkling Wine": "6-8",
    "Quality Sparkling Wine": "6-8",
    "Quality Aromatic Sparkling Wine": "6-8",
    "Semi-Sparkling Wine": "8-10",
    "Wine From Raisined Grapes": "10-12",
    "Wine Of Overripe Grapes": "10-12",
    "Liqueur Wine": "12-14",
}

# Le parole con cui un'etichetta dichiara il proprio colore, nelle lingue in
# cui le etichette italiane lo scrivono. Quando una di queste si legge, non e'
# un indizio: e' la bottiglia che lo dice di se stessa, e nessun record di
# colore diverso puo' essere quella bottiglia.
#
# Per esempio, su «Leggiadro · Brut Rose · METODO CLASSICO» il primo candidato
# per somiglianza e' «Asti Metodo Classico» - che e' BIANCO, di Moscato, e
# dolce - all'86 %, e senza il colore si racconterebbe il Moscato d'Asti a chi
# ha in mano uno spumante rosa. I tre candidati accanto sono tutti Metodo
# Classico Rose', cioe' giusti: il colore, se entra nella scelta, basta a farla.
COLORE_DETTO = {
    "rosato": "Rosato", "rosata": "Rosato", "rose": "Rosato",
    "rosado": "Rosato",
    "rosso": "Rosso", "rossa": "Rosso", "rouge": "Rosso", "red": "Rosso",
    "tinto": "Rosso",
    "bianco": "Bianco", "bianca": "Bianco", "blanc": "Bianco",
    "white": "Bianco", "blanco": "Bianco",
}
# «Nero» e «rosa» NON sono in elenco, di proposito. Su un'etichetta italiana
# non sono dichiarazioni di colore: sono pezzi di nomi di vitigno - Nero
# d'Avola, Nerello, Nero di Troia, Pinot Nero, Moscato Rosa. E il Pinot Nero e'
# la trappola: un blanc de noirs e' un metodo classico BIANCO fatto di Pinot
# Nero, e leggendo «nero» come colore si scarterebbe la risposta giusta per
# andare a cercarne una rossa. Un'etichetta che vuole dire rosso scrive
# «Rosso»; il colore dell'uva lo sa gia' l'archivio.

# Parole che nel nome di una tipologia denotano un PRODOTTO DIVERSO, non una
# sfumatura: un passito non e' la versione dolce del bianco, e' un altro vino.
QUALIFICATORI = frozenset((
    "passito", "liquoroso", "spumante", "frizzante", "riserva", "superiore",
    "novello", "classico", "vendemmia", "tardiva", "stramature",
))

# Le parole che NON identificano un vino: dicono che TIPO di vino e', non QUALE
# vino e'. «Spumante», «rosato», «brut» valgono per migliaia di bottiglie;
# «Trento», «Barolo», «Cerasuolo» valgono per una zona sola.
#
# La distinzione porta tutto il peso della regola piu' importante del
# riconoscimento: **non si nomina cio' che non si e' letto**. Misurato su 139
# etichette vere piu' 9 bottiglie fuori archivio, la separazione e' totale -
# i riconoscimenti giusti hanno il 100 % delle parole identificanti sul vetro,
# le invenzioni ne hanno lo 0 %. Vedi `_tutto_letto`.
PAROLE_GENERICHE = frozenset(QUALIFICATORI) | frozenset((
    "vino", "vini", "wine", "doc", "docg", "dop", "igp", "igt",
    # Le sigle straniere valgono quanto le italiane: sono marchi di
    # denominazione, non nomi di vino. Senza, il conto lo pagherebbe lo
    # Champagne - «aoc» risulterebbe una parola da leggere, nessun titolo
    # passerebbe, e una bottiglia che dice CHAMPAGNE resterebbe senza risposta.
    "aoc", "aop", "ava", "doca", "vdp", "qba", "aoc", "igt",
    "brut", "extra", "dry", "secco", "dolce", "abboccato", "amabile", "nature",
    "metodo", "millesimato", "cuvee", "sec", "demi", "annata", "cru",
    "rosso", "rossa", "bianco", "bianca", "rosato", "rosata", "rose", "rosa",
    "red", "white", "blanc", "noir", "nero", "nera",
))

# Le parole con cui un'etichetta dichiara che TIPO di vino contiene, e la
# categoria del registro UE a cui corrispondono. Servono quando in archivio non
# c'e' niente da nominare: sono l'unica cosa che si puo' dire, e la puo' dire
# perche' l'ha scritta il produttore.
CATEGORIA_DETTA = {
    "spumante": "Sparkling Wine",
    # «Metodo» su un'etichetta di vino compare quasi solo in «metodo classico»
    # e «metodo charmat», che sono due modi di fare le bolle: la parola da
    # sola dichiara uno spumante. «Classico» non si puo' usare - il filtro
    # delle parole lette lo scarta, perche' sta su un'etichetta su tre.
    "metodo": "Sparkling Wine",
    "champenoise": "Quality Sparkling Wine",
    "frizzante": "Semi-Sparkling Wine",
    "passito": "Wine From Raisined Grapes",
    "liquoroso": "Liqueur Wine",
}

# L'ordine in cui le parole del tipo si dicono a voce: «spumante metodo
# classico rosato brut», non «brut rosato classico spumante».
ORDINE_QUALIFICATORI = (
    "spumante", "frizzante", "passito", "liquoroso", "novello",
    "metodo", "classico", "champenoise", "millesimato",
    "rosato", "rosso", "bianco", "rose",
    "brut", "extra", "dry", "nature", "secco", "amabile", "dolce",
    "riserva", "superiore",
)

# Fra i qualificatori, questi non sono una sfumatura: cambiano il PRODOTTO. Un
# passito non e' la versione dolce del bianco, e' un altro vino, fatto con uve
# appassite. Chi ne porta uno e l'altro no non puo' ricevere la sua descrizione
# in nessun caso - non e' una preferenza, e' un'esclusione.
#
# Un esempio misurato: senza «sciacchetra» in questo elenco, «Cinque Terre
# Costa de Campu Riserva», un bianco secco, prende la descrizione dello
# «Sciacchetra' Riserva», che e' un passito. Stessa denominazione, stesso
# colore, e nel nome nessun'altra parola che faccia da freno. I nomi di
# menzione valgono quanto gli aggettivi: e' il vino a essere diverso, non il
# modo di chiamarlo.
# Spumante e frizzante NON sono qui, e la ragione e' misurata: la cascata li
# separa gia' da sola, mentre escluderli costerebbe 412 tipologie per
# correggere quattro attribuzioni. Qui c'e' solo cio' che nasce da uve diverse - appassite,
# stramature, o fortificate dopo - e che quindi non e' lo stesso vino nemmeno
# alla lontana.
PRODOTTO_DIVERSO = frozenset((
    "passito", "liquoroso", "stramature", "sciacchetra", "vinsanto",
    "vin santo", "recioto", "amarone", "sforzato", "sfursat",
    "occhio di pernice", "vendemmia tardiva",
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


# «leggermente erbaceo, erbaceo, secco»: il registro porta cinque citazioni
# con una parola ripetuta di seguito, e il racconto - composto o scritto dal
# modello, che le copia - verrebbe bocciato dalla verifica per una ripetizione
# che non e' sua. Si toglie qui, una volta, dove la citazione entra.
_PAROLA_DOPPIA = re.compile(r"\b(\w{4,})\b([,\s]+)\1\b", re.I)


# Trentanove citazioni del registro cominciano col verbo - «é fresco,
# piacevole e armonico» - e chi le riporta ce ne mette un altro davanti: «il
# gusto è é fresco». Il verbo lo mette la frase che cita, non la citazione.
_INIZIA_COL_VERBO = re.compile(r"^(?:é|è|e'|ed|e|sono|ha|hanno|va)\s+", re.I)

# E dieci cominciano a meta' di una parola o di una frase, perche' il taglio
# del documento d'origine e' caduto li'. Senza pulizia il racconto direbbe
# «il disciplinare lo vuole di odore tico di moscato», dove «tico» e' la coda
# di «aromatico».
#
# Si toglie il troncone, ma quel che resta deve reggere da solo: dopo «tico»
# puo' restare «colore giallo paglierino più o meno intenso, odore
# caratteristico e fragrante», che va benissimo, oppure «di moscato», che nel
# giro di frase diventa «di odore di moscato». Sotto una certa lunghezza si
# lascia perdere la citazione: il narratore ha comunque il resto dei fatti.
_COMINCIA_A_META = re.compile(r"^(?:tico|tici|stico|stici|matico|matici)\b[,;]?\s*", re.I)
_RESTO_MINIMO = 16

# «ove prevalgono le note fruttate» e' la coda di una subordinata: quel che
# segue e' un verbo, e nel giro di frase - «il profumo è ove prevalgono...» -
# non c'e' taglio che tenga.
_COMINCIA_CON_SUBORDINATA = re.compile(r"^(?:ove|dove|che|cui|mentre|quando|se)\b", re.I)

# E centoventisei sono troncate a meta', con l'ultima parola che resta
# appesa: «giallo paglierino più o meno intenso, il». Il taglio viene dal
# documento di origine, non da noi, e una frase che finisce su un articolo la
# si sente subito. Si toglie la coda finche' ce n'e'.
_CODA_APPESA = re.compile(
    r"[,;]?\s+(?:un|uno|una|un'|il|lo|la|i|gli|le|di|del|dello|della|dei|degli"
    r"|delle|da|dal|dalla|dai|con|per|a|al|alla|ai|e|ed|o|od|che|più|piu'|ha"
    r"|hanno|sono|the|of|and|with|to)\s*$", re.I)


def _citazioni_utili(r) -> dict[str, str]:
    fuori = {}
    for ambito in ("colore", "odore", "sapore"):
        v = (r[f"desc_{ambito}"] or "").strip().rstrip(".")
        v = _PAROLA_DOPPIA.sub(r"\1", v)
        if _COMINCIA_CON_SUBORDINATA.match(v):
            continue
        tagliato = _COMINCIA_A_META.sub("", v).strip()
        if tagliato != v:
            v = tagliato if len(tagliato) >= _RESTO_MINIMO else ""
        v = _INIZIA_COL_VERBO.sub("", v).strip()
        for _ in range(4):
            tagliato = _CODA_APPESA.sub("", v).rstrip(" ,;")
            if tagliato == v:
                break
            v = tagliato
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
        self._luoghi: frozenset[str] | None = None
        self._per_parola: dict[str, set[str]] | None = None
        # Cio' che si e' gia' chiesto all'archivio, e che non cambiera'.
        #
        # Senza questa memoria una ricerca fa quasi cinquecento interrogazioni
        # SQL, perche' la cascata ripassa gli stessi candidati a ogni livello:
        # duecentotrenta millesimi sui quattrocento della ricerca intera, spesi
        # a richiedere il colore dello stesso record otto volte. La connessione
        # e' in sola lettura e il file non cambia mentre il dispositivo e'
        # acceso: la seconda risposta e' identica alla prima per costruzione.
        self._colori: dict[tuple[str, int], str | None] = {}
        self._tipologie: dict[tuple[int, str], int | None] = {}
        self._per_record: dict[tuple[str, int], tuple[str, float]] | None = None

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

        migliore = self._del_colore_giusto(candidati, token)
        fatti = self._componi(migliore)
        fatti.sicurezza = migliore.somiglianza
        # La garanzia: un produttore non si nomina se non lo si e' letto.
        if not migliore.produttore_letto:
            fatti = self._senza_produttore(fatti, testo_norm, tetto)
            fatti.produttore_letto_davvero = False
        # E ora la regola che vale su TUTTI i nomi, non solo su quello della
        # cantina: non si nomina cio' che non si e' letto.
        fatti = self._non_oltre_cio_che_si_e_letto(fatti, token, testo_norm, tetto)
        fatti = self._del_colore_dichiarato(fatti, token, testo_norm, tetto)
        # Il produttore lo si dice se lo si e' LETTO, anche quando non si sa
        # quale suo vino sia: vedi `_il_produttore_scritto`.
        fatti = self._il_produttore_scritto(fatti, candidati, testo_norm)
        if self._c_e_un_altro_produttore(candidati):
            fatti.sicurezza = min(fatti.sicurezza, SOGLIA_CERTA - 0.5)
        fatti.annata = annata
        fatti.ripiego = self.catena_di_ripiego(fatti)
        # Le alternative - per il giornale e per `il_piu_generico` - devono
        # essere DIVERSE fra loro: tre righe che dicono quasi la stessa cosa
        # non aggiungono niente.
        visti = {migliore.testo}
        detto = self._colore_detto(token)
        for c in candidati:
            if c is migliore:
                continue
            if len(fatti.candidati) >= 3:
                break
            if c.testo in visti or self._stesso_vino(fatti, c):
                continue
            # Un candidato del colore sbagliato non e' un'alternativa: e' lo
            # stesso errore, spostato di un posto. Se la bottiglia dice
            # «Rose'», un Moscato bianco e' una risposta che si sa gia' falsa.
            if detto is not None:
                suo = self._colore_di(c.ambito, c.ambito_id)
                if suo is not None and suo != detto:
                    continue
            # E nemmeno si propone cio' che non si e' letto: un'alternativa
            # puo' diventare la risposta detta a voce (vedi `il_piu_generico`),
            # e le regole non si allentano li'.
            if not self._tutto_letto(c.testo, token):
                continue
            visti.add(c.testo)
            fatti.candidati.append(self.etichetta(c.ambito, c.ambito_id)
                                   or c.testo)
            fatti.riferimenti.append((c.ambito, c.ambito_id))
        return fatti

    def _del_colore_giusto(self, candidati: list[Candidato],
                           token: Sequence[str]) -> Candidato:
        """Il migliore, ma senza contraddire il colore scritto sull'etichetta.

        Quando la bottiglia dichiara il proprio colore - «Rose'», «Rosso»,
        «Bianco» - quella parola non e' un indizio da pesare insieme agli
        altri: e' la bottiglia che lo dice di se stessa. Nessun record di
        colore diverso puo' essere quella bottiglia, per quanto il suo nome
        somigli a quello che c'e' scritto.

        Un esempio misurato: su «Leggiadro · Brut Rose · METODO CLASSICO» il
        primo per somiglianza e' «Asti Metodo Classico» all'86 % - bianco, di
        Moscato, dolce - e senza questo vincolo si racconterebbe il Moscato
        d'Asti a chi ha in mano uno spumante rosa. I tre candidati accanto
        sono tutti Metodo Classico Rose': la risposta giusta e' in lista, solo
        non per prima.

        Non si butta via niente: si scende nella lista fino al primo che non
        contraddice, e chi contraddice resta fra le alternative. Se nessuno va
        bene si tiene il primo, perche' un archivio che non ha quel colore non
        e' una ragione per tacere.
        """
        detto = self._colore_detto(token)
        if detto is None:
            return candidati[0]
        vicini = candidati[:CANDIDATI_PER_COLORE]
        colori = [self._colore_di(c.ambito, c.ambito_id) for c in vicini]
        if colori[0] in (None, detto):
            # Il primo non contraddice niente: non c'e' nulla da correggere.
            return candidati[0]

        # Prima di scendere: se la denominazione del primo ha una tipologia del
        # colore dichiarato, e il suo nome si legge sull'etichetta, il primo
        # non e' da scartare - e' da correggere, e lo fa `_del_colore_dichiarato`
        # scegliendo fra i fratelli. Scendere gli farebbe perdere una
        # denominazione che sulla bottiglia c'e' scritta.
        #
        # Per esempio, su «TARVESIUM PROSECCO ROSE DOC» i primi quattordici
        # candidati pareggiano tutti a 80, e sono tutti «X prosecco extra dry»
        # tranne un «canti rose extra dry» del Piemonte. Scendere su quello
        # vorrebbe dire cambiare denominazione per via del colore, e poi non
        # poter nominare ne' «Canti» ne' «Piemonte», che sull'etichetta non ci
        # sono: non resterebbe niente da dire.
        if self._fratelli_leggibili(
                self._denominazione_di(candidati[0].ambito, candidati[0].ambito_id),
                detto, token):
            return candidati[0]

        # Si scende SOLO su chi il colore giusto ce l'ha detto. Accontentarsi
        # di chi non lo dichiara fa danni: la lista sotto un bianco e' piena
        # di record senza colore, e il primo che capita non ha nessuna ragione
        # di essere quella bottiglia - misurato, su «Brut Rose'» si finirebbe
        # a raccontare un Brachetto passito rosso.
        for c, colore in zip(vicini, colori):
            if colore == detto:
                log.info("colore letto %s: scelgo «%s» invece di «%s», che e' %s",
                         detto, c.testo, candidati[0].testo, colori[0])
                return c
        return candidati[0]

    @staticmethod
    def _colore_detto(token: Sequence[str]) -> str | None:
        """Il colore che l'etichetta dichiara di se stessa, se lo dichiara.

        Uno solo: due parole di colore diverso sulla stessa etichetta - e
        capita, «Rosso» di una denominazione accanto a «bianco» di una nota -
        vogliono dire che non si sa, e non sapere e' meglio che scegliere a
        caso quale delle due vale.
        """
        trovati = {COLORE_DETTO[x] for x in token if x in COLORE_DETTO}
        return trovati.pop() if len(trovati) == 1 else None

    def _voce_di_ricerca(self, ambito: str, ident: int) -> tuple[str, float] | None:
        """Il testo indicizzato di un record, preso per chiave invece che cercato.

        `ricerca` e' una tabella FTS5, e in FTS5 le colonne che non sono testo
        indicizzato sono UNINDEXED davvero: `WHERE ambito = ? AND ambito_id = ?`
        non ha nessun indice da usare e scandisce venticinquemila righe. Sono
        **quarantacinque millesimi a chiamata**, misurati, e la cascata la
        chiama quattro volte per ricerca: centottantacinque millesimi buttati a
        rileggere un archivio che sa gia' tutto.

        Qui si legge l'archivio una volta e si tiene un dizionario. Costa una
        scansione al primo uso - la stessa che la query pagherebbe a ogni
        chiamata - e poi nulla. Si puo' fare perche' la connessione e' in sola lettura: il file
        non cambia mentre il dispositivo e' acceso.
        """
        if self._per_record is None:
            self._per_record = self._indice_per_record()
        return self._per_record.get((ambito, ident))

    @sotto_lucchetto
    def _indice_per_record(self) -> dict[tuple[str, int], tuple[str, float]]:
        indice: dict[tuple[str, int], tuple[str, float]] = {}
        for r in self.con.execute(
                "SELECT ambito, ambito_id, testo, peso FROM ricerca"):
            # `setdefault` e non assegnazione: dove un record ha piu' di una
            # voce vale la prima, la stessa che darebbe `fetchone()` su una
            # query per chiave. Quale voce si prende decide cosa si racconta.
            indice.setdefault((r["ambito"], r["ambito_id"]), (r["testo"], r["peso"]))
        log.debug("indice per record: %d voci", len(indice))
        return indice

    def _colore_di(self, ambito: str, ambito_id: int) -> str | None:
        """Di che colore e' questo record, tradotto, o `None` se non lo dice.

        Per un VINO il colore sta in `tipo`, e spessissimo quella colonna non
        contiene un colore: contiene «Sparkling» o «Dessert», che dicono che
        tipo di vino e', non di che colore. In quel caso il colore vero sta
        sulla tipologia a cui il vino appartiene, e li' si va a prenderlo -
        altrimenti meta' degli spumanti risulterebbe senza colore proprio
        quando il colore e' l'unica cosa che l'etichetta dichiara.
        """
        chiave = (ambito, ambito_id)
        if chiave not in self._colori:
            self._colori[chiave] = self._leggi_colore(ambito, ambito_id)
        return self._colori[chiave]

    def _leggi_colore(self, ambito: str, ambito_id: int) -> str | None:
        if ambito == "tipologia":
            r = self.con.execute(
                "SELECT colore FROM tipologia WHERE id = ?", (ambito_id,)).fetchone()
            return COLORE_UE.get(r["colore"] or "") if r else None
        if ambito == "denominazione":
            # Una denominazione ha un colore solo se TUTTE le sue tipologie
            # hanno quello. Lambrusco Grasparossa di Castelvetro e' rosso in
            # ogni sua forma, e senza questo il livello «denominazione»
            # resterebbe senza colore: il verificatore non potrebbe smentire un
            # modello che lo descrive «di colore bianco».
            colori = {COLORE_UE.get(r["colore"] or "")
                      for r in self.con.execute(
                          "SELECT colore FROM tipologia WHERE denominazione_id = ?",
                          (ambito_id,))}
            colori.discard(None)
            return colori.pop() if len(colori) == 1 else None
        if ambito != "vino":
            return None
        r = self.con.execute(
            "SELECT tipo, denominazione_id, nome_norm FROM vino WHERE id = ?",
            (ambito_id,)).fetchone()
        if not r:
            return None
        # PRIMA la tipologia, poi `tipo`. Sembra il contrario di quello che si
        # farebbe - il record piu' specifico dovrebbe saperne di piu' - ed e'
        # sbagliato: la colonna `tipo` dei vini commerciali e' sporca. Misurato
        # in archivio, «fiegl metodo classico brut ROSE» ci sta dentro come
        # «Rosso». Il colore delle tipologie viene invece dal registro UE, ed
        # e' il documento che definisce cosa quel vino ha il diritto di essere.
        if r["denominazione_id"]:
            tid = self._tipologia_del_vino(r["denominazione_id"], r["nome_norm"])
            if tid is not None:
                colore = self._colore_di("tipologia", tid)
                if colore is not None:
                    return colore
        # Ultima spiaggia: il colore scritto sull'etichetta. Seicentotrentacinque
        # vini non hanno colore da nessun'altra parte - quasi tutti spumanti e
        # passiti, dove `tipo` dice lo stile e non il colore - e senza colore
        # non c'e' citazione, perche' il registro si interroga per
        # denominazione E colore.
        return COLORE_UE.get(r["tipo"] or "") or self._colore_scritto_nel_nome(
            r["nome_norm"])

    def _stesso_vino(self, f: Fatti, c: Candidato) -> bool:
        """Questo candidato e' lo stesso vino di un altro produttore?

        Sull'etichetta c'e' scritto «Cerasuolo d'Abruzzo» e basta. In archivio
        ce ne sono tre, di Filari, Lepore e Valori, ma non sono tre
        alternative: **la bottiglia non dice di chi e'**, e nessuno al tavolo
        lo sa meglio di lei. La regola del produttore ha gia' dichiarato
        impossibile quella scelta un secondo prima, facendo scendere al vino
        generico.

        Un candidato «aggiunge» qualcosa solo se porta a un vino DIVERSO. Se
        ripiegando finisce sullo stesso record su cui si e' gia' - la stessa
        tipologia, la stessa denominazione - non e' un'alternativa: e' la
        stessa risposta con sopra il nome di un'azienda che non si e' letta.

        Due criteri, e il secondo e' quello che morde.

        Il primo e' la catena: se il candidato, ripiegando, passa da dove siamo
        gia', non porta niente - e' la stessa risposta con sopra un nome.

        Il secondo: **se non stiamo nominando un produttore, un candidato che
        ne nomina uno non e' un'alternativa, e' una tentazione.** Come
        alternativa porterebbe il nome di un'azienda che non si e' letta -
        cioe' proprio cio' che la regola del produttore vieta. E la catena da
        sola non basta a fermarlo: «Origine Cerasuolo d'Abruzzo» di Passione
        Natura in archivio sta sotto Montepulciano d'Abruzzo, non sotto
        Cerasuolo, quindi la sua catena non passa da dove siamo - ma quella
        riga si legge come lo stesso vino con una cantina appiccicata.

        Quando invece la cantina si e' letta, tutto resta: due cantine
        diverse sono due risposte diverse, e l'etichetta in mano all'ospite le
        distingue.
        """
        if not f.origine:
            return False
        if f.cantina is None and c.ambito == "vino":
            r = self.con.execute("SELECT cantina FROM vino WHERE id = ?",
                                 (c.ambito_id,)).fetchone()
            if r and r["cantina"]:
                return True
        suo = Fatti(origine=(c.ambito, c.ambito_id))
        return f.origine in self.catena_di_ripiego(suo)

    def _c_e_un_altro_produttore(self, candidati: list[Candidato]) -> bool:
        """C'e' un ALTRO produttore quasi altrettanto plausibile?

        La sicurezza non e' una proprieta' della stringa vincente: e' una
        proprieta' dell'affermazione che si sta per fare a un tavolo. Per
        esempio, su "Monte Antico ... Sangiovese, Merlot" il primo classificato
        e' il Sangiovese-Merlot di **Monte Giove** con 90, e a 2.4 punti di
        distanza c'e' il vino di **Monte Antico**, cioe' la risposta giusta.
        Con due produttori cosi' vicini il dispositivo non sta riconoscendo:
        sta tirando a indovinare quale nome stampare. Allora non si dichiara
        certo, e il riconoscimento dubbio ripiega sul gradino piu' generico -
        qui lo stesso vino senza produttore: vedi `il_piu_generico`.

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
                log.info("due produttori a pari evidenza (%r / %r): resta dubbio",
                         cantina_primo, altra)
                return True
        return False

    @staticmethod
    def _identificanti(testo: str) -> list[str]:
        """Le parole di un nome che dicono QUALE vino e', non che tipo e'.

        Si passa dallo stesso filtro delle parole LETTE, e non e' un dettaglio:
        pretendere che si legga anche il «di» di «Primitivo di Manduria»
        significa bocciare ogni record che ne contenga uno, perche' quel filtro
        i «di» li butta via da tutte e due le parti. La regola confronta cio'
        che e' confrontabile.
        """
        return [p for p in parole_utili(testo) if p not in PAROLE_GENERICHE]

    @staticmethod
    def _tutto_letto(testo_record: str, lette: Sequence[str]) -> bool:
        """Le parole che identificano questo record erano sull'etichetta?

        È la regola più importante del riconoscimento: **non si nomina cio' che
        non si e' letto.** «Trento Rosato/Rose» somiglia moltissimo a «Brut Rose
        Metodo Classico» - due parole su tre in comune - ma la parola «Trento»
        sulla bottiglia non c'era, e Trento e' un posto: dirlo vuol dire
        attribuire al vino un'origine che nessuno ha dichiarato.

        Misurato su 139 etichette vere piu' 9 bottiglie fuori archivio, e la
        separazione e' totale:

            riconoscimenti giusti      100 % delle parole identificanti lette
            invenzioni                   0 %, con somiglianza da 11 a 73

        Non serve una soglia intermedia, e una soglia di SOMIGLIANZA non
        potrebbe fare questo lavoro: «Lambrusco dell'Emilia» diventerebbe
        «Colli dell'Etruria Centrale» con sicurezza 67, sopra al Chianti
        Classico vero che ne fa 78. Le due popolazioni si sovrappongono nella
        somiglianza e non si sovrappongono per niente qui.

        Un refuso dell'OCR non fa cadere la regola: il riscontro e' per parola,
        con la stessa soglia usata per la prova del produttore - `fuzz.ratio`
        sotto 70 non e' un riscontro debole, e' un non-riscontro, e un refuso
        vale ottanta e passa.
        """
        from rapidfuzz import fuzz

        ident = Matcher._identificanti(testo_record)
        if not ident:
            # Un record fatto di sole parole generiche - «Spumante Rosato» -
            # non attribuisce niente a nessuno: non c'e' niente da provare.
            return True
        libere = list(lette)
        for parola in ident:
            if not libere:
                return False
            i = max(range(len(libere)), key=lambda k: fuzz.ratio(parola, libere[k]))
            if fuzz.ratio(parola, libere[i]) < RISCONTRO_PAROLA:
                return False
            # Una parola letta ne conferma UNA sola: senza, un'etichetta con
            # «Montepulciano» scritto due volte proverebbe due record diversi.
            libere.pop(i)
        return True

    def _denominazione_di(self, ambito: str, ident: int) -> int | None:
        """Sotto quale denominazione sta questo record."""
        if ambito == "denominazione":
            return ident
        if ambito in ("vino", "tipologia"):
            r = self.con.execute(
                f"SELECT denominazione_id FROM {ambito} WHERE id = ?", (ident,)).fetchone()
            return r["denominazione_id"] if r else None
        return None

    def _fratelli_leggibili(self, den_id: int | None, detto: str,
                            token: Sequence[str]) -> list:
        """Le tipologie di questa denominazione, del colore dichiarato, il cui
        nome si legge tutto sull'etichetta."""
        if den_id is None:
            return []
        atteso = [k for k, v in COLORE_UE.items() if v == detto]
        righe = self.con.execute(
            "SELECT t.id, r.testo, r.peso FROM tipologia t"
            " JOIN ricerca r ON r.ambito = 'tipologia' AND r.ambito_id = t.id"
            " WHERE t.denominazione_id = ? AND t.colore IN (%s)"
            % ",".join("?" * len(atteso)), (den_id, *atteso)).fetchall()
        return [r for r in righe if self._tutto_letto(r["testo"], token)]

    def _del_colore_dichiarato(self, f: Fatti, token: Sequence[str],
                               testo_norm: str, tetto: float) -> Fatti:
        """Se il colore scritto contraddice ancora, si cerca il fratello giusto.

        Il vincolo del colore si applica quando si sceglie fra i candidati, ma
        la cascata continua dopo: il produttore non letto fa scendere alla
        tipologia, la regola sul nome fa scendere ancora, e uno di quei gradini
        puo' essere di un altro colore. Per esempio, con un'etichetta che dice
        PROSECCO ROSE si puo' scendere a «Prosecco-Wine», che in archivio e'
        BIANCO, e il colore dichiarato si perde per strada.

        Qui si guarda fra le tipologie della STESSA denominazione - i fratelli
        - e si prende quella del colore giusto, se il suo nome si e' letto. Non
        si va a cercare altrove: cambiare denominazione sarebbe tornare a
        indovinare, e la denominazione qui si e' letta.
        """
        detto = self._colore_detto(token)
        if detto is None or f.denominazione is None:
            return f
        if f.colore is None or COLORE_UE.get(f.colore, f.colore) == detto:
            return f
        den = self.con.execute("SELECT id FROM denominazione WHERE nome = ?",
                               (f.denominazione,)).fetchone()
        for r in self._fratelli_leggibili(den["id"] if den else None, detto, token):
            fratello = self._componi(Candidato(ambito="tipologia", ambito_id=r["id"],
                                               testo=r["testo"], somiglianza=0.0,
                                               peso=r["peso"]))
            if fratello.livello is Livello.NULLA:
                continue
            fratello.sicurezza = min(tetto, self._sicurezza_verificata(
                Candidato(ambito="tipologia", ambito_id=r["id"], testo=r["testo"],
                          somiglianza=0.0, peso=r["peso"]), testo_norm))
            fratello.annata = f.annata
            log.info("colore dichiarato %s: da «%s» (%s) passo a «%s»",
                     detto, f.tipologia or f.denominazione, f.colore, r["testo"])
            return fratello
        return f

    def _non_oltre_cio_che_si_e_letto(self, f: Fatti, token: Sequence[str],
                                      testo_norm: str, tetto: float) -> Fatti:
        """Scende finche' il nome che si sta per dire non e' tutto sull'etichetta.

        È `_senza_produttore` applicata a ogni nome, non solo a quello della
        cantina: la stessa regola, portata fino in fondo. Se non regge nemmeno
        il gradino piu' generico, non si tace e non si inventa - si dice quel
        che c'e' scritto. Vedi `_solo_l_etichetta`.
        """
        for ambito, ident in self.catena_di_ripiego(f):
            r = self._voce_di_ricerca(ambito, ident)
            if r is None or not self._tutto_letto(r[0], token):
                continue
            if f.origine == (ambito, ident):
                return f
            sceso = self._componi(Candidato(ambito=ambito, ambito_id=ident,
                                            testo=r[0], somiglianza=0.0,
                                            peso=r[1]))
            if sceso.livello is Livello.NULLA:
                continue
            sceso.sicurezza = min(tetto, self._sicurezza_verificata(
                Candidato(ambito=ambito, ambito_id=ident, testo=r[0],
                          somiglianza=0.0, peso=r[1]), testo_norm))
            sceso.annata = f.annata
            log.info("«%s» non si e' letto per intero: si scende a %s «%s»",
                     f.nome or f.tipologia or f.denominazione, ambito, r[0])
            return sceso
        return self._solo_l_etichetta(f, token, tetto)

    def _solo_l_etichetta(self, f: Fatti, token: Sequence[str],
                          tetto: float) -> Fatti:
        """Quel che c'e' scritto sulla bottiglia, e nient'altro.

        L'ultimo gradino, e il piu' onesto: l'etichetta si e' letta benissimo e
        in archivio non c'e' niente che si possa nominare senza inventarlo.
        Restano le parole che dicono che TIPO di vino e' - spumante, metodo
        classico, rosato, brut - e quelle si possono ripetere, perche' le ha
        scritte il produttore.

        Non e' «non ce l'ho in archivio», che al tavolo non serve a nessuno, e
        non e' un vino inventato, che e' peggio. E' l'unica risposta vera che
        si puo' dare a una bottiglia che non conosciamo.
        """
        detto = self._colore_detto(token)
        parole = set(token)
        categoria = None
        for chiave, cat in CATEGORIA_DETTA.items():
            if chiave in parole:
                categoria = cat
                break
        # La sicurezza la decide QUANTO si e' letto, come per tutto il resto:
        # «e' uno spumante rosato» detto avendo letto una parola sola non e'
        # piu' solido di qualunque altra affermazione fatta su una parola sola.
        g = Fatti(livello=Livello.GENERICO, colore=detto, categoria=categoria,
                  annata=f.annata, sicurezza=min(tetto, SOGLIA_CERTA - 0.5))
        g.temperatura_c = TEMPERATURA_PER_CATEGORIA.get(categoria or "")
        # Le parole del tipo, nell'ordine in cui si dicono: «spumante metodo
        # classico rosato». Servono al narratore per aprire, e sono TUTTE
        # lette: nessuna viene da noi.
        g.qualificatori = [p for p in ORDINE_QUALIFICATORI if p in parole]
        log.info("niente da nominare: resto su quel che dice l'etichetta (%s)",
                 " ".join(g.qualificatori) or "nulla")
        return g

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
            r = self._voce_di_ricerca(ambito, ident)
            if r is None:
                continue
            generico.sicurezza = min(tetto, self._sicurezza_verificata(
                Candidato(ambito=ambito, ambito_id=ident, testo=r[0],
                          somiglianza=0.0, peso=r[1]), testo_norm))
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
    def _cantine_per_parola(self) -> dict[str, set[str]]:
        """Per ogni parola, quali produttori dell'archivio la portano.

        Serve a sapere se le parole che provano un produttore provano LUI o
        mezza Italia. «Palamà» sta in un nome di cantina solo; «Serra» in
        parecchi, e su «Serra dei Turchi · SANSILVESTRO · BAROLO» basterebbe a
        far dire «la cantina è Castel di Serra» - una parola del VINO che
        firmerebbe un produttore che non c'entra niente.
        """
        if self._per_parola is None:
            indice: dict[str, set[str]] = {}
            for (cantina,) in self.con.execute(
                    "SELECT DISTINCT cantina_norm FROM vino"
                    " WHERE cantina_norm IS NOT NULL AND cantina_norm <> ''"):
                for parola in set(cantina.split()):
                    indice.setdefault(parola, set()).add(cantina)
            self._per_parola = indice
        return self._per_parola

    @sotto_lucchetto
    def _parole_di_luogo(self) -> frozenset[str]:
        """Le parole che in archivio sono nomi di denominazione o di regione.

        Stanno sull'etichetta perche' dicono da dove viene il vino, non chi
        l'ha fatto, e quindi non possono provare un produttore.
        """
        if self._luoghi is None:
            parole: set[str] = set()
            for (nome,) in self.con.execute("SELECT nome_norm FROM denominazione"):
                parole.update((nome or "").split())
            for (regione,) in self.con.execute(
                    "SELECT DISTINCT regione FROM vino WHERE regione IS NOT NULL"):
                parole.update(normalizza(regione).split())
            self._luoghi = frozenset(p for p in parole if len(p) >= 4)
        return self._luoghi

    def _il_produttore_scritto(self, f: Fatti, candidati: list[Candidato],
                               testo_norm: str) -> Fatti:
        """Il produttore si dice se lo si e' letto, anche se il vino non si sa.

        Sull'etichetta il nome della cantina e' la cosa piu' identificante che
        ci sia: in archivio ci sono 6.168 produttori e 19.602 vini, e le
        etichette di prova lo fanno leggere bene nell'81% dei casi. Eppure,
        quando la cascata scende sotto il vino, il produttore uscirebbe dai
        fatti insieme al vino che non si e' riconosciuto.

        Un esempio, su una bottiglia vera: «ALBAROSSA NEGROAMARO PALAMÀ
        VINICOLA DEL SALENTO». «Palamà» si legge benissimo e ha tre vini in
        archivio, ma il record vincente e' il Negroamaro di un ALTRO
        produttore, che ha due parole generiche tutte lette mentre il record
        giusto ne ha cinque di cui l'OCR legge solo «Palamà» (il nome del vino
        e' in un carattere decorativo che non si legge mai). Senza questo
        passaggio il dispositivo direbbe soltanto «Questo è un Salento».

        Qui non si sceglie un vino: si aggiunge un fatto che e' scritto sulla
        bottiglia. La prova e' la stessa che serve per nominarlo accanto a un
        vino - `_prova_del_produttore`, cioe' le parole che il produttore ha
        di suo - e si tace se i produttori che reggono quella prova sono piu'
        d'uno, perche' allora non si sa di chi sia.
        """
        if f.cantina or f.livello is Livello.NULLA:
            return f
        parole = parole_utili(testo_norm)
        if not parole:
            return f
        norme = self._norme_vino([c.ambito_id for c in candidati
                                  if c.ambito == "vino"])
        # Le parole che stanno nel NOME di un vino candidato sono sull'etichetta
        # come parole del vino, non come firma. «Bellavista» e «Cerequio» sono
        # vigne, «Morra» un paese, e tutti e tre sono anche nomi di cantine
        # altrui: su un Castello di Ama uscirebbe «la cantina è Bellavista».
        # E' la regola che vale gia' accanto a un vino - il produttore non si
        # fa confermare dalle parole del vino - portata dove il vino non si sa.
        dei_vini = {x for nome, _, _ in norme.values() for x in nome.split()}
        # La soglia e' piu' alta di `RISCONTRO_PAROLA`, e non per prudenza
        # generica: questo nome verra' DETTO. Con la soglia normale «Santoro»
        # si farebbe confermare da «Salento» - settantuno punti di pura
        # aritmetica delle lettere - e basterebbe a rendere ambiguo un «Palamà»
        # letto a cento.
        trovati: dict[str, float] = {}
        for _, cantina, denominazione in norme.values():
            if not cantina or cantina in trovati:
                continue
            # Qui la prova si stringe due volte rispetto a `_prova_del_produttore`,
            # perche' qui il nome esce da solo, senza un vino accanto.
            #
            # Le parole devono essere PAROLE: a «Cantina del Nebbiolo», tolte
            # quelle della sua denominazione e quelle che stanno su ogni
            # bottiglia, resta «del» - un articolo, che su un'etichetta che
            # dice «Barolo DEL Comune di Serralunga» si ritrova a cento.
            #
            # E non devono stare sull'etichetta per un ALTRO motivo. «Vigneti
            # del Salento» si farebbe provare da «salento», che c'e' come
            # indicazione geografica; «Ca'Delle Rose» da «rose», che c'e'
            # perche' la bottiglia dichiara il proprio colore - su
            # «Leggiadro · Brut Rosé · METODO CLASSICO».
            #
            # `PAROLE_GENERICHE` e' gia' l'elenco di cio' che non identifica
            # un vino, e una parola che non identifica un vino non puo'
            # identificare chi l'ha fatto. I luoghi si aggiungono perche'
            # `_prova_del_produttore` toglie solo quelli della denominazione
            # di QUEL record, e un record senza denominazione non ne toglie
            # nessuno.
            prova = [x for x in self._prova_del_produttore(cantina, denominazione)
                     if len(x) >= 4 and x not in PAROLE_GENERICHE
                     and x not in dei_vini
                     and x not in self._parole_di_luogo()]
            if not prova:
                continue
            # E devono provare LUI: se le stesse parole stanno anche nel nome
            # di un altro produttore, non firmano nessuno.
            indice = self._cantine_per_parola()
            insieme = set.intersection(*(indice.get(x, set()) for x in prova))
            if insieme != {cantina}:
                continue
            punti = self._copertura(" ".join(prova), parole)
            if punti >= PRODUTTORE_SCRITTO:
                trovati[cantina] = punti
        if len(trovati) != 1:
            return f
        riga = self.con.execute(
            "SELECT cantina FROM vino WHERE cantina_norm = ? LIMIT 1",
            (next(iter(trovati)),)).fetchone()
        if riga and riga["cantina"]:
            f.cantina = riga["cantina"]
            log.info("il produttore e' scritto sull'etichetta: %r", f.cantina)
        return f

    @sotto_lucchetto
    def fatti_di(self, ambito: str, ambito_id: int) -> Fatti:
        """I fatti di un record preciso, senza ripassare dalla ricerca.

        E' quello che serve quando qualcuno sceglie un vino nell'editor delle
        correzioni: ha scelto UN record, e va composto quello, non il piu'
        somigliante al suo nome.
        """
        f = self._componi(Candidato(ambito=ambito, ambito_id=ambito_id,
                                    testo="", somiglianza=0.0, peso=0))
        # L'ha scelto una persona guardando la bottiglia: e' la conferma piu'
        # forte che il dispositivo possa ricevere.
        f.sicurezza = 100.0
        f.origine = f.origine or (ambito, ambito_id)
        f.ripiego = self.catena_di_ripiego(f)
        return f

    @sotto_lucchetto
    def il_piu_generico(self, f: Fatti, righe: Sequence[str]) -> Fatti:
        """Con un riconoscimento dubbio, il candidato meno specifico.

        Non si mostrano i candidati chiedendo all'ospite quale sia: una
        schermata con tre nomi quasi uguali, a un tavolo, a chi non ha chiesto
        niente, non aiuta. Si sceglie da soli, e si sceglie cio' che si puo'
        sostenere: fra il primo classificato e le alternative, quello piu' in
        basso nella scala `GENERALITA` - una denominazione invece di un vino
        preciso. A parita' di livello resta il primo classificato.

        Un caso a parte: tutti vini, e di produttori diversi. Li' il dubbio e'
        proprio il nome della cantina - «due produttori a pari evidenza» - e
        il gradino piu' generico e' lo stesso vino senza produttore, come
        quando la cantina non si legge (`_senza_produttore`).
        """
        livello, scelta = f.livello, None
        for ambito, ident in f.riferimenti:
            suo = LIVELLO_DELL_AMBITO.get(ambito)
            if suo is not None and GENERALITA[suo] > GENERALITA.get(livello, -1):
                livello, scelta = suo, (ambito, ident)
        if scelta is not None:
            g = self.fatti_di(*scelta)
            # Scelto da noi, non da una persona: la sicurezza resta quella del
            # riconoscimento, e l'annata viene comunque dall'etichetta.
            g.sicurezza = f.sicurezza
            g.annata = f.annata
            g.candidati, g.riferimenti = f.candidati, f.riferimenti
            log.info("dubbio: dico il meno specifico, %s invece di %s",
                     g.livello.value, f.livello.value)
            return g
        if (f.livello is Livello.VINO and f.cantina and f.origine
                and f.origine[0] == "vino" and self._altri_produttori(f)):
            testo = " ".join(righe)
            token = parole_utili(testo)
            tetto = (TETTO_PER_PAROLE[len(token)] if len(token) < len(TETTO_PER_PAROLE)
                     else math.inf)
            g = self._senza_produttore(f, normalizza(testo), tetto)
            g.annata = f.annata
            g.produttore_letto_davvero = False
            g.candidati, g.riferimenti = f.candidati, f.riferimenti
            g.ripiego = self.catena_di_ripiego(g)
            return g
        return f

    def _altri_produttori(self, f: Fatti) -> bool:
        """Fra le alternative c'e' un vino di un'altra cantina?"""
        vini = [i for a, i in f.riferimenti if a == "vino"]
        if not vini:
            return False
        norme = self._norme_vino([f.origine[1], *vini])
        mia = norme.get(f.origine[1], ("", "", ""))[1]
        return bool(mia) and any(
            norme.get(i, ("", "", ""))[1] not in ("", mia) for i in vini)

    # Cosa si puo' scegliere nell'editor delle correzioni: le bottiglie, cioe'
    # i vini, le tipologie e le denominazioni. Il vitigno no: e' un'uva, e dire
    # che un'etichetta «e'» il Nebbiolo non e' riconoscerla.
    AMBITI_SCEGLIBILI = ("vino", "tipologia", "denominazione")

    @sotto_lucchetto
    def suggerisci(self, testo: str, quanti: int = 5) -> list[tuple[str, int, str]]:
        """Le bottiglie dell'archivio il cui nome comincia come si sta scrivendo.

        Serve al campo titolo dell'editor delle correzioni: a ogni lettera si
        propongono i nomi che la contengono, l'ultima parola presa come
        inizio di parola («barolo cann» trova «Cannubi Barolo»). Prima i nomi
        che cominciano proprio cosi', poi i piu' corti - «Barolo» prima dei
        duecento Barolo di un produttore - e a parita' l'ordine di FTS5.

        Restituisce (ambito, id, come si scrive a schermo). Sotto il
        millisecondo sull'indice di diciannovemila vini.
        """
        parole = normalizza(testo).split()
        if not parole:
            return []
        termini = [f'"{p}"' for p in parole[:-1]] + [f'"{parole[-1]}"*']
        try:
            righe = self.con.execute(
                "SELECT testo, ambito, ambito_id FROM ricerca"
                " WHERE ricerca MATCH ? ORDER BY bm25(ricerca) LIMIT 80",
                (" AND ".join(termini),)).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("suggerimenti: query rifiutata (%s): %r", e, testo)
            return []
        inizio = " ".join(parole)
        adatte = [(r["testo"], r["ambito"], r["ambito_id"], i) for i, r in enumerate(righe)
                  if r["ambito"] in self.AMBITI_SCEGLIBILI]
        adatte.sort(key=lambda r: (not r[0].startswith(inizio), len(r[0].split()), r[3]))
        fuori, visti = [], set()
        for _testo, ambito, ident, _i in adatte:
            nome = self.etichetta(ambito, ident)
            if nome and nome not in visti:
                visti.add(nome)
                fuori.append((ambito, ident, nome))
            if len(fuori) >= quanti:
                break
        return fuori

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
        # e cosi' fa 100 anche "Monte Giove" contro "Monte Antico". Ma la
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
        # viene verificato conserva quello gonfiato. Fermandosi ai primi 25,
        # il 26esimo, mai verificato, potrebbe scavalcare tutti dopo il
        # riordino e presentarsi come "certo" senza aver mai superato
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
        Tenuta Rocca, il record giusto "tenuta rocca barolo bussia" prende
        58.8 per quella e sola nel nome della cantina, mentre il record povero
        "rocca rocca" - un altro produttore - prende 100 perche' la sua unica
        parola c'e' esatta. Il piu' informativo perde contro il piu' vago.

        Qui ogni parola del record cerca il suo miglior riscontro fra quelle
        lette, e il punteggio e' la media: un refuso costa una parola, non
        tutto il record.
        """
        from rapidfuzz import fuzz

        parole = record.split()
        if not parole or not parole_ocr:
            return fuzz.token_set_ratio(" ".join(parole_ocr), record)
        # Ogni parola letta puo' confermarne UNA sola del record. Senza questo,
        # "Ca'Stella" si accontenterebbe della "Stella Polare" stampata sulla
        # retroetichetta di un Burlotto e si dichiarerebbe certa.
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
        il produttore dalle parole del vino: «Barolo del Comune di Serralunga
        d'Alba» verrebbe dichiarato CERTO come Barolo di Terre del Barolo con
        88, da un'etichetta che il produttore non lo nomina.

        Restano le parole che il produttore ha di suo: via quelle della
        denominazione e via quelle che stanno su ogni bottiglia (`tenuta`,
        `cantina`, `azienda`, `podere`... - la lista e' `PAROLE_VUOTE`).

        La denominazione, e NON il nome del vino. Sembra equivalente e non lo
        e': in archivio moltissimi nomi contengono gia' il produttore -
        «Giovanni Allegrini Recioto della Valpolicella» - e togliere le parole
        del nome cancellerebbe proprio quelle che identificano la cantina.
        Misurato: escludendo il nome resterebbero senza prova 164 cantine, fra
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
        parole che sono del vino: «BAROLO» stampato sull'etichetta proverebbe
        insieme il vino «Barolo» e il produttore «Terre del Barolo», due
        conferme che ne sono una sola. Il produttore si misura solo sulle
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
            # farebbe confermare da «VOL» della gradazione alcolica - 75 su 100
            # per pura aritmetica delle lettere - e «Cantine Volpi» finirebbe
            # sull'etichetta di un Piemonte Cortese che non la nomina.
            prova = self._prova_del_produttore(cantina, denominazione)
            if not prova or self._copertura(
                    " ".join(prova), parole_utili(testo_norm)) < RISCONTRO_PAROLA:
                c.produttore_letto = False
                return s_nome * 0.8
            # Poi la domanda di grado, e quella si misura sul nome INTERO. Le
            # parole deboli devono diluire: filtrandole si finirebbe per
            # premiare i nomi poveri, e «Ca'Stella» si dichiarerebbe certo con
            # 92 sulla «Stella Polare» di una retroetichetta altrui.
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

        Un `KeyError` qui non cadrebbe su una riga qualsiasi: `_componi` gira
        nel thread di lavoro, quindi l'eccezione diventerebbe una schermata di
        guasto davanti all'ospite. Basterebbe ricostruire l'indice di ricerca
        con un ambito in piu' - una tabella nuova, un prodotto da scaffale - e
        ogni bottiglia che ci finisca sopra manderebbe il dispositivo in errore.

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
        # La temperatura di servizio la decide la CATEGORIA, e va messa QUI e
        # non dentro alla nota del vitigno: li' un Marsala senza nota d'uva
        # resterebbe senza temperatura pur sapendo benissimo di essere un
        # liquoroso. E' un fatto della categoria, non dell'uva, e non dipende
        # da cos'altro sappiamo di quel vino.
        f.temperatura_c = f.temperatura_c or TEMPERATURA_PER_CATEGORIA.get(
            f.categoria or "")
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
        chiave = (den_id, nome_norm)
        if chiave not in self._tipologie:
            self._tipologie[chiave] = self._cerca_tipologia(den_id, nome_norm)
        return self._tipologie[chiave]

    # Il colore scritto nel nome del vino: «Franciacorta Rosé», «Lambrusco
    # Frizzante Rosato Dolce». Le forme inglesi e francesi ci sono perche'
    # stanno sulle etichette da esportazione.
    #
    # «rosa» NON c'e' di proposito: il Moscato Rosa e' un'uva, e il suo vino
    # e' rosso. E prima di cercare si tolgono i nomi dei vitigni, perche'
    # «Pinot Nero Brut» e' uno spumante BIANCO fatto con un'uva nera.
    _COLORE_NEL_NOME = {"rosso": "Rosso", "red": "Rosso",
                        "bianco": "Bianco", "blanc": "Bianco", "blancs": "Bianco",
                        "white": "Bianco",
                        "rosato": "Rosato", "rose": "Rosato", "rosati": "Rosato"}
    _PAROLA_DI_COLORE = re.compile(
        r"\b(" + "|".join(_COLORE_NEL_NOME) + r")\b")

    def _colore_scritto_nel_nome(self, nome_norm: str) -> str | None:
        """Il colore che il nome dichiara, o None se non ne dichiara uno solo.

        «Terre Bianche Rosso» ne dichiara due e non vale: quando le famiglie
        sono piu' d'una non si sceglie, si tace.
        """
        resto = f" {nome_norm} "
        for v in self._vitigni_noti():
            resto = resto.replace(f" {v} ", " ")
        trovate = {self._COLORE_NEL_NOME[x] for x in self._PAROLA_DI_COLORE.findall(resto)}
        return trovate.pop() if len(trovate) == 1 else None

    # Le parole con cui un nome dichiara di avere le bolle. «Prosecco» non
    # c'e': e' il nome della denominazione, e il Prosecco tranquillo esiste.
    _DICE_LA_BOLLA = re.compile(
        r"\b(?:spumante|frizzante|brut|extra dry|metodo classico|millesimato|"
        r"pas dose|dosaggio zero|nature|sekt|cremant|saten|perlage|charmat)\b")
    _CATEGORIE_CON_LE_BOLLE = ("Sparkling Wine", "Quality Sparkling Wine",
                               "Quality Aromatic Sparkling Wine",
                               "Semi-Sparkling Wine", "Aerated Semi-Sparkling Wine")

    @sotto_lucchetto
    def _cerca_tipologia(self, den_id: int, nome_norm: str) -> int | None:
        from rapidfuzz import fuzz

        with self._db:
            righe = self.con.execute(
                "SELECT id, nome_norm, colore, categoria"
                " FROM tipologia WHERE denominazione_id = ?",
                (den_id,)).fetchall()
        if not righe:
            return None
        # Se il nome dichiara un colore, una tipologia d'altro colore non e'
        # questo vino. Senza questo filtro, con una sola tipologia la si
        # prenderebbe senza nemmeno confrontare: «Franciacorta Rosé» si
        # aggancerebbe al Franciacorta bianco, e da li' prenderebbe colore,
        # categoria e citazione del disciplinare - la descrizione di un altro
        # vino, letta a voce con sicurezza. In archivio: 216 vini su 2.279 col
        # colore scritto nel nome ne riceverebbero uno diverso.
        if (detto := self._colore_scritto_nel_nome(nome_norm)):
            righe = [r for r in righe
                     if COLORE_UE.get(r["colore"] or "") in (detto, None)]
            if not righe:
                return None
        # E se il nome dice che ha le bolle, fra i fratelli si preferisce chi
        # le ha. Altrimenti «Prestige Collection Brut Prosecco Treviso» si
        # prenderebbe «Prosecco-Wine», che e' il Prosecco FERMO, perche'
        # somiglia di piu' - e la denominazione ha «Prosecco Spumante» proprio
        # li' accanto. In archivio: 986 bollicine con la citazione di un vino
        # fermo.
        #
        # Si preferisce, non si pretende: molte denominazioni una tipologia
        # con le bolle non ce l'hanno, e restare senza tipologia costa piu' di
        # quel che si guadagna (vedi `_del_colore_giusto`).
        if self._DICE_LA_BOLLA.search(nome_norm):
            con_bolle = [r for r in righe
                         if r["categoria"] in self._CATEGORIE_CON_LE_BOLLE
                         or self._DICE_LA_BOLLA.search(r["nome_norm"] or "")]
            righe = con_bolle or righe
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
    def _prodotto_diverso(nome: str, categoria: str | None = None) -> frozenset[str]:
        dentro = f" {normalizza(nome)} "
        q = {p for p in PRODOTTO_DIVERSO if f" {p} " in dentro}
        segno = QUALIFICATORE_DI_CATEGORIA.get(categoria or "")
        if segno in PRODOTTO_DIVERSO:
            q.add(segno)
        return frozenset(q)

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
        ci sono tutte. Misurato: 729 abbinamenti su 3.315 finirebbero su un
        vino di un altro colore.

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

        # Prima di tutto il resto: quel che non e' lo stesso prodotto esce, e
        # se non resta niente si tace. Meglio nessuna citazione che quella di
        # un altro vino.
        mio_tipo = self._prodotto_diverso(nome, categoria)
        righe = [r for r in righe if self._prodotto_diverso(
            f"{_nome_leggibile(r)} {r['menzione'] or ''}") == mio_tipo]
        if not righe:
            return None

        # Il nome identico vale piu' di ogni restrizione, ma solo se e'
        # affidabile: un nome ricostruito o numerato coincide per costruzione,
        # non perche' dica qualcosa.
        mio = normalizza(nome)
        uguali = [r for r in righe
                  if not r["nome_incerto"] and normalizza(_nome_leggibile(r)) == mio]
        if len({_confronto(r) for r in uguali}) == 1:
            return _citazioni_utili(uguali[0]), _nome_leggibile(uguali[0])

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
            # Il colore vero, non la colonna `tipo`: vedi `FAMIGLIA_DAL_TIPO`.
            # `_colore_di` prende quello della tipologia, che viene dal
            # registro UE, e ripiega sul tipo solo quando quello e' un colore.
            colore=self._colore_di("vino", vid),
            corpo=r["corpo"], acidita=r["acidita"],
            elaborazione=r["elaborazione"], abv=r["abv"],
        )
        f.categoria = self._categoria_del_vino(r)
        f.vitigni = [x[0] for x in self.con.execute(
            "SELECT vi.nome FROM vino_vitigno vv JOIN vitigno vi ON vi.id = vv.vitigno_id"
            " WHERE vv.vino_id = ?" + _SENZA_VITIGNI_FINTI + " ORDER BY vi.nome", (vid,))]
        f.abbinamenti = [x[0] for x in self.con.execute(
            "SELECT abbinamento FROM vino_abbinamento WHERE vino_id = ? LIMIT 6", (vid,))]
        # Col colore vero e la categoria, il registro dice la sua anche sugli
        # spumanti e sui dessert.
        if not f.regione and r["denominazione_id"]:
            d = self.con.execute("SELECT regione FROM denominazione WHERE id = ?",
                                 (r["denominazione_id"],)).fetchone()
            f.regione = d["regione"] if d else None
        self._aggiungi_disciplinare(f, r["denominazione_id"], r["nome"],
                                    f.colore, f.categoria)
        self._aggiungi_nota_vitigno(f)
        f.temperatura_c = f.temperatura_c or TEMPERATURA_PER_CATEGORIA.get(
            f.categoria or "")
        return f

    def _categoria_del_vino(self, r) -> str | None:
        """La categoria UE di un vino: la famiglia la dice X-Wines, il membro
        della famiglia lo dice il registro, e solo se i due concordano."""
        famiglia = FAMIGLIA_DAL_TIPO.get(r["tipo"] or "")
        if not famiglia:
            return None
        if r["denominazione_id"]:
            tid = self._tipologia_del_vino(r["denominazione_id"], r["nome_norm"])
            if tid is not None:
                riga = self.con.execute(
                    "SELECT categoria FROM tipologia WHERE id = ?", (tid,)).fetchone()
                if riga and riga["categoria"] in famiglia:
                    return riga["categoria"]
        # Il registro non concorda o non sa: resta la famiglia, nella sua
        # forma piu' generica, che e' vera per costruzione. Per i dessert non
        # c'e' una forma generica onesta - passito, stramaturo e liquoroso
        # sono tre cose diverse - e allora si tace.
        return famiglia[0] if famiglia[0].endswith("Sparkling Wine") else None

    @sotto_lucchetto
    def _fatti_tipologia(self, tid: int) -> Fatti:
        r = self.con.execute(
            "SELECT t.*, d.nome AS den_nome, d.tipo AS den_tipo, d.regione AS den_regione"
            " FROM tipologia t JOIN denominazione d ON d.id = t.denominazione_id"
            " WHERE t.id = ?", (tid,)
        ).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.TIPOLOGIA,
            tipologia=r["nome"], denominazione=r["den_nome"],
            tipo_denominazione=r["den_tipo"], regione=r["den_regione"],
            colore=r["colore"], categoria=r["categoria"],
        )
        # Solo i principali finiscono nei fatti raccontabili. Gli ammessi si
        # tengono da parte per poterli ESCLUDERE in verifica, non per dirli.
        for ruolo, dove in (("principale", f.vitigni), ("ammesso", f.vitigni_ammessi)):
            dove.extend(x[0] for x in self.con.execute(
                "SELECT vi.nome FROM tipologia_vitigno tv"
                " JOIN vitigno vi ON vi.id = tv.vitigno_id"
                " WHERE tv.tipologia_id = ? AND tv.ruolo = ?" + _SENZA_VITIGNI_FINTI
                + " ORDER BY " + _USO_NEI_VINI + " DESC, vi.nome",
                (tid, ruolo, r["denominazione_id"])))
        self._aggiungi_disciplinare(f, r["denominazione_id"], r["nome"],
                                    r["colore"], r["categoria"])
        self._aggiungi_nota_vitigno(f)
        return f

    @sotto_lucchetto
    def _fatti_denominazione(self, did: int) -> Fatti:
        r = self.con.execute(
            "SELECT nome, tipo, regione FROM denominazione WHERE id = ?", (did,)).fetchone()
        if not r:
            return Fatti()
        f = Fatti(
            livello=Livello.DENOMINAZIONE,
            denominazione=r["nome"], tipo_denominazione=r["tipo"],
            # La regione sta in tabella per 375 denominazioni su 532, ed e' il
            # fatto che manca proprio dove il modello inventa: «Catarratto, un
            # grande abruzzese del Piemonte».
            regione=r["regione"],
        )
        # La categoria si prende dalle tipologie, ma SOLO se sono unanimi: un
        # Marsala e' liquoroso in tutte e quindici le sue, e dirlo non e'
        # un'ipotesi. L'Asti invece e' meta' fermo e meta' spumante, e li' una
        # maggioranza sceglierebbe per conto suo. Sono 219 denominazioni su
        # 532, e serve alla temperatura di servizio: senza, un Marsala perde
        # la sua e si ritrova quella dell'uva.
        cat = self.con.execute(
            "SELECT categoria FROM tipologia WHERE denominazione_id = ?"
            " GROUP BY categoria", (did,)).fetchall()
        if len(cat) == 1 and cat[0]["categoria"]:
            f.categoria = cat[0]["categoria"]
        # Il colore con lo stesso criterio: solo se tutte le tipologie lo
        # condividono. Senza, un Vermentino di Gallura al livello denominazione
        # non avrebbe colore, e il verificatore lascerebbe passare un modello
        # che lo descrive «di colore rubino».
        f.colore = self._colore_di("denominazione", did)
        # E col colore arriva la citazione del registro, che altrimenti a
        # questo gradino non arriverebbe mai: `_disciplinare` sceglie la
        # tipologia che combacia per colore e qualificatori, e un colore
        # unanime la identifica. Su una denominazione che fa rossi e bianchi
        # il colore non e' unanime, non c'e' colore, e non c'e' citazione:
        # com'e' giusto.
        self._aggiungi_disciplinare(f, did, r["nome"], f.colore)
        # Un vitigno vale come "principale della denominazione" solo se lo e' per
        # la maggioranza delle sue tipologie: altrimenti si finirebbe per
        # attribuire al Chianti generico i vitigni di una sua versione rara.
        f.vitigni = [x[0] for x in self.con.execute(
            "SELECT vi.nome FROM tipologia_vitigno tv"
            " JOIN vitigno vi ON vi.id = tv.vitigno_id"
            " JOIN tipologia t ON t.id = tv.tipologia_id"
            " WHERE t.denominazione_id = ? AND tv.ruolo = 'principale'"
            + _SENZA_VITIGNI_FINTI +
            " GROUP BY vi.id"
            " HAVING count(*) >= (SELECT count(*) FROM tipologia WHERE denominazione_id = ?) / 2.0"
            " ORDER BY " + _USO_NEI_VINI + " DESC, count(*) DESC, vi.nome LIMIT 5",
            (did, did, did))]
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
        # Il colore della bacca DEVE esserci: senza, il modello puo' scrivere
        # che la Falanghina - vitigno a bacca bianca - e' «un vino rosso» con
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
        # La temperatura dell'uva vale solo per un vino FERMO. Uno spumante di
        # Pinot Nero non si serve alla temperatura di un Pinot Nero: vedi
        # TEMPERATURA_PER_CATEGORIA, e il Trentodoc rosato a quindici gradi.
        della_categoria = TEMPERATURA_PER_CATEGORIA.get(f.categoria or "")
        f.temperatura_c = f.temperatura_c or della_categoria or r["temperatura_c"]
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
