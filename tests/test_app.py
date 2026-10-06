"""Collaudo dell'orchestratore, senza hardware.

Con `--simula-mcu` e i sensori finti si può far scorrere l'intero ciclo su un
portatile: è il modo per verificare che la macchina a stati, gli effetti e il
flusso verso lo schermo siano coerenti fra loro, senza dipendere da una
bottiglia vera.
"""

import contextlib
import re
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

    Lo stato resta «misura buona» in tutti e due i casi. Per questo il firmware
    restituisce -1 per lo zero, che il ponte traduce in `None`.

    La presenza della bottiglia la decide il sensore: `Amelie._chi_c_e` passa
    `distanza_mm` a `bridge.Presenza`. La stessa distanza la mostra
    `scripts/bus.py --sensore` a chi ha i cavetti in mano, e uno zero preso
    per una distanza racconterebbe una bugia anche lì.
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


class TestIlCicloNonSiBlocca:
    """Modi in cui il ciclo potrebbe bloccarsi, o non riconoscere niente, senza
    che nessun altro test se ne accorga."""

    def test_il_database_si_usa_da_un_altro_thread(self):
        """Il difetto bloccante: SQLite rifiuta le connessioni fra thread.

        L'orchestratore crea la connessione nel thread principale e la usa nel
        thread di lavoro. Senza check_same_thread=False ogni ricerca solleva
        ProgrammingError e NESSUN vino viene mai riconosciuto. Un test che
        passi righe vuote non lo vede, perche' cerca() ritorna prima di toccare
        la connessione: qui le righe sono vere.
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

    def test_lavoro_sovrapposto_non_blocca_la_macchina(self, amelie):
        """Ignorare e basta lascerebbe la macchina bloccata in SCANSIONE: il
        lavoro nuovo aspetta quello precedente e parte; se quello non finisce
        e' un guasto (vedi test_ripristino.TestIlLavoroDiPrima)."""
        import threading
        import time

        fermo = threading.Event()
        amelie._lavoro = threading.Thread(target=fermo.wait, daemon=True)
        amelie._lavoro.start()
        time.sleep(0.05)
        amelie.macchina.stato = Stato.SCANSIONE
        partito = threading.Event()
        amelie._avvia(partito.set)
        fermo.set()
        assert partito.wait(3), "la macchina resterebbe ad aspettare per sempre"


class TestCicloCompleto:
    """Il ciclo vero, dalla bottiglia al racconto, con camera e OCR finti.

    Spingere la pipeline mandando gli eventi a mano DAL THREAD DEL TEST non
    basta: in esercizio ogni passo della pipeline è avviato dal passo
    precedente, cioè DAL THREAD DI LAVORO. Se lì `_avvia` trovasse vivo un
    thread che è sé stesso, si dichiarerebbe occupato e manderebbe tutto in
    GUASTO, su ogni bottiglia, e un test che manda gli eventi a mano non se ne
    accorgerebbe.

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

            # La via normale: la camera e' gia' in moto e lo scatto si prende
            # dal flusso invece di farlo.
            def al_volo(self, **_):
                return self.scatta()

            def sorveglia(self): pass
            def sbircia(self): return None
            riquadro = None

            @contextlib.contextmanager
            def in_pausa(self):
                yield

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
        """Nessun evento a mano dopo il primo."""
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        finale = self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.GUASTO})
        assert finale is not Stato.GUASTO, (
            "il ciclo è finito in guasto su un'etichetta perfettamente leggibile")
        assert finale in {Stato.RACCONTO, Stato.CONCLUSO}

    def test_il_racconto_nomina_il_vino_letto(self, amelie_con_etichetta):
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.GUASTO})
        assert not a._fatti.vuoto, "l'OCR ha letto ma il riconoscimento non ha dato nulla"
        testo = " ".join(filter(None, [a._fatti.nome, a._fatti.tipologia,
                                       a._fatti.denominazione])).lower()
        assert "barolo" in testo, f"riconosciuto {testo!r} da un'etichetta di Barolo"

    def test_l_annata_dell_etichetta_arriva_ai_fatti(self, amelie_con_etichetta):
        a = amelie_con_etichetta
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.GUASTO})
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

    def test_un_etichetta_tagliata_si_rilegge_piu_larga(self, amelie_con_etichetta):
        """Quando lo scatto porta il fotogramma intero, il ciclo chiede al
        lettore di allargare; e se il lettore allarga, e' l'immagine allargata
        quella che si conserva - le righe lette stanno li' - e il giornale lo
        dice."""
        import numpy as np

        from amelie.capture import Scatto

        a = amelie_con_etichetta
        intero = np.zeros((40, 60, 3), dtype=np.uint8)
        a.camera.al_volo = lambda **_: Scatto(
            immagine=intero[:, 20:40], nitidezza=420.0, intero=intero,
            posto=(20, 0, 40, 40))
        chieste = []

        def allarga(lettura, fotogramma, posto):
            chieste.append(posto)
            return lettura, fotogramma[:, 0:40]

        a.lettore.allarga = allarga
        a.macchina.invia(Evento.BOTTIGLIA_PRESENTE)
        self._attendi(a, {Stato.RACCONTO, Stato.CONCLUSO, Stato.GUASTO})
        assert chieste == [(20, 0, 40, 40)]
        assert a._ultimo_scatto.shape[:2] == (40, 40)
        assert a._scansione.get("allargata") is True


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
        di essere bilingui: le frasi dello schermo vengono dal lessico, non da
        stringhe cablate nel codice."""
        visti = {}
        for lingua in ("it", "en"):
            amelie.cambia_lingua(lingua)
            catturati = []
            amelie._pubblica = lambda m, c=catturati: c.append(m)
            amelie._mostra(Stato.RIPOSIZIONA)
            visti[lingua] = catturati[0]["frase"]
        assert visti["it"] != visti["en"]
        assert visti["en"], "manca la frase inglese"

    def test_il_titolo_della_carta_e_il_suo_e_non_quello_di_prima(self, amelie):
        """Non «Garda Cabernet 2008» scritto sopra la descrizione di un
        Lambrusco Grasparossa.

        In modo carta i fatti dell'archivio possono essere ancora quelli del
        vino PRECEDENTE: il titolo non deve venire da li'.
        """
        from amelie.carta import Voce
        from amelie.matcher import Fatti, Livello

        amelie._fatti = Fatti(livello=Livello.VINO, nome="Garda Cabernet",
                              annata=2008)
        amelie._voce = Voce(titolo="Lambrusco Grasparossa di Castelvetro DOC",
                            descrizione="Il piu' corposo dei Lambruschi.")
        catturati = []
        amelie._pubblica = lambda m, c=catturati: c.append(m)
        amelie._mostra(Stato.RACCONTO)
        assert catturati[0]["titolo"] == "Lambrusco Grasparossa di Castelvetro DOC"
        assert catturati[0]["sottotitolo"] == ""

    def test_ma_se_la_carta_non_parla_la_lingua_il_titolo_e_dell_archivio(self, amelie):
        """La carta e' scritta in italiano e l'ospite ha scelto l'inglese: a
        raccontare e' l'archivio, e il titolo dev'essere il suo."""
        from amelie.carta import Voce
        from amelie.matcher import Fatti, Livello

        amelie.cambia_lingua("en")
        amelie._fatti = Fatti(livello=Livello.TIPOLOGIA,
                              tipologia="Lambrusco Grasparossa di Castelvetro")
        amelie._voce = Voce(titolo="Lambrusco Grasparossa DOC",
                            descrizione="Solo in italiano.")
        catturati = []
        amelie._pubblica = lambda m, c=catturati: c.append(m)
        amelie._mostra(Stato.RACCONTO)
        assert catturati[0]["titolo"] == "Lambrusco Grasparossa di Castelvetro"

    def test_al_generico_il_titolo_e_cio_che_dice_l_etichetta(self, amelie):
        """Senza nome lo schermo resterebbe senza titolo e il testo salirebbe
        in cima, sotto le linguette della lingua."""
        from amelie.matcher import Fatti, Livello

        f = Fatti(livello=Livello.GENERICO, colore="Rosato", sicurezza=88.0)
        f.qualificatori = ["spumante", "brut"]
        amelie._fatti, amelie._voce = f, None
        catturati = []
        amelie._pubblica = lambda m, c=catturati: c.append(m)
        amelie._mostra(Stato.RACCONTO)
        titolo = catturati[0]["titolo"]
        assert titolo.strip(), "nessun titolo al livello generico"
        # Senza l'articolo del racconto: a schermo non si legge «uno spumante».
        assert titolo == "Spumante rosato, brut"

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
        """Senza la transizione (RACCONTO, RIPETI) l'evento cadrebbe nel vuoto.

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
        """Il difetto da evitare non e' un guasto, e' un silenzio.

        Se `_avvia` rifiutasse il lavoro trovandone uno gia' vivo, manderebbe
        ERRORE - che in RACCONTO non ha transizione - e l'evento cadrebbe nel
        vuoto: la lingua cambierebbe a schermo, il racconto non ripartirebbe
        mai, e niente lo direbbe.
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
        """Il difetto che fa sembrare rotto l'amplificatore.

        Le frasi durano un secondo abbondante: se ogni tocco zittisse quella in
        corso, otto tocchi in nove secondi - che e' come si prova un audio -
        non produrrebbero NESSUN suono udibile, perche' ognuno taglierebbe il
        precedente prima che esca. Parla solo l'ultimo, e parla per intero.
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
        """A tentativi finiti, con le correzioni accese e qualcosa di letto,
        si dice che la bottiglia non e' stata riconosciuta, nella lingua del
        tavolo, e si offre di insegnarla."""
        import numpy as np
        amelie.correzioni_attive = True
        amelie._righe = ["PALAMA", "NEGROAMARO"]
        amelie._ultimo_scatto = np.zeros((8, 8, 3), dtype=np.uint8)
        amelie.cambia_lingua("en")
        catturati = []
        amelie._pubblica = lambda m: catturati.append(m)
        amelie._mostra(Stato.CONCLUSO)          # senza fatti: e' una rinuncia
        assert catturati[0]["vista"] == "avviso"
        assert catturati[0]["frase"] == "I couldn't recognise this bottle."
        assert catturati[0]["aiuta"] is True

    def test_senza_niente_da_insegnare_si_torna_all_invito(self, amelie):
        """Senza il pulsante per insegnarla, a tentativi finiti si torna subito
        all'invito: chiedere di togliere la bottiglia non servirebbe a niente."""
        amelie.correzioni_attive = False
        catturati = []
        amelie._pubblica = lambda m: catturati.append(m)
        amelie._mostra(Stato.CONCLUSO)
        assert catturati[0]["vista"] == "attesa"
        amelie.macchina.stato = Stato.RIPOSIZIONA
        amelie.macchina.invia(Evento.RINUNCIA)
        import time
        assert amelie._scadenza is not None and amelie._scadenza <= time.monotonic()


class TestAvvio:
    """Che l'applicazione PARTA, con tutto acceso.

    Il ciclo di vita chiama metodi che nessun altro chiama: cancellandone uno
    per sbaglio, senza questa classe i test resterebbero tutti verdi e il
    servizio non si avvierebbe - `AttributeError` dentro lo startup, e il
    chiosco su una pagina che non risponde.
    """

    def test_il_ciclo_di_vita_trova_tutto_quello_che_chiama(self):
        """I metodi che solo l'avvio usa esistono davvero."""
        for nome in ("_scalda_voci", "_mostra", "_manda_lingua",
                     "sorveglia", "salute"):
            assert callable(getattr(Amelie, nome, None)), \
                f"Amelie.{nome} non esiste: l'applicazione non si avvierebbe"

    def test_il_ciclo_di_vita_parte_e_si_chiude(self):
        """Il vero avvio: e' dentro qui che l'applicazione morirebbe.

        Si entra e si esce dal ciclo di vita come fa uvicorn. Non serve un
        client HTTP: il punto e' che lo startup esegua fino in fondo.
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
        """Con la voce accesa si chiama `_scalda_voci`.

        E' l'unico posto che lo chiama, quindi e' l'unico modo di accorgersi
        se sparisce.
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
    «method not available». Controllare solo il socket farebbe dichiarare
    `mcu: true` a un dispositivo che non può né leggere il sensore né
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

    Senza un tetto resterebbe sulla schermata del racconto per sempre, con il
    riproduttore in vista e tutti i pulsanti inerti, finché qualcuno non toglie
    la bottiglia. A tavola quella schermata non dice niente e non fa niente: è
    il dispositivo che sembra piantato.
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
        """Il difetto che nasce dal tornare da soli all'invito, se non ci si pensa.

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
        amelie._presente = True
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
        amelie._presente = True      # la bottiglia c'era
        amelie._bottiglia_finta = False        # e adesso e' tolta
        for _ in range(6):
            asyncio.run(amelie._un_battito())
        assert not amelie._presente
        assert not amelie._bottiglia_chiusa

        amelie._bottiglia_finta = True          # rimessa
        for _ in range(4):
            asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is not Stato.ATTESA, \
            "una bottiglia nuova deve far ripartire il giro"


class TestIlCambioLinguaEImmediato:
    """Toccare una bandierina mentre parla l'altra vuol dire aver cambiato idea.

    Se l'annuncio in corso si sentisse per intero, e solo dopo partisse quello
    chiesto, il tocco sembrerebbe perso: si taglia e si riparte.

    Interrompere funziona perché il flusso audio resta aperto (vedi
    `TestUscitaSempreAperta` in test_narrator.py). Se si aprisse e chiudesse a
    ogni frase, i due secondi che il DSP di questa board impiega ad avviarsi
    farebbero tagliare gli annunci a vicenda, e non si sentirebbe niente.
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

        «English language» e la prima frase del racconto uscirebbero una sopra
        l'altra, e non si capirebbe né l'una né l'altra.
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
    """Il racconto non si taglia tre quarti di secondo prima della fine.

    Il rischio non è nella voce ma nella coda. `_suona` esce quando l'ultimo
    pezzo è PASSATO all'uscita, ma fra l'uscita e l'orecchio ci sono la riserva
    della coda e la latenza di ALSA — e un `ferma()` chiamato subito dopo li
    butterebbe via, in tutte e due le lingue.
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

    Senza, il tavolo dopo troverebbe l'inglese lasciato dal precedente, senza
    sapere che si cambia toccando una bandierina.
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

    def test_un_racconto_finito_con_la_bottiglia_sul_piatto_non_la_cambia(self, amelie):
        """Stesso tavolo, stesse persone: chi ha scelto l'inglese non deve
        ritoccare la bandierina a ogni bottiglia."""
        amelie._presente = True
        amelie.macchina.stato = Stato.RACCONTO
        amelie.cambia_lingua("en")
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        amelie.macchina.invia(Evento.SCADENZA)
        assert amelie.macchina.stato is Stato.ATTESA
        assert amelie.lingua == "en"

    def test_tolta_ad_attesa_gia_raggiunta_la_lingua_torna_a_casa(self, amelie):
        import asyncio
        amelie._presente = True
        amelie.cambia_lingua("en")
        amelie.macchina.stato = Stato.ATTESA

        async def vuoto():
            return False
        amelie._chi_c_e = vuoto
        asyncio.run(amelie._un_battito())
        assert amelie.lingua == "it"

    def test_la_bandierina_a_racconto_finito_allunga_la_schermata(self, amelie):
        """Il racconto riparte dopo l'annuncio: la schermata finale non deve
        scadere prima, o si torna all'invito senza racconto."""
        import time
        from amelie import app as modulo
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        # Annuncio e ripresa restano fermi: si guarda la schermata finale
        # nell'istante in cui la lingua cambia.
        amelie._parla_dopo = lambda **_: None
        amelie.cambia_lingua("en")
        assert amelie.macchina.stato is Stato.CONCLUSO
        assert amelie._scadenza - time.monotonic() > modulo.LINGUA_A_RACCONTO_FINITO_S - 1

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
        """Un dispositivo che parla da solo, in una sala vuota, sembra guasto."""
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
    stanno in linguaggi diversi su processori diversi. Se i moduli cambiano,
    cambiano i bit, e aggiornare uno solo dei due lati produce il guasto più
    difficile di tutti — il montaggio funziona e il dispositivo dice che il
    sensore non c'è.

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
        è l'unico modo di vedere da lì se sull'MCU c'è un firmware con un'altra
        versione del protocollo, in cui i bit dei moduli significano un'altra
        cosa."""
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
        """È il numero che impedisce di leggere a rovescio i bit di un MCU non
        aggiornato: se i due lati non concordano, non protegge da niente."""
        import re

        from amelie.bridge import PROTOCOLLO_ATTESO

        m = re.search(r"PROTOCOLLO\s*=\s*(\d+)", self._sketch())
        assert m, "lo sketch non dichiara PROTOCOLLO"
        assert int(m.group(1)) == PROTOCOLLO_ATTESO, (
            f"sketch {m.group(1)}, bridge.py {PROTOCOLLO_ATTESO}: "
            f"il controllo di versione non protegge da niente")

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


class TestNienteFlashSeparato:
    """Un solo Modulino Pixels, l'anello: non c'è un flash separato.

    Non è pignoleria. Un nome di flash nel firmware, nell'orchestratore, nella
    cattura o nel ponte manderebbe chi monta a cercare un modulo che non
    esiste. Codice, sketch e distinta devono dire la stessa cosa.
    """

    # I nomi che non devono esistere come CODICE. Nei commenti si possono
    # nominare, per spiegare perché un flash separato non c'è.
    PROIBITI = ("set_flash", "BIANCO_FLASH", "FLASH_E_SCATTA",
                "assestamento_flash_s", "attesa_flash")

    def test_nessuno_di_quei_nomi_sta_nel_codice(self):
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
        assert not colpe, "c'è un flash nel codice:\n  " + "\n  ".join(colpe)

    def test_il_ponte_non_espone_un_flash(self):
        from amelie.bridge import Ponte

        assert not hasattr(Ponte, "flash")

    def test_c_e_un_solo_pixels_nella_distinta(self):
        radice = Path(__file__).resolve().parents[1]
        for leggimi in ("README.md", "README.it.md"):
            distinta = (radice / leggimi).read_text(encoding="utf-8")
            # Le righe della distinta cominciano con la quantita': «- 1 × …».
            distinta_pixels = [r for r in distinta.splitlines()
                               if re.match(r"- \d+ × ", r) and "Modulino Pixels" in r]
            assert len(distinta_pixels) == 1, leggimi
            assert distinta_pixels[0].startswith("- 1 × "), leggimi


class TestOgniEffettoHaUnEsecutore:
    """Un effetto che nessuno esegue è uno stato che non fa niente.

    Un effetto rinominato a metà — in `state.py` sì, in `app.py` no — farebbe
    entrare la macchina a stati in SCANSIONE senza scattare mai, e nessun altro
    test lo direbbe, perché la transizione sarebbe comunque corretta.

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
    """L'anello è anche la luce dello scatto.

    Per questo ha due padroni: la macchina a stati, che gli dà il colore dello
    stato, e la cattura, che lo porta a bianco per la raffica. Dove i due si
    incontrano può nascere un difetto, e questi test lo tengono chiuso.
    """

    class CameraRotta:
        def scatta(self, **_):
            from amelie.capture import CameraNonDisponibile
            raise CameraNonDisponibile("staccata")

        def al_volo(self, **_):
            return None

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

        # Il guardiano non gira: la camera vera risponde `None`, e si passa
        # dalla raffica. E' la condizione di questi test.
        def al_volo(self, **_):
            return None

        @contextlib.contextmanager
        def in_pausa(self):
            yield

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
        """Con un `finally` l'ambra tornerebbe DOPO il rosso.

        L'ordine sarebbe: la camera fallisce, la macchina a stati entra in
        GUASTO e accende il rosso, e il `finally` lo cancella rimettendo
        l'ambra. A schermo resterebbe un guasto dichiarato sopra un anello del
        colore dell'invito — che è esattamente la cosa che schermo e anello non
        devono mai fare.
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

        Quattro secondi di bianco pieno sulla bottiglia non sono una luce,
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

    def test_senza_raffica_non_c_e_nessun_lampo(self):
        """Quando la camera e' gia' in moto, l'anello non si tocca.

        Il bianco serve a illuminare una raffica; se la raffica non c'e', un
        bianco alzato e riabbassato un decimo dopo e' un lampo che non
        illumina niente. E costa: cinque livelli su 255, misurati, contro i
        quaranta che da' la posa.
        """
        from amelie.bridge import BIANCO_SCATTO
        from amelie.capture import Scatto

        class CameraInMoto:
            def __init__(self, _ponte):
                from amelie.capture import ImpostazioniCamera
                self.imp = ImpostazioniCamera()

            def al_volo(self, **_):
                return Scatto(immagine=None, nitidezza=99.0)

            def scatta(self, **_):
                raise AssertionError("non si deve arrivare alla raffica")

            @contextlib.contextmanager
            def in_pausa(self):
                yield

        a = self._amelie(CameraInMoto)
        try:
            try:
                a._scatta_e_leggi()
            except Exception:                               # noqa: BLE001
                pass
            bianco = (BIANCO_SCATTO.r, BIANCO_SCATTO.g, BIANCO_SCATTO.b,
                      BIANCO_SCATTO.luminosita)
            colori = [p for m, p in a.ponte.comandi if m == "set_anello"]
            assert bianco not in colori, \
                "lo scatto al volo non deve accendere l'anello"
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()


class TestModuliVisti:
    """`moduli()` è lo strumento del montaggio: si collega un pezzo per volta e
    si chiede al dispositivo se lo vede, invece di dedurlo da un LED spento.

    Perché serva a quello, deve rispondere sempre — anche con un firmware che
    non conosce il metodo, che è uno dei guasti che si stanno cercando.
    """

    def _ponte(self, risposta, versione=None):
        """Un Ponte che risponde `risposta` a `moduli` e `versione` a `versione`.

        La versione va finta insieme ai bit: `moduli()` chiede prima con chi
        sta parlando, perché il significato dei bit dipende dal protocollo.
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

        Una tabella con un nome in più, in meno o fuori posto direbbe «sensore
        assente» a un sensore collegato, che è il guasto più difficile da
        capire di tutti — il montaggio funziona e il dispositivo dice di no.
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

    def test_un_protocollo_diverso_non_viene_letto_a_rovescio(self):
        """Il guasto peggiore che si possa avere montando.

        Un MCU che parla un'altra versione del protocollo da' ai bit un altro
        significato. Letti senza guardare la versione, gli stessi bit
        direbbero «sensore presente» con un altro modulo collegato, e «sensore
        assente» col sensore: il montaggio è giusto e il dispositivo dice di
        no, in silenzio. Meglio «non lo so» che una risposta rovesciata.
        """
        # 0b011 da un MCU che dichiara un protocollo diverso: non si interpreta.
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
        """Mezzo secondo in cui i tasti agirebbero su un riproduttore gia' morto.

        Il riproduttore resta agganciato finche' l'ultimo suono non e' uscito
        davvero - tre quarti di secondo. In quella finestra i suoi thread sono
        finiti, ma lo schermo mostra ancora il racconto: un tocco su «indietro»
        sposterebbe la posizione, e la barra tornerebbe indietro e ci
        resterebbe, perche' nessuno pubblica piu' niente.
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
        """Niente due secondi di schermo vuoto alla fine di OGNI racconto.

        La vista di CONCLUSO e' la stessa del racconto: se `_mostra` riempisse
        titolo e sottotitolo solo per RACCONTO, il client, che ripulisce a ogni
        messaggio di stato con vista «racconto», si troverebbe senza titolo e
        svuoterebbe testo e barra, lasciando uno schermo nero con sopra il solo
        pulsante finche' non si torna all'invito.
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
        """L'altro lato: fra una bottiglia e l'altra il testo della precedente
        non resta."""
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

    Sollevarla va benissimo quando si e' finito davvero, ma non per chi ha
    appena versato: il vino e' nel bicchiere,
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

    def test_negli_stati_di_lavoro_non_fa_nulla(self, amelie):
        """Quelle schermate non hanno pulsanti, e l'OCR resterebbe a girare."""
        amelie.macchina.stato = Stato.SCANSIONE
        amelie._ferma_voce.clear()
        assert not amelie.annulla()["ok"]
        assert amelie.macchina.stato is Stato.SCANSIONE
        assert not amelie._ferma_voce.is_set(), \
            "un tocco caduto nel vuoto non deve zittire il racconto che verra'"

    def test_un_tocco_caduto_nel_vuoto_non_tocca_niente(self, amelie):
        """Un difetto facile da introdurre scrivendo l'annullamento.

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
        """Fra il controllo e l'assegnazione non resta nemmeno una finestra di pochi bytecode.

        `_racconta` guarda `_ferma_voce`, poi assegna `_lettore`. Un
        annullamento che passasse in mezzo non troverebbe nessun riproduttore
        da fermare, e ne lascerebbe partire uno subito dopo: il dispositivo
        comincerebbe a parlare sopra la schermata d'invito. Stretta quanto si
        vuole, e' proprio la finestra che l'annullamento deve chiudere.

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
        """Un testo che scorre con `sleep` non lo sveglia nessuna bandiera.

        Il thread di lavoro resterebbe vivo fino a sei secondi dopo che lo
        schermo e' gia' tornato all'invito, e una bottiglia rimessa dentro
        quella finestra troverebbe il lavoro ancora in corso: guasto dichiarato.
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
        amelie._presente = True
        amelie.macchina.stato = Stato.RACCONTO
        amelie.annulla()
        assert amelie.lingua == "en", "annullare ha riportato la lingua a casa"

    def test_annullando_a_bottiglia_gia_tolta_la_lingua_torna_a_casa(self, amelie):
        """La bottiglia sollevata per versare non ferma il racconto; se poi
        si annulla e sul piatto non c'e' niente, il tavolo e' libero: chi
        arriva dopo deve trovare la lingua di casa."""
        amelie.cambia_lingua("en")
        amelie._presente = False
        amelie.macchina.stato = Stato.RACCONTO
        amelie.annulla()
        assert amelie.lingua == "it"

    def test_togliendo_la_bottiglia_invece_si(self, amelie):
        """Li' il tavolo cambia davvero, e il dispositivo torna come si trova."""
        amelie.cambia_lingua("en")
        amelie.macchina.stato = Stato.RACCONTO
        amelie.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        assert amelie.lingua == "it"

    def test_annullando_il_giro_non_riparte(self, amelie):
        """Il difetto che nasce dall'annullamento, se non ci si pensa.

        Tornando in attesa con la bottiglia ancora sul piatto, il rilancio che
        serve a riprendersi da un guasto fa ripartire la lettura al PRIMO
        battito, cioe' un decimo di secondo dopo il tocco. E non si ferma dopo
        tre tentativi: ogni lettura riuscita azzera quel contatore, quindi con
        un'etichetta leggibile il dispositivo racconterebbe lo stesso vino ogni
        cinque secondi finche' qualcuno non solleva la bottiglia.
        """
        import asyncio

        amelie._bottiglia_finta = True          # la bottiglia c'e', e resta
        amelie._presente = True      # il filtro l'ha gia' vista
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
        amelie._presente = True
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


class TestIlDubbioNonSiChiede:
    """Con un riconoscimento dubbio non c'e' una schermata di scelta.

    Tre nomi quasi uguali, a un tavolo, a chi non ha chiesto niente, non
    aiutano. Si dice il candidato meno specifico (vedi
    `Matcher.il_piu_generico`) e si racconta subito.
    """

    def _amelie(self):
        return Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                     senza_voce=True, senza_modello=True))

    def test_dal_dubbio_si_va_dritti_al_racconto(self, monkeypatch):
        from amelie.matcher import Fatti, Livello
        a = self._amelie()
        try:
            dubbio = Fatti(livello=Livello.VINO, nome="Un vino", sicurezza=80.0,
                           riferimenti=[("denominazione", 1)])
            generico = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Una DOC",
                             sicurezza=80.0)
            monkeypatch.setattr(a.matcher, "cerca", lambda righe: dubbio)
            chiamate = []
            monkeypatch.setattr(a.matcher, "il_piu_generico",
                                lambda f, righe: chiamate.append(f) or generico)
            monkeypatch.setattr(a, "_avvia", lambda _f: None)
            a._righe = ["UN VINO"]
            a.macchina.stato = Stato.RICONOSCIMENTO
            a._riconosci()
            assert chiamate == [dubbio]
            assert a._fatti is generico
            assert a.macchina.stato is Stato.RACCONTO
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_un_riconoscimento_sicuro_non_si_tocca(self, monkeypatch):
        from amelie.matcher import Fatti, Livello
        a = self._amelie()
        try:
            certo = Fatti(livello=Livello.VINO, nome="Un vino", sicurezza=95.0,
                          riferimenti=[("denominazione", 1)])
            monkeypatch.setattr(a.matcher, "cerca", lambda righe: certo)
            monkeypatch.setattr(a.matcher, "il_piu_generico",
                                lambda f, righe: pytest.fail("non doveva scendere"))
            monkeypatch.setattr(a, "_avvia", lambda _f: None)
            a.macchina.stato = Stato.RICONOSCIMENTO
            a._riconosci()
            assert a._fatti is certo and a.macchina.stato is Stato.RACCONTO
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()
