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
def amelie(tmp_path, monkeypatch):
    from amelie import app as modulo
    from amelie.app import Amelie, Configurazione
    monkeypatch.setattr(modulo, "PERCORSO_CORREZIONI_ATTIVE", tmp_path / "correzioni_attive")
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    a.correzioni = Correzioni(tmp_path / "correzioni")
    a._scansione = {}
    # Quasi tutti i test sono di chi corregge: l'interruttore acceso. Quelli
    # a interruttore spento lo spengono da se'.
    a.correzioni_attive = True
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
    """«Aggiungi correzioni» acceso: il pulsante su OGNI racconto. Spento: mai."""

    def test_correggi_sulla_bottiglia_fuori_archivio(self, amelie):
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato",
                              qualificatori=["spumante"])
        assert amelie._azione_correzione() == "correggi"

    def test_correggi_anche_su_una_bottiglia_riconosciuta(self, amelie):
        amelie._fatti = Fatti(livello=Livello.VINO, nome="Barolo Cannubi")
        assert amelie._azione_correzione() == "correggi"

    def test_modifica_su_una_bottiglia_gia_corretta(self, amelie):
        _correggi(amelie)
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._azione_correzione() == "modifica"

    def test_niente_senza_un_racconto(self, amelie):
        amelie._fatti = Fatti()
        assert amelie._azione_correzione() is None

    def test_a_interruttore_spento_nessun_pulsante_mai(self, amelie):
        amelie.correzioni_attive = False
        for f in (Fatti(livello=Livello.GENERICO, colore="Rosato"),
                  Fatti(livello=Livello.VINO, nome="Barolo Cannubi")):
            amelie._fatti = f
            assert amelie._azione_correzione() is None
        _correggi(amelie)
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._correzione is not None, "le correzioni salvate valgono sempre"
        assert amelie._azione_correzione() is None

    def test_a_interruttore_spento_l_editor_non_si_apre(self, amelie):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.VINO, nome="Barolo Cannubi")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.correzioni_attive = False
        assert amelie.apri_correzione() == {"ok": False}


class TestLInterruttore:
    def test_si_ricorda_dopo_un_riavvio(self, amelie):
        from amelie import app as modulo
        amelie.imposta_correzioni(True)
        assert modulo.Amelie._correzioni_attive_salvate() is True
        amelie.imposta_correzioni(False)
        assert modulo.Amelie._correzioni_attive_salvate() is False

    def test_spento_se_non_c_e_niente_di_salvato(self, amelie):
        from amelie import app as modulo
        assert modulo.Amelie._correzioni_attive_salvate() is False

    def test_il_pulsante_cambia_sul_racconto_a_schermo(self, amelie):
        amelie._fatti = Fatti(livello=Livello.VINO, nome="Barolo Cannubi")
        amelie.macchina.stato = Stato.RACCONTO
        detti = []
        amelie._pubblica = detti.append
        amelie.imposta_correzioni(False)
        assert {"tipo": "correzione", "azione": None} in detti
        amelie.imposta_correzioni(True)
        assert {"tipo": "correzione", "azione": "correggi"} in detti
        assert [m["correzioni"] for m in detti if m.get("tipo") == "impostazioni"] == [False, True]

    def test_spegnendo_con_l_editor_aperto_l_editor_si_chiude(self, amelie):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.apri_correzione()
        detti = []
        amelie._pubblica = detti.append
        amelie.imposta_correzioni(False)
        assert amelie._correggendo is None
        assert {"tipo": "correzione", "aperta": False} in detti


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

    def test_a_interruttore_spento_se_ne_va_come_prima(self, amelie):
        amelie.correzioni_attive = False
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        assert self._finisci(amelie) < 3


class TestLEditor:
    def _in_racconto(self, amelie):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO

    def test_aprire_ferma_il_dispositivo(self, amelie):
        self._in_racconto(amelie)
        esito = amelie.apri_correzione()
        # Fuori archivio non c'e' nessun vino a cui la bottiglia sia gia'
        # collegata, e il titolo si scrive da capo.
        assert esito["ok"] and esito["id"] is None
        assert esito["titolo"] == "" and esito["riferimento"] is None
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
        # Prima la domanda sull'altra lingua; a «no» si racconta.
        assert esito["altra_lingua"] == "en"
        assert amelie.altra_lingua(False) == {"ok": True}
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
        # Il client di prova di FastAPI vuole httpx, che sulla board non c'e':
        # li' questi test si saltano, sul PC girano.
        pytest.importorskip("httpx")
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

    def test_la_domanda_sull_altra_lingua(self, amelie, client):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO
        client.post("/correzione/apri")
        esito = client.post("/correzione/salva",
                            json={"titolo": "Albarossa", "descrizione": "Un rosato."}).json()
        assert esito["altra_lingua"] == "en"
        aperta = client.post("/correzione/altra_lingua", json={"accetta": True}).json()
        assert aperta["ok"] and aperta["lingua"] == "en"
        seconda = client.post("/correzione/salva",
                              json={"titolo": "Albarossa", "descrizione": "A rosé."}).json()
        assert seconda["ok"] and "altra_lingua" not in seconda
        assert amelie.correzioni.trova(esito["id"]).testo_in("en")["descrizione"] == "A rosé."

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


class TestIlCollegamento:
    """Scegliere un vino dalla ricerca collega l'etichetta a quel vino: la volta
    dopo si riconosce come lui, e senza descrizione si racconta la sua scheda."""

    def _in_racconto(self, amelie, testo="PALAMA|NEGROAMARO|ALBAROSSA", seme=7):
        # Qui conta cosa si riconosce, non il racconto: niente thread di lavoro,
        # che il racconto del salvataggio terrebbe occupato.
        amelie._avvia = lambda _f: None
        _appoggia(amelie, testo, seme)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO

    def test_collegata_all_archivio_senza_descrizione(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        esito = amelie.salva_correzione(
            "Cannubi Barolo", "", riferimento={"tipo": "archivio", "ambito": "vino", "id": 510})
        assert esito["ok"], esito
        c = amelie.correzioni.trova(esito["id"])
        assert c.riferimento == {"tipo": "archivio", "ambito": "vino", "id": 510,
                                 "titolo": "Cannubi Barolo — Marchesi di Barolo"}
        # La volta dopo: riconosciuta, e raccontata come quel vino.
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._correzione.id == c.id
        assert not amelie._correzione_parla_ora()
        assert amelie._fatti.nome == "Cannubi Barolo"
        assert amelie._fatti.cantina == "Marchesi di Barolo"
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_salvando_si_racconta_subito_il_vino_collegato(self, amelie):
        """Il racconto che riparte dopo «Salva» e' gia' quello del vino scelto."""
        self._in_racconto(amelie)
        amelie._fatti = amelie.matcher.fatti_di("tipologia", 470)     # un Barolo
        amelie.apri_correzione()
        amelie.salva_correzione("Cannubi Barolo", "",
                                riferimento={"tipo": "archivio", "ambito": "vino", "id": 510})
        assert amelie._fatti.nome == "Cannubi Barolo"
        assert amelie._fatti.cantina == "Marchesi di Barolo"

    def test_con_la_descrizione_parla_la_descrizione(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        amelie.salva_correzione("Cannubi Barolo", "Scritta da chi lo conosce.",
                                riferimento={"tipo": "archivio", "ambito": "vino", "id": 510})
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._correzione_parla_ora()
        assert amelie._racconta_dalla_correzione().testo.endswith("Scritta da chi lo conosce.")
        # e in inglese, dove la descrizione non c'e', parla il vino collegato
        amelie.lingua = "en"
        assert not amelie._correzione_parla_ora()
        assert amelie._fatti.nome == "Cannubi Barolo"

    def test_senza_collegamento_la_descrizione_serve(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        assert amelie.salva_correzione("Un vino", "") == {"ok": False, "campo": "descrizione"}

    def test_un_collegamento_inventato_non_si_salva(self, amelie):
        self._in_racconto(amelie)
        amelie.apri_correzione()
        esito = amelie.salva_correzione(
            "Un vino", "", riferimento={"tipo": "archivio", "ambito": "vino", "id": 99999999})
        assert esito == {"ok": False, "campo": "descrizione"}
        esito = amelie.salva_correzione(
            "Un vino", "", riferimento={"tipo": "archivio", "ambito": "vitigno", "id": 1})
        assert esito == {"ok": False, "campo": "descrizione"}

    def test_la_bottiglia_riconosciuta_si_propone_collegata_a_se_stessa(self, amelie):
        _appoggia(amelie)
        amelie._fatti = amelie.matcher.fatti_di("vino", 510)
        amelie.macchina.stato = Stato.RACCONTO
        esito = amelie.apri_correzione()
        assert esito["riferimento"]["id"] == 510
        assert esito["titolo"] == "Cannubi Barolo — Marchesi di Barolo"

    def test_collegata_alla_carta(self, amelie, tmp_path):
        from amelie.carta import Carta
        csv = tmp_path / "carta.csv"
        csv.write_text('titolo,descrizione\n"Albarossa Palamà","Il rosato di casa, '
                       'fresco e sapido."\n', encoding="utf-8")
        amelie.carta = Carta(csv)
        self._in_racconto(amelie)
        amelie.apri_correzione()
        esito = amelie.salva_correzione("Albarossa Palamà", "",
                                        riferimento={"tipo": "carta", "titolo": "Albarossa Palamà"})
        assert esito["ok"], esito
        amelie.modo = "archivio"          # vale in qualunque modo
        _appoggia(amelie)
        amelie._riconosci()
        assert amelie._la_carta_parla_ora()
        assert amelie._racconta_dalla_carta().testo.endswith("fresco e sapido.")


class TestLaRicerca:
    def test_prima_le_corrette_poi_la_carta_poi_l_archivio(self, amelie, tmp_path):
        from amelie.carta import Carta
        csv = tmp_path / "carta.csv"
        csv.write_text('titolo,descrizione\n"Barolo DOCG","Nebbiolo in purezza."\n',
                       encoding="utf-8")
        amelie.carta = Carta(csv)
        _correggi(amelie, titolo="Barolo di casa", descrizione="Il nostro.")
        tipi = [p["tipo"] for p in amelie.cerca_bottiglie("barol")]
        assert tipi[0] == "correzione" and tipi[1] == "carta" and "archivio" in tipi
        primo_archivio = next(p for p in amelie.cerca_bottiglie("barolo")
                              if p["tipo"] == "archivio")
        assert primo_archivio["ambito"] == "denominazione", \
            "«Barolo» prima dei duecento Barolo di un produttore"
        assert all(p["sotto"] for p in amelie.cerca_bottiglie("barolo"))

    def test_ce_n_e_piu_di_una_pagina(self, amelie):
        """La pagina ne mostra cinque per volta: «Nessuna di queste» deve avere
        altre proposte da far scorrere, non le stesse cinque."""
        proposte = amelie.cerca_bottiglie("barolo")
        assert 10 <= len(proposte) <= 20
        titoli = [p["titolo"] for p in proposte]
        assert len(titoli) == len(set(titoli))

    def test_le_parole_scritte_restringono(self, amelie):
        proposte = amelie.cerca_bottiglie("cannubi marchesi")
        assert any(p.get("id") == 510 for p in proposte)

    def test_niente_a_interruttore_spento_o_campo_vuoto(self, amelie):
        assert amelie.cerca_bottiglie("") == []
        amelie.correzioni_attive = False
        assert amelie.cerca_bottiglie("barolo") == []


def test_si_puo_togliere_un_collegamento(amelie):
    amelie._avvia = lambda _f: None
    _appoggia(amelie)
    amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
    amelie.macchina.stato = Stato.RACCONTO
    amelie.apri_correzione()
    esito = amelie.salva_correzione("Cannubi Barolo", "",
                                    riferimento={"tipo": "archivio", "ambito": "vino", "id": 510})
    amelie.apri_correzione()
    # senza descrizione, togliere il collegamento non si puo': non resterebbe niente
    assert amelie.salva_correzione("Cannubi", "", scollega=True) == {
        "ok": False, "campo": "descrizione"}
    assert amelie.salva_correzione("Cannubi", "Detto a mano.", scollega=True)["ok"]
    assert amelie.correzioni.trova(esito["id"]).riferimento is None



class TestLAltraLingua:
    """Salvata una descrizione, si chiede se la si vuole anche nell'altra
    lingua: in italiano si chiede l'inglese, in inglese l'italiano."""

    def _salvata(self, amelie, lingua="it"):
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.lingua = lingua
        amelie.apri_correzione()
        return amelie.salva_correzione("Albarossa", "Un rosato del Salento.")

    def test_la_domanda_nella_lingua_di_chi_scrive(self, amelie):
        esito = self._salvata(amelie)
        assert esito["altra_lingua"] == "en"
        assert esito["domanda"] == "Vuole scrivere la descrizione anche in inglese?"
        # Mentre si risponde, il dispositivo resta fermo: il racconto non riparte.
        assert amelie._correggendo is not None
        assert not amelie._va_sorvegliata()

    def test_e_viceversa(self, amelie):
        esito = self._salvata(amelie, lingua="en")
        assert esito["altra_lingua"] == "it"
        assert esito["domanda"] == "Would you like to write the description in Italian too?"

    def test_si_scrive_nella_stessa_correzione_senza_un_altra_foto(self, amelie):
        esito = self._salvata(amelie)
        aperta = amelie.altra_lingua(True)
        assert aperta["ok"] and aperta["lingua"] == "en" and aperta["id"] == esito["id"]
        assert aperta["titolo"] == "Albarossa"          # il nome non si traduce
        assert aperta["titolo_editor"] == "Descrizione in inglese"
        seconda = amelie.salva_correzione("Albarossa", "A rosé from Salento.")
        assert seconda == {"ok": True, "id": esito["id"]}  # nessuna altra domanda
        c = amelie.correzioni.trova(esito["id"])
        assert c.testo_in("it")["descrizione"] == "Un rosato del Salento."
        assert c.testo_in("en")["descrizione"] == "A rosé from Salento."
        assert len(c.viste) == 1
        assert amelie._correggendo is None
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_chiudere_la_domanda_racconta_quello_che_si_e_salvato(self, amelie):
        self._salvata(amelie)
        assert amelie.chiudi_correzione() == {"ok": True}
        assert amelie._correggendo is None
        assert amelie._correzione_parla_ora()
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_senza_descrizione_non_si_chiede_niente(self, amelie):
        """Collegata a un vino dell'archivio, senza descrizione: in ogni lingua
        si racconta la sua scheda, e non c'e' niente da tradurre."""
        _appoggia(amelie)
        amelie._fatti = Fatti(livello=Livello.GENERICO, colore="Rosato")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.apri_correzione()
        rif = amelie.matcher.suggerisci("barolo", 1)[0]
        esito = amelie.salva_correzione(
            "Barolo", "", riferimento={"tipo": "archivio", "ambito": rif[0], "id": rif[1]})
        assert esito["ok"] and "altra_lingua" not in esito
        assert amelie._correggendo is None


class TestAiutareIlRiconoscimento:
    """Una bottiglia che non si riconosce si puo' insegnare al dispositivo: il
    pulsante compare fra un tentativo e l'altro e a tentativi finiti, solo con
    le correzioni accese e solo se si e' letta qualche parola."""

    def _non_riconosciuta(self, amelie, stato=Stato.RIPOSIZIONA, testo="PALAMA|NEGROAMARO"):
        _appoggia(amelie, testo)
        amelie._fatti = Fatti()
        amelie._voce = None
        amelie._correzione = None
        amelie.macchina.stato = stato

    def test_fra_un_tentativo_e_l_altro(self, amelie):
        self._non_riconosciuta(amelie)
        detti = []
        amelie._pubblica = detti.append
        amelie._mostra(Stato.RIPOSIZIONA)
        assert detti[-1]["aiuta"] is True
        esito = amelie.apri_correzione()
        assert esito["ok"] and esito["aiuto"] is True
        assert esito["titolo"] == "" and esito["riferimento"] is None

    def test_salvata_si_racconta(self, amelie):
        self._non_riconosciuta(amelie)
        amelie.apri_correzione()
        amelie.salva_correzione("Albarossa", "Un rosato del Salento.")
        amelie.altra_lingua(False)
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._correzione_parla_ora()
        # e la prossima volta la bottiglia si riconosce
        _appoggia(amelie, "PALAMA|NEGROAMARO")
        amelie._riconosci()
        assert amelie._correzione is not None

    def test_a_tentativi_finiti(self, amelie):
        self._non_riconosciuta(amelie, Stato.CONCLUSO)
        detti = []
        amelie._pubblica = detti.append
        amelie._mostra(Stato.CONCLUSO)
        assert detti[-1]["vista"] == "avviso" and detti[-1]["aiuta"] is True
        assert amelie.apri_correzione()["ok"]

    def test_senza_parole_lette_non_si_offre(self, amelie):
        """Una correzione si ritrova dalle parole: senza, non tornerebbe mai."""
        self._non_riconosciuta(amelie, testo="2024|75 cl")
        assert amelie._aiuto_possibile() is False
        assert amelie.apri_correzione() == {"ok": False}

    def test_a_interruttore_spento_non_si_offre(self, amelie):
        self._non_riconosciuta(amelie)
        amelie.correzioni_attive = False
        detti = []
        amelie._pubblica = detti.append
        amelie._mostra(Stato.RIPOSIZIONA)
        assert detti[-1]["aiuta"] is False
        assert amelie.apri_correzione() == {"ok": False}

    def test_chiudere_senza_salvare_lascia_riprovare(self, amelie):
        self._non_riconosciuta(amelie)
        amelie.apri_correzione()
        assert amelie.chiudi_correzione() == {"ok": True}
        assert amelie._correggendo is None
        assert amelie.macchina.stato is Stato.RIPOSIZIONA
