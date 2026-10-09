"""Il ponte verso il microcontrollore, contro un router finto.

Il router scrive due righe nel giornale di sistema per ogni connessione, e il
sensore si interroga a ogni battito: il ponte tiene aperta UNA connessione, e se
il router la chiude - si e' riavviato - la riapre da solo.
"""
from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading

import pytest

msgpack = pytest.importorskip("msgpack")

from amelie.bridge import ErroreMCU, Ponte, PonteNonDisponibile  # noqa: E402


class RouterFinto:
    """Un router MessagePack-RPC su un socket Unix, in un thread suo."""

    def __init__(self, percorso: str) -> None:
        self.percorso = percorso
        self.connessioni = 0
        self.risposte = {"distanza": 87, "versione": 2}
        self.muto = False          # riceve e non risponde
        self.chiudi_dopo = 0       # chiude la connessione dopo tante richieste
        self.rumore = False        # manda prima una risposta di un'altra chiamata
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(percorso)
        self._server.listen(8)
        threading.Thread(target=self._accetta, daemon=True).start()

    def _accetta(self) -> None:
        while True:
            try:
                c, _ = self._server.accept()
            except OSError:
                return
            self.connessioni += 1
            threading.Thread(target=self._servi, args=(c,), daemon=True).start()

    def _servi(self, c: socket.socket) -> None:
        u = msgpack.Unpacker(raw=False)
        richieste = 0
        with c:
            while True:
                try:
                    dati = c.recv(4096)
                except OSError:
                    return
                if not dati:
                    return
                u.feed(dati)
                for _tipo, msgid, metodo, _parametri in u:
                    richieste += 1
                    if self.muto:
                        continue
                    if self.rumore:
                        c.sendall(msgpack.packb([1, msgid + 1000, None, "vecchia"]))
                    if metodo in self.risposte:
                        r = [1, msgid, None, self.risposte[metodo]]
                    else:
                        r = [1, msgid, [2, f"method {metodo} not available"], None]
                    c.sendall(msgpack.packb(r, use_bin_type=True))
                    if self.chiudi_dopo and richieste >= self.chiudi_dopo:
                        return

    def ferma(self) -> None:
        self._server.close()


@pytest.fixture
def router():
    # Corto di proposito: un socket Unix non accetta percorsi oltre i 107 byte,
    # e la cartella temporanea di pytest puo' superarli.
    cartella = tempfile.mkdtemp(prefix="ponte-", dir="/tmp")
    r = RouterFinto(os.path.join(cartella, "r.sock"))
    yield r
    r.ferma()
    shutil.rmtree(cartella, ignore_errors=True)


class TestUnaConnessioneSola:
    def test_tante_chiamate_una_connessione(self, router):
        p = Ponte(router.percorso, timeout=2.0)
        for _ in range(20):
            assert p.chiama("distanza") == 87
        assert router.connessioni == 1

    def test_un_errore_dello_sketch_non_chiude_la_connessione(self, router):
        p = Ponte(router.percorso, timeout=2.0)
        with pytest.raises(ErroreMCU):
            p.chiama("set_anello", 1, 2, 3, 4)
        assert p.chiama("distanza") == 87
        assert router.connessioni == 1

    def test_una_risposta_di_un_altra_chiamata_si_scarta(self, router):
        router.rumore = True
        p = Ponte(router.percorso, timeout=2.0)
        assert p.chiama("versione") == 2
        assert p.chiama("distanza") == 87

    def test_due_fili_insieme(self, router):
        """Le risposte arrivano sullo stesso canale: ognuno deve avere la sua."""
        p = Ponte(router.percorso, timeout=2.0)
        sbagliate = []

        def chiedi(metodo, atteso):
            for _ in range(50):
                if p.chiama(metodo) != atteso:
                    sbagliate.append(metodo)

        fili = [threading.Thread(target=chiedi, args=("distanza", 87)),
                threading.Thread(target=chiedi, args=("versione", 2))]
        for f in fili:
            f.start()
        for f in fili:
            f.join(10)
        assert not sbagliate
        assert router.connessioni == 1


class TestQuandoIlRouterCade:
    def test_se_il_router_chiude_si_riconnette(self, router):
        """Il router riavviato chiude la connessione: la chiamata dopo la
        riapre da sola, e nessuno se ne accorge."""
        router.chiudi_dopo = 1
        p = Ponte(router.percorso, timeout=2.0)
        for _ in range(3):
            assert p.chiama("distanza") == 87
        assert router.connessioni >= 2

    def test_senza_router_si_dice_subito(self):
        p = Ponte("/tmp/non-esiste-questo-router.sock", timeout=1.0)
        with pytest.raises(PonteNonDisponibile):
            p.chiama("distanza")

    def test_nessuna_risposta_e_poi_si_riparte_puliti(self, router):
        router.muto = True
        p = Ponte(router.percorso, timeout=0.3)
        with pytest.raises(PonteNonDisponibile):
            p.chiama("distanza")
        router.muto = False
        assert p.chiama("distanza") == 87
        assert router.connessioni == 2

    def test_chiudere_e_richiamare(self, router):
        p = Ponte(router.percorso, timeout=2.0)
        assert p.chiama("distanza") == 87
        p.chiudi()
        assert p.chiama("distanza") == 87
        assert router.connessioni == 2


class TestLoSketchCe:
    def test_senza_lo_sketch_il_microcontrollore_non_e_disponibile(self, router):
        """Il router risponde anche senza lo sketch di Amelie: ogni metodo
        torna «not available», e il ponte deve dirlo."""
        router.risposte = {}
        assert not Ponte(router.percorso, timeout=2.0).disponibile

    def test_con_lo_sketch_lo_e(self, router):
        assert Ponte(router.percorso, timeout=2.0).disponibile
