"""Collaudo dell'orchestratore, senza hardware.

Con `--simula-mcu` e i sensori finti si può far scorrere l'intero ciclo su un
portatile: è il modo per verificare che la macchina a stati, gli effetti e il
flusso verso lo schermo siano coerenti fra loro, senza dipendere da una
bottiglia vera.
"""

import threading
import time
from pathlib import Path

import pytest

from amelie.app import COLORE_ANELLO, VISTA, Amelie, Configurazione
from amelie.bridge import Colore
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


class TestLoZeroNonEUnaDistanza:
    """Il sensore dice «non c'è niente» restituendo zero, e zero è sotto ogni
    soglia: preso per buono, chi lo legge crede di avere sempre una bottiglia
    davanti.

    Misurato al banco, con la mano che entra ed esce dal cono:

        niente davanti    distanza 0     SPAD 52368, sempre lo stesso
        mano davanti      25..176 mm     SPAD 392..51528, variabili

    Lo stato resta «misura buona» in tutti e due i casi. Il firmware ora
    restituisce -1 per lo zero, che il ponte traduce in `None`.

    La bottiglia non si riconosce più così — la guarda la camera, vedi
    `PresenzaOttica` — ma `distanza_mm` è rimasta, la usa `scripts/bus.py` per
    chi ha i cavetti in mano, e uno zero preso per una distanza racconterebbe
    una bugia anche lì.
    """

    def test_il_ponte_traduce_il_meno_uno(self):
        from amelie.bridge import Ponte

        p = Ponte()
        p.chiama = lambda *a, **k: -1
        assert p.distanza_mm() is None


class TestColore:
    def test_rifiuta_valori_fuori_scala(self):
        with pytest.raises(ValueError):
            Colore(300, 0, 0)
        with pytest.raises(ValueError):
            Colore(0, 0, 0, luminosita=200)

    def test_l_anello_resta_a_bassa_luminosita(self):
        """Otto LED accesi tutta la sera su un cavetto Qwiic da 28 AWG.

        I colori di stato restano bassi perche' ci stanno per ore. L'unico che
        va alto e' la luce dello scatto, che dura la frazione di secondo della
        raffica: se un giorno finisse fra i colori di stato, il rail 3,3 V
        cederebbe e con lui l'I2C — e il sintomo sarebbe un guasto dei moduli.
        """
        from amelie.bridge import AMBRA, BIANCO_SCATTO, ROSSO, VERDE
        for c in (AMBRA, VERDE, ROSSO):
            assert c.luminosita <= 40
        assert BIANCO_SCATTO.luminosita > 40, \
            "la luce dello scatto deve essere davvero piu' forte degli stati"


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
        """Un oggetto illeggibile sul piatto non deve far lampeggiare l'anello
        e girare l'OCR tutta la sera, su una board senza ventola."""
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

        from amelie.capture import ImpostazioniCamera, Scatto
        from amelie.ocr import Lettura, Riga

        class CameraFinta:
            # Come quella vera, che porta con se' le proprie impostazioni: il
            # ciclo ci legge la posa per metterla a giornale.
            imp = ImpostazioniCamera()

            def scatta(self, **_):
                return Scatto(immagine=np.zeros((8, 8, 3), dtype=np.uint8),
                              nitidezza=420.0)

        class LettoreFinto:
            def __init__(self, righe): self.righe = righe
            def leggi(self, _immagine):
                return Lettura(righe=[Riga(testo=t, confidenza=0.95)
                                      for t in self.righe], durata_s=0.1)
            # Il ciclo chiede `leggi_comunque`, che sul lettore vero riprova
            # girando il fotogramma: qui non c'e' niente da girare.
            leggi_comunque = leggi

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


class TestLaSchermataNonResta:
    """A racconto finito il dispositivo torna all'invito, da solo.

    Prima restava sulla schermata del racconto per sempre, con il riproduttore
    in vista e tutti i pulsanti inerti, finché qualcuno non toglieva la
    bottiglia. A tavola quella schermata non dice niente e non fa niente: è il
    dispositivo che sembra piantato.
    """

    @pytest.fixture
    def amelie(self):
        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_concluso_scade_e_torna_in_attesa(self, amelie):
        from amelie.state import DURATE_S

        assert DURATE_S[Stato.CONCLUSO] is not None, \
            "senza un tetto si resta li' per sempre"
        amelie.macchina.stato = Stato.CONCLUSO
        t = amelie.macchina.invia(Evento.SCADENZA)
        assert t.a is Stato.ATTESA

    def test_non_si_racconta_due_volte_la_stessa_bottiglia(self, amelie):
        """Il difetto che nasce dalla correzione, se non ci si pensa.

        Tornando in attesa con la bottiglia ancora sul piatto, il rilancio che
        serve a riprendersi da un guasto farebbe ripartire una seconda lettura,
        e poi una terza: lo stesso vino raccontato all'infinito finché qualcuno
        non toglie la bottiglia.
        """
        import asyncio

        amelie._bottiglia_finta = True          # una bottiglia c'e', e resta
        # E il filtro l'ha gia' vista: quando un racconto finisce, la presenza
        # e' vera da un pezzo. Senza questo si proverebbe un fronte di salita
        # che nella realta' e' gia' passato.
        amelie.presenza.presente = True
        # Dal percorso vero: e' la transizione a segnare che si e' raccontato,
        # non l'assegnazione dello stato.
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        assert amelie.macchina.stato is Stato.CONCLUSO
        assert amelie._bottiglia_chiusa
        amelie.macchina.invia(Evento.SCADENZA)
        assert amelie.macchina.stato is Stato.ATTESA

        for _ in range(6):                   # sei battiti: il filtro è sazio
            asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is Stato.ATTESA, \
            "la stessa bottiglia non deve far ripartire una lettura"

    def test_ma_una_bottiglia_nuova_si(self, amelie):
        """Tolta e rimessa, è un'altra storia."""
        import asyncio

        amelie._bottiglia_chiusa = True
        amelie.macchina.stato = Stato.ATTESA
        amelie.presenza.presente = True      # la bottiglia c'era
        amelie._bottiglia_finta = False        # e adesso e' tolta
        for _ in range(6):
            asyncio.run(amelie._un_battito())
        assert not amelie.presenza.presente
        assert not amelie._bottiglia_chiusa

        amelie._bottiglia_finta = True          # rimessa
        for _ in range(4):
            asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is not Stato.ATTESA, \
            "una bottiglia nuova deve far ripartire il giro"


class TestSegnalazione:
    """«Nessuno di questi»: l'unico caso che il dispositivo non risolve da solo.

    Un OCR che legge male, un vino che nel database non c'è, un'etichetta con un
    carattere che il modello non conosce. Senza un bottone, quel caso sparisce:
    l'ospite tocca a caso o aspetta, e chi deve correggere non sa nemmeno che è
    successo.
    """

    @pytest.fixture
    def amelie(self, tmp_path, monkeypatch):
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "CARTELLA_SEGNALAZIONI", tmp_path / "segn")
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_salva_cosa_serve_a_rifare_il_caso(self, amelie, tmp_path):
        import json as j

        amelie._righe = ["NERO D'AV", "SICILIA"]
        amelie._candidati = ["Sicilia Nero d'Avola", "Nero d'Avola Spumante"]
        amelie.macchina.stato = Stato.CONFERMA

        esito = amelie.segnala()
        assert esito["ok"]

        cartella = (tmp_path / "segn") / esito["cartella"]
        rapporto = j.loads((cartella / "segnalazione.json").read_text(encoding="utf-8"))
        assert rapporto["righe_lette"] == ["NERO D'AV", "SICILIA"]
        assert rapporto["proposte"] == ["Sicilia Nero d'Avola",
                                        "Nero d'Avola Spumante"]
        assert rapporto["quando"] and rapporto["lingua"] == "it"

    def test_il_tavolo_non_resta_fermo(self, amelie):
        """Segnalare non deve lasciare l'ospite su una schermata di scelta: si
        racconta comunque il più generico che si sa dire."""
        amelie.macchina.stato = Stato.CONFERMA
        amelie.segnala()
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_un_disco_pieno_non_blocca_il_racconto(self, amelie, monkeypatch):
        """La segnalazione è un di più: se non si può scrivere, pazienza."""
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "CARTELLA_SEGNALAZIONI",
                            Path("/proc/non-si-puo-scrivere-qui"))
        amelie.macchina.stato = Stato.CONFERMA
        assert amelie.segnala() == {"ok": False}

    def test_la_voce_e_nel_lessico_in_tutte_le_lingue(self, amelie):
        for lingua in amelie.lex.lingue:
            testo = amelie.lex.frase("schermo", "nessuno_di_questi", lingua=lingua)
            assert testo and testo.strip()


class TestIlCambioLinguaEImmediato:
    """Toccare una bandierina mentre parla l'altra vuol dire aver cambiato idea.

    Prima l'annuncio in corso si sentiva per intero, e solo dopo partiva quello
    chiesto: il tocco sembrava perso. Ora si taglia e si riparte.

    È la seconda volta che si sceglie di interrompere. La prima era andata male
    — gli annunci si tagliavano a vicenda e non si sentiva niente — ma la causa
    non era l'interruzione: era che il flusso audio si apriva e chiudeva a ogni
    frase, e il DSP di questa board impiega due secondi ad avviarsi. Da quando
    il flusso resta aperto quel costo non c'è più.
    """

    @pytest.fixture
    def amelie(self):
        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_il_secondo_tocco_taglia_il_primo(self, amelie):
        class VoceFinta:
            def __init__(self): self.zittita = 0
            def zittisci(self): self.zittita += 1
        amelie.voce = VoceFinta()

        avviati = []
        amelie._ciclo_annunci = lambda: avviati.append(1)

        amelie._annunciatore_vivo = True          # uno sta gia' parlando
        amelie._chiedi_annuncio("en")

        assert amelie.voce.zittita == 1, "l'annuncio in corso va tagliato"
        assert amelie._lingua_da_annunciare == "en"
        assert not avviati, "non si avvia un secondo annunciatore"

    def test_il_primo_tocco_parla_e_basta(self, amelie):
        class VoceFinta:
            def __init__(self): self.zittita = 0
            def zittisci(self): self.zittita += 1
        amelie.voce = VoceFinta()

        partiti = []
        import threading as t
        vero = t.Thread
        try:
            t.Thread = lambda **k: type("F", (), {"start": lambda s: partiti.append(k)})()
            amelie._chiedi_annuncio("it")
        finally:
            t.Thread = vero
        assert amelie.voce.zittita == 0, "non c'e' niente da tagliare"
        assert partiti, "il primo tocco avvia l'annunciatore"

    def test_il_racconto_aspetta_che_l_annuncio_abbia_finito(self, amelie):
        """Scrivono nello stesso flusso audio: partendo insieme si sovrappongono.

        «English language» e la prima frase del racconto uscivano una sopra
        l'altra, e non si capiva né l'una né l'altra.
        """
        import time as t

        amelie._annunciatore_vivo = True

        def libera():
            t.sleep(0.25)
            amelie._annunciatore_vivo = False
        threading.Thread(target=libera, daemon=True).start()

        inizio = t.monotonic()
        amelie._attendi_annuncio(3.0)
        passato = t.monotonic() - inizio
        assert 0.2 < passato < 1.0, "deve aspettare, ma non per sempre"
        assert not amelie._annunciatore_vivo

    def test_l_attesa_ha_sempre_un_tetto(self, amelie):
        """Un annunciatore che non finisce non deve bloccare il racconto."""
        import time as t

        amelie._annunciatore_vivo = True
        inizio = t.monotonic()
        amelie._attendi_annuncio(0.3)
        assert t.monotonic() - inizio < 1.0


class TestLaCodaAudioNonSiTronca:
    """Il racconto si tagliava tre quarti di secondo prima della fine.

    Non era la voce: era la coda. `_suona` esce quando l'ultimo pezzo è stato
    CONSEGNATO all'uscita, ma fra la consegna e l'orecchio ci sono la riserva
    della coda e la latenza di ALSA — e `ferma()`, chiamato subito dopo, li
    buttava via. In tutte e due le lingue, perché non dipendeva dalla lingua.
    """

    def test_il_riproduttore_sa_aspettare_la_propria_coda(self):
        from amelie.speech import Riproduttore, Uscita

        assert hasattr(Riproduttore, "attendi_la_coda")
        assert hasattr(Uscita, "attendi_fine")

    def test_si_aspetta_solo_se_e_finito_da_solo(self):
        """Bottiglia tolta a metà: lì si tronca eccome, ed è quello che serve."""
        radice = Path(__file__).resolve().parents[1]
        app = (radice / "src" / "amelie" / "app.py").read_text(encoding="utf-8")
        pezzo = app[app.index("finito = lettore.attendi"):]
        pezzo = pezzo[:pezzo.index("lettore.ferma()")]
        assert "attendi_la_coda" in pezzo
        assert "if finito and not self._ferma_voce.is_set():" in pezzo

    def test_l_attesa_finisce_anche_se_qualcuno_zittisce(self):
        """Altrimenti togliere la bottiglia lascerebbe il thread appeso."""
        from amelie.speech import ImpostazioniVoce, Uscita

        class FintaVoce:
            imp = ImpostazioniVoce()
            guadagno = 1.0

        u = Uscita(FintaVoce())
        u._fermo.set()                       # come dopo un `ferma()`
        t = time.monotonic()
        u.attendi_fine(tetto_s=5.0)
        assert time.monotonic() - t < 0.5, "non deve aspettare a vuoto"


class TestLaLinguaTornaACasa:
    """Tolta la bottiglia, la lingua torna quella di partenza.

    Lo dichiaravano il commento di `Configurazione.lingua` e la guida di
    montaggio, e non lo faceva nessuno: la lingua si scriveva solo all'avvio e
    dentro `cambia_lingua`. Il tavolo dopo trovava l'inglese lasciato dal
    precedente, senza sapere che si cambia toccando una bandierina.
    """

    @pytest.fixture
    def amelie(self):
        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True,
                                  lingua="it"))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_torna_alla_lingua_di_casa_quando_si_torna_in_attesa(self, amelie):
        amelie.macchina.stato = Stato.RACCONTO
        amelie.cambia_lingua("en")
        assert amelie.lingua == "en"

        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert amelie.macchina.stato is Stato.ATTESA
        assert amelie.lingua == "it"
        assert amelie.narratore.lingua == "it", \
            "anche il narratore deve tornare indietro, non solo lo schermo"

    def test_la_schermata_di_attesa_esce_gia_nella_lingua_giusta(self, amelie):
        """Prima di ridisegnare, non dopo: altrimenti l'invito comparirebbe in
        inglese e cambierebbe sotto gli occhi di chi si siede."""
        detti = []
        amelie._pubblica = detti.append
        amelie.macchina.stato = Stato.RACCONTO
        amelie.cambia_lingua("en")
        detti.clear()

        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        lingue = [m for m in detti if m.get("tipo") == "lingua"]
        stati = [m for m in detti if m.get("tipo") == "stato"]
        assert lingue and lingue[0]["lingua"] == "it"
        assert stati, "la schermata d'attesa dev'essere stata ridisegnata"
        assert detti.index(lingue[0]) < detti.index(stati[-1])

    def test_non_si_annuncia_a_tavolo_vuoto(self, amelie):
        """Un dispositivo che parla da solo in sala non va bene."""
        chiesti = []
        amelie._chiedi_annuncio = chiesti.append
        amelie.macchina.stato = Stato.RACCONTO
        amelie.cambia_lingua("en")
        chiesti.clear()

        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert not chiesti, "tornare alla lingua di casa non si annuncia"

    def test_se_la_lingua_non_e_cambiata_non_succede_niente(self, amelie):
        detti = []
        amelie._pubblica = detti.append
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert not [m for m in detti if m.get("tipo") == "lingua"]


class TestFirmwareEPythonDAccordo:
    """Il firmware e il codice Python non si leggono a vicenda.

    Lo sketch somma dei bit, `bridge.NOMI_MODULI` li rilegge per nome, e i due
    stanno in linguaggi diversi su processori diversi. Quando il secondo Pixels
    è stato tolto, i bit sono passati da tre a due e la distanza da 4 a 2:
    aggiornare uno solo dei due lati avrebbe prodotto il guasto più difficile di
    tutti — il montaggio funziona e il dispositivo dice che il sensore non c'è.

    Questi test leggono lo sketch come testo. È rozzo di proposito: qualunque
    cosa di più raffinato richiederebbe un compilatore C.
    """

    @staticmethod
    def _sketch() -> str:
        return (Path(__file__).resolve().parents[1]
                / "firmware" / "amelie_mcu" / "amelie_mcu.ino").read_text(
                    encoding="utf-8")

    def test_i_bit_dello_sketch_sono_quelli_che_python_rilegge(self):
        import re

        from amelie.bridge import NOMI_MODULI

        corpo = re.search(r"int moduli\(\)\s*\{(.*?)\}", self._sketch(), re.S)
        assert corpo, "moduli() non si trova nello sketch"
        bit = [int(b) for b in re.findall(r"\?\s*(\d+)\s*:\s*0", corpo.group(1))]
        atteso = [1 << i for i in range(len(NOMI_MODULI))]
        assert bit == atteso, (
            f"lo sketch somma {bit}, NOMI_MODULI ne prevede {atteso} "
            f"({NOMI_MODULI}): uno dei due lati è rimasto indietro")

    def test_lo_stato_tecnico_dice_che_firmware_c_e(self):
        """Si apre dal vetro tenendo premuto l'angolo, senza tastiera: montando
        è l'unico modo di vedere da lì se sull'MCU c'è ancora il firmware di
        prima, quello in cui i bit dei moduli significavano un'altra cosa."""
        from amelie.app import crea_app

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        try:
            rotta = next(r for r in crea_app(a).routes
                         if getattr(r, "path", None) == "/stato")
            import asyncio
            import json
            corpo = json.loads(asyncio.run(rotta.endpoint()).body)
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()
        from amelie.bridge import PROTOCOLLO_ATTESO
        assert corpo["protocollo"] == PROTOCOLLO_ATTESO
        assert corpo["moduli"] == {"anello": True, "distanza": True}

    def test_la_versione_del_protocollo_e_la_stessa_nei_due_linguaggi(self):
        """È il numero che impedisce di leggere a rovescio i bit di un MCU
        vecchio: se i due lati non concordano, non protegge da niente."""
        import re

        from amelie.bridge import PROTOCOLLO_ATTESO

        m = re.search(r"PROTOCOLLO\s*=\s*(\d+)", self._sketch())
        assert m, "lo sketch non dichiara PROTOCOLLO"
        assert int(m.group(1)) == PROTOCOLLO_ATTESO, (
            f"sketch {m.group(1)}, bridge.py {PROTOCOLLO_ATTESO}: "
            f"il controllo di versione non protegge piu' da niente")

    def test_gli_indirizzi_sono_gli_stessi_nei_due_linguaggi(self):
        import re

        from amelie.bridge import ANELLO, DISTANZA

        sketch = self._sketch()
        for nome, atteso in (("IND_ANELLO", ANELLO), ("IND_TOF", DISTANZA)):
            m = re.search(rf"{nome}\s*=\s*(0x[0-9A-Fa-f]+)", sketch)
            assert m, f"{nome} non si trova nello sketch"
            assert int(m.group(1), 16) == atteso, \
                f"{nome}: sketch {m.group(1)}, bridge.py {atteso:#04x}"

    def test_ogni_metodo_che_python_chiama_lo_sketch_lo_dichiara(self):
        import re

        sketch = self._sketch()
        dichiarati = set(re.findall(r'Bridge\.provide\("([^"]+)"', sketch))
        radice = Path(__file__).resolve().parents[1]
        bridge = (radice / "src" / "amelie" / "bridge.py").read_text(encoding="utf-8")
        chiamati = set(re.findall(r'self\.chiama\("([^"]+)"', bridge))
        assert chiamati <= dichiarati, (
            f"Python chiama metodi che lo sketch non dichiara: "
            f"{sorted(chiamati - dichiarati)}")


class TestIlFlashNonTorna:
    """Il secondo Modulino Pixels è stato tolto: che non rientri per sbaglio.

    Non è pignoleria. I nomi del flash erano sparsi in nove file fra firmware,
    orchestratore, cattura, ponte, test e documenti, e ne bastava uno rimasto
    per mandare chi monta a cercare un modulo che non esiste — che è
    esattamente la classe di perdita di tempo che questo progetto continua a
    incontrare.
    """

    # I nomi che non devono più esistere come CODICE. Nei commenti si possono
    # nominare: la nota storica che spiega perché il modulo è sparito vale più
    # della regola che la vieta.
    PROIBITI = ("set_flash", "BIANCO_FLASH", "FLASH_E_SCATTA",
                "assestamento_flash_s", "attesa_flash")

    def test_nessuno_di_quei_nomi_e_rimasto_nel_codice(self):
        import re

        radice = Path(__file__).resolve().parents[1]
        sorgenti = [*(radice / "src" / "amelie").rglob("*.py"),
                    *(radice / "scripts").glob("*.py"),
                    radice / "firmware" / "amelie_mcu" / "amelie_mcu.ino"]
        colpe = []
        for f in sorgenti:
            for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                spoglia = re.sub(r"(#|//|\*).*$", "", riga)
                for nome in self.PROIBITI:
                    if nome in spoglia:
                        colpe.append(f"{f.relative_to(radice)}:{n}  {riga.strip()}")
        assert not colpe, "il flash è rientrato:\n  " + "\n  ".join(colpe)

    def test_il_ponte_non_espone_piu_un_flash(self):
        from amelie.bridge import Ponte

        assert not hasattr(Ponte, "flash")

    def test_c_e_un_solo_pixels_nella_distinta(self):
        radice = Path(__file__).resolve().parents[1]
        distinta = (radice / "README.md").read_text(encoding="utf-8")
        assert "2× Modulino Pixels" not in distinta
        assert "1× Modulino Pixels" in distinta


class TestOgniEffettoHaUnEsecutore:
    """Un effetto che nessuno esegue è uno stato che non fa niente.

    `Effetto.FLASH_E_SCATTA` è diventato `ILLUMINA_E_SCATTA` in due file: se il
    rinominio fosse rimasto a metà, la macchina a stati sarebbe entrata in
    SCANSIONE e non avrebbe scattato mai — e nessun test l'avrebbe detto, perché
    la transizione sarebbe stata comunque corretta.

    Tre effetti però sono inerti **di proposito**, e vanno tenuti distinti da
    quelli dimenticati: le tre schermate. Lo schermo non lo disegna l'effetto, lo
    disegna `_mostra(stato)` a ogni transizione — gli effetti MOSTRA_* e
    SCHERMO_ATTESA restano nella tabella perché dicono *che cosa* si vede in
    quello stato, non perché qualcuno li esegua.
    """

    # Se questa lista si allunga, qualcuno ha aggiunto un effetto e non l'ha
    # collegato a niente. Se si accorcia, qualcuno l'ha implementato e va tolto
    # da qui. In tutti e due i casi è una decisione da prendere, non da subire.
    INERTI = {"SCHERMO_ATTESA", "MOSTRA_RIPOSIZIONA", "MOSTRA_GUASTO"}

    def test_nessun_effetto_resta_inerte_per_distrazione(self):
        from amelie.state import EFFETTI_INGRESSO, EFFETTI_USCITA

        radice = Path(__file__).resolve().parents[1]
        app = (radice / "src" / "amelie" / "app.py").read_text(encoding="utf-8")
        chiesti = {e for effetti in
                   (*EFFETTI_INGRESSO.values(), *EFFETTI_USCITA.values())
                   for e in effetti}
        senza_esecutore = {e.name for e in chiesti
                           if f"Effetto.{e.name}" not in app and e not in COLORE_ANELLO}
        assert senza_esecutore == self.INERTI, (
            f"gli effetti senza esecutore sono cambiati: {sorted(senza_esecutore)}. "
            f"Se ne hai aggiunto uno, collegalo in `_esegui`; se ne hai "
            f"implementato uno, toglilo da INERTI")


class TestLuceDelloScatto:
    """L'anello è anche la luce dello scatto, da quando il flash è stato tolto.

    Ed è per questo che ora ha due padroni: la macchina a stati, che gli dà il
    colore dello stato, e la cattura, che lo porta a bianco per la raffica. Dove
    i due si incontrano è nato un difetto, e questi test lo tengono chiuso.
    """

    class CameraRotta:
        def scatta(self, **_):
            from amelie.capture import CameraNonDisponibile
            raise CameraNonDisponibile("staccata")

    class CameraFinta:
        """Registra il colore dell'anello NELL'ISTANTE dello scatto.

        Guardare solo l'ordine dei comandi non basta: se un giorno l'ambra
        venisse rimessa PRIMA di `camera.scatta()`, la sequenza resterebbe
        bianco-poi-ambra e il test passerebbe lo stesso, mentre la raffica
        avverrebbe al buio.
        """

        def __init__(self, ponte):
            from amelie.capture import ImpostazioniCamera

            self.ponte = ponte
            self.imp = ImpostazioniCamera()
            self.acceso_quando_ho_scattato = None

        def scatta(self, **_):
            from amelie.capture import Scatto
            anelli = [p for m, p in self.ponte.comandi if m == "set_anello"]
            self.acceso_quando_ho_scattato = anelli[-1] if anelli else None
            return Scatto(immagine=None, nitidezza=99.0)

    def _amelie(self, fabbrica_camera):
        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        a.camera = fabbrica_camera(a.ponte)
        a.lettore = object()          # non ci si arriva mai, in questi test
        a.macchina.stato = Stato.SCANSIONE
        return a

    @staticmethod
    def _ultimo_colore(amelie):
        anelli = [p for m, p in amelie.ponte.comandi if m == "set_anello"]
        return anelli[-1] if anelli else None

    def test_un_guasto_lascia_l_anello_rosso(self):
        """Il difetto vero: con un `finally` l'ambra tornava DOPO il rosso.

        L'ordine era: la camera fallisce, la macchina a stati entra in GUASTO e
        accende il rosso, e il `finally` lo cancellava rimettendo l'ambra. A
        schermo restava un guasto dichiarato sopra un anello del colore
        dell'invito — che è esattamente la cosa che schermo e anello non devono
        mai fare.
        """
        from amelie.bridge import ROSSO

        a = self._amelie(lambda _: self.CameraRotta())
        try:
            a._scatta_e_leggi()
            assert a.macchina.stato is Stato.GUASTO
            assert self._ultimo_colore(a) == (ROSSO.r, ROSSO.g, ROSSO.b,
                                              ROSSO.luminosita), \
                "dopo un guasto l'anello deve restare del colore del guasto"
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_il_bianco_non_resta_acceso_durante_l_ocr(self):
        """Dopo la raffica c'è l'OCR, che dura quattro secondi.

        Quattro secondi di bianco pieno sotto una bottiglia non sono una luce,
        sono un lampeggiante: l'ambra si rimette subito dopo lo scatto, non
        alla fine del metodo.
        """
        from amelie.bridge import AMBRA, BIANCO_SCATTO

        a = self._amelie(self.CameraFinta)
        try:
            # Il lettore finto solleva: si arriva fin qui e non oltre, che è
            # esattamente il punto in cui l'anello dev'essere già tornato ambra.
            try:
                a._scatta_e_leggi()
            except Exception:                               # noqa: BLE001
                pass
            colori = [p for m, p in a.ponte.comandi if m == "set_anello"]
            bianco = (BIANCO_SCATTO.r, BIANCO_SCATTO.g, BIANCO_SCATTO.b,
                      BIANCO_SCATTO.luminosita)
            ambra = (AMBRA.r, AMBRA.g, AMBRA.b, AMBRA.luminosita)
            assert a.camera.acceso_quando_ho_scattato == bianco, \
                "la raffica dev'essere avvenuta con la luce accesa"
            assert colori[-1] == ambra, \
                "dopo lo scatto l'ambra deve tornare subito, prima dell'OCR"
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()


class TestModuliVisti:
    """`moduli()` è lo strumento del montaggio: si collega un pezzo per volta e
    si chiede al dispositivo se lo vede, invece di dedurlo da un LED spento.

    Perché serva a quello, deve rispondere sempre — anche a un firmware vecchio
    che non conosce il metodo, che è uno dei guasti che si stanno cercando.
    """

    def _ponte(self, risposta, versione=None):
        """Un Ponte che risponde `risposta` a `moduli` e `versione` a `versione`.

        La versione va finta insieme ai bit: da quando il significato dei bit è
        cambiato, `moduli()` chiede prima con chi sta parlando.
        """
        from amelie.bridge import PROTOCOLLO_ATTESO, Ponte

        v = PROTOCOLLO_ATTESO if versione is None else versione

        def chiama(metodo, *a, **k):
            if metodo == "versione":
                if isinstance(v, Exception):
                    raise v
                return v
            if isinstance(risposta, Exception):
                raise risposta
            return risposta

        p = Ponte()
        p.chiama = chiama
        return p

    def test_i_bit_stanno_nell_ordine_dello_sketch(self):
        assert self._ponte(0).moduli() == {"anello": False, "distanza": False}
        assert self._ponte(1).moduli()["anello"]
        assert self._ponte(2).moduli()["distanza"]
        assert all(self._ponte(3).moduli().values())

    def test_il_sensore_da_solo_non_e_l_anello(self):
        """Il caso del montaggio vero: sensore collegato, anello ancora no."""
        assert self._ponte(2).moduli() == {"anello": False, "distanza": True}

    def test_i_nomi_sono_quelli_che_lo_sketch_dichiara(self):
        """Il numero dei bit e il numero dei nomi sono la stessa cosa.

        Quando il secondo Pixels è stato tolto, i bit sono passati da tre a due
        e la distanza da 4 a 2: una tabella rimasta indietro avrebbe detto
        «sensore assente» a un sensore collegato, che è il guasto più difficile
        da capire di tutti — il montaggio funziona e il dispositivo dice di no.
        """
        from amelie.bridge import NOMI_MODULI

        assert NOMI_MODULI == ("anello", "distanza")
        pieno = (1 << len(NOMI_MODULI)) - 1
        assert set(self._ponte(pieno).moduli()) == set(NOMI_MODULI)

    def test_un_firmware_vecchio_dice_non_vedo_niente(self):
        from amelie.bridge import ErroreMCU, PonteNonDisponibile

        for guasto in (ErroreMCU("moduli: method not available"),
                       PonteNonDisponibile("niente socket"),
                       OSError("socket sparito")):
            assert self._ponte(guasto).moduli() == {
                "anello": False, "distanza": False}

    def test_una_risposta_senza_senso_non_fa_saltare_niente(self):
        assert self._ponte(None).moduli() == {"anello": False, "distanza": False}

    def test_un_firmware_di_prima_non_viene_letto_a_rovescio(self):
        """Il guasto peggiore che si possa avere montando.

        Quando il secondo Pixels è stato tolto, il bit 2 è passato da «flash» a
        «sensore» e il sensore ha lasciato il bit 4. Un Linux nuovo che legge un
        MCU vecchio direbbe «sensore presente» col flash collegato, e «sensore
        assente» col sensore: il montaggio è giusto e il dispositivo dice di no,
        in silenzio. Meglio «non lo so» che una risposta rovesciata.
        """
        # 0b011: per il firmware vecchio è anello + flash, sensore ASSENTE.
        vecchio = self._ponte(0b011, versione=1)
        assert vecchio.moduli() == {"anello": False, "distanza": False}, \
            "i bit di un protocollo diverso non vanno interpretati"

    def test_un_firmware_che_non_dichiara_la_versione_e_troppo_vecchio(self):
        from amelie.bridge import ErroreMCU

        muto = self._ponte(0b111, versione=ErroreMCU("versione: method not available"))
        assert muto.versione() is None
        assert muto.moduli() == {"anello": False, "distanza": False}

    def test_il_banco_simulato_ha_tutto_collegato(self):
        from amelie.bridge import PonteSimulato

        assert all(PonteSimulato().moduli().values())


class TestFineDelRacconto:
    def test_i_pulsanti_non_fingono_dopo_la_fine(self, amelie):
        """Mezzo secondo in cui i tasti agivano su un riproduttore gia' morto.

        Il riproduttore resta agganciato finche' l'ultimo suono non e' uscito
        davvero - tre quarti di secondo. In quella finestra i suoi thread sono
        finiti, ma lo schermo mostra ancora il racconto: un tocco su «indietro»
        spostava la posizione, la barra tornava indietro e ci restava, perche'
        nessuno pubblicava piu' niente.
        """
        class LettoreEsaurito:
            esaurito = True

            def salta(self, s):
                raise AssertionError("non deve essere toccato")

        amelie._lettore = LettoreEsaurito()
        try:
            assert amelie.comanda_racconto("indietro") == {"ok": False}
        finally:
            amelie._lettore = None


    def test_la_schermata_non_si_svuota_alla_fine(self, amelie):
        """Due secondi di schermo vuoto alla fine di OGNI racconto.

        La vista di CONCLUSO e' la stessa del racconto, ma `_mostra` riempiva
        titolo e sottotitolo solo per RACCONTO: il client, che ripulisce a ogni
        messaggio di stato con vista «racconto», si trovava senza titolo e
        svuotava testo e barra. Restava uno schermo nero con sopra il solo
        pulsante, finche' non si tornava all'invito.
        """
        from amelie.matcher import Livello

        amelie._fatti.livello = Livello.VINO      # altrimenti e' «ho rinunciato»
        amelie._fatti.nome = "Barolo Cannubi"
        amelie._fatti.cantina = "Marchesi di Barolo"
        visti = []
        amelie._pubblica = lambda m: visti.append(m)
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        stati = [m for m in visti if m.get("tipo") == "stato"]
        assert stati, "nessuna schermata mandata entrando in concluso"
        ultimo = stati[-1]
        assert ultimo["vista"] == "racconto"
        assert ultimo.get("titolo"), "il titolo e' sparito"
        assert ultimo.get("stesso_racconto") is True, \
            "senza questo il client svuota il testo che si e' appena ascoltato"

    def test_arrivando_al_racconto_invece_si_svuota(self, amelie):
        """L'altro lato: fra una bottiglia e l'altra il testo di prima non resta."""
        from amelie.matcher import Livello

        amelie._fatti.livello = Livello.VINO
        visti = []
        amelie._pubblica = lambda m: visti.append(m)
        amelie.macchina.stato = Stato.RICONOSCIMENTO
        amelie.macchina.invia(Evento.MATCH_SICURO)
        stati = [m for m in visti if m.get("tipo") == "stato"]
        assert stati[-1].get("stesso_racconto") is False


class TestAnnullamento:
    """Chiudere senza dover togliere la bottiglia dal piatto.

    Fino a qui l'unico modo di finire era sollevarla. Va benissimo quando si e'
    finito davvero, ma non per chi ha appena versato: il vino e' nel bicchiere,
    la bottiglia sta li', e nessuno la risolleva solo per far tacere il
    dispositivo.
    """

    def test_dal_racconto_si_torna_all_invito(self, amelie):
        amelie.macchina.stato = Stato.RACCONTO
        amelie._ferma_voce.clear()
        assert amelie.annulla()["ok"]
        assert amelie.macchina.stato is Stato.ATTESA

    def test_annullare_zittisce_subito(self, amelie):
        """Il difetto che si sente: la voce che continua sopra l'invito.

        La macchina zittisce da sola uscendo da RACCONTO, ma solo da li'.
        """
        amelie.macchina.stato = Stato.RACCONTO
        amelie._ferma_voce.clear()
        amelie.annulla()
        assert amelie._ferma_voce.is_set()

    def test_dalla_conferma_si_torna_all_invito(self, amelie):
        """Da qui la macchina NON zittisce da sola: non si esce da RACCONTO.

        E in conferma ci puo' essere un annuncio di lingua in bocca, perche'
        guardando i candidati si tocca la bandierina.
        """
        amelie.macchina.stato = Stato.CONFERMA
        amelie._lingua_da_annunciare = "en"
        assert amelie.annulla()["ok"]
        assert amelie.macchina.stato is Stato.ATTESA
        assert amelie._lingua_da_annunciare is None, \
            "l'annuncio finirebbe sopra la schermata d'invito"

    def test_anche_nei_due_secondi_dopo_la_fine(self, amelie):
        """La schermata del racconto resta accesa anche in CONCLUSO.

        Ci si vede il pulsante, quindi deve funzionare: un pulsante acceso e
        inerte e' peggio di un pulsante che non c'e'.
        """
        amelie.macchina.stato = Stato.CONCLUSO
        assert amelie.annulla()["ok"]
        assert amelie.macchina.stato is Stato.ATTESA

    def test_l_anello_torna_al_respiro(self, amelie):
        """Schermo e anello devono dire la stessa cosa.

        Un annullamento scritto fuori dalla macchina lascerebbe l'anello del
        racconto acceso sopra la schermata d'invito.
        """
        amelie.macchina.stato = Stato.RACCONTO
        amelie.ponte.comandi.clear()
        amelie.annulla()
        colori = [c for c in amelie.ponte.comandi if c[0] == "set_anello"]
        assert colori, "l'anello non e' stato rimesso"

    def test_la_scadenza_della_conferma_si_spegne(self, amelie):
        """Restava armata e scattava dopo, a invito gia' disegnato.

        In conferma c'e' un tetto di dodici secondi che prende il primo
        candidato: annullando non deve piu' scattare.
        """
        amelie.macchina.stato = Stato.RICONOSCIMENTO
        amelie.macchina.invia(Evento.MATCH_DUBBIO)
        assert amelie._scadenza is not None
        amelie.annulla()
        assert amelie._scadenza is None

    def test_negli_stati_di_lavoro_non_fa_nulla(self, amelie):
        """Quelle schermate non hanno pulsanti, e l'OCR resterebbe a girare."""
        amelie.macchina.stato = Stato.SCANSIONE
        amelie._ferma_voce.clear()
        assert not amelie.annulla()["ok"]
        assert amelie.macchina.stato is Stato.SCANSIONE
        assert not amelie._ferma_voce.is_set(), \
            "un tocco caduto nel vuoto non deve zittire il racconto che verra'"

    def test_un_tocco_caduto_nel_vuoto_non_tocca_niente(self, amelie):
        """Il difetto che stavo per introdurre correggendo l'altro.

        Chi toglie la bottiglia alza `_ferma_voce` per zittire il racconto. Se
        un tocco su «annulla» arriva un istante dopo - il dito era gia' partito
        mentre la schermata cambiava - e l'annullamento «ripulisce» quel flag
        perche' non ha trovato niente da annullare, il racconto di una
        bottiglia che non c'e' piu' riprende a scorrere.

        La regola: si guarda PRIMA se c'e' qualcosa da annullare, e nel dubbio
        non si tocca niente.
        """
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)   # la bottiglia se ne va
        assert amelie._ferma_voce.is_set()
        amelie.annulla()                                   # il tocco in ritardo
        assert amelie._ferma_voce.is_set(), \
            "il tocco in ritardo ha rimesso in moto un racconto gia' fermato"

    def test_fermare_e_avviare_non_possono_incrociarsi(self):
        """Fra il controllo e l'assegnazione c'era una finestra di pochi bytecode.

        `_racconta` guardava `_ferma_voce`, poi assegnava `_lettore`. Un
        annullamento che passava in mezzo non trovava nessun riproduttore da
        fermare, e ne lasciava partire uno subito dopo: il dispositivo
        cominciava a parlare sopra la schermata d'invito. Stretta quanto si
        vuole, era proprio la finestra che l'annullamento doveva chiudere.

        La prova: tenendo il lucchetto del riproduttore, `_ferma_racconto` non
        deve riuscire ad alzare la bandiera. Se ci riuscisse, vorrebbe dire che
        la alza FUORI dal lucchetto, e allora potrebbe alzarla in mezzo.
        """
        import threading

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        try:
            a._ferma_voce.clear()
            partito = threading.Event()

            def ferma():
                partito.set()
                a._ferma_racconto()

            with a._lucchetto_lettore:
                t = threading.Thread(target=ferma, daemon=True)
                t.start()
                partito.wait(1.0)
                time.sleep(0.05)
                assert not a._ferma_voce.is_set(), (
                    "la bandiera si alza fuori dal lucchetto: fra il controllo "
                    "e l'assegnazione ci si puo' infilare")
            t.join(timeout=1.0)
            assert a._ferma_voce.is_set(), "rilasciato il lucchetto, deve alzarsi"
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_senza_voce_annullare_non_lascia_il_lavoro_in_giro(self, amelie):
        """Il testo scorreva con `sleep`, che nessuna bandiera puo' svegliare.

        Il thread di lavoro restava vivo fino a sei secondi dopo che lo schermo
        era gia' tornato all'invito, e una bottiglia rimessa dentro quella
        finestra trovava il lavoro ancora in corso: guasto dichiarato.
        """
        import threading
        import time

        frasi = ["Una frase abbastanza lunga da far dormire il ciclo a lungo." * 2]
        amelie._ferma_voce.clear()
        finito = threading.Event()

        def scorri():
            amelie._scorri_senza_voce(frasi)
            finito.set()

        t = threading.Thread(target=scorri, daemon=True)
        t.start()
        time.sleep(0.15)
        amelie._ferma_voce.set()
        assert finito.wait(1.0), \
            "il ripiego senza voce non si e' accorto dell'annullamento"

    def test_la_lingua_scelta_non_si_perde(self, amelie):
        """Annullare non vuol dire che il tavolo e' finito.

        Una coppia inglese tocca la bandierina, ascolta, e poi preme la croce
        perche' ne ha sentito abbastanza. La bottiglia e' ancora sul piatto e
        sono le stesse persone: ritrovarsi l'invito in italiano, e dover
        ricercare la bandierina per la bottiglia dopo, e' una piccola offesa.
        La lingua torna a casa quando la bottiglia viene TOLTA.
        """
        amelie.cambia_lingua("en")
        assert amelie.lingua == "en"
        amelie.macchina.stato = Stato.RACCONTO
        amelie.annulla()
        assert amelie.lingua == "en", "annullare ha riportato la lingua a casa"

    def test_togliendo_la_bottiglia_invece_si(self, amelie):
        """Li' il tavolo cambia davvero, e il dispositivo torna come si trova."""
        amelie.cambia_lingua("en")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert amelie.lingua == "it"

    def test_annullando_il_giro_non_riparte(self, amelie):
        """Il difetto che nasce dalla correzione, se non ci si pensa.

        Tornando in attesa con la bottiglia ancora sul piatto, il rilancio che
        serve a riprendersi da un guasto fa ripartire la lettura al PRIMO
        battito, cioe' un decimo di secondo dopo il tocco. E non si ferma dopo
        tre tentativi: ogni lettura riuscita azzera quel contatore, quindi con
        un'etichetta leggibile il dispositivo racconterebbe lo stesso vino ogni
        cinque secondi finche' qualcuno non solleva la bottiglia.
        """
        import asyncio

        amelie._bottiglia_finta = True          # la bottiglia c'e', e resta
        amelie.presenza.presente = True      # il filtro l'ha gia' vista
        amelie.macchina.stato = Stato.RACCONTO
        amelie.annulla()
        assert amelie.macchina.stato is Stato.ATTESA

        for _ in range(6):
            asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is Stato.ATTESA, \
            "annullare e poi ricominciare da soli e' peggio che non annullare"

    def test_ma_togliendola_e_rimettendola_si(self, amelie):
        """Annullare chiude QUESTA bottiglia, non spegne il dispositivo."""
        import asyncio

        amelie._bottiglia_finta = True
        amelie.presenza.presente = True
        amelie.macchina.stato = Stato.RACCONTO
        amelie.annulla()

        amelie._bottiglia_finta = False        # tolta
        for _ in range(6):
            asyncio.run(amelie._un_battito())
        assert not amelie._bottiglia_chiusa

        amelie._bottiglia_finta = True          # rimessa
        for _ in range(4):
            asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is not Stato.ATTESA


class TestLaSceltaCheNessunoFa:
    """Dodici secondi davanti a tre candidati, e nessuno tocca lo schermo.

    Succede quasi sempre: l'ospite guarda, non capisce che deve scegliere, o
    sta versando. Allora si prende il PRIMO CANDIDATO, cioè la prima riga che
    aveva davanti.

    Prima si raccontava il match primario, che è un'altra cosa. Visto sul
    dispositivo con uno spumante rosa: a schermo tre Metodo Classico Rosé,
    nessuno li tocca, e la voce racconta il Moscato d'Asti — un quarto vino,
    che in quella lista non c'era.
    """

    def amelie(self):
        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        return a

    def test_scaduta_la_scelta_si_prende_il_primo_candidato(self, monkeypatch):
        a = self.amelie()
        try:
            adottati = []
            monkeypatch.setattr(a, "_adotta_candidato",
                                lambda i: adottati.append(i) or True)
            monkeypatch.setattr(a, "_avvia", lambda _f: None)
            a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
            a.macchina.invia(Evento.SCADENZA)          # assestamento -> scansione
            a.macchina.invia(Evento.LETTURA_RIUSCITA)  # -> riconoscimento
            a.macchina.invia(Evento.MATCH_DUBBIO)      # -> conferma
            assert a.macchina.stato is Stato.CONFERMA
            a.macchina.invia(Evento.SCADENZA)          # -> racconto
            assert a.macchina.stato is Stato.RACCONTO
            assert adottati == [0], (
                "ha raccontato senza prendere il candidato che mostrava")
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_se_invece_si_sceglie_si_prende_quello_toccato(self, monkeypatch):
        a = self.amelie()
        try:
            adottati = []
            monkeypatch.setattr(a, "_adotta_candidato",
                                lambda i: adottati.append(i) or True)
            monkeypatch.setattr(a, "_avvia", lambda _f: None)
            a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
            a.macchina.invia(Evento.SCADENZA)
            a.macchina.invia(Evento.LETTURA_RIUSCITA)
            a.macchina.invia(Evento.MATCH_DUBBIO)
            a.scegli(2)
            assert a.macchina.stato is Stato.RACCONTO
            assert adottati == [2]
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_un_racconto_normale_non_adotta_niente(self, monkeypatch):
        """Un match sicuro non passa dalla schermata di scelta, e non deve
        trovarsi sostituito da un candidato che nessuno ha visto."""
        a = self.amelie()
        try:
            adottati = []
            monkeypatch.setattr(a, "_adotta_candidato",
                                lambda i: adottati.append(i) or True)
            monkeypatch.setattr(a, "_avvia", lambda _f: None)
            a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
            a.macchina.invia(Evento.SCADENZA)
            a.macchina.invia(Evento.LETTURA_RIUSCITA)
            a.macchina.invia(Evento.MATCH_SICURO)      # -> racconto, diretto
            assert a.macchina.stato is Stato.RACCONTO
            assert adottati == []
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()
