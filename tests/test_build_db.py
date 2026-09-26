"""Il costruttore del database e il dispositivo devono normalizzare allo stesso modo.

`data/build_db.py` ripete `normalizza` di proposito: deve poter girare senza il
pacchetto installato, perché è il primo passo di un'installazione pulita. Il
prezzo di quella scelta è che le due copie possono divergere in silenzio: se
cambiasse `amelie.text` e non l'altra, le forme scritte in archivio smetterebbero
di corrispondere a quelle cercate a runtime, e certi produttori diventerebbero
introvabili senza che nulla segnalasse un errore. Questo test tiene allineate
le due copie.
"""

import importlib.util
from pathlib import Path

import pytest

from amelie.text import normalizza

RADICE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def costruttore():
    spec = importlib.util.spec_from_file_location(
        "build_db", RADICE / "data" / "build_db.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Ogni riga è un caso su cui una divergenza produrrebbe un difetto: acronimi,
# punti fra parole, abbreviazioni italiane, cifre decimali, confusioni
# dell'OCR, accenti, apostrofi.
CASI = [
    "Barolo D.O.C.G. — Cannubi",
    "COMM.G.B.BURLOTTO",
    "Comm. G.B. Burlotto",
    "F.lli Vincenzi",
    "S.to Ippolito",
    "P.Lex",
    "Ca.So.Co. Soc",
    "13.5",
    "Audax Zero.3",
    "B0LGHERI",
    "Chianti 2019",
    "Ca' del Bosco",
    "Montepulciano d'Abruzzo",
    "Nero d'Avola",
    "Müller Thurgau",
    "Gewürztraminer",
    "Château Something",
    "  spazi   multipli  ",
    "TRATTINI-E-ALTRO",
    "",
]


@pytest.mark.parametrize("testo", CASI)
def test_le_due_normalizzazioni_coincidono(costruttore, testo):
    assert costruttore.normalizza(testo) == normalizza(testo), (
        f"build_db e amelie.text divergono su {testo!r}: chi ricostruisce il "
        "database scriverebbe forme che il dispositivo non sa cercare")


def test_il_suffisso_di_colore_si_stacca(costruttore):
    """"Corvina N" nel registro UE vuol dire bacca nera, non un vitigno «N»."""
    assert costruttore.pulisci_vitigno("Corvina N") == ("Corvina", "nera")
    assert costruttore.pulisci_vitigno("Garganega B") == ("Garganega", "bianca")
    assert costruttore.pulisci_vitigno("Pinot Grigio") == ("Pinot Grigio", None)
