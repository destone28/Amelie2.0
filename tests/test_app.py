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
