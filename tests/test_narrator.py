"""Test del racconto.

Il test che conta è quello sull'invenzione: il dispositivo può dire meno di
quello che sa, mai più. Un racconto che aggiunge un premio, un'annata o un
luogo che non stanno nei fatti è un guasto, non un'imprecisione.
"""

import pytest

from amelie.matcher import Fatti, Livello
from amelie.narrator import (
    PAROLE_MAX,
    Narratore,
    Racconto,
    _ripulisci,
    a_frasi,
    prompt,
    template,
    verifica,
)


@pytest.fixture
def barolo():
    return Fatti(
        livello=Livello.VINO, sicurezza=100.0,
        nome="Cannubi Barolo", cantina="Marchesi di Barolo",
        regione="Barolo", annata=2016, denominazione="Barolo",
        tipo_denominazione="DOP", colore="Red", corpo="Full-bodied",
        acidita="High", vitigni=["Nebbiolo"],
        vitigni_ammessi=["Barbera", "Croatina"],
        abbinamenti=["Beef", "Game Meat"], temperatura_c="17-19",
    )


class TestVerifica:
    def test_accetta_cio_che_sta_nei_fatti(self, barolo):
        ok, inv = verifica("Questo è il Cannubi Barolo di Marchesi di Barolo.", barolo)
        assert ok, inv

    def test_scarta_un_premio_inventato(self, barolo):
        ok, inv = verifica("Ha vinto i Tre Bicchieri del Gambero Rosso.", barolo)
        assert not ok
        assert any("Bicchieri" in x or "Gambero" in x for x in inv)

    def test_scarta_un_numero_inventato(self, barolo):
        ok, inv = verifica("Le vigne stanno a 400 metri di altitudine.", barolo)
        assert not ok
        assert "400" in inv

    def test_scarta_un_luogo_inventato(self, barolo):
        ok, inv = verifica("Nasce sulle colline di Serralunga.", barolo)
        assert not ok
        assert "Serralunga" in inv

    def test_accetta_l_annata_dei_fatti(self, barolo):
        assert verifica("L'annata 2016 è stata generosa.", barolo)[0]

    def test_scarta_un_annata_diversa(self, barolo):
        ok, inv = verifica("L'annata 2011 è stata generosa.", barolo)
        assert not ok and "2011" in inv

    def test_ignora_le_maiuscole_di_inizio_frase(self, barolo):
        assert verifica("Questo vino nasce dal Nebbiolo. Ottimo.", barolo)[0]

    def test_ignora_gli_articoli_maiuscoli(self, barolo):
        assert verifica("Il Nebbiolo. La struttura. Un vino.", barolo)[0]

    def test_un_vitigno_solo_ammesso_e_invenzione(self, barolo):
        """Il caso Amarone/Croatina: il disciplinare lo ammette, il vino non lo contiene."""
        ok, inv = verifica("Contiene anche un tocco di Croatina.", barolo)
        assert not ok, "un vitigno solo AMMESSO non puo' essere dichiarato presente"

    def test_testo_vuoto(self, barolo):
        assert verifica("", barolo)[0]


class TestColoreContraddetto:
    """L'errore piu' visibile, e quello che un modello piccolo fa piu' spesso.

    Sul serio, in pre-generazione, il modello ha scritto che la Falanghina -
    vitigno a bacca BIANCA - e' «un vino rosso di campagna con tannicita'
    bassa». Non e' un'imprecisione: e' falso, e un sommelier lo coglie subito.
    """

    @pytest.fixture
    def bianco(self):
        return Fatti(livello=Livello.VITIGNO, vitigni=["Falanghina"],
                     colore_bacca="bianca")

    @pytest.fixture
    def rosso(self):
        return Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"],
                     colore_bacca="nera")

    def test_scarta_rosso_su_un_bianco(self, bianco):
        ok, inv = verifica("La Falanghina è un vino rosso di campagna.", bianco)
        assert not ok and "colore" in inv[0]

    def test_scarta_il_tannino_su_un_bianco(self, bianco):
        assert not verifica("Ha una tannicità bassa e piacevole.", bianco)[0]

    def test_accetta_bianco_su_un_bianco(self, bianco):
        assert verifica("Dà bianchi freschi e floreali.", bianco)[0]

    def test_scarta_paglierino_su_un_rosso(self, rosso):
        assert not verifica("Un giallo paglierino luminoso.", rosso)[0]

    def test_accetta_rubino_su_un_rosso(self, rosso):
        assert verifica("Un rosso rubino di bella intensità.", rosso)[0]

    def test_senza_colore_dichiarato_non_giudica(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        assert verifica("Un vino rosso intenso.", f)[0]


def inizia_con(testo: str, chiave: str) -> bool:
    """Il testo apre con UNA delle forme di quella frase d'apertura?

    Le forme sono piu' d'una e le sceglie il seme: il test non puo' pretendere
    una parola precisa, ma puo' pretendere che sia la frase GIUSTA - quella
    affermativa o quella che dichiara il dubbio - in una qualunque delle sue
    forme.
    """
    from amelie.lessico import carica
    for forma in carica().varianti("apertura", chiave):
        prefisso = forma.split("{")[0]
        if prefisso and testo.startswith(prefisso):
            return True
    return False


class TestTemplate:
    def test_il_livello_vino_e_affermativo(self, barolo):
        t = template(barolo)
        assert inizia_con(t, "vino_certo"), t
        assert "Cannubi" in t and "Marchesi di Barolo" in t

    def test_il_livello_tipologia_dichiara_l_incertezza(self):
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo Riserva",
                  denominazione="Barolo", sicurezza=80.0)
        t = template(f)
        assert inizia_con(t, "tipologia_nota"), t
        assert "un Barolo Riserva" in t

    def test_il_livello_vitigno_non_attribuisce_al_produttore(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=80.0)
        t = template(f)
        assert "Nebbiolo" in t and "non sono sicuro" not in t.lower()

    def test_un_vino_certo_si_annuncia_come_certo(self):
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=95.0)
        assert inizia_con(template(f), "vino_certo"), template(f)

    def test_un_vino_dubbio_non_si_annuncia_come_certo(self):
        """Sicurezza 80: il record e' completo, la somiglianza no."""
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=80.0)
        t = template(f)
        assert not inizia_con(t, "vino_certo"), t
        assert inizia_con(t, "vino_dubbio"), t
        assert "Barolo Cannubi" in t

    def test_una_somiglianza_bassa_si_dichiara_tale(self):
        """Il difetto piu' insidioso: un record perfetto trovato male.

        Non si scusa della lettura - quello non interessa a nessuno - ma non
        annuncia nemmeno come certo un produttore che ha attribuito al 60%.

        MATCH_ASSENTE porta al racconto anche sotto la soglia dubbia. Se
        l'apertura guardasse solo il livello, il dispositivo direbbe al tavolo
        «Questo è il Barolo di Marchesi di Barolo» con il 60% di somiglianza.
        """
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", sicurezza=60.0)
        t = template(f)
        assert inizia_con(t, "vino_dubbio") or inizia_con(t, "vino_incerto"), t
        assert "non è nitida" not in t

    def test_anche_i_livelli_deboli_si_smorzano_sotto_la_soglia(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=50.0)
        assert inizia_con(template(f), "vitigno_incerto"), template(f)

    def test_il_template_supera_sempre_la_verifica(self, barolo):
        """La rete di sicurezza non puo' essere quella che inventa."""
        assert verifica(template(barolo), barolo)[0]

    def test_la_temperatura_si_legge_ad_alta_voce(self, barolo):
        """'17-19' pronunciato diventa 'diciassette trattino diciannove'."""
        t = template(barolo)
        assert "17-19" not in t
        assert "17 e 19" in t and "gradi" in t

    def test_fatti_vuoti_non_esplodono(self):
        assert template(Fatti()) != ""


class TestPrompt:
    def test_contiene_i_fatti(self, barolo):
        assert "Cannubi Barolo" in prompt(barolo)

    def test_non_contiene_i_vitigni_ammessi(self, barolo):
        """Il modello non deve nemmeno vederli: se li vede, li nomina."""
        p = prompt(barolo)
        assert "Croatina" not in p

    def test_avverte_quando_il_match_e_incerto(self):
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Barolo")
        assert "produttore specifico" in prompt(f)

    def test_non_avverte_quando_il_match_e_certo(self, barolo):
        assert "produttore specifico" not in prompt(barolo)


class TestRipulisci:
    def test_toglie_le_virgolette(self):
        assert _ripulisci('"Un bel vino."') == "Un bel vino."

    def test_toglie_le_intestazioni(self):
        assert _ripulisci("Racconto: Un bel vino.") == "Un bel vino."

    def test_toglie_gli_elenchi(self):
        assert "-" not in _ripulisci("- Un bel vino.")

    def test_taglia_alla_frase_intera_quando_conviene(self):
        """Chiude su una frase se questo non butta via mezzo testo."""
        fuori = _ripulisci("Una frase. " * 60)
        assert len(fuori.split()) <= PAROLE_MAX
        assert fuori.endswith(".")

    def test_dichiara_il_troncamento_se_la_frase_e_troppo_indietro(self):
        """Meglio un troncamento coi puntini che due parole al posto di cento."""
        fuori = _ripulisci("Frase breve. " + "parola " * 300)
        assert len(fuori.split()) <= PAROLE_MAX
        assert fuori.endswith("…")
        assert len(fuori.split()) > 50

    def test_normalizza_gli_spazi(self):
        assert _ripulisci("Un   bel\n\nvino.") == "Un bel vino."


class TestAFrasi:
    def test_raggruppa_i_token_in_frasi(self):
        token = ["Que", "sto ", "è ", "un ", "Barolo. ", "Nasce ", "in ", "Langa. "]
        assert list(a_frasi(iter(token))) == ["Questo è un Barolo.", "Nasce in Langa."]

    def test_restituisce_la_coda_senza_punto(self):
        assert list(a_frasi(iter(["Senza punto finale"]))) == ["Senza punto finale"]

    def test_flusso_vuoto(self):
        assert list(a_frasi(iter([]))) == []


class TestRacconto:
    def test_spezza_in_frasi(self):
        r = Racconto(testo="Prima. Seconda! Terza?", origine="template",
                     livello=Livello.VINO)
        assert len(r.frasi) == 3


@pytest.fixture(scope="module")
def matcher():
    from amelie.matcher import Matcher
    m = Matcher()
    yield m
    m.chiudi()


class TestDueLingue:
    """Il racconto in inglese dev'essere inglese, non parole inglesi in frasi italiane."""

    # Solo connettivi inequivocabili. Fuori « di », « un », « con »: compaiono
    # nei NOMI PROPRI - "Marchesi di Barolo", "Nero d'Avola" - che non si
    # traducono, e un test che li vietasse fallirebbe sul testo giusto.
    PAROLE_ITALIANE = (" è ", " si serve ", " nasce da ", " gradi.",
                       " bene a ", "questo è", "l'etichetta")

    def test_il_racconto_inglese_non_contiene_impalcatura_italiana(self, matcher):
        for righe in (["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"],
                      ["Etna Rosso"], ["Nebbiolo"], ["Chianti Classico"]):
            f = matcher.cerca(righe)
            testo = f" {template(f, lingua='en').lower()} "
            trovate = [p for p in self.PAROLE_ITALIANE if p in testo]
            assert not trovate, f"{righe}: {trovate} in {testo!r}"

    def test_l_articolo_inglese_segue_il_suono(self, matcher):
        """«a Etna Rosso» si sente subito."""
        f = matcher.cerca(["Etna Rosso"])
        assert "an Etna Rosso" in template(f, lingua="en")

    def test_lo_stesso_vino_si_racconta_in_due_lingue(self, matcher):
        f = matcher.cerca(["MARCHESI DI BAROLO", "BAROLO", "CANNUBI", "2016"])
        it, en = template(f, lingua="it"), template(f, lingua="en")
        assert it != en
        for testo in (it, en):
            assert "Cannubi" in testo, "il nome del vino sparisce"
            assert "2016" in testo, "l'annata sparisce"

    def test_la_temperatura_non_si_spezza_in_inglese(self, matcher):
        f = matcher.cerca(["Nebbiolo"])
        testo = template(f, lingua="en")
        assert "17-19" not in testo, "il trattino va sciolto: lo legge una voce"
        assert "between 17 and 19" in testo


class TestChiusura:
    """Chiudere il database mentre qualcuno ci legge era un segmentation fault.

    Non un'eccezione che si cattura: il processo moriva. Si vedeva solo sulla
    board, dove i test girano nell'ambiente vero e un thread di lavoro puo'
    essere ancora dentro `_dalla_cache` quando la fixture chiude tutto.
    """

    def test_chiudere_aspetta_chi_sta_leggendo(self):
        import threading
        from amelie.matcher import Matcher
        from amelie.narrator import Narratore

        m, n = Matcher(), Narratore()
        errori = []
        fermo = threading.Event()

        def legge():
            try:
                for _ in range(40):
                    f = m.cerca(["Barolo", "Marchesi di Barolo", "Cannubi"])
                    # In «generativa» e senza modello: cosi' si passa da
                    # `_dalla_cache`, che e' dove il lucchetto serve.
                    n.racconta(f, preferisci_modello=True)
            except Exception as e:                      # noqa: BLE001
                errori.append(e)
            finally:
                fermo.set()

        t = threading.Thread(target=legge, daemon=True)
        t.start()
        t.join(timeout=30)
        m.chiudi()
        n.chiudi()
        assert fermo.is_set(), "il lettore non ha finito"
        assert not errori, errori


class TestUscitaSempreAperta:
    """Il flusso audio si apre una volta e non si chiude mai.

    Il DSP di questa board impiega **circa due secondi** a cominciare a rendere
    il suono dopo l'apertura del flusso. Non e' una stima: si sono fatti
    ascoltare sei bip a un secondo l'uno dall'altro e se ne sono sentiti
    quattro. Aprendo e chiudendo `aplay` a ogni frase, una frase da un secondo
    sparisce del tutto - se ne sente l'ultima sillaba, e sembra un guasto
    dell'amplificatore.
    """

    @staticmethod
    def _voce_finta(monkeypatch):
        import time

        from amelie.speech import ImpostazioniVoce, Voce

        aperture = []

        class FintoStdin:
            """Registra e basta.

            Non deve rallentare: il passo lo detta ora chi versa, con il suo
            orologio. Un finto che aspettasse a sua volta raddoppierebbe il
            ritmo e i test durerebbero il doppio del dovuto.
            """

            def __init__(self, scritti):
                self.scritti = scritti

            def write(self, dati): self.scritti.append(bytes(dati))
            def flush(self): pass
            def close(self): pass

        class FintoProc:
            def __init__(self):
                self.scritti = []
                self.stdin = FintoStdin(self.scritti)
                self.ucciso = False
            def wait(self, timeout=None): return 0
            def kill(self): self.ucciso = True

        v = Voce(ImpostazioniVoce(usa_cache=False))

        def apri():
            p = FintoProc()
            aperture.append(p)
            return p

        monkeypatch.setattr(v, "apri_uscita", apri)
        monkeypatch.setattr(v, "sintetizza", lambda f: b"\x11\x22" * 2205)  # 0,1 s
        return v, aperture

    def test_il_flusso_si_apre_una_volta_sola(self, monkeypatch):
        """Tre frasi, una sola apertura: e' tutto il punto."""
        v, aperture = self._voce_finta(monkeypatch)
        try:
            for _ in range(3):
                v.parla(["qualcosa"])
            assert len(aperture) == 1, (
                f"{len(aperture)} aperture invece di una: si pagherebbero due "
                "secondi di avvio del DSP a ogni frase")
        finally:
            v.chiudi()

    def test_il_flusso_non_si_chiude_quando_si_zittisce(self, monkeypatch):
        """Zittire e' buttare via la coda, non chiudere il rubinetto."""
        v, aperture = self._voce_finta(monkeypatch)
        try:
            v.parla(["qualcosa"])
            v.zittisci()
            assert not aperture[0].ucciso, "il flusso e' stato chiuso"
            v.parla(["ancora"])
            assert len(aperture) == 1, "riaperto dopo lo zittisci"
        finally:
            v.chiudi()

    def test_si_versa_silenzio_quando_non_c_e_niente_da_dire(self, monkeypatch):
        """E' il silenzio che tiene sveglio il DSP."""
        import time
        v, aperture = self._voce_finta(monkeypatch)
        try:
            v.uscita()
            time.sleep(0.4)
            scritti = aperture[0].scritti
            assert scritti, "il flusso non sta scrivendo niente"
            assert all(x.strip(b"\x00") == b"" for x in scritti), \
                "a riposo si deve versare silenzio, non altro"
        finally:
            v.chiudi()

    def test_svuotare_butta_via_cio_che_non_e_ancora_uscito(self, monkeypatch):
        v, _ = self._voce_finta(monkeypatch)
        try:
            u = v.uscita()
            u.scrivi(b"\x11\x22" * 22050)      # un secondo
            u.svuota()
            # Resta solo la latenza fissa: cio' che e' gia' passato ad aplay e
            # non e' ancora uscito. La coda e' vuota.
            assert u.in_pancia_s() == pytest.approx(u.latenza_s, abs=0.05)
        finally:
            v.chiudi()

    def test_si_versa_al_ritmo_del_suono_e_non_a_riempimento(self, monkeypatch):
        """L'invariante che fa combaciare didascalia e voce.

        Scrivendo finche' qualcuno accetta si finisce molto avanti a cio' che
        si sente: la pipe del sistema da sola tiene 64 KB, che a 22050 mono
        sono un secondo e mezzo di parlato. Era quello il ritardo con cui la
        voce arrivava dopo il testo.
        """
        import time

        v, aperture = self._voce_finta(monkeypatch)
        try:
            u = v.uscita()
            time.sleep(0.05)
            t0, n0 = time.monotonic(), len(aperture[0].scritti)
            time.sleep(1.0)
            versati = (len(aperture[0].scritti) - n0) * u.PEZZO_S
            trascorso = time.monotonic() - t0
            # In un secondo si versa circa un secondo di suono, non dieci.
            assert versati == pytest.approx(trascorso, abs=0.35), (
                f"versati {versati:.2f}s di suono in {trascorso:.2f}s reali: "
                "si sta correndo avanti all'orecchio")
        finally:
            v.chiudi()

    def test_scrivere_non_corre_avanti_all_orecchio(self, monkeypatch):
        """La riserva e' cio' che tiene onesta la posizione del player.

        Senza un tetto si scriverebbe finche' qualcuno accetta, e la posizione
        dichiarata scapperebbe avanti a quella che si sente.
        """
        from amelie.speech import Uscita
        v, _ = self._voce_finta(monkeypatch)
        try:
            u = v.uscita()
            assert u.RISERVA_S <= 0.5, "una riserva cosi' grande si vedrebbe"
            assert u.PEZZO_S < u.RISERVA_S
        finally:
            v.chiudi()


class TestDidascalia:
    """La didascalia deve seguire la VOCE, non la scrittura.

    Fra lo scrivere una frase nell'uscita e il sentirla ci sono la riserva e il
    buffer di ALSA: mezzo secondo. Una didascalia agganciata alla scrittura
    correrebbe avanti di quel mezzo secondo, e su una frase da un secondo si
    vede.
    """

    def test_la_didascalia_arriva_una_frase_per_volta_e_in_ordine(self, monkeypatch):
        from amelie.speech import ImpostazioniVoce, Voce

        class FintoStdin:
            def __init__(self): self.scritti = []
            def write(self, dati): self.scritti.append(bytes(dati))
            def flush(self): pass
            def close(self): pass

        class FintoProc:
            def __init__(self): self.stdin = FintoStdin()
            def wait(self, timeout=None): return 0
            def kill(self): pass

        v = Voce(ImpostazioniVoce(usa_cache=False))
        monkeypatch.setattr(v, "apri_uscita", lambda: FintoProc())
        monkeypatch.setattr(v, "sintetizza", lambda f: b"\x11\x22" * 4410)  # 0,2 s

        viste = []
        try:
            v.parla(["Prima.", "Seconda.", "Terza."], su_frase=viste.append)
        finally:
            v.chiudi()

        assert viste == ["Prima.", "Seconda.", "Terza."]

    def test_la_didascalia_compare_QUANDO_la_frase_comincia_a_sentirsi(
            self, monkeypatch):
        """Il difetto vero: il testo compariva uno o due secondi prima della voce.

        Fra lo scrivere una frase e il sentirla c'è tutto quello che è in
        viaggio: la coda, la pipe del sistema — 64 KB, cioè un secondo e mezzo
        di parlato a 22050 mono — e il buffer di ALSA. Aspettare che si
        svuotasse solo la coda faceva credere di aver finito con un secondo e
        mezzo di anticipo.

        Qui si verifica il conto: la frase N deve comparire dopo la latenza più
        la somma delle durate di quelle prima.
        """
        import time

        from amelie.speech import ImpostazioniVoce, Voce

        class FintoStdin:
            def __init__(self): self.scritti = []
            def write(self, dati): self.scritti.append(bytes(dati))
            def flush(self): pass
            def close(self): pass

        class FintoProc:
            def __init__(self): self.stdin = FintoStdin()
            def wait(self, timeout=None): return 0
            def kill(self): pass

        v = Voce(ImpostazioniVoce(usa_cache=False))
        monkeypatch.setattr(v, "apri_uscita", lambda: FintoProc())
        # Due frasi da mezzo secondo l'una.
        monkeypatch.setattr(v, "sintetizza", lambda f: b"\x11\x22" * 11025)

        u = v.uscita()
        time.sleep(0.3)                     # il flusso va a regime
        quando = []
        t0 = time.monotonic()
        try:
            v.parla(["Prima.", "Seconda."],
                    su_frase=lambda f: quando.append(time.monotonic() - t0))
        finally:
            v.chiudi()

        assert len(quando) == 2
        # La prima comincia a sentirsi dopo la latenza; la seconda mezzo
        # secondo dopo, che e' la durata della prima.
        assert quando[0] == pytest.approx(u.latenza_s, abs=0.25)
        assert quando[1] - quando[0] == pytest.approx(0.5, abs=0.25)

    def test_senza_didascalia_non_si_aspetta_niente(self, monkeypatch):
        """Chi non chiede la didascalia non deve pagare le attese che serve a lei."""
        import inspect

        from amelie.speech import Voce
        sorgente = inspect.getsource(Voce.parla)
        assert "su_frase is not None" in sorgente, (
            "l'attesa per sincronizzare la didascalia va fatta SOLO se qualcuno "
            "la sta guardando: e' un'attesa per frase, e senza motivo "
            "rallenterebbe ogni racconto")

    def test_le_frasi_si_spezzano_dove_finiscono(self):
        from amelie.narrator import spezza_in_frasi
        assert spezza_in_frasi("Uno. Due! Tre? Quattro…") == [
            "Uno.", "Due!", "Tre?", "Quattro…"]
        assert spezza_in_frasi("") == []
        # Un punto dentro una sigla non spezza: non c'e' spazio dopo.
        assert len(spezza_in_frasi("Un Barolo D.O.C.G. del 2016.")) == 1


class TestLeQuattroClassiUsciteDallaRilettura:
    """Passavano tutte. Ciò che la verifica non vede diventa un'abitudine del
    modello: il modello addestrato invocava il disciplinare senza averlo nel
    76 % dei casi, perché il maestro lo faceva nel 55 % e nessuno lo fermava."""

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Rosso di prova", denominazione="Prova",
                    colore="Red", abv=12.5, temperatura_c="16-18",
                    abbinamenti=["carni rosse", "formaggi stagionati"])
        base.update(kw)
        return Fatti(**base)

    def test_il_punto_medio_dell_intervallo_non_e_scritto(self):
        ok, inv = verifica("Da servire a diciassette gradi.", self._fatti())
        assert not ok and any("diciassette" in x for x in inv)

    def test_gli_estremi_dell_intervallo_vanno_bene(self):
        ok, _ = verifica("Da servire fra i sedici e i diciotto gradi.", self._fatti())
        assert ok

    def test_il_mezzo_grado_si_confronta_come_mezzo(self):
        """«tredici gradi e mezzo» di un 12,5 %: l'intero tornava, il vino no."""
        ok, inv = verifica("Tredici gradi e mezzo, da servire fra i sedici e i diciotto.",
                           self._fatti())
        assert not ok and any("tredici gradi e mezzo" in x for x in inv)
        ok, _ = verifica("Dodici gradi e mezzo, da servire fra i sedici e i diciotto.",
                         self._fatti())
        assert ok

    def test_un_conteggio_non_e_un_grado(self):
        ok, _ = verifica("Nasce da due vitigni. Da servire fra i sedici e i diciotto gradi.",
                         self._fatti())
        assert ok

    def test_il_disciplinare_si_nomina_solo_se_c_e(self):
        ok, inv = verifica("Il disciplinare lo vuole rosso.", self._fatti())
        assert not ok and "disciplinare invocato senza citazioni" in inv
        ok, _ = verifica("Il disciplinare lo vuole rosso rubino.",
                         self._fatti(disciplinare={"colore": "rosso rubino"}))
        assert ok

    def test_un_cibo_non_scritto_e_un_invenzione(self):
        ok, inv = verifica("Ideale su crostacei e formaggi.", self._fatti())
        assert not ok and "crostacei" in inv and "formaggi" not in inv

    def test_l_origine_del_vitigno_va_nei_fatti(self):
        ok, inv = verifica("Un grande vitigno siciliano.", self._fatti())
        assert not ok and "siciliano" in inv
        ok, _ = verifica("Un grande vitigno siciliano.",
                         self._fatti(note_vitigno="Vitigno siciliano, dell'Etna."))
        assert ok


class TestIlPromptSegueIlModello:
    """Un modello affinato su una forma e interrogato con un'altra è un modello
    che non hai affinato. Misurato sulla board dandogli per sbaglio il prompt
    del modello generico: 63,8 secondi invece di 27, e la prosa tornata
    sgrammaticata — «Il Abruzzo Spumante Bianco Charmat è un solo vitigno»."""

    def _fatti(self):
        return Fatti(livello=Livello.TIPOLOGIA, denominazione="Prova",
                     tipologia="Prova Rosso", colore="Red", vitigni=["Nebbiolo"],
                     temperatura_c="16-18")

    def test_il_prompt_addestrato_e_molto_piu_corto(self):
        from amelie.narrator import prompt, prompt_addestrato
        f = self._fatti()
        assert len(prompt_addestrato(f)) < len(prompt(f)) / 2

    def test_porta_i_fatti_compatti_e_una_riga_di_istruzione(self):
        from amelie.narrator import ISTRUZIONE_ADDESTRATA, prompt_addestrato
        f = self._fatti()
        p = prompt_addestrato(f)
        assert ISTRUZIONE_ADDESTRATA["it"] in p
        assert f.blocco_compatto() in p
        assert p.rstrip().endswith("<|im_start|>assistant")

    def test_segue_la_lingua(self):
        from amelie.narrator import ISTRUZIONE_ADDESTRATA, prompt_addestrato
        p = prompt_addestrato(self._fatti(), "en")
        assert ISTRUZIONE_ADDESTRATA["en"] in p

    def test_il_narratore_sceglie_la_forma_giusta(self):
        from amelie.narrator import ISTRUZIONE_ADDESTRATA, Narratore
        visti = []
        for addestrato in (False, True):
            n = Narratore(genera=lambda p: (visti.append(p), "x.")[1],
                          modello_addestrato=addestrato)
            try:
                n._dal_modello(self._fatti())
            finally:
                n.chiudi()
        assert ISTRUZIONE_ADDESTRATA["it"] not in visti[0]
        assert ISTRUZIONE_ADDESTRATA["it"] in visti[-1]


class TestRaccontoAFrasi:
    """Il racconto che esce una frase per volta, mentre il modello lo scrive.

    Serve a coprire i dodici secondi di prefill che sulla board passano prima
    che esca la prima lettera. La prima frase è l'apertura, che è un template:
    vera, pronta subito, e l'unica che il modello non scrive mai perché dipende
    dalla certezza, che si conosce solo al momento.
    """

    def _fatti(self):
        return Fatti(livello=Livello.TIPOLOGIA, sicurezza=0.95,
                     denominazione="Prova", tipologia="Prova Rosso",
                     colore="Red", vitigni=["Nebbiolo"], temperatura_c="16-18",
                     note_vitigno="Vitigno piemontese, delle Langhe.")

    def _narratore(self, pezzi):
        return Narratore(genera=lambda p: "".join(pezzi),
                         genera_a_flusso=lambda p: iter(list(pezzi)))

    def test_la_prima_frase_arriva_prima_del_modello(self):
        """Il modello non ha ancora detto una parola e la voce ha già di che
        parlare: è tutto il punto."""
        n = self._narratore(["Nasce dal Nebbiolo. "])
        try:
            frasi = n.racconta_a_frasi(self._fatti(), preferisci_modello=True)
            prima = next(frasi)
            assert prima and "Nebbiolo" not in prima      # è l'apertura, non il modello
        finally:
            n.chiudi()

    def test_le_frasi_del_modello_seguono(self):
        n = self._narratore(["Nasce dal Nebbiolo. ", "Da servire fra i sedici e i diciotto gradi. "])
        try:
            frasi = list(n.racconta_a_frasi(self._fatti(), preferisci_modello=True))
            assert any("Nebbiolo" in f for f in frasi)
            assert any("sedici" in f for f in frasi)
        finally:
            n.chiudi()

    def test_una_frase_inventata_si_lascia_cadere(self):
        """Le altre restano vere una per una, anche se il periodo è più corto."""
        n = self._narratore(["Nasce dal Nebbiolo. ",
                             "Ha vinto tre stelle al Gambero Rosso nel 1998. ",
                             "Da servire fra i sedici e i diciotto gradi. "])
        try:
            frasi = list(n.racconta_a_frasi(self._fatti(), preferisci_modello=True))
            assert not any("Gambero" in f for f in frasi)
            assert any("Nebbiolo" in f for f in frasi)
            assert any("sedici" in f for f in frasi)
        finally:
            n.chiudi()

    def test_se_il_modello_non_da_niente_di_buono_si_finisce_col_template(self):
        """Chi ascolta non deve accorgersi che qualcosa non ha funzionato."""
        n = self._narratore(["Ha vinto tre stelle nel 1998. "])
        try:
            frasi = list(n.racconta_a_frasi(self._fatti(), preferisci_modello=True))
            assert not any("1998" in f for f in frasi)
            assert len(frasi) > 1                  # l'apertura più il template
            assert any("piemontese" in f for f in frasi)
        finally:
            n.chiudi()

    def test_senza_modello_si_racconta_lo_stesso(self):
        n = Narratore()
        try:
            frasi = list(n.racconta_a_frasi(self._fatti(), preferisci_modello=True))
            assert any("piemontese" in f for f in frasi)
        finally:
            n.chiudi()

    def test_senza_flusso_degrada_invece_di_rompersi(self):
        """Un modello che non sa dare i pezzi dà tutto insieme: più tardi, non
        mai."""
        n = Narratore(genera=lambda p: "Nasce dal Nebbiolo. Da servire fra i sedici e i diciotto gradi.")
        try:
            frasi = list(n.racconta_a_frasi(self._fatti(), preferisci_modello=True))
            assert any("Nebbiolo" in f for f in frasi)
        finally:
            n.chiudi()


class TestIlLimiteSiDiceSoloSeSiEDetto:
    """«Questa bottiglia non è nel mio archivio: quello che le ho detto è
    scritto sull'etichetta» è una frase onesta — ma solo dopo aver detto
    qualcosa.

    Senza colore né tipo l'apertura ripiega su «provi a girare l'etichetta», e
    dirle dietro quella frase significa vantare una risposta che non c'è stata.
    Sentito sul dispositivo, parola per parola.
    """

    def test_col_tipo_la_frase_c_e(self):
        from amelie.matcher import Fatti, Livello
        from amelie.narrator import Narratore

        n = Narratore()
        try:
            f = Fatti(livello=Livello.GENERICO, colore="Rosato",
                      qualificatori=["spumante", "brut"])
            testo = n.racconta(f, consenti_modello=False).testo
            assert "non è nel mio archivio" in testo
            assert "spumante" in testo
        finally:
            n.chiudi()

    def test_il_colore_sta_dove_lo_vuole_la_lingua(self):
        """Accodato, in inglese usciva «a sparkling wine rosé»."""
        from amelie.lessico import carica
        from amelie.matcher import Fatti, Livello
        from amelie.narrator import _che_tipo_di_vino, titolo_generico

        lex = carica()
        f = Fatti(livello=Livello.GENERICO, colore="Rosato",
                  qualificatori=["spumante", "metodo", "brut"])
        assert _che_tipo_di_vino(f, lex, "it") == "uno spumante rosato metodo classico, brut"
        assert _che_tipo_di_vino(f, lex, "en") == "a rosé sparkling wine metodo classico, brut"
        assert titolo_generico(f, lex, "it") == "Spumante rosato metodo classico, brut"
        assert titolo_generico(f, lex, "en") == "Rosé sparkling wine metodo classico, brut"
        senza_colore = Fatti(livello=Livello.GENERICO, qualificatori=["frizzante"])
        assert _che_tipo_di_vino(senza_colore, lex, "it") == "un vino frizzante"
        assert _che_tipo_di_vino(senza_colore, lex, "en") == "a semi-sparkling wine"
        solo_colore = Fatti(livello=Livello.GENERICO, colore="Rosso")
        assert _che_tipo_di_vino(solo_colore, lex, "en") == "a red wine"
        assert titolo_generico(solo_colore, lex, "it") == "Vino rosso"

    def test_senza_niente_da_dire_la_frase_non_c_e(self):
        from amelie.matcher import Fatti, Livello
        from amelie.narrator import Narratore

        n = Narratore()
        try:
            testo = n.racconta(Fatti(livello=Livello.GENERICO),
                               consenti_modello=False).testo
            assert "non è nel mio archivio" not in testo
        finally:
            n.chiudi()


class TestAlGenericoIlModelloNonScrive:
    """GENERICO vuol dire: ogni parola detta viene dalla bottiglia.

    Dare quei quattro fatti a un modello e chiedergli una descrizione e'
    chiedergli di riempire il resto, e il resto se lo inventa. Visto sul
    dispositivo su un Lambrusco Grasparossa: «Colore giallo, con sapore
    delicato e acidita' equilibrata. In bocca e' un vino di media struttura,
    con bella acidita' e buona acidita'.» Un rosso dichiarato giallo, e
    l'acidita' detta due volte.

    `verifica` non lo prende, e non e' un suo difetto: controlla che non si
    nominino vitigni e denominazioni che non ci sono, ma il colore di un vino
    non e' un nome, e' un'affermazione. A questo livello non ce ne sono da
    fare.
    """

    def _narratore(self, chiamate):
        from amelie.narrator import Narratore

        def genera(_prompt):
            chiamate.append(_prompt)
            return "Colore giallo, con bella acidita' e buona acidita'."

        return Narratore(genera=genera)

    def test_col_modello_acceso_non_lo_si_chiama(self):
        from amelie.matcher import Fatti, Livello

        chiamate = []
        n = self._narratore(chiamate)
        try:
            f = Fatti(livello=Livello.GENERICO, colore="Rosato", sicurezza=88.0)
            f.qualificatori = ["spumante", "brut"]
            r = n.racconta(f, preferisci_modello=True)
            assert chiamate == [], "il modello e' stato chiamato al livello generico"
            assert r.origine != "modello"
            assert r.testo.strip()
        finally:
            n.chiudi()

    def test_e_a_un_livello_vero_invece_si(self):
        """La regola e' sul livello, non sul modello: altrove il modello serve."""
        from amelie.matcher import Fatti, Livello

        chiamate = []
        n = self._narratore(chiamate)
        try:
            f = Fatti(livello=Livello.TIPOLOGIA, denominazione="Barolo",
                      tipologia="Barolo", colore="Rosso", sicurezza=90.0,
                      # Col registro che ha detto la sua: senza citazione il
                      # modello non scrive comunque, vedi il cancello.
                      disciplinare={"colore": "rosso granato"})
            n.racconta(f, preferisci_modello=True)
            assert chiamate, "al livello tipologia il modello deve poter scrivere"
        finally:
            n.chiudi()


class TestLeBugieConParoleVere:
    """Dodici testi generati sul dispositivo, riletti: cinque sbagliati, tutti
    promossi. Non inventavano nomi, inventavano RAPPORTI fra nomi veri."""

    def _fatti(self, **kw):
        from amelie.matcher import Fatti, Livello
        f = Fatti(livello=Livello.DENOMINAZIONE, sicurezza=85.0, **kw)
        return f

    def test_una_nota_olfattiva_non_e_un_vitigno(self):
        from amelie.narrator import verifica

        f = self._fatti(denominazione="Brunello di Montalcino", colore="Rosso",
                        vitigni=["Sangiovese"], note_sensoriali=["amarena", "viola"])
        ok, inv = verifica("Nasce dall'incontro di Sangiovese e Amarena, i vitigni "
                           "più coltivati d'Italia.", f)
        assert not ok and any("Amarena" in x for x in inv)

    def test_ma_il_vitigno_vero_passa(self):
        from amelie.narrator import verifica

        f = self._fatti(denominazione="Brunello di Montalcino", colore="Rosso",
                        vitigni=["Sangiovese"], note_sensoriali=["amarena"])
        ok, inv = verifica("Nasce dal Sangiovese, con note di amarena.", f)
        assert ok, inv

    def test_il_vino_non_e_un_vitigno(self):
        from amelie.narrator import verifica

        f = self._fatti(denominazione="Amarone della Valpolicella",
                        vitigni=["Corvina", "Rondinella", "Corvinone"])
        ok, inv = verifica("Amarone della Valpolicella, un vitigno compagno dei "
                           "Rondinella, Corvinone e Corvina.", f)
        assert not ok and any("vino" in x for x in inv)

    def test_un_vino_fermo_non_ha_bollicine(self):
        from amelie.narrator import verifica

        f = self._fatti(denominazione="Amarone della Valpolicella",
                        categoria="Wine", vitigni=["Corvina"])
        ok, inv = verifica("Questa spumante nasce dai sedici gradi.", f)
        assert not ok and any("bollicine" in x for x in inv)

    def test_uno_spumante_invece_si(self):
        from amelie.narrator import verifica

        f = self._fatti(denominazione="Franciacorta", categoria="Sparkling Wine",
                        vitigni=["Chardonnay"])
        ok, inv = verifica("Uno spumante dal perlage fine.", f)
        assert ok, inv


class TestUnTestoTroncoSiChiudeSullaFraseIntera:
    def test_la_coda_a_meta_frase_si_toglie(self):
        from amelie.narrator import _ripulisci

        t = _ripulisci("Nasce dal Nebbiolo. Al palato è asciutto e pieno. "
                       "Da servire fra i diciassette e i dici")
        assert t == "Nasce dal Nebbiolo. Al palato è asciutto e pieno."

    def test_ma_non_si_butta_piu_di_meta(self):
        from amelie.narrator import _ripulisci

        t = _ripulisci("Breve. Una frase lunghissima che non finisce mai e "
                       "continua e continua senza un punto")
        assert t.endswith("…")


class TestAncheLaCacheSiVerifica:
    """La cache l'ha scritta lo stesso modello, prima: «Borgognone, ovunque nel
    mondo» su un Franciacorta usciva da li', e nessuno l'aveva mai riletto."""

    def test_un_testo_pronto_che_inventa_si_salta(self, tmp_path, monkeypatch):
        import sqlite3

        from amelie.matcher import Fatti, Livello
        from amelie.narrator import Narratore

        db = tmp_path / "a.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE racconto (ambito TEXT, ambito_id INT, lingua TEXT, testo TEXT)")
        con.execute("INSERT INTO racconto VALUES ('tipologia', 7, 'it', "
                    "'Borgognone, ovunque nel mondo. Si serve fra 10 e 12 gradi.')")
        con.commit(); con.close()
        n = Narratore(percorso_db=db)
        try:
            f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Franciacorta",
                      colore="Bianco", sicurezza=90.0, origine=("tipologia", 7))
            # In «generativa», senza modello: la cache e' la prima cosa che
            # si legge, e dev'essere lei a venire scartata.
            r = n.racconta(f, preferisci_modello=True)
            assert r.origine != "cache"
            assert "Borgognone" not in r.testo
        finally:
            n.chiudi()


class TestLeNoteOlfattiveNonSonoNeUveNeCibi:
    """Seconda rilettura, dopo la prima stretta: le note finivano nei posti
    delle uve e dei cibi, in minuscolo, dove i nomi propri non si guardano."""

    def _fatti(self, **kw):
        from amelie.matcher import Fatti, Livello
        return Fatti(livello=Livello.TIPOLOGIA, sicurezza=85.0, **kw)

    def test_mela_verde_non_e_un_vitigno(self):
        from amelie.narrator import verifica

        f = self._fatti(tipologia="Prosecco", colore="Bianco", vitigni=["Glera"],
                        note_sensoriali=["mela verde", "fiori bianchi"])
        ok, inv = verifica("Nasce dall'incontro di mela verde e fiori bianchi, "
                           "il vitigno Prosecco.", f)
        assert not ok and any("vitigno" in x for x in inv)

    def test_l_amarena_non_si_serve_a_tavola(self):
        from amelie.narrator import verifica

        f = self._fatti(tipologia="Cerasuolo d'Abruzzo", colore="Rosato",
                        vitigni=["Montepulciano"], note_sensoriali=["amarena", "prugna"],
                        abbinamenti=["pizza"])
        ok, inv = verifica("Da servire con amarena, prugna o tannino morbido.", f)
        assert not ok
        assert any("cibo" in x for x in inv) and any("tannino" in x for x in inv)

    def test_ma_le_note_al_naso_passano(self):
        from amelie.narrator import verifica

        f = self._fatti(tipologia="Cerasuolo d'Abruzzo", colore="Rosato",
                        vitigni=["Montepulciano"], note_sensoriali=["amarena", "prugna"],
                        abbinamenti=["pizza"])
        ok, inv = verifica("Al naso amarena e prugna. Si accompagna bene a pizza.", f)
        assert ok, inv

    def test_una_parola_ripetuta_di_seguito(self):
        from amelie.narrator import verifica

        f = self._fatti(tipologia="Nero d'Avola", colore="Rosso")
        ok, inv = verifica("In bocca è gradevole, delicato, delicato, fruttato.", f)
        assert not ok and any("ripetizione" in x for x in inv)


class TestIlRaccontoCompostoDaiFatti:
    """Il modo «archivio»: l'unico di cui si possa dire che non inventa.

    Ogni frase nasce da un campo dell'archivio dentro una forma del lessico;
    il seme sceglie la forma, sempre la stessa per lo stesso vino. Breve: al
    massimo quattro frasi dopo l'apertura.
    """

    def _barolo(self, **kw):
        base = dict(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi di Barolo",
                    annata=2016, denominazione="Barolo", vitigni=["Nebbiolo"],
                    corpo="Full-bodied", acidita="High", abbinamenti=["Beef", "Lamb"],
                    temperatura_c="17-19", sicurezza=95.0, colore="Rosso")
        base.update(kw)
        return Fatti(**base)

    def test_lo_stesso_vino_si_racconta_sempre_con_le_stesse_parole(self):
        assert template(self._barolo()) == template(self._barolo())

    def test_il_seme_e_stabile_fra_un_avvio_e_l_altro(self):
        from amelie.narrator import seme_di
        # `crc32` di una stringa nota: se cambia, cambia il racconto di ogni
        # vino a ogni riavvio, e nessuno se ne accorgerebbe dai test.
        assert seme_di(self._barolo()) == 331640975
        assert seme_di(self._barolo()) != seme_di(self._barolo(nome="Brunate"))

    def test_e_breve(self):
        from amelie.narrator import spezza_in_frasi
        t = template(self._barolo(disciplinare={
            "colore": "rosso granato", "odore": "intenso e caratteristico",
            "sapore": "asciutto, pieno, armonico"}))
        assert len(spezza_in_frasi(t)) <= 5, t

    def test_temperatura_e_tavola_stanno_in_una_frase_sola(self):
        t = template(self._barolo())
        assert "17 e 19" in t and "manzo" in t
        assert t.count("gradi") == 1
        frase = next(f for f in t.split(". ") if "gradi" in f)
        assert "manzo" in frase

    def test_col_disciplinare_corpo_e_acidita_tacciono(self):
        t = template(self._barolo(disciplinare={"colore": "rosso granato",
                                                "sapore": "asciutto, pieno"}))
        assert "struttura" not in t and "acidità" not in t

    def test_senza_disciplinare_parlano(self):
        t = template(self._barolo())
        assert "struttura" in t or "acidità" in t

    def test_supera_sempre_la_verifica(self):
        f = self._barolo(disciplinare={"colore": "rosso granato", "odore": "intenso",
                                       "sapore": "asciutto, pieno, armonico"})
        for lingua in ("it", "en"):
            ok, inv = verifica(template(f, lingua=lingua), f, lingua)
            assert ok, (lingua, inv)


class TestInArchivioIlModelloNonParlaMai:
    """La garanzia vale solo se non ha eccezioni: in modo «archivio» ne' il
    modello dal vivo ne' la cache, che e' lo stesso modello un giorno prima."""

    def test_in_archivio_la_cache_non_si_legge(self, tmp_path):
        import sqlite3
        from amelie.narrator import Narratore

        db = tmp_path / "a.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE racconto (ambito TEXT, ambito_id INT, lingua TEXT, testo TEXT)")
        con.execute("INSERT INTO racconto VALUES ('tipologia', 7, 'it', "
                    "'Nasce dal Nebbiolo.')")
        con.commit(); con.close()
        chiamate = []
        n = Narratore(percorso_db=db, genera=lambda p: chiamate.append(p) or "x.")
        try:
            f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo", colore="Rosso",
                      vitigni=["Nebbiolo"], sicurezza=90.0, origine=("tipologia", 7),
                      disciplinare={"colore": "rosso granato"})
            r = n.racconta(f, preferisci_modello=False)
            assert r.origine == "template"
            assert chiamate == []
            # E in «generativa» invece la cache si usa, se regge la verifica.
            r = n.racconta(f, preferisci_modello=True)
            assert r.origine in ("cache", "modello")
        finally:
            n.chiudi()


class TestLaRevisioneDelRaccontoComposto:
    """Trentatre' segnalazioni di una revisione a piu' lenti sul racconto
    composto, riprodotte sull'archivio vero. Quelle vere stanno qui, perche'
    non tornino."""

    def _fatti(self, **kw):
        base = dict(livello=Livello.TIPOLOGIA, tipologia="Franciacorta",
                    colore="Bianco", sicurezza=90.0, vitigni=["Chardonnay", "Erbamat"],
                    note_vitigno="Borgognone, ovunque nel mondo. In Italia va ovunque.")
        base.update(kw)
        return Fatti(**base)

    def test_la_scheda_del_vitigno_porta_il_suo_nome_davanti(self):
        """«Questa bottiglia e' un Franciacorta. Borgognone, ovunque nel
        mondo.»: parole vere dell'archivio, soggetto sbagliato."""
        t = template(self._fatti())
        assert "Chardonnay: Borgognone, ovunque nel mondo." in t

    def test_con_un_uva_sola_la_scheda_si_aggancia_alle_uve(self):
        t = template(self._fatti(vitigni=["Chardonnay"]))
        assert "Chardonnay: Borgognone, ovunque nel mondo." in t
        assert "Chardonnay. Chardonnay" not in t

    def test_ma_non_se_la_scheda_lo_nomina_gia(self):
        t = template(self._fatti(note_vitigno="Lo Chardonnay e' ovunque. Anche qui."))
        assert "Chardonnay: Lo Chardonnay" not in t
        assert "Lo Chardonnay e' ovunque." in t

    def test_quattro_uve_si_dicono_tutte(self):
        """Il Bardolino ne ha quattro a pari merito, e con tre si perdeva la
        Corvina."""
        t = template(self._fatti(vitigni=["Molinara", "Rondinella", "Corvinone", "Corvina"],
                                 note_vitigno=None))
        assert "Corvina" in t

    def test_una_citazione_col_verbo_non_finisce_dopo_una_copula(self):
        """«Il sapore e' sono asciutti armonici», letto sul dispositivo."""
        f = self._fatti(note_vitigno=None,
                        disciplinare={"sapore": "sono asciutti armonici con retrogusto amarognolo"})
        t = template(f)
        assert "è sono" not in t and "sono asciutti armonici" in t

    def test_una_citazione_relativa_vuole_un_nome_davanti(self):
        """«Il disciplinare lo vuole che va dal giallo paglierino»."""
        f = self._fatti(note_vitigno=None,
                        disciplinare={"colore": "che va dal giallo paglierino a verdognolo"})
        t = template(f)
        assert "vuole che" not in t and "lo descrive come che" not in t
        assert "colore che va dal giallo paglierino" in t

    def test_la_forma_non_ripete_una_parola_della_citazione(self):
        """«il gusto e' ... con lieve gusto di mandorla»: su tutti i semi."""
        from amelie.narrator import _frase_di_citazione
        from amelie.lessico import carica
        for seme in range(40):
            t = _frase_di_citazione(carica(), "it", seme, "sapore",
                                    "asciutto, con lieve gusto di mandorla")
            assert "gusto è" not in t, t

    def test_in_inglese_un_participio_sta_solo_dopo_la_virgola(self):
        from amelie.narrator import _frase_di_citazione
        from amelie.lessico import carica
        for seme in range(40):
            t = _frase_di_citazione(carica(), "en", seme, "sapore", "ranging from dry to sweet")
            assert "is ranging" not in t and "be ranging" not in t and "as ranging" not in t, t

    def test_in_inglese_may_be_ha_il_suo_soggetto(self):
        from amelie.narrator import _frase_di_citazione
        from amelie.lessico import carica
        t = _frase_di_citazione(carica(), "en", 3, "sapore", "may be pleasantly fruity")
        assert "it may be pleasantly fruity" in t

    def test_davanti_a_una_a_l_italiano_vuole_ad(self):
        t = template(self._fatti(note_vitigno=None, abbinamenti=["Appetizer", "Lamb"],
                                 temperatura_c="6-8"))
        assert "a antipasti" not in t and "a aperitivo" not in t

    def test_la_coda_tronca_con_l_articolo_eliso(self):
        from amelie.narrator import _senza_coda_tronca
        assert _senza_coda_tronca("giallo ambrato, all'") == "giallo ambrato"
        assert _senza_coda_tronca("rosso rubino con riflessi violacei e dall’") == \
            "rosso rubino con riflessi violacei"

    def test_il_seme_per_frase_mescola_anche_su_liste_pari(self):
        """Con lo XOR uscivano quattro combinazioni su ventimila semi."""
        from amelie.narrator import _seme_per
        chiavi = ["disciplinare_colore", "disciplinare_sapore", "servizio_intervallo",
                  "abbinamenti", "vino_dubbio", "temperatura_intervallo"]
        combinazioni = {tuple(_seme_per(s, k) % 4 for k in chiavi) for s in range(0, 4_000_000, 997)}
        assert len(combinazioni) > 500


class TestLaVerificaDopoLaRevisione:
    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Chianti", vitigni=["Sangiovese", "Canaiolo"],
                    note_sensoriali=["amarena", "prugna", "acidità viva"], colore="Rosso",
                    sicurezza=95.0)
        base.update(kw)
        return Fatti(**base)

    def test_l_elenco_delle_uve_si_guarda_tutto(self):
        """«Nasce dal Sangiovese, Amarena e Canaiolo» passava: la prima
        versione si fermava alla virgola."""
        assert not verifica("Nasce dal Sangiovese, Amarena e Canaiolo.", self._fatti())[0]

    def test_ma_un_inciso_dopo_la_virgola_no(self):
        assert verifica("Nasce dal Sangiovese, con note di amarena.", self._fatti())[0]
        assert verifica("Nasce dal Sangiovese, il vitigno della zona.", self._fatti())[0]

    def test_un_uva_nominata_dentro_una_scheda_non_trascina_i_profumi(self):
        """«Nome popolare dell'uva Isabella, ibrido americano dal profumo di
        fragola»: l'elenco finisce a Isabella."""
        f = self._fatti(vitigni=["Isabella"], note_sensoriali=["fragola"])
        assert verifica("Nome popolare dell'uva Isabella, ibrido americano dal "
                        "profumo di fragola.", f)[0]

    def test_vitigno_con_l_aggettivo_non_e_un_elenco(self):
        """La scheda della Molinara: «Vitigno veronese dal colore tenue e
        dall'acidita' viva» - e la nota «acidita' viva» finiva letta come uva."""
        f = self._fatti(vitigni=["Molinara"])
        assert verifica("Molinara: Vitigno veronese dal colore tenue e dall'acidità viva.", f)[0]

    def test_l_apostrofo_tipografico_vale_come_quello_dritto(self):
        assert not verifica("Nasce dall’incontro di Sangiovese e Amarena.", self._fatti())[0]

    def test_il_vino_detto_vitigno_anche_con_che_e(self):
        f = self._fatti(livello=Livello.DENOMINAZIONE, nome=None,
                        denominazione="Amarone della Valpolicella", vitigni=["Corvina"])
        assert not verifica("Amarone della Valpolicella, che è un vitigno del Veneto.", f)[0]
        assert not verifica("Amarone della Valpolicella e' un vitigno.", f)[0]

    def test_le_ripetizioni_che_si_prendono_e_quelle_che_no(self):
        from amelie.narrator import _parole_ripetute
        assert _parole_ripetute("In bocca è delicato delicato e fruttato.")
        assert not _parole_ripetute("con bella acidità e buona acidità.")
        assert not _parole_ripetute("It goes well with cheese and matured cheese.")
        assert not _parole_ripetute("Nasce da Schiava, Schiava Gentile e Schiava Grigia.")
        assert not _parole_ripetute("Direi un Pantelleria Pantelleria-Bianco.")
        assert not _parole_ripetute("con antipasti, dolci, dolci secchi e frutta.")


class TestInFlussoValeLaStessaRegola:
    def test_senza_preferire_il_modello_le_frasi_sono_composte(self):
        from amelie.narrator import Narratore
        chiamate = []

        def genera(p):
            chiamate.append(p); yield "Ha vinto tre stelle. "

        n = Narratore(genera=lambda p: "Ha vinto tre stelle.", genera_a_flusso=genera)
        try:
            f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=90.0)
            frasi = list(n.racconta_a_frasi(f))
            assert chiamate == [] and frasi
        finally:
            n.chiudi()


class TestCioCheLaVerificaLasciavaPassare:
    """Letti sui trenta testi della misura di riferimento: passavano tutti."""

    def test_un_rosato_non_e_rosso(self):
        f = Fatti(livello=Livello.VINO, nome="Infinito Rosé", colore="Rosato",
                  vitigni=["Corvina"], sicurezza=95.0)
        assert not verifica("Il vino è rosato, di colore rosso, con note di ciliegia.", f)[0]
        assert verifica("Il vino è rosato, con note di ciliegia.", f)[0]

    def test_un_colore_non_e_una_categoria(self):
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Asti", colore="Bianco",
                  categoria="Sparkling Wine", sicurezza=95.0)
        assert not verifica("Il vino è di colore spumante, con note di pesca.", f)[0]

    def test_la_stessa_coppia_due_volte(self):
        f = Fatti(livello=Livello.VINO, nome="Cannubi", colore="Rosso", sicurezza=95.0)
        assert not verifica("È di corpo medio, con bella acidità e bella acidità.", f)[0]
        # Un nome proprio che torna non e' una ripetizione: e' il vitigno.
        f2 = Fatti(livello=Livello.VINO, nome="Piave Cabernet", colore="Rosso",
                   vitigni=["Cabernet Sauvignon"], sicurezza=95.0)
        assert verifica("Nasce dal Cabernet Sauvignon, e il Cabernet Sauvignon qui è pieno.", f2)[0]
        assert verifica("Nasce da Schiava, Schiava Gentile e Schiava Grigia.",
                        Fatti(livello=Livello.VINO, nome="Santa Maddalena", colore="Rosso",
                              vitigni=["Schiava", "Schiava Gentile", "Schiava Grigia"],
                              sicurezza=95.0))[0]


class TestLaGabbia:
    """Il modello sceglie e combina, ma solo fra parole ammesse."""

    def _fatti(self):
        return Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo", denominazione="Barolo",
                     colore="Rosso", vitigni=["Nebbiolo"], note_sensoriali=["catrame", "rosa"],
                     abbinamenti=["Beef"], temperatura_c="17-19", sicurezza=95.0,
                     disciplinare={"colore": "rosso granato"})

    def test_ammette_i_fatti_e_il_raccordo_e_niente_altro(self):
        from amelie.gabbia import gabbia_di, lessico
        g = gabbia_di(self._fatti(), "it")
        assert g and '"Nebbiolo"' in g and '"catrame"' in g
        assert "nasce" in lessico("it") and '"nasce"' in g
        assert '"Amarena"' not in g and '"borgognone"' not in g

    def test_in_inglese_non_c_e_e_si_dice(self):
        from amelie.gabbia import gabbia_di
        assert gabbia_di(self._fatti(), "en") is None

    def test_il_narratore_la_passa_al_modello_solo_se_accesa(self):
        from amelie.narrator import Narratore
        ricevute = []

        def genera(p, grammatica=None):
            ricevute.append(grammatica)
            return "Nasce dal Nebbiolo. Si serve fra 17 e 19 gradi."

        for accesa in (True, False):
            n = Narratore(genera=genera, gabbia=accesa)
            try:
                n.racconta(self._fatti(), preferisci_modello=True)
            finally:
                n.chiudi()
        assert ricevute[0] and "Nebbiolo" in ricevute[0]
        assert ricevute[1] is None


class TestGliElenchiCheSiRipetono:
    """Trovati su testi COMPOSTI, dove ogni difetto e' un difetto vero: il
    registro elenca le sfumature ammesse e X-Wines gli abbinamenti, e a voce
    diventano «straw yellow, deep straw yellow and light straw yellow»."""

    def test_le_sfumature_del_registro_si_dicono_una_volta(self):
        from amelie.narrator import _senza_doppioni_di_elenco
        assert _senza_doppioni_di_elenco(
            ["giallo paglierino", "giallo paglierino carico",
             "giallo paglierino scarico"]) == ["giallo paglierino"]

    def test_ma_un_seguito_vero_resta(self):
        from amelie.narrator import _senza_doppioni_di_elenco
        assert _senza_doppioni_di_elenco(
            ["rosso rubino", "tendente al granato con l'invecchiamento"]) == \
            ["rosso rubino", "tendente al granato con l'invecchiamento"]

    def test_e_gli_abbinamenti_non_si_annidano(self):
        from amelie.matcher import Fatti, Livello
        f = Fatti(livello=Livello.DENOMINAZIONE, denominazione="Asti", colore="Bianco",
                  vitigni=["Moscato Bianco"], temperatura_c="6-8", sicurezza=95.0)
        f.abbinamenti = ["Dessert", "Fruit Dessert", "Fruit"]
        t = template(f, lingua="en")
        assert "desserts, fruit desserts" not in t.lower()
        ok, inv = verifica(t, f, "en")
        assert ok, inv


class TestLoSpezzafrasiELeCitazioni:
    def test_un_iniziale_puntata_non_chiude_una_frase(self):
        """«di M. Marengo»: la voce faceva una pausa in mezzo al nome della
        cantina, e a schermo si illuminava la frase sbagliata."""
        from amelie.narrator import spezza_in_frasi

        assert spezza_in_frasi("Questo è il Barolo di M. Marengo. Nasce dal Nebbiolo.") == \
            ["Questo è il Barolo di M. Marengo.", "Nasce dal Nebbiolo."]
        assert len(spezza_in_frasi("Il vino di Abbazia di S. Gaudenzio è fresco.")) == 1

    def test_una_ripetizione_dentro_una_citazione_non_e_nostra(self):
        """Il registro enumera le sfumature ammesse: «rosso rubino più o meno
        intenso, rosa più o meno intenso». Noi le riportiamo."""
        f = Fatti(livello=Livello.VINO, nome="Cannonau", colore="Rosato",
                  vitigni=["Cannonau"], sicurezza=95.0,
                  disciplinare={"colore": "rosso rubino più o meno intenso, "
                                          "rosa più o meno intenso"})
        assert verifica("Il disciplinare lo vuole rosso rubino più o meno intenso, "
                        "rosa più o meno intenso.", f)[0]
        # Ma fuori dalla citazione resta un difetto.
        assert not verifica("In bocca è più o meno intenso e più o meno intenso.",
                            Fatti(livello=Livello.VINO, nome="X", colore="Rosso",
                                  sicurezza=95.0))[0]


class TestIlCancelloDelModello:
    """Il modello scrive solo quando il registro ha detto la sua.

    Misurato su 210 bottiglie stratificate: con la citazione del disciplinare
    passa 84 volte su 85, senza 104 su 125. E i testi senza citazione sono
    quelli in cui inventa i piatti e mette i cibi al posto dei profumi.
    """

    def _fatti(self, **kw):
        base = dict(livello=Livello.TIPOLOGIA, tipologia="Barolo", colore="Rosso",
                    vitigni=["Nebbiolo"], sicurezza=95.0)
        base.update(kw)
        return Fatti(**base)

    def test_senza_citazione_il_modello_non_viene_chiamato(self):
        from amelie.narrator import Narratore
        chiamate = []
        n = Narratore(genera=lambda p, g=None: chiamate.append(p) or "x.")
        try:
            r = n.racconta(self._fatti(), preferisci_modello=True)
            assert chiamate == [] and r.origine == "template"
        finally:
            n.chiudi()

    def test_con_la_citazione_si(self):
        from amelie.narrator import Narratore
        chiamate = []

        def genera(p, g=None):
            chiamate.append(p)
            return "Nasce dal Nebbiolo. Il disciplinare lo vuole rosso granato."

        n = Narratore(genera=genera)
        try:
            f = self._fatti(disciplinare={"colore": "rosso granato"})
            n.racconta(f, preferisci_modello=True)
            assert chiamate
        finally:
            n.chiudi()

    def test_i_cibi_non_sono_profumi(self):
        """«note sensoriali tipiche di manzo, cacciagione, agnello e pasta»:
        passava, perche' quelle parole stanno nei fatti."""
        f = self._fatti(abbinamenti=["Beef", "Game Meat"], note_sensoriali=["amarena"])
        ok, inv = verifica("È un rosso con note sensoriali tipiche di manzo e "
                           "cacciagione.", f)
        assert not ok and any("piatto" in x for x in inv)
        assert verifica("Al naso amarena. Si accompagna bene a manzo.", f)[0]


class TestInPurezza:
    """«Etna in purezza, il vitigno siciliano di Sicilia»: l'Etna e' la
    denominazione, e la frase passava perche' «Etna» sta nei fatti."""

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Etna Rosso Contrada Arcuria",
                    denominazione="Etna", regione="Sicilia", colore="Rosso",
                    vitigni=["Nerello Mascalese"], sicurezza=95.0,
                    disciplinare={"colore": "rosso rubino"})
        base.update(kw)
        return Fatti(**base)

    def test_quel_che_sta_in_purezza_dev_essere_un_uva(self):
        ok, inv = verifica("Etna in purezza, il vitigno siciliano di Sicilia.", self._fatti())
        assert not ok and any("purezza" in x for x in inv)

    def test_e_il_vitigno_vero_passa(self):
        assert verifica("Nerello Mascalese in purezza, siciliano.", self._fatti())[0]


class TestUnLuogoNonEUnUva:
    """«It comes from Ripa Teatina»: un paese messo dove vanno le uve.
    Passava perche' quel nome sta nei fatti - e' la denominazione."""

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Arenile Pecorino",
                    denominazione="Ripa Teatina", colore="Bianco",
                    vitigni=["Pecorino"], sicurezza=95.0,
                    disciplinare={"colore": "giallo paglierino"})
        base.update(kw)
        return Fatti(**base)

    def test_il_da_liscio_apre_un_elenco_di_uve(self):
        """«Nasce da Barbaresco»: c'erano «dal», «dalla», «dai», non «da»."""
        f = self._fatti(nome="Arenile Pecorino", denominazione="Ripa Teatina")
        ok, inv = verifica("Nasce da Ripa Teatina: giallo paglierino.", f)
        assert not ok and any("uve" in x for x in inv)

    def test_nemmeno_il_produttore(self):
        """«Si ottiene da Restivo»: Restivo e' la cantina."""
        f = self._fatti(cantina="Restivo")
        ok, inv = verifica("Si ottiene da Restivo: rosso rubino con riflessi granato.", f)
        assert not ok and any("uve" in x for x in inv)

    def test_la_denominazione_non_sta_fra_le_uve(self):
        ok, inv = verifica("It comes from Ripa Teatina: from Abruzzo.",
                           self._fatti(regione="Abruzzo"), "en")
        assert not ok and any("uve" in x for x in inv)

    def test_ma_il_vitigno_vero_si(self):
        assert verifica("It comes from Pecorino: recovered after nearly disappearing.",
                        self._fatti(note_vitigno="recovered after nearly disappearing"),
                        "en")[0]

    def test_e_un_nome_che_contiene_il_vitigno_resta_lecito(self):
        """«Brachetto d'Acqui» contiene il Brachetto: e' un modo legittimo."""
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Brachetto d'Acqui",
                  denominazione="Brachetto d'Acqui", colore="Rosso",
                  vitigni=["Brachetto"], sicurezza=95.0,
                  disciplinare={"colore": "rosso rubino"})
        assert verifica("Nasce dal Brachetto d'Acqui, vitigno di casa.", f)[0]


class TestChiLoFaNonEDoveSiFa:
    """«Si produce in Produttori di Manduria», letto sul dispositivo.

    Il modello impara la frase «Si produce in {regione}» e, quando la regione
    nei fatti non c'e', la riempie col primo nome proprio che trova.
    """

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Primitivo di Manduria Dolce",
                    denominazione="Primitivo di Manduria",
                    cantina="Produttori di Manduria", colore="Rosso",
                    vitigni=["Primitivo"], sicurezza=95.0,
                    disciplinare={"colore": "rosso intenso"})
        base.update(kw)
        return Fatti(**base)

    def test_la_cantina_non_e_un_luogo(self):
        ok, inv = verifica("Si produce in Produttori di Manduria. Il disciplinare "
                           "lo vuole rosso intenso.", self._fatti())
        assert not ok and any("chi lo produce" in x for x in inv)

    def test_la_regione_si(self):
        f = self._fatti(regione="Puglia")
        ok, _ = verifica("Si produce in Puglia. Il disciplinare lo vuole rosso intenso.", f)
        assert ok

    def test_una_denominazione_e_quasi_sempre_un_luogo(self):
        """«si produce a Montalcino» non e' un errore, e' come si dice."""
        f = self._fatti(cantina=None)
        ok, _ = verifica("Si produce in Primitivo di Manduria. Il disciplinare "
                         "lo vuole rosso intenso.", f)
        assert ok


class TestIlColoreNonSiBeve:
    """«In bocca è asciutto, di colore bianco», «On the palate, ruby red».

    Il modello ha tre citazioni - colore, odore, sapore - e ogni tanto mette
    quella del colore nel giro di frase del gusto. Le parole sono vere, il
    posto no. Sui racconti salvati dei due modelli succede nel 3-9% dei testi.
    """

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Rosso di prova", denominazione="Prova",
                    colore="Rosso", sicurezza=95.0,
                    disciplinare={"colore": "rosso rubino", "sapore": "asciutto e armonico"})
        base.update(kw)
        return Fatti(**base)

    def test_il_rubino_non_si_sente_in_bocca(self):
        ok, inv = verifica("In bocca è asciutto e armonico, rosso rubino.", self._fatti())
        assert not ok and any("il colore" in x for x in inv)

    def test_nemmeno_in_inglese(self):
        f = self._fatti(disciplinare={"colore": "ruby red", "sapore": "dry and harmonious"})
        ok, inv = verifica("On the palate, dry and harmonious, ruby red.", f, "en")
        assert not ok and any("il colore" in x for x in inv)

    def test_il_gusto_al_posto_suo_va_bene(self):
        ok, _ = verifica("In bocca è asciutto e armonico. Il disciplinare lo vuole "
                         "rosso rubino.", self._fatti())
        assert ok


class TestIlPostoDelleCose:
    """Due nomi veri messi nel posto di un'altra cosa, letti sul dispositivo.

    «This is the "Barbera del Monferrato" by Grignolino, Freisa, Dolcetto and
    Barbera»: quelle sono le uve, e quel record una cantina non ce l'ha
    nemmeno. «Morellino di Scansano: Italy's most planted grape»: quella e' la
    scheda del Sangiovese.
    """

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Morellino di Scansano",
                    denominazione="Morellino di Scansano", cantina="Bonacchi",
                    colore="Rosso", vitigni=["Sangiovese"], sicurezza=95.0,
                    note_vitigno="Il vitigno più coltivato d'Italia e l'anima della Toscana.",
                    disciplinare={"colore": "rosso rubino"})
        base.update(kw)
        return Fatti(**base)

    def test_le_uve_non_sono_il_produttore(self):
        f = self._fatti(cantina=None, vitigni=["Grignolino", "Freisa", "Dolcetto"])
        ok, inv = verifica("Questo è il «Morellino di Scansano» di Grignolino, Freisa "
                           "e Dolcetto. Il disciplinare lo vuole rosso rubino.", f)
        assert not ok and any("sono le uve" in x for x in inv)

    def test_il_produttore_vero_si(self):
        ok, _ = verifica("Questo è il «Morellino di Scansano» di Bonacchi. "
                         "Il disciplinare lo vuole rosso rubino.", self._fatti())
        assert ok

    def test_la_scheda_del_vitigno_non_va_sul_vino(self):
        ok, inv = verifica("Morellino di Scansano: Il vitigno più coltivato d'Italia "
                           "e l'anima della Toscana.", self._fatti())
        assert not ok and any("scheda del vitigno" in x for x in inv)

    def test_ma_sul_vitigno_si(self):
        ok, _ = verifica("Sangiovese: Il vitigno più coltivato d'Italia e l'anima "
                         "della Toscana. Il disciplinare lo vuole rosso rubino.",
                         self._fatti())
        assert ok

    def test_un_vino_che_si_chiama_come_la_sua_uva(self):
        """«Nero d'Avola: il rosso siciliano»: qui il nome e' l'uva, ed e' giusto."""
        f = self._fatti(nome="Nero d'Avola", denominazione="Sicilia",
                        vitigni=["Nero d'Avola"],
                        note_vitigno="Il rosso siciliano per eccellenza, di grande frutto.")
        ok, _ = verifica("Nero d'Avola: Il rosso siciliano per eccellenza, di grande "
                         "frutto. Il disciplinare lo vuole rosso rubino.", f)
        assert ok


class TestOgniVoceDellElencoDeveEssereUnUva:
    """«Nasce dall'incontro di tre vitigni: Trebbiano, Toscano, Abruzzese e Soave».

    La scheda del Trebbiano dice che non e' un vitigno solo «ma una famiglia
    numerosa: il Toscano, l'Abruzzese, quello di Soave». Il modello ne ha
    fatto quattro uve di questo vino. Parole tutte vere, fatto falso - e
    bastava che la parola stesse da qualche parte nei fatti perche' passasse.
    """

    def _fatti(self, **kw):
        base = dict(livello=Livello.VINO, nome="Casasole Orvieto Classico",
                    denominazione="Orvieto", cantina="Santa Cristina",
                    colore="Bianco", vitigni=["Trebbiano"], sicurezza=95.0,
                    note_vitigno="Non un vitigno solo ma una famiglia numerosa: "
                                 "il Toscano, l'Abruzzese, quello di Soave.",
                    disciplinare={"colore": "giallo paglierino"})
        base.update(kw)
        return Fatti(**base)

    def test_i_pezzi_della_famiglia_non_sono_uve_di_questo_vino(self):
        ok, inv = verifica("Nasce dall'incontro di tre vitigni: Trebbiano, Toscano, "
                           "Abruzzese e Soave.", self._fatti())
        assert not ok
        assert sum("fra le uve non c'e'" in x for x in inv) == 3

    def test_la_scheda_riportata_non_si_giudica(self):
        """«Trebbiano: non un vitigno solo ma una famiglia: il Toscano...»
        e' materiale dei fatti riportato, non un elenco di uve."""
        ok, _ = verifica("Trebbiano: Non un vitigno solo ma una famiglia numerosa: "
                         "il Toscano, l'Abruzzese, quello di Soave. Il disciplinare "
                         "lo vuole giallo paglierino.", self._fatti())
        assert ok

    def test_la_scheda_vale_solo_se_attribuita(self):
        """«Nasce da Siciliano, chiamato Ansonica in Toscana»: e' la scheda
        dell'Inzolia messa dove vanno le uve, e «Siciliano» un vitigno non e'."""
        f = self._fatti(vitigni=["Ansonica"],
                        note_vitigno="Siciliano, chiamato Ansonica in Toscana "
                                     "dove è arrivato dall'isola.")
        ok, inv = verifica("Nasce da Siciliano, chiamato Ansonica in Toscana dove "
                           "è arrivato dall'isola.", f)
        assert not ok and any("fra le uve non c'e'" in x for x in inv)

    def test_ma_attribuita_va_bene(self):
        f = self._fatti(vitigni=["Ansonica"],
                        note_vitigno="Siciliano, chiamato Ansonica in Toscana "
                                     "dove è arrivato dall'isola.")
        ok, _ = verifica("Ansonica: Siciliano, chiamato Ansonica in Toscana dove "
                         "è arrivato dall'isola. Il disciplinare lo vuole giallo "
                         "paglierino.", f)
        assert ok

    def test_il_nome_fra_virgolette_non_e_un_elenco(self):
        """«Da Uve Garganega Monte Fiorentine»: quell'«Uve» e' l'etichetta."""
        f = self._fatti(nome="Da Uve Garganega Monte Fiorentine", vitigni=["Garganega"])
        ok, _ = verifica("Questo è il «Da Uve Garganega Monte Fiorentine» di Santa "
                         "Cristina. Il disciplinare lo vuole giallo paglierino.", f)
        assert ok

    def test_nemmeno_una_cantina_che_si_chiama_uva(self):
        """Esiste «Uva Mia di Luisella», e quell'«Uva» apriva un elenco finto."""
        f = self._fatti(cantina="Uva Mia di Luisella")
        ok, _ = verifica("Questo è il «Casasole Orvieto Classico» di Uva Mia di "
                         "Luisella. Il disciplinare lo vuole giallo paglierino.", f)
        assert ok

    def test_un_nome_composto_resta_una_voce_sola(self):
        """«Brachetto d'Acqui» e' un modo legittimo di dire il Brachetto."""
        f = self._fatti(nome="Brachetto d'Acqui", denominazione="Brachetto d'Acqui",
                        vitigni=["Brachetto"])
        assert verifica("Nasce dal Brachetto d'Acqui, vitigno di casa.", f)[0]

    def test_la_regione_in_un_elenco_di_uve_si_perdona(self):
        f = self._fatti(regione="Umbria")
        assert verifica("Nasce dal Trebbiano, Umbria. Il disciplinare lo vuole "
                        "giallo paglierino.", f)[0]


def test_un_racconto_pronto_che_nomina_un_uva_finta_si_salta(matcher):
    """Quarantotto testi pronti dicono «Nasce da na.»: scritti quando il
    vitigno «na» del registro passava per un'uva. Si saltano."""
    from amelie.narrator import Narratore
    n = Narratore()
    try:
        f = matcher.fatti_di("tipologia", 3400)
        with n._db:
            r = n.con.execute("SELECT testo FROM racconto WHERE ambito='tipologia'"
                              " AND ambito_id=3400 AND lingua='it'").fetchone()
        assert r is not None and "da na." in r["testo"]
        assert n._dalla_cache(f, solo_esatto=True) is None
    finally:
        n.chiudi()
