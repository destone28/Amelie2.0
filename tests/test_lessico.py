"""Test dei vocabolari tradotti.

Il test che conta davvero è quello di COPERTURA: legge i dataset veri e
verifica che ogni valore che compare nelle fonti abbia una traduzione in ogni
lingua dichiarata. Senza, il lessico deriva in silenzio dai dati appena una
fonte viene aggiornata, e il dispositivo si mette a dire parole inglesi in mezzo
a una frase italiana.
"""

import ast
import csv
import json
from pathlib import Path

import pytest

from amelie.lessico import PERCORSO_PREDEFINITO, carica, elenca_in_lingua

RADICE = Path(__file__).resolve().parents[1]
XWINES = RADICE / "data" / "sources" / "xwines_italia.csv"
FIGSHARE = RADICE / "data" / "sources" / "PDO_wine_data_IT_FR.csv"


@pytest.fixture(scope="module")
def lex():
    return carica()


# --------------------------------------------------------------- traduzione

class TestTraduzione:
    def test_italiano_predefinito(self, lex):
        assert lex.traduci("corpo", "Full-bodied") == "strutturato"

    def test_inglese(self, lex):
        assert lex.traduci("corpo", "Full-bodied", lingua="en") == "full-bodied"

    def test_forma_narrativa_diversa_dall_etichetta(self, lex):
        """«acidità alta» non si dice: dentro una frase è «bella acidità»."""
        assert lex.traduci("acidita", "High") == "alta"
        assert lex.traduci("acidita", "High", forma="narrativa") == "bella acidità"

    def test_narrativa_ricade_sull_etichetta(self, lex):
        """Dove la forma narrativa non serve, l'etichetta va benissimo."""
        assert lex.traduci("tipo", "Red", forma="narrativa") == "rosso"

    def test_valore_sconosciuto_torna_com_e(self, lex):
        """Un termine nuovo non deve fermare il dispositivo."""
        assert lex.traduci("corpo", "Chewy") == "Chewy"

    def test_vocabolario_sconosciuto_torna_com_e(self, lex):
        assert lex.traduci("inesistente", "Qualcosa") == "Qualcosa"

    def test_lingua_sconosciuta_ricade_sulla_predefinita(self, lex):
        assert lex.traduci("corpo", "Full-bodied", lingua="de") == "strutturato"

    def test_traduci_molti(self, lex):
        assert lex.traduci_molti("abbinamento", ["Beef", "Lamb"]) == ["manzo", "agnello"]

    def test_caricamento_memorizzato(self):
        assert carica() is carica()


# ---------------------------------------------------------------- copertura

def _valori_distinti(percorso, campo, *, delimitatore=",", lista=False, filtro=None):
    if not percorso.exists():
        pytest.skip(f"manca {percorso.name}: esegui data/estrai_xwines.py")
    csv.field_size_limit(10 ** 7)
    valori = set()
    with percorso.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=delimitatore):
            if filtro and not filtro(r):
                continue
            v = r.get(campo)
            if not v:
                continue
            if lista:
                try:
                    valori.update(ast.literal_eval(v))
                except (ValueError, SyntaxError):
                    pass
            else:
                valori.add(v)
    return valori


CASI_XWINES = [
    ("tipo", "Type", False),
    ("elaborazione", "Elaborate", False),
    ("corpo", "Body", False),
    ("acidita", "Acidity", False),
    ("abbinamento", "Harmonize", True),
]

CASI_FIGSHARE = [
    ("colore", "Color"),
    ("categoria_ue", "Category"),
]


class TestCopertura:
    """Ogni valore che compare nelle fonti deve essere traducibile."""

    @pytest.mark.parametrize("vocabolario, campo, lista", CASI_XWINES)
    def test_xwines(self, lex, vocabolario, campo, lista):
        presenti = _valori_distinti(XWINES, campo, lista=lista)
        mancanti = lex.manca(vocabolario, presenti)
        assert not mancanti, (
            f"'{vocabolario}' non traduce {sorted(mancanti)} "
            f"(compaiono in xwines_italia.csv, campo {campo})"
        )

    @pytest.mark.parametrize("vocabolario, campo", CASI_FIGSHARE)
    def test_figshare(self, lex, vocabolario, campo):
        presenti = _valori_distinti(
            FIGSHARE, campo, delimitatore=";", filtro=lambda r: r.get("Country") == "IT"
        )
        mancanti = lex.manca(vocabolario, presenti)
        assert not mancanti, (
            f"'{vocabolario}' non traduce {sorted(mancanti)} "
            f"(compaiono in PDO_wine_data_IT_FR.csv, campo {campo})"
        )

    def test_ogni_termine_ha_tutte_le_lingue(self, lex):
        """Una lingua non può restare tradotta a metà."""
        buchi = []
        for vocabolario, termini in lex.vocabolari.items():
            for chiave, voce in termini.items():
                for lingua in lex.lingue:
                    if lingua not in voce or not voce[lingua].get("etichetta"):
                        buchi.append(f"{vocabolario}/{chiave}/{lingua}")
        assert not buchi, f"traduzioni mancanti: {buchi}"

    def test_nessuna_etichetta_vuota(self, lex):
        for vocabolario, termini in lex.vocabolari.items():
            for chiave, voce in termini.items():
                for lingua, forme in voce.items():
                    assert forme["etichetta"].strip(), f"{vocabolario}/{chiave}/{lingua}"


class TestFileVocabolari:
    def test_json_valido(self):
        json.loads(PERCORSO_PREDEFINITO.read_text(encoding="utf-8"))

    def test_dichiara_italiano_e_inglese(self, lex):
        assert "it" in lex.lingue and "en" in lex.lingue

    def test_la_predefinita_e_fra_le_lingue(self, lex):
        assert lex.predefinita in lex.lingue

    def test_i_vocabolari_attesi_ci_sono(self, lex):
        attesi = {
            "tipo", "colore", "categoria_ue",
            "elaborazione", "corpo", "acidita", "abbinamento",
        }
        assert attesi <= set(lex.nomi_vocabolari())


class TestElencaInLingua:
    def test_tre_voci(self):
        assert elenca_in_lingua(["a", "b", "c"]) == "a, b e c"

    def test_inglese(self):
        assert elenca_in_lingua(["a", "b"], "en") == "a and b"

    def test_una_voce(self):
        assert elenca_in_lingua(["solo"]) == "solo"

    def test_vuoto(self):
        assert elenca_in_lingua([]) == ""

    def test_scarta_i_vuoti(self):
        assert elenca_in_lingua(["a", "", None, "b"]) == "a e b"


class TestFrasi:
    """L'impalcatura delle frasi, che senza controllo si traduce a meta'.

    Tradurre le parole non basta: sono i periodi a tenerle insieme, e un
    periodo che esiste solo in italiano fa dire al dispositivo, con
    lingua="en", parole inglesi dentro frasi italiane. Questi test se ne
    accorgono prima di chi ascolta.
    """

    def test_ogni_frase_esiste_in_ogni_lingua(self):
        lex = carica()
        mancanti = [
            f"{gruppo}.{chiave} manca in {lingua}"
            for gruppo, voci in lex.frasi.items()
            for chiave, per_lingua in voci.items()
            for lingua in lex.lingue
            if not per_lingua.get(lingua)
        ]
        assert not mancanti, mancanti

    def test_i_segnaposto_coincidono_fra_le_lingue(self):
        """Un segnaposto in piu' o in meno e' una frase che esplode a runtime.

        `str.format` solleva KeyError se il modello chiede un valore che chi
        chiama non passa: una traduzione con «{vino}» al posto di «{cosa}»
        farebbe fallire il racconto solo in quella lingua, e solo su quella
        frase.
        """
        import re
        lex = carica()
        problemi = []
        for gruppo, voci in lex.frasi.items():
            for chiave, per_lingua in voci.items():
                riferimento = lex.varianti(gruppo, chiave, lex.predefinita)
                attesi = set(re.findall(r"\{(\w+)\}", riferimento[0] if riferimento else ""))
                # Ogni variante, in ogni lingua: una variante con un segnaposto
                # in meno direbbe una cosa diversa, e una con uno in piu'
                # esploderebbe a runtime, ma solo quando il seme la sceglie.
                for lingua in per_lingua:
                    for n, modello in enumerate(lex.varianti(gruppo, chiave, lingua)):
                        trovati = set(re.findall(r"\{(\w+)\}", modello))
                        if trovati != attesi:
                            problemi.append(
                                f"{gruppo}.{chiave} [{lingua} #{n}]: {sorted(trovati)} "
                                f"invece di {sorted(attesi)}")
        assert not problemi, problemi

    def test_le_varianti_si_scelgono_col_seme_e_senza_seme_la_prima(self):
        """Stesso vino, stesse parole; vini diversi, parole diverse. E la
        prima e' quella di riferimento, su cui si e' scritto tutto il resto."""
        from amelie.lessico import Lessico
        lex = Lessico(vocabolari={}, lingue=("it", "en"), predefinita="it",
                      frasi={"corpo": {"x": {"it": ["Uno {a}.", "Due {a}.", "Tre {a}."],
                                             "en": "One {a}."}}})
        assert lex.frase("corpo", "x", a="k") == "Uno k."
        assert lex.frase("corpo", "x", seme=4, a="k") == "Due k."
        assert lex.frase("corpo", "x", seme=4, a="k") == lex.frase("corpo", "x", seme=4, a="k")
        assert lex.frase("corpo", "x", lingua="en", seme=4, a="k") == "One k."
        assert lex.varianti("corpo", "x") == ["Uno {a}.", "Due {a}.", "Tre {a}."]

    def test_una_frase_sconosciuta_non_ferma_il_dispositivo(self):
        """Meglio una riga in meno che un'eccezione davanti a un tavolo."""
        lex = carica()
        assert lex.frase("apertura", "non_esiste") == ""
        assert lex.frase("gruppo_inventato", "niente") == ""

    def test_una_lingua_sconosciuta_ripiega_sulla_predefinita(self):
        lex = carica()
        assert lex.frase("apertura", "illeggibile", lingua="de") == \
            lex.frase("apertura", "illeggibile", lingua=lex.predefinita)
