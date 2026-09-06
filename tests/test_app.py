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
