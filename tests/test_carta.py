"""Test della carta dei vini: un file di testo al posto dell'archivio.

Quello che si verifica qui è che la regola dell'archivio — **non si nomina ciò
che non si è letto** — valga anche qui, e più severa. In archivio il veto
riguarda le parole che IDENTIFICANO un vino; qui anche quelle che lo
distinguono, perché una carta ha «Champagne Extra Brut» e «Champagne Brut Sans
Année» come voci separate, e sono due vini diversi.

E vale di più perché il danno è peggiore: la descrizione è lunga, dettagliata e
scritta da una persona. Attaccarla alla bottiglia sbagliata sarebbe un errore
raccontato benissimo.
"""

import csv

import pytest

pytest.importorskip("rapidfuzz")

from amelie.carta import Carta, CartaVuota  # noqa: E402

CARTA = [
    ("Barolo DOCG", "Nebbiolo in purezza sulle Langhe."),
    ("Soave DOC", "Garganega sui colli veronesi."),
    ("Soave DOC Classico", "La zona storica, sui suoli vulcanici."),
    ("Soave Superiore DOCG", "Rese più basse e un anno di affinamento."),
    ("Champagne AOC", "Chardonnay, Pinot Nero e Meunier sul gesso."),
    ("Champagne Extra Brut AOC", "Fra zero e sei grammi di residuo."),
    ("Champagne Rosé AOC", "Per salasso o per assemblaggio."),
    ("Chianti DOCG", "Sangiovese su un'area vastissima."),
    ("Chianti Classico DOCG Annata", "Il gradino base della zona storica."),
    ("Chianti Classico DOCG Riserva", "Almeno ventiquattro mesi."),
]


@pytest.fixture
def carta(tmp_path):
    f = tmp_path / "vini.csv"
    with open(f, "w", encoding="utf-8", newline="") as g:
        w = csv.writer(g, quoting=csv.QUOTE_ALL)
        w.writerow(["titolo", "descrizione"])
        w.writerows(CARTA)
    return Carta(f)


class TestCaricare:
    def test_legge_le_voci(self, carta):
        assert len(carta.voci) == len(CARTA)

    def test_una_voce_senza_descrizione_si_salta(self, tmp_path):
        f = tmp_path / "v.csv"
        f.write_text('titolo,descrizione\n"Barolo DOCG","x"\n"Vuoto",""\n',
                     encoding="utf-8")
        assert [v.titolo for v in Carta(f).voci] == ["Barolo DOCG"]

    def test_un_file_senza_voci_e_un_errore_dichiarato(self, tmp_path):
        f = tmp_path / "v.csv"
        f.write_text("titolo,descrizione\n", encoding="utf-8")
        with pytest.raises(CartaVuota):
            Carta(f)


class TestNonSiPrometteCioCheNonSiELetto:
    def test_un_titolo_che_promette_troppo_non_si_dice(self, carta):
        """«CHAMPAGNE BRUT» non è un Extra Brut: sono dosaggi diversi, e
        «extra» sulla bottiglia non c'era."""
        v = carta.cerca(["CHAMPAGNE", "BRUT", "RESERVE"])
        assert v is not None
        assert v.titolo == "Champagne AOC"

    def test_e_nemmeno_un_rosé_che_nessuno_ha_letto(self, carta):
        v = carta.cerca(["CHAMPAGNE", "BRUT"])
        assert v.titolo == "Champagne AOC"

    def test_ma_se_c_e_scritto_si_dice_eccome(self, carta):
        v = carta.cerca(["CHAMPAGNE", "ROSÉ", "AOC"])
        assert v.titolo == "Champagne Rosé AOC"

    def test_un_vino_che_non_c_e_non_si_inventa(self, carta):
        assert carta.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"]) is None

    def test_e_nemmeno_da_una_parola_sola_che_non_c_entra(self, carta):
        assert carta.cerca(["20", "aka", "21"]) is None

    def test_senza_niente_da_leggere_non_si_risponde(self, carta):
        assert carta.cerca([]) is None
        assert carta.cerca(["12", "75"]) is None


class TestSiSceglieIlPiuSpecificoFraIVeri:
    """La somiglianza da sola sceglie male: «Soave DOC» è un sottoinsieme di
    «Soave DOC Classico», e fanno cento tutti e due. Vince chi spiega di più
    dell'etichetta, fra quelli che si possono dire."""

    def test_il_classico_vince_quando_c_e_scritto(self, carta):
        assert carta.cerca(["SOAVE", "CLASSICO", "DOC"]).titolo == "Soave DOC Classico"

    def test_e_il_nudo_quando_non_c_e(self, carta):
        assert carta.cerca(["SOAVE", "DOC", "2022"]).titolo == "Soave DOC"

    def test_il_superiore_non_si_regala(self, carta):
        v = carta.cerca(["SOAVE", "DOC"])
        assert "Superiore" not in v.titolo

    def test_annata_non_si_deve_leggere(self, carta):
        """Nel Chianti Classico «Annata» è il nome del gradino base e
        sull'etichetta non compare mai: chi ne imbottiglia una scrive «Chianti
        Classico» e basta."""
        v = carta.cerca(["CHIANTI", "CLASSICO", "DOCG", "2018"])
        assert v.titolo == "Chianti Classico DOCG Annata"

    def test_e_la_riserva_invece_si(self, carta):
        v = carta.cerca(["CHIANTI", "CLASSICO", "RISERVA", "DOCG"])
        assert v.titolo == "Chianti Classico DOCG Riserva"


class TestLOcrSbagliaLeLettere:
    def test_un_refuso_non_fa_perdere_il_vino(self, carta):
        """Misurato sul dispositivo: l'OCR ha letto «CERUOLO» e la bottiglia è
        stata riconosciuta lo stesso. Il riscontro è per parola e un refuso
        vale ottanta su cento."""
        assert carta.cerca(["BAROLC", "DOCG"]).titolo == "Barolo DOCG"

    def test_ma_una_parola_diversa_si(self, carta):
        assert carta.cerca(["BARBERA", "DOCG"]) is None


class TestLeVicine:
    """Servono al giornale, non alla voce: se il titolo giusto è fra queste, il
    problema è la regola o l'OCR; se non c'è, il problema è la carta."""

    def test_dice_cosa_ha_scartato(self, carta):
        vicine = carta.vicine(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert vicine and all(isinstance(x, str) for x in vicine)

    def test_senza_niente_da_leggere_non_dice_niente(self, carta):
        assert carta.vicine([]) == []


class TestCioCheLaCartaDaPerScontato:
    """Sul dispositivo, etichetta vera: l'OCR ha letto «Brunello» e tre
    frammenti, e la regola ha scartato «Brunello di Montalcino DOCG» perché
    «Montalcino» sul vetro non c'era. Ma in carta non esiste un altro Brunello:
    ogni voce che contiene quella parola contiene anche «Montalcino».

    Non è un'eccezione scritta a mano: è una proprietà del file, e cambiando la
    carta cambia da sola.
    """

    @pytest.fixture
    def carta(self, tmp_path):
        f = tmp_path / "vini.csv"
        with open(f, "w", encoding="utf-8", newline="") as g:
            w = csv.writer(g, quoting=csv.QUOTE_ALL)
            w.writerow(["titolo", "descrizione"])
            w.writerows([
                ("Brunello di Montalcino DOCG", "Sangiovese grosso, cinque anni."),
                ("Brunello di Montalcino DOCG Riserva", "Sei anni, di cui due in legno."),
                ("Rosso di Montalcino DOC", "Il fratello minore, un anno."),
                ("Champagne AOC", "Chardonnay, Pinot Nero e Meunier."),
                ("Champagne Extra Brut AOC", "Fra zero e sei grammi."),
                ("Champagne Rosé AOC", "Per salasso o assemblaggio."),
            ])
        return Carta(f)

    def test_una_parola_che_non_ha_omonimi_basta(self, carta):
        v = carta.cerca(["Affinato in botidm", "0E61", "Brunello"])
        assert v is not None and v.titolo == "Brunello di Montalcino DOCG"

    def test_ma_la_riserva_resta_da_guadagnarsi(self, carta):
        """«Riserva» sta in una delle due voci e non nell'altra: non è
        implicata da niente."""
        v = carta.cerca(["Brunello"])
        assert "Riserva" not in v.titolo

    def test_e_l_extra_brut_pure(self, carta):
        """Il caso che ha fatto nascere la regola non deve smentirla: se a
        restringere la famiglia bastasse «brut», resterebbe in piedi il solo
        Extra Brut e «extra» risulterebbe implicato."""
        v = carta.cerca(["CHAMPAGNE", "BRUT", "RESERVE"])
        assert v.titolo == "Champagne AOC"

    def test_e_il_rosso_di_montalcino_non_diventa_un_brunello(self, carta):
        v = carta.cerca(["ROSSO", "DI", "MONTALCINO", "DOC"])
        assert v.titolo == "Rosso di Montalcino DOC"
