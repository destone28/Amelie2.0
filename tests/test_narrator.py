"""Test del racconto.

Il test che conta è quello sull'invenzione: il dispositivo può dire meno di
quello che sa, mai più. Un racconto che aggiunge un premio, un'annata o un
luogo che non stanno nei fatti è un guasto, non un'imprecisione.
"""

import pytest

from amelie.matcher import Fatti, Livello
from amelie.narrator import (
    PAROLE_MAX,
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


class TestTemplate:
    def test_il_livello_vino_e_affermativo(self, barolo):
        t = template(barolo)
        assert "Questo è il" in t
        assert "Cannubi" in t and "Marchesi di Barolo" in t

    def test_il_livello_tipologia_dichiara_l_incertezza(self):
        f = Fatti(livello=Livello.TIPOLOGIA, tipologia="Barolo Riserva",
                  denominazione="Barolo", sicurezza=80.0)
        t = template(f)
        assert "non riesco a leggere" in t.lower()
        assert "Barolo Riserva" in t

    def test_il_livello_vitigno_non_attribuisce_al_produttore(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=80.0)
        t = template(f)
        assert "produttore non sono sicuro" in t.lower()

    def test_un_vino_certo_si_annuncia_come_certo(self):
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=95.0)
        assert template(f).startswith("Questo è il")

    def test_un_vino_dubbio_non_si_annuncia_come_certo(self):
        """Sicurezza 80: il record e' completo, la somiglianza no."""
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", annata=2016, sicurezza=80.0)
        t = template(f)
        assert not t.startswith("Questo è il")
        assert "Direi che è il" in t
        assert "Barolo Cannubi" in t

    def test_una_somiglianza_bassa_si_dichiara_tale(self):
        """Il difetto piu' insidioso: un record perfetto trovato male.

        MATCH_ASSENTE porta al racconto anche sotto la soglia dubbia. Se
        l'apertura guardasse solo il livello, il dispositivo direbbe al tavolo
        «Questo è il Barolo di Marchesi di Barolo» con il 60% di somiglianza.
        """
        f = Fatti(livello=Livello.VINO, nome="Barolo Cannubi",
                  cantina="Marchesi di Barolo", sicurezza=60.0)
        t = template(f)
        assert "non è nitida" in t
        assert "potrebbe essere" in t.lower()

    def test_anche_i_livelli_deboli_si_smorzano_sotto_la_soglia(self):
        f = Fatti(livello=Livello.VITIGNO, vitigni=["Nebbiolo"], sicurezza=50.0)
        assert "non è nitida" in template(f)

    def test_il_template_supera_sempre_la_verifica(self, barolo):
        """La rete di sicurezza non puo' essere quella che inventa."""
        assert verifica(template(barolo), barolo)[0]

    def test_la_temperatura_si_legge_ad_alta_voce(self, barolo):
        """'17-19' pronunciato diventa 'diciassette trattino diciannove'."""
        t = template(barolo)
        assert "17-19" not in t
        assert "fra 17 e 19 gradi" in t

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
                    n.racconta(f)
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
            """Finge ALSA: accetta al ritmo del suono, non a velocità infinita.

            Senza questa attesa il thread che versa gira a vuoto a piena
            velocità e il test non finisce più. È ALSA a dettare il passo, e un
            finto che non blocca non è un finto fedele.
            """

            def __init__(self, scritti):
                self.scritti = scritti

            def write(self, dati):
                self.scritti.append(bytes(dati))
                time.sleep(len(dati) / (22050 * 2))

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
        from amelie.speech import Uscita
        v, _ = self._voce_finta(monkeypatch)
        try:
            u = v.uscita()
            u.scrivi(b"\x11\x22" * 22050)      # un secondo
            u.svuota()
            assert u.in_pancia_s() == 0.0
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
            def write(self, dati):
                import time
                self.scritti.append(bytes(dati))
                time.sleep(len(dati) / (22050 * 2))
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
