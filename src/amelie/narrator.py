"""Il racconto: dai fatti alla prosa, senza inventare.

Un modello da 0,8 miliardi di parametri non sa nulla di vino. Se gli si chiede
di raccontare un Sagrantino, inventa premi, punteggi e note di degustazione che
suonano benissimo e sono false. In sala, davanti a un ospite, è una figuraccia.

Per questo il modello **non è la fonte dei fatti, è solo lo stile**. Tutto ciò
che il racconto afferma viene da `Fatti`, e ciò che non c'è nei fatti non si
dice. La difesa è a quattro strati, in ordine di costo crescente:

1. **Testo pre-generato.** Per ciò che il database conosce già, il racconto è
   stato scritto una volta e riletto. Latenza zero, rischio zero.
2. **Generazione dal vivo vincolata.** Per l'ignoto: il modello riceve solo il
   blocco dei fatti e un divieto esplicito di aggiungerne. ~20 secondi.
3. **Verifica deterministica.** Ogni numero e ogni nome proprio del testo
   generato deve comparire nei fatti. Se non ci compare, il testo si scarta.
   Questa non è una preferenza espressa nel prompt: è un controllo in Python
   che il modello non può aggirare.
4. **Template.** Frasi concatenate dai campi del database, senza modello. È
   l'unica cosa che garantisce che il dispositivo dica qualcosa di vero anche
   se tutto il resto fallisce.

Il tono cambia con il livello raggiunto dalla cascata: sotto il primo gradino
non si attribuisce mai a un produttore sconosciuto ciò che non si è verificato.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .lessico import Lessico, carica, elenca_in_lingua
from .matcher import SOGLIA_DUBBIA, Fatti, Livello

log = logging.getLogger(__name__)

# Un racconto piu' lungo di così non lo ascolta nessuno in piedi davanti a un
# tavolo, e ogni parola in piu' costa ~0,2 s di generazione sui Cortex-A53.
PAROLE_MAX = 130


@dataclass
class Racconto:
    testo: str
    origine: str          # 'cache' | 'modello' | 'template'
    livello: Livello
    verificato: bool = True

    @property
    def frasi(self) -> list[str]:
        """Spezza in frasi, che è l'unità con cui il TTS può iniziare a parlare
        prima che il testo sia finito."""
        return spezza_in_frasi(self.testo)


# Si spezza dopo un punto SOLO se quello che segue comincia come una frase:
# maiuscola, virgoletta o parentesi. Altrimenti «Un Barolo D.O.C.G. del 2016»
# si spaccava dentro la sigla e ne usciva un frammento che comincia in
# minuscolo - una pausa sbagliata nella voce, e una didascalia a meta'.
_FINE_FRASE = re.compile(r"""(?<=[.!?…])\s+(?=[A-ZÀ-Ý«"“'(])""")


def spezza_in_frasi(testo: str) -> list[str]:
    """La frase è l'unità con cui il dispositivo parla e con cui si legge.

    Serve in due posti: al racconto, che comincia a parlare prima di aver
    finito di scrivere, e alla didascalia, che deve cambiare quando cambia la
    voce e non prima.

    Diverso da `a_frasi`, che fa lo stesso su un FLUSSO di token mentre il
    modello scrive: qui il testo c'è già tutto.
    """
    return [f.strip() for f in _FINE_FRASE.split(testo) if f.strip()]


# ---------------------------------------------------------------- verifica

_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
# Un nome proprio: maiuscola iniziale, almeno tre lettere, non a inizio frase.
_PROPRIO = re.compile(r"(?<![.!?…]\s)(?<!^)\b([A-ZÀ-Ý][a-zà-ÿ']{2,})\b")

# Parole che iniziano per maiuscola senza essere nomi propri di vino: mesi,
# regioni generiche del discorso, e l'inizio di ogni frase.
_MAIUSCOLE_INNOCENTI = frozenset("""
    Il Lo La I Gli Le Un Uno Una Questo Questa Queste Questi Nel Nella Nelle Nei
    Dal Dalla Dalle Dai Del Della Delle Dei Con Per Tra Fra Ma Se Come Quando
    Dove Ogni Anche Ancora Oggi Qui Si No Non Suo Sua Sue Suoi Loro
    Gennaio Febbraio Marzo Aprile Maggio Giugno Luglio Agosto Settembre Ottobre
    Novembre Dicembre Italia Italiano Italiana
""".split())


def _senza_accenti(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def verifica(testo: str, fatti: Fatti) -> tuple[bool, list[str]]:
    """Il testo afferma solo cose presenti nei fatti?

    Restituisce (va bene, elenco delle invenzioni). Il controllo è volutamente
    grossolano ma **deterministico**: cerca numeri e nomi propri che non
    compaiano da nessuna parte nel blocco dei fatti. Preferisce un falso
    allarme — che costa una rigenerazione — a una bugia detta all'ospite.

    >>> f = Fatti(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi")
    >>> verifica("Il Cannubi di Marchesi.", f)[0]
    True
    >>> verifica("Il Cannubi ha vinto tre stelle Gambero Rosso.", f)[0]
    False
    """
    ammesso = _senza_accenti(
        " ".join(filter(None, [
            fatti.blocco_fatti(),
            " ".join(fatti.vitigni),
            fatti.note_vitigno or "",
            fatti.denominazione or "",
            fatti.tipologia or "",
            fatti.nome or "",
            fatti.cantina or "",
            fatti.regione or "",
            str(fatti.annata or ""),
            fatti.temperatura_c or "",
            " ".join(fatti.note_sensoriali),
        ]))
    )
    invenzioni = []

    for m in _NUMERO.finditer(testo):
        n = m.group(0).replace(",", ".")
        if n not in ammesso and n.replace(".", ",") not in ammesso:
            invenzioni.append(n)

    for m in _PROPRIO.finditer(testo):
        parola = m.group(1)
        if parola in _MAIUSCOLE_INNOCENTI:
            continue
        if _senza_accenti(parola) not in ammesso:
            invenzioni.append(parola)

    # Contraddizioni di colore. Sono l'errore che si nota di piu' e il piu'
    # facile da intercettare: se i fatti dicono bianco e il testo dice rosso,
    # e' falso e basta. Un modello piccolo ci casca spesso, perche' "vino" e
    # "rosso" stanno vicini nella sua testa.
    if contraddizione := _colore_sbagliato(testo, fatti):
        invenzioni.append(contraddizione)

    # Le quattro classi che seguono sono uscite da una rilettura dei testi del
    # modello addestrato: passavano tutte, e cio' che la verifica non vede
    # diventa un'abitudine del modello.
    invenzioni.extend(_gradi_sbagliati(testo, fatti))
    if "disciplinar" in _senza_accenti(testo) and not fatti.disciplinare:
        invenzioni.append("disciplinare invocato senza citazioni")
    invenzioni.extend(_cibi_inventati(testo, ammesso))
    invenzioni.extend(_provenienze_inventate(testo, ammesso))

    return (not invenzioni), invenzioni


# I numeri che il modello addestrato dice a voce sono scritti in lettere - e'
# cosi' che il corpus glieli ha insegnati, perche' una voce sintetica legge
# «17-19» come «diciassette trattino diciannove». Il controllo sulle cifre non
# li vedeva. Si guardano solo nelle frasi che parlano di gradi: «due vitigni»
# e' un conteggio, non un fatto da verificare.
_IN_LETTERE = {
    "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "undici": 11, "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15,
    "sedici": 16, "diciassette": 17, "diciotto": 18, "diciannove": 19, "venti": 20,
}
_NUMERO_IN_LETTERE = re.compile(
    r"\b(" + "|".join(sorted(_IN_LETTERE, key=len, reverse=True)) + r")\b(\s+gradi)?(\s+e\s+mezzo)?",
    re.I)


def _gradi_sbagliati(testo: str, fatti: Fatti) -> list[str]:
    """Gradazione e temperatura dette in lettere, confrontate coi fatti.

    Un intervallo si dice coi suoi estremi: «fra i sedici e i diciotto». Il
    punto medio - «diciassette» - non e' scritto da nessuna parte, e il mezzo
    grado va confrontato come mezzo: «tredici gradi e mezzo» di un 12,5% e'
    sbagliato anche se l'intero torna."""
    permessi: set[float] = set()
    if fatti.abv:
        permessi.add(float(fatti.abv))
    for n in re.findall(r"\d+(?:[.,]\d+)?", fatti.temperatura_c or ""):
        permessi.add(float(n.replace(",", ".")))
    if not permessi:
        return []
    fuori = []
    for frase in spezza_in_frasi(testo):
        if "grad" not in _senza_accenti(frase):
            continue
        for m in _NUMERO_IN_LETTERE.finditer(_senza_accenti(frase)):
            detto = _IN_LETTERE[m.group(1).lower()] + (0.5 if m.group(3) else 0.0)
            if detto not in permessi:
                fuori.append(f"{m.group(0).strip()} (nei fatti: "
                             f"{', '.join(f'{p:g}' for p in sorted(permessi))})")
    return fuori


_CIBI = re.compile(
    r"\b(manzo|agnello|maiale|vitello|pollame|pollo|cacciagione|selvaggina|salumi|"
    r"formagg\w*|pesc[ei]|crostacei|molluschi|frutti di mare|antipasti|stuzzichini|"
    r"risott\w*|zupp[ae]|verdure|dolci|pasticceria|dessert|cioccolato|funghi|tartufo|"
    r"pizza|carni? (?:rosse|bianche)|arrost\w*|brasat\w*|grigliat\w+|ostriche|"
    r"primi piatti|pasta)\b", re.I)


def _cibi_inventati(testo: str, ammesso: str) -> list[str]:
    """Abbinamenti che i fatti non danno: «formaggi» nei fatti copre
    «formaggio» nel testo, per questo si confronta la radice."""
    return [m.group(0) for m in _CIBI.finditer(_senza_accenti(testo))
            if m.group(0)[:5] not in ammesso]


# Un modello piccolo non sa da dove venga un vitigno, ma impara benissimo la
# forma «il vitigno <aggettivo> di <denominazione>» e riempie l'aggettivo a
# caso: «Catarratto, un grande abruzzese del Piemonte». E' siciliano.
_PROVENIENZA = re.compile(
    r"\b(piemontes|toscan|sicilian|abruzzes|puglies|venet|umbr|lazial|marchigian|"
    r"sard|calabres|campan|lombard|ligur|friulan|trentin|altoatesin|emilian|"
    r"romagnol|borgognon|bordoles|frances|spagnol|tedesc|austriac)\w*", re.I)


def _provenienze_inventate(testo: str, ammesso: str) -> list[str]:
    return [m.group(0) for m in _PROVENIENZA.finditer(_senza_accenti(testo))
            if m.group(0)[:6] not in ammesso]


_ROSSO = re.compile(r"\b(rosso|rossa|rubino|granato|tannico|tannicit[àa]|tannin)", re.I)
_BIANCO = re.compile(r"\b(bianco|bianca|paglierino|dorat[oa]|verdolino)", re.I)


def _colore_sbagliato(testo: str, fatti: Fatti) -> str | None:
    """Il testo dice di un colore che i fatti smentiscono?"""
    dichiarato = " ".join(filter(None, [
        _senza_accenti(fatti.colore or ""),
        _senza_accenti(fatti.colore_bacca or ""),
    ]))
    if not dichiarato:
        return None
    e_bianco = ("white" in dichiarato or "bianc" in dichiarato)
    e_rosso = ("red" in dichiarato or "ner" in dichiarato or "ross" in dichiarato)

    if e_bianco and not e_rosso and _ROSSO.search(testo):
        return f"colore contraddetto ({_ROSSO.search(testo).group(1)}, ma è bianco)"
    if e_rosso and not e_bianco and _BIANCO.search(testo):
        return f"colore contraddetto ({_BIANCO.search(testo).group(1)}, ma è rosso)"
    return None


# ---------------------------------------------------------------- template

def _con_articolo(nome: str, lingua: str) -> str:
    """«Etna Rosso» -> «un Etna Rosso» / «an Etna Rosso».

    In inglese l'articolo cambia davanti a vocale, e «a Etna Rosso» si sente
    subito. In italiano un vino resta maschile anche quando il nome non lo e' -
    si sottintende «vino» - quindi «un» va bene sempre.
    """
    if lingua == "en":
        return f"{'an' if nome[:1].lower() in 'aeiou' else 'a'} {nome}"
    return f"un {nome}"


def _apertura(f: Fatti, lex: Lessico, lingua: str) -> str:
    """La prima frase dice CHE COSA si ha davanti, con l'onestà del livello.

    E con l'onestà della SICUREZZA. Il livello dice quanto è specifico il record
    trovato; la sicurezza dice quanto somiglia a ciò che c'era sull'etichetta.
    Sono cose diverse: si può avere un record di livello VINO — nome, cantina,
    annata, tutto — trovato con una somiglianza del 60%. Annunciarlo come
    «Questo è il Barolo di Marchesi di Barolo» sarebbe una bugia detta bene.
    Sotto la soglia della certezza si dice al tavolo che è una supposizione.

    Le frasi vengono da `data/lessico/frasi.json`: qui c'è solo la logica di
    quale dire, mai il testo, perché il testo cambia con la lingua.
    """
    d = lambda chiave, **kw: lex.frase("apertura", chiave, lingua=lingua, **kw)

    if f.livello is Livello.VINO and f.nome:
        pezzi = [d("pezzo_nome", nome=f.nome)]
        if f.cantina:
            pezzi.append(d("pezzo_cantina", cantina=f.cantina))
        if f.annata:
            pezzi.append(d("pezzo_annata", annata=f.annata))
        cosa = " ".join(p for p in pezzi if p)
        if f.certo:
            return d("vino_certo", cosa=cosa)
        if f.dubbio:
            return d("vino_dubbio", cosa=cosa)
        return d("vino_incerto", cosa=cosa)

    if f.livello is Livello.TIPOLOGIA and f.tipologia:
        chiave = ("tipologia_incerta" if f.sicurezza < SOGLIA_DUBBIA
                  else "tipologia_nota")
        return d(chiave, cosa=_con_articolo(f.tipologia, lingua))

    if f.livello is Livello.DENOMINAZIONE and f.denominazione:
        sigla = lex.frase("sigle", f.tipo_denominazione or "IGP", lingua=lingua)
        return d("denominazione", denominazione=f.denominazione, sigla=sigla)

    if f.livello is Livello.VITIGNO and f.vitigni:
        if f.sicurezza < SOGLIA_DUBBIA:
            return d("vitigno_incerto", cosa=_con_articolo(f.vitigni[0], lingua))
        return d("vitigno_noto", vitigno=f.vitigni[0])

    return d("illeggibile")


def _corpo(f: Fatti, lex: Lessico, lingua: str) -> list[str]:
    d = lambda chiave, **kw: lex.frase("corpo", chiave, lingua=lingua, **kw)
    frasi = []

    if (nota := f.nota_in(lingua)):
        frasi.append(nota)
    elif f.vitigni:
        frasi.append(d("nasce_da", vitigni=elenca_in_lingua(f.vitigni[:3], lingua)))

    # Le parole del disciplinare vengono prima dei tratti generici: sono la
    # descrizione sensoriale VERA di questo vino, mentre «corpo» e «acidita'»
    # sono due caselle di un vocabolario. Dove ci sono le prime, le seconde
    # sono il contorno.
    #
    # In italiano sono la citazione parola per parola. In inglese sono una
    # traduzione (vedi `amelie.organolettico`), e per questo la frase dice cosa
    # il disciplinare CHIEDE invece di virgolettare: quella resa e' nostra, e
    # metterla fra virgolette attribuirebbe a un ente pubblico parole che non
    # ha scritto.
    if f.disciplinare:
        from .organolettico import carica as carica_organolettico

        vocabolario = carica_organolettico()
        for ambito in ("colore", "odore", "sapore"):
            if not (testo := f.disciplinare.get(ambito)):
                continue
            if (reso := vocabolario.rendi(testo, ambito, lingua=lingua)):
                frasi.append(d(f"disciplinare_{ambito}", valore=reso.testo))

    corpo = (lex.traduci("corpo", f.corpo, lingua=lingua, forma="narrativa")
             if f.corpo else None)
    acidita = (lex.traduci("acidita", f.acidita, lingua=lingua, forma="narrativa")
               if f.acidita else None)
    if corpo and acidita:
        frasi.append(d("tratti_entrambi", corpo=corpo, acidita=acidita))
    elif corpo:
        frasi.append(d("tratti_corpo", corpo=corpo))
    elif acidita:
        frasi.append(d("tratti_acidita", acidita=acidita))

    # Due sorgenti diverse: gli abbinamenti di un vino commerciale sono chiavi
    # del vocabolario e si traducono; quelli di un vitigno sono prosa scritta a
    # mano, e per l'inglese esiste gia' la sua versione. Passare la prosa
    # italiana per il vocabolario non la tradurrebbe: la lascerebbe li'.
    if (abbinamenti := f.abbinamenti_in(lingua)):
        piatti = lex.traduci_molti("abbinamento", abbinamenti[:3], lingua=lingua)
        frasi.append(d("abbinamenti", piatti=elenca_in_lingua(piatti, lingua)))

    if f.temperatura_c:
        # "16-18" letto ad alta voce diventa "sedici trattino diciotto": va
        # sciolto, perche' questo testo lo pronuncia una voce sintetica.
        t = f.temperatura_c.replace("\u2013", "-")
        if "-" in t:
            da, _, a = t.partition("-")
            frasi.append(d("temperatura_intervallo", da=da.strip(), a=a.strip()))
        else:
            frasi.append(d("temperatura_puntuale", gradi=t.strip()))

    return [x for x in frasi if x]


def corpo_neutro(f: Fatti, lex: Lessico | None = None, lingua: str = "it") -> str:
    """Il racconto SENZA la frase d'apertura.

    È questo che si pre-genera e si mette in cache: l'apertura dipende da quanto
    il dispositivo è sicuro di ciò che ha davanti, e quella certezza si conosce
    solo al momento. Un testo che comincia con «Del produttore non sono sicuro»
    sarebbe sbagliato per una bottiglia riconosciuta con certezza.
    """
    lex = lex or carica()
    return " ".join(_corpo(f, lex, lingua)).strip()


def template(f: Fatti, lex: Lessico | None = None, lingua: str = "it") -> str:
    """Il racconto senza modello: la rete di sicurezza.

    Non è bello come un testo generato, ma è **vero per costruzione**: ogni
    frase nasce da un campo del database. È quello che il dispositivo dice se
    tutto il resto fallisce.
    """
    lex = lex or carica()
    return " ".join([_apertura(f, lex, lingua)] + _corpo(f, lex, lingua)).strip()


# ---------------------------------------------------------------- il prompt

ISTRUZIONI = """Scrivi la descrizione di un vino per il display di un dispositivo da tavolo.

UN SOLO paragrafo in italiano, da 50 a 90 parole, tono caldo e sobrio, come una
buona scheda di sala: si parla DEL VINO, non a chi legge.

REGOLE INDEROGABILI:
- Usa ESCLUSIVAMENTE le informazioni del blocco FATTI qui sotto.
- Non aggiungere premi, punteggi, medaglie, annate, gradi, colori, profumi,
  luoghi, persone o vitigni che non siano scritti nei FATTI.
- Se un'informazione non c'è, non nominarla: non tentare di indovinarla.
- NON salutare, non ringraziare, non rivolgerti a chi legge: niente «vi», «la
  vostra», «buona degustazione», niente domande.
- Non cominciare con «Questo vino è»: entra nel merito.
- Niente elenchi, titoli, virgolette o note finali: solo il paragrafo.

FATTI:
{fatti}

Descrizione:"""

ISTRUZIONI_INCERTO = """
NOTA: l'etichetta non è stata letta con certezza. Non attribuire nulla a un
produttore specifico: parla della denominazione o del vitigno in generale, non
di questa bottiglia.
"""


ISTRUZIONI_CACHE = """
NOTA: il testo verrà preceduto da una frase che nomina il vino, quindi NON
ripetere il nome all'inizio e non aprire con «Questo è…». Comincia direttamente
dalla sostanza.
"""


def prompt(f: Fatti, *, per_cache: bool = False) -> str:
    testo = ISTRUZIONI.format(fatti=f.blocco_fatti())
    if per_cache:
        testo = testo.replace("\nFATTI:", ISTRUZIONI_CACHE + "\nFATTI:")
    elif f.livello is not Livello.VINO:
        testo = testo.replace("\nFATTI:", ISTRUZIONI_INCERTO + "\nFATTI:")
    return testo


# ---------------------------------------------------------------- narratore

class Narratore:
    """Sceglie da dove far venire il racconto, nell'ordine che costa meno."""

    def __init__(
        self,
        percorso_db: str | Path | None = None,
        genera: Callable[[str], str] | None = None,
        lingua: str = "it",
    ) -> None:
        from .matcher import PERCORSO_DB

        self.percorso = Path(percorso_db) if percorso_db else PERCORSO_DB
        self.genera = genera          # None = nessun modello disponibile
        self.lingua = lingua
        self.lex = carica()
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

    def chiudi(self) -> None:
        # Sotto lucchetto: se un thread di lavoro sta leggendo la cache, chiudere
        # sotto di lui non e' un errore che si cattura, e' un segmentation fault.
        with self._db:
            self.con.close()

    def racconta(self, f: Fatti, *, consenti_modello: bool = True,
                 preferisci_modello: bool = False) -> Racconto:
        """Da dove far venire il racconto, dal piu' specifico al piu' generico.

        L'ordine non e' per costo, e' per QUANTO SI SA della bottiglia:

        1. un testo gia' scritto per QUESTO record, se c'e';
        2. il template sui fatti trovati, che e' vero per costruzione e piu'
           specifico di qualunque ripiego: di un vino riconosciuto fino al
           produttore si conoscono corpo, acidita' e abbinamenti suoi, e
           raccontarlo col testo generico del suo vino sarebbe buttarli via;
        3. i gradini di ripiego gia' scritti - la tipologia, la denominazione,
           il vitigno - per le bottiglie di cui si sa poco;
        4. il modello dal vivo, se qualcuno l'ha acceso;
        5. la sola apertura, che dice almeno che cosa si ha davanti.

        Con `preferisci_modello` il quarto gradino passa davanti a tutti: vedi
        sotto.
        """
        if f.vuoto:
            return Racconto(
                testo=self.lex.frase("schermo", "illeggibile_con_invito",
                                     lingua=self.lingua),
                origine="template", livello=f.livello)

        # Le «descrizioni generate», se qualcuno le ha accese dalle
        # impostazioni. Ribaltano l'ordine di proposito: il modello va per
        # primo, non per ultimo. E' una scelta di chi gestisce il locale, non
        # nostra - costa l'attesa della generazione e in cambio il racconto e'
        # scritto per quella bottiglia li'.
        #
        # Non e' un salto nel vuoto: `_dal_modello` verifica quel che scrive e
        # torna None se il modello ha inventato due volte di fila. Allora si
        # riprende la cascata di sempre, dal gradino piu' specifico. Acceso non
        # puo' voler dire peggio.
        if preferisci_modello and consenti_modello and self.genera is not None:
            if (vivo := self._dal_modello(f)) is not None:
                return vivo

        if (pronto := self._dalla_cache(f, solo_esatto=True)) is not None:
            return pronto

        if (corpo := corpo_neutro(f, self.lex, self.lingua)):
            apertura = _apertura(f, self.lex, self.lingua)
            return Racconto(testo=f"{apertura} {corpo}".strip(),
                            origine="template", livello=f.livello)

        if (pronto := self._dalla_cache(f)) is not None:
            return pronto

        if consenti_modello and self.genera is not None:
            if (vivo := self._dal_modello(f)) is not None:
                return vivo

        return Racconto(testo=template(f, self.lex, self.lingua),
                        origine="template", livello=f.livello)

    # -------------------------------------------------------------- strati

    def _dalla_cache(self, f: Fatti, *, solo_esatto: bool = False) -> Racconto | None:
        """Il primo gradino della catena che abbia un testo pronto.

        Si scende dal record trovato verso il generico: il Primitivo di
        Manduria di un produttore qualunque ricade sul Primitivo di Manduria,
        poi sulla denominazione, poi sul vitigno. La catena la costruisce il
        matcher, che sa come sono legate le tabelle.
        """
        gradini = self._gradini(f)
        for ambito, ident in (gradini[:1] if solo_esatto else gradini):
            with self._db:
                r = self.con.execute(
                    "SELECT testo FROM racconto"
                    " WHERE ambito=? AND ambito_id=? AND lingua=?",
                    (ambito, ident, self.lingua),
                ).fetchone()
            if not r:
                continue
            # L'apertura si compone ADESSO, perche' dice quanto siamo sicuri; il
            # corpo viene dalla cache. Un testo pre-generato non puo' sapere se
            # l'etichetta e' stata letta bene, ne' quale bottiglia sia: per
            # questo il corpo e' scritto sul vino generico e l'apertura no.
            apertura = _apertura(f, self.lex, self.lingua)
            log.debug("racconto da %s/%s in cache", ambito, ident)
            return Racconto(testo=f"{apertura} {r['testo']}".strip(),
                            origine="cache", livello=f.livello)
        return None

    @staticmethod
    def _gradini(f: Fatti) -> list[tuple[str, int]]:
        """La catena di ripiego, o il solo record d'origine se non c'e'."""
        if f.ripiego:
            return f.ripiego
        return [f.origine] if f.origine else []

    def _dal_modello(self, f: Fatti) -> Racconto | None:
        """Genera e verifica. Un solo secondo tentativo, poi si rinuncia.

        Rigenerare all'infinito su un modello che continua a inventare
        significherebbe far aspettare l'ospite per nulla: meglio il template.
        """
        for tentativo in (1, 2):
            try:
                testo = (self.genera(prompt(f)) or "").strip()
            except Exception as e:                       # noqa: BLE001
                log.warning("generazione fallita: %s", e)
                return None
            if not testo:
                continue
            testo = _ripulisci(testo)
            ok, invenzioni = verifica(testo, f)
            if ok:
                return Racconto(testo=testo, origine="modello", livello=f.livello)
            log.warning("tentativo %d scartato, ha inventato: %s", tentativo, invenzioni)
        return None


def _ripulisci(testo: str) -> str:
    """Toglie le abitudini dei modelli: virgolette, titoli, elenchi, code."""
    testo = testo.strip().strip('"«»')
    testo = re.sub(r"^\s*(Racconto|Testo|Risposta)\s*:\s*", "", testo, flags=re.I)
    testo = re.sub(r"^\s*[-*•]\s*", "", testo, flags=re.M)
    testo = re.sub(r"\s+", " ", testo).strip()
    parole = testo.split()
    if len(parole) > PAROLE_MAX:
        testo = " ".join(parole[:PAROLE_MAX])
        # Si preferisce chiudere su una frase intera, ma solo se questo non
        # butta via piu' di meta' del testo: meglio un troncamento dichiarato
        # con i puntini che due parole al posto di cento.
        punto = testo.rfind(".")
        if punto >= len(testo) // 2:
            testo = testo[: punto + 1]
        elif not testo.endswith(("…", ".", "!", "?")):
            testo = testo.rstrip(" ,;:") + "…"
    return testo


def a_frasi(flusso: Iterator[str]) -> Iterator[str]:
    """Raggruppa un flusso di token in frasi complete.

    Serve al TTS: si può cominciare a parlare appena la prima frase è finita,
    invece di aspettare tutto il racconto. Su questa board sono venti secondi
    di attesa risparmiati.
    """
    buffer = ""
    for pezzo in flusso:
        buffer += pezzo
        while (m := re.search(r"[.!?…]\s", buffer)):
            frase, buffer = buffer[: m.end()].strip(), buffer[m.end():]
            if frase:
                yield frase
    if buffer.strip():
        yield buffer.strip()
