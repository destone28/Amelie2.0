"""Test della normalizzazione dell'uscita OCR.

Il motore vero non serve: qui si verifica che l'involucro regga entrambi i
formati di uscita di RapidOCR (quello 3.x a oggetto e quello vecchio a tuple),
che il filtro sulla confidenza funzioni, e che il riconoscimento delle righe
"grandi" — quelle dove sta la denominazione — sia sensato.
"""

import pytest

from amelie.ocr import (
    ImpostazioniOCR,
    Lettore,
    Lettura,
    Riga,
    _estrai_righe,
)


class UscitaNuova:
    """Come risponde RapidOCR 3.x."""

    def __init__(self, txts, scores, boxes=None):
        self.txts = txts
        self.scores = scores
        self.boxes = boxes


def riquadro(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class TestEstrazione:
    def test_formato_nuovo(self):
        u = UscitaNuova(["Barolo", "2019"], [0.98, 0.91])
        righe = _estrai_righe(u)
        assert [r.testo for r in righe] == ["Barolo", "2019"]
        assert righe[0].confidenza == pytest.approx(0.98)

    def test_formato_vecchio_a_tuple(self):
        grezzo = [
            (riquadro(0, 0, 100, 30), "Barolo", 0.98),
            (riquadro(0, 40, 60, 60), "2019", 0.91),
        ]
        righe = _estrai_righe(grezzo)
        assert [r.testo for r in righe] == ["Barolo", "2019"]

    def test_nessun_risultato(self):
        assert _estrai_righe(None) == []
        assert _estrai_righe([]) == []

    def test_uscita_incomprensibile_non_esplode(self):
        assert _estrai_righe(42) == []

    def test_elementi_malformati_vengono_saltati(self):
        grezzo = [
            (riquadro(0, 0, 10, 10), "Barolo", 0.9),
            ("spazzatura",),
            None,
        ]
        assert len(_estrai_righe(grezzo)) == 1

    def test_riquadro_illeggibile_non_perde_la_riga(self):
        righe = _estrai_righe(UscitaNuova(["Barolo"], [0.9], [["x", "y"]]))
        assert righe[0].testo == "Barolo"
        assert righe[0].riquadro == ()


class TestFiltro:
    def test_scarta_bassa_confidenza(self):
        lettore = Lettore(ImpostazioniOCR(confidenza_minima=0.6))
        assert lettore._tieni(Riga("Barolo", 0.9))
        assert not lettore._tieni(Riga("~~", 0.3))

    def test_scarta_righe_troppo_corte(self):
        lettore = Lettore(ImpostazioniOCR(lunghezza_minima=3))
        assert not lettore._tieni(Riga("ab", 0.99))
        assert lettore._tieni(Riga("abc", 0.99))

    def test_scarta_righe_di_soli_spazi(self):
        assert not Lettore()._tieni(Riga("     ", 0.99))


class TestRiga:
    def test_altezza_dal_riquadro(self):
        assert Riga("x", 0.9, tuple(map(tuple, riquadro(0, 10, 100, 40)))).altezza == 30

    def test_altezza_senza_riquadro(self):
        assert Riga("x", 0.9).altezza == 0.0


class TestLettura:
    def test_testo_unisce_le_righe(self):
        lettura = Lettura(righe=[Riga("Barolo", 0.9), Riga("2019", 0.9)])
        assert lettura.testo == "Barolo\n2019"

    def test_vuota(self):
        assert Lettura().vuota
        assert not Lettura(righe=[Riga("x", 0.9)]).vuota

    def test_righe_grandi_trovano_la_denominazione(self):
        """Sull'etichetta la denominazione è scritta grande, i solfiti piccoli."""
        lettura = Lettura(righe=[
            Riga("BAROLO", 0.99, tuple(map(tuple, riquadro(0, 0, 200, 50)))),
            Riga("contiene solfiti", 0.8, tuple(map(tuple, riquadro(0, 90, 80, 98)))),
        ])
        grandi = [r.testo for r in lettura.righe_grandi()]
        assert grandi == ["BAROLO"]

    def test_righe_grandi_senza_riquadri_le_tiene_tutte(self):
        lettura = Lettura(righe=[Riga("a", 0.9), Riga("b", 0.9)])
        assert len(lettura.righe_grandi()) == 2

    def test_righe_grandi_su_lettura_vuota(self):
        assert Lettura().righe_grandi() == []


class TestImpostazioni:
    def test_il_classificatore_di_orientamento_resta_acceso(self):
        """Era spento, e spegnerlo costava quasi tutto.

        La motivazione era «sul supporto l'etichetta è sempre dritta, il
        classificatore è tempo sprecato». Sbagliata due volte. Su una bottiglia
        il testo non è quasi mai orizzontale nel fotogramma — cilindro,
        appoggio, camera che guarda dal basso e di sbieco — e su un'etichetta
        scritta lungo l'asse arriva ruotato di novanta gradi.

        Misurato su tre scatti veri della stessa bottiglia:

            spento    `DOLA | SILIA | NER`        vitigno, 61   6,6 s
            acceso    `D'AVOLA | SICILIA | NERO`  tipologia, 87 4,9 s

        Più accurato **e** più veloce: raddrizzare un ritaglio prima di
        riconoscerlo fa risparmiare al riconoscitore il lavoro di indovinare.
        """
        assert ImpostazioniOCR().usa_classificatore is True

    def test_non_si_alza_la_risoluzione_del_rilevatore(self):
        """L'altra cosa che verrebbe da fare, e che peggiora.

        Sugli stessi tre scatti, 1536 ha dato `AVOLA | SICILIA | (0 | 10 | NERO`
        in 12,0 s contro `D'AVOLA | SICILIA | NERO` in 4,9 s a 736: più
        spazzatura e il doppio del tempo.
        """
        assert ImpostazioniOCR().lato_massimo == 736

    def test_immutabile(self):
        with pytest.raises(Exception):
            ImpostazioniOCR().lato_massimo = 1
