"""Il ripristino: riportare il dispositivo all'invito senza staccare la corrente.

Una camera che smette di dare fotogrammi manda in guasto ogni bottiglia,
finche' qualcuno non spegne e riaccende. Il ripristino fa lo stesso senza
toccare la spina: a comando, o da solo quando i guasti si ripetono.
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
        """Con un lavoro rimasto «in corso» ogni bottiglia sarebbe un guasto,
        perche' `_avvia` non ne fa partire un altro: dopo il ripristino la
        pipeline e' libera."""
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


class TestIlLavoroDiPrima:
    """La bottiglia «sparisce» un istante durante una lettura e torna: la
    lettura precedente sta ancora finendo, e non deve diventare un guasto al
    primo colpo."""

    def _occupa(self, amelie, secondi):
        fine = threading.Event()
        t = threading.Thread(target=lambda: fine.wait(secondi), daemon=True)
        t.start()
        amelie._lavoro = t
        return fine

    def test_si_aspetta_che_finisca(self, amelie):
        fine = self._occupa(amelie, 5)
        amelie.macchina.stato = Stato.SCANSIONE
        fatto = threading.Event()
        amelie._avvia(fatto.set)
        assert amelie.macchina.stato is Stato.SCANSIONE, "non e' un guasto"
        fine.set()
        assert fatto.wait(3), "finito il lavoro precedente, il nuovo parte"

    def test_se_non_finisce_e_un_guasto(self, amelie, monkeypatch):
        from amelie import app as modulo
        monkeypatch.setattr(modulo, "ATTESA_DEL_LAVORO_S", 0.1)
        self._occupa(amelie, 5)
        amelie.macchina.stato = Stato.SCANSIONE
        amelie._avvia(lambda: pytest.fail("non doveva partire"))
        amelie._lavoro.join(2)
        assert amelie.macchina.stato is Stato.GUASTO

    def test_se_intanto_la_bottiglia_e_stata_tolta_non_parte(self, amelie):
        fine = self._occupa(amelie, 5)
        amelie.macchina.stato = Stato.SCANSIONE
        amelie._avvia(lambda: pytest.fail("nessuno lo aspetta piu'"))
        amelie.macchina.stato = Stato.ATTESA
        fine.set()
        amelie._lavoro.join(2)
        assert amelie.macchina.stato is Stato.ATTESA


class TestIlRipristinoRiapreIlRouter:
    def test_la_connessione_col_router_si_chiude(self, amelie):
        """La connessione col router e' una sola e resta aperta: il ripristino
        la chiude, e la prossima chiamata ne apre una pulita."""
        chiusure = []
        amelie.ponte.chiudi = lambda: chiusure.append(1)
        assert amelie.ripristina("prova")["ok"]
        assert chiusure == [1]
