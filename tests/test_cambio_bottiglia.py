"""La bottiglia cambiata mentre il dispositivo sta raccontando.

Il comportamento voluto: quando la bottiglia sul piatto viene sollevata e
sostituita con un'altra, la descrizione deve cambiare subito, e la nuova si
comincia a leggere mentre la voce parla ancora della vecchia. Ma se la
bottiglia rimessa e' la STESSA - sollevata per versare - il racconto non si
interrompe. Qui si prova la decisione, con camera e OCR finti e il resto vero:
la macchina a stati, le correzioni, l'archivio.
"""
from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from amelie.capture import ImpostazioniCamera, Scatto  # noqa: E402
from amelie.correzioni import Correzioni  # noqa: E402
from amelie.ocr import Lettura, Riga  # noqa: E402
from amelie.state import Evento, Stato  # noqa: E402


def _etichetta(testo: str, seme: int):
    """Un'etichetta finta con abbastanza disegno perche' ORB la riconosca."""
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


class CameraFinta:
    imp = ImpostazioniCamera()

    def __init__(self):
        self.immagine = None
        self.scatti = 0
        self.chiusa = 0

    def sorveglia(self): pass
    def sbircia(self): return None
    riquadro = None

    def al_volo(self, **_):
        self.scatti += 1
        return Scatto(immagine=self.immagine, nitidezza=200.0)

    def scatta(self, **_):
        return self.al_volo()

    def chiudi(self):
        self.chiusa += 1

    @contextlib.contextmanager
    def in_pausa(self):
        yield


class LettoreFinto:
    def __init__(self):
        self.righe: list[Riga] = []
        self.letture = 0

    def leggi_comunque(self, _immagine):
        self.letture += 1
        return Lettura(righe=list(self.righe), durata_s=0.1)


VECCHIA = "MARCHESI DI BAROLO|BAROLO|CANNUBI|2016"
NUOVA = "PALAMA|NEGROAMARO|SALENTO"


@pytest.fixture
def amelie(tmp_path):
    from amelie.app import Amelie, Configurazione
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    a.correzioni = Correzioni(tmp_path / "correzioni")
    a.camera = CameraFinta()
    a.lettore = LettoreFinto()
    yield a
    a._annulla_anticipo()
    a._ferma_racconto()
    a.matcher.chiudi()
    a.narratore.chiudi()


def _racconta(amelie, testo=VECCHIA, seme=3):
    """Il dispositivo sta raccontando questa bottiglia."""
    im, righe = _etichetta(testo, seme)
    amelie._ultimo_scatto = im
    amelie._righe_lette = righe
    amelie._righe = [r.testo for r in righe]
    amelie._fatti = amelie.matcher.cerca(amelie._righe)
    amelie._voce = None
    amelie._correzione = None
    assert not amelie._fatti.vuoto
    amelie.macchina.stato = Stato.RACCONTO
    amelie._cambiata_durante_il_racconto = True


def _posa(amelie, testo, seme):
    """Sul piatto arriva questa bottiglia: foto e righe che la camera vedra'."""
    im, righe = _etichetta(testo, seme)
    amelie.camera.immagine = im
    amelie.lettore.righe = righe
    from amelie.app import _Anticipo
    return _Anticipo(apparsa=time.monotonic())


def _attendi(amelie, stati, secondi=15.0):
    fine = time.monotonic() + secondi
    while time.monotonic() < fine:
        if amelie.macchina.stato in stati:
            return amelie.macchina.stato
        if amelie._scadenza and time.monotonic() >= amelie._scadenza:
            amelie._scadenza = None
            amelie.macchina.invia(Evento.SCADENZA)
        time.sleep(0.02)
    return amelie.macchina.stato


class TestLaStessaBottiglia:
    def test_la_foto_basta_e_non_si_legge_nemmeno(self, amelie):
        """Sollevata per versare e rimessa: la foto ritrova l'etichetta in un
        attimo, e l'OCR non parte."""
        _racconta(amelie)
        a = _posa(amelie, VECCHIA, 3)
        amelie._decidi_in_anticipo(a)
        assert amelie.lettore.letture == 0
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._cambiata_durante_il_racconto is False
        assert amelie._anticipata is None

    def test_le_stesse_parole_bastano_anche_se_la_foto_no(self, amelie):
        """Rimessa girata: la foto non si ritrova, le parole si'."""
        _racconta(amelie)
        a = _posa(amelie, VECCHIA, 99)          # stesso testo, disegno diverso
        amelie._decidi_in_anticipo(a)
        assert amelie.lettore.letture == 1
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._cambiata_durante_il_racconto is False

    def test_a_racconto_finito_non_si_rilegge(self, amelie):
        _racconta(amelie)
        amelie.macchina.invia(Evento.RACCONTO_FINITO)
        assert amelie.macchina.stato is Stato.CONCLUSO
        amelie._decidi_in_anticipo(_posa(amelie, VECCHIA, 3))
        assert amelie._bottiglia_chiusa is True


class TestUnAltraBottiglia:
    def test_la_voce_si_ferma_e_parte_la_nuova_senza_rifare_la_foto(self, amelie):
        _racconta(amelie)
        a = _posa(amelie, NUOVA, 11)
        amelie._decidi_in_anticipo(a)
        # La lettura e' stata fatta una volta sola, in anticipo: la scansione
        # la prende e non scatta ne' legge di nuovo.
        finale = _attendi(amelie, {Stato.RACCONTO, Stato.RIPOSIZIONA, Stato.GUASTO})
        assert finale is Stato.RACCONTO, finale
        assert amelie.camera.scatti == 1 and amelie.lettore.letture == 1
        assert amelie._righe == ["PALAMA", "NEGROAMARO", "SALENTO"]
        assert "negroamaro" in (amelie._fatti.vitigni[0] if amelie._fatti.vitigni else "").lower() \
            or "Palam" in (amelie._fatti.cantina or "")

    def test_se_non_si_capisce_il_racconto_continua(self, amelie):
        """Nessuna parola letta: non si interrompe niente, e la bottiglia si
        rilegge a racconto finito, come prima."""
        _racconta(amelie)
        a = _posa(amelie, "2024|75 cl", 11)
        amelie._decidi_in_anticipo(a)
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._cambiata_durante_il_racconto is True

    def test_tolta_prima_di_decidere_non_se_ne_fa_niente(self, amelie):
        _racconta(amelie)
        a = _posa(amelie, NUOVA, 11)
        amelie._anticipo = a
        amelie._annulla_anticipo()
        amelie._decidi_in_anticipo(a)
        assert amelie.macchina.stato is Stato.RACCONTO
        assert amelie._anticipata is None


    def test_decisa_a_racconto_finito_la_raccoglie_il_battito(self, amelie):
        """La lettura finisce quando si e' gia' tornati all'invito: il cambio
        non ha niente da interrompere, e la bottiglia la rilancia il battito,
        con la lettura gia' pronta."""
        _racconta(amelie)
        amelie.macchina.stato = Stato.ATTESA
        amelie._bottiglia_chiusa = True        # la vecchia era gia' raccontata
        amelie._presente = True
        amelie._decidi_in_anticipo(_posa(amelie, NUOVA, 11))
        assert amelie._bottiglia_chiusa is False and amelie._anticipata is not None

        async def c_e():
            return True
        amelie._chi_c_e = c_e
        asyncio.run(amelie._un_battito())
        finale = _attendi(amelie, {Stato.RACCONTO, Stato.RIPOSIZIONA, Stato.GUASTO})
        assert finale is Stato.RACCONTO, finale
        assert amelie.camera.scatti == 1 and amelie.lettore.letture == 1


class TestIlBattito:
    def test_una_bottiglia_posata_a_racconto_in_corso_si_legge_subito(self, amelie):
        _racconta(amelie)
        amelie._presente = False
        partite = []
        amelie._anticipa = lambda: partite.append(True)

        async def c_e():
            return True
        amelie._chi_c_e = c_e
        asyncio.run(amelie._un_battito())
        assert partite == [True]
        assert amelie.macchina.stato is Stato.RACCONTO

    def test_in_attesa_non_si_rilancia_mentre_si_legge_in_anticipo(self, amelie):
        """La lettura in corso decide lei se la bottiglia e' da raccontare."""
        amelie.macchina.stato = Stato.ATTESA
        amelie._presente = True
        amelie._bottiglia_chiusa = False
        from amelie.app import _Anticipo
        amelie._anticipo = _Anticipo(apparsa=time.monotonic())

        async def c_e():
            return True
        amelie._chi_c_e = c_e
        asyncio.run(amelie._un_battito())
        assert amelie.macchina.stato is Stato.ATTESA
