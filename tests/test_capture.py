"""Test delle funzioni pure di cattura.

L'apertura del device non è testabile senza hardware: qui si verificano il
ritaglio e la misura di nitidezza, che sono le due cose che possono sbagliare
in silenzio.
"""

import numpy as np
import pytest

from amelie.capture import (
    ImpostazioniCamera,
    Scatto,
    SOGLIA_NITIDEZZA,
    nitidezza,
    ritaglia_centro,
)


def immagine(h=100, w=200, valore=128):
    return np.full((h, w, 3), valore, dtype=np.uint8)


def immagine_a_scacchi(h=100, w=200, passo=4):
    """Molto contrasto locale: nitidezza alta."""
    yy, xx = np.mgrid[0:h, 0:w]
    piano = (((yy // passo) + (xx // passo)) % 2 * 255).astype(np.uint8)
    return np.dstack([piano] * 3)


class TestRitaglio:
    def test_dimensioni(self):
        out = ritaglia_centro(immagine(100, 200), 0.5)
        assert out.shape[:2] == (50, 100)

    def test_e_centrato(self):
        img = immagine(100, 100, valore=0)
        img[40:60, 40:60] = 255            # macchia bianca al centro
        out = ritaglia_centro(img, 0.5)    # tiene 50x50 centrali
        assert out.shape[:2] == (50, 50)
        assert out[25, 25, 0] == 255       # il centro è ancora al centro

    def test_frazione_uno_non_taglia(self):
        img = immagine(30, 40)
        assert ritaglia_centro(img, 1.0).shape == img.shape

    @pytest.mark.parametrize("frazione", [0, -0.1, 1.5])
    def test_frazione_non_valida(self, frazione):
        with pytest.raises(ValueError):
            ritaglia_centro(immagine(), frazione)

    def test_il_ritaglio_lascia_passare_abbastanza_etichetta(self):
        """Il compromesso va nella direzione opposta a quella che verrebbe da
        pensare.

        Stringere migliora ogni singolo carattere — meno distorsione a barile,
        niente vignettatura — ma toglie righe intere, e il riconoscimento lavora
        su PAROLE, non su caratteri. Misurato tre volte, sempre nella stessa
        direzione: 0,58 dava `'AVO`, 0,80 dava `NERO D'AV`, il fotogramma intero
        dà `NERO D'AVOL`. Una bottiglia in piedi occupa il fotogramma per il
        lungo, e tagliarne i bordi taglia le parole.
        """
        imp = ImpostazioniCamera()
        assert imp.ritaglio >= 0.8
        assert imp.ritaglio ** 2 > 0.6, "sotto questa area si perdono parole"

    def test_il_fotogramma_si_raddrizza(self):
        """La camera è montata ruotata di 90°, ed è la sua posizione giusta:
        una bottiglia è alta e stretta, e un sensore 16:9 girato di lato la
        inquadra per il lungo. Ma il testo dell'etichetta arriva coricato, e un
        riconoscitore di testo lavora su righe orizzontali."""
        assert ImpostazioniCamera().rotazione in (0, 90, 180, 270)
        assert ImpostazioniCamera().rotazione == 90

    def test_raddrizzare_scambia_i_lati(self):
        from amelie.capture import Camera

        c = Camera()
        alto = c._raddrizza(immagine(40, 90))
        assert alto.shape[:2] == (90, 40), "novanta gradi scambiano i lati"


class TestNitidezza:
    def test_uniforme_e_piatta(self):
        assert nitidezza(immagine()) == pytest.approx(0.0, abs=1e-6)

    def test_scacchi_piu_nitidi_di_uniforme(self):
        assert nitidezza(immagine_a_scacchi()) > nitidezza(immagine())

    def test_sfocare_abbassa_la_nitidezza(self):
        import cv2

        netta = immagine_a_scacchi()
        sfocata = cv2.GaussianBlur(netta, (9, 9), 0)
        assert nitidezza(sfocata) < nitidezza(netta)

    def test_restituisce_float(self):
        assert isinstance(nitidezza(immagine_a_scacchi()), float)


class TestScatto:
    def test_sospetto_mosso_sotto_soglia(self):
        s = Scatto(immagine=immagine(), nitidezza=SOGLIA_NITIDEZZA - 1)
        assert s.sospetto_mosso

    def test_non_sospetto_sopra_soglia(self):
        s = Scatto(immagine=immagine(), nitidezza=SOGLIA_NITIDEZZA + 1)
        assert not s.sospetto_mosso


class TestImpostazioni:
    def test_scarta_prima_di_tenere(self):
        """Il buffer UVC contiene fotogrammi precedenti alla luce: senza scarto
        si legge un'immagine al buio.

        Erano cinque, scelti quando un fotogramma costava 30 ms. A 90 ms
        costavano un secondo intero, e la scena è ferma: lo scarto serve a
        svuotare il buffer, non a mediare, e tre bastano.
        """
        imp = ImpostazioniCamera()
        assert imp.fotogrammi_da_scartare >= 3

    def test_immutabile(self):
        with pytest.raises(Exception):
            ImpostazioniCamera().esposizione = 999
