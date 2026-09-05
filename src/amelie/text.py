"""Normalizzazione del testo prodotto dall'OCR.

Un'etichetta fotografata di sbieco, su vetro curvo e con caratteri decorativi,
non produce mai testo pulito. Questo modulo si occupa di renderlo confrontabile
con i nomi del database senza perdere l'informazione utile.

Due lavori distinti, che vanno tenuti separati:

- `normalizza()` prepara una stringa per il confronto fuzzy: toglie accenti,
  maiuscole e punteggiatura, e appiattisce le confusioni tipiche dell'OCR
  (`0`/`O`, `1`/`l`/`I`, `5`/`S`, `8`/`B`). Il risultato non è leggibile da un
  umano: serve solo alla macchina.

- `estrai_annata()` fa il contrario: cerca le cifre, e per trovarle deve
  *riparare* le lettere che l'OCR ha messo al posto dei numeri. "2Ol7" è un
  1 su 4 nelle nostre prove e senza riparazione non viene letto affatto.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# ---------------------------------------------------------------------------
# Normalizzazione per il confronto
# ---------------------------------------------------------------------------

# Confusioni che l'OCR fa in entrambe le direzioni. Si collassa sempre verso la
# LETTERA, perché nei nomi di vino le lettere sono molto più frequenti delle
# cifre: "B0LGHERI" diventa "bolgheri" e non "b0lgheri".
_CONFUSIONI_VERSO_LETTERA = str.maketrans({
    "0": "o",
    "1": "l",
    "5": "s",
    "8": "b",
    "6": "g",
    "2": "z",
})

_NON_ALFANUM = re.compile(r"[^a-z0-9]+")
_SPAZI = re.compile(r"\s+")
_SOLO_CIFRE = re.compile(r"^\d+$")


def spoglia_accenti(s: str) -> str:
    """Toglie i segni diacritici: "Château" -> "Chateau"."""
    scomposto = unicodedata.normalize("NFKD", s)
    return "".join(c for c in scomposto if not unicodedata.combining(c))


def normalizza(s: str, *, collassa_confusioni: bool = True) -> str:
    """Riduce una stringa alla forma usata per il confronto fuzzy.

    >>> normalizza("Barolo D.O.C.G. — Cannubi")
    'barolo docg cannubi'
    >>> normalizza("B0LGHERI")
    'bolgheri'
    >>> normalizza("Chianti 2019")
    'chianti 2019'
    """
    s = spoglia_accenti(s).lower()
    # I punti degli acronimi vanno tolti, non trasformati in spazi, altrimenti
    # "D.O.C.G." si sbriciola in quattro token da una lettera.
    s = s.replace(".", "")
    parti = [p for p in _NON_ALFANUM.split(s) if p]
    if collassa_confusioni:
        # Un token fatto di sole cifre è quasi sempre un'annata o una
        # gradazione: va lasciato stare. Applicare le confusioni lo
        # distruggerebbe ("2019" -> "zol9").
        parti = [
            p if _SOLO_CIFRE.match(p) else p.translate(_CONFUSIONI_VERSO_LETTERA)
            for p in parti
        ]
    return " ".join(parti)


def token(s: str, *, minimo: int = 3) -> list[str]:
    """Token utili per una query FTS5: scarta le parole troppo corte.

    Le parole di una o due lettere ("di", "il", "e") non discriminano nulla e
    allargano inutilmente il set di candidati.
    """
    return [t for t in normalizza(s).split() if len(t) >= minimo]


# ---------------------------------------------------------------------------
# Annata
# ---------------------------------------------------------------------------

# Nel senso opposto: qui vogliamo le cifre, quindi le lettere che assomigliano
# a numeri vanno riportate a numero.
_CONFUSIONI_VERSO_CIFRA = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "i": "1", "|": "1",
    "Z": "2", "z": "2",
    "E": "3",
    "A": "4",
    "S": "5", "s": "5",
    "G": "6", "b": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
})

# Sul testo grezzo basta escludere che il numero faccia parte di una cifra piu'
# lunga: un codice a barre non e' un'annata.
_ANNATA = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

# Sul testo RIPARATO la regola dev'essere molto piu' severa. La riparazione
# trasforma lettere in cifre, e dentro una parola qualsiasi puo' far comparire
# un anno dal nulla: "Grigio" diventa "6r1910" (G->6, i->1, g->9, i->1, o->0) e
# "1910" e' li'. Un'annata vera, sull'etichetta, e' sempre un token a se': non
# e' mai incollata a delle lettere. Pretendere confini non alfanumerici elimina
# le invenzioni e conserva i casi veri come "2Ol7".
_ANNATA_RIPARATA = re.compile(r"(?<![0-9A-Za-z])(19\d{2}|20\d{2})(?![0-9A-Za-z])")

# Un vino imbottigliato non può avere un'annata nel futuro, e sotto il 1900 si
# tratta quasi sempre di un numero civico o di una gradazione mal letta.
ANNO_MINIMO = 1900


def estrai_annata(righe: Iterable[str], *, anno_massimo: int | None = None) -> int | None:
    """Cerca l'annata fra le righe dell'OCR, riparando le cifre travestite.

    Restituisce l'annata più plausibile, o `None` se non ne trova.

    >>> estrai_annata(["Barolo", "2Ol7"])
    2017
    >>> estrai_annata(["Nessun anno qui"]) is None
    True

    Quando compaiono più anni si prende il **più recente** fra quelli
    ammissibili: sulle etichette la seconda data è di solito l'anno di
    fondazione della cantina ("dal 1898"), che è sempre più vecchio.
    """
    candidati: list[int] = []
    for riga in righe:
        # Prima si cerca nel testo così com'è: se le cifre sono già cifre, non
        # si rischia di rovinare una parola trasformandola in numero.
        for m in _ANNATA.finditer(riga):
            candidati.append(int(m.group(1)))
        # Poi si riprova sul testo riparato, ma con la regola severa.
        riparata = riga.translate(_CONFUSIONI_VERSO_CIFRA)
        for m in _ANNATA_RIPARATA.finditer(riparata):
            candidati.append(int(m.group(1)))

    if anno_massimo is None:
        anno_massimo = 2100
    ammissibili = [a for a in candidati if ANNO_MINIMO <= a <= anno_massimo]
    return max(ammissibili) if ammissibili else None


# ---------------------------------------------------------------------------
# Rumore
# ---------------------------------------------------------------------------

# Parole che compaiono su quasi tutte le etichette e non aiutano a distinguere
# un vino da un altro. Vanno tolte dalla query, non dal testo mostrato.
PAROLE_VUOTE = frozenset("""
    vino wine imbottigliato bottled prodotto product italia italy italiano
    denominazione origine controllata garantita indicazione geografica tipica
    doc docg igt igp dop azienda agricola societa cantina cantine tenuta
    tenute podere poderi fattoria casa vigna vigne vigneto vigneti
    contiene solfiti contains sulfites bottiglia cl ml vol alc alcool
    annata vendemmia harvest riserva superiore classico
""".split())


def parole_utili(s: str, *, minimo: int = 3) -> list[str]:
    """Token della stringa, senza le parole che stanno su ogni etichetta.

    Nota: "riserva", "superiore" e "classico" sono qui perché non identificano
    il *vino*, ma vanno recuperate a parte come qualificatori della
    denominazione ("Chianti Classico" è una denominazione diversa da "Chianti").
    """
    return [t for t in token(s, minimo=minimo) if t not in PAROLE_VUOTE]
