"""Il ripristino: cio' che prima si otteneva solo staccando la corrente.

Una serala camera ha smesso di dare fotogrammi e ogni bottiglia e'
finita in guasto per un'ora, finche' qualcuno non ha spento e riacceso.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from amelie.state import Evento, Stato


@pytest.fixture
def amelie():
    from amelie.app import Amelie, Configurazione
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    yield a
    a.matcher.chiudi()
    a.narratore.chiudi()


class CameraFinta:
    def __init__(self):
        self.ripristinata = 0

    def ripristina(self):
        self.ripristinata += 1

    def chiudi(self):
        pass


class TestRipristinare:
    def test_torna_all_invito_come_appena_acceso(self, amelie):
        amelie.camera = CameraFinta()
        amelie.macchina.stato = Stato.GUASTO
        amelie._scadenza = time.monotonic() + 5
        amelie._tentativi = 3
        amelie._bottiglia_chiusa = True
        detti = []
        amelie._pubblica = detti.append
        assert amelie.ripristina("prova")["ok"]
        assert amelie.macchina.stato is Stato.ATTESA
        assert amelie.camera.ripristinata == 1
        assert amelie._tentativi == 0 and not amelie._bottiglia_chiusa
        assert amelie._scadenza is None
        assert any(m.get("tipo") == "stato" and m.get("vista") == "attesa" for m in detti)

    def test_un_lavoro_che_non_torna_si_lascia_andare(self, amelie, monkeypatch):
        """Col lavoro «in corso» ogni bottiglia era un guasto: `_avvia` non ne
        faceva partire un altro. Dopo il ripristino la pipeline e' libera."""
        fermo = threading.Event()
        appeso = threading.Thread(target=fermo.wait, daemon=True)
        appeso.start()
        amelie._lavoro = appeso
        monkeypatch.setattr(amelie, "_attendi_lavoro", lambda s: None)
        amelie.ripristina("prova")
        assert amelie._lavoro is None
        fermo.set()

    def test_chiude_l_editor_aperto(self, amelie):
        amelie._correggendo = {"quando": time.monotonic()}
        detti = []
        amelie._pubblica = detti.append
        amelie.ripristina("prova")
        assert amelie._correggendo is None
        assert {"tipo": "correzione", "aperta": False} in detti


class TestDaSolo:
    def _guasto(self, amelie):
        amelie.macchina.stato = Stato.RICONOSCIMENTO
        amelie.macchina.invia(Evento.ERRORE)

    def test_un_guasto_isolato_non_ripristina(self, amelie):
        self._guasto(amelie)
        assert amelie._da_ripristinare is None

    def test_tre_guasti_in_tre_minuti_ripristinano(self, amelie, monkeypatch):
        chiamate = []
        monkeypatch.setattr(amelie, "ripristina", lambda motivo="": chiamate.append(motivo))
        for _ in range(3):
            self._guasto(amelie)
        assert amelie._da_ripristinare
        asyncio.run(amelie._un_battito())
        assert len(chiamate) == 1 and amelie._da_ripristinare is None

    def test_guasti_lontani_non_si_sommano(self, amelie, monkeypatch):
        from amelie import app as modulo
        amelie._guasti = [time.monotonic() - modulo.FINESTRA_GUASTI_S - 1] * 2
        self._guasto(amelie)
        assert amelie._da_ripristinare is None

    def test_se_tornano_subito_si_riavvia_il_servizio(self, amelie, monkeypatch):
        import os
        uscite = []
        monkeypatch.setenv("INVOCATION_ID", "prova")
        monkeypatch.setattr(os, "_exit", lambda codice: uscite.append(codice))
        amelie._ultimo_ripristino = time.monotonic() - 60
        amelie._ripristina_da_solo("tre guasti")
        assert uscite == [75]

    def test_fuori_da_systemd_non_si_esce_mai(self, amelie, monkeypatch):
        import os
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        monkeypatch.setattr(os, "_exit", lambda codice: pytest.fail("non doveva uscire"))
        amelie._ultimo_ripristino = time.monotonic() - 60
        amelie._ripristina_da_solo("tre guasti")
        assert amelie.macchina.stato is Stato.ATTESA


def test_la_rotta_c_e(amelie):
    from amelie.app import crea_app
    assert "/ripristina" in {r.path for r in crea_app(amelie).routes}
