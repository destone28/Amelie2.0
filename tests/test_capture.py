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
        su PAROLE, non su caratteri: una riga un po' storta vale molto più di
        una riga assente. A 0,58 del lato passava il 34% dell'area, e sul banco
        le etichette non venivano riconosciute anche quando erano nitide e ben
        illuminate. A 0,80 passa il 64%.
        """
        imp = ImpostazioniCamera()
        assert 0.7 <= imp.ritaglio <= 0.9
        area = imp.ritaglio ** 2
        assert area > 0.5, "sotto meta' area si perdono righe intere di etichetta"


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
        # il buffer UVC contiene fotogrammi precedenti alla luce: se non se ne
        # scartano abbastanza si legge un'immagine al buio
        imp = ImpostazioniCamera()
        assert imp.fotogrammi_da_scartare >= 4

    def test_immutabile(self):
        with pytest.raises(Exception):
            ImpostazioniCamera().esposizione = 999
