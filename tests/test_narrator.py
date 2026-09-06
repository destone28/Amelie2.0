"""Test del racconto.

Il test che conta è quello sull'invenzione: il dispositivo può dire meno di
quello che sa, mai più. Un racconto che aggiunge un premio, un'annata o un
luogo che non stanno nei fatti è un guasto, non un'imprecisione.
"""

import pytest

from amelie.matcher import Fatti, Livello
from amelie.narrator import (
    PAROLE_MAX,
    Racconto,
    _ripulisci,
    a_frasi,
    prompt,
    template,
    verifica,
)


@pytest.fixture
def barolo():
    return Fatti(
        livello=Livello.VINO, sicurezza=100.0,
        nome="Cannubi Barolo", cantina="Marchesi di Barolo",
        regione="Barolo", annata=2016, denominazione="Barolo",
        tipo_denominazione="DOP", colore="Red", corpo="Full-bodied",
        acidita="High", vitigni=["Nebbiolo"],
        vitigni_ammessi=["Barbera", "Croatina"],
        abbinamenti=["Beef", "Game Meat"], temperatura_c="17-19",
    )


class TestVerifica:
    def test_accetta_cio_che_sta_nei_fatti(self, barolo):
        ok, inv = verifica("Questo è il Cannubi Barolo di Marchesi di Barolo.", barolo)
        assert ok, inv

    def test_scarta_un_premio_inventato(self, barolo):
        ok, inv = verifica("Ha vinto i Tre Bicchieri del Gambero Rosso.", barolo)
        assert not ok
        assert any("Bicchieri" in x or "Gambero" in x for x in inv)

    def test_scarta_un_numero_inventato(self, barolo):
        ok, inv = verifica("Le vigne stanno a 400 metri di altitudine.", barolo)
        assert not ok
        assert "400" in inv

    def test_scarta_un_luogo_inventato(self, barolo):
        ok, inv = verifica("Nasce sulle colline di Serralunga.", barolo)
        assert not ok
        assert "Serralunga" in inv

    def test_accetta_l_annata_dei_fatti(self, barolo):
        assert verifica("L'annata 2016 è stata generosa.", barolo)[0]

    def test_scarta_un_annata_diversa(self, barolo):
        ok, inv = verifica("L'annata 2011 è stata generosa.", barolo)
        assert not ok and "2011" in inv

    def test_ignora_le_maiuscole_di_inizio_frase(self, barolo):
        assert verifica("Questo vino nasce dal Nebbiolo. Ottimo.", barolo)[0]

    def test_ignora_gli_articoli_maiuscoli(self, barolo):
        assert verifica("Il Nebbiolo. La struttura. Un vino.", barolo)[0]

    def test_un_vitigno_solo_ammesso_e_invenzione(self, barolo):
        """Il caso Amarone/Croatina: il disciplinare lo ammette, il vino non lo contiene."""
        ok, inv = verifica("Contiene anche un tocco di Croatina.", barolo)
        assert not ok, "un vitigno solo AMMESSO non puo' essere dichiarato presente"

    def test_testo_vuoto(self, barolo):
        assert verifica("", barolo)[0]


class TestTemplate:
    def test_il_livello_vino_e_affermativo(self, barolo):
        t = template(barolo)
        assert "Questo è il" in t
        assert "Cannubi" in t and "Marchesi di Barolo" in t

    def test_il_livello_tipologia_dichiara_l_incertezza(self):
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo Riserva",
                  denominazione="Barolo")
        t = template(f)
        assert "non riesco a leggere" in t.lower()
        assert "Barolo Riserva" in t

    def test_il_livello_vitigno_non_attribuisce_al_produttore(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"])
        t = template(f)
        assert "produttore non sono sicuro" in t.lower()

    def test_il_template_supera_sempre_la_verifica(self, barolo):
        """La rete di sicurezza non puo' essere quella che inventa."""
        assert verifica(template(barolo), barolo)[0]

    def test_la_temperatura_si_legge_ad_alta_voce(self, barolo):
        """'17-19' pronunciato diventa 'diciassette trattino diciannove'."""
        t = template(barolo)
        assert "17-19" not in t
        assert "fra 17 e 19 gradi" in t

    def test_fatti_vuoti_non_esplodono(self):
        assert template(Fatti()) != ""


class TestPrompt:
    def test_contiene_i_fatti(self, barolo):
        assert "Cannubi Barolo" in prompt(barolo)

    def test_non_contiene_i_vitigni_ammessi(self, barolo):
        """Il modello non deve nemmeno vederli: se li vede, li nomina."""
        p = prompt(barolo)
        assert "Croatina" not in p

    def test_avverte_quando_il_match_e_incerto(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        assert "produttore specifico" in prompt(f)

    def test_non_avverte_quando_il_match_e_certo(self, barolo):
        assert "produttore specifico" not in prompt(barolo)


class TestRipulisci:
    def test_toglie_le_virgolette(self):
        assert _ripulisci('"Un bel vino."') == "Un bel vino."

    def test_toglie_le_intestazioni(self):
        assert _ripulisci("Racconto: Un bel vino.") == "Un bel vino."

    def test_toglie_gli_elenchi(self):
        assert "-" not in _ripulisci("- Un bel vino.")

    def test_taglia_alla_frase_intera_quando_conviene(self):
        """Chiude su una frase se questo non butta via mezzo testo."""
        fuori = _ripulisci("Una frase. " * 60)
        assert len(fuori.split()) <= PAROLE_MAX
        assert fuori.endswith(".")

    def test_dichiara_il_troncamento_se_la_frase_e_troppo_indietro(self):
        """Meglio un troncamento coi puntini che due parole al posto di cento."""
        fuori = _ripulisci("Frase breve. " + "parola " * 300)
        assert len(fuori.split()) <= PAROLE_MAX
        assert fuori.endswith("…")
        assert len(fuori.split()) > 50

    def test_normalizza_gli_spazi(self):
        assert _ripulisci("Un   bel\n\nvino.") == "Un bel vino."


class TestAFrasi:
    def test_raggruppa_i_token_in_frasi(self):
        token = ["Que", "sto ", "è ", "un ", "Barolo. ", "Nasce ", "in ", "Langa. "]
        assert list(a_frasi(iter(token))) == ["Questo è un Barolo.", "Nasce in Langa."]

    def test_restituisce_la_coda_senza_punto(self):
        assert list(a_frasi(iter(["Senza punto finale"]))) == ["Senza punto finale"]

    def test_flusso_vuoto(self):
        assert list(a_frasi(iter([]))) == []


class TestRacconto:
    def test_spezza_in_frasi(self):
        r = Racconto(testo="Prima. Seconda! Terza?", origine="template",
                     livello=Livello.VINO)
        assert len(r.frasi) == 3
