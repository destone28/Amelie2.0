# -*- coding: utf-8 -*-
"""Le due fonti dell'Unione europea: il registro eAmbrosia e i documenti unici.

Tutte e due sono © Unione europea, riutilizzabili con licenza CC BY 4.0
(Decisione 2011/833/UE). Gli snapshot stanno in data/sources/, descritti in
data/sources/LEGGIMI.md.

## Il registro: le denominazioni che figshare non ha

`eambrosia_it_wine.tsv` elenca le 532 indicazioni geografiche italiane del vino,
una per riga, con il numero di fascicolo che fa da chiave comune con figshare:

    EUGI...  Cesanese del Piglio|Piglio  PDO-IT-A0680  PDO  1  1973-09-18  ...

Da qui vengono le 124 denominazioni che figshare non conosce (119 IGP e 5 DOP)
e, per tutte, la menzione italiana: DOCG, DOC o IGT. Il registro distingue DOP
da IGP ma non DOCG da DOC: l'elenco delle DOCG sta in `docg.txt`, un nome per
riga.

## I documenti unici: colore, odore e sapore ufficiali

`documenti_unici.jsonl` contiene il testo del documento unico di ogni
denominazione, estratto dal PDF pubblicato nel registro. Il testo ha perso righe
e colonne; gli unici ancoraggi affidabili sono le due formule fisse del modulo
UE:

    «Breve descrizione testuale»   -> inizio della descrizione organolettica
    «Caratteristiche analitiche»   -> fine

Fra le due stanno colore, odore e sapore di ogni tipologia, come li scrive il
disciplinare: sono le citazioni che il racconto riporta, e finiscono nella
tabella `tipologia_ue`.

Il nome della tipologia e' la parte fragile. Sta nell'intestazione di pagina,
che nel testo appiattito finisce in mezzo ai parametri di legge:

    ... Titolo alcolometrico FASCICOLO TECNICO 4 /17 Numero di fascicolo:
    PDO-IT-A0880-AM02 Abruzzo Cococciola - Abruzzo Cococciola superiore
    Abruzzo Malvasia - Abruzzo Malvasia superiore effettivo minimo (in % vol):

Cercarlo non funziona, perche' non se ne conosce la forma. Lo si trova al
contrario: si taglia il testo su ogni parola del modulo UE - titolo,
alcolometrico, minimo, fascicolo... - e quel che resta in mezzo sono i titoli.
Le voci trovate si assegnano ai blocchi nell'ordine in cui compaiono, con il
colore come controllo: una voce che dice «bianco» non descrive un rubino.

A un blocco su due il documento non offre alcun titolo, e allora si ripete
l'ultimo visto. Quel nome e' un'ipotesi, e `nome_incerto` lo dice: chi deve
scegliere fra due descrizioni non ci si puo' appoggiare. Le descrizioni e i
parametri di legge invece sono sempre quelli del blocco, e sono corretti.

## Le chiavi

Le denominazioni del registro si agganciano a quelle gia' in archivio per
numero di fascicolo, che e' lo stesso documento da entrambe le parti. I
documenti unici si agganciano al registro per nome: il primo nome del documento
contro tutti i nomi del registro, nell'ordine del registro.
"""
from __future__ import annotations

import ast
import csv
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SORGENTI = Path(__file__).resolve().parent / "sources"
REGISTRO = SORGENTI / "eambrosia_it_wine.tsv"
DOCUMENTI = SORGENTI / "documenti_unici.jsonl"
DOCG = SORGENTI / "docg.txt"


def chiave(s: str) -> str:
    """Minuscole, senza accenti, solo lettere e cifre separate da uno spazio.

    E' la chiave con cui si confrontano i nomi FRA LE FONTI, non quella con
    cui il dispositivo cerca: per quella c'e' `amelie.text.normalizza`.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ------------------------------------------------------------------ registro

@dataclass
class VoceRegistro:
    nomi: list[str]           # il primo e' quello ufficiale
    fascicolo: str            # PDO-IT-A0680
    tipo: str                 # DOP | IGP
    menzione: str             # DOCG | DOC | IGT

    @property
    def nome(self) -> str:
        return self.nomi[0]


def leggi_registro(percorso: Path = REGISTRO, docg: Path = DOCG) -> list[VoceRegistro]:
    """Le righe del registro, nell'ordine del file.

    Colonne: identificativo GI, nomi separati da «|», fascicolo, PDO o PGI,
    numero di categorie, data di protezione, scheda, consorzio. Servono le
    prime quattro.
    """
    elenco_docg = {chiave(r) for r in docg.read_text(encoding="utf-8").splitlines()
                   if r.strip()} if docg.exists() else set()
    voci = []
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        campi = riga.split("\t")
        if len(campi) < 8:
            continue
        _gi, nomi, fascicolo, tipo = campi[:4]
        nomi = [n for n in nomi.split("|") if n]
        if not nomi:
            continue
        if tipo != "PDO":
            tipo_ue, menzione = "IGP", "IGT"
        else:
            tipo_ue = "DOP"
            menzione = "DOCG" if any(chiave(n) in elenco_docg for n in nomi) else "DOC"
        voci.append(VoceRegistro(nomi, fascicolo, tipo_ue, menzione))
    return voci


def carica_registro(con: sqlite3.Connection, voci: list[VoceRegistro],
                    normalizza) -> int:
    """Aggiunge le denominazioni che mancano e scrive la menzione su tutte.

    Le nuove vanno in fondo, nell'ordine del registro, e hanno come nome il
    primo del registro. Ritorna quante ne ha aggiunte.
    """
    esistenti = dict(con.execute(
        "SELECT codice, id FROM denominazione WHERE codice IS NOT NULL"))
    nuove = 0
    for v in voci:
        did = esistenti.get(v.fascicolo)
        if did is None:
            did = con.execute(
                "INSERT INTO denominazione(codice, nome, nome_norm, tipo, fonte_id)"
                " VALUES (?,?,?,?,?)",
                (v.fascicolo, v.nome, normalizza(v.nome), v.tipo, "eambrosia")).lastrowid
            esistenti[v.fascicolo] = did
            nuove += 1
        con.execute("UPDATE denominazione SET menzione = ? WHERE id = ?", (v.menzione, did))
    return nuove


# --------------------------------------------------- vitigni per il parser

# Sinonimi di X-Wines -> nome italiano. Servono al parser, che riconosce come
# titolo di tipologia anche un'intestazione fatta del solo vitigno
# («Chardonnay», «Riesling renano»), e alla tabella `vitigno`, dove il nome
# italiano va aggiunto se manca. Pinot Noir e Pinot Nero sono lo stesso vitigno.
SINONIMI_VITIGNO = {
    "Glera/Prosecco": "Glera", "Prosecco": "Glera",
    "Pinot Noir": "Pinot Nero", "Pinot Nero": "Pinot Nero",
    "Pinot Blanc": "Pinot Bianco", "Pinot Bianco": "Pinot Bianco",
    "Pinot Gris": "Pinot Grigio", "Pinot Grigio": "Pinot Grigio",
    "Syrah/Shiraz": "Syrah", "Shiraz": "Syrah",
    "Muscat/Moscato": "Moscato", "Muscat": "Moscato", "Muscat Blanc": "Moscato bianco",
    "Sauvignon Blanc": "Sauvignon", "Friulano/Sauvignonasse": "Friulano",
    "Sauvignonasse": "Friulano",
    "Trebbiano Toscano": "Trebbiano toscano", "Trebbiano": "Trebbiano",
    "Refosco dal Peduncolo Rosso": "Refosco dal peduncolo rosso",
    "Canaiolo Nero": "Canaiolo nero", "Malvasia Nera": "Malvasia nera",
    "Ribolla Gialla": "Ribolla gialla",
}


def vitigni_xwines(percorso: Path) -> list[str]:
    """I vitigni di X-Wines col nome italiano, nell'ordine in cui compaiono."""
    if not percorso.exists():
        return []
    csv.field_size_limit(10 ** 7)
    visti: dict[str, None] = {}
    with percorso.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                uve = ast.literal_eval(r.get("Grapes") or "[]")
            except (ValueError, SyntaxError):
                continue
            for g in uve if isinstance(uve, (list, tuple)) else []:
                n = str(g).strip()
                visti.setdefault(SINONIMI_VITIGNO.get(n, n), None)
    return list(visti)


def aggiungi_vitigni_mancanti(con: sqlite3.Connection, nomi: list[str],
                              normalizza) -> int:
    """Inserisce i nomi italiani dei vitigni che l'archivio non ha ancora.

    X-Wines scrive «Muscat/Moscato» e figshare «Moscato Bianco»: il nome che
    un'etichetta italiana porta, «Moscato», altrimenti non c'e'.
    """
    noti = {normalizza(r[0]) for r in con.execute("SELECT nome FROM vitigno")}
    n = 0
    for nome in nomi:
        k = normalizza(nome)
        if k not in noti:
            con.execute("INSERT INTO vitigno(nome, nome_norm) VALUES (?,?)", (nome, k))
            noti.add(k)
            n += 1
    return n


# ----------------------------------------------- parser del documento unico

INIZIO = re.compile(r"(?:Breve\s+descrizione\s+testuale|Caratteristich\w*\s+organolettich\w*)"
                    r"\s*:?\s*", re.I)
FINE = re.compile(r"Caratteristich\w*\s+analitich\w*|Numero\s+di\s+fascicolo", re.I)
RUMORE = re.compile(
    r"(FASCICOLO\s+TECNICO\s*\d*\s*/?\d*|Numero\s+di\s+fascicolo\s*:\s*\S+|"
    r"Ref\.\s*Ares\(\d{4}\)\d+\s*-\s*[\d/]+|Domanda\s+di\s+una\s+nuova\s+modifica|"
    r"DOP\s*-\s*Denominazione\s+di\s+origine\s+protetta|"
    r"IGP\s*-\s*Indicazione\s+geografica\s+protetta|"
    r"Tenore\s+massimo\s+di\s+anidride\s+solforosa[^:]*:|"
    r"Acidit[àa]\s+volatile\s+massima[^:]*:|"
    r"Titolo\s+alcolometrico\s+(?:totale\s+massimo|effettivo\s+minimo)[^:]*:|"
    r"Acidit[àa]\s+totale\s+minima\s*:\s*[\d,\.]+\s*in\s+(?:grammi|milliequivalenti)[^;\n]*|"
    r"\(in\s*%\s*vol\)\s*:|\(it\)|«|»|“|”)", re.I)

# Il vocabolario del modulo UE. Ogni parola qui dentro e' un TAGLIO: il nome di
# una tipologia non la contiene mai, e nel PDF appiattito i nomi stanno proprio
# in mezzo a queste.
PAROLE_DEL_MODULO = set("""
titolo alcolometrico volumico totale totali effettivo minimo minima massimo massima
acidita volatile fissa estratto riduttore ridutt zuccheri riduttori
anidride solforosa tenore grammi grammo litro litri milliequivalenti milligrammi vol
espresso acido tartarico percentuale
fascicolo tecnico numero ref ares allegato pagina
breve descrizione descrizioni testuale testuali caratteristiche analitiche generali
domanda nuova modifica unica unico documento
denominazione origine protetta indicazione geografica protette dop igp doc docg igt
pratiche vinificazione enologiche rese massime resa produzione ettaro
categoria categorie prodotto prodotti vitivinicolo vitivinicoli
zona delimitata legame ambiente etichettatura confezionamento
menzione menzioni consentita consentite consetita prevista previste
facoltativa facoltativo registrare specificazione
""".split())

# «1. Vino», «4. Vino spumante di qualita'»: l'elenco delle categorie UE non e'
# un titolo. Si toglie a parte, perche' «vino» da sola serve altrove.
_CATEGORIE = re.compile(r"\b\d{1,2}\.\s*(?:Vino|Mosto)\b[^.\d]{0,60}", re.I)
_PAROLA = re.compile(r"[A-Za-zÀ-ÿ'’]+")

_ROSSO = re.compile(r"\b(rosso|rossi|rubino|granato|porpora|violaceo)\b", re.I)
_ROSATO = re.compile(r"\b(rosato|rosa|cerasuolo|chiaretto|ramato)\b", re.I)
_BIANCO = re.compile(r"\b(bianco|bianchi|paglierino|giallo|dorato|verdognolo|verdolino|"
                     r"ambrato|ambra|oro)\b", re.I)

# Parole che un titolo puo' contenere ma su cui non puo' ne' cominciare ne'
# finire: il taglio sul vocabolario del modulo lascia spesso code sospese,
# «Alto Adige Bianco passito e», «Alto Adige con o senza».
_SOSPESE = {"e", "ed", "o", "od", "con", "senza", "di", "del", "dello", "della", "dei",
            "delle", "da", "dal", "dalla", "in", "nel", "nella", "nelle", "nei", "a",
            "al", "alla", "per", "il", "lo", "la", "i", "gli", "le", "l", "un", "una",
            "anche", "sulla", "su", "che", "come", "sia", "oppure", "ovvero"}
# Parole di servizio che il modulo mette dentro i titoli: si tolgono e basta.
_DI_SERVIZIO = {"tipologia", "tipologie", "menzione", "menzioni"}


def _spoglia(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _pulisci(t: str) -> str:
    t = t.replace("­", "").replace("’", "'")
    t = RUMORE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip(" .;:,-")


def _colore_detto(t: str | None) -> str | None:
    """Il colore che questo testo dichiara, se ne dichiara uno solo."""
    t = t or ""
    v = {c for c, p in (("r", _ROSSO), ("p", _ROSATO), ("b", _BIANCO)) if p.search(t)}
    return v.pop() if len(v) == 1 else None


def _tratti(coda: str) -> list[str]:
    """Il testo spezzato su ogni parola del modulo: in mezzo restano i titoli."""
    coda = RUMORE.sub(" | ", coda)
    coda = _CATEGORIE.sub(" | ", coda)
    fuori, corrente = [], []
    for pezzo in re.split(r"([A-Za-zÀ-ÿ'’]+|[^A-Za-zÀ-ÿ'’]+)",
                          coda):
        if not pezzo:
            continue
        if _PAROLA.fullmatch(pezzo):
            if _spoglia(pezzo).lower() in PAROLE_DEL_MODULO:
                fuori.append(corrente)
                corrente = []
            else:
                corrente.append(pezzo)
        elif re.search(r"[:;|\n]|\d", pezzo):
            fuori.append(corrente)
            corrente = []
        else:
            corrente.append(pezzo.strip() or " ")
    fuori.append(corrente)
    return [" ".join(w for w in t if w.strip()) for t in fuori if t]


def _ripulisci_voce(v: str) -> str:
    parole = [p for p in v.split() if _spoglia(p).lower().strip("'’") not in _DI_SERVIZIO]
    while parole and _spoglia(parole[0]).lower().strip("'’.,;:") in _SOSPESE:
        parole.pop(0)
    while parole and _spoglia(parole[-1]).lower().strip("'’.,;:") in _SOSPESE:
        parole.pop()
    return " ".join(parole).strip(" -–—.,;:")


def _voci(coda: str, radice: str, vitigni: tuple[str, ...]) -> list[str]:
    """Le voci d'intestazione dentro un tratto di testo.

    Un'intestazione di pagina ne elenca piu' d'una, e le scrive di seguito:
    «Abruzzo Cococciola - Abruzzo Cococciola superiore Abruzzo Malvasia - ...».
    Si spezza a ogni ricorrenza del nome della denominazione che NON sia
    preceduta da un trattino, perche' il trattino lega le due forme di una voce
    sola - base e superiore - che nel disciplinare condividono la descrizione.
    """
    trovate = []
    for tratto in _tratti(coda):
        tratto = re.sub(r"\s+(['’])\s*", r"\1", tratto)
        tratto = re.sub(r"\(\s*", "(", re.sub(r"\s*\)", ")", tratto)).strip(" -–—.,;:")
        if not (2 <= len(tratto.split()) <= 14):
            continue
        tl = _spoglia(tratto).lower()
        if radice and radice in tl:
            tagli = [m.start() for m in re.finditer(re.escape(radice), tl)]
            inizi = [t for i, t in enumerate(tagli)
                     if not (i and tratto[:t].rstrip().endswith(("-", "–", "—")))]
            for i, t in enumerate(inizi):
                fine = inizi[i + 1] if i + 1 < len(inizi) else len(tratto)
                v = _ripulisci_voce(tratto[t:fine].strip(" -–—.,;:"))
                if 2 <= len(v.split()) <= 10:
                    trovate.append(v)
        elif any(f" {v} " in f" {tl} " for v in vitigni):
            v = _ripulisci_voce(tratto)
            if 2 <= len(v.split()) <= 10:
                trovate.append(v)
    return trovate


def _blocchi(testo: str) -> list[tuple[str, str]]:
    """(testo che precede, descrizione) per ogni blocco organolettico."""
    out, pos = [], 0
    for m in INIZIO.finditer(testo):
        coda = testo[pos:m.start()]
        resto = testo[m.end():]
        f = FINE.search(resto)
        desc = _pulisci(resto[:f.start()] if f else resto[:2500])
        pos = m.end() + (f.start() if f else 0)
        if len(desc) >= 25:
            out.append((coda, desc))
    return out


# Un formato diverso: nessuna formula d'intestazione, i campi stanno in linea.
_ANCORA_COLORE = re.compile(r"\bcolore\s*:", re.I)
_STOP = re.compile(r"Caratteristich\w*\s+analitich\w*|\d\.\s*PRATICHE|"
                   r"PRATICHE\s+DI\s+VINIFICAZIONE|Numero\s+di\s+fascicolo|"
                   r"\bRese\s+massime\b|Domanda\s+di\s+una\s+nuova\s+modifica", re.I)
_SEZIONE = re.compile(r"\d{1,2}\.\s*DESCRIZIONE\s+DEI\s+VINI\s*:?", re.I)


def _ripiego(testo: str, nome_den: str, vitigni: tuple[str, ...]):
    """Per i documenti senza alcuna formula d'intestazione."""
    out = []
    for m in _ANCORA_COLORE.finditer(testo):
        resto = testo[m.start():]
        f = _STOP.search(resto)
        desc = _pulisci(resto[:f.start()] if f else resto[:1400])
        if len(desc) < 25:
            continue
        coda = testo[:m.start()]
        ms = list(_SEZIONE.finditer(coda))
        if ms:
            coda = coda[ms[-1].end():]
        radice = _spoglia(nome_den.split("|")[0]).lower().split()
        v = _voci(coda, radice[0] if radice else "", vitigni)
        out.append((v[-1] if v else nome_den.split("|")[0], desc, not v))
    return out


def tipologie(testo: str, nome_den: str, vitigni: tuple[str, ...] = ()):
    """[(nome, descrizione, nome_incerto)] per ogni blocco del documento.

    Le voci d'intestazione si raccolgono man mano e si consumano in ordine: la
    prima voce non ancora usata tocca al primo blocco che arriva. Il colore fa
    da controllo - una voce che dice «bianco» non puo' descrivere un rubino, e
    si salta - ed e' l'unica verifica indipendente che il documento offra.

    Dove non c'e' nessuna voce da consumare si ripete l'ultima, e il nome esce
    incerto: e' l'ipotesi piu' ragionevole, non un dato letto.
    """
    base = nome_den.split("|")[0]
    parole = _spoglia(base).lower().split()
    radice = parole[0] if parole else ""
    vitigni = tuple(vitigni)
    blocchi = _blocchi(testo)
    if not blocchi:
        return _ripiego(testo, nome_den, vitigni)

    viste, disponibili, out = set(), [], []
    for coda, desc in blocchi:
        for v in _voci(coda, radice, vitigni):
            k = _spoglia(v).lower()
            if k not in viste:
                viste.add(k)
                disponibili.append(v)
        colore = _colore_detto(desc[:130])
        scelta = None
        if disponibili:
            if colore:
                for i, v in enumerate(disponibili):
                    suo = _colore_detto(v.replace(base, ""))
                    if suo is None or suo == colore:
                        scelta = disponibili.pop(i)
                        break
            else:
                scelta = disponibili.pop(0)
        if scelta is None:
            out.append(((out[-1][0] if out else base)[:110], desc, True))
        else:
            out.append((scelta[:110], desc, False))
    return out


_CAMPI = [
    ("desc_colore", r"colore\s*:?\s*(?:e'|è)?\s*(.*?)(?=;|\.\s|\bodore\b|\bprofumo\b|\bsapore\b"
                    r"|\bgusto\b|\bspuma\b|$)"),
    ("desc_odore", r"(?:odore|profumo|aroma)\s*:?\s*(?:e'|è)?\s*(.*?)(?=;|\.\s|\bsapore\b"
                   r"|\bgusto\b|\btitolo\b|$)"),
    ("desc_sapore", r"(?:sapore|gusto|al\s+gusto)\s*:?\s*(?:e'|è)?\s*(.*?)(?=;|\.\s"
                    r"|\btitolo\s+alcolometrico\b|\bestratto\b|$)"),
    ("desc_spuma", r"(?:spuma|perlage)\s*:?\s*(.*?)(?=;|\.\s|\bcolore\b|\bodore\b|$)"),
]
_NUMERI = [
    ("titolo_alcol_min", r"titolo\s+alcolometrico[^:;]{0,40}?minim[oa]\s*:?\s*([\d]+[,.]?\d*)"),
    ("acidita_min", r"acidit[àa]\s+totale\s+minima\s*:?\s*([\d]+[,.]?\d*)"),
    ("estratto_min", r"estratto\s+non\s+rid[^:;]{0,20}?minim[oa]\s*:?\s*([\d]+[,.]?\d*)"),
]


def campi(desc: str) -> dict:
    """Colore, odore, sapore, spuma e i minimi di legge di un blocco."""
    d, low = {}, desc.lower()
    for nome, pat in _CAMPI:
        m = re.search(pat, low, re.S)
        if m:
            v = re.sub(r"\s+", " ", m.group(1)).strip(" .;:,-")
            if 2 < len(v) < 400:
                d[nome] = v
    for nome, pat in _NUMERI:
        m = re.search(pat, low)
        if m:
            try:
                x = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            if 0 < x < 400:
                d[nome] = x
    return d


# -------------------------------------------- nomi, colori e menzioni finali

# Residui del modulo che l'estrazione lascia dentro i nomi.
RESIDUI = re.compile(
    r"(Caratteristich\w*\s+analitich\w*(\s+generali)?|anidride\s+solforosa[^,;]*|"
    r"\(in\s*(%\s*vol|milligrammi[^)]*|milliequivalenti[^)]*)\)|"
    r"\d{1,2}\.\s*DESCRIZIONE\s+DEI\s+VINI\s*:?|Tenore\s+massimo[^,;]*|"
    r"Titolo\s+alcolometrico[^,;]*|Acidit[àa]\s+(totale|volatile)[^,;]*|"
    r"minim[oa]\s*:|massim[oa]\s*:|g/l|milligrammi\s+per\s+litro|"
    r"Numero\s+di\s+fascicolo[^,;]*|FASCICOLO\s+TECNICO[^,;]*|Ref\.\s*Ares[^,;]*|"
    r"Domanda\s+di\s+una\s+nuova\s+modifica)", re.I)

# Parole spezzate dall'estrazione del PDF.
SPEZZATE = [(r"\bspuma\s+nte\b", "spumante"), (r"\bprofumo\s+tic([oi])\b", r"tipic\1"),
            (r"\bfrizza\s+nte\b", "frizzante"), (r"\bpersiste\s+nte\b", "persistente"),
            (r"\binte\s+nso\b", "intenso"), (r"\bpeglierino\b", "paglierino")]

COLORE_DA_TESTO = [
    ("Rosato", r"\bros(?:a|ato|é|e)\b|cerasuolo|chiaretto|rosa\s+(?:tenue|ciliegia|antico"
               r"|cerasuolo)"),
    ("Rosso", r"\brosso\b|rubino|granato|porpora|violaceo|amaranto|mattone"),
    ("Bianco", r"\bbianco\b|paglierino|giallo|dorato|verdognolo|ambrato|ambra|verdolino|oro"),
]
MENZIONI = ["gran selezione", "riserva", "superiore", "classico", "novello", "passito",
            "vendemmia tardiva", "liquoroso", "vin santo", "spumante", "frizzante",
            "metodo classico", "sottozona", "amabile", "dolce", "secco", "brut"]


def colore_da(desc_colore: str | None, nome: str | None = None) -> str | None:
    """Il colore si legge nel testo della descrizione; il nome e' un ripiego."""
    for col, pat in COLORE_DA_TESTO:
        if re.search(pat, desc_colore or "", re.I):
            return col
    for col, pat in COLORE_DA_TESTO:
        if nome and re.search(pat, nome, re.I):
            return col
    return None


def pulisci_nome(nome: str | None) -> str:
    n = RESIDUI.sub(" ", nome or "")
    for pat, rep in SPEZZATE:
        n = re.sub(pat, rep, n, flags=re.I)
    n = re.sub(r"[«»“”\"]", "", n)
    # L'estrazione dal PDF a volte perde l'apostrofo: «dellArgentario».
    n = re.sub(r"\b(dell|nell|all|sull|dall|d|l)(?=[A-ZÀ-Ý])", r"\1'", n)
    n = re.sub(r"\s+", " ", n).strip(" .;:,-")
    return n[:90]


def menzione_da(nome: str | None) -> str | None:
    nl = (nome or "").lower()
    trovate = [m for m in MENZIONI if m in nl]
    return " ".join(x.title() for x in trovate[:2]) or None


def sistema_nomi(righe: list[dict], nome_den: str) -> None:
    """Ricalcola nome, colore e menzione delle tipologie di UNA denominazione.

    Il colore si ricava dal testo della descrizione, che e' estratto bene, e
    non dal titolo. Tre cose svuotano di senso il nome estratto: il colore che
    dichiara contraddice il testo, non dice nulla piu' della denominazione,
    oppure e' gia' usato da un'altra tipologia e va numerato. In tutti e tre i
    casi il nome resta - serve da identificatore - ma `nome_incerto` dice che
    non distingue niente. Dove il nome non dice nulla lo si ricostruisce da
    denominazione, colore e menzione.
    """
    usati: dict[str, int] = {}
    for r in righe:
        pulito = pulisci_nome(r["nome"])
        colore = colore_da(r.get("desc_colore"), pulito)
        menz = menzione_da(pulito)
        incerto = r["nome_incerto"]
        # Un nome che dichiara un colore diverso da quello del testo e'
        # un'intestazione di pagina finita sul blocco sbagliato: si scarta.
        colore_nel_nome = None
        for cc, pp in COLORE_DA_TESTO:
            if pulito and re.search(pp, pulito, re.I):
                colore_nel_nome = cc
                break
        if colore and colore_nel_nome and colore_nel_nome != colore:
            pulito = ""
            incerto = 1
        if not pulito or chiave(pulito) == chiave(nome_den) or len(pulito) < 4:
            pulito = " ".join([nome_den] + ([colore] if colore else [])
                              + ([menz] if menz else []))
            incerto = 1
        k = chiave(pulito)
        if k in usati:
            usati[k] += 1
            pulito = f"{pulito} ({usati[k]})"
        else:
            usati[k] = 1
        r.update(nome=pulito, colore=colore, menzione=menz, nome_incerto=int(bool(incerto)),
                 _chiave=k)
    # Un nome numerato non distingue - ma non distingue nemmeno il primo del
    # gruppo, che il numero non ce l'ha: si marcano tutti.
    ripetuti = {k for k, n in usati.items() if n > 1}
    for r in righe:
        if r.pop("_chiave") in ripetuti:
            r["nome_incerto"] = 1


def tipologie_ue(voci: list[VoceRegistro], vitigni: list[str],
                 documenti: Path = DOCUMENTI) -> list[tuple[VoceRegistro, dict]]:
    """Le tipologie di tutti i documenti unici, gia' ripulite.

    Si tengono solo i blocchi che hanno almeno uno fra colore, odore, sapore e
    spuma: un blocco senza nessuno dei quattro non ha nulla da citare.
    """
    per_nome: dict[str, VoceRegistro] = {}
    for v in voci:
        for n in v.nomi:
            per_nome.setdefault(chiave(n), v)
    # I vitigni aiutano il parser a riconoscere i titoli fatti del solo
    # vitigno; i nomi corti («Uva», «Nero») troverebbero titoli ovunque.
    vit = tuple({chiave(n) for n in vitigni if n and len(n) >= 5})

    # Le tipologie si ripuliscono per denominazione, perche' la numerazione dei
    # nomi ripetuti vale dentro la stessa denominazione.
    per_voce: dict[int, tuple[VoceRegistro, list[dict]]] = {}
    ordine: list[tuple[VoceRegistro, dict]] = []
    for riga in documenti.read_text(encoding="utf-8").splitlines():
        d = json.loads(riga)
        if not d.get("d"):
            continue
        voce = per_nome.get(chiave(d["nome"].split("|")[0]))
        if voce is None:
            continue
        for nome, desc, incerto in tipologie(d["d"], d["nome"], vit):
            c = campi(desc)
            if not any(c.get(k) for k in ("desc_spuma", "desc_colore", "desc_odore",
                                            "desc_sapore")):
                continue
            t = dict(nome=nome[:110], nome_incerto=int(bool(incerto)), **c)
            per_voce.setdefault(id(voce), (voce, []))[1].append(t)
            ordine.append((voce, t))
    for voce, righe in per_voce.values():
        sistema_nomi(righe, voce.nome)
    return ordine


def carica_tipologie_ue(con: sqlite3.Connection, voci: list[VoceRegistro],
                        vitigni: list[str], documenti: Path = DOCUMENTI) -> tuple[int, int]:
    """Riempie `tipologia_ue`. Ritorna (tipologie, denominazioni coperte)."""
    per_codice = dict(con.execute(
        "SELECT codice, id FROM denominazione WHERE codice IS NOT NULL"))
    righe = []
    for voce, t in tipologie_ue(voci, vitigni, documenti):
        righe.append((per_codice.get(voce.fascicolo), t["nome"], t["nome_incerto"],
                      t["menzione"], t["colore"], t.get("desc_colore"), t.get("desc_odore"),
                      t.get("desc_sapore"), t.get("titolo_alcol_min"), t.get("acidita_min"),
                      t.get("estratto_min"), "documento_unico_ue"))
    con.executemany(
        "INSERT INTO tipologia_ue(denominazione_id, nome, nome_incerto, menzione, colore,"
        " desc_colore, desc_odore, desc_sapore, titolo_alcol_min, acidita_min,"
        " estratto_min, fonte_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", righe)
    return len(righe), len({r[0] for r in righe})
