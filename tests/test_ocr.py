"""Test della lettura dell'etichetta.

Il motore vero non serve: qui si verifica che il filtro sulla confidenza
funzioni, che il riconoscimento delle righe "grandi" — quelle dove sta la
denominazione — sia sensato, e che le scelte pagate con una misura restino
quelle.
"""

import pytest

from amelie.ocr import (
    ImpostazioniOCR,
    Lettore,
    Lettura,
    Riga,
    _altezza_del_riquadro,
)


def riquadro(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class TestAltezzaDelRiquadro:
    """Serve a decidere quali righe meritano i quaranta millesimi di lettura."""

    def test_misura_l_altezza(self):
        assert _altezza_del_riquadro(riquadro(0, 10, 100, 40)) == 30

    def test_un_riquadro_illeggibile_vale_zero_e_non_esplode(self):
        assert _altezza_del_riquadro([["x", "y"]]) == 0.0
        assert _altezza_del_riquadro(None) == 0.0


class TestFiltro:
    def test_scarta_bassa_confidenza(self):
        lettore = Lettore(ImpostazioniOCR(confidenza_minima=0.6))
        assert lettore._tieni(Riga("Barolo", 0.9))
        assert not lettore._tieni(Riga("~~", 0.3))

    def test_scarta_righe_troppo_corte(self):
        lettore = Lettore(ImpostazioniOCR(lunghezza_minima=3))
        assert not lettore._tieni(Riga("ab", 0.99))
        assert lettore._tieni(Riga("abc", 0.99))

    def test_scarta_righe_di_soli_spazi(self):
        assert not Lettore()._tieni(Riga("     ", 0.99))


class TestRiga:
    def test_altezza_dal_riquadro(self):
        assert Riga("x", 0.9, tuple(map(tuple, riquadro(0, 10, 100, 40)))).altezza == 30

    def test_altezza_senza_riquadro(self):
        assert Riga("x", 0.9).altezza == 0.0


class TestLettura:
    def test_testo_unisce_le_righe(self):
        lettura = Lettura(righe=[Riga("Barolo", 0.9), Riga("2019", 0.9)])
        assert lettura.testo == "Barolo\n2019"

    def test_vuota(self):
        assert Lettura().vuota
        assert not Lettura(righe=[Riga("x", 0.9)]).vuota

    def test_righe_grandi_trovano_la_denominazione(self):
        """Sull'etichetta la denominazione è scritta grande, i solfiti piccoli."""
        lettura = Lettura(righe=[
            Riga("BAROLO", 0.99, tuple(map(tuple, riquadro(0, 0, 200, 50)))),
            Riga("contiene solfiti", 0.8, tuple(map(tuple, riquadro(0, 90, 80, 98)))),
        ])
        grandi = [r.testo for r in lettura.righe_grandi()]
        assert grandi == ["BAROLO"]

    def test_righe_grandi_senza_riquadri_le_tiene_tutte(self):
        lettura = Lettura(righe=[Riga("a", 0.9), Riga("b", 0.9)])
        assert len(lettura.righe_grandi()) == 2

    def test_righe_grandi_su_lettura_vuota(self):
        assert Lettura().righe_grandi() == []


class TestImpostazioni:
    def test_il_classificatore_di_orientamento_resta_acceso(self):
        """Era spento, e spegnerlo costava quasi tutto.

        La motivazione era «sul supporto l'etichetta è sempre dritta, il
        classificatore è tempo sprecato». Sbagliata due volte. Su una bottiglia
        il testo non è quasi mai orizzontale nel fotogramma — cilindro,
        appoggio, camera che guarda dal basso e di sbieco — e su un'etichetta
        scritta lungo l'asse arriva ruotato di novanta gradi.

        Misurato su tre scatti veri della stessa bottiglia:

            spento    `DOLA | SILIA | NER`        vitigno, 61   6,6 s
            acceso    `D'AVOLA | SICILIA | NERO`  tipologia, 87 4,9 s

        Più accurato **e** più veloce: raddrizzare un ritaglio prima di
        riconoscerlo fa risparmiare al riconoscitore il lavoro di indovinare.

        **Quella misura è stata presa con la camera montata orizzontale.** Ora
        la camera è di lato e il fotogramma si raddrizza in `capture`: il testo
        arriva già dritto e non c'è più niente da raddrizzare. Verificato che si
        legga lo stesso con e senza, sulla stessa etichetta.
        """
        assert ImpostazioniOCR().usa_classificatore is False

    def test_la_risoluzione_del_rilevatore_e_un_compromesso_misurato(self):
        """Sotto sbaglia le lettere, sopra si guadagna fino a un certo punto.

        «Sopra costa e basta» veniva da UN'etichetta - a 756 si leggevano le
        stesse righe di 320 - e sulle 139 vere, con l'OCR della board, non e'
        cosi':

                           cantina letta   nome letto   riconoscimento   tempo
            lato 320          112/139        72/139         87,1%        1,02 s
            lato 480          114/139        74/139         90,6%        1,32 s

        Piu' su si torna a peggiorare: a 960 la stessa etichetta da'
        `PALAMA · VINICOLANLSALENTO`, con le parole incollate e il vitigno
        perso. Il rilevatore ha una scala sua.
        """
        assert ImpostazioniOCR().lato_rilevatore == 480

    def test_si_leggono_solo_le_righe_piu_alte(self):
        """Ogni riga costa quaranta millesimi, e una parete ne dà trentotto."""
        assert ImpostazioniOCR().righe_massime == 10

    def test_la_larghezza_di_una_riga_ha_un_tetto(self):
        """Il pacchetto non glielo mette, e una didascalia lunga costava da
        sola quanto tutta l'etichetta."""
        assert ImpostazioniOCR().larghezza_riga == 320
        assert ImpostazioniOCR().altezza_riga == 48

    def test_immutabile(self):
        with pytest.raises(Exception):
            ImpostazioniOCR().lato_rilevatore = 1


class TestIlVersoDelFotogramma:
    """Un verso sbagliato non degrada la lettura: la annulla.

    Misurato nella scocca, stessa bottiglia e stesso fotogramma, dando all'OCR
    i quattro versi: a 0 gradi `ULISS | CERASUOLO | D'ABRUZZO` e il vino
    riconosciuto; a 90 gradi solo `D'ABRUZZC`; a 180 e 270 spazzatura. Un'ora
    di dispositivo che «non riconosce le bottiglie» era questo.
    """

    @staticmethod
    def _fotogramma():
        """Un fotogramma vero serve: `cv2.rotate` non gira un finto."""
        np = pytest.importorskip("numpy")
        pytest.importorskip("cv2")
        return np.zeros((40, 80, 3), dtype=np.uint8)   # largo: il verso sbagliato

    def test_se_il_raccolto_e_povero_si_riprova_girando(self, monkeypatch):
        from amelie import ocr as modulo

        immagine = self._fotogramma()
        versi = []

        def finta(self, fotogramma):
            h, w = fotogramma.shape[:2]
            versi.append((w, h))
            # in piedi l'etichetta si legge, coricata no
            testi = (["CERASUOLO", "D'ABRUZZO", "ULISS"] if h > w
                     else ["D'ABRUZZC"])
            return modulo.Lettura(righe=[modulo.Riga(testo=x, confidenza=0.9)
                                         for x in testi])

        monkeypatch.setattr(modulo.Lettore, "leggi", finta)
        letta = modulo.Lettore().leggi_comunque(immagine)
        assert [r.testo for r in letta.righe] == ["CERASUOLO", "D'ABRUZZO", "ULISS"]
        assert len(versi) > 1, "non ha nemmeno provato a girare"

    def test_ma_un_etichetta_letta_a_meta_non_si_gira(self):
        """Due parole sono una lettura: il verso e' giusto, manca altro.

        Misurato sul dispositivo su «Azienda Agricola Brunello 1930»: letto
        `1930 | Brunello | Affinato inboti`, e il ripiego girava tre volte per
        4,6 secondi per poi tenere comunque la prima lettura - che era gia'
        quella con cui il vino e' stato riconosciuto.
        """
        from amelie import ocr as modulo

        immagine = self._fotogramma()
        versi = []

        def finta(self, fotogramma):
            versi.append(fotogramma.shape)
            return modulo.Lettura(righe=[modulo.Riga(testo=x, confidenza=0.9)
                                         for x in ("1930", "Brunello",
                                                   "Affinato inboti")])

        modulo.Lettore.leggi, vera = finta, modulo.Lettore.leggi
        try:
            modulo.Lettore().leggi_comunque(immagine)
        finally:
            modulo.Lettore.leggi = vera
        assert len(versi) == 1, "ha girato un'etichetta che stava dritta"

    def test_il_tempo_dichiarato_e_quello_di_tutti_i_versi(self):
        """A giornale comparivano «1,1 s» per una lettura costata 4,6.

        `durata_s` era quella della `leggi` che aveva vinto, non della
        `leggi_comunque`: il costo del ripiego era invisibile proprio a chi
        doveva accorgersene.
        """
        import time

        from amelie import ocr as modulo

        immagine = self._fotogramma()

        def finta(self, fotogramma):
            time.sleep(0.02)
            return modulo.Lettura(righe=[modulo.Riga(testo="ab", confidenza=0.9)],
                                  durata_s=0.02)

        modulo.Lettore.leggi, vera = finta, modulo.Lettore.leggi
        try:
            letta = modulo.Lettore().leggi_comunque(immagine)
        finally:
            modulo.Lettore.leggi = vera
        assert letta.durata_s >= 0.08, (
            "il tempo dichiarato e' quello di un verso solo, non di tutti")

    def test_se_il_primo_verso_basta_non_si_gira_niente(self, monkeypatch):
        """Girare costa secondi, e si pagano solo quando servono."""
        from amelie import ocr as modulo

        immagine = self._fotogramma()
        versi = []

        def finta(self, fotogramma):
            versi.append(fotogramma.shape)
            return modulo.Lettura(righe=[modulo.Riga(testo=x, confidenza=0.9)
                                         for x in ("CERASUOLO", "D'ABRUZZO", "ULISS")])

        monkeypatch.setattr(modulo.Lettore, "leggi", finta)
        modulo.Lettore().leggi_comunque(immagine)
        assert len(versi) == 1

    def test_su_un_piatto_vuoto_non_si_gira_niente(self):
        """Il vuoto è il piatto vuoto, ed è il caso più frequente di tutti.

        Un verso sbagliato non dà il vuoto, dà spazzatura: `D'ABRUZZC` a 90
        gradi, `3IMER · DRZZZO · CEAVOLO` a 180. Zero righe vuol dire che
        davanti alla camera non c'è scritto niente, e girare il fotogramma non
        ci scriverà nulla. Senza questa distinzione ogni scansione a vuoto
        costava quattro passaggi di OCR invece di uno — sul dispositivo,
        ventiquattro secondi contro sei, abbastanza da far scadere la scansione
        e dichiarare un guasto al posto di un piatto vuoto.
        """
        from amelie import ocr as modulo

        immagine = self._fotogramma()
        versi = []

        def finta(self, fotogramma):
            versi.append(fotogramma.shape)
            return modulo.Lettura(righe=[])

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(modulo.Lettore, "leggi", finta)
        try:
            letta = modulo.Lettore().leggi_comunque(immagine)
        finally:
            monkeypatch.undo()
        assert letta.vuota
        assert len(versi) == 1, "ha girato un fotogramma su cui non c'era nulla"

    def test_su_una_parete_piena_di_scritte_non_si_gira_niente(self):
        """Tante righe non sono un'etichetta girata male: sono una parete.

        Misurato sul dispositivo, bottiglia tolta e un calendario dietro:
        trentotto righe di numeri e 39 secondi per leggerle. Girare altre tre
        volte vorrebbe dire due minuti e mezzo, e per niente — qualunque verso,
        quella parete resta piena di scritte.
        """
        from amelie import ocr as modulo

        immagine = self._fotogramma()
        versi = []

        def finta(self, fotogramma):
            versi.append(fotogramma.shape)
            # cifre: nessuna conta come parola utile, quindi il raccolto e'
            # «povero» e senza questa regola si girerebbe
            return modulo.Lettura(righe=[
                modulo.Riga(testo=str(10 + k), confidenza=0.9)
                for k in range(38)])

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(modulo.Lettore, "leggi", finta)
        try:
            letta = modulo.Lettore().leggi_comunque(immagine)
        finally:
            monkeypatch.undo()
        assert len(letta.righe) == 38
        assert len(versi) == 1, "ha girato un fotogramma pieno di scritte"

    def test_le_cifre_non_contano_come_parole(self):
        """Un calendario appeso dietro la bottiglia ne produce a decine, e su
        quelle il riconoscitore non ci fa niente."""
        from amelie.ocr import _parole_utili

        cifre = Lettura(righe=[Riga(testo=t, confidenza=0.9)
                               for t in ("16", "17", "2026", "20")])
        parole = Lettura(righe=[Riga(testo=t, confidenza=0.9)
                                for t in ("CERASUOLO", "D'ABRUZZO", "ULISS")])
        assert _parole_utili(cifre) == 0
        assert _parole_utili(parole) == 3
