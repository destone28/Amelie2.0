"""Test della stima di batteria.

Non c'e' nessun dato dalla batteria: si integra la potenza nel tempo. Quello
che si verifica qui e' che il conto torni, che una notte di fermo valga una
ricarica, e che un orologio inattendibile non azzeri la stima per sbaglio.
"""

import json

import pytest

from amelie.batteria import (
    CAPACITA_WH, POTENZA_ANELLO_W, POTENZA_BASE_W, POTENZA_CPU_W, RICARICATA_DOPO_S,
    Batteria,
)


class Orologio:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Cpu:
    """Tick di `/proc/stat` finti: occupato e totale crescono a comando."""

    def __init__(self):
        self.occupato, self.totale = 0, 0

    def __call__(self):
        return self.occupato, self.totale

    def lavora(self, quota, tick=1000):
        self.occupato += int(tick * quota)
        self.totale += tick


@pytest.fixture
def batteria(tmp_path):
    return Batteria(tmp_path / "batteria.json", ora=Orologio(), cpu=Cpu())


class TestIlConto:
    def test_nuova_e_piena(self, batteria):
        batteria.avvia()
        assert batteria.frazione == 1.0
        assert batteria.tacche == 4

    def test_un_ora_a_riposo_costa_la_base(self, batteria):
        batteria.avvia()
        batteria._ora.t += 3600
        batteria._cpu.lavora(0.0)
        batteria.aggiorna()
        assert batteria.consumato_wh == pytest.approx(POTENZA_BASE_W + POTENZA_ANELLO_W, rel=1e-6)

    def test_un_ora_a_cpu_piena_costa_di_piu(self, batteria):
        batteria.avvia()
        batteria._ora.t += 3600
        batteria._cpu.lavora(1.0)
        batteria.aggiorna()
        assert batteria.consumato_wh == pytest.approx(
            POTENZA_BASE_W + POTENZA_ANELLO_W + POTENZA_CPU_W, rel=1e-6)

    def test_le_tacche_scendono_e_l_ultima_sparisce_prima_dello_zero(self, batteria):
        batteria.avvia()
        viste = []
        for _ in range(24):
            batteria._ora.t += 1800
            batteria._cpu.lavora(0.2)
            batteria.aggiorna()
            viste.append(batteria.tacche)
        assert viste[0] == 4 and viste[-1] == 0
        assert viste == sorted(viste, reverse=True), "le tacche non risalgono da sole"
        # A zero tacche resta ancora qualcosa: il power bank puo' spegnersi
        # senza avvisare, e una tacca accesa sarebbe una bugia.
        primo_zero = next(i for i, t in enumerate(viste) if t == 0)
        assert 0 < (CAPACITA_WH - (primo_zero + 1) * 0.5 * (POTENZA_BASE_W + 0.2 * POTENZA_CPU_W))

    def test_dichiararla_ricaricata_la_riporta_a_piena(self, batteria):
        batteria.avvia()
        batteria._ora.t += 7200
        batteria.aggiorna()
        assert batteria.frazione < 1.0
        batteria.ricaricata()
        assert batteria.frazione == 1.0
        assert json.loads(batteria.percorso.read_text())["consumato_wh"] == 0.0


class TestQuandoSiAzzera:
    def _spegni_e_riaccendi(self, tmp_path, fermo_s):
        orologio, cpu = Orologio(), Cpu()
        prima = Batteria(tmp_path / "b.json", ora=orologio, cpu=cpu)
        prima.avvia()
        orologio.t += 4 * 3600
        prima.aggiorna()
        prima.salva()
        spesi = prima.consumato_wh
        orologio.t += fermo_s
        dopo = Batteria(tmp_path / "b.json", ora=orologio, cpu=cpu)
        dopo.avvia()
        return spesi, dopo

    def test_una_notte_di_fermo_vale_una_ricarica(self, tmp_path):
        spesi, dopo = self._spegni_e_riaccendi(tmp_path, RICARICATA_DOPO_S + 60)
        assert spesi > 0
        assert dopo.consumato_wh == 0.0

    def test_un_riavvio_a_meta_servizio_riprende_da_dov_era(self, tmp_path):
        spesi, dopo = self._spegni_e_riaccendi(tmp_path, 120)
        assert dopo.consumato_wh == pytest.approx(spesi)

    def test_un_orologio_che_torna_indietro_non_azzera(self, tmp_path):
        """Senza rete la board puo' ripartire da una data qualunque: il salto
        negativo non e' una notte, e la stima si tiene."""
        spesi, dopo = self._spegni_e_riaccendi(tmp_path, -50_000)
        assert dopo.consumato_wh == pytest.approx(spesi)

    def test_un_salto_assurdo_non_azzera(self, tmp_path):
        spesi, dopo = self._spegni_e_riaccendi(tmp_path, 400 * 86400)
        assert dopo.consumato_wh == pytest.approx(spesi)

    def test_un_file_rotto_non_ferma_niente(self, tmp_path):
        f = tmp_path / "b.json"
        f.write_text("{non json")
        b = Batteria(f, ora=Orologio(), cpu=Cpu())
        b.avvia()
        assert b.frazione == 1.0
