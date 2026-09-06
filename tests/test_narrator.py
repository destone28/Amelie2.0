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


class TestColoreContraddetto:
    """L'errore piu' visibile, e quello che un modello piccolo fa piu' spesso.

    Sul serio, in pre-generazione, il modello ha scritto che la Falanghina -
    vitigno a bacca BIANCA - e' «un vino rosso di campagna con tannicita'
    bassa». Non e' un'imprecisione: e' falso, e un sommelier lo coglie subito.
    """

    @pytest.fixture
    def bianco(self):
        return Fatti(livello=Livello.VITIGNO, vitigni=["Falanghina"],
                     colore_bacca="bianca")

    @pytest.fixture
    def rosso(self):
        return Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"],
                     colore_bacca="nera")

    def test_scarta_rosso_su_un_bianco(self, bianco):
        ok, inv = verifica("La Falanghina è un vino rosso di campagna.", bianco)
        assert not ok and "colore" in inv[0]

    def test_scarta_il_tannino_su_un_bianco(self, bianco):
        assert not verifica("Ha una tannicità bassa e piacevole.", bianco)[0]

    def test_accetta_bianco_su_un_bianco(self, bianco):
        assert verifica("Dà bianchi freschi e floreali.", bianco)[0]

    def test_scarta_paglierino_su_un_rosso(self, rosso):
        assert not verifica("Un giallo paglierino luminoso.", rosso)[0]

    def test_accetta_rubino_su_un_rosso(self, rosso):
        assert verifica("Un rosso rubino di bella intensità.", rosso)[0]

    def test_senza_colore_dichiarato_non_giudica(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        assert verifica("Un vino rosso intenso.", f)[0]


class TestTemplate:
    def test_il_livello_vino_e_affermativo(self, barolo):
        t = template(barolo)
        assert "Questo è il" in t
        assert "Cannubi" in t and "Marchesi di Barolo" in t

    def test_il_livello_tipologia_dichiara_l_incertezza(self):
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo Riserva",
                  denominazione="Barolo", sicurezza=80.0)
        t = template(f)
        assert "non riesco a leggere" in t.lower()
        assert "Barolo Riserva" in t

    def test_il_livello_vitigno_non_attribuisce_al_produttore(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=80.0)
        t = template(f)
        assert "produttore non sono sicuro" in t.lower()

    def test_un_vino_certo_si_annuncia_come_certo(self):
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=95.0)
        assert template(f).startswith("Questo è il")

    def test_un_vino_dubbio_non_si_annuncia_come_certo(self):
        """Sicurezza 80: il record e' completo, la somiglianza no."""
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=80.0)
        t = template(f)
        assert not t.startswith("Questo è il")
        assert "Direi che è il" in t
        assert "Barolo Cannubi" in t

    def test_una_somiglianza_bassa_si_dichiara_tale(self):
        """Il difetto piu' insidioso: un record perfetto trovato male.

        MATCH_ASSENTE porta al racconto anche sotto la soglia dubbia. Se
        l'apertura guardasse solo il livello, il dispositivo direbbe al tavolo
        «Questo è il Barolo di Marchesi di Barolo» con il 60% di somiglianza.
        """
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", sicurezza=60.0)
        t = template(f)
        assert "non è nitida" in t
        assert "potrebbe essere" in t.lower()

    def test_anche_i_livelli_deboli_si_smorzano_sotto_la_soglia(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=50.0)
        assert "non è nitida" in template(f)

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


@pytest.fixture(scope="module")
def matcher():
    from amelie.matcher import Matcher
    m = Matcher()
    yield m
    m.chiudi()


class TestDueLingue:
    """Il racconto in inglese dev'essere inglese, non parole inglesi in frasi italiane."""

    # Solo connettivi inequivocabili. Fuori « di », « un », « con »: compaiono
    # nei NOMI PROPRI - "Marchesi di Barolo", "Nero d'Avola" - che non si
    # traducono, e un test che li vietasse fallirebbe sul testo giusto.
    PAROLE_ITALIANE = (" è ", " si serve ", " nasce da ", " gradi.",
                       " bene a ", "questo è", "l'etichetta")

    def test_il_racconto_inglese_non_contiene_impalcatura_italiana(self, matcher):
        for righe in (["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"],
                      ["Etna Rosso"], ["Nebbiolo"], ["Chianti Classico"]):
            f = matcher.cerca(righe)
            testo = f" {template(f, lingua='en').lower()} "
            trovate = [p for p in self.PAROLE_ITALIANE if p in testo]
            assert not trovate, f"{righe}: {trovate} in {testo!r}"

    def test_l_articolo_inglese_segue_il_suono(self, matcher):
        """«a Etna Rosso» si sente subito."""
        f = matcher.cerca(["Etna Rosso"])
        assert "an Etna Rosso" in template(f, lingua="en")

    def test_lo_stesso_vino_si_racconta_in_due_lingue(self, matcher):
        f = matcher.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        it, en = template(f, lingua="it"), template(f, lingua="en")
        assert it != en
        for testo in (it, en):
            assert "Cannubi" in testo, "il nome del vino sparisce"
            assert "2016" in testo, "l'annata sparisce"

    def test_la_temperatura_non_si_spezza_in_inglese(self, matcher):
        f = matcher.cerca(["Nebbiolo"])
        testo = template(f, lingua="en")
        assert "17-19" not in testo, "il trattino va sciolto: lo legge una voce"
        assert "between 17 and 19" in testo
