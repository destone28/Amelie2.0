"""Test del giornale di bordo.

Quello che si verifica qui non è che sappia scrivere: è che **non smetta mai di
raccontare vini per colpa sua**. Un dispositivo che si pianta perché non è
riuscito a salvare una riga di diagnostica ha invertito le priorità, e questo
gira su una board in sala senza nessuno che la sorvegli.
"""

import json

import pytest

from amelie.giornale import Giornale


def voce(nome="Barolo"):
    return {"righe": ["BAROLO", "2016"], "livello": "vino", "nome": nome}


class TestAnnotare:
    def test_una_riga_per_scansione(self, tmp_path):
        g = Giornale(tmp_path)
        g.annota(voce("Barolo"))
        g.annota(voce("Chianti"))
        righe = g.percorso.read_text(encoding="utf-8").strip().splitlines()
        assert len(righe) == 2
        assert json.loads(righe[0])["nome"] == "Barolo"

    def test_ogni_voce_sa_quando(self, tmp_path):
        """Senza l'ora, tre scansioni uguali sono indistinguibili."""
        g = Giornale(tmp_path)
        g.annota(voce())
        assert "quando" in g.ultime()[0]

    def test_le_ultime_arrivano_per_prime(self, tmp_path):
        """Chi apre il giornale cerca l'ultima bottiglia, non la prima."""
        g = Giornale(tmp_path)
        for nome in ("primo", "secondo", "terzo"):
            g.annota(voce(nome))
        assert [v["nome"] for v in g.ultime()] == ["terzo", "secondo", "primo"]

    def test_se_ne_chiedono_poche_se_ne_danno_poche(self, tmp_path):
        g = Giornale(tmp_path)
        for k in range(10):
            g.annota(voce(str(k)))
        assert len(g.ultime(3)) == 3

    def test_un_giornale_che_non_c_e_non_e_un_errore(self, tmp_path):
        assert Giornale(tmp_path / "mai-nata").ultime() == []

    def test_una_riga_tronca_non_porta_via_il_resto(self, tmp_path):
        """Uno spegnimento a metà scrittura lascia una riga a metà. È l'ultima,
        si butta, e tutto quello che c'era prima resta buono."""
        g = Giornale(tmp_path)
        g.annota(voce("buona"))
        with open(g.percorso, "a", encoding="utf-8") as f:
            f.write('{"nome": "tron')
        fuori = g.ultime()
        assert [v["nome"] for v in fuori] == ["buona"]

    def test_una_voce_non_serializzabile_non_solleva(self, tmp_path):
        """Un oggetto finito per sbaglio dentro la voce costa una riga persa,
        non una scansione persa."""
        g = Giornale(tmp_path)
        assert g.annota({"roba": object()}) is None

    def test_una_cartella_che_non_si_puo_scrivere_non_solleva(self, tmp_path):
        impossibile = tmp_path / "file-non-cartella"
        impossibile.write_text("sono un file")
        g = Giornale(impossibile / "dentro")
        assert g.annota(voce()) is None


class TestLeImmagini:
    """Senza l'immagine si sa che ha sbagliato, non perché."""

    @staticmethod
    def immagine():
        np = pytest.importorskip("numpy")
        pytest.importorskip("cv2")
        return np.full((40, 60, 3), 120, dtype=np.uint8)

    def test_la_voce_porta_il_nome_della_sua_immagine(self, tmp_path):
        g = Giornale(tmp_path)
        nome = g.annota(voce(), self.immagine())
        assert nome and nome.endswith(".jpg")
        assert (tmp_path / nome).is_file()
        assert g.ultime()[0]["immagine"] == nome

    def test_le_piu_vecchie_se_ne_vanno(self, tmp_path):
        """La flash di una board non è un archivio: c'è un tetto, ed è quello
        che tiene il giornale utile senza farlo diventare un problema."""
        g = Giornale(tmp_path, immagini_tenute=3)
        for _ in range(6):
            g.annota(voce(), self.immagine())
        assert len(list(tmp_path.glob("*.jpg"))) == 3
        # e le righe restano tutte: il testo costa niente
        assert len(g.ultime(50)) == 6

    def test_un_nome_che_esce_dalla_cartella_non_si_apre(self, tmp_path):
        """Il nome arriva da fuori, e un nome che arriva da fuori non si
        concatena a un percorso senza guardarlo."""
        g = Giornale(tmp_path)
        for cattivo in ("../../etc/passwd", "../fuori.jpg", "sotto/cosa.jpg",
                        "chiave.pem", "..%2Fcosa.jpg"):
            assert g.immagine(cattivo) is None

    def test_un_nome_giusto_si_apre(self, tmp_path):
        g = Giornale(tmp_path)
        nome = g.annota(voce(), self.immagine())
        assert g.immagine(nome) == tmp_path / nome

    def test_un_nome_giusto_di_un_file_che_non_c_e(self, tmp_path):
        assert Giornale(tmp_path).immagine("20260101-000000-000.jpg") is None


class TestLaRotazione:
    def test_oltre_la_taglia_il_giornale_ruota(self, tmp_path, monkeypatch):
        """Senza, il file cresce per mesi e un giorno riempie il disco."""
        from amelie import giornale as modulo

        monkeypatch.setattr(modulo, "TAGLIA_MASSIMA", 200)
        g = Giornale(tmp_path)
        for k in range(20):
            g.annota(voce("x" * 40))
        assert (tmp_path / "giornale.1.jsonl").is_file()
        # il giornale nuovo riparte, e quello vecchio e' ancora li' da leggere
        assert len(g.ultime(50)) < 20
