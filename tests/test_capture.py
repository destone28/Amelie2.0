"""Test delle funzioni pure di cattura.

L'apertura del device non è testabile senza hardware: qui si verificano il
ritaglio e la misura di nitidezza, che sono le due cose che possono sbagliare
in silenzio.
"""

import numpy as np
import pytest

from amelie.capture import (
    ImpostazioniCamera,
    PresenzaOttica,
    Scatto,
    SOGLIA_NITIDEZZA,
    nitidezza,
    quanto_diverso,
    ritaglia_centro,
)


def immagine(h=100, w=200, valore=128):
    return np.full((h, w, 3), valore, dtype=np.uint8)


def immagine_a_scacchi(h=100, w=200, passo=4):
    """Molto contrasto locale: nitidezza alta."""
    yy, xx = np.mgrid[0:h, 0:w]
    piano = (((yy // passo) + (xx // passo)) % 2 * 255).astype(np.uint8)
    return np.dstack([piano] * 3)


class TestRitaglio:
    def test_dimensioni(self):
        out = ritaglia_centro(immagine(100, 200), 0.5)
        assert out.shape[:2] == (50, 100)

    def test_e_centrato(self):
        img = immagine(100, 100, valore=0)
        img[40:60, 40:60] = 255            # macchia bianca al centro
        out = ritaglia_centro(img, 0.5)    # tiene 50x50 centrali
        assert out.shape[:2] == (50, 50)
        assert out[25, 25, 0] == 255       # il centro è ancora al centro

    def test_frazione_uno_non_taglia(self):
        img = immagine(30, 40)
        assert ritaglia_centro(img, 1.0).shape == img.shape

    @pytest.mark.parametrize("frazione", [0, -0.1, 1.5])
    def test_frazione_non_valida(self, frazione):
        with pytest.raises(ValueError):
            ritaglia_centro(immagine(), frazione)

    def test_le_due_frazioni_sono_indipendenti(self):
        """Una bottiglia non è quadrata, e il ritaglio non deve esserlo."""
        out = ritaglia_centro(immagine(100, 200), 0.5, 1.0)
        assert out.shape[:2] == (100, 100)

    def test_una_frazione_sola_vale_per_tutti_e_due_i_lati(self):
        out = ritaglia_centro(immagine(100, 200), 0.5)
        assert out.shape[:2] == (50, 100)

    def test_il_ritaglio_e_alto_e_stretto_come_una_bottiglia(self):
        """I due mestieri del ritaglio stanno su assi diversi.

        In larghezza si stringe per buttare fuori la stanza, che il rilevatore
        legge come testo; in altezza si tiene quasi tutto, perché è lì che sta
        l'etichetta. Misurato con la camera in piedi, stessa bottiglia: a
        0,70 × 0,95 sparisce «MOLISE» — che è il calendario appeso dietro, non
        la bottiglia — e restano `Leggiadro · Brut Rosé · METODO CLASSICO`.
        A 0,60 comincia a sfaldarsi la parola sull'etichetta.
        """
        imp = ImpostazioniCamera()
        assert imp.ritaglio_alto > imp.ritaglio_largo, (
            "una bottiglia e' alta e stretta, e il ritaglio deve seguirla")
        assert imp.ritaglio_largo >= 0.65, "sotto questo si sfaldano le parole"
        assert imp.ritaglio_alto >= 0.90, "e' in altezza che sta l'etichetta"

    def test_la_camera_e_montata_di_lato(self):
        """Una bottiglia è alta e stretta, e un sensore 16:9 girato di fianco
        la inquadra per il lungo.

        Il fotogramma nativo ha la bottiglia coricata col collo a sinistra: qui
        si rimette in piedi. Misurato sulla stessa bottiglia e sullo stesso
        fotogramma, a 90° si leggono otto righe fra cui `Leggiadro`,
        `Brut Rosé` e `METODO CLASSICO`, tutte dentro al fotogramma; dritta
        (0°) la denominazione cadeva sotto il bordo.
        """
        assert ImpostazioniCamera().rotazione in (0, 90, 180, 270)
        assert ImpostazioniCamera().rotazione == 90

    def test_raddrizzare_scambia_i_lati(self):
        from amelie.capture import Camera

        c = Camera(ImpostazioniCamera(rotazione=90))
        alto = c._raddrizza(immagine(40, 90))
        assert alto.shape[:2] == (90, 40), "novanta gradi scambiano i lati"
        fermo = Camera(ImpostazioniCamera(rotazione=0))
        assert fermo._raddrizza(immagine(40, 90)).shape[:2] == (40, 90)


class TestNitidezza:
    def test_uniforme_e_piatta(self):
        assert nitidezza(immagine()) == pytest.approx(0.0, abs=1e-6)

    def test_scacchi_piu_nitidi_di_uniforme(self):
        assert nitidezza(immagine_a_scacchi()) > nitidezza(immagine())

    def test_sfocare_abbassa_la_nitidezza(self):
        import cv2

        netta = immagine_a_scacchi()
        sfocata = cv2.GaussianBlur(netta, (9, 9), 0)
        assert nitidezza(sfocata) < nitidezza(netta)

    def test_restituisce_float(self):
        assert isinstance(nitidezza(immagine_a_scacchi()), float)


class TestScatto:
    def test_sospetto_mosso_sotto_soglia(self):
        s = Scatto(immagine=immagine(), nitidezza=SOGLIA_NITIDEZZA - 1)
        assert s.sospetto_mosso

    def test_non_sospetto_sopra_soglia(self):
        s = Scatto(immagine=immagine(), nitidezza=SOGLIA_NITIDEZZA + 1)
        assert not s.sospetto_mosso


class TestImpostazioni:
    def test_scarta_prima_di_tenere(self):
        """Il buffer UVC contiene fotogrammi precedenti alla luce: senza scarto
        si legge un'immagine al buio.

        Erano cinque, scelti quando un fotogramma costava 30 ms. A 90 ms
        costavano un secondo intero, e la scena è ferma: lo scarto serve a
        svuotare il buffer, non a mediare, e tre bastano.
        """
        imp = ImpostazioniCamera()
        assert imp.fotogrammi_da_scartare >= 3

    def test_immutabile(self):
        with pytest.raises(Exception):
            ImpostazioniCamera().esposizione = 999


class TestQuantoDiverso:
    """La metrica deve distinguere «è cambiata la scena» da «è cambiata la luce».

    I numeri di riferimento sono quelli misurati sul dispositivo, sulla fascia
    vera, con la bottiglia al suo posto: vedi il docstring di `quanto_diverso`.
    """

    @staticmethod
    def scena(seme=0):
        r = np.random.default_rng(seme)
        return r.integers(0, 255, (128, 96)).astype(np.float32)

    def test_la_stessa_scena_non_e_cambiata(self):
        a = self.scena()
        assert quanto_diverso(a, a.copy()) == 0.0

    def test_un_po_di_rumore_non_e_un_cambiamento(self):
        a = self.scena()
        r = np.random.default_rng(1)
        b = np.clip(a + r.normal(0, 3, a.shape), 0, 255)
        assert quanto_diverso(a, b) < 0.05

    def test_la_luce_che_cala_non_e_una_bottiglia(self):
        """Il caso per cui la normalizzazione esiste: senza, l'80 % dei pixel
        risultava cambiato abbassando la luce del 20 %, a scena identica."""
        a = self.scena()
        for fattore in (0.7, 0.85, 1.15):
            assert quanto_diverso(a, a * fattore) < 0.05, fattore
        assert quanto_diverso(a, a - 40) < 0.05

    def test_una_scena_diversa_e_diversa(self):
        assert quanto_diverso(self.scena(0), self.scena(1)) > 0.5

    def test_una_fascia_senza_contrasto_si_giudica_sulla_luce(self):
        """Un muro bianco non si può normalizzare: dividere per la propria
        deviazione vorrebbe dire moltiplicare il rumore per il suo inverso."""
        piatta = np.full((128, 96), 100.0, dtype=np.float32)
        assert quanto_diverso(piatta, piatta + 1) == 0.0
        assert quanto_diverso(piatta, piatta + 60) == 1.0

    def test_due_fasce_di_forma_diversa_sono_un_errore(self):
        with pytest.raises(ValueError):
            quanto_diverso(self.scena(), np.zeros((64, 48), dtype=np.float32))


class TestPresenzaOttica:
    """Arrivo, permanenza e partenza di una bottiglia vista dalla camera."""

    @staticmethod
    def vuoto(seme=0):
        return np.random.default_rng(seme).integers(0, 255, (128, 96)).astype(np.float32)

    @staticmethod
    def con_bottiglia(seme=99):
        return np.random.default_rng(seme).integers(0, 255, (128, 96)).astype(np.float32)

    def posa(self, p, fascia, volte=6):
        for _ in range(volte):
            fuori = p.aggiorna(fascia)
        return fuori

    def test_il_piatto_vuoto_resta_vuoto(self):
        p = PresenzaOttica()
        assert self.posa(p, self.vuoto()) is False

    def test_una_bottiglia_posata_si_vede(self):
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        assert self.posa(p, self.con_bottiglia()) is True

    def test_e_quando_viene_tolta_si_vede_che_non_c_e_piu(self):
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        self.posa(p, self.con_bottiglia())
        assert self.posa(p, self.vuoto()) is False

    def test_la_luce_che_cambia_non_e_una_bottiglia(self):
        """Il locale abbassa le luci a cena: il dispositivo non deve svegliarsi."""
        p = PresenzaOttica()
        vuoto = self.vuoto()
        self.posa(p, vuoto)
        assert self.posa(p, vuoto * 0.7) is False

    def test_una_bottiglia_spostata_non_e_una_bottiglia_tolta(self):
        """Qualcuno versa da bere e riappoggia la bottiglia un dito piu' in la'.

        La scena non somiglia piu' a quella di prima, ma non somiglia nemmeno
        al piatto vuoto: il racconto non si interrompe. E' la stessa isteresi
        asimmetrica del sensore di distanza, per la stessa ragione.
        """
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        self.posa(p, self.con_bottiglia())
        spostata = np.roll(self.con_bottiglia(), 3, axis=1)
        assert self.posa(p, spostata) is True

    def test_una_mano_che_si_muove_non_fa_decidere(self):
        """Ogni sbirciata diversa dalla precedente: non si giudica mai."""
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        for k in range(8):
            fuori = p.aggiorna(self.con_bottiglia(seme=100 + k))
        assert fuori is False

    def test_lo_sfondo_si_aggiorna_quando_il_piatto_e_vuoto(self):
        """La sala cambia lentamente e lo sfondo la deve seguire, altrimenti
        una tovaglia nuova diventa una bottiglia per sempre."""
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        for passo in range(10):                      # la luce cala piano
            self.posa(p, self.vuoto() * (1 - 0.03 * passo), volte=3)
        assert p.presente is False

    def test_acceso_con_la_bottiglia_gia_posata(self):
        """Il caso che il sensore di distanza non aveva: la prima sbirciata
        impara la bottiglia come se fosse lo sfondo. Lo dice l'OCR, e quando lo
        dice si butta via lo sfondo sbagliato."""
        p = PresenzaOttica()
        bottiglia = self.con_bottiglia()
        assert self.posa(p, bottiglia) is False      # creduta sfondo
        p.c_e_qualcosa()                             # l'etichetta e' stata letta
        assert p.presente is True
        assert self.posa(p, bottiglia) is True       # finche' resta li', c'e'
        assert self.posa(p, self.vuoto()) is False   # tolta: ora si sa il vuoto
        assert self.posa(p, self.con_bottiglia(7)) is True   # e si riparte

    def test_reimposta_dimentica_tutto(self):
        p = PresenzaOttica()
        self.posa(p, self.vuoto())
        self.posa(p, self.con_bottiglia())
        p.reimposta()
        assert p.presente is False
        assert self.posa(p, self.con_bottiglia()) is False   # ora e' lo sfondo


class TestLaPosaSiCerca:
    """La posa fissa era fissa alla stanza in cui è stata misurata.

    Misurato sul dispositivo, al buio, con l'anello bianco: a posa 900 l'OCR
    non leggeva NIENTE; a 3000 leggeva la denominazione. Una sala che la sera
    abbassa le luci è la condizione normale, non un caso limite.
    """

    class CameraFinta:
        """Una camera in cui la luce segue la posa come su quella vera.

        `luce ∝ posa^0,54`, misurata: 900→47, 2000→73, 3000→89, 4000→99. E la
        posa nuova si vede solo dopo tre fotogrammi, anche questo misurato.
        """

        def __init__(self, posa=900, ritardo=3, esponente=0.54, sorda=False):
            self.posa = self.in_arrivo = posa
            self.ritardo, self.esponente = ritardo, esponente
            self.coda = 0
            self.letti = 0
            self.sorda = sorda      # una camera che ignora la posa nuova

        def imposta(self, posa):
            if self.sorda:
                return
            self.in_arrivo, self.coda = posa, self.ritardo

        def _avanza(self):
            if self.coda:
                self.coda -= 1
                if not self.coda:
                    self.posa = self.in_arrivo

        def grab(self):
            self._avanza()
            return True

        def read(self):
            self._avanza()
            self.letti += 1
            luce = 47.0 * (self.posa / 900.0) ** self.esponente
            return True, np.full((100, 200, 3), min(255, luce), dtype=np.uint8)

    def cerca(self, partenza=900, sorda=False, ritardo=3, **extra):
        from amelie.capture import Camera

        imp = ImpostazioniCamera(esposizione=partenza, ritaglio_largo=1.0,
                                 ritaglio_alto=1.0, **extra)
        c = Camera(imp)
        c._percorso = "/dev/finto"
        finta = self.CameraFinta(posa=partenza, sorda=sorda, ritardo=ritardo)
        applicate = []

        import amelie.capture as modulo
        vero = modulo.imposta_posa
        modulo.imposta_posa = lambda _d, p: (applicate.append(p), finta.imposta(p))
        try:
            luce = c._cerca_la_posa(finta)
        finally:
            modulo.imposta_posa = vero
        return c, finta, applicate, luce

    def test_al_buio_la_posa_sale_e_la_luce_arriva_a_bersaglio(self):
        c, _, applicate, luce = self.cerca(900)
        assert applicate, "da 47 di luce non ha corretto niente"
        atteso = ImpostazioniCamera().luce_cercata
        assert abs(luce - atteso) <= ImpostazioniCamera().luce_tollerata
        assert c.imp.esposizione > 900

    def test_in_piena_luce_la_posa_scende(self):
        """Il ritocco va nei due versi: in una sala illuminata la raffica
        finisce per costare meno di prima, non di più."""
        c, _, applicate, _ = self.cerca(4000)
        assert applicate and applicate[-1] < 4000
        assert c.imp.esposizione < 4000

    def test_se_la_luce_e_gia_giusta_non_si_tocca_niente(self):
        """La seconda bottiglia della sera: un fotogramma e via."""
        c, finta, applicate, _ = self.cerca(2900)
        assert applicate == [], "ha corretto una posa che andava bene"
        assert finta.letti == 1, "un fotogramma solo per dire che va bene"
        assert c.imp.esposizione == 2900

    def test_non_si_esce_dagli_estremi(self):
        """Sotto il minimo non si legge nemmeno di giorno; sopra il massimo la
        raffica dura più del racconto."""
        imp = ImpostazioniCamera()
        c, _, applicate, _ = self.cerca(900)
        for p in applicate:
            assert imp.posa_minima <= p <= imp.posa_massima

    def test_il_ritardo_del_driver_non_manda_la_correzione_al_tetto(self):
        """Il difetto vero, e costava il tetto ogni volta.

        Il driver applica la posa nuova dopo tre fotogrammi. Chi rimisura prima
        legge ancora la posa vecchia, corregge una seconda volta nello stesso
        verso, e finisce contro l'estremo qualunque fosse la luce.
        """
        c, _, applicate, _ = self.cerca(900)
        assert applicate[-1] < ImpostazioniCamera().posa_massima, (
            "la ricerca e' finita contro il tetto: sta rimisurando la posa vecchia")

    def test_con_un_ritardo_lungo_si_aspetta_invece_di_contare(self):
        """Contare i fotogrammi funziona finché il ritardo è quello misurato.
        Nel servizio, dove lo stream sta fermo fra una sbirciata e l'altra, non
        lo era: si guarda la luce, e si corregge solo dopo averla vista muovere.
        """
        c, _, applicate, luce = self.cerca(900, ritardo=5)
        imp = ImpostazioniCamera()
        assert abs(luce - imp.luce_cercata) <= imp.luce_tollerata
        assert applicate[-1] < imp.posa_massima

    def test_una_posa_che_non_arriva_al_sensore_ferma_la_ricerca(self):
        """Se la luce non si muove, la posa non sta arrivando: si smette.
        Insistere vuol dire sommare correzioni su una misura mai verificata, e
        finire contro il tetto senza che nessuno se ne accorga."""
        c, _, applicate, _ = self.cerca(900, sorda=True)
        assert len(applicate) == 1, "ha corretto di nuovo senza aver verificato"
        assert applicate[0] < ImpostazioniCamera().posa_massima

    def test_una_camera_che_non_da_fotogrammi_non_blocca_lo_scatto(self):
        from amelie.capture import Camera

        class Muta:
            def read(self): return False, None
            def grab(self): return False

        c = Camera(ImpostazioniCamera())
        c._percorso = "/dev/finto"
        assert c._cerca_la_posa(Muta()) == 0.0


class TestLoSfondoSiRicorda:
    """Il piatto vuoto è una proprietà dell'installazione, non del processo."""

    @staticmethod
    def fascia(seme=0):
        return np.random.default_rng(seme).integers(0, 255, (128, 96)).astype(np.float32)

    def test_ripartire_da_uno_sfondo_conosciuto(self):
        """Senza, un dispositivo acceso con la bottiglia già posata impara
        quella come sfondo e resta fermo a guardarla per sempre."""
        p = PresenzaOttica()
        p.ricorda(self.fascia(0))
        assert p.presente is False
        for _ in range(6):
            fuori = p.aggiorna(self.fascia(9))      # la bottiglia, gia' li'
        assert fuori is True

    def test_lo_sfondo_non_si_offre_mentre_c_e_una_bottiglia(self):
        """Salvare lo sfondo con la bottiglia davanti vuol dire non vederla
        mai più, nemmeno dopo un riavvio."""
        p = PresenzaOttica()
        for _ in range(6):
            p.aggiorna(self.fascia(0))
        assert p.sfondo is not None
        for _ in range(6):
            p.aggiorna(self.fascia(9))
        assert p.presente and p.sfondo is None

    def test_tre_letture_a_vuoto_rimettono_a_posto_lo_sfondo(self):
        """L'uscita di sicurezza: se lo sfondo è sbagliato la differenza resta
        alta per sempre, e il dispositivo crede di avere davanti qualcosa che
        non c'è. Tre scansioni senza una parola dicono che non è così."""
        p = PresenzaOttica()
        p.ricorda(self.fascia(0))
        for _ in range(6):
            p.aggiorna(self.fascia(9))
        assert p.presente
        p.non_e_una_bottiglia(self.fascia(9))
        assert p.presente is False
        for _ in range(6):
            assert p.aggiorna(self.fascia(9)) is False


class TestIlRiquadroDellaBottiglia:
    """Il riquadro che va all'OCR segue la bottiglia, invece di stare fermo.

    Una renana alta e stretta e una borgognona larga non occupano la stessa
    parte del fotogramma: un riquadro fisso o taglia l'una, o lascia dentro
    mezza stanza per l'altra. La sagoma è quella della bottiglia contro lo
    sfondo imparato — i pixel cambiati sono lei, perché è l'unica cosa che è
    arrivata.
    """

    LARGO, ALTO = 96, 170

    def sfondo(self, seme=0):
        r = np.random.default_rng(seme)
        return r.integers(0, 255, (self.ALTO, self.LARGO)).astype(np.float32)

    def con_bottiglia(self, x0, x1, y0=40, seme=0):
        """Lo sfondo con sopra la bottiglia: chiara, e con la sua etichetta.

        Non una macchia uniforme: una bottiglia vera ha un'etichetta e dei
        riflessi, e un rettangolo di un solo valore sbilancia le statistiche
        dell'immagine al punto che la normalizzazione della luce fa risultare
        cambiato anche lo sfondo. Il rivelatore se ne accorge e rinuncia — che
        è il comportamento giusto davanti a una sagoma incredibile — ma
        provarlo così vorrebbe dire provare un caso che sul vetro non esiste.
        """
        r = np.random.default_rng(seme + 1)
        img = self.sfondo(seme).copy()
        alta = self.ALTO - y0
        img[y0:, x0:x1] = 190 + r.integers(0, 40, (alta, x1 - x0))
        return img

    def posa(self, p, immagine, volte=6):
        for _ in range(volte):
            fuori = p.aggiorna(immagine)
        return fuori

    def test_senza_bottiglia_non_c_e_riquadro(self):
        p = PresenzaOttica()
        self.posa(p, self.sfondo())
        assert p.riquadro() is None

    def test_una_bottiglia_stretta_da_un_riquadro_stretto(self):
        p = PresenzaOttica()
        self.posa(p, self.sfondo())
        assert self.posa(p, self.con_bottiglia(38, 58)) is True
        r = p.riquadro()
        assert r is not None
        x0, y0, x1, y1 = r
        assert 0.35 < x0 < 0.42 and 0.58 < x1 < 0.65, r
        assert y1 > 0.95, "la bottiglia arriva al bordo di sotto"

    def test_una_bottiglia_larga_da_un_riquadro_largo(self):
        p = PresenzaOttica()
        self.posa(p, self.sfondo())
        self.posa(p, self.con_bottiglia(20, 76))
        stretto = PresenzaOttica()
        self.posa(stretto, self.sfondo())
        self.posa(stretto, self.con_bottiglia(38, 58))
        largo, sottile = p.riquadro(), stretto.riquadro()
        assert largo is not None and sottile is not None
        assert (largo[2] - largo[0]) > (sottile[2] - sottile[0]) * 1.8

    def test_una_macchia_larga_e_bassa_non_e_una_bottiglia(self):
        """Una sagoma più larga che alta non sta in piedi sul piatto: è una
        scena che è cambiata, e un riquadro sbagliato non si vede — taglia
        l'etichetta e basta."""
        p = PresenzaOttica()
        self.posa(p, self.sfondo())
        img = self.sfondo().copy()
        img[10:40, :] = 200.0              # una fascia larga e bassa
        self.posa(p, img)
        assert p.riquadro() is None

    def test_una_macchia_minuscola_non_e_una_bottiglia(self):
        p = PresenzaOttica()
        self.posa(p, self.sfondo())
        img = self.sfondo().copy()
        img[80:100, 46:50] = 200.0
        self.posa(p, img)
        assert p.riquadro() is None

    def test_la_luce_che_cambia_non_disegna_riquadri(self):
        """Stessa normalizzazione della differenza: una luce diversa varrebbe
        una sagoma grande quanto il vetro."""
        p = PresenzaOttica()
        s = self.sfondo()
        self.posa(p, s)
        self.posa(p, s * 0.7)
        assert p.riquadro() is None


class TestIlRitaglioSegueIlRiquadro:
    def camera(self, riquadro=None):
        from amelie.capture import Camera

        c = Camera(ImpostazioniCamera(ritaglio_largo=0.70, ritaglio_alto=0.95))
        c.riquadro = riquadro
        return c

    def test_senza_riquadro_si_usa_quello_fisso(self):
        out = self.camera().ritaglia(immagine(1000, 500))
        assert out.shape[:2] == (950, 350)

    def test_col_riquadro_si_usa_quello(self):
        c = self.camera((0.2, 0.1, 0.6, 0.9))
        out = c.ritaglia(immagine(1000, 500))
        # 40% di larghezza meno il margine ai due lati, 80% di altezza
        largo = int(500 * (0.4 - 2 * 0.06 * 0.4))
        assert out.shape[0] == 800
        assert abs(out.shape[1] - largo) <= 2, out.shape

    def test_un_riquadro_degenere_torna_al_fisso(self):
        c = self.camera((0.5, 0.5, 0.5001, 0.5001))
        out = c.ritaglia(immagine(1000, 500))
        assert out.shape[:2] == (950, 350)


class TestLaCameraCheSiFerma:
    """Una serala sala si e' fatta buia, la posa e' salita a 5000 e
    la camera ha smesso di dare fotogrammi. Ogni riapertura riapplicava 5000:
    solo spegnere il dispositivo la sbloccava."""

    class Muta:
        """Una camera che, come quella vera, si ferma da una posa in su."""

        def __init__(self, soglia=4999):
            self.soglia, self.posa, self.rilasciata = soglia, 900, False

        def isOpened(self):
            return True

        def set(self, *_a):
            return True

        def read(self):
            if self.posa >= self.soglia:
                return False, None
            return True, np.full((100, 200, 3), 90, dtype=np.uint8)

        def release(self):
            self.rilasciata = True

    def _camera(self, monkeypatch, posa, soglia=4999):
        import amelie.capture as modulo
        muta = self.Muta(soglia)
        monkeypatch.setattr(modulo.cv2, "VideoCapture", lambda *_a: muta)
        monkeypatch.setattr(modulo, "imposta_posa",
                            lambda _d, p: setattr(muta, "posa", p))
        c = modulo.Camera(ImpostazioniCamera(esposizione=posa))
        c._percorso = "/dev/finto"
        return c, muta

    def test_il_tetto_sta_sotto_la_soglia_misurata(self):
        assert ImpostazioniCamera().posa_massima <= 4500

    def test_alla_seconda_lettura_a_vuoto_si_riparte_dalla_posa_sicura(self, monkeypatch):
        c, muta = self._camera(monkeypatch, 5000)
        assert c.fotogramma() is None            # 5000: muta
        assert c.imp.esposizione == 5000         # una volta sola puo' capitare
        assert c.fotogramma() is None
        assert c.imp.esposizione == c.imp.posa_sicura
        assert c.fotogramma() is not None        # riaperta a 900: parla
        assert c._vuoti == 0

    def test_con_una_posa_corta_non_si_tocca_niente(self, monkeypatch):
        c, muta = self._camera(monkeypatch, 900, soglia=0)     # muta sempre
        for _ in range(3):
            assert c.fotogramma() is None
        assert c.imp.esposizione == 900

    def test_ripristinare_riporta_la_camera_come_all_accensione(self, monkeypatch):
        c, muta = self._camera(monkeypatch, 4400)
        c.riquadro = (0.1, 0.1, 0.9, 0.9)
        c._vuoti = 5
        c.ripristina()
        assert c.imp.esposizione == c.imp.posa_sicura and c.riquadro is None
        assert c._vuoti == 0 and c._cap is None
        assert c._percorso is None, "il device si ricerca: dopo un inceppamento USB cambia nome"
