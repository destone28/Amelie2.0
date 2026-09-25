"""Il racconto: dai fatti alla prosa, senza inventare.

Un modello piccolo non sa nulla di vino. Se gli si chiede di raccontare un
Sagrantino, inventa premi, punteggi e note di degustazione che suonano
benissimo e sono false. In sala, davanti a un ospite, è una figuraccia.

Per questo il modello **non è la fonte dei fatti**, e nel modo predefinito non
è nemmeno la fonte delle parole. Due modi, e la differenza fra loro è DA DOVE
VENGONO le parole:

1. **Composizione dai fatti** — il modo «archivio», quello predefinito. Ogni
   frase nasce da un campo dell'archivio o da una citazione del disciplinare,
   dentro una forma del lessico scelta da un seme stabile per vino. Non c'è
   nessun passaggio in cui una parola possa nascere altrove, ed è l'unica
   garanzia che regge: istantanea, e vera per costruzione. Vedi `template`.
2. **Il modello** — il modo «generativa», dichiarato sperimentale. Riceve solo
   il blocco dei fatti e un divieto di aggiungerne; ciò che scrive passa da
   `verifica`, e se inventa due volte di fila si scende al testo pronto per
   quel record, se qualcuno l'ha scritto, e poi alla composizione. Misurato
   sul dispositivo: cinque testi su dodici con un errore di fatto, e la
   verifica non li prendeva tutti. Ogni giro di regole trova una forma nuova
   di errore: per questo non è il modo predefinito.

`verifica` è un controllo deterministico in Python — numeri, nomi propri,
colori, rapporti fra nomi veri — che il modello non può aggirare, e che si
applica anche ai testi pronti, perché li ha scritti lo stesso modello.

Il tono cambia con il livello raggiunto dalla cascata del riconoscimento:
sotto il primo gradino non si attribuisce mai a un produttore sconosciuto ciò
che non si è verificato.
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

# Un vitigno finto del registro detto come se fosse un'uva: vedi
# `matcher.VITIGNI_FINTI` e `Narratore._dalla_cache`.
_UVA_FINTA = re.compile(r"\b(?:da|from)\s+(?:na|n\.a\.|n/a|nd|n\.d\.)(?=[\s.,;]|$)", re.I)

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
# E non dopo un'iniziale puntata: «di M. Marengo», «Abbazia di S. Gaudenzio»,
# «F.lli Vincenzi» sono nomi di cantina, e la voce ci faceva una pausa in
# mezzo - «...di emme.» «Marengo.» - mentre a schermo si illuminava la frase
# sbagliata. Sul dispositivo si sente, e sono centinaia di cantine.
_FINE_FRASE = re.compile(
    r"""(?<=[.!?…])(?<!\b[A-ZÀ-Ý].)\s+(?=[A-ZÀ-Ý«"“'(])""")


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
# Un nome proprio: maiuscola iniziale, almeno tre lettere, non a inizio frase
# - e nemmeno dopo i due punti, dove la maiuscola e' d'uso: «Molinara: Vitigno
# veronese» non nomina nessuno.
_PROPRIO = re.compile(r"(?<![.!?…:]\s)(?<!^)\b([A-ZÀ-Ý][a-zà-ÿ']{2,})\b")

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
    # L'apostrofo tipografico vale come quello dritto: il modello lo scrive,
    # e «dall’incontro» non trovava piu' il contesto delle uve.
    testo = testo.replace("’", "'").replace("‘", "'")
    # E lo stesso dall'altra parte: «Valled’aosta» sta nel registro con
    # l'apostrofo tipografico, e il testo normalizzato non lo ritrovava piu'.
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
        ])).replace("’", "'").replace("‘", "'")
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
    invenzioni.extend(_produttore_al_posto_del_luogo(testo, fatti))
    invenzioni.extend(_colore_al_posto_del_gusto(testo, fatti))
    invenzioni.extend(_uve_al_posto_del_produttore(testo, fatti))
    invenzioni.extend(_scheda_attaccata_al_vino(testo, fatti, lingua))
    invenzioni.extend(_note_al_posto_sbagliato(testo, fatti, lingua))
    invenzioni.extend(_cibi_al_posto_dei_profumi(testo, fatti, lingua))
    # Le ripetizioni che stanno dentro una citazione del registro non sono
    # nostre: il registro enumera le sfumature ammesse - «rosso rubino piu' o
    # meno intenso, rosa piu' o meno intenso» - e noi le riportiamo. Si
    # riprende quel che si e' ripetuto, non chi l'ha scritto.
    citazioni = _citazioni_come_si_dicono(fatti, lingua)
    invenzioni.extend(x for x in _parole_ripetute(testo)
                      if x.removeprefix("ripetizione: ") not in citazioni)

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
    # «vitigno» e «uve» aprono un elenco solo se seguono con un nome proprio:
    # «vitigno veronese dal colore tenue» e' un aggettivo, non un elenco, e la
    # scheda della Molinara finiva bocciata per «acidita' viva detta come
    # uva». E l'elenco continua oltre una virgola solo se dopo la virgola
    # viene un altro nome proprio: «Sangiovese, Amarena e Canaiolo» e' un
    # elenco intero e va guardato tutto; «Isabella, ibrido americano dal
    # profumo di fragola» finisce a Isabella, e la fragola non e' un'uva
    # detta male, e' un profumo detto bene.
    # Il «da» liscio mancava: c'erano «dal», «dalla», «dall'», «dai», non
    # «nasce da Barbaresco» - letto sul dispositivo, e Barbaresco e' il vino.
    r"(?:nasce\s+(?:dall'|dalla\s+|dalle\s+|dal\s+|dai\s+|da\s+)\s*(?:solo\s+|incontro\s+di\s+)?"
    # «Nasce dall'incontro di tre vitigni: Trebbiano, Toscano, Abruzzese e
    # Soave»: i due punti chiudevano il pezzo catturato, e l'elenco vero -
    # quello dopo - non si leggeva affatto.
    r"|vitign[oi]\s*:?\s*(?=(?-i:[A-ZÀ-Ý]))|uv[ae]\s+(?:di\s+)?(?=(?-i:[A-ZÀ-Ý]))"
    # «It comes from Ripa Teatina», «It is made from Nebbiolo»: sono le frasi
    # inglesi del lessico, e quel che segue sono uve. Mancavano, e un luogo
    # detto al posto di un vitigno passava - letto sul dispositivo.
    # Non «from the»: e' troppo generico, e dentro la scheda di un vitigno
    # - «Arneis: Piedmontese, from the Roero» - diceva che il Roero e' un'uva.
    # «Si ottiene da {vitigni}» e' una frase del lessico, quindi il modello
    # l'ha imparata: e quel che segue sono uve per definizione. Mancava, e
    # «Si ottiene da Restivo» - il produttore - passava.
    r"|si\s+ottien(?:e|gono)\s+(?:da(?:i|l|lla|lle|gli)?\s*)(?=(?-i:[A-ZÀ-Ý]))"
    r"|ottenut[oaie]\s+(?:da(?:i|l|lla|lle|gli)?\s*)(?=(?-i:[A-ZÀ-Ý]))"
    r"|grapes?\s+(?=(?-i:[A-Z]))"
    r"|(?:comes?|made|is\s+made)\s+from\s+(?=(?-i:[A-Z])))"
    # I due punti chiudono il pezzo - «Si ottiene da Zibibbo: Il Moscato
    # d'Alessandria» ha la scheda dopo, non un'altra uva - tranne quando
    # davanti c'e' la parola che annuncia l'elenco: «tre vitigni: Trebbiano,
    # Toscano, Abruzzese e Soave». Li' l'elenco comincia dopo.
    r"((?:[^.;:!?,]|,(?=\s+(?-i:[A-ZÀ-Ý]))"
    r"|(?<=vitigni):|(?<=vitigno):|(?<=uve):|(?<=grapes):|(?<=varieties):)*)", re.I)
_UN_VITIGNO = re.compile(r"\b(un|a)\s+(?:grande\s+)?(vitigno|grape)\b", re.I)
# «Nebbiolo in purezza» e' l'apertura che il corpus insegna, e quel che sta
# davanti DEVE essere un'uva. Letto sul dispositivo: «Etna in purezza, il
# vitigno siciliano di Sicilia» - l'Etna e' la denominazione, e la frase
# passava perche' «Etna» sta nei fatti.
_IN_PUREZZA = re.compile(
    r"([A-ZÀ-Ý][\w'’ -]{2,40}?)\s+in\s+(?:purezza|pura\s+essenza)\b")


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
    # La cantina c'e' dentro, e non e' un di piu': «Si ottiene da Restivo»,
    # letto sul dispositivo, dove Restivo e' il produttore. Passava perche' il
    # nome sta nei fatti e nessuna regola guardava in che posto fosse finito.
    vino = {_senza_accenti(x).lower() for x in (fatti.nome, fatti.tipologia,
                                                  fatti.denominazione,
                                                  fatti.cantina) if x}
    # I luoghi in un elenco di uve capitano per il verso giusto - «Nasce dal
    # Sangiovese, Toscana» - e non sono un'uva detta male.
    luoghi = {_senza_accenti(x).lower() for x in (fatti.regione, fatti.denominazione) if x}
    # Quel che sta fra virgolette e' il nome sull'etichetta, e la scheda del
    # vitigno e' roba dei fatti riportata: nessuno dei due afferma che quelle
    # parole siano uve di questo vino. Guardarci dentro dava sedici allarmi
    # falsi sui racconti composti - «Da Uve Garganega Monte Fiorentine»,
    # «Fragolino: nome popolare dell'uva Isabella».
    pulito = re.sub(r"[«“\"][^»”\"]*[»”\"]", " ", testo)
    for pezzo in (fatti.note_vitigno, fatti.nota_in(lingua)):
        # La scheda si riporta anche a pezzi - il racconto composto ne prende
        # la prima frase - quindi si toglie frase per frase. Ma solo quando e'
        # ATTRIBUITA, cioe' preceduta dai due punti: «Trebbiano: Non un
        # vitigno solo ma una famiglia...» e' la scheda del Trebbiano, mentre
        # «Nasce da Siciliano, chiamato Ansonica in Toscana» e' la stessa
        # scheda messa dove vanno le uve - e «Siciliano» un vitigno non e'.
        for frase in spezza_in_frasi(pezzo or ""):
            if len(frase) > 12:
                pulito = re.sub(r":\s*" + re.escape(frase), ": ", pulito, flags=re.I)

    # Per l'elenco voce per voce si tolgono anche i NOMI: la cantina «Uva Mia
    # di Luisella» e la tipologia «San Severo Uva di Troia» aprono un elenco
    # di uve che non esiste. Sono etichette, non affermazioni. Restano visibili
    # agli altri due controlli, che cercano proprio i nomi finiti fra le uve.
    per_voci = pulito
    for pezzo in (fatti.cantina, fatti.nome, fatti.tipologia, fatti.denominazione):
        if pezzo and len(pezzo) > 3:
            per_voci = re.sub(re.escape(pezzo), " ", per_voci, flags=re.I)
    fuori: list[str] = []
    for m in _CONTESTO_VITIGNI.finditer(pulito):
        for nome in re.findall(r"\b([A-ZÀ-Ý][a-zà-ÿ']{2,})\b", m.group(1)):
            n = _senza_accenti(nome).lower()
            if any(n in u or u in n for u in uve):
                continue
            if any(n in x for x in note):
                fuori.append(f"{nome} detto vitigno, ma e' una nota olfattiva")
    # Il nome del vino, o della sua denominazione, messo dove vanno le uve:
    # «It comes from Ripa Teatina», che e' un paese. Passava perche' quel
    # nome STA nei fatti - e' la denominazione - e nessuna regola guardava in
    # che posto fosse finito. Si flagga solo se nell'elenco non compare
    # nessuna delle uve vere: «Brachetto d'Acqui» contiene il Brachetto, ed e'
    # un modo legittimo di dirlo.
    # «It comes from Trentino-Alto Adige» dice da DOVE viene, ed e' vero: in
    # inglese la stessa apertura serve alle uve e alla provenienza. Se nel
    # pezzo c'e' la regione dei fatti, si sta parlando di quella.
    regione = _senza_accenti(fatti.regione or "").lower()
    # Ogni VOCE dell'elenco deve contenere un'uva vera. «Brachetto d'Acqui»
    # e' una voce sola e contiene il Brachetto: legittimo. «Trebbiano,
    # Toscano, Abruzzese e Soave» sono quattro voci, e tre non sono uve - la
    # scheda del Trebbiano dice che la famiglia comprende «il Toscano,
    # l'Abruzzese, quello di Soave», e il modello ne ha fatto quattro vitigni
    # di questo vino. Parole vere, fatto falso.
    for m in _CONTESTO_VITIGNI.finditer(per_voci):
        for voce in re.split(r",|\be\b|\bed\b|\band\b", m.group(1)):
            if not re.search(r"[A-ZÀ-Ý]", voce):
                continue
            v = _senza_accenti(voce).lower()
            if any(u and (u in v or v.strip() in u) for u in uve):
                continue
            if any(x and x in v for x in luoghi | note):
                continue
            nomi = re.findall(r"\b[A-ZÀ-Ý][a-zà-ÿ']{2,}\b", voce)
            if nomi:
                fuori.append(f"«{voce.strip()}» detto vitigno, ma fra le uve non c'e'")

    for m in _CONTESTO_VITIGNI.finditer(pulito):
        elenco = _senza_accenti(m.group(1)).lower()
        if any(re.search(r"\b" + re.escape(u) + r"\b", elenco) for u in uve if u):
            continue
        if regione and regione in elenco:
            continue
        for v in vino:
            if v and len(v) > 4 and v in elenco:
                fuori.append(f"«{v}» messo fra le uve, ma e' il vino")
                break

    for m in _IN_PUREZZA.finditer(testo):
        nome = _senza_accenti(m.group(1)).strip().lower()
        if nome and not any(nome in u or u in nome for u in uve):
            fuori.append(f"«{m.group(1).strip()}» detto in purezza, ma non e' un vitigno")
    # «Amarone della Valpolicella, un vitigno compagno...»: il vino stesso
    # presentato come uva. Il nome deve stare ATTACCATO a «un vitigno»: la
    # prima versione guardava i sessanta caratteri prima, e bocciava la scheda
    # del vitigno che dice «Non un vitigno ma una famiglia numerosa» subito
    # dopo il nome del vino. Su 360 racconti composti, 7 falsi allarmi cosi'.
    piano = _senza_accenti(testo).lower()
    for v in vino:
        if not v or any(v in u for u in uve):
            continue
        # «X, un vitigno», «X è un vitigno», «X, che è un vitigno»: dopo
        # `_senza_accenti` la «è» e' una «e», e «e'» e' ammessa anche lei.
        if re.search(re.escape(v) + r"\s*(?:,\s*(?:che\s+)?(?:e'?\s+)?|\s+(?:e'?|is)\s+)?"
                     r"(?:un|a)\s+(?:grande\s+)?(?:vitigno|grape)\b", piano):
            fuori.append(f"«{v}» detto vitigno, ma e' il vino")
    return fuori


# Dove un testo dice che cosa si sente in bocca: li' il colore non c'entra.
_CONTESTO_GUSTO = re.compile(
    r"(?:il\s+gusto\s+è|al\s+palato|in\s+bocca\s+è|il\s+sapore\s+è"
    r"|the\s+taste\s+is|on\s+the\s+palate|in\s+the\s+mouth)([^.!?]*)", re.I)
# Solo parole che descrivono un colore e nient'altro: «secco» o «pieno» in
# bocca ci stanno, «rubino» no.
_PAROLA_DEL_COLORE = re.compile(
    r"\b(?:di\s+colore\s+\w+|rubino|granato|paglierino|verdognol\w+|violacei"
    r"|ambrat\w+|dorat\w+|salmone|ramat\w+|buccia\s+di\s+cipolla"
    r"|ruby|garnet|straw[- ]colou?red|golden[- ]yellow|amber)\b", re.I)


def _colore_al_posto_del_gusto(testo: str, fatti: Fatti) -> list[str]:
    """Il colore detto dove va il gusto.

    «In bocca è asciutto, armonico, di colore bianco e con acidità alta»,
    «On the palate, bright ruby red». Il modello ha tre citazioni del
    disciplinare - colore, odore, sapore - e ogni tanto mette quella del
    colore nel giro di frase del gusto. Le parole sono tutte vere, il posto
    no, e la verifica non guardava in che posto fossero.

    Misurato sui racconti salvati dei due modelli: succede nel 3-9% dei testi
    scritti dal modello, in tutte e due le lingue.
    """
    fuori = []
    for m in _CONTESTO_GUSTO.finditer(testo):
        if (x := _PAROLA_DEL_COLORE.search(m.group(1))):
            fuori.append(f"«{x.group(0)}» detto del gusto, ma e' il colore")
    return fuori


# Dopo il nome fra virgolette, «di» e «by» introducono chi l'ha fatto.
_CONTESTO_PRODUTTORE = re.compile(r"[»”\"']\s+(?:di|by)\s+([^.;:!?]*)", re.I)


def _uve_al_posto_del_produttore(testo: str, fatti: Fatti) -> list[str]:
    """I vitigni messi dove va la cantina.

    «This is the "Barbera del Monferrato" by Grignolino, Freisa, Dolcetto and
    Barbera», letto sul dispositivo: quelle sono le uve, e quel record una
    cantina non ce l'ha nemmeno - e' una denominazione.
    """
    uve = [_senza_accenti(v).lower() for v in fatti.vitigni + fatti.vitigni_ammessi
           if len(v) > 3]
    if not uve:
        return []
    cantina = _senza_accenti(fatti.cantina or "").lower()
    fuori = []
    for m in _CONTESTO_PRODUTTORE.finditer(testo):
        chi = _senza_accenti(m.group(1)).lower()
        if cantina and cantina in chi:
            continue
        if any(re.search(r"\b" + re.escape(u) + r"\b", chi) for u in uve):
            fuori.append(f"«{m.group(1).strip()}» detto come produttore, ma sono le uve")
    return fuori


def _scheda_attaccata_al_vino(testo: str, fatti: Fatti, lingua: str) -> list[str]:
    """La scheda del vitigno appesa al nome del vino.

    «Morellino di Scansano: Italy's most planted grape and the soul of
    Tuscany»: quella e' la scheda del Sangiovese, e il Morellino e' il vino.
    La forma «{vitigno}: {scheda}» e' giusta e la composizione la usa; qui il
    nome davanti ai due punti e' quello sbagliato.
    """
    scheda = _senza_accenti(fatti.nota_in(lingua) or "").lower().strip()
    if len(scheda) < 24:
        return []
    inizio = re.escape(scheda[:24])
    fuori = []
    for nome in (fatti.nome, fatti.tipologia, fatti.denominazione):
        if not nome or len(nome) <= 4:
            continue
        n = _senza_accenti(nome).lower()
        if any(n in _senza_accenti(v).lower() or _senza_accenti(v).lower() in n
               for v in fatti.vitigni + fatti.vitigni_ammessi):
            continue        # un vino che si chiama come la sua uva: e' giusto
        if re.search(re.escape(n) + r"\s*:\s*" + inizio, _senza_accenti(testo).lower()):
            fuori.append(f"«{nome}» con la scheda del vitigno, ma e' il vino")
            break
    return fuori


# Dove un testo dice DOVE si fa: quel che segue e' un luogo.
_CONTESTO_LUOGO = re.compile(
    r"(?:si\s+produce\s+(?:in|a|nel|nella|nelle|nei|negli)\s+"
    r"|nasce\s+(?:in|a|nel|nella)\s+"
    r"|(?:is\s+)?produced\s+in\s+|made\s+in\s+|grown\s+in\s+)([^.;:!?]*)", re.I)


def _produttore_al_posto_del_luogo(testo: str, fatti: Fatti) -> list[str]:
    """Il nome della cantina messo dove va la regione.

    «Si produce in Produttori di Manduria», letto sul dispositivo: quello e'
    chi lo fa, non dove si fa. Il modello impara la frase «Si produce in
    {regione}» e, quando la regione nei fatti non c'e', la riempie col primo
    nome proprio che trova.

    Si guarda solo la cantina, e solo se nel pezzo la regione non c'e': una
    denominazione E' quasi sempre anche un luogo - «si produce a Montalcino» -
    e bocciarla sarebbe un allarme falso.
    """
    cantina = _senza_accenti(fatti.cantina or "").lower().strip()
    if len(cantina) <= 4:
        return []
    regione = _senza_accenti(fatti.regione or "").lower()
    fuori = []
    for m in _CONTESTO_LUOGO.finditer(testo):
        dove = _senza_accenti(m.group(1)).lower()
        if regione and regione in dove:
            continue
        if cantina in dove:
            fuori.append(f"«{fatti.cantina}» detto come luogo, ma e' chi lo produce")
    return fuori


# Dove un testo dice con che cosa si beve: quel che segue e' un elenco di cibi.
_CONTESTO_ABBINAMENTI = re.compile(
    r"(?:si\s+accompagna\s+(?:bene\s+)?(?:a|con)\s+|da\s+(?:servire|accompagnare|abbinare)\s+con\s+"
    r"|(?:ideale|perfett[oa]|adatt[oa])\s+(?:per|su|a|con)\s+|abbinat[oa]\s+a\s+"
    r"|pairs?\s+(?:well\s+)?with\s+|serve\s+with\s+)([^.;:!?]*)", re.I)
_TANNINO = re.compile(r"\btannin\w*", re.I)


# Dove un testo dice che cosa si sente: quel che segue sono profumi, non cibi.
_CONTESTO_NOTE = re.compile(
    r"(?:note\s+(?:sensoriali\s+)?(?:tipiche\s+)?(?:di\s+)?|sentori\s+di\s+"
    r"|profuma\s+di\s+|al\s+naso\s+|aromi\s+di\s+|notes?\s+of\s+|aromas?\s+of\s+"
    r"|on\s+the\s+nose\s+)([^.;:!?]*)", re.I)


def _citazioni_come_si_dicono(fatti: Fatti, lingua: str) -> str:
    """Le citazioni del registro nella lingua in cui il racconto le dira'.

    In italiano sono quelle, parola per parola; in inglese sono una resa
    nostra, e confrontare un testo inglese con la citazione italiana non
    trova niente: «from pale straw yellow to straw yellow» veniva da «da
    giallo paglierino scarico a giallo paglierino», e la ripetizione
    risultava nostra.
    """
    pezzi = list((fatti.disciplinare or {}).values())
    if lingua != "it" and fatti.disciplinare:
        from .organolettico import carica as carica_organolettico

        vocabolario = carica_organolettico()
        for ambito, testo in fatti.disciplinare.items():
            if (reso := vocabolario.rendi(testo, ambito, lingua=lingua)):
                pezzi.append(reso.testo)
    return _senza_accenti(" ".join(pezzi)).lower()


def _cibi_al_posto_dei_profumi(testo: str, fatti: Fatti, lingua: str) -> list[str]:
    """Piatti detti come profumi: «note sensoriali tipiche di manzo,
    cacciagione, agnello e pasta».

    Passava la verifica perche' quelle parole stanno nei fatti - sono gli
    abbinamenti - ed e' l'errore che questo controllo cerca: un rapporto
    sbagliato fra parole vere. Lo specchio di `_note_al_posto_sbagliato`.
    """
    # Tradotti: in `fatti.abbinamenti` stanno le CHIAVI del vocabolario, che
    # sono inglesi («Beef»), e il testo dice «manzo».
    lex = carica()
    crudi = list(fatti.abbinamenti) + list(fatti.abbinamenti_in(lingua))
    piatti = {_senza_accenti(x).lower() for x in
              crudi + lex.traduci_molti("abbinamento", crudi, lingua=lingua)}
    piatti = {p for p in piatti if len(p) >= 4}
    fuori = []
    for m in _CONTESTO_NOTE.finditer(testo):
        pezzo = _senza_accenti(m.group(1)).lower()
        for p in piatti:
            if re.search(r"\b" + re.escape(p) + r"\b", pezzo):
                fuori.append(f"«{p}» detto come profumo, ma e' un piatto")
    return fuori


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
# La stessa parola due volte con solo uno spazio in mezzo, e in minuscolo:
# «delicato delicato e fruttato» si'; «Pantelleria Pantelleria-Bianco» e «Il
# Sangiovese Sangiovese Predappio» no, sono nomi che stanno in archivio cosi'.
_RIPETUTA_ATTACCATA = re.compile(r"\b([a-zà-ÿ]{4,})\s+\1\b(?!-)")


# La stessa coppia di parole due volte nella stessa frase: «con bella acidità
# e bella acidità». Le coppie sono piu' rare delle parole, e una coppia che
# torna non e' un elenco - «Schiava Gentile e Schiava Grigia» ha coppie
# diverse.
_COPPIA = re.compile(r"\b([a-zà-ÿ]{4,} [a-zà-ÿ]{4,})\b")


def _coppie_ripetute(testo: str) -> list[str]:
    fuori = []
    for frase in spezza_in_frasi(testo):
        viste: set[str] = set()
        # Le parole con l'originale davanti: un nome proprio ripetuto -
        # «Nasce dal Cabernet Sauvignon ... il Cabernet Sauvignon» - non e'
        # il modello che gira a vuoto, e' il nome del vitigno. Misurato: la
        # prima versione bocciava «Malvasia Nera» e «Moscato Giallo».
        # Sulla frase ORIGINALE, perche' `_senza_accenti` toglie anche le
        # maiuscole, e senza maiuscole non si distingue un nome.
        parole = re.findall(r"[A-Za-zÀ-ÿ]{4,}", frase)
        for a, b in zip(parole, parole[1:]):
            if a[:1].isupper() or b[:1].isupper():
                continue
            coppia = f"{_senza_accenti(a)} {_senza_accenti(b)}".lower()
            if coppia in viste:
                fuori.append(f"ripetizione: {coppia}")
                break
            viste.add(coppia)
    return fuori


def _parole_ripetute(testo: str) -> list[str]:
    """Il modello che gira a vuoto: «delicato, delicato, fruttato», «delicato
    delicato e fruttato». Non prende «delicato, delicate» - due parole
    diverse - ne' «bella acidita' e buona acidita'», e non deve: una regola
    sulla stessa parola a poche parole di distanza bocciava «cheese and
    matured cheese», «frutta e frutta secca», «di bella struttura, con bella
    acidita'» - sessanta racconti composti dai fatti su duemilaquattrocento,
    dove non c'e' niente da bocciare. Ogni regola in piu' qui e' un allarme
    falso in piu'."""
    trovate = []
    for rx in (_RIPETUTA, _RIPETUTA_ATTACCATA):
        trovate.extend(f"ripetizione: {m.group(0)}" for m in rx.finditer(testo))
    trovate.extend(_coppie_ripetute(testo))
    return trovate


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
# Per il rosato il tannino non conta: un rosato puo' averne. Contano i colori.
_ROSSO_PURO = re.compile(r"\b(rosso|rossa|rubino|granato)\b", re.I)
_COLORE_CHE_NON_LO_E = re.compile(
    r"\bcolou?re?\s+(?:è\s+|is\s+|da\s+|of\s+)?(spumante|frizzante|dessert|passito|"
    r"liquoroso|sparkling|fortified)\b", re.I)
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
    e_rosato = ("rosat" in dichiarato or "rose" in dichiarato or "pink" in dichiarato)

    def fuori_dai_fatti(trovato):
        return trovato and _senza_accenti(trovato.group(1)) not in ammesso

    if e_bianco and not e_rosso and fuori_dai_fatti(t := _ROSSO.search(testo)):
        return f"colore contraddetto ({t.group(1)}, ma è bianco)"
    if e_rosso and not e_bianco and fuori_dai_fatti(t := _BIANCO.search(testo)):
        return f"colore contraddetto ({t.group(1)}, ma è rosso)"
    # Un rosato non e' ne' rosso ne' bianco. «Il vino è rosato, di colore
    # rosso», su un rosé: passava, perche' il rosato non era un colore che
    # la regola conoscesse.
    if e_rosato and not (e_rosso or e_bianco):
        for rx in (_ROSSO_PURO, _BIANCO):
            if fuori_dai_fatti(t := rx.search(testo)):
                return f"colore contraddetto ({t.group(1)}, ma è rosato)"
    # E un colore non e' una categoria: «di colore spumante», «colore da
    # dessert». Il modello incolla due caselle dei fatti.
    if (t := _COLORE_CHE_NON_LO_E.search(testo)):
        return f"colore che non è un colore ({t.group(0)})"
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
    si assomiglierebbero a gruppi di tre.

    Un hash vero di «seme|chiave», non uno XOR e nemmeno un crc col seme
    come valore iniziale. Con lo XOR, sulle liste a due o quattro forme
    l'indice dipendeva solo dai bit bassi del seme e la costante della chiave
    era una permutazione fissa: su ventimila semi diversi uscivano QUATTRO
    combinazioni di scelte. Col crc a valore iniziale non cambiava: il valore
    iniziale entra in modo lineare, e per chiavi della stessa lunghezza nello
    stesso modo. Misurato tutte e due le volte.
    """
    import hashlib

    impronta = hashlib.blake2b(f"{seme}|{chiave}".encode("utf-8"), digest_size=4)
    return int.from_bytes(impronta.digest(), "big")


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
    g = lambda chiave, **kw: lex.frase("generico", chiave, lingua=lingua, **kw)
    parole = set(f.qualificatori)
    base = next((k for k in ("spumante", "frizzante", "passito", "liquoroso")
                 if k in parole), None)
    # «Metodo» da solo dichiara uno spumante: se c'e' quello e manca la parola
    # «spumante», si dice comunque spumante.
    if base is None and "metodo" in parole:
        base = "spumante"
    colore = {"Rosato": "rosato", "Rosso": "rosso", "Bianco": "bianco"}.get(
        f.colore or "")
    if base is None and colore is None:
        return ""
    # Il colore lo mette il lessico, perche' ogni lingua lo vuole in un posto
    # diverso: «uno spumante rosato», «a rosé sparkling wine». Accodato, in
    # inglese usciva «a sparkling wine rosé».
    pezzi = [" ".join(g(base or "vino", colore=g(colore) if colore else "").split())]
    if "metodo" in parole:
        pezzi.append(g("metodo"))
    dosaggio = next((g(k) for k in ("nature", "brut", "extra", "dry", "secco",
                                    "amabile", "dolce") if k in parole), None)
    testo = " ".join(pezzi)
    return f"{testo}, {dosaggio}" if dosaggio else testo


_ARTICOLO = re.compile(r"^(?:un'|(?:uno|una|un|an|a)\s+)", re.IGNORECASE)


def titolo_generico(f: Fatti, lex: Lessico, lingua: str) -> str:
    """Il titolo della schermata al livello generico: il tipo di vino senza
    articolo, con la maiuscola - «Spumante rosato metodo classico, brut».

    Era la frase del racconto tale e quale, e a schermo il titolo diventava
    «uno spumante rosato metodo classico, brut».
    """
    testo = _ARTICOLO.sub("", _che_tipo_di_vino(f, lex, lingua), count=1)
    return testo[:1].upper() + testo[1:]


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
    #    Quattro uve e non tre: il Bardolino ne ha quattro principali a pari
    #    merito, e con tre si perdeva la Corvina - l'unica che tutti conoscono.
    #    Oltre le quattro si taglia, e si dice «da»: e' un elenco, non una
    #    ricetta.
    nel_nome = " ".join(x for x in (f.nome, f.tipologia, f.denominazione) if x).lower()
    uve = f.vitigni[:4]
    nota = f.nota_in(lingua)
    prima = (spezza_in_frasi(nota) or [""])[0] if nota else ""
    vitigno = f.vitigni[0] if f.vitigni else ""
    #    E la scheda dice di quale uva parla. Senza, la sua prima frase -
    #    «Borgognone, ovunque nel mondo» - finiva attaccata al vino: parole
    #    vere dell'archivio, soggetto sbagliato. In 197 schede su 224 la prima
    #    frase non nomina il vitigno. Con un'uva sola la scheda si aggancia
    #    alla frase delle uve con i due punti - «Nasce da Chardonnay:
    #    borgognone, ovunque nel mondo» - che e' una frase in meno; con piu'
    #    uve, o senza la frase delle uve, porta il nome davanti.
    if uve and not all(v.lower() in nel_nome for v in uve):
        frase_uve = d("nasce_da", vitigni=elenca_in_lingua(uve, lingua))
        if prima and len(uve) == 1 and vitigno.lower() not in prima.lower():
            frasi.append(f"{frase_uve.rstrip('.')}: {prima}")
            prima = ""
        else:
            frasi.append(frase_uve)
    if prima:
        if not vitigno or vitigno.lower() in prima.lower():
            frasi.append(prima)
        else:
            frasi.append(d("scheda_vitigno", vitigno=vitigno, nota=prima))

    #    E dove si produce, ma solo quando c'e' poco altro da dire. Su 1.932
    #    denominazioni e tipologie provate, 227 non avevano ne' vitigni ne'
    #    citazioni ne' abbinamenti: il racconto era una frase sola, il nome e
    #    basta. La regione sta in archivio per 375 denominazioni su 532, e
    #    nessuno la leggeva.
    if len(frasi) < 2 and f.regione and not (
            f.denominazione and f.regione in f.denominazione):
        frasi.append(d("dove_si_produce", regione=f.regione))

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
    # tutto, apertura compresa, e' il tetto - e ci si arriva anche quando
    # l'elenco delle uve e la scheda sono due frasi distinte.
    if len(frasi) > 1 and len(scelti) > 1:
        scelti = ["sapore"] if "sapore" in scelti else scelti[:1]
    for ambito in ("colore", "odore", "sapore"):
        if ambito in scelti:
            citazione = ", ".join(_senza_doppioni_di_elenco(
                [x.strip() for x in _senza_coda_tronca(resi[ambito]).split(",")]))
            frasi.append(_frase_di_citazione(lex, lingua, seme, ambito, citazione))

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
        tradotti = _senza_doppioni_di_elenco(list(dict.fromkeys(
            lex.traduci_molti("abbinamento", abbinamenti, lingua=lingua))))
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


# Come comincia una citazione del disciplinare, e quali forme del lessico la
# reggono. Il registro non scrive aggettivi e basta: dodici citazioni di colore
# cominciano con «che va dal giallo paglierino...», diciannove di sapore con
# «sono asciutti, armonici...» - plurale, perche' parlano di piu' tipologie -
# e in inglese la resa puo' cominciare con «may be» o «ranging from». Messe
# dopo «Il sapore è» danno «Il sapore è sono asciutti»; dopo «lo vuole» danno
# «lo vuole che va dal». Letti sul dispositivo, uno per uno.
#
# Quindi la forma si sceglie dopo aver guardato la citazione: quelle con la
# virgola davanti al buco - «In bocca, {valore}» - reggono tutto; quelle col
# verbo - «Il sapore è {valore}» - reggono solo un aggettivo; una relativa
# vuole un nome davanti - «di un colore che va dal...»; un verbo vuole il suo
# soggetto sottinteso - «Secondo il disciplinare, sono asciutti».
_VERBO_ITALIANO = re.compile(
    r"^(?:sono|hanno|ha|presenta|presentano|puo|possono|posso|si\s|va|vanno|"
    r"varia|variano|risulta|risultano|tende|tendono|mostra|offre|ricorda)\b")
_MODALE_INGLESE = re.compile(r"^(?:may|can|must|should|might)\s+be\b")
_PARTICIPIO_INGLESE = re.compile(r"^(?:ranging|tending|varying|taking|depending|from)\b")


def _forma_della_citazione(valore: str, lingua: str) -> str:
    """«aggettivo», «relativa», «verbo» o «participio»."""
    v = _senza_accenti(valore).strip().lower()
    if v.startswith("che ") or v.startswith("che,") or v.startswith("which "):
        return "relativa"
    if lingua == "en":
        if _MODALE_INGLESE.match(v):
            return "verbo"
        if _PARTICIPIO_INGLESE.match(v):
            return "participio"
        return "aggettivo"
    if _VERBO_ITALIANO.match(v):
        return "verbo"
    return "aggettivo"


def _frase_di_citazione(lex: Lessico, lingua: str, seme: int, ambito: str,
                        valore: str) -> str:
    chiave = f"disciplinare_{ambito}"
    forma = _forma_della_citazione(valore, lingua)
    if forma == "relativa":
        return lex.frase("corpo", f"{chiave}_relativa", lingua=lingua,
                         seme=_seme_per(seme, chiave), valore=valore)
    if forma == "verbo":
        return lex.frase("corpo", "disciplinare_verbo", lingua=lingua,
                         seme=_seme_per(seme, chiave), valore=valore)
    forme = lex.varianti("corpo", chiave, lingua) or lex.varianti("corpo", chiave)
    parole_valore = {w for w in re.findall(r"[a-z]{5,}", _senza_accenti(valore).lower())}

    def regge(modello: str) -> bool:
        # Una parola che sta sia nella forma sia nella citazione e' una
        # ripetizione: «Il sapore è ... di sapore pieno», «The taste is ...
        # of full taste».
        fisse = {w for w in re.findall(r"[a-z]{5,}", _senza_accenti(modello).lower())}
        if fisse & parole_valore:
            return False
        if forma == "participio":
            return ", {valore}" in modello
        return True

    ammesse = [m for m in forme if regge(m)]
    if not ammesse:
        ammesse = [m for m in forme if ", {valore}" in m] or forme[:1]
    modello = ammesse[_seme_per(seme, chiave) % len(ammesse)]
    return modello.format(valore=valore)


# Le parole con cui una citazione NON puo' finire. Il campo del disciplinare in
# archivio e' stato tagliato a un numero di caratteri quando lo si e' estratto,
# e a volte finisce a meta' inciso: «rosso rubino intenso, scuro, un» -
# «brillante, dal». Letto ad alta voce e' un inciampo. Si toglie l'ultimo
# inciso quando finisce con una di queste.
# Le forme elise - «all'», «dall'», «l'» - stanno qui senza l'apostrofo, e
# l'apostrofo si toglie prima del confronto: undici campi in archivio finiscono
# proprio cosi', «giallo ambrato, all'».
_CODA_TRONCA = frozenset(
    "un una uno il lo la i gli le l dal dalla dallo dai dalle del della dello "
    "dei delle di da con e ed o al alla allo ai alle a in nel nella per piu "
    "tendente talvolta anche all dall dell nell sull d quell coll "
    "the a an of with and or to from more".split())


def _senza_doppioni_di_elenco(voci: list[str]) -> list[str]:
    """Da un elenco toglie le voci che ne ripetono un'altra con un'aggiunta.

    Il registro elenca le sfumature ammesse - «giallo paglierino, giallo
    paglierino carico, giallo paglierino scarico» - e X-Wines gli abbinamenti
    - «dolci, dolci alla frutta, frutta». Detti a voce diventano «straw
    yellow, deep straw yellow and light straw yellow»: vero, e insopportabile.

    Si tiene la prima e si scartano quelle che la contengono tutta: dire
    «giallo paglierino» non afferma niente che il registro non dica, dire
    tre volte «giallo paglierino» non aggiunge niente a chi ascolta.
    """
    tenute: list[str] = []
    parole_tenute: list[set[str]] = []
    for voce in voci:
        parole = {w for w in re.findall(r"[a-zà-ÿ]{3,}", _senza_accenti(voce).lower())}
        if not parole:
            tenute.append(voce)
            continue
        if any(p <= parole or parole <= p for p in parole_tenute):
            continue
        tenute.append(voce)
        parole_tenute.append(parole)
    return tenute


def _senza_coda_tronca(testo: str) -> str:
    testo = testo.replace("’", "'")

    def ultima_parola(pezzo: str) -> str:
        parole = _senza_accenti(pezzo).lower().rstrip(". ").split()
        return parole[-1].rstrip("'") if parole else ""

    pezzi = [x.strip() for x in testo.split(",")]
    while len(pezzi) > 1 and ultima_parola(pezzi[-1]) in _CODA_TRONCA:
        pezzi.pop()
    parole = ", ".join(pezzi).split()
    # «...violacei e dall'»: tolto «dall'» resta «e», e si toglie anche lei.
    while len(parole) > 1 and ultima_parola(parole[-1]) in _CODA_TRONCA:
        parole.pop()
    return " ".join(parole).rstrip(" ,")


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
    pezzi = [_apertura(f, lex, lingua, seme)]
    # Il produttore, quando si e' letto ma il vino non si sa. Al livello
    # «vino» sta gia' dentro l'apertura - «il "Cannubi" di Marchesi di
    # Barolo» - e ripeterlo sarebbe goffo; piu' in basso non lo diceva
    # nessuno, e si buttava via la cosa piu' identificante dell'etichetta.
    if f.cantina and f.livello is not Livello.VINO:
        pezzi.append(lex.frase("apertura", "cantina_sola", lingua=lingua,
                               seme=_seme_per(seme, "cantina_sola"),
                               cantina=f.cantina))
    testo = " ".join(pezzi + _corpo(f, lex, lingua, seme)).strip()
    if lingua == "it":
        # «abbinato a antipasti»: davanti a un'altra a l'italiano vuole «ad»,
        # e la voce sintetica legge lo iato. Quattromila record cominciano
        # gli abbinamenti con «antipasti».
        testo = re.sub(r"\b([Aa]) (?=[aA])", lambda m: m.group(1) + "d ", testo)
    return testo


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


def _abbastanza_per_il_modello(f: Fatti) -> bool:
    """C'e' abbastanza, in questi fatti, perche' un modello piccolo racconti
    senza riempire i buchi da solo?

    La risposta e' una sola, ed e' misurata: **la citazione del registro**.
    Su 210 bottiglie stratificate, italiano, modello v6:

        con la citazione     84 su 85 passano la verifica   98,8 %
        senza la citazione  104 su 125                      83,2 %

    E non e' solo il conteggio. Letti a mano, i testi senza citazione sono
    quelli in cui il modello inventa i piatti - «si serve bene con pesce,
    verdure e verdoli», dove «verdoli» non e' nemmeno una parola - e mette i
    cibi al posto dei profumi: «note sensoriali tipiche di manzo, cacciagione,
    agnello e pasta». Quelli con la citazione sono buoni:
    «Aglianico e Montepulciano, i vitigni del grande rosso del Sud, fra
    Taurasi e Vulture. Il disciplinare lo vuole rosa piu' o meno intenso...»

    La citazione non e' un ingrediente qualunque: e' l'unico pezzo di prosa
    VERA che i fatti contengono, scritta da un consorzio per quel vino. Con
    quella davanti il modello ha qualcosa da riformulare; senza, ha un
    elenco di campi e la tentazione di scrivere un vino qualunque.

    Copre il 45 % dell'archivio - un vino su due che si incontra - e l'altra
    meta' la racconta la composizione, che non inventa mai.
    """
    return bool(f.disciplinare)


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
        gabbia: bool = False,
    ) -> None:
        from .matcher import PERCORSO_DB

        self.percorso = Path(percorso_db) if percorso_db else PERCORSO_DB
        self.genera = genera          # None = nessun modello disponibile
        self.lingua = lingua
        # Quale forma di prompt vuole il modello che c'e' dietro: vedi
        # `prompt_addestrato`. Sbagliarla costa il doppio del tempo e tutta la
        # qualita' che l'addestramento aveva comprato.
        self.modello_addestrato = modello_addestrato
        # La gabbia: vedi `amelie.gabbia`. Sta a FALSE, ed e' una misura che
        # ha rovesciato la precedente - su trenta bottiglie facili sembrava
        # guadagnare tre testi, su duecentodieci stratificate ne perde otto e
        # sui record poveri produce italiano rotto. Chi la vuole deve dare un
        # `genera` che accetti la grammatica come secondo argomento.
        self.gabbia = gabbia
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
        """Da dove far venire il racconto.

        Nel modo «archivio» (`preferisci_modello` falso) da un posto solo: la
        composizione dai fatti, `template`. Nel modo «generativa»:

        1. il modello dal vivo, verificato, due tentativi;
        2. il testo pronto per QUESTO record, se c'e', verificato anch'esso;
        3. la composizione dai fatti.

        Il testo pronto e' solo quello del record esatto, non dei gradini di
        ripiego: di un vino riconosciuto fino al produttore si conoscono corpo,
        acidita' e abbinamenti suoi, e raccontarlo col testo generico del suo
        vitigno - scritto prima, in un'altra forma, senza nemmeno il nome
        dell'uva - sarebbe buttarli via. Successo, su un Gavi: usciva la
        scheda del Cortese senza mai dire Cortese.
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
                      and f.livello is not Livello.GENERICO
                      and _abbastanza_per_il_modello(f))
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
            if (pronto := self._dalla_cache(f, solo_esatto=True)) is not None:
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
            # Quarantotto testi pronti sono stati scritti quando il vitigno
            # «na» del registro passava per un'uva: «Nasce da na.», «It is
            # made from na.». Si saltano come quelli che inventano.
            if _UVA_FINTA.search(r["testo"]):
                log.warning("cache %s/%s scartata: nomina un vitigno che non c'e'",
                            ambito, ident)
                continue
            apertura = _apertura(f, self.lex, self.lingua, seme_di(f))
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

    def racconta_a_frasi(self, f: Fatti, *,
                         preferisci_modello: bool = False) -> Iterator[str]:
        """Le frasi del racconto, una per volta, appena sono pronte E verificate.

        Vale la stessa regola di `racconta`: senza `preferisci_modello` il
        modello non parla, e le frasi sono quelle della composizione. Nessuno
        chiama questa via dal dispositivo oggi, ma una porta aperta in una
        classe che dichiara una garanzia e' una garanzia a meta'.

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
        apertura = _apertura(f, self.lex, self.lingua, seme_di(f))
        if apertura:
            yield apertura
        if (f.vuoto or self.genera is None or not preferisci_modello
                or f.livello is Livello.GENERICO):
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
        grammatica = None
        if self.gabbia:
            from .gabbia import gabbia_di
            grammatica = gabbia_di(f, self.lingua)
        for tentativo in (1, 2):
            try:
                domanda = (prompt_addestrato(f, self.lingua) if self.modello_addestrato
                           else prompt(f, lingua=self.lingua))
                testo = (self.genera(domanda, grammatica) if grammatica
                         else self.genera(domanda)) or ""
                testo = testo.strip()
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
