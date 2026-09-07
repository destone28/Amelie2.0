"""Collaudo dell'orchestratore, senza hardware.

Con `--simula-mcu` e i sensori finti si può far scorrere l'intero ciclo su un
portatile: è il modo per verificare che la macchina a stati, gli effetti e il
flusso verso lo schermo siano coerenti fra loro, senza dipendere da una
bottiglia vera.
"""

import pytest

from amelie.app import COLORE_ANELLO, VISTA, Amelie, Configurazione
from amelie.bridge import Colore, Presenza
from amelie.state import Effetto, Evento, Stato


@pytest.fixture
def amelie():
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                              senza_voce=True, senza_modello=True))
    yield a
    a.matcher.chiudi()
    a.narratore.chiudi()


class TestCopertura:
    def test_ogni_stato_ha_una_vista(self):
        for s in Stato:
            assert s in VISTA, f"{s} non sa cosa mostrare"

    def test_ogni_effetto_anello_ha_un_colore(self):
        for e in Effetto:
            if e.name.startswith("ANELLO_"):
                assert e in COLORE_ANELLO, f"{e} non ha un colore"


class TestCiclo:
    def test_la_bottiglia_accende_l_anello(self, amelie):
        amelie.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        metodi = [c[0] for c in amelie.ponte.comandi]
        assert "set_anello" in metodi

    def test_togliere_la_bottiglia_zittisce(self, amelie):
        """Il difetto peggiore possibile: parlare di un vino tolto dal tavolo.

        Si porta la macchina in RACCONTO direttamente, senza passare dalla
        pipeline: quella gira in un thread e renderebbe il test dipendente dai
        tempi. Qui interessa solo che l'effetto di uscita scatti.
        """
        amelie.macchina.stato = Stato.RACCONTO
        amelie._ferma_voce.clear()
        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert amelie._ferma_voce.is_set(), "il racconto deve fermarsi subito"

    def test_la_pipeline_e_collegata_davvero(self, amelie):
        """Senza righe da leggere, il riconoscimento porta a RIPOSIZIONA.

        E' la prova che gli effetti della macchina a stati chiamano davvero il
        codice, invece di limitarsi a cambiare etichetta.
        """
        import time
        for e in (Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA,
                  Evento.LETTURA_RIUSCITA):
            amelie.macchina.invia(e)
        for _ in range(50):
            if amelie.macchina.stato is not Stato.RICONOSCIMENTO:
                break
            time.sleep(0.05)
        assert amelie.macchina.stato is Stato.RIPOSIZIONA

    def test_uno_stato_sconosciuto_non_fa_esplodere_la_vista(self, amelie):
        for s in Stato:
            amelie._fatti.livello = amelie._fatti.livello
            amelie._mostra(s)   # non deve sollevare


class TestPresenza:
    def test_serve_piu_di_una_lettura_per_dire_che_c_e(self):
        p = Presenza(letture_per_arrivare=3)
        assert not p.aggiorna(20)
        assert not p.aggiorna(20)
        assert p.aggiorna(20)

    def test_e_piu_difficile_dire_che_se_n_e_andata(self):
        """Asimmetria voluta: interrompere un racconto si nota molto di piu'."""
        p = Presenza(letture_per_arrivare=3, letture_per_andarsene=5)
        for _ in range(3):
            p.aggiorna(20)
        assert p.presente
        for _ in range(4):
            p.aggiorna(200)
        assert p.presente, "quattro letture lontane non bastano"
        p.aggiorna(200)
        assert not p.presente

    def test_la_zona_morta_non_fa_tremolare(self):
        p = Presenza(vicino_mm=40, lontano_mm=70)
        for _ in range(5):
            p.aggiorna(20)
        assert p.presente
        for _ in range(20):
            p.aggiorna(55)      # in mezzo: non deve cambiare idea
        assert p.presente

    def test_misura_non_valida_conta_come_assente(self):
        p = Presenza(letture_per_andarsene=2)
        for _ in range(3):
            p.aggiorna(20)
        p.aggiorna(None); p.aggiorna(None)
        assert not p.presente


class TestColore:
    def test_rifiuta_valori_fuori_scala(self):
        with pytest.raises(ValueError):
            Colore(300, 0, 0)
        with pytest.raises(ValueError):
            Colore(0, 0, 0, luminosita=200)

    def test_l_anello_resta_a_bassa_luminosita(self):
        """Due Pixels a piena potenza sono mezzo ampere sui cavetti Qwiic."""
        from amelie.bridge import AMBRA, VERDE, ROSSO
        for c in (AMBRA, VERDE, ROSSO):
            assert c.luminosita <= 40


class TestDifettiTrovatiDallaVerifica:
    """I tre difetti che la verifica avversariale ha trovato, e che i test
    precedenti non vedevano. Restano qui perche' non tornino."""

    def test_il_database_si_usa_da_un_altro_thread(self):
        """Il difetto bloccante: SQLite rifiuta le connessioni fra thread.

        L'orchestratore crea la connessione nel thread principale e la usa nel
        thread di lavoro. Senza check_same_thread=False ogni ricerca solleva
        ProgrammingError e NESSUN vino viene mai riconosciuto. Il test
        precedente non lo vedeva perche' passava righe vuote, e cerca()
        ritornava prima di toccare la connessione.
        """
        import threading

        import pytest as _pytest
        _pytest.importorskip("rapidfuzz")
        from amelie.matcher import DatabaseAssente, Matcher

        try:
            m = Matcher()
        except DatabaseAssente as e:
            _pytest.skip(str(e))

        esito: list = []

        def cerca_da_un_altro_thread():
            try:
                esito.append(m.cerca(["MARCHESI DI BAROLO", "Barolo", "Cannubi"]))
            except Exception as e:                          # noqa: BLE001
                esito.append(e)

        t = threading.Thread(target=cerca_da_un_altro_thread)
        t.start()
        t.join(timeout=30)
        m.chiudi()

        assert esito, "il thread non ha prodotto nulla"
        assert not isinstance(esito[0], Exception), (
            f"ricerca fallita da un altro thread: {esito[0]!r}")
        assert esito[0].livello is not Stato and esito[0].nome

    def test_non_si_riprova_all_infinito(self, amelie):
        """Un oggetto illeggibile sul piatto non deve far lampeggiare il flash
        tutta la sera."""
        from amelie.app import TENTATIVI_MAX
        assert TENTATIVI_MAX <= 5

        amelie._tentativi = TENTATIVI_MAX
        amelie.macchina.stato = Stato.RIPOSIZIONA
        t = amelie.macchina.invia(Evento.RINUNCIA)
        assert t.a is Stato.CONCLUSO, "dopo troppi tentativi si deve smettere"

    def test_gli_stati_che_dipendono_da_un_thread_hanno_un_tetto(self):
        """Se il lavoro non torna, la macchina non deve restare li' per sempre."""
        from amelie.state import DURATE_S, TRANSIZIONI
        for stato in (Stato.SCANSIONE, Stato.RICONOSCIMENTO):
            assert DURATE_S[stato] is not None, f"{stato} senza tetto"
            assert (stato, Evento.SCADENZA) in TRANSIZIONI, f"{stato} non gestisce SCADENZA"

    def test_lavoro_sovrapposto_dichiara_guasto(self, amelie):
        """Ignorare e basta lasciava la macchina bloccata in SCANSIONE."""
        import threading
        import time

        fermo = threading.Event()
        amelie._lavoro = threading.Thread(target=fermo.wait, daemon=True)
        amelie._lavoro.start()
        time.sleep(0.05)
        amelie.macchina.stato = Stato.SCANSIONE
        amelie._avvia(lambda: None)
        fermo.set()
        assert amelie.macchina.stato is Stato.GUASTO


class TestCicloCompleto:
    """Il ciclo vero, dalla bottiglia al racconto, con camera e OCR finti.

    Questa classe esiste per un motivo preciso. Tutti gli altri test spingevano
    la pipeline mandando gli eventi a mano DAL THREAD DEL TEST, e con quella
    forma il dispositivo sembrava funzionare. Ma in esercizio ogni passo della
    pipeline è avviato dal passo precedente, cioè DAL THREAD DI LAVORO: e lì
    `_avvia` trovava vivo un thread che era sé stesso, si dichiarava occupato e
    mandava tutto in GUASTO. Su ogni bottiglia, sempre. Il dispositivo non
    raccontava nulla e nessun test se ne accorgeva.

    Il collaudo che conta è quello che percorre il ciclo come lo percorre una
    bottiglia vera: si mette la presenza, si aspetta, si guarda cosa dice.
    """

    ETICHETTA = ["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016",
                 "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA"]

    @pytest.fixture
    def amelie_con_etichetta(self):
        """Amelie con camera e OCR finti che restituiscono righe VERE."""
        import numpy as np

        from amelie.capture import Scatto
        from amelie.ocr import Lettura, Riga

        class CameraFinta:
            def scatta(self, **_):
                return Scatto(immagine=np.zeros((8, 8, 3), dtype=np.uint8),
                              nitidezza=420.0)

        class LettoreFinto:
            def __init__(self, righe): self.righe = righe
            def leggi(self, _immagine):
                return Lettura(righe=[Riga(testo=t, confidenza=0.95)
                                      for t in self.righe], durata_s=0.1)

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        a.camera = CameraFinta()
        a.lettore = LettoreFinto(self.ETICHETTA)
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def _attendi(self, amelie, stati, secondi=20.0):
        import time
        scadenza = time.monotonic() + secondi
        while time.monotonic() < scadenza:
            if amelie.macchina.stato in stati:
                return amelie.macchina.stato
            # La scadenza dell'assestamento la fa scattare il ciclo di
            # sorveglianza, che qui non gira: la si simula.
            if amelie._scadenza and time.monotonic() >= amelie._scadenza:
                amelie._scadenza = None
                amelie.macchina.invia(Evento.SCADENZA)
            time.sleep(0.02)
        return amelie.macchina.stato

    def test_una_bottiglia_leggibile_viene_raccontata(self, amelie_con_etichetta):
        """Il test che mancava: nessun evento a mano dopo il primo."""
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        finale = self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO,
                                   Stato.CONFERMA, Stato.GUASTO})
        assert finale is not Stato.GUASTO, (
            "il ciclo è finito in guasto su un'etichetta perfettamente leggibile")
        assert finale in {Stato.RACCONTO, Stato.CONCLUSO, Stato.CONFERMA}

    def test_il_racconto_nomina_il_vino_letto(self, amelie_con_etichetta):
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.CONFERMA,
                          Stato.GUASTO})
        assert not a._fatti.vuoto, "l'OCR ha letto ma il riconoscimento non ha dato nulla"
        testo = " ".join(filter(None, [a._fatti.nome, a._fatti.tipologia,
                                       a._fatti.denominazione])).lower()
        assert "barolo" in testo, f"riconosciuto {testo!r} da un'etichetta di Barolo"

    def test_l_annata_dell_etichetta_arriva_ai_fatti(self, amelie_con_etichetta):
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.CONFERMA,
                          Stato.GUASTO})
        assert a._fatti.annata == 2016

    def test_un_etichetta_illeggibile_chiede_di_girarla(self, amelie_con_etichetta):
        """L'altro capo: nessuna riga letta non deve diventare un guasto."""
        a = amelie_con_etichetta
        a.lettore.righe = []
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        finale = self._attendi(a, {Stato.RIPOSIZIONA, Stato.CONCLUSO,
                                   Stato.GUASTO})
        assert finale is not Stato.GUASTO

    def test_righe_senza_riscontro_non_finiscono_in_guasto(self, amelie_con_etichetta):
        """L'OCR legge, ma nel database non c'è niente: si chiede di girarla."""
        a = amelie_con_etichetta
        a.lettore.righe = ["ZZZQXW", "KJHGFD"]
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        finale = self._attendi(a, {Stato.RIPOSIZIONA, Stato.RACCONTO,
                                   Stato.CONCLUSO, Stato.GUASTO})
        assert finale is not Stato.GUASTO


class TestLingua:
    """La lingua si sceglie a schermo, con un tocco, anche a racconto in corso."""

    def test_si_parte_dalla_lingua_configurata(self, amelie):
        assert amelie.lingua == "it"
        assert amelie.narratore.lingua == "it"

    def test_cambiare_lingua_cambia_anche_il_narratore(self, amelie):
        assert amelie.cambia_lingua("en")
        assert amelie.lingua == "en"
        assert amelie.narratore.lingua == "en"

    def test_una_lingua_che_non_esiste_non_cambia_nulla(self, amelie):
        prima = amelie.lingua
        assert not amelie.cambia_lingua("de")
        assert amelie.lingua == prima

    def test_scegliere_la_lingua_gia_attiva_non_fa_nulla(self, amelie):
        assert not amelie.cambia_lingua(amelie.lingua)

    def test_le_scritte_dello_schermo_seguono_la_lingua(self, amelie):
        """Schermo in italiano e racconto in inglese e' il modo peggiore
        di essere bilingui: le frasi venivano da stringhe cablate nel codice."""
        visti = {}
        for lingua in ("it", "en"):
            amelie.cambia_lingua(lingua)
            catturati = []
            amelie._pubblica = lambda m, c=catturati: c.append(m)
            amelie._mostra(Stato.RIPOSIZIONA)
            visti[lingua] = catturati[0]["frase"]
        assert visti["it"] != visti["en"]
        assert visti["en"], "manca la frase inglese"

    def _attendi(self, amelie, stato, secondi=5.0):
        """L'annuncio e la ripresa girano in un thread: non sono istantanei."""
        import time
        scadenza = time.monotonic() + secondi
        while time.monotonic() < scadenza:
            if amelie.macchina.stato is stato:
                return True
            time.sleep(0.02)
        return False

    def test_il_racconto_riparte_quando_si_cambia_lingua(self, amelie):
        """Coi fatti gia' in mano non serve rimettere la bottiglia."""
        amelie.macchina.stato = Stato.CONCLUSO
        amelie.cambia_lingua("en")
        assert self._attendi(amelie, Stato.RACCONTO)

    def test_si_puo_cambiare_lingua_mentre_parla(self, amelie):
        """Senza la transizione (RACCONTO, RIPETI) l'evento cadeva nel vuoto.

        Si guarda il FATTO - che il racconto sia ripartito - e non lo stato in
        un istante preciso: la storia riparte, corre e finisce, e a seconda di
        quanto e' carica la macchina si arriva a guardare prima o dopo.
        """
        import time

        amelie.macchina.stato = Stato.RACCONTO
        vecchio = amelie._lavoro
        assert amelie.cambia_lingua("en")

        # Non si guarda `_ferma_voce`: e' un dettaglio interno, e per giunta in
        # corsa - il racconto nuovo lo azzera appena riparte, quindi a seconda
        # di come si incastrano i thread lo si trova acceso o spento. Cio' che
        # conta e' che la storia sia ripartita.
        scadenza = time.monotonic() + 5
        while time.monotonic() < scadenza and amelie._lavoro is vecchio:
            time.sleep(0.02)
        assert amelie._lavoro is not vecchio, "il racconto non e' ripartito"
        assert amelie.macchina.stato in (Stato.RACCONTO, Stato.CONCLUSO)

    def test_il_racconto_riparte_anche_col_lavoro_vecchio_ancora_vivo(self, amelie):
        """Il difetto vero: non un guasto, un silenzio.

        `_avvia` rifiuta il lavoro se ne trova uno gia' vivo, e rifiutandolo
        manda ERRORE - che in RACCONTO non ha transizione. L'evento cadeva nel
        vuoto: la lingua cambiava a schermo, il racconto non ripartiva mai, e
        niente lo diceva.
        """
        import threading
        import time

        fermo = threading.Event()
        vecchio = threading.Thread(target=fermo.wait, daemon=True)
        vecchio.start()
        time.sleep(0.05)
        amelie._lavoro = vecchio
        amelie.macchina.stato = Stato.RACCONTO

        amelie.cambia_lingua("en")
        time.sleep(0.3)
        assert amelie._lavoro is vecchio, "non doveva partire nulla di nuovo"
        fermo.set()                       # il racconto vecchio finisce adesso

        scadenza = time.monotonic() + 5
        while time.monotonic() < scadenza and amelie._lavoro is vecchio:
            time.sleep(0.02)
        assert amelie._lavoro is not vecchio, \
            "il racconto non e' ripartito dopo l'uscita del lavoro precedente"

    def test_toccare_la_lingua_gia_attiva_annuncia_lo_stesso(self, amelie):
        """E' il modo piu' rapido di provare l'audio senza una bottiglia."""
        annunci = []
        amelie._annuncia_lingua = lambda l=None: annunci.append(l or amelie.lingua)
        assert not amelie.cambia_lingua(amelie.lingua)   # nulla e' cambiato
        import time
        scadenza = time.monotonic() + 3
        while time.monotonic() < scadenza and not annunci:
            time.sleep(0.02)
        assert annunci, "nessun annuncio: non si puo' provare l'audio con un tocco"

    def test_tocchi_ravvicinati_producono_un_solo_annuncio(self, amelie):
        """Il difetto che ha fatto sembrare rotto l'amplificatore.

        Le frasi durano un secondo abbondante, e ogni tocco zittiva quella in
        corso. Otto tocchi in nove secondi - che e' come si prova un audio -
        non producevano NESSUN suono udibile: ognuno tagliava il precedente
        prima che uscisse. Ora parla solo l'ultimo, e parla per intero.
        """
        import time

        annunci = []

        def parla_piano(lingua=None):
            # Una frase vera dura un secondo abbondante: senza questa durata il
            # test non riproduce il caso, perche' la coda non ha mai niente da
            # fondere e ogni tocco fa in tempo a parlare.
            annunci.append(lingua or amelie.lingua)
            time.sleep(0.4)

        amelie._annuncia_lingua = parla_piano
        for _ in range(4):
            amelie.cambia_lingua("en")
            time.sleep(0.05)
            amelie.cambia_lingua("it")
            time.sleep(0.05)
        time.sleep(2.0)
        # Il primo parla subito, i sette che arrivano mentre parla si riducono a
        # uno: al massimo due annunci, mai otto troncati.
        assert len(annunci) <= 2, f"{len(annunci)} annunci: {annunci}"
        assert annunci[-1] == "it", "l'ULTIMA lingua toccata dev'essere annunciata"

    def test_un_tocco_solo_annuncia(self, amelie):
        import time
        annunci = []
        amelie._annuncia_lingua = lambda l=None: annunci.append(l or amelie.lingua)
        amelie.cambia_lingua("en")
        scadenza = time.monotonic() + 3
        while time.monotonic() < scadenza and not annunci:
            time.sleep(0.02)
        assert annunci == ["en"]

    def test_una_lingua_inesistente_non_annuncia(self, amelie):
        annunci = []
        amelie._annuncia_lingua = lambda l=None: annunci.append(1)
        assert not amelie.cambia_lingua("de")
        import time
        time.sleep(1.0)
        assert not annunci

    def test_l_annuncio_esiste_in_ogni_lingua(self, amelie):
        for lingua in amelie.lex.lingue:
            frase = amelie.lex.frase("voce", "conferma_lingua", lingua=lingua)
            assert frase, f"manca l'annuncio per {lingua}"
        assert (amelie.lex.frase("voce", "conferma_lingua", lingua="it")
                != amelie.lex.frase("voce", "conferma_lingua", lingua="en"))

    def test_la_rinuncia_parla_la_lingua_scelta(self, amelie):
        amelie.cambia_lingua("en")
        catturati = []
        amelie._pubblica = lambda m: catturati.append(m)
        amelie._mostra(Stato.CONCLUSO)          # senza fatti: e' una rinuncia
        assert catturati[0]["vista"] == "avviso"
        assert catturati[0]["frase"], "nessun messaggio: lo schermo resterebbe vuoto"


class TestAvvio:
    """Che l'applicazione PARTA, con tutto acceso.

    Il buco che questa classe chiude: nessun test montava l'applicazione con la
    voce, e il ciclo di vita chiama metodi che nessun altro chiama. Cancellandone
    uno per sbaglio, i test restavano tutti verdi e il servizio non si avviava
    piu' - `AttributeError` dentro lo startup, e il chiosco su una pagina che non
    rispondeva.
    """

    def test_il_ciclo_di_vita_trova_tutto_quello_che_chiama(self):
        """I metodi che solo l'avvio usa esistono davvero."""
        for nome in ("_scalda_voci", "_mostra", "_manda_lingua",
                     "sorveglia", "salute"):
            assert callable(getattr(Amelie, nome, None)), \
                f"Amelie.{nome} non esiste: l'applicazione non si avvierebbe"

    def test_il_ciclo_di_vita_parte_e_si_chiude(self):
        """Il vero avvio: e' dentro qui che l'applicazione moriva.

        Si entra e si esce dal ciclo di vita come fa uvicorn. Non serve un
        client HTTP: il punto e' che lo startup esegua fino in fondo, che e'
        esattamente quello che non faceva piu'.
        """
        import asyncio

        from amelie.app import crea_app

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        app = crea_app(a)

        async def prova():
            async with app.router.lifespan_context(app):
                await asyncio.sleep(0.1)

        try:
            asyncio.run(prova())
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_il_ciclo_di_vita_parte_anche_con_la_voce(self):
        """Il caso che mancava: con la voce accesa si chiama `_scalda_voci`.

        E' l'unico posto che lo chiama, quindi era l'unico modo di accorgersi
        che non c'era piu'.
        """
        import asyncio

        from amelie.app import crea_app

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        # Una voce finta: qui non interessa il suono, interessa che il ciclo di
        # vita percorra il ramo che la usa.
        class VoceFinta:
            imp = type("i", (), {"device_alsa": "nulla", "frequenza": 22050})()
            disponibile_per_lingua = True
            def scalda(self, lingue=()): pass
            def per_lingua(self, codice): return True
            def sintetizza(self, frase): return b""
            def zittisci(self): pass
        a.voce = VoceFinta()
        app = crea_app(a)

        async def prova():
            async with app.router.lifespan_context(app):
                await asyncio.sleep(0.3)

        try:
            asyncio.run(prova())
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()


class TestPonteOnesto:
    """«MCU disponibile» deve voler dire che l'MCU sa fare quello che serve.

    Il router della UNO Q gira anche quando sull'MCU non c'è lo sketch di
    Amelie: il socket esiste, si connette, e ogni chiamata fallisce con
    «method not available». Controllare solo il socket faceva dichiarare
    `mcu: true` a un dispositivo che non poteva né leggere il sensore né
    accendere l'anello — ed è esattamente lo stato di una board appena
    preparata, prima di caricare il firmware.
    """

    def test_un_router_senza_sketch_non_e_un_mcu_disponibile(self):
        from amelie.bridge import ErroreMCU, Ponte

        p = Ponte()
        p.chiama = lambda *a, **k: (_ for _ in ()).throw(
            ErroreMCU("distanza: method distanza not available"))
        assert not p.disponibile

    def test_un_mcu_che_risponde_e_disponibile(self):
        from amelie.bridge import Ponte

        p = Ponte()
        p.chiama = lambda *a, **k: 42
        assert p.disponibile

    def test_senza_router_non_e_disponibile(self):
        from amelie.bridge import Ponte, PonteNonDisponibile

        p = Ponte(percorso="/non/esiste")
        p.chiama = lambda *a, **k: (_ for _ in ()).throw(
            PonteNonDisponibile("niente socket"))
        assert not p.disponibile
