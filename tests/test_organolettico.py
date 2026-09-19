"""Test della resa in inglese delle citazioni dei disciplinari.

Due cose vanno sorvegliate, e sono di natura diversa.

La prima è che le regole compongano bene: sono poche e ricombinano duecento
atomi in migliaia di citazioni, quindi un errore in una regola non si vede su
un caso, si vede su mille. I casi qui sotto sono presi dal database vero.

La seconda, più importante, è che non si inventi niente. Una citazione di un
disciplinare è una fonte: può uscire più corta, non può uscire diversa. Il test
di copertura legge tutte le 6.363 citazioni del database e verifica che la resa
non peggiori sotto una soglia misurata, così se qualcuno tocca il vocabolario e
rompe una regola il conto lo dice subito.
"""

import sqlite3
from pathlib import Path

import pytest

from amelie.organolettico import AMBITI, carica

RADICE = Path(__file__).resolve().parents[1]
DB = RADICE / "data" / "amelie.db"


def c_e_il_registro() -> bool:
    """Le citazioni arrivano dalla fusione: un archivio più vecchio non ha
    ancora la tabella, e il test di copertura non ha niente da contare."""
    if not DB.exists():
        return False
    c = sqlite3.connect(DB)
    try:
        return bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tipologia_ue'"
        ).fetchone())
    finally:
        c.close()


@pytest.fixture(scope="module")
def voc():
    return carica()


# ------------------------------------------------------------- composizione

class TestComposizione:
    def test_termine_semplice(self, voc):
        assert voc.rendi("rosso rubino", "colore").testo == "ruby red"

    def test_elenco(self, voc):
        r = voc.rendi("fruttato, tipico, gradevole", "odore")
        assert r.testo == "fruity, typical and pleasant"

    def test_aggettivo_secco_passa_davanti(self, voc):
        """L'italiano dice «rosso rubino intenso», l'inglese «deep ruby red»."""
        assert voc.rendi("rosso rubino intenso", "colore").testo == "deep ruby red"

    def test_modificatore_lungo_resta_dietro(self, voc):
        r = voc.rendi("giallo paglierino più o meno intenso", "colore")
        assert r.testo == "straw yellow, more or less deep"

    def test_intervallo(self, voc):
        assert voc.rendi("dal secco al dolce", "sapore").testo == "from dry to sweet"

    def test_intervallo_con_ad(self, voc):
        """«ad» davanti a vocale: se l'alternativa lo perde, l'intervallo si
        spezza dentro la parola e il senso cambia."""
        assert voc.rendi("da secco ad abboccato", "sapore").testo == "from dry to off-dry"

    def test_tendenza_e_invecchiamento(self, voc):
        r = voc.rendi("rosso rubino carico tendente al granato con l'invecchiamento", "colore")
        assert r.testo == "deep ruby red, tending to garnet with age"

    def test_riflessi_il_nome_passa_dietro(self, voc):
        r = voc.rendi("con riflessi dorati o verdognoli", "colore")
        assert r.testo == "with golden or greenish highlights"

    def test_riflessi_col_predicato_non_si_rovesciano(self, voc):
        r = voc.rendi("con eventuali riflessi tendenti al granato", "colore")
        assert r.testo == "with possible highlights tending to garnet"

    def test_desinenze(self, voc):
        """«ambrati» è «ambrato»: il vocabolario tiene una forma sola."""
        assert voc.rendi("talvolta con riflessi ambrati", "colore").testo == (
            "sometimes with amber highlights"
        )

    def test_la_e_lega_gli_aggettivi_non_separa(self, voc):
        """«con note floreali e fruttate» è un nome con due aggettivi, non due
        voci di elenco: spezzandolo esce «with floral notes and fruity»."""
        r = voc.rendi("intenso, con note floreali e fruttate", "odore")
        assert r.testo == "intense, with floral and fruity notes"

    def test_un_solo_and_in_fondo(self, voc):
        r = voc.rendi("intenso, persistente e armonico", "sapore")
        assert r.testo == "intense, persistent and harmonious"

    def test_di_davanti_a_nome_e_davanti_ad_aggettivo(self, voc):
        assert voc.rendi("di buon corpo", "sapore").testo == "of good body"
        assert voc.rendi("di fruttato", "odore").testo == "fruity"


class TestAmbiti:
    def test_vivace_cambia_senso_col_campo(self, voc):
        """Alla vista è un colore vivido; in bocca è vivacità di gusto.

        Era «lightly sparkling», e su un Menfi bianco fermo il racconto
        inglese dichiarava un'effervescenza che né il disciplinare né i fatti
        affermano: 110 citazioni del registro hanno «vivace» nel sapore, quasi
        tutte su tipologie ferme. «Lively» è vero per tutte e due.
        """
        assert voc.rendi("vivace", "colore").testo == "vivid"
        assert voc.rendi("vivace", "sapore").testo == "lively"

    def test_rosa_colore_e_rosa_fiore(self, voc):
        assert voc.rendi("rosa", "colore").testo == "pink"
        assert voc.rendi("rosa", "odore").testo == "rose"


# --------------------------------------------------------------- prudenza

class TestNonSiInventa:
    def test_frammento_ignoto_cade(self, voc):
        r = voc.rendi("secco, sollecitato dall'estro del cantiniere", "sapore")
        assert r.testo == "dry"
        assert not r.integrale

    def test_niente_da_dire_e_niente(self, voc):
        assert voc.rendi("devono presentare le caratteristiche proprie", "odore") is None
        assert voc.rendi("", "odore") is None

    def test_meta_di_una_congiunzione_si_salva(self, voc):
        """Un elenco si può accorciare: «secco e <prosa>» resta «dry». È il
        contrario dell'intervallo, ed è per questo che i due casi stanno in
        posti diversi del codice."""
        r = voc.rendi("secco e sollecitato dall'estro del cantiniere", "sapore")
        assert r.testo == "dry"
        assert not r.integrale

    def test_intervallo_a_meta_non_esiste(self, voc):
        """Metà di «da secco a dolce» direbbe una cosa che il disciplinare non
        dice. O passa tutto l'intervallo, o non passa niente."""
        r = voc.rendi("da secco a cangiante", "sapore")
        assert r is None

    def test_le_cifre_non_sono_descrizioni(self, voc):
        """Nelle citazioni le cifre sono residui dei minimi di legge."""
        r = voc.rendi("equilibrato, titolo alcolometrico minimo 11", "sapore")
        assert r.testo == "balanced"

    def test_l_italiano_non_si_traduce(self, voc):
        r = voc.rendi("rosso rubino", "colore", lingua="it")
        assert r.testo == "rosso rubino"
        assert not r.tradotto

    def test_l_inglese_e_dichiarato_traduzione(self, voc):
        """«rosso rubino» reso «ruby red» è parola nostra, non del consorzio:
        chi lo mostra deve poterlo dire."""
        assert voc.rendi("rosso rubino", "colore").tradotto


# --------------------------------------------------------------- copertura

@pytest.fixture(scope="module")
def conto(voc):
    """Quante delle citazioni vere passano, e come."""
    if not c_e_il_registro():
        pytest.skip("il registro UE non c'è in archivio")
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    campi = {a: f"desc_{a}" for a in AMBITI}
    totale = integrali = parziali = 0
    for r in c.execute("SELECT desc_colore, desc_odore, desc_sapore FROM tipologia_ue"):
        for ambito, campo in campi.items():
            testo = (r[campo] or "").strip()
            if not testo:
                continue
            totale += 1
            reso = voc.rendi(testo, ambito)
            if reso is None:
                continue
            integrali += reso.integrale
            parziali += not reso.integrale
    c.close()
    return totale, integrali, parziali


@pytest.mark.skipif(not c_e_il_registro(), reason="il registro UE non c'è in archivio")
class TestCopertura:
    def test_quasi_tutte_passano_intere(self, conto):
        totale, integrali, _ = conto
        assert totale > 6000
        assert integrali / totale > 0.83, f"solo {integrali}/{totale} intere"

    def test_quasi_nessuna_si_perde(self, conto):
        totale, integrali, parziali = conto
        perse = totale - integrali - parziali
        assert perse / totale < 0.05, f"{perse}/{totale} perse"
