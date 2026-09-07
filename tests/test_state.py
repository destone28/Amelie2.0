"""Test della macchina a stati dell'interazione.

Questa è la parte che si collauda per intero senza hardware, ed è quella che
in sala si rompe nei modi più imbarazzanti: il dispositivo che continua a
parlare di un vino che non c'è più, quello che si pianta perché il sensore ha
rimbalzato, quello che non riparte dopo un errore.
"""

import pytest

from amelie.state import (
    DURATE_S,
    EFFETTI_INGRESSO,
    EFFETTI_USCITA,
    TRANSIZIONI,
    Effetto,
    Evento,
    Macchina,
    Stato,
)


def porta_a(stato: Stato) -> Macchina:
    """Guida la macchina fino allo stato voluto, per il ciclo normale."""
    m = Macchina()
    cammino = {
        Stato.ATTESA: [],
        Stato.ASSESTAMENTO: [Evento.BOTTIGLIA_PRESENTE],
        Stato.SCANSIONE: [Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA],
        Stato.RICONOSCIMENTO: [
            Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA, Evento.LETTURA_RIUSCITA],
        Stato.CONFERMA: [
            Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA, Evento.LETTURA_RIUSCITA,
            Evento.MATCH_DUBBIO],
        Stato.RACCONTO: [
            Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA, Evento.LETTURA_RIUSCITA,
            Evento.MATCH_SICURO],
        Stato.CONCLUSO: [
            Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA, Evento.LETTURA_RIUSCITA,
            Evento.MATCH_SICURO, Evento.RACCONTO_FINITO],
        Stato.RIPOSIZIONA: [
            Evento.BOTTIGLIA_PRESENTE, Evento.SCADENZA, Evento.LETTURA_FALLITA],
    }[stato]
    for e in cammino:
        m.invia(e)
    assert m.stato is stato
    return m


class TestCicloNormale:
    def test_dall_attesa_al_racconto(self):
        m = porta_a(Stato.CONCLUSO)
        percorso = [t.a for t in m.storia]
        assert percorso == [
            Stato.ASSESTAMENTO,
            Stato.SCANSIONE,
            Stato.RICONOSCIMENTO,
            Stato.RACCONTO,
            Stato.CONCLUSO,
        ]

    def test_parte_in_attesa(self):
        assert Macchina().stato is Stato.ATTESA

    def test_togliere_la_bottiglia_chiude_il_ciclo(self):
        m = porta_a(Stato.CONCLUSO)
        assert m.invia(Evento.BOTTIGLIA_ASSENTE).a is Stato.ATTESA


class TestBottigliaTolta:
    @pytest.mark.parametrize(
        "stato",
        [s for s in Stato if s not in (Stato.ATTESA, Stato.GUASTO)],
    )
    def test_torna_sempre_in_attesa(self, stato):
        m = porta_a(stato)
        assert m.invia(Evento.BOTTIGLIA_ASSENTE).a is Stato.ATTESA

    def test_zittisce_il_racconto(self):
        """Il difetto peggiore possibile: parlare di un vino tolto dal tavolo."""
        m = porta_a(Stato.RACCONTO)
        t = m.invia(Evento.BOTTIGLIA_ASSENTE)
        assert Effetto.FERMA_RACCONTO in t.effetti

    def test_non_zittisce_se_non_stava_parlando(self):
        m = porta_a(Stato.SCANSIONE)
        t = m.invia(Evento.BOTTIGLIA_ASSENTE)
        assert Effetto.FERMA_RACCONTO not in t.effetti

    def test_in_attesa_non_fa_niente(self):
        m = Macchina()
        t = m.invia(Evento.BOTTIGLIA_ASSENTE)
        assert not t.cambia_stato


class TestDeviazioni:
    def test_etichetta_illeggibile_chiede_di_riposizionare(self):
        m = porta_a(Stato.SCANSIONE)
        t = m.invia(Evento.LETTURA_FALLITA)
        assert t.a is Stato.RIPOSIZIONA
        assert Effetto.MOSTRA_RIPOSIZIONA in t.effetti

    def test_dopo_riposiziona_si_ritenta(self):
        m = porta_a(Stato.RIPOSIZIONA)
        assert m.invia(Evento.SCADENZA).a is Stato.SCANSIONE

    def test_match_dubbio_chiede_conferma(self):
        m = porta_a(Stato.CONFERMA)
        assert Effetto.MOSTRA_CANDIDATI in m.storia[-1].effetti

    def test_conferma_senza_tocco_racconta_lo_stesso(self):
        """Meglio il candidato più probabile che restare fermi."""
        m = porta_a(Stato.CONFERMA)
        assert m.invia(Evento.SCADENZA).a is Stato.RACCONTO

    def test_match_assente_racconta_comunque(self):
        """Il fallback onesto: denominazione, o vitigno, non silenzio."""
        m = porta_a(Stato.RICONOSCIMENTO)
        assert m.invia(Evento.MATCH_ASSENTE).a is Stato.RACCONTO

    def test_ripetizione_a_racconto_concluso(self):
        m = porta_a(Stato.CONCLUSO)
        t = m.invia(Evento.RIPETI)
        assert t.a is Stato.RACCONTO
        assert Effetto.AVVIA_RACCONTO in t.effetti


class TestRobustezza:
    @pytest.mark.parametrize("stato", list(Stato))
    def test_un_errore_e_sempre_gestito(self, stato):
        m = Macchina(stato=stato)
        assert m.invia(Evento.ERRORE).a is Stato.GUASTO

    def test_dal_guasto_si_torna_in_attesa(self):
        m = Macchina(stato=Stato.GUASTO)
        assert m.invia(Evento.SCADENZA).a is Stato.ATTESA

    @pytest.mark.parametrize("stato", list(Stato))
    @pytest.mark.parametrize("evento", list(Evento))
    def test_nessun_evento_solleva_eccezioni(self, stato, evento):
        """Il sensore rimbalza e l'utente tocca a caso: non ci si pianta."""
        m = Macchina(stato=stato)
        t = m.invia(evento)
        assert isinstance(t.a, Stato)

    def test_evento_senza_senso_lascia_lo_stato(self):
        m = Macchina()
        t = m.invia(Evento.RACCONTO_FINITO)   # non stava raccontando
        assert not t.cambia_stato
        assert m.stato is Stato.ATTESA

    def test_rimbalzo_del_sensore(self):
        """Presente/assente in rapida successione non deve incastrare nulla."""
        m = Macchina()
        for _ in range(20):
            m.invia(Evento.BOTTIGLIA_PRESENTE)
            m.invia(Evento.BOTTIGLIA_ASSENTE)
        assert m.stato is Stato.ATTESA

    def test_reimposta(self):
        m = porta_a(Stato.RACCONTO)
        m.reimposta()
        assert m.stato is Stato.ATTESA
        assert m.storia == []


class TestOsservabilita:
    def test_richiama_il_gancio(self):
        visti = []
        m = Macchina(su_transizione=visti.append)
        m.invia(Evento.BOTTIGLIA_PRESENTE)
        assert len(visti) == 1
        assert visti[0].a is Stato.ASSESTAMENTO

    def test_registra_la_storia(self):
        m = porta_a(Stato.CONCLUSO)
        assert len(m.storia) == 5

    @pytest.mark.parametrize(
        "stato, occupata",
        [
            (Stato.ATTESA, False),
            (Stato.SCANSIONE, True),
            (Stato.RICONOSCIMENTO, True),
            (Stato.RACCONTO, True),
            (Stato.CONFERMA, False),
            (Stato.CONCLUSO, False),
        ],
    )
    def test_sa_quando_la_cpu_e_occupata(self, stato, occupata):
        assert Macchina(stato=stato).sta_elaborando is occupata


class TestCoerenzaDelleTabelle:
    def test_ogni_stato_raggiungibile_ha_effetti(self):
        for stato in Stato:
            assert stato in EFFETTI_INGRESSO, f"{stato} non ha effetti d'ingresso"

    def test_ogni_stato_ha_una_durata_dichiarata(self):
        for stato in Stato:
            assert stato in DURATE_S, f"{stato} non dichiara una durata"

    def test_gli_stati_a_tempo_hanno_una_via_d_uscita(self):
        """Uno stato con un timer deve reagire a SCADENZA, o resta bloccato."""
        for stato, durata in DURATE_S.items():
            if durata is not None:
                assert (stato, Evento.SCADENZA) in TRANSIZIONI, (
                    f"{stato} scade dopo {durata}s ma non gestisce SCADENZA"
                )

    def test_assestamento_abbastanza_lungo_da_fermare_l_oscillazione(self):
        assert 0.4 <= DURATE_S[Stato.ASSESTAMENTO] <= 1.0


class TestRientro:
    """Una regola verso lo stesso stato deve fare qualcosa, o non serve scriverla.

    La macchina trattava allo stesso modo due cose diverse: un evento che nello
    stato corrente non significa niente, e una transizione scritta apposta verso
    lo stesso stato. La prima deve restare inerte, la seconda no.

    Il difetto non si vedeva: `(RACCONTO, RIPETI) -> RACCONTO` era dichiarata e
    non produceva alcun effetto, quindi ripetere il racconto o cambiare lingua
    mentre parlava non faceva assolutamente nulla. Nessun errore, nessun
    messaggio, nessuna traccia nei registri.
    """

    def test_un_evento_senza_regola_resta_inerte(self):
        m = Macchina()
        assert m.stato is Stato.ATTESA
        t = m.invia(Evento.RACCONTO_FINITO)      # qui non significa niente
        assert t.a is Stato.ATTESA
        assert not t.effetti
        assert not t.cambia_stato and not t.rientro

    def test_una_regola_verso_se_stesso_esegue_gli_effetti(self):
        m = Macchina()
        m.stato = Stato.RACCONTO
        t = m.invia(Evento.RIPETI)
        assert t.a is Stato.RACCONTO
        assert not t.cambia_stato, "lo stato non cambia"
        assert t.rientro, "ma la transizione e' dichiarata, quindi vale"
        assert Effetto.FERMA_RACCONTO in t.effetti, "manca l'uscita"
        assert Effetto.AVVIA_RACCONTO in t.effetti, "manca l'ingresso"

    def test_ogni_regola_verso_se_stesso_ha_effetti(self):
        """Una regola del genere senza effetti sarebbe una riga morta."""
        for (da, evento), a in TRANSIZIONI.items():
            if da is not a:
                continue
            effetti = EFFETTI_USCITA.get(da, ()) + EFFETTI_INGRESSO.get(a, ())
            assert effetti, (
                f"({da.value}, {evento.value}) -> {a.value} non fa niente: "
                "o le si danno degli effetti o la si toglie")
