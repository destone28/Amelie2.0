"""Il volume, e la schermata che copre l'accensione.

Due cose che si provano male a mano e benissimo qui: il volume perché il suo
difetto tipico — una scala che sembra lineare e non lo è, o un byte spaiato che
sfasa il PCM — non si vede, si sente; la schermata d'avvio perché il momento in
cui dovrebbe funzionare è l'unico in cui nessuno la sta guardando da uno
schermo con una tastiera davanti.
"""

import array
import math
import sys
from pathlib import Path

import pytest

from amelie.speech import (
    ImpostazioniVoce, Uscita, VOLUME_PREDEFINITO, guadagno_di, scala_pcm, tocco,
)

STATICI = Path(__file__).resolve().parents[1] / "src" / "amelie" / "ui" / "static"


def campioni(pcm: bytes) -> list[int]:
    a = array.array("h")
    a.frombytes(pcm)
    return list(a)


def onda(valore: int, n: int) -> bytes:
    return array.array("h", [valore] * n).tobytes()


class TestScala:
    """La curva del volume.

    Questa catena audio non ha un volume hardware — il suono esce dall'HDMI e i
    controlli del mixer stanno su un altro percorso — quindi la curva è tutto
    ciò che c'è, e sbagliarla si sente come un comando che non fa niente per
    mezza corsa e poi crolla.
    """

    def test_gli_estremi_sono_gli_estremi(self):
        assert guadagno_di(0) == 0.0
        assert guadagno_di(100) == 1.0

    def test_non_si_sale_mai_sopra_il_fondo_scala(self):
        """Amplificare oltre 0 dBFS taglierebbe le creste: non è disponibile."""
        for oltre in (101, 200, 10_000):
            assert guadagno_di(oltre) == 1.0

    def test_sotto_zero_e_silenzio(self):
        for sotto in (-1, -100):
            assert guadagno_di(sotto) == 0.0

    def test_meta_corsa_e_meno_dodici_decibel(self):
        """Che è ciò che l'orecchio chiama «metà volume».

        Con una scala lineare sull'ampiezza, metà corsa farebbe -6 dB, che si
        sente come «quasi uguale»: è il difetto che questa curva evita.
        """
        db = 20 * math.log10(guadagno_di(50))
        assert -12.5 < db < -11.5

    def test_un_decimo_di_corsa_e_un_filo_di_voce(self):
        assert -41 < 20 * math.log10(guadagno_di(10)) < -39


class TestGuadagnoSulPcm:
    def test_a_volume_pieno_i_byte_non_si_toccano(self):
        """Il caso normale non deve costare niente: stessi byte, stesso oggetto."""
        dati = onda(1000, 64)
        assert scala_pcm(dati, 1.0) is dati

    def test_a_zero_e_tutto_silenzio(self):
        dati = onda(30000, 64)
        fuori = scala_pcm(dati, 0.0)
        assert len(fuori) == len(dati)
        assert set(fuori) == {0}

    def test_meta_ampiezza_e_meta_campione(self):
        fuori = campioni(scala_pcm(onda(10000, 8), 0.5))
        assert fuori == [5000] * 8

    def test_un_byte_spaiato_non_sfasa_il_resto(self):
        """Buttarlo via sposterebbe di mezzo campione tutto ciò che segue.

        Il parlato diventerebbe fruscio, e la causa sarebbe invisibile: nel
        flusso vero i pezzi sono pari, quindi il difetto comparirebbe solo il
        giorno in cui qualcuno accoda una frase di lunghezza dispari.
        """
        dati = onda(10000, 4) + b"\x7f"
        fuori = scala_pcm(dati, 0.5)
        assert len(fuori) == len(dati)
        assert fuori[-1:] == b"\x7f"
        assert campioni(fuori[:-1]) == [5000] * 4

    def test_le_due_strade_dicono_la_stessa_cosa(self, monkeypatch):
        """Con numpy e senza. La seconda esiste per non rendere numpy
        obbligatorio a un modulo che deve solo parlare."""
        dati = array.array("h", [-30000, -1, 0, 1, 12345, 30000]).tobytes()
        con = scala_pcm(dati, 0.37)
        monkeypatch.setitem(sys.modules, "numpy", None)   # import -> ImportError
        senza = scala_pcm(dati, 0.37)
        # Le due strade arrotondano in modo diverso di al massimo un'unita' su
        # 32.768, che sono -90 dB: udibile da nessuno, ma va detto.
        for a, b in zip(campioni(con), campioni(senza)):
            assert abs(a - b) <= 1


class TestColpetto:
    """Il suono che fa sentire il livello a dispositivo fermo."""

    def test_dura_quanto_deve(self):
        assert len(campioni(tocco(durata_s=0.2, frequenza=22050))) == 4410

    def test_comincia_e_finisce_a_zero(self):
        """Un seno troncato di netto fa un click ai due capi, e su un
        amplificatore quel click è più forte della nota."""
        c = campioni(tocco())
        assert abs(c[0]) < 200
        assert abs(c[-1]) < 400

    def test_si_spegne_da_solo(self):
        c = [abs(v) for v in campioni(tocco())]
        assert max(c[: len(c) // 4]) > 4 * max(c[-len(c) // 8:])

    def test_non_arriva_mai_al_fondo_scala(self):
        """È un ritorno di comando, non un allarme."""
        assert max(abs(v) for v in campioni(tocco())) < 16000


class FintoStdin:
    def __init__(self):
        self.scritto = bytearray()

    def write(self, dati):
        self.scritto.extend(dati)

    def flush(self):
        pass

    def close(self):
        pass


class FintoProcesso:
    def __init__(self):
        self.stdin = FintoStdin()

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


class FintaVoce:
    """Quel tanto di Voce che serve a un'Uscita: le impostazioni e il guadagno."""

    def __init__(self, guadagno=1.0):
        self.imp = ImpostazioniVoce()
        self.guadagno = guadagno
        self.processo = FintoProcesso()

    def apri_uscita(self):
        return self.processo


class TestUscitaAbbassata:
    """Il guadagno si applica DOVE PASSA TUTTO.

    Non quando si accoda: lì lo prenderebbe solo ciò che viene scritto dopo, e
    un volume abbassato a metà racconto si sentirebbe alla frase seguente.
    """

    def _versa(self, guadagno, dati):
        voce = FintaVoce(guadagno)
        u = Uscita(voce)
        u.avvia()
        try:
            u.scrivi(dati)
            u.attendi_residuo(0.0, tetto_s=5.0)
        finally:
            u.chiudi()
        return voce.processo.stdin.scritto

    def test_il_volume_arriva_al_flusso(self):
        forte = self._versa(1.0, onda(20000, 22050 // 2))
        piano = self._versa(0.25, onda(20000, 22050 // 2))
        assert max(campioni(bytes(forte))) > 19000
        # A un quarto d'ampiezza, e nient'altro nel flusso che superi quel valore.
        assert 4000 < max(campioni(bytes(piano))) < 5600

    def test_il_silenzio_di_riempimento_resta_silenzio(self):
        """Non e' un dettaglio di prestazioni: moltiplicare il silenzio per il
        guadagno a ogni pezzo, per ore, è lavoro fatto per ottenere zero."""
        vuoto = self._versa(0.5, b"")
        assert set(bytes(vuoto)) <= {0}


class TestVoceVolume:
    def test_il_volume_si_regola_anche_a_flusso_chiuso(self):
        """Si imposta all'avvio, prima che esista un'uscita: se vivesse
        nell'uscita, il valore salvato andrebbe perso fino alla prima frase."""
        from amelie.speech import Voce

        v = Voce()
        assert v.volume == VOLUME_PREDEFINITO
        v.volume = 40
        assert v.volume == 40
        assert v.guadagno == pytest.approx(0.16)

    def test_si_ferma_agli_estremi(self):
        from amelie.speech import Voce

        v = Voce()
        v.volume = 500
        assert v.volume == 100
        v.volume = -3
        assert v.volume == 0


class TestVolumeDelDispositivo:
    """Il volume come lo vede l'orchestratore: si ricorda, si limita, si dice."""

    @pytest.fixture
    def amelie(self, tmp_path, monkeypatch):
        from amelie import app as modulo

        # Il file vero sta in `var/`, ed è quello del dispositivo: un test che
        # ci scrivesse dentro cambierebbe il volume della board su cui gira.
        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_parte_dal_predefinito_se_non_c_e_niente_di_salvato(self, amelie):
        assert amelie.volume == VOLUME_PREDEFINITO

    def test_si_ferma_agli_estremi(self, amelie):
        assert amelie.imposta_volume(-40) == 0
        assert amelie.imposta_volume(4000) == 100

    def test_si_ricorda_da_una_sera_all_altra(self, tmp_path, monkeypatch):
        """Chi apre il locale non deve ritarare il volume ogni sera."""
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        cfg = modulo.Configurazione(simula_mcu=True, senza_camera=True,
                                    senza_voce=True, senza_modello=True)
        prima = modulo.Amelie(cfg)
        prima.imposta_volume(30)
        prima.matcher.chiudi()
        prima.narratore.chiudi()

        dopo = modulo.Amelie(cfg)
        try:
            assert dopo.volume == 30
        finally:
            dopo.matcher.chiudi()
            dopo.narratore.chiudi()

    def test_un_file_illeggibile_costa_il_predefinito_non_l_avvio(
            self, tmp_path, monkeypatch):
        """Uno spegnimento a metà scrittura non deve impedire l'accensione."""
        from amelie import app as modulo

        rovinato = tmp_path / "volume"
        rovinato.write_text("mezzo\x00", encoding="utf-8")
        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", rovinato)
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        try:
            assert a.volume == VOLUME_PREDEFINITO
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()

    def test_lo_dice_a_tutte_le_pagine_aperte(self, amelie):
        """Due schermate aperte non possono mostrare due livelli diversi."""
        detti = []
        amelie._pubblica = detti.append
        amelie.imposta_volume(60)
        volume = [m for m in detti if m.get("tipo") == "volume"]
        assert volume and volume[-1]["valore"] == 60

    def test_senza_voce_il_comando_non_si_mostra(self, amelie):
        detti = []
        amelie._pubblica = detti.append
        amelie._manda_volume()
        assert detti[-1]["attivo"] is False


class TestSchermataDAvvio:
    """La schermata che copre i quaranta secondi dell'accensione.

    Va provata qui perché il momento in cui dovrebbe funzionare è l'unico in
    cui nessuno ha davanti uno schermo con una tastiera.
    """

    @pytest.fixture
    def avvio(self):
        return (STATICI / "avvio.html").read_text(encoding="utf-8")

    def test_non_dipende_da_niente_che_venga_da_fuori(self, avvio):
        """È un file, e compare quando il server non esiste ancora: un font o
        un foglio di stile remoto la lascerebbe muta proprio all'accensione."""
        import re

        indirizzi = re.findall(r"https?://[^\s\"')]+", avvio)
        assert all(u.startswith("http://127.0.0.1:8080") for u in indirizzi), \
            f"la schermata d'avvio dipende da fuori: {indirizzi}"

    def test_aspetta_il_dispositivo_pronto_non_il_server(self, avvio):
        """Fra il server che risponde e le voci caricate ci sono trenta
        secondi: andarsene troppo presto vuol dire un primo ospite muto."""
        assert "/pronto" in avvio and "pronta" in avvio

    def test_se_ne_va_senza_lasciare_traccia(self, avvio):
        assert "location.replace" in avvio

    def test_dice_qualcosa_se_ci_mette_troppo(self, avvio):
        """Un marchio fermo per cinque minuti non si distingue da un guasto."""
        assert "lento" in avvio

    def test_l_endpoint_che_aspetta_esiste_davvero(self):
        from amelie.app import Amelie, Configurazione, crea_app

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        try:
            percorsi = {r.path for r in crea_app(a).routes}
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()
        assert "/pronto" in percorsi
        assert "/volume/{valore}" in percorsi

    def test_pronta_solo_a_preparazione_finita(self):
        """Il flusso audio e le due voci: è il senso di tutta la schermata."""
        from amelie.app import Amelie, Configurazione

        a = Amelie(Configurazione(simula_mcu=True, senza_camera=True,
                                  senza_voce=True, senza_modello=True))
        try:
            assert a._pronta is False
            a._prepara()
            assert a._pronta is True
        finally:
            a.matcher.chiudi()
            a.narratore.chiudi()


class TestUnSoloColore:
    """Dal framebuffer alla prima frase non ci deve essere uno stacco.

    Il fondo del marchio è scritto in quattro posti — il sipario sul
    framebuffer, la radice di X, la schermata d'avvio, l'interfaccia — perché
    i quattro non possono leggersi a vicenda: uno è bash prima di X, uno è X,
    due sono pagine che vivono in momenti diversi. Questo test è ciò che tiene
    insieme le quattro copie.
    """

    FONDO = "3D1512"

    def _testo(self, *pezzi):
        radice = Path(__file__).resolve().parents[1]
        return [(p, (radice / p).read_text(encoding="utf-8")) for p in pezzi]

    def test_il_marchio_non_salta_al_passaggio(self):
        """Le due pagine centrano il marchio nello stesso punto solo se hanno
        la stessa interlinea: senza, il nome è alto diciotto pixel di meno, il
        gruppo si centra più in basso, e il marchio salta nell'istante esatto
        in cui la schermata d'avvio lascia il posto all'interfaccia — che è
        l'unico modo di accorgersi che sono due pagine."""
        import re
        radice = Path(__file__).resolve().parents[1]
        interlinee = {}
        for nome in ("index", "avvio"):
            testo = (radice / f"src/amelie/ui/static/{nome}.html").read_text(
                encoding="utf-8")
            regola = re.search(r"html, body \{(.*?)\}", testo, re.S)
            assert regola, f"{nome}.html non ha la regola di html, body"
            valore = re.search(r"line-height:\s*([\d.]+)", regola.group(1))
            assert valore, f"{nome}.html non dichiara un'interlinea"
            interlinee[nome] = valore.group(1)
        assert interlinee["index"] == interlinee["avvio"], \
            f"interlinee diverse: {interlinee} - il marchio salterebbe"

    def test_l_avvio_ha_la_stessa_impaginazione_dell_attesa(self):
        """Il marchio cade nello stesso punto solo se sotto di lui c'e' lo
        stesso ingombro: l'avvio tiene i tre passi dell'attesa, invisibili.
        Senza, il gruppo si centrerebbe piu' in basso di settanta pixel."""
        radice = Path(__file__).resolve().parents[1]
        avvio = (radice / "src/amelie/ui/static/avvio.html").read_text(encoding="utf-8")
        assert 'class="passi"' in avvio and "visibility: hidden" in avvio
        index = (radice / "src/amelie/ui/static/index.html").read_text(encoding="utf-8")
        # E il marchio e' lo stesso disegno, tracciato per tracciato.
        import re
        tracce = [re.search(r'<path class="parola" d="([^"]+)"', t).group(1)
                  for t in (index, avvio)]
        assert tracce[0] == tracce[1], "il marchio dell'avvio non e' quello dell'attesa"
        # E il calice sopra il nome, con la coppa che ne ritaglia il vino.
        coppe = [re.search(r'<clipPath id="coppa"><path d="([^"]+)"', t).group(1)
                 for t in (index, avvio)]
        assert coppe[0] == coppe[1], "il calice dell'avvio non e' quello dell'attesa"

    def test_lo_stesso_bordeaux_dappertutto(self):
        for nome, testo in self._testo(
                "src/amelie/ui/static/index.html",
                "src/amelie/ui/static/avvio.html",
                "scripts/systemd/amelie-sessione.sh",
                "scripts/systemd/amelie-sipario.sh"):
            assert self.FONDO in testo.upper(), \
                f"{nome} non usa il fondo del marchio: si vedrebbe uno stacco"


class TestAvanzamentoDelRacconto:
    """La barra del racconto non deve arretrare a ogni frase nuova.

    Dividere la posizione per `durata_s`, cioe' per i byte GIA' sintetizzati,
    non funziona: la sintesi corre al doppio del tempo reale, e per tutta la
    prima meta' del racconto il denominatore cresce quasi al doppio della
    velocita' del numeratore. Dentro una frase il rapporto sale, all'arrivo
    della frase dopo precipita.

    Misurato su un racconto ricomposto da frasi con audio vero - otto frasi per
    16,8 secondi - quel conto fa **sette arretramenti, il peggiore di 43,9
    punti**, e a due secondi dall'inizio segna gia' il 56%.
    """

    @staticmethod
    def _riproduttore(frasi):
        from amelie.speech import Riproduttore

        class UscitaFinta:
            def svuota(self): pass
            def scrivi(self, dati): pass
            def in_pancia_s(self): return 0.0
            def attendi_fine(self, tetto=10.0): pass

        class VoceFinta:
            class imp:
                modello = "it_IT-serena-medium"
                frequenza = 22050

            def uscita(self):
                return UscitaFinta()

        return Riproduttore(VoceFinta(), frasi)

    @staticmethod
    def _accoda(r, secondi):
        """Aggiunge una frase gia' sintetizzata, come fa il thread di sintesi."""
        from amelie.speech import byte_al_secondo

        r._inizi.append(len(r._pcm))
        r._pcm.extend(b"\x00" * int(secondi * byte_al_secondo(22050)))

    FRASI = ["Questo è un Barolo.",
             "Nasce da uve Nebbiolo nelle Langhe, in Piemonte.",
             "Ha corpo pieno e tannini fitti.",
             "Si accompagna a brasati e formaggi stagionati.",
             "Si serve fra 16 e 18 gradi."]
    DURATE = [2.1, 4.4, 2.6, 4.0, 2.2]

    def _ascolta(self, r):
        """Simula l'ascolto: una frase si sintetizza, poi la si sente."""
        from amelie.speech import byte_al_secondo

        bps = byte_al_secondo(22050)
        quote = []
        for i, sec in enumerate(self.DURATE):
            self._accoda(r, sec)
            for k in range(int(sec / 0.1)):
                r._posizione = r._inizi[i] + int((k + 1) * 0.1 * bps)
                quote.append(r.quota)
        return quote

    def test_non_arretra_mai_ascoltando(self):
        r = self._riproduttore(self.FRASI)
        quote = self._ascolta(r)
        arretra = [(a, b) for a, b in zip(quote, quote[1:]) if b < a - 1e-9]
        assert not arretra, f"la barra e' tornata indietro {len(arretra)} volte"

    def test_arriva_in_fondo_alla_fine(self):
        r = self._riproduttore(self.FRASI)
        self._ascolta(r)
        r._completo = True
        r._posizione = len(r._pcm)
        assert r.quota == pytest.approx(1.0)

    def test_non_arriva_in_fondo_prima_della_voce(self):
        """L'altro modo di sbagliare, in un caso su quattro.

        Quando la riproduzione raggiunge la sintesi, la posizione finisce
        esattamente sull'ultimo byte esistente: dividendo per i byte
        sintetizzati fa uno tondo, e la barra andrebbe a fondo scala a meta'
        racconto per poi crollare.
        """
        r = self._riproduttore(self.FRASI)
        self._accoda(r, self.DURATE[0])
        r._posizione = len(r._pcm)           # la voce ha raggiunto la sintesi
        assert r.quota < 0.9, f"barra a {r.quota:.2f} con una frase su cinque"

    def test_la_pausa_puo_farla_arretrare(self):
        """L'unico movimento all'indietro che una barra debba fare.

        La pausa riavvolge di circa tre quarti di secondo per non tagliare una
        parola alla ripresa, e la barra deve seguirla.
        """
        r = self._riproduttore(self.FRASI)
        self._ascolta(r)
        prima = r.quota
        r._posizione = int(len(r._pcm) * 0.5)
        r._quota_vista = 0.0                 # come fanno pausa, salta, ricomincia
        assert r.quota < prima

    def test_da_capo_riporta_a_zero(self):
        r = self._riproduttore(self.FRASI)
        self._ascolta(r)
        r.ricomincia()
        assert r.quota == pytest.approx(0.0)

    def test_una_sintesi_rotta_a_meta_arriva_lo_stesso_in_fondo(self):
        """`_completo` diventa vero anche quando la sintesi si rompe.

        Restano meno frasi di quelle previste, e il racconto finisce dove e'
        arrivato. Continuando a contare le frasi mai sintetizzate la barra
        resterebbe inchiodata a due terzi per sempre, mentre lo schermo va
        avanti.
        """
        r = self._riproduttore(self.FRASI)
        for sec in self.DURATE[:3]:
            self._accoda(r, sec)
        r._completo = True                   # rotta dopo tre frasi su cinque
        r._posizione = len(r._pcm)
        assert r.quota == pytest.approx(1.0)


class TestZittire:
    """Svuotare la coda non basta a far tacere chi sta parlando.

    Se `zittisci()` buttasse soltanto via cio' che non e' ancora uscito, chi
    aspetta spazio per accodare la frase successiva si sveglierebbe sulla coda
    ora vuota e la farebbe sentire. Un annuncio di lingua e' di DUE frasi:
    zittendolo a meta' si sentirebbe la seconda per intero - piu' di due
    secondi - sopra la schermata d'invito.
    """

    @staticmethod
    def _voce():
        from amelie.speech import Voce

        v = Voce.__new__(Voce)
        import threading
        v._lock = threading.Lock()
        v._silenzi = 0
        v._uscita = None
        return v

    def test_chi_parla_si_accorge_di_essere_zittito(self):
        v = self._voce()
        mio = v._silenzi
        v.zittisci()
        assert v._silenzi != mio, \
            "senza contatore, il ciclo delle frasi non ha modo di accorgersene"

    def test_ogni_silenzio_conta(self):
        v = self._voce()
        v.zittisci()
        v.zittisci()
        assert v._silenzi == 2

    def test_zittire_a_meta_ferma_la_frase_dopo(self):
        """Il caso vero: il silenzio arriva mentre la prima frase e' in coda.

        E' quello che succede toccando «annulla» durante l'annuncio della
        lingua: la prima frase e' gia' passata all'uscita, la seconda no. Senza
        il contatore dei silenzi uscirebbe lo stesso, perche' `svuota` libera
        la coda e chi aspetta spazio si sveglia e accoda.
        """
        from amelie.speech import Voce

        v = self._voce()
        sintetizzate, inviate = [], []

        class UscitaFinta:
            def scrivi(self, dati):
                inviate.append(dati)
                # Il tocco arriva mentre la prima frase e' appena entrata.
                if len(inviate) == 1:
                    v.zittisci()

            def svuota(self):
                pass

            def attendi_residuo(self, secondi):
                pass

        v.sintetizza = lambda f: (sintetizzate.append(f) or b"\x00" * 100)
        v.uscita = lambda: UscitaFinta()
        v._attendi_uscita = lambda u: None
        v._byte_al_secondo = lambda: 44100

        Voce.parla(v, ["Lingua italiana.", "Da adesso racconto i vini in italiano."])
        assert sintetizzate == ["Lingua italiana."], (
            f"ha continuato dopo il silenzio: {sintetizzate}")
        assert len(inviate) == 1


class TestStimaDellaVoce:
    def test_si_stima_su_cio_che_si_pronuncia(self):
        """«DOCG» sono quattro caratteri e quarantotto suoni.

        `per_la_voce` scioglie le sigle prima della sintesi. Stimare sul testo
        scritto sbaglia di piu' del doppio, e proprio sulle frasi d'apertura -
        quelle che si sentono per prime.
        """
        from amelie.speech import byte_stimati

        sigla = byte_stimati("Un Barolo DOCG.", "it_IT-serena-medium")
        piano = byte_stimati("Un Barolo rosso.", "it_IT-serena-medium")
        assert sigla > piano * 2

    def test_una_frase_che_non_si_pronuncia_non_dura(self):
        """`sintetizza` restituisce b"" nello stesso caso: devono concordare.

        Sono i soli spazi, non la punteggiatura: «...» il motore lo pronuncia
        eccome, come una pausa.
        """
        from amelie.speech import byte_stimati

        assert byte_stimati("   ", "it_IT-serena-medium") == 0
        assert byte_stimati("", "it_IT-serena-medium") == 0

    def test_ogni_voce_ha_il_suo_ritmo(self):
        """Misurati sintetizzando davvero, 90 frasi per voce.

        Non dalla cache: i quattordici file inglesi in cache danno un'altra
        costante, e sbagliata.
        """
        from amelie.speech import CARATTERI_AL_SECONDO, VOCI

        for modello in VOCI.values():
            assert modello in CARATTERI_AL_SECONDO, f"{modello} senza ritmo misurato"

    def test_una_cifra_dura_piu_di_un_carattere(self):
        """«1990» sono quattro segni e Piper dice «millenovecentonovanta».

        Non e' un caso di bordo: annata, temperatura e gradazione chiudono
        quasi ogni racconto, cioe' sono proprio la coda che la stima deve
        coprire. Contandole per quattro, l'errore mediano su quelle frasi e'
        del 27% in italiano; col peso misurato scende al 3,2%.
        """
        from amelie.speech import byte_stimati

        con_cifre = byte_stimati("Annata 1990.", "it_IT-serena-medium")
        senza = byte_stimati("Annata rossa.", "it_IT-serena-medium")
        assert con_cifre > senza * 1.5

    def test_il_ripiego_sta_fra_le_due(self):
        from amelie.speech import CARATTERI_AL_SECONDO, CARATTERI_AL_SECONDO_RIPIEGO

        misurate = list(CARATTERI_AL_SECONDO.values())
        assert min(misurate) <= CARATTERI_AL_SECONDO_RIPIEGO <= max(misurate)


class TestIlModoDiRaccontare:
    """Il selettore di dove viene quello che il dispositivo dice.

    Sta nello stesso file dei test del volume perché è la stessa cosa: una
    scelta di chi apre il locale, che deve sopravvivere alla spina staccata.

    Tre modi, e la differenza fra loro non è di stile: è la FONTE. L'archivio
    compone dai dati del registro; la generativa fa scrivere al modello quegli
    stessi dati; la carta legge un file scritto a mano. Accanto al selettore
    c'e' un interruttore a due posizioni, `imposta_generati`, come scorciatoia
    fra archivio e generativa.
    """

    @pytest.fixture
    def amelie(self, tmp_path, monkeypatch):
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        monkeypatch.setattr(modulo, "PERCORSO_GENERATI", tmp_path / "generati")
        monkeypatch.setattr(modulo, "PERCORSO_MODO", tmp_path / "modo")
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        yield a
        a.matcher.chiudi()
        a.narratore.chiudi()

    def test_dall_archivio_di_partenza(self, amelie):
        """Un dispositivo appena acceso deve rispondere subito."""
        assert amelie.modo == "archivio"
        assert amelie.genera_racconti is False

    def test_un_modo_che_non_si_puo_servire_si_rifiuta(self, amelie):
        """Senza modello caricato non si può scrivere sul momento, e dirlo è
        meglio che accettare e poi raccontare qualcos'altro."""
        esito = amelie.imposta_modo("generativa")
        assert esito["ok"] is False
        assert amelie.modo == "archivio"

    def test_e_nemmeno_uno_che_non_esiste(self, amelie):
        assert amelie.imposta_modo("fantasia")["ok"] is False

    def test_col_modello_la_generativa_si_accende(self, tmp_path, monkeypatch):
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        monkeypatch.setattr(modulo, "PERCORSO_MODO", tmp_path / "modo")
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        try:
            a.narratore.genera = lambda _p: "x"      # un modello finto, ma c'e'
            assert a.imposta_modo("generativa")["ok"] is True
            assert a.genera_racconti is True
            assert a.imposta_generati(False)["ok"] is True
            assert a.modo == "archivio"
        finally:
            a.matcher.chiudi(); a.narratore.chiudi()

    def test_si_ricorda_da_una_sera_all_altra(self, tmp_path, monkeypatch):
        from amelie import app as modulo

        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        monkeypatch.setattr(modulo, "PERCORSO_MODO", tmp_path / "modo")
        cfg = modulo.Configurazione(simula_mcu=True, senza_camera=True,
                                    senza_voce=True, senza_modello=True)
        prima = modulo.Amelie(cfg)
        prima.narratore.genera = lambda _p: "x"
        prima.imposta_modo("generativa")
        prima.matcher.chiudi(); prima.narratore.chiudi()

        dopo = modulo.Amelie(cfg)
        try:
            # Il modo salvato c'e', ma il modello no: non si resta muti, si
            # torna all'archivio, che c'e' sempre.
            assert dopo.modo == "archivio"
        finally:
            dopo.matcher.chiudi(); dopo.narratore.chiudi()

    def test_un_file_illeggibile_costa_le_impostazioni_non_l_avvio(
            self, tmp_path, monkeypatch):
        """Come per il volume: un file rovinato non deve impedire di accendere."""
        from amelie import app as modulo

        rovinato = tmp_path / "modo"
        rovinato.mkdir()                       # una cartella al posto del file
        monkeypatch.setattr(modulo, "PERCORSO_VOLUME", tmp_path / "volume")
        monkeypatch.setattr(modulo, "PERCORSO_MODO", rovinato)
        monkeypatch.setattr(modulo, "PERCORSO_GENERATI", tmp_path / "generati")
        a = modulo.Amelie(modulo.Configurazione(
            simula_mcu=True, senza_camera=True, senza_voce=True,
            senza_modello=True))
        try:
            assert a.modo == "archivio"
        finally:
            a.matcher.chiudi(); a.narratore.chiudi()

    def test_si_mostrano_solo_i_modi_servibili(self, amelie):
        """Un comando che non fa niente è peggio di nessun comando."""
        visti = []
        amelie._pubblica = lambda m: visti.append(m)
        amelie._manda_impostazioni()
        assert visti[-1]["modi"] == ["archivio"]
        assert visti[-1]["modo"] == "archivio"

    def test_il_narratore_riceve_il_modo(self, amelie):
        """La scelta deve arrivare fino a `racconta`, non fermarsi qui."""
        from amelie.matcher import Fatti, Livello

        chiesto = {}
        amelie._fatti = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"])

        def finto(f, **kw):
            chiesto.update(kw)
            from amelie.narrator import Racconto
            return Racconto(testo="x.", origine="template", livello=f.livello)

        amelie.narratore.racconta = finto
        amelie.narratore.genera = lambda _p: "x"
        amelie.imposta_modo("generativa")
        amelie._racconta()
        assert chiesto["preferisci_modello"] is True


class TestLaPronunciaSegueLaLingua:
    """Ogni lingua ha la sua tabella di pronuncia. Con una sola, italiana,
    applicata a qualunque voce, in inglese «DOCG» diventerebbe «denominazione
    di origine controllata e garantita», e la voce inglese lo compiterebbe
    all'inglese."""

    def test_in_inglese_la_sigla_si_scioglie_in_inglese(self):
        from amelie.speech import per_la_voce

        detto = per_la_voce("A Barolo DOCG at 14%.", "en")
        assert "denominazione" not in detto
        assert "designation of origin" in detto
        assert "percent" in detto

    def test_in_italiano_la_sigla_si_scioglie_in_italiano(self):
        from amelie.speech import per_la_voce

        assert "denominazione di origine controllata e garantita" in per_la_voce(
            "Un Barolo DOCG.")

    def test_l_intervallo_si_congiunge_nella_lingua_giusta(self):
        """«Serve at 8 e 10 degrees»: una parola italiana in una frase inglese."""
        from amelie.speech import per_la_voce

        assert "8 to 10" in per_la_voce("Serve at 8-10 degrees.", "en")
        assert "8 e 10" in per_la_voce("Si serve fra 8-10 gradi.", "it")

    def test_il_decimale_italiano_ha_la_virgola(self):
        """«13.0» si sente «tredici punto zero»."""
        from amelie.speech import per_la_voce

        assert "13,5" in per_la_voce("Ha 13.5% di alcol.", "it")
        assert "13.5" in per_la_voce("It has 13.5% alcohol.", "en")

    def test_le_migliaia_non_sono_un_decimale(self):
        """«1.500 metri» non diventa «millecinquecento virgola»."""
        from amelie.speech import per_la_voce

        assert "1.500" in per_la_voce("Sale a 1.500 metri.", "it")

    def test_i_nomi_francesi_non_si_riscrivono_per_la_voce_inglese(self):
        """«sciardonè» serve a una voce italiana; a una inglese fa solo danno."""
        from amelie.speech import per_la_voce

        assert per_la_voce("A Chardonnay.", "en") == "A Chardonnay."

    def test_la_lingua_si_legge_dal_nome_della_voce(self):
        from amelie.speech import lingua_del_modello

        assert lingua_del_modello("en_US-ljspeech-medium") == "en"
        assert lingua_del_modello("it_IT-serena-medium") == "it"
        assert lingua_del_modello("") == "it"
