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
        """L'OCR sbaglia spesso una lettera, e la bottiglia va riconosciuta lo
        stesso: il riscontro è per parola, e un refuso vale ottanta su cento."""
        assert carta.cerca(["BAROLC", "DOCG"]).titolo == "Barolo DOCG"

    def test_ma_una_parola_diversa_si(self, carta):
        assert carta.cerca(["BARBERA", "DOCG"]) is None


class TestLEtichettaLettaAPezzi:
    """Il vetro curvo si mangia l'inizio e la fine delle parole.

    Un Lambrusco tenuto in mano: ogni parola del titolo è sul vetro, ma a
    pezzi, e la somiglianza dell'intera stringa resta a 54 - sotto la soglia -
    anche con tutte le parole lette.
    """

    VOCI = [
        ("Lambrusco Grasparossa di Castelvetro DOC", "Frizzante, rosso scuro."),
        ("Lambrusco di Sorbara DOC", "Il piu' chiaro dei Lambruschi."),
        ("Franciacorta DOCG Brut", "Metodo classico in Lombardia."),
        ("Alentejo DOC", "Il sud del Portogallo."),
        ("Marino DOC", "Bianco dei Castelli Romani."),
    ]

    @pytest.fixture
    def lambrusco(self, tmp_path):
        f = tmp_path / "vini.csv"
        with open(f, "w", encoding="utf-8", newline="") as g:
            w = csv.writer(g, quoting=csv.QUOTE_ALL)
            w.writerow(["titolo", "descrizione"])
            w.writerows(self.VOCI)
        return Carta(f)

    def test_i_pezzi_del_titolo_bastano(self, lambrusco):
        righe = ["BORGO", "LAMBRUSCO", "PAROSSA DI CASTELVETN", "ourmd", "CORTE",
                 "DEL", "toncominasione di Crigine Contedlt", "VINO FRIZZANTE AMABILE"]
        assert lambrusco.cerca(righe).titolo == "Lambrusco Grasparossa di Castelvetro DOC"

    def test_ma_una_parola_sola_che_somiglia_no(self, lambrusco):
        """Serve una parola letta esatta e una seconda che la conferma: se
        bastasse una somiglianza, «SALENTO» farebbe «Alentejo» e «MARO»
        farebbe «Marino»."""
        assert lambrusco.cerca(["PALAMA", "NEGROAMARO", "SALENTO", "VINICOLA"]) is None
        assert lambrusco.cerca(["2026", "ALBAD", "PALAMÀ", "MARO", "22"]) is None

    def test_e_un_pezzo_troppo_lontano_nemmeno(self, lambrusco):
        """«raccolta» della retroetichetta somiglia a «franciacorta» per settanta
        su cento: se il pezzo bastasse, con «BRUT» esatto uno spumante pugliese
        diventerebbe un Franciacorta."""
        righe = ["PRODUTTORI MANDURIA", "Vino Spumante di Qualità", "METODO CLASSICO",
                 "BRUT ROSÉ", "RACCOLTA DIFERENZIATA VERIFICA LE DISPOSIZIONI"]
        assert lambrusco.cerca(righe) is None

    def test_il_nome_intero_porta_con_se_cio_che_la_carta_da_per_scontato(self, lambrusco):
        """«Castelvetro» sta in una voce sola: letto intero, insieme a un
        pezzo di «Lambrusco», basta anche se «Grasparossa» e' caduto oltre la
        curva. E «del» di «CORTE DEL BORGO», che sta in mezza carta, non deve
        disfare la famiglia."""
        righe = ["CORTE DEL BORGO", "OSSA DI CASTELVETRO", "AMBRUSCO",
                 "VINO FRIZZANTE AMABILE"]
        assert lambrusco.cerca(righe).titolo == "Lambrusco Grasparossa di Castelvetro DOC"

    def test_ma_una_parola_sola_non_si_porta_dietro_un_titolo(self, tmp_path):
        """Righe vere del giornale di bordo. Senza questa regola «TOSCANA» da
        sola diventerebbe «Maremma Toscana DOC Vermentino», e «VIN» di
        «VINICOLA», con «SALENTO» somigliante a «santo», diventerebbe un Vin
        Santo."""
        f = tmp_path / "vini.csv"
        with open(f, "w", encoding="utf-8", newline="") as g:
            w = csv.writer(g, quoting=csv.QUOTE_ALL)
            w.writerow(["titolo", "descrizione"])
            w.writerows([("Maremma Toscana DOC Vermentino", "x"),
                         ("Vin Santo del Chianti Classico DOC", "y"),
                         ("Chianti DOCG", "z")])
        c = Carta(f)
        assert c.cerca(["RUFFINO", "TOSCANA", "DAL 1877"]) is None
        assert c.cerca(["PALAMA", "ALBAL", "NICROAMARO", "SALENTO", "VIN"]) is None

    def test_e_la_parola_che_manca_resta_mancante(self, lambrusco):
        """«CAS» non e' «Castelvetro»: un titolo di cui manca una parola non si
        dice, pezzi o non pezzi."""
        assert lambrusco.cerca(["LAMBRUSCO", "SPAROSSA DI CAS"]) is None


class TestLeVicine:
    """Servono al giornale, non alla voce: se il titolo giusto è fra queste, il
    problema è la regola o l'OCR; se non c'è, il problema è la carta."""

    def test_dice_cosa_ha_scartato(self, carta):
        vicine = carta.vicine(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert vicine and all(isinstance(x, str) for x in vicine)

    def test_senza_niente_da_leggere_non_dice_niente(self, carta):
        assert carta.vicine([]) == []


class TestCioCheLaCartaDaPerScontato:
    """Un'etichetta vera da cui l'OCR legge «Brunello» e tre frammenti: la
    regola, da sola, scarterebbe «Brunello di Montalcino DOCG» perché
    «Montalcino» sul vetro non c'è. Ma in carta non esiste un altro Brunello:
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
        """Il caso che giustifica il veto resta vietato: se a restringere la
        famiglia bastasse «brut», resterebbe in piedi il solo Extra Brut e
        «extra» risulterebbe implicato."""
        v = carta.cerca(["CHAMPAGNE", "BRUT", "RESERVE"])
        assert v.titolo == "Champagne AOC"

    def test_e_il_rosso_di_montalcino_non_diventa_un_brunello(self, carta):
        v = carta.cerca(["ROSSO", "DI", "MONTALCINO", "DOC"])
        assert v.titolo == "Rosso di Montalcino DOC"


class TestLeLingueDellaCarta:
    """Una carta scritta solo in italiano non deve fingere di parlare inglese.

    Altrimenti, con l'inglese scelto, all'ospite arriverebbe la prima frase
    tradotta - quella la compone il lessico - e poi tutta la descrizione in
    italiano, **letta dalla voce inglese**: una frase italiana compitata
    all'inglese in mezzo a un testo inglese.
    """

    def test_un_file_con_la_sola_descrizione_parla_italiano(self, carta):
        assert carta.lingue == {"it"}
        v = carta.cerca(["BAROLO", "DOCG"])
        assert v.testo_in("it")
        assert v.testo_in("en") is None

    @pytest.fixture
    def bilingue(self, tmp_path):
        f = tmp_path / "vini.csv"
        with open(f, "w", encoding="utf-8", newline="") as g:
            w = csv.writer(g, quoting=csv.QUOTE_ALL)
            w.writerow(["titolo", "descrizione", "titolo_en", "descrizione_en"])
            w.writerow(["Barolo DOCG", "Nebbiolo sulle Langhe.",
                        "Barolo DOCG", "Nebbiolo from the Langhe hills."])
            w.writerow(["Soave DOC", "Garganega sui colli veronesi.", "", ""])
        return Carta(f)

    def test_le_colonne_dicono_le_lingue(self, bilingue):
        assert bilingue.lingue == {"it", "en"}

    def test_dove_c_e_l_inglese_si_usa_l_inglese(self, bilingue):
        v = bilingue.cerca(["BAROLO", "DOCG"])
        assert v.testo_in("en") == "Nebbiolo from the Langhe hills."
        assert v.titolo_in("en") == "Barolo DOCG"

    def test_ma_riga_per_riga_e_non_per_file(self, bilingue):
        """Il file parla inglese, questa voce no: e non si spaccia per tale."""
        v = bilingue.cerca(["SOAVE", "DOC"])
        assert v.testo_in("en") is None
        assert v.testo_in("it")

    def test_senza_titolo_tradotto_resta_quello_di_partenza(self, bilingue):
        v = bilingue.cerca(["SOAVE", "DOC"])
        assert v.titolo_in("en") == "Soave DOC"
