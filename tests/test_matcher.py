"""Test del riconoscimento.

Servono il database costruito (`python3 data/build_db.py`) e `rapidfuzz`: senza,
i test si saltano invece di fallire, perché un ambiente pulito non ha ancora né
l'uno né l'altro.

I casi qui dentro sono quelli che contano per il prodotto: la cascata che scende
al livello giusto, la sicurezza che NON dichiara certo ciò che certo non è, e i
vitigni ammessi dal disciplinare che non devono mai finire fra i fatti
raccontabili.
"""

import pytest

pytest.importorskip("rapidfuzz")

from amelie.matcher import (  # noqa: E402
    SOGLIA_CERTA,
    SOGLIA_DUBBIA,
    DatabaseAssente,
    Fatti,
    Livello,
    Matcher,
)


@pytest.fixture(scope="module")
def m():
    try:
        matcher = Matcher()
    except DatabaseAssente as e:
        pytest.skip(str(e))
    yield matcher
    matcher.chiudi()


class TestCascata:
    def test_etichetta_completa_arriva_al_vino(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "Barolo", "Denominazione di Origine",
                     "Controllata e Garantita", "2016"])
        assert f.livello in (Livello.VINO, Livello.TIPOLOGIA)
        assert f.denominazione and "barolo" in f.denominazione.lower()

    def test_solo_denominazione_scende_alla_tipologia(self, m):
        """Senza produttore leggibile si racconta comunque la denominazione."""
        f = m.cerca(["AMARONE DELLA VALPOLICELLA", "Denominazione di Origine"])
        assert f.livello in (Livello.TIPOLOGIA, Livello.DENOMINAZIONE, Livello.VINO)
        assert "amarone" in (f.denominazione or f.tipologia or "").lower()

    def test_solo_vitigno_scende_al_vitigno(self, m):
        f = m.cerca(["Nebbiolo"])
        assert f.livello in (Livello.VITIGNO, Livello.DENOMINAZIONE, Livello.TIPOLOGIA)

    def test_testo_vuoto_non_inventa(self, m):
        assert m.cerca([]).livello is Livello.NULLA
        assert m.cerca(["", "  "]).livello is Livello.NULLA

    def test_solo_rumore_non_inventa(self, m):
        """Le parole che stanno su ogni etichetta non identificano nulla."""
        f = m.cerca(["CONTIENE SOLFITI", "PRODOTTO IN ITALIA", "750 ml", "13,5% vol"])
        assert f.livello is Livello.NULLA

    def test_annata_estratta(self, m):
        f = m.cerca(["Chianti Classico", "2019"])
        assert f.annata == 2019


class TestSicurezza:
    def test_non_dichiara_certo_un_produttore_diverso(self, m):
        """Il caso che generava figuracce: 'Monte Antico' -> 'Monte Giove'.

        Un nome simile a metà non deve MAI produrre un match certo su un vino
        commerciale, perché quello impegna il produttore.
        """
        f = m.cerca(["MONTE ANTICO", "Toscana", "Rosso"])
        if f.livello is Livello.VINO and f.cantina:
            assert "antico" in f.cantina.lower() or not f.certo

    def test_una_parola_sola_non_basta_per_essere_certi(self, m):
        f = m.cerca(["Rosso"])
        assert not f.certo

    def test_soglie_coerenti(self):
        assert SOGLIA_DUBBIA < SOGLIA_CERTA

    def test_le_tre_fasce_si_escludono(self, m):
        f = m.cerca(["Barolo", "Marchesi di Barolo"])
        assert not (f.certo and f.dubbio)


class TestVitigniAmmessi:
    """Il cuore dell'anti-invenzione."""

    def test_amarone_non_dichiara_croatina(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA", "Classico"])
        if f.vitigni:
            assert "Croatina" not in f.vitigni, (
                "Croatina e' AMMESSA dal disciplinare, non imposta: dirla presente"
                " e' falso"
            )

    def test_gli_ammessi_restano_fuori_dal_blocco_fatti(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA"])
        blocco = f.blocco_fatti()
        for ammesso in f.vitigni_ammessi:
            assert ammesso not in blocco, (
                f"{ammesso!r} e' solo ammesso: il modello non deve nemmeno vederlo"
            )

    def test_amarone_ha_i_vitigni_giusti(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA"])
        if f.livello is Livello.TIPOLOGIA and f.vitigni:
            assert any("corvina" in v.lower() for v in f.vitigni)


class TestBloccoFatti:
    def test_salta_i_campi_vuoti(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        blocco = f.blocco_fatti()
        assert "Barolo" in blocco
        assert "Produttore" not in blocco
        assert "None" not in blocco

    def test_una_riga_per_campo(self):
        f = Fatti(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi",
                  annata=2016, vitigni=["Nebbiolo"])
        righe = f.blocco_fatti().split("\n")
        assert len(righe) == 4
        assert all(":" in r for r in righe)

    def test_fatti_vuoti_danno_blocco_vuoto(self):
        assert Fatti().blocco_fatti() == ""


class TestRobustezza:
    def test_apici_e_trattini_non_rompono_la_query(self, m):
        """FTS5 interpreta la punteggiatura come sintassi se non e' quotata."""
        for testo in ["Ca' del Bosco", "Montepulciano d'Abruzzo",
                      'virgolette "strane"', "meno - meno", "*", "AND OR NOT"]:
            assert m.cerca([testo]) is not None

    def test_testo_lunghissimo(self, m):
        assert m.cerca(["Barolo " * 500]) is not None

    def test_caratteri_non_latini(self, m):
        assert m.cerca(["日本語", "Ελληνικά", "кириллица"]) is not None

    def test_database_in_sola_lettura(self, m):
        import sqlite3
        with pytest.raises(sqlite3.OperationalError):
            m.con.execute("DELETE FROM vino")


class TestCandidati:
    def test_propone_alternative_per_la_conferma(self, m):
        f = m.cerca(["Chianti"])
        assert len(f.candidati) <= 3

    def test_le_alternative_sono_diverse_fra_loro(self, m):
        f = m.cerca(["Barolo"])
        assert len(f.candidati) == len(set(f.candidati))
