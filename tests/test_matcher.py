"""Test del riconoscimento.

Servono il database costruito (`python3 data/build_db.py`) e `rapidfuzz`: senza,
i test si saltano invece di fallire, perché un ambiente pulito non ha ancora né
l'uno né l'altro.

I casi qui dentro sono quelli che contano per il prodotto: la cascata che scende
al livello giusto, la sicurezza che NON dichiara certo ciò che certo non è, e i
vitigni ammessi dal disciplinare che non devono mai finire fra i fatti
raccontabili.
"""

import pytest

pytest.importorskip("rapidfuzz")

from amelie.matcher import (  # noqa: E402
    SOGLIA_CERTA,
    SOGLIA_DUBBIA,
    DatabaseAssente,
    Fatti,
    Livello,
    Matcher,
)


@pytest.fixture(scope="module")
def m():
    try:
        matcher = Matcher()
    except DatabaseAssente as e:
        pytest.skip(str(e))
    yield matcher
    matcher.chiudi()


class TestCascata:
    def test_etichetta_completa_arriva_al_vino(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "Barolo", "Denominazione di Origine",
                     "Controllata e Garantita", "2016"])
        assert f.livello in (Livello.VINO, Livello.TIPOLOGIA)
        assert f.denominazione and "barolo" in f.denominazione.lower()

    def test_solo_denominazione_scende_alla_tipologia(self, m):
        """Senza produttore leggibile si racconta comunque la denominazione."""
        f = m.cerca(["AMARONE DELLA VALPOLICELLA", "Denominazione di Origine"])
        assert f.livello in (Livello.TIPOLOGIA, Livello.DENOMINAZIONE, Livello.VINO)
        assert "amarone" in (f.denominazione or f.tipologia or "").lower()

    def test_solo_vitigno_scende_al_vitigno(self, m):
        f = m.cerca(["Nebbiolo"])
        assert f.livello in (Livello.VITIGNO, Livello.DENOMINAZIONE, Livello.TIPOLOGIA)

    def test_testo_vuoto_non_inventa(self, m):
        assert m.cerca([]).livello is Livello.NULLA
        assert m.cerca(["", "  "]).livello is Livello.NULLA

    def test_solo_rumore_non_inventa(self, m):
        """Le parole che stanno su ogni etichetta non identificano nulla."""
        f = m.cerca(["CONTIENE SOLFITI", "PRODOTTO IN ITALIA", "750 ml", "13,5% vol"])
        assert f.livello is Livello.NULLA

    def test_annata_estratta(self, m):
        f = m.cerca(["Chianti Classico", "2019"])
        assert f.annata == 2019


class TestSicurezza:
    def test_non_dichiara_certo_un_produttore_diverso(self, m):
        """Il caso che generava figuracce: 'Monte Antico' -> 'Monte Giove'.

        Un nome simile a metà non deve MAI produrre un match certo su un vino
        commerciale, perché quello impegna il produttore.
        """
        f = m.cerca(["MONTE ANTICO", "Toscana", "Rosso"])
        if f.livello is Livello.VINO and f.cantina:
            assert "antico" in f.cantina.lower() or not f.certo

    def test_una_parola_sola_non_basta_per_essere_certi(self, m):
        f = m.cerca(["Rosso"])
        assert not f.certo

    def test_soglie_coerenti(self):
        assert SOGLIA_DUBBIA < SOGLIA_CERTA

    def test_le_tre_fasce_si_escludono(self, m):
        f = m.cerca(["Barolo", "Marchesi di Barolo"])
        assert not (f.certo and f.dubbio)


class TestVitigniAmmessi:
    """Il cuore dell'anti-invenzione."""

    def test_amarone_non_dichiara_croatina(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA", "Classico"])
        if f.vitigni:
            assert "Croatina" not in f.vitigni, (
                "Croatina e' AMMESSA dal disciplinare, non imposta: dirla presente"
                " e' falso"
            )

    def test_gli_ammessi_restano_fuori_dal_blocco_fatti(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA"])
        blocco = f.blocco_fatti()
        for ammesso in f.vitigni_ammessi:
            assert ammesso not in blocco, (
                f"{ammesso!r} e' solo ammesso: il modello non deve nemmeno vederlo"
            )

    def test_amarone_ha_i_vitigni_giusti(self, m):
        f = m.cerca(["AMARONE DELLA VALPOLICELLA"])
        if f.livello is Livello.TIPOLOGIA and f.vitigni:
            assert any("corvina" in v.lower() for v in f.vitigni)


class TestBloccoFatti:
    def test_salta_i_campi_vuoti(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        blocco = f.blocco_fatti()
        assert "Barolo" in blocco
        assert "Produttore" not in blocco
        assert "None" not in blocco

    def test_una_riga_per_campo(self):
        f = Fatti(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi",
                  annata=2016, vitigni=["Nebbiolo"])
        righe = f.blocco_fatti().split("\n")
        assert len(righe) == 4
        assert all(":" in r for r in righe)

    def test_fatti_vuoti_danno_blocco_vuoto(self):
        assert Fatti().blocco_fatti() == ""


class TestRobustezza:
    def test_apici_e_trattini_non_rompono_la_query(self, m):
        """FTS5 interpreta la punteggiatura come sintassi se non e' quotata."""
        for testo in ["Ca' del Bosco", "Montepulciano d'Abruzzo",
                      'virgolette "strane"', "meno - meno", "*", "AND OR NOT"]:
            assert m.cerca([testo]) is not None

    def test_testo_lunghissimo(self, m):
        assert m.cerca(["Barolo " * 500]) is not None

    def test_caratteri_non_latini(self, m):
        assert m.cerca(["日本語", "Ελληνικά", "кириллица"]) is not None

    def test_database_in_sola_lettura(self, m):
        import sqlite3
        with pytest.raises(sqlite3.OperationalError):
            m.con.execute("DELETE FROM vino")


class TestCandidati:
    def test_propone_alternative_per_la_conferma(self, m):
        f = m.cerca(["Chianti"])
        assert len(f.candidati) <= 3

    def test_le_alternative_sono_diverse_fra_loro(self, m):
        f = m.cerca(["Barolo"])
        assert len(f.candidati) == len(set(f.candidati))

    def test_le_alternative_sono_leggibili_da_una_persona(self, m):
        """Sullo schermo di un ristorante non si mostra l'indice di ricerca.

        Le voci dell'indice sono normalizzate - minuscole, senza punteggiatura -
        e mostrarle tali e quali significava proporre all'ospite di scegliere
        fra "barolo cannubi marchesi di barolo" e "barolo bussia tenuta rocca".
        """
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI"])
        for voce in f.candidati:
            assert voce != voce.lower() or not voce.isascii(), \
                f"{voce!r} sembra il testo normalizzato dell'indice"

    def test_ogni_alternativa_sa_a_quale_record_corrisponde(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI"])
        assert len(f.riferimenti) == len(f.candidati)

    def test_scegliere_un_alternativa_da_proprio_quel_record(self, m):
        """Ricercare il NOME del candidato poteva riportare a un altro vino."""
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI"])
        if not f.riferimenti:
            pytest.skip("nessuna alternativa da questa etichetta")
        scelto = m.fatti_di(*f.riferimenti[0])
        assert not scelto.vuoto
        assert scelto.sicurezza == 100.0, "l'ha scelto una persona: e' certo"
        atteso = f.candidati[0].split(" — ")[0]
        trovato = " ".join(filter(None, [scelto.nome, scelto.tipologia,
                                         scelto.denominazione]))
        assert atteso in trovato or trovato in atteso, \
            f"toccato {atteso!r}, composto {trovato!r}"


class TestFigureBrutte:
    """I casi veri che hanno prodotto un'affermazione sbagliata a schermo.

    Ognuno viene da un'etichetta fotografata davvero, e ognuno e' costato una
    modifica al calcolo della sicurezza. Stanno qui perche' non tornino.
    """

    def test_un_refuso_non_deve_far_perdere_il_record_giusto(self, m):
        """«TINUTA ROCCA BAROLO BUSSIA»: una lettera sbagliata su «Tenuta».

        token_set_ratio e' tutto-o-niente sui token: bastava quella «i» per far
        crollare «tenuta rocca barolo bussia» a 58.8, mentre un altro
        produttore chiamato semplicemente «Rocca» prendeva 100 con la sua unica
        parola. Vinceva il record che spiegava UNA parola su sette.
        """
        f = m.cerca(["TINUTA", "ROCCA", "BAROLO", "BUSSIA", "2010",
                     "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA"])
        nome = (f.nome or "").lower()
        cantina = (f.cantina or "").lower()
        assert "bussia" in nome or "bussia" in f"{nome} {cantina}", \
            f"riconosciuto {cantina!r} / {nome!r}"

    def test_due_produttori_vicini_non_si_dichiarano_certi(self, m):
        """«Monte Antico» contro «Monte Giove»: 90 contro 87.6.

        Il primo classificato era il produttore SBAGLIATO, e quello giusto
        stava 2.4 punti sotto. Con due nomi cosi' vicini il dispositivo non
        riconosce: sceglie a caso. Deve chiedere.
        """
        f = m.cerca(["Monte", "Antico", "Toscana", "Indicacsione Gecgafica Tipica",
                     "Sangiovese, Merlot", "and Cabernet Saucignon", "Red Wine"])
        if f.cantina and "antico" not in f.cantina.lower():
            assert not f.certo, (
                f"dichiarato certo il produttore {f.cantina!r} mentre "
                f"l'etichetta dice «Monte Antico»")

    def test_i_punti_fra_le_parole_non_le_incollano(self, m):
        """«COMM.G.B.BURLOTTO»: l'OCR legge i punti, non gli spazi.

        Togliendo ogni punto quella riga diventava l'unico token
        «commgbburlotto», mentre lo stesso produttore in archivio - scritto
        «Comm. G.B. Burlotto», con gli spazi - era «comm gb burlotto». Lo
        stesso nome in due forme diverse: il suo Barolo Vigneto Cannubi era
        nel database e non veniva trovato. Vinceva invece «Ca'Stella», che si
        accontentava della «Stella Polare» stampata sulla retroetichetta, e si
        dichiarava CERTA con 92.
        """
        f = m.cerca(["Barole", "CANNUBI", "COMM.G.B.BURLOTTO",
                     "Imbottigliato da Burlotto Marina", "VERDUNO", "ITALIA",
                     "unici provveditori della Real Casa",
                     "spedizione Duca degli Abruzzi al Polo Nord",
                     "nel 1899 con la Stella Polare"])
        assert "burlotto" in (f.cantina or "").lower(), \
            f"riconosciuto il produttore {f.cantina!r}"

    def test_una_parola_della_retroetichetta_non_conferma_un_produttore(self, m):
        """L'altro capo dello stesso caso, isolato.

        Senza le righe che nominano Burlotto, «stella» resta l'unico appiglio:
        una parola sola, presa da un testo di retro, non puo' bastare a
        dichiarare certo un produttore.
        """
        f = m.cerca(["Barole", "CANNUBI", "VERDUNO", "ITALIA",
                     "unici provveditori della Real Casa",
                     "spedizione Duca degli Abruzzi al Polo Nord",
                     "nel 1899 con la Stella Polare"])
        cantina = (f.cantina or "").lower()
        assert not (f.certo and "stella" in cantina), (
            f"dichiarato certo {f.cantina!r} ({f.sicurezza:.0f}) su una parola "
            "di retroetichetta")

    def test_un_vino_di_una_parola_non_basta_a_se_stesso(self, m):
        """Un record «Rocca»/«Rocca» spiegava una parola e diceva 100."""
        f = m.cerca(["ROCCA"])
        assert not f.certo, "una parola sola non puo' identificare un produttore"


class TestVerificaCompleta:
    def test_si_verificano_tutti_i_candidati_non_solo_i_primi(self):
        """Chi resta fuori dalla verifica conserva il punteggio gonfiato.

        La verifica ABBASSA i punteggi. Fermarsi ai primi 25 su 200 voleva dire
        che il 26esimo, mai esaminato, poteva scavalcare tutti dopo il riordino
        e presentarsi come certo senza aver mai superato l'esame.
        """
        from amelie.matcher import CANDIDATI, VERIFICATI
        assert VERIFICATI >= CANDIDATI


class TestRipiego:
    """Ogni bottiglia deve poter ricadere sul suo vino generico.

    Un vino commerciale e' uno di diciannovemila, e per quasi tutti non c'e'
    niente da dire che non sia gia' vero del loro vino generico. Il ripiego
    scende per IDENTIFICATIVO, non ricercando il nome: cercare "Primitivo di
    Manduria" fra i nomi puo' riportare al vino di un altro produttore.
    """

    def test_i_fatti_sanno_da_quale_record_vengono(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        assert f.origine is not None
        ambito, ident = f.origine
        assert ambito in ("vino", "tipologia", "denominazione", "vitigno")
        assert isinstance(ident, int)

    def test_un_vino_ricade_sul_suo_generico(self, m):
        """Il caso raccontato: il Primitivo di Manduria di un produttore."""
        f = m.cerca(["Cooperativa Produttori Vini Manduria",
                     "PRIMITIVO DI MANDURIA", "2019"])
        ambiti = [a for a, _ in f.ripiego]
        assert "tipologia" in ambiti or "denominazione" in ambiti, \
            f"nessun gradino generico nella catena: {f.ripiego}"

    def test_la_catena_scende_dal_specifico_al_generico(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        ordine = {"vino": 0, "tipologia": 1, "denominazione": 2, "vitigno": 3}
        gradi = [ordine[a] for a, _ in f.ripiego]
        assert gradi == sorted(gradi), f"la catena non scende: {f.ripiego}"

    def test_la_tipologia_scelta_e_quella_che_somiglia_di_piu(self, m):
        """Una denominazione ha spesso una base e una Riserva.

        Prendere la prima a caso significherebbe raccontare una Riserva per un
        vino base, o viceversa.
        """
        f = m.cerca(["Cooperativa Produttori Vini Manduria",
                     "PRIMITIVO DI MANDURIA", "2019"])
        tipologie = [i for a, i in f.ripiego if a == "tipologia"]
        if not tipologie:
            pytest.skip("questa etichetta non passa da una tipologia")
        nome = m.con.execute("SELECT nome FROM tipologia WHERE id=?",
                             (tipologie[0],)).fetchone()[0]
        assert "riserva" not in nome.lower(), \
            f"scelta la tipologia {nome!r} per un'etichetta che non la nomina"

    def test_ogni_gradino_esiste_davvero(self, m):
        for righe in (["Chianti Classico"], ["Etna Rosso"], ["Nebbiolo"],
                      ["MARCHESI DI BAROLO", "BAROLO", "CANNUBI"]):
            f = m.cerca(righe)
            for ambito, ident in f.ripiego:
                assert m.con.execute(
                    f"SELECT 1 FROM {ambito} WHERE id=?", (ident,)).fetchone(), \
                    f"{ambito}/{ident} non esiste, da {righe}"


class TestDueLingue:
    def test_i_fatti_portano_la_scheda_in_entrambe_le_lingue(self, m):
        """Cosi' l'ospite cambia lingua senza rifare la scansione."""
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        assert f.nota_in("it"), "manca la scheda italiana"
        assert f.nota_in("en"), "manca la scheda inglese"
        assert f.nota_in("it") != f.nota_in("en")

    def test_una_lingua_assente_ripiega_su_quella_che_c_e(self, m):
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        assert f.nota_in("de") == f.note_vitigno

    def test_gli_abbinamenti_del_vino_valgono_in_tutte_le_lingue(self, m):
        """Non si sente il vino in italiano e l'uva in inglese.

        La scheda del vitigno SUBENTRA solo dove il vino non ha nulla di suo, e
        la sostituzione dev'essere la stessa in ogni lingua: altrimenti la
        stessa bottiglia dava due risposte diverse alla stessa domanda.
        """
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        if not f.abbinamenti:
            pytest.skip("questo vino non ha abbinamenti propri")
        assert len(f.abbinamenti_in("en")) == len(f.abbinamenti)
