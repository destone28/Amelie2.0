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


def verifica(testo: str, fatti: Fatti, lingua: str = "it") -> tuple[bool, list[str]]:
    """Il testo afferma solo cose presenti nei fatti?

    Restituisce (va bene, elenco delle invenzioni). Il controllo è volutamente
    grossolano ma **deterministico**: cerca numeri e nomi propri che non
    compaiano da nessuna parte nel blocco dei fatti. Preferisce un falso
    allarme — che costa una rigenerazione — a una bugia detta all'ospite.

    **La lingua conta**, ed è costato scoprirlo: i fatti si componevano sempre
    in italiano, e un racconto inglese veniva confrontato con parole italiane.
    «Tuscany» non sta in un blocco che dice «Toscana», e nemmeno «Italy»,
    «Piedmont», «Bordeaux»: sui 9.660 racconti in archivio la verifica ne
    bocciava 3.401, quasi tutti per questo. Un controllo che grida sempre non
    è un controllo severo, è un controllo spento.

    >>> f = Fatti(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi")
    >>> verifica("Il Cannubi di Marchesi.", f)[0]
    True
    >>> verifica("Il Cannubi ha vinto tre stelle Gambero Rosso.", f)[0]
    False
    """
    ammesso = _senza_accenti(
        " ".join(filter(None, [
            fatti.blocco_fatti(lingua=lingua),
            " ".join(fatti.vitigni),
            fatti.nota_in(lingua) or "",
            fatti.note_vitigno or "",
            " ".join(fatti.sensoriali_in(lingua)),
            " ".join(fatti.abbinamenti_in(lingua)),
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
    if contraddizione := _colore_sbagliato(testo, fatti, ammesso):
        invenzioni.append(contraddizione)

    # Le quattro classi che seguono sono uscite da una rilettura dei testi del
    # modello addestrato: passavano tutte, e cio' che la verifica non vede
    # diventa un'abitudine del modello.
    invenzioni.extend(_gradi_sbagliati(testo, fatti))
    if "disciplinar" in _senza_accenti(testo) and not fatti.disciplinare:
        invenzioni.append("disciplinare invocato senza citazioni")
    invenzioni.extend(_cibi_inventati(testo, ammesso))
    invenzioni.extend(_provenienze_inventate(testo, ammesso))
    # Le due classi che seguono sono uscite da una rilettura di dodici testi
    # generati sul dispositivo: cinque erano sbagliati e la verifica li aveva
    # promossi tutti, perche' non inventavano NOMI, inventavano RAPPORTI fra
    # nomi veri. «Sangiovese e Amarena, i vitigni piu' coltivati d'Italia» -
    # tre volte su dodici: l'amarena e' una nota olfattiva dei fatti, non
    # un'uva. «Amarone della Valpolicella, un vitigno compagno dei
    # Rondinella»: e' il vino, non un vitigno. E «questa spumante» detto di un
    # Amarone.
    invenzioni.extend(_vitigni_che_non_lo_sono(testo, fatti, lingua))
    if contraddizione := _categoria_sbagliata(testo, fatti, ammesso):
        invenzioni.append(contraddizione)
    # Seconda rilettura, dopo la prima stretta: «da servire con amarena,
    # prugna o tannino morbido», «nasce dall'incontro di mela verde e fiori
    # bianchi, il vitigno Prosecco», «gradevole, fine, delicato, delicate».
    # Le note olfattive finivano nei posti delle uve e dei cibi, in
    # minuscolo, dove il controllo sui nomi propri non guarda.
    invenzioni.extend(_note_al_posto_sbagliato(testo, fatti, lingua))
    invenzioni.extend(_parole_ripetute(testo))

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


# Dove un testo dichiara i vitigni: quel che segue fino alla fine della frase
# e' un elenco di uve, e ogni nome proprio li' dentro dev'essere un'uva.
_CONTESTO_VITIGNI = re.compile(
    # «dall'incontro»: dopo l'apostrofo non c'e' spazio, e la prima versione
    # di questa espressione lo pretendeva - e non prendeva proprio la frase
    # che l'ha fatta nascere.
    # L'elenco delle uve finisce alla prima virgola o a un «con»/«che»: dopo
    # comincia un'altra cosa - «Nasce dal Sangiovese, con note di amarena» ha
    # l'amarena al posto giusto, e il controllo non deve leggerla come uva.
    r"(?:nasce\s+(?:dall'|dalla\s+|dalle\s+|dal\s+|dai\s+)\s*(?:solo\s+|incontro\s+di\s+)?"
    r"|vitign[oi]\s+|uv[ae]\s+(?:di\s+)?|grapes?\s+|from\s+the\s+)"
    r"((?:(?!\s+(?:con|che|with|which)\s)[^.;:!?,])*)", re.I)
_UN_VITIGNO = re.compile(r"\b(un|a)\s+(?:grande\s+)?(vitigno|grape)\b", re.I)


def _vitigni_che_non_lo_sono(testo: str, fatti: Fatti, lingua: str) -> list[str]:
    """Nomi detti come uve che nei fatti sono altro.

    Il modello impara la forma «nasce da X e Y» e la riempie con due nomi
    propri qualunque presi dai fatti: il vitigno vero e la prima nota
    olfattiva che trova. Ogni nome proprio in un contesto da vitigno deve
    stare fra i vitigni dei fatti; se invece sta fra le note sensoriali, o e'
    il nome del vino stesso, e' una bugia con parole vere.
    """
    uve = {_senza_accenti(v).lower() for v in fatti.vitigni + fatti.vitigni_ammessi}
    note = {_senza_accenti(n).lower()
            for n in list(fatti.note_sensoriali) + list(fatti.sensoriali_in(lingua))}
    vino = {_senza_accenti(x).lower() for x in (fatti.nome, fatti.tipologia,
                                                  fatti.denominazione) if x}
    fuori: list[str] = []
    for m in _CONTESTO_VITIGNI.finditer(testo):
        for nome in re.findall(r"\b([A-ZÀ-Ý][a-zà-ÿ']{2,})\b", m.group(1)):
            n = _senza_accenti(nome).lower()
            if any(n in u for u in uve):
                continue
            if any(n in x for x in note):
                fuori.append(f"{nome} detto vitigno, ma e' una nota olfattiva")
    # «Amarone della Valpolicella, un vitigno compagno...»: il vino stesso
    # presentato come uva. Il nome deve stare ATTACCATO a «un vitigno»: la
    # prima versione guardava i sessanta caratteri prima, e bocciava la scheda
    # del vitigno che dice «Non un vitigno ma una famiglia numerosa» subito
    # dopo il nome del vino. Su 360 racconti composti, 7 falsi allarmi cosi'.
    piano = _senza_accenti(testo).lower()
    for v in vino:
        if not v or any(v in u for u in uve):
            continue
        if re.search(re.escape(v) + r"\s*(?:,|\be\b|\bis\b)?\s*(?:un|a)\s+(?:grande\s+)?(?:vitigno|grape)\b",
                     piano):
            fuori.append(f"«{v}» detto vitigno, ma e' il vino")
    return fuori


# Dove un testo dice con che cosa si beve: quel che segue e' un elenco di cibi.
_CONTESTO_ABBINAMENTI = re.compile(
    r"(?:si\s+accompagna\s+(?:bene\s+)?(?:a|con)\s+|da\s+(?:servire|accompagnare|abbinare)\s+con\s+"
    r"|(?:ideale|perfett[oa]|adatt[oa])\s+(?:per|su|a|con)\s+|abbinat[oa]\s+a\s+"
    r"|pairs?\s+(?:well\s+)?with\s+|serve\s+with\s+)([^.;:!?]*)", re.I)
_TANNINO = re.compile(r"\btannin\w*", re.I)


def _note_al_posto_sbagliato(testo: str, fatti: Fatti, lingua: str) -> list[str]:
    """Note olfattive dette come uve o come cibi.

    In minuscolo: il controllo sui nomi propri non le vede, e il modello le
    scrive cosi'. «Nasce dall'incontro di mela verde e fiori bianchi» e «da
    servire con amarena, prugna o tannino morbido» sono frasi fatte di parole
    dei fatti, messe dove non possono stare.
    """
    note = {_senza_accenti(n).lower()
            for n in list(fatti.note_sensoriali) + list(fatti.sensoriali_in(lingua))}
    note = {n for n in note if len(n) >= 4}
    fuori: list[str] = []
    for contesto, dove in ((_CONTESTO_VITIGNI, "vitigno"),
                           (_CONTESTO_ABBINAMENTI, "cibo")):
        for m in contesto.finditer(testo):
            pezzo = _senza_accenti(m.group(1)).lower()
            for n in note:
                if re.search(r"\b" + re.escape(n) + r"\b", pezzo):
                    fuori.append(f"«{n}» detta come {dove}")
            if dove == "cibo" and _TANNINO.search(pezzo):
                fuori.append("tannino servito come cibo")
    return fuori


# Solo spazio o virgola fra le due, e la seconda deve CHIUDERE - virgola,
# punto o fine: «delicato, delicato, fruttato» e' il modello che gira a vuoto,
# ma «Schiava, Schiava Gentile e Schiava Grigia» e' un elenco di uve,
# «Pantelleria Pantelleria-Bianco» e «Carso/Carso-Kras» sono nomi del
# registro, e «dolci, dolci secchi» e' una lista di piatti. Visti tutti su
# 360 racconti composti dai fatti, dove non c'e' niente da bocciare.
_RIPETUTA = re.compile(r"\b(\w{4,})[,\s]+\1(?=\s*(?:[,.;!?]|$))", re.I)


def _parole_ripetute(testo: str) -> list[str]:
    """«delicato, delicate», «bella acidita' e buona acidita'»: il modello che
    gira a vuoto. Una parola ripetuta di seguito non e' una frase."""
    return [f"ripetizione: {m.group(0)}" for m in _RIPETUTA.finditer(testo)]


_SPUMANTE = re.compile(r"\b(spumante|frizzante|bollicin\w*|perlage|sparkling|bubbles?)\b", re.I)
_FERMO = frozenset(("Wine", "Vino", "wine"))


def _categoria_sbagliata(testo: str, fatti: Fatti, ammesso: str) -> str | None:
    """Un vino fermo raccontato con le bollicine, o il contrario.

    Si controlla solo quando la categoria e' nota e non e' citata nei fatti
    stessi: se la scheda dice «spumante», dirlo non e' un'invenzione.
    """
    cat = fatti.categoria or ""
    if not cat:
        return None
    frizza_nei_fatti = bool(_SPUMANTE.search(ammesso))
    frizza_nel_testo = _SPUMANTE.search(testo)
    fermo = cat in _FERMO
    if fermo and frizza_nel_testo and not frizza_nei_fatti:
        return f"bollicine inventate ({frizza_nel_testo.group(1)}) su un vino fermo"
    return None


_ROSSO = re.compile(r"\b(rosso|rossa|rubino|granato|tannico|tannicit[àa]|tannin)", re.I)
_BIANCO = re.compile(r"\b(bianco|bianca|paglierino|dorat[oa]|verdolino)", re.I)


def _colore_sbagliato(testo: str, fatti: Fatti, ammesso: str = "") -> str | None:
    """Il testo dice di un colore che i fatti smentiscono?

    `ammesso` è il testo dei fatti: una parola che sta LÌ non è una
    contraddizione, è una citazione. La scheda del Friulano dice «passito di
    grande dolcezza sostenuta da un tannino insolito», e il tannino faceva
    gridare al rosso su un vino bianco — ma quelle parole le abbiamo scritte
    noi, nei fatti, apposta.
    """
    dichiarato = " ".join(filter(None, [
        _senza_accenti(fatti.colore or ""),
        _senza_accenti(fatti.colore_bacca or ""),
    ]))
    if not dichiarato:
        return None
    e_bianco = ("white" in dichiarato or "bianc" in dichiarato)
    e_rosso = ("red" in dichiarato or "ner" in dichiarato or "ross" in dichiarato)

    def fuori_dai_fatti(trovato):
        return trovato and _senza_accenti(trovato.group(1)) not in ammesso

    if e_bianco and not e_rosso and fuori_dai_fatti(t := _ROSSO.search(testo)):
        return f"colore contraddetto ({t.group(1)}, ma è bianco)"
    if e_rosso and not e_bianco and fuori_dai_fatti(t := _BIANCO.search(testo)):
        return f"colore contraddetto ({t.group(1)}, ma è rosso)"
    return None


# ---------------------------------------------------------------- template

def seme_di(f: Fatti) -> int:
    """Un numero stabile per ogni vino: e' cio' che sceglie le varianti.

    Le frasi del lessico hanno piu' forme equivalenti, e questo seme decide
    quale tocca a questo vino - la stessa ogni volta, perche' un ospite che
    rimette la bottiglia deve sentire lo stesso racconto, e diversa da vino a
    vino, perche' due bottiglie di fila non devono suonare come un modulo
    riempito due volte. E' `crc32`, non `hash()`: quello cambia a ogni avvio
    del processo, e il racconto cambierebbe con lui.
    """
    import zlib

    identita = "|".join(str(x) for x in (
        f.origine, f.nome, f.cantina, f.annata, f.tipologia, f.denominazione,
        *f.vitigni))
    return zlib.crc32(identita.encode("utf-8"))


def _seme_per(seme: int, chiave: str) -> int:
    """Lo stesso seme, ma diverso per ogni frase: altrimenti con tre varianti
    per frase un vino prenderebbe sempre «la seconda» di tutte, e i racconti
    si assomiglierebbero a gruppi di tre."""
    import zlib

    return seme ^ zlib.crc32(chiave.encode("utf-8"))


def _con_articolo(nome: str, lingua: str) -> str:
    """«Etna Rosso» -> «un Etna Rosso» / «an Etna Rosso».

    In inglese l'articolo cambia davanti a vocale, e «a Etna Rosso» si sente
    subito. In italiano un vino resta maschile anche quando il nome non lo e' -
    si sottintende «vino» - quindi «un» va bene sempre.
    """
    if lingua == "en":
        return f"{'an' if nome[:1].lower() in 'aeiou' else 'a'} {nome}"
    return f"un {nome}"


def _apertura(f: Fatti, lex: Lessico, lingua: str, seme: int = 0) -> str:
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
    d = lambda chiave, **kw: lex.frase("apertura", chiave, lingua=lingua,
                                       seme=_seme_per(seme, chiave), **kw)

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

    if f.livello is Livello.GENERICO:
        cosa = _che_tipo_di_vino(f, lex, lingua)
        if cosa:
            return d("generico", cosa=cosa)

    return d("illeggibile")


def _che_tipo_di_vino(f: Fatti, lex: Lessico, lingua: str) -> str:
    """«Uno spumante rosato metodo classico, brut» — solo cio' che c'e' scritto.

    Ogni pezzo viene da una parola LETTA sull'etichetta, e ogni parola letta
    passa da un elenco chiuso: niente di quello che dice il rumore dell'OCR
    puo' finire in bocca al dispositivo. Se non c'e' nessun pezzo non si dice
    niente, e il racconto passa alla frase che chiede di girare l'etichetta.
    """
    g = lambda chiave: lex.frase("generico", chiave, lingua=lingua)
    parole = set(f.qualificatori)
    base = next((g(k) for k in ("spumante", "frizzante", "passito", "liquoroso")
                 if k in parole), None)
    # «Metodo» da solo dichiara uno spumante: se c'e' quello e manca la parola
    # «spumante», si dice comunque spumante.
    if base is None and "metodo" in parole:
        base = g("spumante")
    colore = {"Rosato": "rosato", "Rosso": "rosso", "Bianco": "bianco"}.get(
        f.colore or "")
    if base is None and colore is None:
        return ""
    pezzi = [base or g("vino")]
    if colore:
        pezzi.append(g(colore))
    if "metodo" in parole:
        pezzi.append(g("metodo"))
    dosaggio = next((g(k) for k in ("nature", "brut", "extra", "dry", "secco",
                                    "amabile", "dolce") if k in parole), None)
    testo = " ".join(pezzi)
    return f"{testo}, {dosaggio}" if dosaggio else testo


def _corpo(f: Fatti, lex: Lessico, lingua: str, seme: int = 0) -> list[str]:
    """Le frasi dopo l'apertura: poche, e ognuna nata da un campo dell'archivio.

    Al massimo quattro. Prima erano fino a sette - vitigno, tre frasi di
    disciplinare, corpo e acidita', abbinamenti, temperatura - e un racconto
    da sette frasi di formula si sente che e' una formula. Qui si sceglie:
    da dove viene; che cosa ne dice il disciplinare, in due frasi al massimo;
    corpo e acidita' solo se il disciplinare tace; e una frase sola per
    temperatura e tavola, che prima erano due.

    Ogni frase ha piu' forme equivalenti nel lessico e il seme sceglie quale:
    vedi `seme_di`. Le forme dicono la stessa cosa - il test del lessico
    controlla che abbiano gli stessi segnaposto - e non aggiungono niente:
    questo e' il racconto che si puo' garantire, e la garanzia sta tutta qui.
    """
    d = lambda chiave, **kw: lex.frase("corpo", chiave, lingua=lingua,
                                       seme=_seme_per(seme, chiave), **kw)
    frasi = []

    # 1. Da dove viene. Prima i vitigni per nome - a meno che il nome del vino
    #    non li contenga gia', «Cabernet Sauvignon» di tal cantina - poi la
    #    scheda del vitigno, che e' prosa scritta da una persona e vale piu' di
    #    una formula, ma nella sua prima frase sola: e' quella che lo
    #    presenta, le altre approfondiscono, e qui si deve essere brevi.
    #
    #    La scheda senza il nome davanti era un difetto visto su 360 racconti
    #    composti: «Questo e' un Valdinievole. Il vitigno piu' coltivato
    #    d'Italia e l'anima della Toscana...» - e quale? Non lo diceva mai.
    nel_nome = " ".join(x for x in (f.nome, f.tipologia, f.denominazione) if x).lower()
    if f.vitigni and not all(v.lower() in nel_nome for v in f.vitigni[:3]):
        frasi.append(d("nasce_da", vitigni=elenca_in_lingua(f.vitigni[:3], lingua)))
    nota = f.nota_in(lingua)
    if nota:
        frasi.append(spezza_in_frasi(nota)[0])

    # 2. Il disciplinare: la descrizione sensoriale VERA di questo vino. In
    #    italiano e' la citazione parola per parola; in inglese e' una resa
    #    nostra (vedi `amelie.organolettico`), e per questo la frase dice cosa
    #    il disciplinare CHIEDE invece di virgolettare - metterla fra
    #    virgolette attribuirebbe a un ente pubblico parole che non ha scritto.
    #
    #    Due frasi al massimo: colore e sapore, che sono quelle che si
    #    riconoscono nel bicchiere; l'odore entra solo se una delle due manca.
    resi: dict[str, str] = {}
    if f.disciplinare:
        from .organolettico import carica as carica_organolettico

        vocabolario = carica_organolettico()
        for ambito in ("colore", "odore", "sapore"):
            if (testo := f.disciplinare.get(ambito)):
                if (reso := vocabolario.rendi(testo, ambito, lingua=lingua)):
                    resi[ambito] = reso.testo
    scelti = [a for a in ("colore", "sapore") if a in resi]
    if len(scelti) < 2 and "odore" in resi:
        scelti.append("odore")
    # Con la scheda del vitigno gia' detta, del disciplinare resta una frase:
    # il sapore, che e' quello che si sente, o quel che c'e'. Cinque frasi in
    # tutto, apertura compresa, e' il tetto.
    if nota and len(scelti) > 1:
        scelti = ["sapore"] if "sapore" in scelti else scelti[:1]
    for ambito in ("colore", "odore", "sapore"):
        if ambito in scelti:
            frasi.append(d(f"disciplinare_{ambito}", valore=_senza_coda_tronca(resi[ambito])))

    # 3. Corpo e acidita' sono due caselle di un vocabolario: dove parla il
    #    disciplinare sono il contorno, e il contorno si taglia.
    if not scelti:
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

    # 4. A tavola: temperatura e piatti in una frase sola. Due sorgenti
    #    diverse per i piatti: gli abbinamenti di un vino commerciale sono
    #    chiavi del vocabolario e si traducono; quelli di un vitigno sono
    #    prosa scritta a mano, gia' nella lingua giusta.
    piatti = ""
    if (abbinamenti := f.abbinamenti_in(lingua)):
        # Senza doppioni DOPO la traduzione: «Dessert» e «Sweet» sono due
        # chiavi e una parola sola, «dolci», e il racconto diceva «dolci,
        # dolci e antipasti».
        tradotti = list(dict.fromkeys(
            lex.traduci_molti("abbinamento", abbinamenti, lingua=lingua)))
        piatti = elenca_in_lingua(tradotti[:3], lingua)
    da = a = gradi = ""
    if f.temperatura_c:
        # "16-18" letto ad alta voce diventa "sedici trattino diciotto": va
        # sciolto, perche' questo testo lo pronuncia una voce sintetica.
        t = f.temperatura_c.replace("\u2013", "-")
        if "-" in t:
            da, _, a = (x.strip() for x in t.partition("-"))
        else:
            gradi = t.strip()
    if piatti and da:
        frasi.append(d("servizio_intervallo", da=da, a=a, piatti=piatti))
    elif piatti and gradi:
        frasi.append(d("servizio_puntuale", gradi=gradi, piatti=piatti))
    elif piatti:
        frasi.append(d("abbinamenti", piatti=piatti))
    elif da:
        frasi.append(d("temperatura_intervallo", da=da, a=a))
    elif gradi:
        frasi.append(d("temperatura_puntuale", gradi=gradi))

    # E alla fine, quando non c'e' nient'altro da dire, si dice PERCHE'. Non e'
    # un'esitazione - quelle si sono tolte, e riguardavano il leggere - e' un
    # fatto: questa bottiglia in archivio non c'e'. Senza, un racconto di due
    # righe sembra un dispositivo rotto; con, e' un dispositivo onesto.
    #
    # Ma solo se qualcosa si e' detto. Senza colore ne' tipo, l'apertura ripiega
    # su «provi a girare l'etichetta», e dirle dietro «quello che le ho detto e'
    # scritto sull'etichetta» significa vantare una risposta che non c'e' stata.
    # Sentito sul dispositivo, parola per parola.
    if f.livello is Livello.GENERICO and (f.qualificatori or f.colore):
        frasi.append(d("generico_limite"))

    return [x for x in frasi if x]


# Le parole con cui una citazione NON puo' finire. Il campo del disciplinare in
# archivio e' stato tagliato a un numero di caratteri quando lo si e' estratto,
# e a volte finisce a meta' inciso: «rosso rubino intenso, scuro, un» -
# «brillante, dal». Letto ad alta voce e' un inciampo. Si toglie l'ultimo
# inciso quando finisce con una di queste.
_CODA_TRONCA = frozenset(
    "un una uno il lo la i gli le l dal dalla dallo dai dalle del della dello "
    "dei delle di da con e ed o al alla allo ai alle a in nel nella per piu "
    "tendente talvolta anche the a an of with and or to from more".split())


def _senza_coda_tronca(testo: str) -> str:
    pezzi = [x.strip() for x in testo.split(",")]
    while len(pezzi) > 1:
        ultima = _senza_accenti(pezzi[-1]).lower().rstrip(".").split()
        if ultima and ultima[-1] in _CODA_TRONCA:
            pezzi.pop()
            continue
        break
    testo = ", ".join(pezzi)
    parole = testo.split()
    if len(parole) > 1 and _senza_accenti(parole[-1]).lower().rstrip(".") in _CODA_TRONCA:
        testo = " ".join(parole[:-1])
    return testo.rstrip(" ,")


def corpo_neutro(f: Fatti, lex: Lessico | None = None, lingua: str = "it") -> str:
    """Il racconto SENZA la frase d'apertura.

    È questo che si pre-genera e si mette in cache: l'apertura dipende da quanto
    il dispositivo è sicuro di ciò che ha davanti, e quella certezza si conosce
    solo al momento. Un testo che comincia con «Del produttore non sono sicuro»
    sarebbe sbagliato per una bottiglia riconosciuta con certezza.
    """
    lex = lex or carica()
    return " ".join(_corpo(f, lex, lingua, seme_di(f))).strip()


def template(f: Fatti, lex: Lessico | None = None, lingua: str = "it") -> str:
    """Il racconto composto dai fatti: quello che si puo' garantire.

    Ogni frase nasce da un campo dell'archivio o da una citazione del
    disciplinare, dentro una forma del lessico che il seme sceglie fra
    equivalenti. Non c'e' nessun passaggio in cui una parola possa nascere da
    un'altra parte: e' il modo «archivio», ed e' l'unico di cui si possa dire
    che non inventa - misurato, il modello sul dispositivo sbagliava un fatto
    in cinque testi su dodici, e la verifica a posteriori non li prendeva
    tutti.
    """
    lex = lex or carica()
    seme = seme_di(f)
    return " ".join([_apertura(f, lex, lingua, seme)]
                    + _corpo(f, lex, lingua, seme)).strip()


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


def prompt(f: Fatti, *, per_cache: bool = False, lingua: str = "it") -> str:
    testo = ISTRUZIONI.format(fatti=f.blocco_fatti(lingua=lingua))
    if per_cache:
        testo = testo.replace("\nFATTI:", ISTRUZIONI_CACHE + "\nFATTI:")
    elif f.livello is not Livello.VINO:
        testo = testo.replace("\nFATTI:", ISTRUZIONI_INCERTO + "\nFATTI:")
    return testo


# Il prompt del modello ADDESTRATO. Deve essere identico a quello su cui e'
# stato addestrato, parola per parola: un modello affinato su una forma e
# interrogato con un'altra e' un modello che non hai affinato.
#
# Misurato sulla board dandogli per sbaglio il prompt del modello generico -
# le istruzioni lunghe piu' il blocco esteso: 63,8 secondi invece di 27, e la
# prosa tornata sgrammaticata («Il Abruzzo Spumante Bianco Charmat e' un solo
# vitigno»). Le regole non gli servono: le ha imparate. Gli serve la forma.
ISTRUZIONE_ADDESTRATA = {
    "it": "Scrivi la scheda di sala di questo vino, in quattro frasi.",
    "en": "Write this wine's tasting note, in four sentences.",
}


def prompt_addestrato(f: Fatti, lingua: str = "it") -> str:
    """I fatti compatti nel formato di chat di Qwen, come all'addestramento."""
    istruzione = ISTRUZIONE_ADDESTRATA.get(lingua, ISTRUZIONE_ADDESTRATA["it"])
    return (f"<|im_start|>system\n{istruzione}<|im_end|>\n"
            f"<|im_start|>user\n{f.blocco_compatto(lingua=lingua)}<|im_end|>\n"
            f"<|im_start|>assistant\n")


# ---------------------------------------------------------------- narratore

class Narratore:
    """Sceglie da dove far venire il racconto, nell'ordine che costa meno."""

    def __init__(
        self,
        percorso_db: str | Path | None = None,
        genera: Callable[[str], str] | None = None,
        lingua: str = "it",
        modello_addestrato: bool = False,
        genera_a_flusso: Callable[[str], Iterator[str]] | None = None,
    ) -> None:
        from .matcher import PERCORSO_DB

        self.percorso = Path(percorso_db) if percorso_db else PERCORSO_DB
        self.genera = genera          # None = nessun modello disponibile
        self.lingua = lingua
        # Quale forma di prompt vuole il modello che c'e' dietro: vedi
        # `prompt_addestrato`. Sbagliarla costa il doppio del tempo e tutta la
        # qualita' che l'addestramento aveva comprato.
        self.modello_addestrato = modello_addestrato
        # Chi sa dare il testo a pezzi. Senza, `racconta_a_frasi` funziona
        # lo stesso ma aspetta la fine: e' il modo in cui degrada, non un caso
        # da evitare.
        self._flusso = genera_a_flusso
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
        # Al livello GENERICO il modello non scrive, mai, nemmeno se acceso.
        #
        # GENERICO vuol dire: l'etichetta si e' letta benissimo e in archivio
        # non c'e' niente che si possa nominare senza inventarlo, quindi si
        # ripete SOLO cio' che c'e' scritto - che e' uno spumante, che e'
        # rosato, che e' brut. Ogni parola viene dalla bottiglia, per
        # costruzione.
        #
        # Dare quei quattro fatti a un modello e chiedergli una descrizione e'
        # chiedergli di riempire il resto, e il resto se lo inventa. Visto sul
        # dispositivo, su un Lambrusco Grasparossa: «Nasce dai vitigni
        # Lambrusco e Grasparossa, tipico della zona castellana. Colore giallo,
        # con sapore delicato e acidita' equilibrata. In bocca e' un vino di
        # media struttura, con bella acidita' e buona acidita'.» Un rosso
        # dichiarato giallo, una zona che non esiste, e l'acidita' detta due
        # volte.
        #
        # `verifica` non lo prende, e non e' un suo difetto: controlla che non
        # si nominino vitigni e denominazioni che non ci sono - e infatti su un
        # altro tentativo ha scartato «Pinot Noir, Cabernet Sauvignon» - ma il
        # colore di un vino non e' un nome, e' un'affermazione. A questo
        # livello non ci sono affermazioni da fare.
        genera_qui = (consenti_modello and self.genera is not None
                      and f.livello is not Livello.GENERICO)
        # Il modo «generativa» e' l'unico in cui un testo scritto da un
        # modello - dal vivo o dalla cache, che e' lo stesso modello un giorno
        # prima - arriva in bocca al dispositivo. Nel modo «archivio» non ci
        # arriva mai: il racconto e' composto dai fatti, e basta. Prima la
        # cache si usava anche li', e un Franciacorta in modo «archivio»
        # diceva «Borgognone, ovunque nel mondo». La garanzia vale solo se
        # non ha eccezioni.
        if preferisci_modello:
            if genera_qui and (vivo := self._dal_modello(f)) is not None:
                return vivo
            if (pronto := self._dalla_cache(f)) is not None:
                return pronto

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
            # Verificato come un testo del modello, perche' LO E': la cache e'
            # stata scritta dallo stesso modello, prima. Sul dispositivo un
            # Franciacorta usciva dalla cache cosi': «Borgognone, ovunque nel
            # mondo» - e nessuno l'aveva mai riletto. Un testo pronto che non
            # regge si salta, e si scende al gradino dopo o al template.
            ok, invenzioni = verifica(r["testo"], f, self.lingua)
            if not ok:
                log.warning("cache %s/%s scartata, ha inventato: %s",
                            ambito, ident, invenzioni)
                continue
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

    def racconta_a_frasi(self, f: Fatti) -> Iterator[str]:
        """Le frasi del racconto, una per volta, appena sono pronte E verificate.

        Serve a coprire l'attesa. Sulla board il prefill dei fatti costa dodici
        secondi prima che esca la prima lettera, e sono dodici secondi di
        silenzio davanti a un ospite. Qui la prima frase e' l'APERTURA, che e'
        un template: nasce dai fatti, e' pronta in millisecondi e dice gia'
        qualcosa di vero - che bottiglia si ha davanti e quanto se ne e' sicuri.
        Mentre la voce la pronuncia, il modello lavora.

        L'apertura e' anche l'unica frase che il modello non scrive mai: dipende
        dalla CERTEZZA, che si conosce solo al momento. Dirla noi e lasciare a
        lui il resto non e' una ripetizione, e' la divisione naturale.

        **Ogni frase si verifica prima di uscire di qui.** Una frase detta non
        si riprende: aspettare il testo intero per verificarlo tutto insieme
        sarebbe piu' comodo, ma allora non si potrebbe cominciare a parlare
        prima della fine, che e' tutto il punto. Una frase che non passa si
        lascia cadere e si va avanti con le altre - restano vere una per una,
        anche se il periodo ne esce piu' corto.

        Se il modello non da' nemmeno una frase buona, si finisce col template:
        chi ascolta non deve accorgersi che qualcosa non ha funzionato.
        """
        apertura = _apertura(f, self.lex, self.lingua)
        if apertura:
            yield apertura
        if f.vuoto or self.genera is None:
            yield from spezza_in_frasi(corpo_neutro(f, self.lex, self.lingua))
            return

        domanda = (prompt_addestrato(f, self.lingua) if self.modello_addestrato
                   else prompt(f, lingua=self.lingua))
        buone = scartate = 0
        try:
            for frase in a_frasi(self.genera_a_flusso(domanda)):
                frase = _ripulisci(frase)
                if not frase:
                    continue
                ok, invenzioni = verifica(frase, f, self.lingua)
                if ok:
                    buone += 1
                    yield frase
                else:
                    scartate += 1
                    log.warning("frase scartata, ha inventato: %s", invenzioni)
        except Exception as e:                               # noqa: BLE001
            log.warning("generazione a flusso fallita: %s", e)
        if not buone:
            # Nemmeno una frase buona: si racconta col template, e chi ascolta
            # sente solo un racconto normale un po' piu' tardi.
            log.info("nessuna frase dal modello (%d scartate): si va di template",
                     scartate)
            yield from spezza_in_frasi(corpo_neutro(f, self.lex, self.lingua))

    def genera_a_flusso(self, domanda: str) -> Iterator[str]:
        """Il modello a pezzi. Senza uno che li sappia dare, si da' tutto insieme."""
        if (flusso := getattr(self, "_flusso", None)) is not None:
            yield from flusso(domanda)
        else:
            yield self.genera(domanda) or ""

    def _dal_modello(self, f: Fatti) -> Racconto | None:
        """Genera e verifica. Un solo secondo tentativo, poi si rinuncia.

        Rigenerare all'infinito su un modello che continua a inventare
        significherebbe far aspettare l'ospite per nulla: meglio il template.
        """
        for tentativo in (1, 2):
            try:
                domanda = (prompt_addestrato(f, self.lingua) if self.modello_addestrato
                           else prompt(f, lingua=self.lingua))
                testo = (self.genera(domanda) or "").strip()
            except Exception as e:                       # noqa: BLE001
                log.warning("generazione fallita: %s", e)
                return None
            if not testo:
                continue
            testo = _ripulisci(testo)
            ok, invenzioni = verifica(testo, f, self.lingua)
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
    if not testo.endswith(("…", ".", "!", "?")):
        # Il modello si e' fermato a meta' frase - il tetto dei token, o il
        # nostro taglio qui sopra. Quattro testi su dodici, sul dispositivo,
        # finivano cosi': «Da servire fra i diciassette e i dici». Si chiude
        # sull'ultima frase intera, ma solo se questo non butta via piu' di
        # meta' del testo: meglio un troncamento dichiarato con i puntini che
        # due parole al posto di cento.
        punto = max(testo.rfind("."), testo.rfind("!"), testo.rfind("?"))
        if punto >= len(testo) // 2:
            testo = testo[: punto + 1]
        else:
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
