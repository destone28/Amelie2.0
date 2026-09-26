"""La gabbia: il modello sceglie e combina, ma solo fra parole ammesse.

Una grammatica GBNF costruita per OGNI bottiglia: le parole dei suoi fatti,
più un lessico chiuso di parole di raccordo — quelle che i testi verificati
usano oltre ai fatti: «nasce», «in bocca», «si serve» — più cifre e
punteggiatura. `llama.cpp` la applica a ogni token: il modello non può
scrivere una parola che non stia qui dentro, e questo non è un controllo a
posteriori, è un vincolo strutturale.

Misurato su trenta vini, stesso modello, temperatura 0,2:

    senza gabbia   22 su 30 passano la verifica   0,67 parole fuori dai fatti
    con la gabbia  25 su 30                        0,50

Costa un terzo di tempo in più a testo. Quel che resta fuori dalla gabbia
sono i RAPPORTI sbagliati fra parole vere — «di colore spumante», «Sangiovese
e Amarena» come vitigni — e a quelli pensa `verifica`, dopo.

Il lessico sta in `data/lessico/gabbia_it.txt` ed è ricavato dai testi del
corpus di addestramento che passano la verifica: 310 parole, viste almeno due
volte. Non c'è un lessico inglese perché non c'è un corpus inglese scritto da
una persona o da un modello maestro; con il solo lessico dei testi composti
la gabbia inglese affamerebbe il modello. In inglese, niente gabbia.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .matcher import Fatti

CARTELLA_LESSICO = Path(__file__).resolve().parents[2] / "data" / "lessico"

_PAROLA = re.compile(r"[A-Za-zÀ-ÿ']+")


@lru_cache(maxsize=4)
def lessico(lingua: str) -> frozenset[str]:
    """Le parole di raccordo ammesse in questa lingua; vuoto se non c'è."""
    percorso = CARTELLA_LESSICO / f"gabbia_{lingua}.txt"
    if not percorso.exists():
        return frozenset()
    return frozenset(r.strip() for r in percorso.read_text(encoding="utf-8").splitlines()
                     if r.strip() and not r.startswith("#"))


def parole_dei_fatti(f: Fatti, lingua: str) -> set[str]:
    """Tutte le parole che i fatti di questa bottiglia contengono."""
    testo = " ".join(filter(None, [
        f.blocco_fatti(lingua=lingua), " ".join(f.vitigni), " ".join(f.vitigni_ammessi),
        f.nota_in(lingua) or "", f.note_vitigno or "",
        " ".join(f.sensoriali_in(lingua)), " ".join(f.abbinamenti_in(lingua)),
        f.denominazione or "", f.tipologia or "", f.nome or "", f.cantina or "",
        f.regione or "", str(f.annata or ""), f.temperatura_c or "",
        " ".join(f.note_sensoriali),
        " ".join(f.disciplinare.values()) if f.disciplinare else "",
    ]))
    return {w.strip("'") for w in _PAROLA.findall(testo) if w.strip("'")}


def gabbia_di(f: Fatti, lingua: str = "it") -> str | None:
    """La grammatica per questa bottiglia, o `None` se la lingua non ha lessico."""
    raccordo = lessico(lingua)
    if not raccordo:
        return None
    parole: set[str] = set()
    for w in parole_dei_fatti(f, lingua) | set(raccordo):
        parole.update((w, w.lower(), w.capitalize()))
    parole.update(("d'", "l'", "un'", "dell'", "all'", "nell'", "dall'", "sull'", "è", "È"))
    # Le più lunghe prima: in una grammatica le alternative si provano in
    # ordine, e «Cabernet» prima di «Cab» non taglia mai una parola a metà.
    alternative = " | ".join(json.dumps(w, ensure_ascii=False)
                             for w in sorted(parole, key=lambda x: (-len(x), x)))
    return "\n".join([
        'root ::= frase (" " frase){1,5}',
        'frase ::= pezzo (" " pezzo){2,40} "."',
        'pezzo ::= parola ("," | ";" | ":")?',
        f"parola ::= numero | {alternative}",
        'numero ::= [0-9]+ ("." [0-9]+)?',
    ])
