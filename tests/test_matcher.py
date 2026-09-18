"""Test del riconoscimento.

Servono il database costruito (`python3 data/build_db.py`) e `rapidfuzz`: senza,
i test si saltano invece di fallire, perché un ambiente pulito non ha ancora né
l'uno né l'altro.

I casi qui dentro sono quelli che contano per il prodotto: la cascata che scende
al livello giusto, la sicurezza che NON dichiara certo ciò che certo non è, e i
vitigni ammessi dal disciplinare che non devono mai finire fra i fatti
raccontabili.
"""

import re

import pytest

pytest.importorskip("rapidfuzz")

from amelie.matcher import (  # noqa: E402
    SOGLIA_CERTA,
    SOGLIA_DUBBIA,
    Candidato,
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


class TestProduttoreLetto:
    """Un produttore non si nomina se non lo si e' letto.

    E' la regola che questo dispositivo deve piu' di ogni altra a chi sta
    seduto al tavolo. Su una bottiglia c'e' scritto «Primitivo di Manduria» e
    basta: quel vino lo fanno centinaia di aziende, e sceglierne una vuol dire
    inventare un nome davanti a un ospite. Cio' che il dispositivo puo' dire e'
    che cos'e' - e lo dice benissimo, perche' la descrizione della tipologia
    parla del vitigno, del disciplinare e della zona, ed e' vera per tutte
    quelle bottiglie.

    Misurato su 1200 etichette costruite dalle tipologie del database, lunghe
    abbastanza da non essere protette dal tetto sulle parole:

        prima    1179 generiche, 21 attribuite a un produttore, 1 CERTA
        dopo     1200 generiche,  0 attribuite,                  0 certe

    La certa era «Brunello di Montalcino» dato a «Vigna Italia» con 100, da
    un'etichetta dove la parola «vigna» era quella del disciplinare.
    """

    def test_una_denominazione_da_sola_non_si_attribuisce_a_nessuno(self, m):
        """Il caso raccontato: «Primitivo di Manduria» e nient'altro."""
        f = m.cerca(["PRIMITIVO DI MANDURIA", "DENOMINAZIONE DI ORIGINE CONTROLLATA",
                     "2019", "14% VOL", "CONTIENE SOLFITI"], anno_massimo=2026)
        assert not f.cantina, f"attribuito a {f.cantina!r} senza averlo letto"
        assert "manduria" in (f.tipologia or f.denominazione or "").lower()

    def test_il_produttore_non_si_fa_confermare_dalle_parole_del_vino(self, m):
        """«Barolo del Comune di Serralunga d'Alba», dato a «Terre del Barolo».

        Il produttore prendeva 88 e si dichiarava certo perche' il suo nome
        contiene «Barolo», che sull'etichetta c'e' - ma come denominazione, non
        come firma. Due conferme indipendenti che erano la stessa parola.
        """
        f = m.cerca(["BAROLO DEL COMUNE DI SERRALUNGA D'ALBA",
                     "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA",
                     "2019", "13,5% VOL"], anno_massimo=2026)
        assert not f.cantina, f"attribuito a {f.cantina!r}"

    def test_una_parola_del_disciplinare_non_fa_una_cantina(self, m):
        """«Vigna» sull'etichetta non e' l'azienda «Vigna Italia»."""
        f = m.cerca(["BRUNELLO DI MONTALCINO", "VIGNA",
                     "DENOMINAZIONE DI ORIGINE PROTETTA", "2019",
                     "IMBOTTIGLIATO ALL'ORIGINE", "13,5% VOL",
                     "CONTIENE SOLFITI"], anno_massimo=2026)
        assert not (f.certo and f.cantina), \
            f"dichiarato certo {f.cantina!r} con {f.sicurezza:.0f}"

    def test_quando_il_produttore_c_e_il_vino_si_riconosce(self, m):
        """L'altro lato: la regola non deve rendere il dispositivo cieco.

        Misurato su 500 etichette complete: 498 col produttore giusto, 461
        dichiarate certe, nessuna attribuita al produttore sbagliato - dove
        prima ce n'era una, per giunta dichiarata certa con 93.
        """
        f = m.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI",
                     "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA", "2016"],
                    anno_massimo=2026)
        assert "barolo" in (f.cantina or "").lower(), \
            f"non riconosciuto: {f.cantina!r} / {f.nome!r}"
        assert f.certo

    def test_scendendo_al_generico_il_racconto_resta_pieno(self, m):
        """Generico non vuol dire povero: sotto c'e' ancora tutto da dire."""
        f = m.cerca(["PRIMITIVO DI MANDURIA", "DENOMINAZIONE DI ORIGINE CONTROLLATA",
                     "2019", "14% VOL", "CONTIENE SOLFITI"], anno_massimo=2026)
        assert f.livello is not Livello.NULLA
        assert f.vitigni or f.note_vitigno, "nessun fatto da raccontare"
        assert f.origine is not None and f.ripiego

    def test_le_parole_della_denominazione_non_provano_il_produttore(self):
        """L'unita' della regola, senza database."""
        prova = Matcher._prova_del_produttore
        assert prova("terre del barolo", "barolo") == ["terre", "del"]
        assert prova("antinori", "chianti classico") == ["antinori"]
        # `tenuta` sta su ogni etichetta: e' in PAROLE_VUOTE, non prova nulla.
        assert prova("tenuta san guido", "bolgheri sassicaia") == ["san", "guido"]

    def test_una_cooperativa_chiamata_come_la_sua_denominazione(self):
        """Non ha una parola sua: dalle parole non e' riconoscibile.

        Sono 31 cantine su 5998 - «Cantina di Soave», «Cantina di Montalcino»,
        «Cantina Valpolicella». Le loro bottiglie si raccontano come generiche,
        ed e' l'unica cosa onesta da fare: da «SOAVE» stampato non si distingue
        la cooperativa che si chiama Soave da chiunque altro faccia Soave.
        """
        assert Matcher._prova_del_produttore("cantina di soave", "soave") == []

    def test_la_gradazione_alcolica_non_e_una_firma(self, m):
        """«VOL» confermava il produttore «Volpi».

        Cinque lettere contro tre, due terzi in comune: `fuzz.ratio` da' 75, e
        75 bastava a dire «il produttore l'ho letto». Cosi' «Cantine Volpi»
        finiva su un Piemonte Cortese che non la nominava affatto - bastava che
        sull'etichetta ci fosse la gradazione, cioe' su ogni etichetta.

        La prova del produttore si misura sulle parole UTILI: quelle che stanno
        su ogni bottiglia non identificano una cantina piu' di quanto
        identifichino un vino.
        """
        f = m.cerca(["PIEMONTE CORTESE", "PIEMONTE",
                     "DENOMINAZIONE DI ORIGINE PROTETTA", "2019",
                     "IMBOTTIGLIATO ALL'ORIGINE", "13,5% VOL",
                     "CONTIENE SOLFITI", "750 ml", "PRODOTTO IN ITALIA"],
                    anno_massimo=2026)
        assert not f.cantina, f"attribuito a {f.cantina!r} dalla gradazione"

    def test_una_parola_assente_non_vale_un_riscontro_parziale(self):
        """`fuzz.ratio` fra parole che non c'entrano vale trenta o quaranta.

        Contarlo regalava a ogni produttore di tre parole una quarantina di
        punti che sull'etichetta non c'erano. Un refuso, invece, vale ottanta
        e passa, e deve continuare a contare.
        """
        assente = Matcher._copertura("terre", "comune serralunga alba".split())
        assert assente == 0.0, f"una parola assente ha preso {assente}"
        refuso = Matcher._copertura("tenuta rocca", "tinuta rocca barolo".split())
        assert refuso > 80, f"un refuso e' costato troppo: {refuso}"


class TestDatabasePiuRiccoDelCodice:
    """Il database cresce, il codice si aggiorna col firmware: non vanno insieme.

    L'indice di ricerca vive nel database. Chi lo ricostruisce puo' metterci
    righe di un ambito che questo codice non conosce - una tabella nuova, un
    prodotto da scaffale con un codice a barre. Prima era un `KeyError` dentro
    `_componi`, che gira nel thread di lavoro: diventava una schermata di
    guasto davanti all'ospite, su ogni bottiglia che ci finisse sopra.

    Chi legge deve reggere un database piu' ricco di quanto sappia usare.
    """

    def test_un_ambito_sconosciuto_non_solleva(self, m):
        f = m._componi(Candidato(ambito="scaffale", ambito_id=1, testo="",
                                 somiglianza=0.0, peso=0))
        assert f.livello is Livello.NULLA
        assert f.origine is None

    def test_un_ambito_sconosciuto_non_entra_in_gara(self, m):
        """E non basta che non sollevi: non deve nemmeno poter vincere.

        I pesi dell'indice li decide chi lo costruisce, non questo codice: una
        riga sconosciuta con peso alto scavalcherebbe la denominazione giusta e
        l'ospite vedrebbe una schermata vuota.
        """
        candidati = m._candidati(["barolo"], "barolo")
        assert candidati, "nessun candidato: la prova non direbbe niente"
        ignoti = [c.ambito for c in candidati if c.ambito not in Matcher.AMBITI]
        assert not ignoti, f"ambiti che non si sanno raccontare: {set(ignoti)}"

    def test_gli_ambiti_dichiarati_sono_quelli_che_si_sanno_comporre(self, m):
        """La tupla e il dizionario di `_componi` devono dire la stessa cosa."""
        for ambito in Matcher.AMBITI:
            f = m._componi(Candidato(ambito=ambito, ambito_id=1, testo="",
                                     somiglianza=0.0, peso=0))
            assert isinstance(f, Fatti)


class TestDisciplinare:
    """Le citazioni del registro UE, e a chi si possono attribuire.

    Le tipologie vengono da figshare, le citazioni dal documento unico
    eAmbrosia: due fonti che non hanno una chiave in comune. Accostarle per
    somiglianza del nome sbaglia — «Trentino Manzoni Bianco» si prende la
    descrizione di «Trentino Bianco» con punteggio pieno, perché le parole ci
    sono tutte — e il modo in cui sbaglia è il peggiore possibile: attribuisce
    a un vino la descrizione organolettica di un altro, con sicurezza.

    Per questo si restringe invece di somigliare, e quando non si può
    restringere abbastanza si tace.
    """

    def test_la_citazione_arriva(self, m):
        f = m._fatti_tipologia(2)                     # Abruzzo Rosso
        assert f.disciplinare["colore"].startswith("rosso rubino")
        assert f.disciplinare_di == "Abruzzo rosso"

    def test_dice_di_che_cosa_parla(self, m):
        """Il disciplinare descrive la TIPOLOGIA, non la bottiglia di quel
        produttore: chi racconta deve poterlo dire."""
        for tid in range(1, 400):
            f = m._fatti_tipologia(tid)
            if f.disciplinare:
                assert f.disciplinare_di

    def test_nessun_numero_di_servizio_nel_nome(self, m):
        """Quando due tipologie si chiamano uguale l'archivio le numera per
        tenerle distinte. Il numero è un identificativo, non un nome."""
        for tid in range(1, 400):
            di = m._fatti_tipologia(tid).disciplinare_di
            if di:
                assert not re.search(r"\(\d+\)$", di), di

    def test_mai_la_descrizione_di_un_altro_colore(self, m):
        """L'invariante che conta. Su tutte le tipologie dell'archivio: nessuna
        riceve una descrizione che contraddica il proprio colore."""
        rosso = re.compile(r"\b(rosso|rubino|granato|porpora|violaceo)\b", re.I)
        bianco = re.compile(
            r"\b(bianco|paglierino|giallo|dorato|verdognolo|verdolino|ambrato)\b", re.I)
        con, sbagliate = 0, []
        for tid, colore in m.con.execute("SELECT id, colore FROM tipologia"):
            d = m._fatti_tipologia(tid).disciplinare
            if not d:
                continue
            con += 1
            c = d.get("colore", "")
            if colore == "Red" and bianco.search(c) and not rosso.search(c):
                sbagliate.append((tid, c))
            if colore == "White" and rosso.search(c) and not bianco.search(c):
                sbagliate.append((tid, c))
        assert con > 2000, f"solo {con} tipologie con citazioni"
        assert not sbagliate, sbagliate[:3]

    def test_un_passito_non_descrive_un_vino_secco(self, m):
        """«Cinque Terre Costa de Campu Riserva» è un bianco secco, lo
        Sciacchetrà è un passito: stessa denominazione, stesso colore, e nel
        nome nessuna parola che facesse da freno. Le uve appassite fanno un
        altro vino, e quella descrizione è esclusa — non rimandata in fondo.
        """
        riga = m.con.execute(
            "SELECT id FROM tipologia WHERE nome = ?",
            ("Cinque Terre Costa de Campu Riserva",)).fetchone()
        if riga is None:
            pytest.skip("la tipologia non c'è in questo archivio")
        assert not m._fatti_tipologia(riga[0]).disciplinare

    def test_il_pareggio_si_tace(self, m):
        """Una denominazione con più descrizioni dello stesso colore, e niente
        che dica quale sia la nostra: si resta in silenzio. Il narratore ha
        comunque il resto dei fatti."""
        assert m._disciplinare(None, "qualunque", "Red") is None
        assert m._disciplinare(1, "qualunque", "Sparkling") is None

    def test_nel_blocco_dei_fatti_sono_separate(self, m):
        """Il resto dei fatti si può riformulare, queste sono parole altrui."""
        blocco = m._fatti_tipologia(2).blocco_fatti()
        assert "DAL DISCIPLINARE" in blocco
        assert blocco.index("Denominazione:") < blocco.index("DAL DISCIPLINARE")

    def test_la_forma_compatta_costa_meno_e_dice_lo_stesso(self, m):
        """Sulla board ogni token del prompt è 60 millisecondi di silenzio, e i
        fatti non si possono mettere in cache: cambiano a ogni bottiglia."""
        f = m._fatti_tipologia(2)
        compatto = f.blocco_compatto()
        assert len(compatto) < len(f.blocco_fatti()) / 1.4
        for pezzo in (f.denominazione, f.tipologia, f.disciplinare["colore"]):
            assert pezzo in compatto

    def test_la_forma_compatta_porta_la_nota(self, m):
        """Costa quaranta token, e vanno pagati.

        Toglierla sembrava gratis — il racconto la dice comunque, dal template
        — ma il corpus d'addestramento è scritto da un modello che la nota la
        vede: 498 esempi su 550 usano sue parole. Un ingresso che non la porta
        insegna a dire cose che l'ingresso non contiene, e l'unico modo di
        produrle è inventarle.
        """
        f = m._fatti_tipologia(2)
        assert f.note_vitigno
        assert f.note_vitigno in f.blocco_compatto()

    def test_la_forma_compatta_segue_la_lingua(self, m):
        compatto = m._fatti_tipologia(2).blocco_compatto(lingua="en")
        assert "ruby red" in compatto and "rosso rubino" not in compatto

    def test_in_inglese_sono_dichiarate_traduzione(self, m):
        """«rosso rubino» reso «ruby red» è parola nostra: dirlo citazione
        attribuirebbe a un ente pubblico una frase che non ha mai scritto."""
        blocco = m._fatti_tipologia(2).blocco_fatti(lingua="en")
        assert "translated from the Italian" in blocco
        assert "ruby red" in blocco


class TestCandidatiCheNonAggiungonoNiente:
    """Sull'etichetta c'è «Cerasuolo d'Abruzzo» e basta.

    In archivio ce ne sono tre, di Filari, Lepore e Valori, e il dispositivo li
    mostrava tutti e tre chiedendo di scegliere. Quella domanda non ha
    risposta: la bottiglia non dice di chi è, e nessuno al tavolo lo sa meglio
    di lei. Chiedere sposta su un ospite una scelta che il riconoscitore ha
    appena dichiarato impossibile, quando la regola del produttore l'ha fatto
    scendere al vino generico.
    """

    def test_senza_cantina_letta_non_si_propone_nessuna_cantina(self, m):
        """Qualunque riga l'ospite tocchi, il dispositivo stamperebbe il nome
        di un'azienda che non ha letto: è proprio ciò che la regola del
        produttore vieta."""
        f = m.cerca(["CERASUOLO", "D'ABRUZZO", "DENOMINAZIONE DI ORIGINE PROTETTA"])
        assert f.cantina is None
        for proposta in f.candidati:
            assert " — " not in proposta, proposta

    def test_un_vino_davvero_diverso_si_propone_ancora(self, m):
        """La schermata serve: toglierla del tutto sarebbe l'errore opposto."""
        f = m.cerca(["CERASUOLO", "D'ABRUZZO"])
        assert f.candidati, "senza alternative non si può chiedere niente"

    def test_col_produttore_letto_le_alternative_restano(self, m):
        """Se l'etichetta nomina la cantina, due cantine diverse sono due
        risposte diverse e la domanda ha senso eccome."""
        f = m.cerca(["MARCHESI DI BAROLO", "Barolo", "Cannubi", "2016"])
        assert f.cantina
        assert f.candidati


class TestIlColoreScrittoSullEtichetta:
    """Quando la bottiglia dichiara il proprio colore, quella parola non è un
    indizio da pesare insieme agli altri: è la bottiglia che lo dice di sé.

    Viene da un caso vero, visto sul dispositivo. Su «Leggiadro · Brut Rosé ·
    METODO CLASSICO» il riconoscitore proponeva per primo «Asti Metodo
    Classico» — bianco, di Moscato, dolce — all'86 %, e la voce raccontava il
    Moscato d'Asti a chi aveva in mano uno spumante rosa. I tre candidati
    offerti accanto erano già tutti Metodo Classico Rosé: la risposta giusta
    era in lista, solo non per prima.
    """

    ROSA = ["Leggiadro", "Brut Rosé", "METODO CLASSICO"]

    def test_un_rosato_non_si_racconta_come_un_bianco(self, m):
        f = m.cerca(self.ROSA)
        assert f.colore is not None
        assert f.colore in ("Rosé", "Rosato"), (
            f"ha scelto un {f.colore} per un'etichetta che dice «Rosé»")

    def test_e_nemmeno_si_propone(self, m):
        """Un candidato del colore sbagliato è lo stesso errore, spostato sotto
        il dito dell'ospite."""
        f = m.cerca(self.ROSA)
        for nome in f.candidati:
            assert "asti" not in nome.lower() or "rosé" in nome.lower(), nome

    def test_senza_colore_scritto_non_cambia_niente(self, m):
        """La regola si applica solo quando l'etichetta il colore lo DICE."""
        f = m.cerca(["BAROLO", "2016", "MARCHESI DI BAROLO", "CANNUBI"])
        assert f.livello is Livello.VINO
        assert f.sicurezza == pytest.approx(100, abs=1)

    def test_due_colori_diversi_valgono_come_nessuno(self, m):
        """Capita: «Rosso» di una denominazione accanto a «bianco» di una nota.
        Non sapere è meglio che scegliere a caso quale delle due vale."""
        assert m._colore_detto(["rosso", "bianco", "chianti"]) is None
        assert m._colore_detto(["rosso", "chianti"]) == "Rosso"

    def test_nero_non_e_un_colore_dichiarato(self, m):
        """Su un'etichetta italiana «nero» è un pezzo di nome di vitigno — Nero
        d'Avola, Nerello, Pinot Nero — non una dichiarazione di colore. E il
        Pinot Nero è la trappola: un blanc de noirs è un metodo classico BIANCO
        fatto di Pinot Nero, e leggendo «nero» come colore si scarterebbe la
        risposta giusta per cercarne una rossa. Chi vuole dire rosso scrive
        «Rosso»."""
        assert m._colore_detto(["pinot", "nero", "metodo", "classico"]) is None
        assert m._colore_detto(["nero", "d", "avola", "sicilia"]) is None
        assert m._colore_detto(["moscato", "rosa"]) is None
        # e la parola vera continua a valere
        assert m._colore_detto(["montepulciano", "rosso"]) == "Rosso"

    def test_il_colore_di_un_vino_viene_dalla_sua_tipologia(self, m):
        """La colonna `tipo` dei vini commerciali è sporca: in archivio
        «fiegl metodo classico brut ROSE» ci sta dentro come «Rosso». Il colore
        delle tipologie viene invece dal registro UE."""
        f = m.cerca(["BARDOLINO", "CHIARETTO", "ROSATO"])
        assert f.colore in ("Rosé", "Rosato")


class TestLaTemperaturaDiServizio:
    """La decide la categoria, non l'uva, tutte le volte che il vino non è fermo.

    Le schede in `data/vitigni.json` danno la temperatura del vino FERMO di
    quell'uva — giusta per un Pinot Nero — e uno spumante di Pinot Nero la
    ereditava: il dispositivo ha consigliato di servire un Trentodoc rosato a
    quindici-diciassette gradi. In archivio 819 tipologie su 4.300 sono
    spumanti o frizzanti, più 212 fra passiti e liquorosi: non è un caso
    isolato, è una classe.
    """

    def test_uno_spumante_si_serve_freddo(self, m):
        f = m.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert "Sparkling" in (f.categoria or "")
        assert f.temperatura_c == "6-8", (
            f"uno spumante a {f.temperatura_c} gradi")

    def test_un_liquoroso_ha_la_sua(self, m):
        f = m.cerca(["MARSALA", "SUPERIORE"])
        assert f.categoria == "Liqueur Wine"
        assert f.temperatura_c == "12-14"

    def test_un_vino_fermo_resta_all_uva(self, m):
        """Per un vino fermo l'uva ne sa più della categoria, e la regola non
        deve toccarla: un Barolo non si serve a sei gradi."""
        f = m.cerca(["BAROLO", "2016"])
        assert f.categoria == "Wine"
        assert f.temperatura_c == "17-19"

    def test_e_un_bianco_fermo_pure(self, m):
        f = m.cerca(["SOAVE", "CLASSICO"])
        assert f.temperatura_c == "10-12"


class TestNonSiNominaCioCheNonSiELetto:
    """La regola più importante del riconoscimento.

    «Trento Rosato/Rosé» somiglia moltissimo a «Brut Rosé Metodo Classico» —
    due parole su tre in comune — ma «Trento» sulla bottiglia non c'era, e
    Trento è un posto: dirlo vuol dire attribuire al vino un'origine che
    nessuno ha dichiarato.

    Misurato su 139 etichette vere più 9 bottiglie fuori archivio, e la
    separazione è totale: i riconoscimenti giusti hanno il 100 % delle parole
    identificanti sul vetro, le invenzioni ne hanno lo 0 %. Una soglia di
    SOMIGLIANZA non avrebbe potuto fare questo lavoro — «Lambrusco dell'Emilia»
    diventava «Colli dell'Etruria Centrale» con sicurezza 67, sopra al Chianti
    Classico vero che ne fa 78.
    """

    def test_un_posto_che_non_si_e_letto_non_si_nomina(self, m):
        f = m.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        detto = " ".join(filter(None, [f.nome, f.denominazione, f.tipologia]))
        assert "trento" not in detto.lower(), f"ha nominato Trento: {detto!r}"
        assert "asti" not in detto.lower(), f"ha nominato Asti: {detto!r}"

    def test_e_nemmeno_lo_propone(self, m):
        f = m.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        for c in f.candidati:
            assert "trento" not in c.lower(), c

    def test_il_produttore_non_trascina_la_sua_omonima(self, m):
        """Caso vero, dalle 139 etichette: il produttore si chiama «Santa
        Margherita» e il vino è un Valdadige, dell'Alto Adige. In archivio
        esiste «Santa Margherita di Belice», che è in Sicilia, e il
        riconoscitore la metteva prima all'84 %."""
        f = m.cerca(["Santa Margherita", "VALDADIGE", "DENOMINAZIONE DI ORIGINE"])
        detto = " ".join(filter(None, [f.nome, f.denominazione, f.tipologia]))
        assert "belice" not in detto.lower(), f"ha inventato la Sicilia: {detto!r}"

    def test_quello_che_si_e_letto_si_dice_eccome(self, m):
        """La regola non deve costare i riconoscimenti giusti."""
        f = m.cerca(["BAROLO", "2016", "MARCHESI DI BAROLO", "CANNUBI"])
        assert f.livello is Livello.VINO
        assert "barolo" in (f.nome or "").lower()
        assert f.sicurezza == pytest.approx(100, abs=1)

    def test_e_nemmeno_quelli_generici(self, m):
        f = m.cerca(["PRIMITIVO", "DI", "MANDURIA", "2019"])
        assert "manduria" in (f.denominazione or f.tipologia or "").lower()

    def test_un_refuso_dell_ocr_non_fa_cadere_la_regola(self, m):
        """Il riscontro è per parola e sopporta un errore di lettura: sotto la
        soglia non è un riscontro debole, è un non-riscontro, e un refuso vale
        ottanta e passa."""
        assert m._tutto_letto("cerasuolo abruzzo", ["cerasuolc", "abruzzo"])
        assert not m._tutto_letto("cerasuolo abruzzo", ["montepulciano", "abruzzo"])

    def test_le_parole_generiche_non_devono_essere_lette(self, m):
        """«Spumante», «rosato», «riserva» valgono per migliaia di bottiglie:
        non identificano niente e non possono vincolare niente."""
        assert m._identificanti("trento rosato spumante") == ["trento"]
        assert m._identificanti("spumante rosato brut") == []
        # e un record fatto di sole parole generiche non attribuisce niente
        assert m._tutto_letto("spumante rosato", ["qualcosa", "d", "altro"])

    def test_i_di_e_i_del_non_contano(self, m):
        """Il filtro delle parole lette butta via «di» da tutte e due le parti:
        pretenderlo boccerebbe ogni «Primitivo di Manduria»."""
        assert m._tutto_letto("primitivo di manduria", ["primitivo", "manduria"])


class TestQuelCheDiceLEtichetta:
    """Quando in archivio non c'è niente da nominare, si dice quel che c'è
    scritto. Non «non ce l'ho», che al tavolo non serve a nessuno, e non un
    vino inventato, che è peggio."""

    def test_uno_spumante_sconosciuto_resta_uno_spumante(self, m):
        f = m.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert f.livello is Livello.GENERICO
        assert f.colore == "Rosato"
        assert "spumante" in f.qualificatori or "metodo" in f.qualificatori
        assert f.temperatura_c == "6-8"
        assert not f.vuoto, "il racconto deve partire lo stesso"

    def test_di_un_rosso_sconosciuto_si_dice_che_e_rosso(self, m):
        f = m.cerca(["CASTELLO", "DI", "FANTASIA", "ROSSO", "2019"])
        assert f.livello is Livello.GENERICO
        assert f.colore == "Rosso"

    def test_non_si_inventa_ne_vitigno_ne_denominazione(self, m):
        f = m.cerca(["Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert not f.vitigni and not f.denominazione and not f.nome
        assert not f.cantina and not f.regione

    def test_i_qualificatori_vengono_da_un_elenco_chiuso(self, m):
        """Niente di quello che dice il rumore dell'OCR può finire in bocca al
        dispositivo: le parole del tipo passano da un elenco scritto a mano."""
        from amelie.matcher import ORDINE_QUALIFICATORI

        f = m.cerca(["uIsE", "202", "Leggiadro", "Brut Rosé", "METODO CLASSICO"])
        assert all(q in ORDINE_QUALIFICATORI for q in f.qualificatori)

    def test_il_colore_regge_anche_dopo_la_cascata(self, m):
        """Il vincolo si applica scegliendo fra i candidati, ma la cascata
        continua dopo: il produttore non letto fa scendere alla tipologia, la
        regola sul nome fa scendere ancora, e uno di quei gradini può essere di
        un altro colore.

        Visto sul dispositivo con un'etichetta che diceva PROSECCO ROSÉ: si
        scendeva a «Prosecco-Wine», che in archivio è BIANCO.
        """
        f = m.cerca(["ISE", "20", "TARVESIUM", "PROSECCO ROSÉ", "DOC",
                     "MILLESIMATO2024", "EXTRA DRY"])
        assert f.colore in ("Rosé", "Rosato"), (
            f"un Prosecco Rosé raccontato come {f.colore}")
        assert "prosecco" in (f.tipologia or f.denominazione or "").lower()

    def test_un_prosecco_bianco_resta_bianco(self, m):
        """E la correzione non deve scattare quando non c'è niente da
        correggere: senza la parola «rosé» il Prosecco è quello di sempre."""
        f = m.cerca(["PROSECCO", "DOC", "EXTRA", "DRY"])
        assert f.colore == "White"
