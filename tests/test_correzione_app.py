"""La correzione a mano dentro al dispositivo: riconoscere, raccontare, scrivere.

`test_correzioni.py` prova il modulo da solo. Qui si prova quello che vede chi
sta in sala: la bottiglia corretta torna sul piatto e si racconta con le sue
parole, in qualunque modo di racconto; l'editor aperto ferma il dispositivo;
salvare racconta subito la descrizione nuova.
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from amelie.correzioni import Correzioni  # noqa: E402
from amelie.matcher import Fatti, Livello  # noqa: E402
from amelie.ocr import Riga  # noqa: E402
from amelie.state import Evento, Stato  # noqa: E402


def _etichetta(testo: str, seme: int):
    rng = np.random.default_rng(seme)
    im = np.full((1400, 600, 3), 235, np.uint8)
    for _ in range(260):
        x, y = int(rng.integers(40, 560)), int(rng.integers(300, 1100))
        r = int(rng.integers(4, 22))
        c = tuple(int(v) for v in rng.integers(0, 200, 3))
        cv2.circle(im, (x, y), r, c, -1)
        cv2.rectangle(im, (x, y), (x + r, y + 2 * r), c, 2)
    righe = []
    for i, riga in enumerate(testo.split("|")):
        y = 520 + i * 110
        cv2.putText(im, riga, (70, y), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 5)
        righe.append(Riga(testo=riga, confidenza=.9,
                          riquadro=((60, y - 60), (560, y - 60), (560, y + 20), (60, y + 20))))
    return im, righe


@pytest.fixture
def amelie(tmp_path):
    from amelie.app import Amelie, Configurazione
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    a.correzioni = Correzioni(tmp_path / "correzioni")
    a._scansione = {}
    yield a
    a.matcher.chiudi()
    a.narratore.chiudi()


def _appoggia(amelie, testo="PALAMA|NEGROAMARO|ALBAROSSA", seme=7):
    """Fa credere al dispositivo di aver appena letto questa etichetta."""
    im, righe = _etichetta(testo, seme)
    amelie._ultimo_scatto = im
    amelie._righe_lette = righe
    amelie._righe = [r.testo for r in righe]
    amelie._scansione = {}
    amelie.macchina.stato = Stato.RICONOSCIMENTO
    return im, righe


def _correggi(amelie, lingua="it", titolo="Albarossa Negroamaro",
              descrizione="Un rosato del Salento, fresco e sapido."):
    im, righe = _etichetta("PALAMA|NEGROAMARO|ALBAROSSA", 7)
    return amelie.correzioni.salva(righe=righe, immagine=im, titolo=titolo,
                                   descrizione=descrizione, lingua=lingua)


class TestSiRiconosceInOgniModo:
    """«Indipendentemente dalla modalità di output scelta»: la correzione vale
    prima dell'archivio, del modello e della carta."""

    @pytest.mark.parametrize("modo", ["archivio", "generativa"])
    def test_prima_dell_archivio_e_del_modello(self, amelie, modo):
        c = _correggi(amelie)
        amelie.modo = modo
        _appoggia(amelie)
        # Il giornale si scrive e si svuota appena parte il racconto: si guarda
        # la voce che ci finisce dentro.
        annotate = []
        amelie._annota = lambda esito: annotate.append(dict(amelie._scansione, esito=esito))
        amelie._riconosci()
        assert amelie._correzione is not None and amelie._correzione.id == c.id
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._scansione.get("livello") == "correzione" or any(
            a.get("livello") == "correzione" for a in annotate)

    def test_prima_della_carta(self, amelie):
        class CartaCheNonHaNiente:
            def cerca(self, righe):
                raise AssertionError("la carta non doveva nemmeno essere guardata")
        c = _correggi(amelie)
        amelie.carta = CartaCheNonHaNiente()
        amelie.modo = "carta"
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._correzione.id == c.id

    def test_il_racconto_e_quello_scritto(self, amelie):
        _correggi(amelie)
        _appoggia(amelie)
        amelie._riconosci()
        r = amelie._racconta_dalla_correzione()
        assert r.origine == "correzione"
        assert "Albarossa Negroamaro" in r.testo
        assert r.testo.endswith("Un rosato del Salento, fresco e sapido.")

    def test_lo_schermo_mostra_il_titolo_scritto(self, amelie):
        _correggi(amelie)
        _appoggia(amelie)
        messaggi = []
        amelie._pubblica = messaggi.append
        amelie._riconosci()
        stato = [m for m in messaggi if m.get("tipo") == "stato"][-1]
        assert stato["titolo"] == "Albarossa Negroamaro"
        assert stato["correzione"] == "modifica"

    def test_una_bottiglia_diversa_resta_all_archivio(self, amelie):
        _correggi(amelie)
        _appoggia(amelie, "CORTE DEL BORGO|LAMBRUSCO|GRASPAROSSA", 99)
        amelie._riconosci()
        assert amelie._correzione is None


class TestLeLingue:
    def test_scritta_in_italiano_non_si_legge_con_la_voce_inglese(self, amelie):
        _correggi(amelie, lingua="it")
        amelie.lingua = "en"
        _appoggia(amelie)
        amelie._riconosci()
        # riconosciuta si', ma racconta come se non ci fosse...
        assert amelie._correzione is not None
        assert not amelie._correzione_parla_ora()
        # ...e offre di aggiungere l'inglese
        assert amelie._azione_correzione() == "modifica"


class TestIlPulsante:
    def test_correggi_sulla_bottiglia_fuori_archivio(self, amelie):
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato",
                              qualificatori=["spumante"])
        assert amelie._azione_correzione() == "correggi"

    def test_niente_su_una_bottiglia_dell_archivio(self, amelie):
        amelie._fatti = Fatti(livello=Livello.VINO, nome="Barolo Cannubi")
        assert amelie._azione_correzione() is None

    def test_niente_quando_non_si_e_detto_niente(self, amelie):
        """Senza colore ne' tipo il racconto chiede di girare l'etichetta: li'
        non c'e' nessuna descrizione da correggere."""
        amelie._fatti = Fatti(livello=Livello.GENERICO)
        assert amelie._azione_correzione() is None


class TestIlTempoPerCorreggere:
    """Il pulsante serve DOPO l'ultima frase, che e' quella che dice «non e' nel
    mio archivio»: i due secondi di CONCLUSO non bastavano ad arrivarci."""

    def _finisci(self, amelie):
        import time
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        return amelie._scadenza - time.monotonic()

    def test_fuori_archivio_resta_a_schermo(self, amelie):
        from amelie import app as modulo
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        assert self._finisci(amelie) > modulo.CONCLUSO_CON_CORREZIONE_S - 1

    def test_un_vino_dell_archivio_se_ne_va_come_prima(self, amelie):
        amelie._fatti = Fatti(livello=Livello.VINO, nome="Barolo Cannubi")
        assert self._finisci(amelie) < 3


class TestLEditor:
    def _in_racconto(self, amelie):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO

    def test_aprire_ferma_il_dispositivo(self, amelie):
        self._in_racconto(amelie)
        esito = amelie.apri_correzione()
        assert esito["ok"] and esito["id"] is None and esito["titolo"] == ""
        assert amelie._correggendo is not None
        assert not amelie._va_sorvegliata()

    def test_mentre_si_scrive_il_piatto_non_si_guarda(self, amelie):
        import asyncio
        self._in_racconto(amelie)
        amelie.apri_correzione()

        async def chi_c_e():
            raise AssertionError("il piatto non doveva essere guardato")
        amelie._chi_c_e = chi_c_e
        asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_non_si_apre_fuori_dal_racconto(self, amelie):
        amelie.macchina.stato = Stato.ATTESA
        assert amelie.apri_correzione() == {"ok": False}

    def test_salvare_racconta_subito(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        esito = amelie.salva_correzione("Albarossa", "Un rosato del Salento.")
        assert esito["ok"]
        assert amelie._correggendo is None
        assert amelie._correzione is not None
        assert amelie._correzione_parla_ora()
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_la_foto_e_quella_di_quando_si_e_aperto(self, amelie):
        """Se mentre si scrive qualcuno cambia bottiglia, la correzione resta
        attaccata a quella che si stava correggendo."""
        self._in_racconto(amelie)
        prima = amelie._ultimo_scatto.copy()
        amelie.apri_correzione()
        amelie._ultimo_scatto = np.zeros_like(prima)       # un'altra bottiglia
        amelie._righe_lette = []
        amelie.salva_correzione("Albarossa", "Un rosato.")
        c = amelie._correzione
        foto = cv2.imread(str(amelie.correzioni.cartella / c.id / c.viste[0].immagine))
        assert foto is not None and foto.mean() > 50          # non e' quella nera
        assert c.viste[0].parole                              # e ha le sue parole

    def test_titolo_o_descrizione_vuoti_non_si_salvano(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        assert amelie.salva_correzione("  ", "x") == {"ok": False, "campo": "titolo"}
        assert amelie.salva_correzione("x", "") == {"ok": False, "campo": "descrizione"}
        assert amelie._correggendo is not None               # l'editor resta aperto

    def test_chiudere_senza_salvare(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        assert amelie.chiudi_correzione() == {"ok": True}
        assert amelie._correggendo is None
        assert amelie.macchina.stato is Stato.CONCLUSO
        assert amelie.correzioni.tutte() == []

    def test_modificare_non_crea_un_doppione(self, amelie):
        c = _correggi(amelie)
        _appoggia(amelie)
        amelie._riconosci()
        esito = amelie.apri_correzione()
        assert esito["id"] == c.id and esito["descrizione"]
        amelie.salva_correzione("Albarossa Negroamaro", "Testo nuovo.")
        assert len(amelie.correzioni.tutte()) == 1
        assert amelie.correzioni.trova(c.id).testo_in("it")["descrizione"] == "Testo nuovo."
        assert len(amelie.correzioni.trova(c.id).viste) == 2

    def test_le_vicine_si_propongono(self, amelie):
        """Una bottiglia corretta che stavolta non si e' riconosciuta: nell'editor
        la si ritrova, invece di crearne un'altra."""
        c = _correggi(amelie)
        _appoggia(amelie, "PALAMA|APADOSEN", 555)
        amelie._riconosci()
        assert amelie._correzione is None
        amelie.macchina.stato = Stato.RACCONTO
        esito = amelie.apri_correzione()
        assert [v["id"] for v in esito["vicine"]] == [c.id]

    def test_l_editor_dimenticato_si_chiude_da_solo(self, amelie, monkeypatch):
        import asyncio
        from amelie import app as modulo
        self._in_racconto(amelie)
        amelie.apri_correzione()
        amelie._correggendo["quando"] -= modulo.CORREZIONE_TETTO_S + 1
        pubblicati = []
        amelie._pubblica = pubblicati.append
        asyncio.run(amelie._un_battito())
        assert amelie._correggendo is None
        assert {"tipo": "correzione", "aperta": False} in pubblicati


class TestLeRotte:
    """Le stesse cose, passando dalle rotte HTTP come fa la pagina.

    Chiamare i metodi non bastava: la rotta del salvataggio prendeva il corpo
    come `Request`, FastAPI - con le annotazioni rimandate - non lo
    riconosceva e rispondeva 422 a ogni richiesta. I test dei metodi
    passavano tutti, e sul dispositivo «Salva» non salvava.
    """

    @pytest.fixture
    def client(self, amelie):
        from fastapi.testclient import TestClient

        from amelie.app import crea_app
        return TestClient(crea_app(amelie))

    def test_aprire_salvare_e_ritrovare(self, amelie, client):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO
        aperto = client.post("/correzione/apri").json()
        assert aperto["ok"] and aperto["id"] is None
        foto = client.get("/correzione/foto/adesso")
        assert foto.status_code == 200 and foto.headers["content-type"] == "image/jpeg"
        esito = client.post("/correzione/salva",
                            json={"titolo": "Albarossa", "descrizione": "Un rosato.",
                                  "id": None}).json()
        assert esito["ok"], esito
        assert client.get(f"/correzione/foto/{esito['id']}").status_code == 200
        assert len(amelie.correzioni.tutte()) == 1

    def test_un_campo_vuoto_torna_indietro_col_suo_nome(self, amelie, client):
        _appoggia(amelie)
        amelie.macchina.stato = Stato.RACCONTO
        client.post("/correzione/apri")
        esito = client.post("/correzione/salva", json={"titolo": "", "descrizione": "x"})
        assert esito.json() == {"ok": False, "campo": "titolo"}

    def test_chiudere(self, amelie, client):
        _appoggia(amelie)
        amelie.macchina.stato = Stato.RACCONTO
        client.post("/correzione/apri")
        assert client.post("/correzione/chiudi").json() == {"ok": True}
        assert client.get("/correzione/foto/adesso").status_code == 404


class TestLeScritte:
    def test_tutte_le_scritte_dell_editor_in_tutte_le_lingue(self, amelie):
        chiavi = ("correggi_descrizione", "modifica_descrizione", "campo_titolo",
                  "campo_descrizione", "salva", "titolo_vuoto", "descrizione_vuota",
                  "correzione_spiega", "correzione_salvata", "correzione_vicine",
                  "tasto_spazio")
        for lingua in amelie.lex.lingue:
            for k in chiavi:
                assert amelie.lex.frase("schermo", k, lingua=lingua).strip(), (lingua, k)
