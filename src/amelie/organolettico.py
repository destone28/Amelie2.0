"""Le citazioni dei disciplinari, rese in inglese.

Il database porta, per ogni tipologia di una denominazione, le tre descrizioni
ufficiali del disciplinare: colore, odore, sapore. Sono la cosa piu' preziosa
che abbiamo - nessuno le ha inventate, le ha scritte il consorzio - ma sono
scritte solo in italiano, e il dispositivo racconta anche in inglese.

Tradurle a mano non si puo': sono 6.363 citazioni, con 3.124 valori distinti.
Ma i valori distinti non sono materiale distinto. Spezzando le citazioni sui
separatori si ottengono 15.137 frammenti di 2.405 forme, e quelle forme sono
quasi tutte la stessa manciata di parole ricombinata: «giallo paglierino»,
«giallo paglierino piu' o meno intenso», «giallo paglierino con riflessi
verdognoli», «dal giallo paglierino al dorato». Elencare le combinazioni e' un
elenco senza fine; elencare gli atomi sono duecento voci.

Quindi: gli atomi stanno in data/lessico/organolettico.json, e qui stanno le
regole che li ricompongono - gli intervalli «da X a Y», le tendenze «tendente
al X», i riflessi, gli avverbi. Una citazione si traduce se tutti i suoi pezzi
si traducono.

Due cose che questo modulo non fa, di proposito.

La prima: non indovina. Un frammento che non si sa tradurre viene lasciato
cadere, e la citazione esce piu' corta. Una citazione piu' corta e' ancora
vera; una parola inventata dentro una citazione di un disciplinare non lo e'.
Gli intervalli sono trattati come un pezzo solo proprio per questo: mezzo «da
secco a dolce» direbbe una cosa falsa.

La seconda: il risultato non e' una citazione. «rosso rubino» reso «ruby red»
e' una nostra traduzione, non una parola del disciplinare, e va presentato
come tale. Chi usa questo modulo deve dirlo (vedi `Reso`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .text import spoglia_accenti

PERCORSO_PREDEFINITO = (
    Path(__file__).resolve().parents[2] / "data" / "lessico" / "organolettico.json"
)

# I campi del disciplinare. La stessa parola cambia senso a seconda del campo:
# «vivace» e' un colore vivido alla vista e una leggera effervescenza in bocca.
AMBITI = ("colore", "odore", "sapore")

# Dove si spezza una citazione. Sono i punti in cui il disciplinare elenca, e
# sono anche i punti in cui si puo' togliere un pezzo senza cambiare il senso
# dei pezzi rimasti. La «e» NON e' uno di questi: in «con note floreali e
# fruttate» lega due aggettivi dello stesso nome, e spezzando li' esce «with
# floral notes and fruity». La congiunzione si tratta dentro il frammento.
_SEPARATORI = re.compile(r"\s*[,;]\s*")

_SPAZI = re.compile(r"\s+")
_E = re.compile(r"\s+ed?\s+")

# Preposizioni articolate. L'ordine conta: se «a» viene prima di «ad»,
# «da secco ad abboccato» si spezza dentro la parola e l'intervallo si perde.
_DA = r"(?:dalla|dallo|dall'|dal|da|d')"
_A = r"(?:all'|alla|allo|al|ad|a)"

# Parole che stanno davanti in italiano e davanti anche in inglese: si
# traducono e si rimettono dove stavano.
_PREFISSI = {
    "talvolta": "sometimes",
    "talora": "sometimes",
    "a volte": "sometimes",
    "generalmente": "generally",
    "solitamente": "usually",
    "leggermente": "slightly",
    "lievemente": "slightly",
    "gradevolmente": "pleasantly",
    "piacevolmente": "pleasantly",
    "delicatamente": "delicately",
    "moderatamente": "moderately",
    "intensamente": "intensely",
    "finemente": "finely",
    "debolmente": "faintly",
    "giustamente": "properly",
    "abbastanza": "fairly",
    "molto": "very",
    "poco": "slightly",
    "anche": "also",
    "eventualmente": "possibly",
    "prevalentemente": "mainly",
    "particolarmente": "particularly",
    "eventuali": "possible",
    "eventuale": "possible",
    "lievi": "faint",
    "lieve": "faint",
    "leggeri": "light",
    "leggero": "light",
    "delicati": "delicate",
    "delicato": "delicate",
    "buon": "good",
    "buona": "good",
    "medio": "medium",
    "media": "medium",
    "discreto": "fair",
    "giusto": "proper",
    "giusta": "proper",
    "varie": "varying",
    "varia": "varying",
    "altrettanta": "equally",
    "altrettanto": "equally",
    "ben": "well",
    "bene": "well",
    "piu": "more",
    "meno": "less",
    "un": "a",
    "uno": "a",
    "una": "a",
    "un po'": "slightly",
    "tendenzialmente": "generally",
    "nettamente": "distinctly",
    "decisamente": "decidedly",
    "piuttosto": "rather",
}

# Nomi che in italiano si fanno seguire dall'aggettivo e in inglese lo vogliono
# davanti: «riflessi violacei» -> «purplish highlights».
_SI_ROVESCIA = (
    "riflessi",
    "sfumature",
    "orli",
    "note",
    "nota",
    "profumo",
    "profumi",
    "aroma",
    "aromi",
    "sentore",
    "sentori",
    "retrogusto",
    "gusto",
    "sapore",
    "bouquet",
    "spuma",
    "fondo",
)

# Nomi che reggono un complemento: «sentore di legno» -> «hint of wood».
_REGGE_DI = {
    "sentore": "hint",
    "sentori": "hints",
    "nota": "note",
    "note": "notes",
    "profumo": "scent",
    "profumi": "scents",
    "aroma": "aroma",
    "aromi": "aromas",
    "percezione": "a hint",
    "gusto": "taste",
    "retrogusto": "aftertaste",
    "sapore": "flavour",
    "fondo": "base note",
    "carattere": "character",
}

_MASSIMA_PROFONDITA = 8

# Quando il modificatore comincia con una di queste parole non vuole la virgola:
# «ruby red with purplish highlights», non «ruby red, with purplish highlights».
_SENZA_VIRGOLA = frozenset(("with", "of", "in", "to"))

# Cio' che in inglese non puo' stare davanti a un nome: «highlights tending to
# garnet», mai «tending to garnet highlights».
_POSPONE = frozenset(
    ("tending", "from", "through", "with", "of", "to", "when", "depending",
     "may", "ranging", "taking", "in", "but")
)


@dataclass(frozen=True)
class Reso:
    """Una citazione resa in un'altra lingua.

    `integrale` dice se e' passata tutta: se e' falso qualche frammento e'
    stato lasciato cadere, e il testo e' piu' corto dell'originale.

    `tradotto` dice che il testo non e' piu' una citazione. In italiano la
    citazione e' il disciplinare parola per parola e si puo' virgolettare; in
    inglese no, e chi la mostra deve dire che e' una traduzione.
    """

    testo: str
    integrale: bool
    tradotto: bool


class Organolettico:
    """Il vocabolario, con le regole che lo ricompongono."""

    def __init__(
        self,
        termini: dict[str, str],
        per_ambito: dict[str, dict[str, str]],
        nomi: frozenset[str] = frozenset(),
    ):
        self._termini = {_chiave(k): v for k, v in termini.items()}
        self._nomi = frozenset(_chiave(n) for n in nomi)
        self._per_ambito = {
            a: {_chiave(k): v for k, v in d.items()} for a, d in per_ambito.items()
        }
        self._prefissi = {_chiave(k): v for k, v in _PREFISSI.items()}

    # -- interfaccia ------------------------------------------------------

    def rendi(self, testo: str, ambito: str, lingua: str = "en") -> Reso | None:
        """La citazione `testo` del campo `ambito`, resa in `lingua`.

        In italiano non c'e' niente da rendere: la citazione e' gia' quella, e
        torna com'e'. Torna None se non ne resta niente di traducibile.
        """
        testo = _SPAZI.sub(" ", (testo or "").strip().rstrip(".").strip())
        if not testo:
            return None
        if lingua == "it":
            return Reso(testo, integrale=True, tradotto=False)

        # Da qui in giu' si lavora su testo spoglio: le regole sono scritte in
        # italiano senza accenti, come le chiavi del vocabolario, cosi' non c'e'
        # un solo posto dove «piu'» e «piu» possano divergere.
        pezzi = [p.strip() for p in _SEPARATORI.split(_chiave(testo)) if p and p.strip()]
        resi, caduti = [], False
        for p in pezzi:
            reso = self._frammento(p, ambito)
            if reso is not None:
                resi.append(reso)
                continue
            caduti = True
            # Se il pezzo non passa intero, si prova a salvarne le meta' unite
            # dalla «e»: una congiunzione e' un elenco, e un elenco si puo'
            # accorciare. Un intervallo o un'alternativa no, e infatti quelli
            # restano dentro `_frammento`, dove o passano tutti o cadono tutti.
            resi.extend(
                t for t in (self._frammento(x, ambito) for x in _E.split(p)) if t
            )
        if not resi:
            return None
        return Reso(_elenca(resi), integrale=not caduti, tradotto=True)

    # -- il lavoro --------------------------------------------------------

    def _e_nome(self, parola: str) -> bool:
        """Nel sintagma basta che ci sia un nome: «buon corpo» e' un corpo."""
        return any(p in self._nomi for p in _chiave(parola).split())

    def _cerca(self, parola: str, ambito: str) -> str | None:
        k = _chiave(parola)
        trovato = self._per_ambito.get(ambito, {}).get(k) or self._termini.get(k)
        if trovato or " " in k or len(k) < 4 or k[-1] not in "oaie":
            return trovato
        # Una parola sola che finisce in vocale e' quasi sempre un aggettivo, e
        # l'italiano ne ha quattro forme: «ambrato, ambrati, ambrate, ambrata».
        # Elencarle tutte nel vocabolario sarebbe quadruplicarlo per niente.
        for vocale in "oaie":
            altro = k[:-1] + vocale
            trovato = self._per_ambito.get(ambito, {}).get(altro) or self._termini.get(altro)
            if trovato:
                return trovato
        return None

    def _frammento(self, f: str, ambito: str, profondita: int = 0) -> str | None:
        f = f.strip().strip(".").strip()
        if not f or profondita > _MASSIMA_PROFONDITA:
            return None
        # Le cifre nelle citazioni sono sempre residui dei minimi di legge
        # («titolo alcolometrico minimo: 11»), che non sono descrizioni.
        if any(c.isdigit() for c in f):
            return None
        diretto = self._cerca(f, ambito)
        if diretto:
            return diretto
        for regola in self._regole():
            reso = regola(f, ambito, profondita + 1)
            if reso:
                return reso
        return None

    @lru_cache(maxsize=1)
    def _regole(self):
        return (
            self._intervallo,
            self._fino_a,
            self._tendenza,
            self._invecchiamento,
            self._contrasto,
            self._verso,
            self._verbo,
            self._menzione,
            self._secondo,
            self._complemento,
            self._rovescia,
            self._congiunzione,
            self._alternativa,
            self._prefisso,
            self._sintagma,
        )

    def _intervallo(self, f: str, ambito: str, p: int) -> str | None:
        """«dal secco al dolce» -> «from dry to sweet». Pezzo unico: mezzo
        intervallo direbbe una cosa che il disciplinare non dice."""
        m = re.fullmatch(_DA + r"\s*(.+?)\s+" + _A + r"\s*(.+)", f)
        if not m:
            return None
        a = self._frammento(m.group(1), ambito, p)
        b = self._frammento(m.group(2), ambito, p)
        return f"from {a} to {b}" if a and b else None

    def _fino_a(self, f: str, ambito: str, p: int) -> str | None:
        m = re.fullmatch(r"(.+?)\s+fino\s+" + _A + r"\s*(.+)", f)
        if not m:
            return None
        a = self._frammento(m.group(1), ambito, p)
        b = self._frammento(m.group(2), ambito, p)
        return f"{a} through to {b}" if a and b else None

    def _tendenza(self, f: str, ambito: str, p: int) -> str | None:
        m = re.fullmatch(
            r"(?:tendente|tendenti|con\s+tendenza)\s+" + _A + r"\s*(.+)", f
        )
        if not m:
            return None
        x = self._frammento(m.group(1), ambito, p)
        return f"tending to {x}" if x else None

    def _invecchiamento(self, f: str, ambito: str, p: int) -> str | None:
        for schema, forma in (
            (r"con\s+l'invecchiamento", "with age"),
            (r"se\s+invecchiato", "when aged"),
            (r"col\s+tempo", "with time"),
            (r"(.+?)\s+con\s+l'invecchiamento", "{x} with age"),
            (r"(.+?)\s+se\s+invecchiato", "{x} when aged"),
            (r"(.+?)\s+a\s+seconda\s+dell'invecchiamento", "{x} depending on ageing"),
            (r"(.+?)\s+nella\s+riserva", "{x} in the riserva"),
            (r"(.+?)\s+se\s+giovane", "{x} when young"),
        ):
            m = re.fullmatch(schema, f)
            if not m:
                continue
            if not m.groups():
                return forma
            x = self._frammento(m.group(1), ambito, p)
            if x:
                return forma.format(x=x)
        return None

    def _rovescia(self, f: str, ambito: str, p: int) -> str | None:
        """«riflessi dorati o verdognoli» -> «golden or greenish highlights».

        Deve venire prima delle alternative: il nome comanda tutto quello che
        lo segue, e spezzare sulla «o» darebbe «golden highlights or greenish».
        """
        parole = f.split()
        if len(parole) < 2 or _chiave(parole[0]) not in _SI_ROVESCIA:
            return None
        nome = self._cerca(parole[0], ambito)
        if not nome:
            return None
        resto = self._frammento(" ".join(parole[1:]), ambito, p)
        if not resto:
            return None
        if resto.split()[0] in _POSPONE:
            return f"{nome} {resto}"
        return f"{resto} {nome}"

    def _congiunzione(self, f: str, ambito: str, p: int) -> str | None:
        m = re.fullmatch(r"(.+?)\s+e[d]?\s+(.+)", f)
        if not m:
            return None
        a = self._frammento(m.group(1), ambito, p)
        b = self._frammento(m.group(2), ambito, p)
        return f"{a} and {b}" if a and b else None

    def _alternativa(self, f: str, ambito: str, p: int) -> str | None:
        """«amabile o dolce», «sentori floreali e/o fruttati». Come gli
        intervalli: si tiene tutta o si lascia cadere tutta, perche' meta' di
        un'alternativa e' una scelta che il disciplinare non ha fatto."""
        for schema, giunzione in ((r"(.+?)\s+e/o\s+(.+)", "and/or"),
                                  (r"(.+?)\s+o(?:ppure)?\s+(.+)", "or")):
            m = re.fullmatch(schema, f)
            if not m:
                continue
            a = self._frammento(m.group(1), ambito, p)
            b = self._frammento(m.group(2), ambito, p)
            if a and b:
                return f"{a} {giunzione} {b}"
        return None

    def _contrasto(self, f: str, ambito: str, p: int) -> str | None:
        m = re.fullmatch(r"(.+?)\s+ma\s+(.+)", f)
        if not m:
            return None
        a = self._frammento(m.group(1), ambito, p)
        b = self._frammento(m.group(2), ambito, p)
        return f"{a} but {b}" if a and b else None

    def _verso(self, f: str, ambito: str, p: int) -> str | None:
        """Un pezzo che comincia con la preposizione: e' la meta' di un
        intervallo che il disciplinare ha scritto dopo una virgola."""
        for schema, forma in (
            (r"fino\s+" + _A + r"\s*(.+)", "through to {x}"),
            (_A + r"\s+(.+)", "to {x}"),
            (r"all'(.+)", "to {x}"),
        ):
            m = re.fullmatch(schema, f)
            if not m:
                continue
            x = self._frammento(m.group(1), ambito, p)
            if x:
                return forma.format(x=x)
        return None

    def _verbo(self, f: str, ambito: str, p: int) -> str | None:
        for schema, forma in (
            (r"(?:che\s+)?puo'?\s+essere\s+(.+)", "may be {x}"),
            (r"(?:che\s+)?(?:va|varia)\s+(.+)", "ranging {x}"),
            (r"(?:acquista|assume|presenta)\s+(.+)", "taking on {x}"),
        ):
            m = re.fullmatch(schema, f)
            if not m:
                continue
            x = self._frammento(m.group(1), ambito, p)
            if x:
                return forma.format(x=x)
        return None

    def _menzione(self, f: str, ambito: str, p: int) -> str | None:
        """«vivace nella tipologia frizzante»: il disciplinare dice che quel
        tratto vale solo per una menzione, e va detto, non tolto."""
        m = re.fullmatch(
            r"(.+?)\s+(?:nella|nelle|nei|nel)\s+"
            r"(?:tipologia|tipologie|menzione\s+tradizionale|menzioni)\s+(.+)",
            f,
        )
        if not m:
            return None
        x = self._frammento(m.group(1), ambito, p)
        y = self._cerca(m.group(2), ambito)
        return f"{x} in the {y} type" if x and y else None

    def _complemento(self, f: str, ambito: str, p: int) -> str | None:
        """«con riflessi violacei», «con sentore di legno», «di buon corpo»."""
        m = re.fullmatch(r"(?:con|dotato\s+di|dotati\s+di)\s+(.+)", f)
        if m:
            x = self._frammento(m.group(1), ambito, p)
            return f"with {x}" if x else None
        m = re.fullmatch(r"(\w+)\s+di\s+(.+)", f)
        if m and _chiave(m.group(1)) in _REGGE_DI:
            x = self._frammento(m.group(2), ambito, p)
            return f"{_REGGE_DI[_chiave(m.group(1))]} of {x}" if x else None
        m = re.fullmatch(r"di\s+(.+)", f)
        if m:
            x = self._frammento(m.group(1), ambito, p)
            if not x:
                return None
            # «di corpo» e' «of body», ma «di fruttato» e' solo «fruity»: in
            # italiano quel «di» attenua un aggettivo, in inglese non esiste.
            return f"of {x}" if self._e_nome(m.group(1)) else x
        m = re.fullmatch(r"piu'?\s+o\s+meno\s+(.+)", f)
        if m:
            x = self._frammento(m.group(1), ambito, p)
            return f"more or less {x}" if x else None
        return None

    def _secondo(self, f: str, ambito: str, p: int) -> str | None:
        m = re.fullmatch(
            r"(.+?)\s+a\s+seconda\s+(?:della|delle|dei|degli|del|dello|dell')\s*(.+)", f
        )
        if not m:
            return None
        x = self._frammento(m.group(1), ambito, p)
        y = self._frammento(m.group(2), ambito, p)
        return f"{x} depending on the {y}" if x and y else None

    def _prefisso(self, f: str, ambito: str, p: int) -> str | None:
        parole = f.split()
        for n in (2, 1):
            if len(parole) <= n:
                continue
            avanti = self._prefissi.get(_chiave(" ".join(parole[:n])))
            if not avanti:
                continue
            resto = self._frammento(" ".join(parole[n:]), ambito, p)
            if resto:
                return f"{avanti} {resto}"
        return None

    def _sintagma(self, f: str, ambito: str, p: int) -> str | None:
        """Un termine noto seguito da cio' che lo modifica.

        «rosso rubino piu' o meno intenso»: la testa e' «rosso rubino», il
        resto la modifica. Un modificatore di una parola va davanti, come
        vuole l'inglese («deep ruby red»); uno lungo resta dov'e', dopo una
        virgola, come si scrive in una scheda di degustazione.
        """
        parole = f.split()
        for n in range(len(parole) - 1, 0, -1):
            testa = self._cerca(" ".join(parole[:n]), ambito)
            if not testa:
                continue
            coda = parole[n:]
            # Gli aggettivi secchi che seguono la testa passano davanti, dove
            # l'inglese li vuole: «rosso rubino carico» -> «deep ruby red».
            while coda:
                solo = self._frammento(coda[0], ambito, p)
                if not solo or " " in solo:
                    break
                testa = f"{solo} {testa}"
                coda = coda[1:]
            if not coda:
                return testa
            modifica = self._frammento(" ".join(coda), ambito, p)
            if not modifica:
                continue
            if " " not in modifica:
                return f"{modifica} {testa}"
            if modifica.split()[0] in _SENZA_VIRGOLA:
                return f"{testa} {modifica}"
            return f"{testa}, {modifica}"
        return None


def _chiave(s: str) -> str:
    """Spoglia accenti e uniforma l'apostrofo: le fonti usano entrambe le forme,
    e «dell'» con l'apostrofo tipografico non e' una parola diversa."""
    s = s.replace("\u2019", "'").replace("\u02bc", "'")
    return _SPAZI.sub(" ", spoglia_accenti(s).lower().strip())


def _elenca(pezzi: list[str]) -> str:
    """L'inglese vuole «and» prima dell'ultimo - ma non se l'ultimo ce l'ha
    gia' dentro, altrimenti esce «intense and persistent and harmonious»."""
    # Senza doppioni: «erbaceo» e «erbacea» sono due frammenti e una resa
    # sola, e usciva «herbaceous, herbaceous». Visto su 360 racconti composti.
    pezzi = list(dict.fromkeys(pezzi))
    if len(pezzi) == 1:
        return pezzi[0]
    ultimo = pezzi[-1]
    if " and " in ultimo or " or " in ultimo:
        return ", ".join(pezzi)
    return ", ".join(pezzi[:-1]) + " and " + ultimo


@lru_cache(maxsize=4)
def carica(percorso: str | Path | None = None) -> Organolettico:
    p = Path(percorso or PERCORSO_PREDEFINITO)
    dati = json.loads(p.read_text(encoding="utf-8"))
    termini: dict[str, str] = {}
    for gruppo in dati["termini"].values():
        termini.update(gruppo)
    return Organolettico(
        termini, dati.get("per_ambito", {}), frozenset(dati.get("nomi", ()))
    )
