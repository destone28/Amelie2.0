"""Le bottiglie corrette a mano: salvare, ritrovare, e soprattutto non sbagliare.

Il caso che conta di piu' e' l'ultimo: una bottiglia DIVERSA non deve mai
prendersi la descrizione di un'altra. E' la bugia che il resto del progetto si
sforza di non dire, e qui la direbbe con le parole di una persona.
"""
from __future__ import annotations

import json

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from amelie.correzioni import (  # noqa: E402
    Correzioni, Regola, parole_identificanti, parole_in_comune, zona_etichetta,
)
from amelie.ocr import Riga  # noqa: E402


def _etichetta(testo: str, seme: int, larghezza=600, altezza=1400):
    """Un'etichetta finta ma con dettaglio vero: rumore fisso per seme, e le
    scritte in mezzo. ORB ha bisogno di angoli, e un fondo piatto non ne ha."""
    rng = np.random.default_rng(seme)
    im = np.full((altezza, larghezza, 3), 235, np.uint8)
    for _ in range(260):
        x, y = rng.integers(40, larghezza - 40), rng.integers(300, 1100)
        r = int(rng.integers(4, 22))
        c = tuple(int(v) for v in rng.integers(0, 200, 3))
        cv2.circle(im, (int(x), int(y)), r, c, -1)
        cv2.rectangle(im, (int(x), int(y)), (int(x) + r, int(y) + 2 * r), c, 2)
    righe = []
    for i, riga in enumerate(testo.split("|")):
        y = 520 + i * 110
        cv2.putText(im, riga, (70, y), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 5)
        righe.append(Riga(testo=riga, confidenza=.9,
                          riquadro=((60, y - 60), (560, y - 60), (560, y + 20), (60, y + 20))))
    return im, righe


@pytest.fixture
def archivio(tmp_path):
    return Correzioni(tmp_path / "correzioni")


class TestParole:
    def test_si_tengono_solo_le_parole_che_identificano(self):
        p = parole_identificanti(["ALBAROSSA", "NEGROAMARO", "ROSATO", "DOC", "2023", "PALAMÀ"])
        assert "albarossa" in p and "negroamaro" in p and "palama" in p
        # «rosato», «doc» e l'annata stanno su migliaia di bottiglie
        assert "rosato" not in p and "doc" not in p and "2023" not in p

    def test_l_ocr_che_sbaglia_una_lettera_conta_lo_stesso(self):
        quota, prese = parole_in_comune(["negroamaro", "palama", "salento"],
                                        ["necroamaro", "palama"])
        assert prese == 2 and quota == pytest.approx(2 / 3)

    def test_una_parola_letta_ne_conferma_una_sola(self):
        """«MONTEPULCIANO» scritto due volte non prova due parole ricordate."""
        _, prese = parole_in_comune(["montepulciano", "montepulciani"], ["montepulciano"])
        assert prese == 1


class TestZonaDellEtichetta:
    def test_attorno_alle_righe_con_parole_vere(self):
        _, righe = _etichetta("PALAMA|NEGROAMARO", 1)
        zona = zona_etichetta(righe, (1400, 600))
        x0, y0, x1, y1 = zona
        assert y0 < 460 and y1 > 650          # contiene le due righe
        assert y0 > 100 and y1 < 1300         # ma non tutta la foto

    def test_senza_parole_non_c_e_etichetta(self):
        """Un calendario dietro al piatto da' solo numeri: nessuna zona, e
        l'immagine non deve dire niente."""
        righe = [Riga("2026", .9, ((0, 0), (80, 0), (80, 30), (0, 30))),
                 Riga("17 18", .9, ((0, 40), (80, 40), (80, 70), (0, 70)))]
        assert zona_etichetta(righe, (1400, 600)) is None


class TestSalvareERitrovare:
    def test_la_stessa_bottiglia_si_ritrova(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        archivio.salva(righe=righe, immagine=im, titolo="Albarossa Negroamaro",
                       descrizione="Un rosato del Salento.", lingua="it")
        r = archivio.cerca(righe, im)
        assert r is not None and r.correzione.testo_in("it")["titolo"] == "Albarossa Negroamaro"

    def test_riletta_male_e_un_po_girata(self, archivio):
        """Come succede davvero: l'OCR sbaglia una lettera e la bottiglia e'
        appoggiata un po' diversa."""
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                       descrizione="Un rosato.", lingua="it")
        m = cv2.getRotationMatrix2D((300, 700), 3, 1.0)
        girata = cv2.warpAffine(im, m, (600, 1400), borderValue=(235, 235, 235))
        _, righe2 = _etichetta("PALAMA|NECROAMARO|ALBAROSSA", 7)
        assert archivio.cerca(righe2, girata) is not None

    def test_una_bottiglia_diversa_non_si_prende_la_correzione(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                       descrizione="Un rosato.", lingua="it")
        altra, righe_altra = _etichetta("CORTE DEL BORGO|LAMBRUSCO|GRASPAROSSA", 99)
        assert archivio.cerca(righe_altra, altra) is None

    def test_le_stesse_parole_su_un_etichetta_diversa_non_bastano(self, archivio):
        """Due vini dello stesso produttore: le scritte coincidono, la foto no.
        Le parole d'accordo non bastano se l'immagine dice di no."""
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                       descrizione="Un rosato.", lingua="it")
        sorella, righe_s = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 12345)
        assert archivio.cerca(righe_s, sorella) is None

    def test_senza_correzioni_non_si_cerca_niente(self, archivio):
        im, righe = _etichetta("PALAMA", 1)
        assert archivio.cerca(righe, im) is None


class TestLingueEViste:
    def test_una_lingua_non_scrive_sull_altra(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO", 3)
        c = archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                           descrizione="Un rosato del Salento.", lingua="it")
        archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                       descrizione="A rosé from Salento.", lingua="en", ident=c.id)
        c = archivio.trova(c.id)
        assert c.testo_in("it")["descrizione"] == "Un rosato del Salento."
        assert c.testo_in("en")["descrizione"] == "A rosé from Salento."

    def test_ogni_conferma_aggiunge_una_vista(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO", 3)
        c = archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="B", lingua="it")
        archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="C", lingua="it",
                       ident=c.id)
        assert len(archivio.trova(c.id).viste) == 2

    def test_la_lingua_che_manca_non_c_e(self, archivio):
        im, righe = _etichetta("PALAMA", 3)
        c = archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="B", lingua="it")
        assert c.testo_in("en") is None


class TestSulDisco:
    def test_sopravvive_al_riavvio(self, tmp_path):
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        prima = Correzioni(tmp_path / "c")
        c = prima.salva(righe=righe, immagine=im, titolo="Albarossa",
                        descrizione="Un rosato.", lingua="it")
        dopo = Correzioni(tmp_path / "c")
        assert dopo.trova(c.id).testo_in("it")["titolo"] == "Albarossa"
        assert dopo.cerca(righe, im) is not None
        assert (tmp_path / "c" / c.id / "vista-1.jpg").is_file()

    def test_un_file_rovinato_non_ferma_gli_altri(self, tmp_path):
        im, righe = _etichetta("PALAMA", 7)
        a = Correzioni(tmp_path / "c")
        a.salva(righe=righe, immagine=im, titolo="Buona", descrizione="Ok.", lingua="it")
        rotta = tmp_path / "c" / "rotta"
        rotta.mkdir()
        (rotta / "correzione.json").write_text("{ non e' json", encoding="utf-8")
        assert len(Correzioni(tmp_path / "c").tutte()) == 1

    def test_titolo_e_descrizione_servono_tutti_e_due(self, archivio):
        im, righe = _etichetta("PALAMA", 7)
        with pytest.raises(ValueError):
            archivio.salva(righe=righe, immagine=im, titolo="  ", descrizione="x", lingua="it")

    def test_si_elimina(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO", 7)
        c = archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="B", lingua="it")
        assert archivio.elimina(c.id)
        assert archivio.cerca(righe, im) is None
        assert not (archivio.cartella / c.id).exists()

    def test_il_testo_si_ripulisce(self, archivio):
        im, righe = _etichetta("PALAMA", 7)
        c = archivio.salva(righe=righe, immagine=im, titolo="  Albarossa \x07 ",
                           descrizione="Riga uno\n\n\n\nRiga due", lingua="it")
        t = c.testo_in("it")
        assert t["titolo"] == "Albarossa" and t["descrizione"] == "Riga uno\n\nRiga due"


class TestLaRegola:
    """La regola da sola, senza foto: quali combinazioni bastano."""

    @staticmethod
    def _basta(archivio, parole, prese, immagine):
        from amelie.correzioni import Riscontro
        return archivio._basta(Riscontro(correzione=None, parole=parole,
                                         parole_prese=prese, immagine=immagine))

    def test_l_immagine_schiacciante_basta_da_sola(self, archivio):
        """L'OCR stavolta non ha letto niente, ma la foto e' la stessa."""
        assert self._basta(archivio, 0.0, 0, Regola().immagine_da_sola)

    def test_sotto_quella_soglia_l_immagine_da_sola_no(self, archivio):
        assert not self._basta(archivio, 0.0, 0, Regola().immagine_da_sola - 1)

    def test_una_parola_sola_in_comune_non_basta(self, archivio):
        """Una parola sola e' una coincidenza: «Salento» sta su mille etichette.
        Venti punti d'immagine basterebbero con due parole, non con una."""
        assert not self._basta(archivio, 1.0, 1, 20)
        assert self._basta(archivio, 1.0, 2, 20)

    def test_parole_d_accordo_ma_immagine_contraria(self, archivio):
        """Due vini dello stesso produttore: le scritte coincidono, la foto no."""
        assert not self._basta(archivio, 1.0, 3, Regola().immagine_con_parole - 1)

    def test_parole_e_immagine_d_accordo(self, archivio):
        assert self._basta(archivio, .67, 2, Regola().immagine_con_parole)


class TestLeVicine:
    """Una bottiglia gia' corretta che stavolta non e' stata riconosciuta: chi
    la ricorregge deve poterla ritrovare, non crearne un doppione."""

    def test_basta_una_parola_perche_una_persona_scelga(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
        c = archivio.salva(righe=righe, immagine=im, titolo="Albarossa",
                           descrizione="Un rosato.", lingua="it")
        _, altre = _etichetta("PALAMA|APADOSEN", 50)
        assert [x.id for x in archivio.vicine(altre)] == [c.id]

    def test_senza_parole_in_comune_nessuna(self, archivio):
        im, righe = _etichetta("PALAMA|NEGROAMARO", 7)
        archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="B", lingua="it")
        _, altre = _etichetta("LAMBRUSCO|GRASPAROSSA", 50)
        assert archivio.vicine(altre) == []

    def test_la_foto_per_riconoscerla_a_occhio(self, archivio):
        im, righe = _etichetta("PALAMA", 7)
        c = archivio.salva(righe=righe, immagine=im, titolo="A", descrizione="B", lingua="it")
        assert archivio.foto(c.id).name == "vista-1.jpg"
        assert archivio.foto("non-esiste") is None


def test_il_collegamento_si_salva_e_si_ricarica(tmp_path):
    """Una correzione collegata a un vino conosciuto non ha bisogno della
    descrizione, e il collegamento sopravvive al riavvio."""
    im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
    arch = Correzioni(tmp_path)
    rif = {"tipo": "archivio", "ambito": "vino", "id": 510, "titolo": "Cannubi Barolo"}
    c = arch.salva(righe=righe, immagine=im, titolo="Cannubi Barolo", descrizione="",
                   lingua="it", riferimento=rif)
    assert c.testo_in("it") is None and c.riferimento == rif
    di_nuovo = Correzioni(tmp_path).trova(c.id)
    assert di_nuovo.riferimento == rif and di_nuovo.titolo() == "Cannubi Barolo"
    # aggiungendo una foto senza dire niente del collegamento, resta
    arch.salva(righe=righe, immagine=im, titolo="Cannubi Barolo", descrizione="",
               lingua="it", ident=c.id)
    assert arch.trova(c.id).riferimento == rif
    with pytest.raises(ValueError):
        arch.salva(righe=righe, immagine=im, titolo="Senza niente", descrizione="",
                   lingua="it")
