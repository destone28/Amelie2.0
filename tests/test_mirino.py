"""Test del mirino.

Il mirino è uno strumento di misura, e uno strumento di misura ha un modo
tutto suo di sbagliare: misurare se stesso. Il test che conta più di tutti è
quello che verifica che il rettangolo e la scritta disegnati sopra al
fotogramma NON finiscano dentro all'immagine che l'OCR sta per leggere.
"""

import pytest

from amelie.mirino import LetturaContinua, Mirino, disegna


class LettoreFinto:
    def __init__(self, righe=("BAROLO", "2016"), rompe=False):
        self.righe, self.rompe = list(righe), rompe
        self.viste = []

    def leggi(self, immagine):
        from amelie.ocr import Lettura, Riga

        if self.rompe:
            raise RuntimeError("il motore non parte")
        self.viste.append(immagine)
        return Lettura(righe=[Riga(testo=t, confidenza=0.9) for t in self.righe],
                       durata_s=0.2)


class MatcherFinto:
    def __init__(self, **campi):
        self.campi = campi
        self.chiuso = False

    def cerca(self, righe):
        from amelie.matcher import Fatti

        return Fatti(**self.campi)

    def chiudi(self):
        self.chiuso = True


class TestLaLetturaContinua:
    def test_dice_cosa_ha_letto_e_cosa_ha_trovato(self):
        from amelie.matcher import Livello

        esito = LetturaContinua._leggi(
            LettoreFinto(), MatcherFinto(livello=Livello.DENOMINAZIONE,
                                         sicurezza=87.0, nome="Barolo DOCG"),
            "un fotogramma")
        assert esito["stato"] == "letto"
        assert esito["righe"] == ["BAROLO", "2016"]
        assert esito["livello"] == "denominazione"
        assert esito["sicurezza"] == 87
        assert esito["nome"] == "Barolo DOCG"
        assert esito["durata"] >= 0

    def test_un_OCR_che_inciampa_non_spegne_il_mirino(self):
        """Proprio quando l'OCR fallisce è il momento in cui lo si sta
        guardando: un mirino che muore lì non serve a niente."""
        esito = LetturaContinua._leggi(LettoreFinto(rompe=True), MatcherFinto(),
                                       "un fotogramma")
        assert esito["stato"].startswith("errore:")
        assert "il motore non parte" in esito["stato"]

    def test_del_fotogramma_vecchio_non_importa_niente(self):
        """Se ne arriva uno nuovo mentre si legge, il vecchio si butta: si
        vuole sapere cosa legge ADESSO, non recuperare la coda."""
        l = LetturaContinua(LettoreFinto(), MatcherFinto())
        l.proponi("primo")
        l.proponi("secondo")
        assert l._prendi() == "secondo"
        assert l._prendi() is None

    def test_il_lettore_prestato_non_si_chiude(self):
        """Quando qualcuno glieli presta, chiuderli non tocca al mirino.

        Il caso normale è l'opposto — il mirino apre i suoi, perché due fili
        dentro allo stesso motore ONNX non è una cosa che si fa — ma la
        prestazione resta possibile, e chi presta se li riprende.
        """
        matcher = MatcherFinto()
        l = LetturaContinua(LettoreFinto(), matcher)
        assert l._miei is False
        l.avvia()
        l.spegni()
        for _ in range(50):
            if not l._filo.is_alive():
                break
            import time
            time.sleep(0.05)
        assert matcher.chiuso is False, "ha chiuso un matcher che non era suo"


class TestIlDisegno:
    @staticmethod
    def fotogramma(valore=30):
        np = pytest.importorskip("numpy")
        pytest.importorskip("cv2")
        return np.full((200, 320, 3), valore, dtype=np.uint8)

    @staticmethod
    def imp(largo=0.85, alto=None):
        """Una camera vera, che non tocca l'hardware finché non le si chiede un
        fotogramma: `disegna` chiede a lei il riquadro, perché deve disegnare
        QUELLO IN USO e non uno che gli somiglia."""
        from dataclasses import replace

        from amelie.capture import Camera, ImpostazioniCamera

        return Camera(replace(ImpostazioniCamera(), ritaglio_largo=largo,
                              ritaglio_alto=largo if alto is None else alto))

    def test_lo_strumento_non_misura_se_stesso(self):
        """IL test.

        `ritaglia_centro` restituisce una VISTA sullo stesso blocco di memoria.
        Disegnandoci sopra il rettangolo e la scritta, quelli finivano dentro
        all'immagine che l'OCR stava per leggere: la prima riga riconosciuta
        era «nitidezza 60 (soglia 40)», cioè la sovrimpressione di questo
        strumento.
        """
        import numpy as np

        frame = self.fotogramma()
        _, ritaglio, _ = disegna(frame, self.imp())
        assert np.all(ritaglio == 30), (
            "il disegno del mirino e' finito nell'immagine che legge l'OCR")
        # e sul fotogramma mostrato il disegno c'e' eccome
        assert not np.all(frame == 30)

    def test_quello_che_esce_e_un_jpeg(self):
        jpg, _, _ = disegna(self.fotogramma(), self.imp())
        assert jpg[:2] == b"\xff\xd8"          # SOI, l'inizio di ogni JPEG

    def test_all_OCR_va_il_ritaglio_non_il_fotogramma_intero(self):
        """È quello che vede il dispositivo: leggere di più qui darebbe un
        risultato che a regime non si otterrebbe."""
        frame = self.fotogramma()
        _, ritaglio, _ = disegna(frame, self.imp(0.5))
        assert ritaglio.shape[:2] == (100, 160)

    def test_la_nitidezza_e_quella_del_ritaglio(self):
        """Fuori dal riquadro l'OCR non guarda, e includerlo darebbe un numero
        che non decide niente."""
        import numpy as np

        frame = self.fotogramma()
        # tutto il contrasto sta FUORI dal ritaglio
        frame[:20, :] = 255
        frame[-20:, :] = 255
        _, _, n = disegna(frame, self.imp(0.5))
        assert n == pytest.approx(0.0, abs=1e-6)


class CameraFinta:
    """Una camera che consegna sempre lo stesso fotogramma.

    Il ritaglio lo delega a una camera VERA: `disegna` chiede alla camera il
    riquadro in uso, e riscriverne qui una copia vorrebbe dire provare il
    disegno contro un ritaglio che il dispositivo non usa.
    """

    def __init__(self, frame=None, vera=None):
        self.frame = frame
        self.vera = vera
        self.imp = vera.imp if vera is not None else None
        self.chieste = 0
        self.regolata = 0

    @property
    def riquadro(self):
        return None if self.vera is None else self.vera.riquadro

    def ritaglia(self, frame):
        return self.vera.ritaglia(frame)

    def fotogramma(self):
        self.chieste += 1
        return self.frame

    def regola_la_luce(self):
        self.regolata += 1
        return 90.0


class TestAccendereESpegnere:
    def test_spento_non_c_e_niente_da_vedere(self):
        m = Mirino(CameraFinta())
        assert m.acceso is False
        assert m.ultimo() is None

    def test_senza_OCR_lo_dice(self):
        assert Mirino(CameraFinta()).esito == {"stato": "OCR spento"}

    def test_acceso_produce_fotogrammi_e_li_da_da_leggere(self):
        import time

        frame = TestIlDisegno.fotogramma()
        camera = CameraFinta(frame, TestIlDisegno.imp())
        lettore = LettoreFinto()
        m = Mirino(camera, LetturaContinua(lettore, MatcherFinto()))
        m.accendi()
        try:
            for _ in range(60):
                if m.ultimo() is not None and lettore.viste:
                    break
                time.sleep(0.05)
            assert m.ultimo() is not None, "nessun fotogramma in tre secondi"
            assert lettore.viste, "l'OCR non ha mai ricevuto niente da leggere"
            assert m.nitidezza >= 0
        finally:
            m.spegni()

    def test_spegnendolo_non_resta_l_ultimo_fotogramma(self):
        """Riaccendendolo, il browser mostrerebbe la volta prima come se fosse
        adesso — che su uno strumento di taratura è il peggio che possa fare."""
        import time

        camera = CameraFinta(TestIlDisegno.fotogramma(), TestIlDisegno.imp())
        m = Mirino(camera)
        m.accendi()
        for _ in range(60):
            if m.ultimo() is not None:
                break
            time.sleep(0.05)
        m.spegni()
        assert m.acceso is False
        assert m.ultimo() is None

    def test_la_posa_si_cerca_sul_filo_del_mirino(self):
        """Non da chi ha premuto l'interruttore: cercarla apre la camera e puo'
        aspettare che una scansione in corso la lasci, e chi risponde al tocco
        e' il ciclo di eventi del server - schermo, pulsanti e racconto, tutti
        fermi insieme per una decina di secondi."""
        import time

        camera = CameraFinta(TestIlDisegno.fotogramma(), TestIlDisegno.imp())
        m = Mirino(camera)
        m.accendi()
        for _ in range(60):
            if camera.regolata:
                break
            time.sleep(0.05)
        m.spegni()
        assert camera.regolata == 1

    def test_si_puo_dire_di_non_toccare_la_posa(self):
        """Il mirino da banco la imposta da riga di comando, e ricercarla
        vorrebbe dire scavalcare quello che si e' chiesto."""
        import time

        camera = CameraFinta(TestIlDisegno.fotogramma(), TestIlDisegno.imp())
        m = Mirino(camera, regola_la_luce=False)
        m.accendi()
        time.sleep(0.3)
        m.spegni()
        assert camera.regolata == 0

    def test_una_camera_che_non_da_niente_non_fa_girare_a_vuoto(self):
        """Nessun fotogramma non è un guasto: si riprova piano, invece di
        consumare un core intero su una camera staccata."""
        import time

        camera = CameraFinta(None)
        m = Mirino(camera, regola_la_luce=False)
        m.accendi()
        time.sleep(0.4)
        m.spegni()
        assert camera.chieste <= 8, "sta girando a vuoto a tutta velocità"
