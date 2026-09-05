"""Test della normalizzazione del testo OCR.

I casi qui dentro vengono da come sbaglia davvero l'OCR su un'etichetta di vino:
confusioni fra cifre e lettere, acronimi puntati, accenti francesi, e la
seconda data sull'etichetta che è l'anno di fondazione della cantina.
"""

import pytest

from amelie.text import (
    estrai_annata,
    normalizza,
    parole_utili,
    spoglia_accenti,
    token,
)


class TestNormalizza:
    def test_minuscole_e_punteggiatura(self):
        assert normalizza("Barolo — Cannubi") == "barolo cannubi"

    def test_acronimi_puntati_restano_interi(self):
        # "D.O.C.G." non deve sbriciolarsi in quattro token da una lettera
        assert normalizza("Barolo D.O.C.G.") == "barolo docg"

    def test_accenti(self):
        assert normalizza("Château") == "chateau"
        assert normalizza("Gewürztraminer") == "gewurztraminer"

    def test_confusioni_ocr_verso_lettera(self):
        assert normalizza("B0LGHERI") == "bolgheri"
        assert normalizza("CHIANT1") == "chiantl"  # 1 -> l, poi ci pensa il fuzzy

    def test_le_cifre_pure_non_si_toccano(self):
        # senza questa regola "2019" diventerebbe "zol9"
        assert normalizza("Chianti 2019") == "chianti 2019"
        assert normalizza("13.5") == "135"

    def test_idempotente(self):
        una = normalizza("Barolo D.O.C.G. 2019")
        assert normalizza(una) == una

    def test_stringa_vuota(self):
        assert normalizza("") == ""
        assert normalizza("   ...---   ") == ""


class TestToken:
    def test_scarta_le_parole_corte(self):
        assert token("Vino di Rossi e Figli") == ["vino", "rossi", "figli"]

    def test_soglia_configurabile(self):
        assert token("di re", minimo=2) == ["di", "re"]


class TestEstraiAnnata:
    def test_annata_pulita(self):
        assert estrai_annata(["Barolo", "2017"]) == 2017

    @pytest.mark.parametrize(
        "grezzo, atteso",
        [
            ("2Ol7", 2017),   # O->0, l->1
            ("2O19", 2019),
            ("l998", 1998),   # l->1
            ("2Ol5", 2015),
        ],
    )
    def test_ripara_le_cifre_travestite(self, grezzo, atteso):
        assert estrai_annata([grezzo]) == atteso

    def test_preferisce_la_piu_recente(self):
        # la data più vecchia sull'etichetta è quasi sempre l'anno di fondazione
        assert estrai_annata(["Tenuta dal 1898", "Chianti 2019"]) == 2019

    def test_ignora_i_numeri_che_non_sono_anni(self):
        assert estrai_annata(["750 ml", "13,5% vol"]) is None
        assert estrai_annata(["Via Roma 1234"]) is None

    def test_scarta_il_futuro(self):
        assert estrai_annata(["2019", "2099"], anno_massimo=2026) == 2019

    def test_nessuna_annata(self):
        assert estrai_annata(["Barolo", "Cannubi"]) is None
        assert estrai_annata([]) is None

    def test_non_spezza_un_numero_lungo(self):
        # un codice a barre non è un'annata
        assert estrai_annata(["8001234201900"]) is None


class TestParoleUtili:
    def test_toglie_le_parole_di_ogni_etichetta(self):
        risultato = parole_utili(
            "Azienda Agricola Rossi - Chianti Classico DOCG 2019"
        )
        assert "rossi" in risultato
        assert "chianti" in risultato
        assert "azienda" not in risultato
        assert "docg" not in risultato

    def test_conserva_l_annata(self):
        assert "2019" in parole_utili("Chianti 2019")

    def test_etichetta_di_solo_rumore(self):
        assert parole_utili("Vino Prodotto in Italia - Contiene Solfiti") == []


def test_spoglia_accenti_non_perde_lettere():
    assert spoglia_accenti("Nebbiolo") == "Nebbiolo"
    assert len(spoglia_accenti("àèìòù")) == 5
