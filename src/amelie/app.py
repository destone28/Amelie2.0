"""L'orchestratore: mette insieme sensore, camera, riconoscimento, voce e schermo.

Un solo processo, un solo ciclo. Il lavoro pesante — cattura, OCR, generazione,
sintesi — gira in un thread separato, perché sono operazioni che bloccano per
secondi e il ciclo degli eventi deve restare libero di aggiornare lo schermo.

## La regola che decide l'architettura

**Niente gira in parallelo.** OCR, modello e voce si contendono gli stessi
quattro core, e su questa board sono tutti e tre al limite: farli concorrere li
rallenta tutti. La pipeline è quindi rigorosamente sequenziale, e questo risolve
gratis anche la contesa sul bus USB — lo stream della camera si chiude prima che
la voce cominci.

## Il tempo

Il momento in cui l'ospite appoggia la bottiglia è l'unica cosa che il
dispositivo non controlla. Da lì:

    assestamento    0,6 s   la bottiglia smette di oscillare
    scatto          0,3 s   luce, scarto dei fotogrammi vecchi, raffica
    OCR             3,8 s   il vero costo
    riconoscimento  ~0 s    SQLite
    racconto        ~0 s    se è in cache; 65 s se va generato dal vivo

Perciò il testo pre-generato non è un'ottimizzazione: è ciò che rende il
dispositivo utilizzabile. E l'anello di luce copre i quattro secondi di lavoro
con qualcosa da guardare.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bridge import (
    AMBRA, BIANCO_SCATTO, ROSSO, SPENTO, VERDE,
    Colore, ErroreMCU, Ponte, PonteNonDisponibile, PonteSimulato, Presenza,
)
from .capture import Camera, CameraNonDisponibile, blocca_esposizione
from .matcher import Fatti, Livello, Matcher
from .narrator import Narratore, spezza_in_frasi
from .ocr import Lettore, OCRNonDisponibile
from .speech import (
    VOLUME_PREDEFINITO, ImpostazioniVoce, Riproduttore, Voce, VoceNonDisponibile,
)
from .state import DURATE_S, EFFETTI_INGRESSO, Effetto, Evento, Macchina, Stato

log = logging.getLogger("amelie")

RADICE = Path(__file__).resolve().parents[2]
STATICI = Path(__file__).resolve().parent / "ui" / "static"

# Come si vede ogni stato sullo schermo.
VISTA = {
    Stato.ATTESA: "attesa",
    Stato.ASSESTAMENTO: "lavoro",
    Stato.SCANSIONE: "lavoro",
    Stato.RICONOSCIMENTO: "lavoro",
    Stato.CONFERMA: "conferma",
    Stato.RACCONTO: "racconto",
    Stato.CONCLUSO: "racconto",
    Stato.RIPOSIZIONA: "avviso",
    Stato.GUASTO: "avviso",
}

# Dopo tre letture a vuoto si smette di riprovare.
TENTATIVI_MAX = 3

# Di quanto saltano i due pulsanti laterali. Cinque secondi: meno non si
# distingue da un tocco a vuoto, di piu' scavalca una frase intera.
SALTO_S = 5.0
# Quanto puo' durare al massimo un racconto prima che il thread di lavoro si
# liberi comunque. Serve al caso in cui qualcuno mette in pausa e si alza da
# tavola: la bottiglia tolta lo chiude subito, ma se nessuno la toglie il
# dispositivo non puo' restare occupato per sempre.
TETTO_RACCONTO_S = 900.0

# Il volume regolato a schermo sopravvive allo spegnimento: chi apre il
# ristorante non deve ritararlo ogni sera. Sta in `var`, che e' l'unica cartella
# del progetto che l'unita' systemd lascia scrivibile.
PERCORSO_VOLUME = RADICE / "var" / "volume"
# Di quanto sale e scende a ogni tocco. Dieci passi da un capo all'altro: meno
# non si sente, di piu' non si regola.
PASSO_VOLUME = 10
# Quanto si aspetta prima di far sentire il colpetto di ritorno. Chi tara il
# volume preme piu' volte di fila, e un colpetto per pressione sarebbe un
# tambureggiamento: si suona quando la mano si e' fermata.
RIPOSO_VOLUME_S = 0.35

# Il tono di ogni schermata, per tenere schermo e anello d'accordo. Prima erano
# tutti dello stesso oro: un guasto aveva l'aria di un invito.
TONO = {
    Stato.RIPOSIZIONA: "invito",     # ambra: si chiede una cosa
    Stato.GUASTO: "errore",          # rosso: qualcosa non ha funzionato
    Stato.CONCLUSO: "neutro",
}

COLORE_ANELLO = {
    Effetto.ANELLO_RESPIRO: AMBRA,
    Effetto.ANELLO_ACCESO: VERDE,
    Effetto.ANELLO_LAVORO: AMBRA,
    Effetto.ANELLO_ATTENZIONE: ROSSO,
    Effetto.ANELLO_SPENTO: SPENTO,
}


@dataclass
class Configurazione:
    simula_mcu: bool = False
    senza_camera: bool = False
    senza_voce: bool = False
    # Il modello e' SPENTO in modo predefinito, e non e' una scelta di comodo.
    # Misurato su questa board, un modello da 1 miliardo di parametri produce
    # italiano non presentabile: «La Falanghina e' un'annata di media eta'»,
    # «Il colore della bacca e' bianco» (recita l'etichetta del campo), e sul
    # Nebbiolo inverte i fatti - il template dice «colore scarico» e lui scrive
    # «colore scuro». Provati anche Qwen 2.5 1.5B (peggiore e piu' lento) e la
    # riscrittura del template (butta via meta' dei fatti).
    # Il testo pre-generato in cache resta la prima scelta; sotto c'e' il
    # template, che e' vero per costruzione. Con --con-modello si riaccende la
    # generazione dal vivo per l'ignoto.
    senza_modello: bool = True
    device_audio: str = "plughw:0,3"
    porta: int = 8080
    periodo_sensore_s: float = 0.15
    # La lingua di partenza. Si cambia a schermo, con un tocco, e il
    # dispositivo torna a questa quando la bottiglia viene tolta: il tavolo
    # dopo trova il dispositivo come lo trova sempre.
    lingua: str = "it"
    # Il volume di partenza, che il file in `var` sovrascrive se c'e'. 100 e'
    # il fondo scala del PCM: sopra non si puo' andare, vedi speech.guadagno_di.
    volume: int = VOLUME_PREDEFINITO


class Amelie:
    def __init__(self, cfg: Configurazione) -> None:
        self.cfg = cfg
        self.macchina = Macchina(su_transizione=self._su_transizione)
        self.ponte: Ponte = PonteSimulato() if cfg.simula_mcu else Ponte()
        self.presenza = Presenza()
        self.camera = None if cfg.senza_camera else Camera()
        self.lettore = None if cfg.senza_camera else Lettore()
        self.matcher = Matcher()
        self.voce = None if cfg.senza_voce else Voce(
            ImpostazioniVoce(device_alsa=cfg.device_audio))
        self.narratore = Narratore(genera=self._genera if not cfg.senza_modello else None,
                                   lingua=cfg.lingua)
        self.lex = self.narratore.lex
        self.lingua = cfg.lingua

        self._ascoltatori: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lavoro: threading.Thread | None = None
        self._scadenza: float | None = None
        self._fatti: Fatti = Fatti()
        self._candidati: list[str] = []
        # Quante volte di fila l'OCR non ha letto nulla. Senza un tetto, un
        # oggetto illeggibile lasciato sul piatto fa lampeggiare l'anello e
        # girare l'OCR per tutta la sera, su una board senza ventola.
        self._tentativi = 0
        self._ferma_voce = threading.Event()
        # Il racconto in riproduzione, se ce n'e' uno. Lo tocca il thread di
        # lavoro che lo crea e lo toccano le richieste HTTP dei pulsanti: due
        # padroni, quindi un lucchetto.
        self._lettore: Riproduttore | None = None
        self._lucchetto_lettore = threading.Lock()
        # Gli annunci si fanno UNO ALLA VOLTA e per INTERO. Chi tocca mentre
        # uno sta parlando non lo interrompe: lascia detto quale lingua vuole
        # sentire dopo, e i tocchi che si accumulano nel frattempo si riducono
        # a quell'unica richiesta.
        self._lucchetto_annuncio = threading.Lock()
        self._lingua_da_annunciare: str | None = None
        self._annunciatore_vivo = False
        # Il colpetto di ritorno del volume, rimandato finche' la mano si ferma.
        self._lucchetto_volume = threading.Lock()
        self._rinvio_colpetto: threading.Timer | None = None
        # Vero quando il dispositivo ha finito di prepararsi. La schermata
        # d'avvio guarda questo per sapere quando lasciare il posto: prima le
        # voci non sono caricate, e la prima frase uscirebbe con quindici
        # secondi di ritardo proprio davanti al primo ospite.
        self._pronta = False
        # Una distanza finta, per il banco: vedi l'endpoint /prova. Quando c'e',
        # prende il posto del sensore e passa per l'isteresi vera.
        self._distanza_finta: int | None = None
        self.volume = self._volume_salvato(cfg.volume)
        if self.voce is not None:
            self.voce.volume = self.volume

    # --------------------------------------------------------- comunicazione

    def _pubblica(self, messaggio: dict[str, Any]) -> None:
        """Manda un messaggio a tutte le pagine aperte. Non blocca mai."""
        if self._loop is None:
            return
        dati = json.dumps(messaggio, ensure_ascii=False)
        for coda in list(self._ascoltatori):
            try:
                self._loop.call_soon_threadsafe(coda.put_nowait, dati)
            except (asyncio.QueueFull, RuntimeError):
                pass

    def _su_transizione(self, t) -> None:
        # Anche un rientro nello stesso stato ridisegna e rimette il tetto: e'
        # una transizione dichiarata, non un evento caduto nel vuoto.
        if t.cambia_stato or t.rientro:
            log.info("%s -> %s", t.da.value, t.a.value)
            self._scadenza = (time.monotonic() + t.durata_s) if t.durata_s else None
            # Il tavolo e' finito: si torna alla lingua di casa PRIMA di
            # ridisegnare, cosi' la schermata d'attesa esce gia' nella lingua
            # giusta invece di cambiare sotto gli occhi di chi arriva.
            if t.cambia_stato and t.a is Stato.ATTESA:
                self._torna_alla_lingua_di_casa()
            self._mostra(t.a)
        for e in t.effetti:
            self._esegui(e)

    def _torna_alla_lingua_di_casa(self) -> None:
        """Tolta la bottiglia, la lingua torna quella di partenza.

        Il tavolo dopo deve trovare il dispositivo come lo trova sempre: chi si
        siede non ha modo di sapere che l'inglese ce l'ha lasciato qualcun
        altro, ne' che la bandierina si tocca per cambiarlo.

        Senza voce e senza annuncio: qui non c'e' nessuno a cui dirlo, e un
        dispositivo che parla da solo a tavolo vuoto in un ristorante e' una
        cosa che non si puo' lasciare in sala.
        """
        if self.lingua == self.cfg.lingua:
            return
        log.info("tavolo finito, torno alla lingua di casa: %s -> %s",
                 self.lingua, self.cfg.lingua)
        self.lingua = self.cfg.lingua
        self.narratore.lingua = self.cfg.lingua
        if self.voce is not None:
            self.voce.per_lingua(self.cfg.lingua)
        self._manda_lingua()

    def _mostra(self, stato: Stato) -> None:
        """Che cosa vede l'ospite. Le frasi vengono dal lessico, non da qui.

        Cablarle nel codice significava avere lo schermo in italiano e il
        racconto in inglese, che e' il modo peggiore di essere bilingui.
        """
        def frase(chiave: str) -> str:
            return self.lex.frase("schermo", chiave, lingua=self.lingua)

        if stato is Stato.CONCLUSO and self._fatti.vuoto:  # si e' rinunciato
            # Ci si arriva dopo aver rinunciato a leggere l'etichetta: la vista
            # "racconto" mostrerebbe un titolo vuoto e nessun testo, cioe' uno
            # schermo nero con una bottiglia ancora appoggiata sopra.
            self._pubblica({"tipo": "stato", "vista": "avviso", "simbolo": "☐",
                            "tono": "neutro", "frase": frase("rinuncia"),
                            "voce_muta": not self._voce_disponibile()})
            return

        m: dict[str, Any] = {"tipo": "stato", "vista": VISTA[stato],
                             # Lo schermo e l'anello devono dire la stessa cosa:
                             # se il LED e' rosso, il simbolo a schermo non puo'
                             # essere dello stesso oro dell'invito.
                             "tono": TONO.get(stato, "invito"),
                             "voce_muta": not self._voce_disponibile()}
        if stato is Stato.RACCONTO:
            f = self._fatti
            m["titolo"] = f.nome or f.tipologia or f.denominazione or (
                f.vitigni[0] if f.vitigni else "")
            pezzi = [x for x in (f.cantina, str(f.annata) if f.annata else None) if x]
            m["sottotitolo"] = " · ".join(pezzi)
        elif stato is Stato.SCANSIONE:
            m["frase"] = frase("sto_leggendo")
        elif stato is Stato.RICONOSCIMENTO:
            m["frase"] = frase("un_attimo")
        elif stato is Stato.ASSESTAMENTO:
            m["frase"] = frase("fammi_guardare")
        elif stato is Stato.RIPOSIZIONA:
            m["simbolo"] = "↻"
            m["frase"] = frase("invito_a_girare")
        elif stato is Stato.GUASTO:
            m["simbolo"] = "⚠"
            m["frase"] = frase("guasto")
        self._pubblica(m)

    def _manda_lingua(self) -> None:
        """Le scritte fisse della pagina: quelle che nessun evento porta con se'."""
        self._pubblica({
            "tipo": "lingua",
            "lingua": self.lingua,
            "disponibili": list(self.lex.lingue),
            "invito": self.lex.frase("schermo", "appoggia_bottiglia",
                                     lingua=self.lingua),
            "domanda": self.lex.frase("schermo", "quale_di_questi",
                                      lingua=self.lingua),
            "voce_muta": not self._voce_disponibile(),
            "avviso_muto": self.lex.frase("schermo", "voce_assente",
                                          lingua=self.lingua),
        })

    # -------------------------------------------------------------- volume

    def _volume_salvato(self, ripiego: int) -> int:
        """Il volume dell'ultima volta, se c'e' ed e' un numero sensato.

        Non solleva mai: un file illeggibile deve costare il volume
        predefinito, non un dispositivo che non si accende.
        """
        try:
            valore = int(PERCORSO_VOLUME.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return max(0, min(100, int(ripiego)))
        return max(0, min(100, valore))

    def _salva_volume(self, valore: int) -> None:
        """Scrive il volume in modo che sopravviva alla spina staccata.

        Questo dispositivo non si spegne con un comando: si toglie corrente a
        fine servizio. Fra la `rename` e il disco possono passare secondi, e in
        quei secondi il valore appena regolato non esiste da nessuna parte -
        chi ha appena tarato il volume e ha spento lo ritroverebbe com'era. Da
        qui i due `fsync`: uno per il contenuto, uno per la cartella, che e'
        cio' che rende durevole il nome nuovo.
        """
        try:
            PERCORSO_VOLUME.parent.mkdir(parents=True, exist_ok=True)
            # Scrittura atomica: un file troncato da uno spegnimento tornerebbe
            # come volume illeggibile, e il dispositivo ripartirebbe al massimo.
            tmp = PERCORSO_VOLUME.with_suffix(".parziale")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{valore}\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(PERCORSO_VOLUME)
            cartella = os.open(PERCORSO_VOLUME.parent, os.O_RDONLY)
            try:
                os.fsync(cartella)
            finally:
                os.close(cartella)
        except OSError as e:
            log.warning("volume non salvato: %s", e)

    def imposta_volume(self, valore: int) -> int:
        """Il tocco sui due pulsanti del volume. Restituisce quello effettivo."""
        nuovo = max(0, min(100, int(valore)))
        if nuovo == self.volume:
            # Toccare oltre il fondo o oltre il massimo non cambia niente, ma il
            # colpetto si fa lo stesso: senza, il pulsante estremo sembrerebbe
            # rotto invece che arrivato in fondo.
            self._programma_colpetto()
            return self.volume
        self.volume = nuovo
        if self.voce is not None:
            self.voce.volume = nuovo
        self._salva_volume(nuovo)
        self._manda_volume()
        self._programma_colpetto()
        return nuovo

    def _manda_volume(self) -> None:
        self._pubblica({"tipo": "volume", "valore": self.volume,
                        "passo": PASSO_VOLUME,
                        # Senza voce del tutto il comando non si mostra: un
                        # livello che non muove niente e' peggio di nessun
                        # livello.
                        "attivo": self.voce is not None})

    def _programma_colpetto(self) -> None:
        """Fa sentire il livello, ma solo quando la mano si e' fermata."""
        with self._lucchetto_volume:
            if self._rinvio_colpetto is not None:
                self._rinvio_colpetto.cancel()
            t = threading.Timer(RIPOSO_VOLUME_S, self._colpetto)
            t.daemon = True
            self._rinvio_colpetto = t
            t.start()

    def _colpetto(self) -> None:
        """Il ritorno sonoro del volume, se non c'e' gia' qualcosa da sentire.

        Mentre il dispositivo racconta o annuncia una lingua il livello si sente
        gia' da solo, e un colpetto in mezzo a una frase sarebbe un disturbo.
        """
        if self.voce is None or self._annunciatore_vivo:
            return
        with self._lucchetto_lettore:
            occupato = self._lettore is not None
        if occupato:
            return
        self.voce.colpetto()

    def _voce_disponibile(self) -> bool:
        """C'e' una voce per la lingua a schermo?

        Non e' la stessa cosa che «l'audio funziona»: la voce puo' esserci e
        l'altoparlante no. Qui si risponde solo alla prima domanda, che e'
        quella che cambia col tocco dell'ospite.
        """
        return self.voce is None or getattr(
            self.voce, "disponibile_per_lingua", True)

    def cambia_lingua(self, codice: str) -> bool:
        """L'ospite ha toccato la bandierina.

        Il dispositivo RISPONDE A VOCE - «Lingua italiana», «English language» -
        e solo dopo, se un racconto era in corso, lo rifà nella lingua nuova.
        L'annuncio non è un vezzo: è la conferma che la lingua è cambiata *e*
        che l'audio funziona, ed è il modo più rapido di provare amplificatore
        e casse senza appoggiare una bottiglia.

        Il racconto riparte SUBITO nella lingua nuova, senza chiedere di
        rimettere la bottiglia: i fatti sono già in mano e si portano dietro
        tutte le lingue proprio per questo.
        """
        if codice not in self.lex.lingue:
            return False

        if codice == self.lingua:
            # Toccare la lingua già attiva non cambia niente, ma l'annuncio si
            # fa lo stesso: è l'unico modo di riprovare l'audio con un tocco
            # solo, invece di dover alternare avanti e indietro.
            self._parla_dopo(annuncia=True, riprendi=False)
            return False

        log.info("lingua: %s -> %s", self.lingua, codice)
        self.lingua = codice
        self.narratore.lingua = codice
        if self.voce is not None:
            self.voce.per_lingua(codice)
        self._manda_lingua()
        self._mostra(self.macchina.stato)

        riprendi = self.macchina.stato in (Stato.RACCONTO, Stato.CONCLUSO)
        if riprendi:
            self._ferma_racconto()
        self._parla_dopo(annuncia=True, riprendi=riprendi)
        return True

    def _parla_dopo(self, *, annuncia: bool, riprendi: bool) -> None:
        """Annuncia e semmai fa ripartire il racconto, fuori dal filo HTTP.

        Sono cose lente - una sintesi, l'attesa di un thread - e chi ha toccato
        lo schermo non deve aspettarle: il tocco deve rispondere subito.
        """
        if annuncia:
            self._chiedi_annuncio(self.lingua)
        if riprendi:
            threading.Thread(target=self._riprendi_racconto, daemon=True).start()

    def _chiedi_annuncio(self, lingua: str) -> None:
        """Chiede di annunciare una lingua. Uno alla volta, per intero.

        Il primo tocco parla SUBITO. Chi tocca mentre quello parla non lo
        interrompe: lascia detto cosa vuole sentire dopo, e se arrivano dieci
        tocchi resta solo l'ultimo.

        Interrompere era la scelta di prima, ed era sbagliata: le frasi durano
        un secondo abbondante, e provando l'audio si tocca ogni mezzo secondo.
        Ogni annuncio tagliava il precedente prima che uscisse dalle casse, e
        non si sentiva NIENTE - sembrava un guasto dell'amplificatore.
        """
        with self._lucchetto_annuncio:
            self._lingua_da_annunciare = lingua
            if self._annunciatore_vivo:
                return
            self._annunciatore_vivo = True
        threading.Thread(target=self._ciclo_annunci, daemon=True).start()

    def _ciclo_annunci(self) -> None:
        while True:
            with self._lucchetto_annuncio:
                lingua = self._lingua_da_annunciare
                self._lingua_da_annunciare = None
                if lingua is None:
                    self._annunciatore_vivo = False
                    return
            self._annuncia_lingua(lingua)

    def _riprendi_racconto(self) -> None:
        # Il thread del racconto vecchio deve essere USCITO prima di chiedere
        # quello nuovo: `_avvia` rifiuta il lavoro se ne trova uno vivo, e
        # rifiutandolo mandava un ERRORE che in RACCONTO non ha transizione.
        # Cadeva nel vuoto: la lingua cambiava a schermo e la storia non
        # ripartiva mai, senza che niente lo dicesse.
        self._attendi_lavoro(5.0)
        self.macchina.invia(Evento.RIPETI)

    def _prepara(self) -> None:
        """Scalda le voci, e in ogni caso dichiara finita la preparazione.

        La rete di sicurezza sotto la schermata d'avvio: se il caricamento va
        storto - un modello mancante, il disco pieno - il dispositivo deve
        arrivare comunque alla sua schermata e dire li' cosa non va, invece di
        restare sul marchio a tempo indeterminato senza spiegare niente.
        """
        try:
            self._scalda_voci()
        finally:
            self._pronta = True

    def _scalda_voci(self) -> None:
        """Carica le voci e pre-sintetizza le frasi che si dicono sempre.

        L'annuncio della lingua è una frase fissa, e sintetizzarla al momento
        costerebbe un secondo di silenzio proprio dopo il tocco: la si mette in
        cache all'avvio, dove il tempo non lo vede nessuno.
        """
        if self.voce is None:
            self._pronta = True
            return
        # Il flusso audio si apre ADESSO e non si chiude piu'. Il DSP di questa
        # board impiega circa due secondi a cominciare a rendere il suono dopo
        # l'apertura, e pagarli qui - all'accensione, mentre nessuno ascolta -
        # e' l'unico modo perche' ogni frase dopo esca all'istante.
        try:
            self.voce.uscita()
        except Exception as e:                              # noqa: BLE001
            log.warning("uscita audio non aperta: %s", e)
        self.voce.scalda()
        for lingua in self.lex.lingue:
            frase = self.lex.frase("voce", "conferma_lingua", lingua=lingua)
            if not frase or not self.voce.per_lingua(lingua):
                continue
            try:
                self.voce.sintetizza(frase)
            except Exception as e:                          # noqa: BLE001
                log.warning("frase fissa non pre-sintetizzata (%s): %s", lingua, e)
        self.voce.per_lingua(self.lingua)      # si torna alla lingua a schermo
        # Da adesso il dispositivo e' pronto davvero: le voci sono in memoria e
        # la prima frase esce subito. La schermata d'avvio aspetta questo, non
        # il server che risponde: fra le due cose ci sono trenta secondi di
        # caricamento, e sono esattamente quelli in cui il dispositivo sembra
        # pronto e non lo e'.
        self._pronta = True

    def _annuncia_lingua(self, lingua: str | None = None) -> None:
        lingua = lingua or self.lingua
        frase = self.lex.frase("voce", "conferma_lingua", lingua=lingua)
        if not frase or self.voce is None:
            return
        # La voce si allinea qui: fra il tocco e il turno di parola la lingua
        # puo' essere gia' cambiata di nuovo.
        if not self.voce.per_lingua(lingua):
            return
        log.info("annuncio [%s]: %r", lingua, frase)
        try:
            # Le frasi si dicono una per volta perche' la didascalia le segua:
            # una frase intera a schermo mentre se ne sente mezza non e'
            # sincronia, e' un sottotitolo scritto in anticipo.
            self.voce.parla(spezza_in_frasi(frase), su_frase=self._didascalia)
        except Exception as e:                              # noqa: BLE001
            log.warning("annuncio della lingua non riuscito: %s", e)
        finally:
            self._didascalia("")
            # Si torna alla lingua a schermo, che puo' essere un'altra.
            self.voce.per_lingua(self.lingua)

    def _didascalia(self, testo: str) -> None:
        """Che cosa il dispositivo sta dicendo, adesso."""
        self._pubblica({"tipo": "didascalia", "testo": testo})

    def _ferma_racconto(self) -> None:
        """Ferma la riproduzione in corso e chi la stava aspettando."""
        self._ferma_voce.set()
        with self._lucchetto_lettore:
            lettore, self._lettore = self._lettore, None
        if lettore is not None:
            lettore.ferma()
        if self.voce is not None:
            self.voce.zittisci()

    def _attendi_lavoro(self, secondi: float) -> None:
        """Aspetta che il thread di lavoro esca. Mai se stessi."""
        lavoro = self._lavoro
        if lavoro is not None and lavoro is not threading.current_thread():
            lavoro.join(timeout=secondi)
            if lavoro.is_alive():
                log.warning("il lavoro precedente non è uscito in %.0f s", secondi)

    # -------------------------------------------------------------- effetti

    def _colore_dello_stato(self) -> Colore | None:
        """Di che colore vuole l'anello lo stato in cui siamo ADESSO.

        Serve a rimettere l'anello dopo la raffica. Cablare AMBRA funzionava
        finche' SCANSIONE era l'unico stato da cui si scatta, ma era una
        coincidenza scritta in due posti: bastava cambiare ANELLO_LAVORO in
        state.py perche' la pipeline continuasse a rimettere l'ambra di prima.
        E se nel frattempo la bottiglia e' stata tolta - succede, la raffica
        dura mezzo secondo - lo stato non e' piu' quello di partenza.
        """
        for effetto in EFFETTI_INGRESSO.get(self.macchina.stato, ()):
            if effetto in COLORE_ANELLO:
                return COLORE_ANELLO[effetto]
        return None

    def _esegui(self, e: Effetto) -> None:
        try:
            if e in COLORE_ANELLO:
                self.ponte.anello(COLORE_ANELLO[e])
            elif e is Effetto.ILLUMINA_E_SCATTA:
                self._avvia(self._scatta_e_leggi)
            elif e is Effetto.INTERROGA_DATABASE:
                self._avvia(self._riconosci)
            elif e is Effetto.AVVIA_RACCONTO:
                self._avvia(self._racconta)
            elif e is Effetto.FERMA_RACCONTO:
                self._ferma_voce.set()
                with self._lucchetto_lettore:
                    lettore, self._lettore = self._lettore, None
                if lettore is not None:
                    lettore.ferma()
                if self.voce:
                    self.voce.zittisci()
            elif e is Effetto.MOSTRA_CANDIDATI:
                self._pubblica({"tipo": "candidati", "voci": self._candidati})
        except Exception as ex:                             # noqa: BLE001
            # Un effetto che fallisce non deve MAI fermare la macchina a stati:
            # un errore dell'MCU deve costare un anello spento, non il
            # dispositivo.
            log.warning("effetto %s fallito: %s", e.value, ex)

    def _avvia(self, funzione) -> None:
        """Esegue in un thread. Uno alla volta: la pipeline è sequenziale."""
        # Il passo successivo della pipeline viene avviato DAL thread di lavoro
        # stesso: _scatta_e_leggi manda LETTURA_RIUSCITA, che innesca
        # INTERROGA_DATABASE, che richiama _avvia mentre siamo ancora dentro
        # quel thread. Confrontare con `is_alive()` senza escludere il chiamante
        # significa trovarsi sempre occupati, e quindi non raccontare mai nulla.
        occupato = (self._lavoro is not None
                    and self._lavoro.is_alive()
                    and self._lavoro is not threading.current_thread())
        if occupato:
            # Ignorare e basta lascerebbe la macchina ad aspettare un evento che
            # nessuno mandera' mai. Meglio dichiarare il guasto, che scade da
            # solo e riporta in attesa.
            log.warning("lavoro già in corso, dichiaro guasto invece di %s",
                        funzione.__name__)
            self.macchina.invia(Evento.ERRORE)
            return
        self._lavoro = threading.Thread(target=self._protetto, args=(funzione,),
                                        daemon=True)
        self._lavoro.start()

    def _protetto(self, funzione) -> None:
        try:
            funzione()
        except Exception:                                   # noqa: BLE001
            log.exception("errore in %s", funzione.__name__)
            self.macchina.invia(Evento.ERRORE)

    # ------------------------------------------------------------- pipeline

    def _scatta_e_leggi(self) -> None:
        if self.camera is None or self.lettore is None:
            self.macchina.invia(Evento.LETTURA_FALLITA)
            return
        # La luce dello scatto è l'anello stesso, che sale a bianco e poi torna
        # al colore del lavoro. Prima era un secondo Modulino Pixels che faceva
        # da flash di taglio sull'etichetta; tolto quello, questa è la sola luce
        # che il dispositivo controlla.
        #
        # L'ambra si rimette SOLO se lo scatto è riuscito, e in un `else` invece
        # che in un `finally`. Col `finally` l'ordine era: errore -> la macchina
        # a stati entra in GUASTO e accende il ROSSO -> il finally lo cancella
        # rimettendo l'ambra. Restava uno schermo che dichiara un guasto sopra
        # un anello del colore dell'invito, che è esattamente la cosa che schermo
        # e anello non devono mai fare. In ogni via d'errore il colore lo decide
        # la macchina a stati, che è l'unica a sapere dove si sta andando.
        #
        # E si rimette SUBITO dopo la raffica, non alla fine del metodo: dopo
        # c'è l'OCR, che dura quattro secondi, e quattro secondi di bianco pieno
        # sotto una bottiglia non sono una luce, sono un lampeggiante.
        try:
            self.ponte.anello(BIANCO_SCATTO)
        except (PonteNonDisponibile, ErroreMCU):
            # Un anello che non si accende costa una foto piu' scura, non una
            # scansione fallita: e' la stessa regola con cui `_esegui` protegge
            # tutti gli effetti. Senza ErroreMCU, un firmware vecchio che non
            # conosce `set_anello` trasformava ogni scatto in un guasto.
            pass
        try:
            scatto = self.camera.scatta()
        except CameraNonDisponibile as e:
            log.error("camera: %s", e)
            self.macchina.invia(Evento.ERRORE)
            return
        else:
            colore = self._colore_dello_stato()
            if colore is not None:
                try:
                    self.ponte.anello(colore)
                except (PonteNonDisponibile, ErroreMCU):
                    pass

        try:
            lettura = self.lettore.leggi(scatto.immagine)
        except OCRNonDisponibile as e:
            log.error("OCR: %s", e)
            self.macchina.invia(Evento.ERRORE)
            return

        self._righe = [r.testo for r in lettura.righe]
        log.info("lette %d righe in %.1f s (nitidezza %.0f)",
                 len(self._righe), lettura.durata_s, scatto.nitidezza)
        if self._righe:
            self._tentativi = 0
            self.macchina.invia(Evento.LETTURA_RIUSCITA)
            return
        self._tentativi += 1
        self.macchina.invia(Evento.LETTURA_FALLITA)
        if self._tentativi >= TENTATIVI_MAX:
            # Si e' provato abbastanza: si mostra il messaggio e si tace, invece
            # di riaccendere la luce ogni quattro secondi finche' qualcuno non
            # toglie l'oggetto dal piatto.
            log.info("rinuncio dopo %d tentativi", self._tentativi)
            self.macchina.invia(Evento.RINUNCIA)

    def _riconosci(self) -> None:
        self._fatti = self.matcher.cerca(getattr(self, "_righe", []))
        self._candidati = self._fatti.candidati
        log.info("livello %s, sicurezza %.0f", self._fatti.livello.value,
                 self._fatti.sicurezza)
        if self._fatti.certo:
            self.macchina.invia(Evento.MATCH_SICURO)
        elif self._fatti.dubbio and self._candidati:
            self.macchina.invia(Evento.MATCH_DUBBIO)
        elif self._fatti.vuoto:
            self.macchina.invia(Evento.LETTURA_FALLITA)
        else:
            self.macchina.invia(Evento.MATCH_ASSENTE)

    def _racconta(self) -> None:
        self._ferma_voce.clear()
        racconto = self.narratore.racconta(self._fatti)
        log.info("racconto da %s (%d parole)", racconto.origine,
                 len(racconto.testo.split()))
        frasi = racconto.frasi

        # Il testo arriva TUTTO INSIEME, e la frase in ascolto si illumina.
        # Prima compariva un pezzo alla volta, al ritmo stimato della lettura:
        # una finzione che regge finche' si va dritti, ma con un pulsante di
        # pausa e uno di riavvolgimento si sfalda al primo tocco. E con un
        # player davanti, chi guarda vuole vedere quanto manca.
        self._pubblica({"tipo": "racconto", "frasi": frasi,
                        "origine": racconto.origine})

        if self.voce is None or not self.voce.disponibile_per_lingua:
            # Nessuna voce per questa lingua: il racconto si legge soltanto, e
            # allora e' giusto che scorra da solo al ritmo di una lettura.
            self._scorri_senza_voce(frasi)
            return

        try:
            lettore = Riproduttore(
                self.voce, frasi,
                su_avanzamento=lambda i: self._pubblica({"tipo": "riproduzione", **i}),
                passo_s=SALTO_S)
        except Exception as e:                              # noqa: BLE001
            log.warning("riproduttore non avviabile: %s", e)
            self._scorri_senza_voce(frasi)
            return

        with self._lucchetto_lettore:
            self._lettore = lettore
        lettore.avvia()
        finito = lettore.attendi(timeout=TETTO_RACCONTO_S)
        with self._lucchetto_lettore:
            if self._lettore is lettore:
                self._lettore = None
        lettore.ferma()

        if finito and not self._ferma_voce.is_set():
            self.macchina.invia(Evento.RACCONTO_FINITO)

    def _scorri_senza_voce(self, frasi: list[str]) -> None:
        """Il ripiego quando non c'e' voce: il testo si illumina da solo.

        Il ritmo e' quello di una lettura ad alta voce, circa quindici caratteri
        al secondo. E' una stima, ma qui non c'e' nessun audio con cui possa
        andare fuori sincrono.
        """
        for i, frase in enumerate(frasi):
            if self._ferma_voce.is_set():
                return
            self._pubblica({"tipo": "riproduzione", "frase": i,
                            "posizione": 0.0, "durata": 0.0,
                            "in_pausa": False, "completo": False,
                            "senza_voce": True})
            time.sleep(min(6.0, max(1.0, len(frase) / 15)))
        if not self._ferma_voce.is_set():
            self.macchina.invia(Evento.RACCONTO_FINITO)

    # ------------------------------------------------------------- comandi

    def comanda_racconto(self, azione: str) -> dict:
        """I pulsanti sotto il racconto. Nient'altro sullo schermo reagisce.

        Se non c'e' niente in riproduzione si risponde e basta: un tocco che
        arriva mentre il racconto sta finendo non deve sollevare nulla.
        """
        with self._lucchetto_lettore:
            lettore = self._lettore
        if lettore is None:
            return {"ok": False}
        if azione == "alterna":
            lettore.alterna()
        elif azione == "pausa":
            lettore.pausa()
        elif azione == "riprendi":
            lettore.riprendi()
        elif azione == "avanti":
            lettore.salta(SALTO_S)
        elif azione == "indietro":
            lettore.salta(-SALTO_S)
        elif azione == "ricomincia":
            lettore.ricomincia()
        else:
            return {"ok": False, "motivo": "azione sconosciuta"}
        return {"ok": True, **lettore.istantanea()}

    def scegli(self, indice: int) -> None:
        """L'ospite ha toccato uno dei candidati.

        Si compone il record TOCCATO. Rifare la ricerca sul suo nome sarebbe
        un secondo tiro di dadi: la stringa normalizzata di un candidato puo'
        somigliare piu' a un altro record che a se stessa, e l'ospite si
        vedrebbe raccontare un vino diverso da quello che ha scelto.
        """
        rif = self._fatti.riferimenti
        if 0 <= indice < len(rif):
            annata = self._fatti.annata
            self._fatti = self.matcher.fatti_di(*rif[indice])
            self._fatti.annata = annata     # l'annata viene dall'etichetta
        self.macchina.invia(Evento.CANDIDATO_SCELTO)

    def _genera(self, prompt: str) -> str:
        from .llm import Modello
        if not hasattr(self, "_modello"):
            self._modello = Modello()
        return self._modello.genera(prompt)

    # ------------------------------------------------------------ ciclo

    async def sorveglia(self) -> None:
        """Legge il sensore e fa scadere i timer. È il battito del dispositivo."""
        if self.camera is not None:
            try:
                blocca_esposizione(self.camera.imp, self.camera.percorso)
            except Exception as e:                          # noqa: BLE001
                log.warning("esposizione non bloccata: %s", e)

        while True:
            try:
                await self._un_battito()
            except Exception:                               # noqa: BLE001
                # Il battito del dispositivo non puo' morire per nessun motivo:
                # se muore, nessuna bottiglia viene piu' vista, per sempre.
                log.exception("errore nel ciclo di sorveglianza")
            await asyncio.sleep(self.cfg.periodo_sensore_s)

    async def _un_battito(self) -> None:
        """Un giro solo: sensore, presenza, timer. Isolato per poterlo provare."""
        if self._distanza_finta is not None:
            mm = self._distanza_finta
        else:
            try:
                mm = self.ponte.distanza_mm()
            except Exception:                           # noqa: BLE001
                mm = None
        c_era = self.presenza.presente
        ora = self.presenza.aggiorna(mm)
        if ora != c_era:
            if ora:
                self._tentativi = 0     # bottiglia nuova, si riparte da capo
            self.macchina.invia(
                Evento.BOTTIGLIA_PRESENTE if ora else Evento.BOTTIGLIA_ASSENTE)
        elif ora and self.macchina.stato is Stato.ATTESA and self._tentativi < TENTATIVI_MAX:
            # La bottiglia c'e' ma siamo tornati in attesa: succede dopo un
            # guasto. Il fronte di salita non si ripresenta mai piu', e senza
            # questo rilancio il dispositivo resterebbe fermo per sempre con una
            # bottiglia davanti. Il contatore NON si azzera qui: se il guasto si
            # ripete, dopo TENTATIVI_MAX si smette, invece di riaccendere
            # l'anello ogni quattro secondi tutta la sera su una board senza
            # ventola. Si riparte solo togliendo e rimettendo la bottiglia.
            self._tentativi += 1
            log.info("bottiglia ancora presente in attesa, rilancio (%d/%d)",
                     self._tentativi, TENTATIVI_MAX)
            self.macchina.invia(Evento.BOTTIGLIA_PRESENTE)

        if self._scadenza and time.monotonic() >= self._scadenza:
            self._scadenza = None
            self.macchina.invia(Evento.SCADENZA)

    async def salute(self) -> None:
        while True:
            self._pubblica({"tipo": "salute", "tutto_bene": self._tutto_bene(),
                            "voce_muta": not self._voce_disponibile()})
            await asyncio.sleep(20)

    def _tutto_bene(self) -> bool:
        return self.ponte.disponibile


# --------------------------------------------------------------- server

def crea_app(amelie: Amelie):
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

    @asynccontextmanager
    async def ciclo_di_vita(app):
        amelie._loop = asyncio.get_running_loop()
        compiti = [asyncio.create_task(amelie.sorveglia()),
                   asyncio.create_task(amelie.salute())]
        # Le voci si caricano ADESSO, in un thread a parte: quindici secondi
        # l'una mentre nessuno guarda non li vede nessuno, gli stessi quindici
        # secondi dopo che un ospite ha toccato la bandierina sono un guasto.
        if amelie.voce is not None:
            threading.Thread(target=amelie._prepara, daemon=True).start()
        else:
            amelie._pronta = True
        amelie._mostra(amelie.macchina.stato)
        amelie._manda_lingua()
        amelie._manda_volume()
        try:
            yield
        finally:
            # Si sveglia ogni pagina aperta con un segnale di fine. Senza,
            # il flusso di eventi resta appeso su una coda che nessuno
            # riempira' piu': uvicorn aspetta educatamente che la connessione
            # si chiuda, il chiosco non la chiude mai, e lo spegnimento del
            # servizio finisce a colpi di SIGKILL dopo un minuto e mezzo.
            for coda in list(amelie._ascoltatori):
                try:
                    coda.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            for c in compiti:
                c.cancel()

    # docs_url e redoc_url spenti: il dispositivo espone solo cio' che serve.
    app = FastAPI(title="Amelie", docs_url=None, redoc_url=None,
                  lifespan=ciclo_di_vita)

    @app.get("/")
    async def pagina():
        # Mai in cache. Il chiosco apre questa pagina una volta sola, all'avvio,
        # e ci resta per giorni: se Chromium se la tiene, aggiornare
        # l'interfaccia non basta piu' a cambiarla e bisogna ricordarsi di
        # riavviare anche il chiosco. E' successo, e si e' visto come una
        # schermata vecchia che non cambiava per nessun motivo.
        return FileResponse(
            STATICI / "index.html",
            headers={"Cache-Control": "no-store, must-revalidate",
                     "Pragma": "no-cache", "Expires": "0"})

    @app.get("/eventi")
    async def eventi():
        coda: asyncio.Queue = asyncio.Queue(maxsize=100)
        amelie._ascoltatori.add(coda)

        async def flusso():
            try:
                # Appena la pagina si apre le si dice dove siamo: se il browser
                # si e' riavviato a meta' racconto, deve ritrovare la scena.
                amelie._mostra(amelie.macchina.stato)
                amelie._manda_lingua()
                amelie._manda_volume()
                while True:
                    dati = await coda.get()
                    if dati is None:        # il servizio sta chiudendo
                        return
                    yield f"data: {dati}\n\n"
            finally:
                amelie._ascoltatori.discard(coda)

        return StreamingResponse(flusso(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/scegli/{indice}")
    async def scegli(indice: int):
        amelie.scegli(indice)
        return JSONResponse({"ok": True})

    @app.post("/racconto/{azione}")
    async def racconto(azione: str):
        return JSONResponse(amelie.comanda_racconto(azione))

    @app.post("/lingua/{codice}")
    async def lingua(codice: str):
        cambiata = amelie.cambia_lingua(codice)
        return JSONResponse({"ok": cambiata, "lingua": amelie.lingua})

    @app.post("/volume/{valore}")
    async def volume(valore: int):
        return JSONResponse({"ok": True, "valore": amelie.imposta_volume(valore),
                             "passo": PASSO_VOLUME})

    @app.post("/prova/{cosa}")
    async def prova(cosa: str):
        """Il banco: fa credere al dispositivo che ci sia una bottiglia.

        Serve a provare tutto il resto — camera, lettura, riconoscimento,
        racconto, voce, schermo, comandi — quando il sensore di distanza non c'è
        o non risponde. È l'unico pezzo del giro che non si può provare senza
        hardware, e senza questo bloccherebbe tutti gli altri.

        Non manda l'evento a mano: mette una **distanza finta** al posto di
        quella del sensore, e lascia che sia il battito normale a passarla per
        l'isteresi. Così si prova il percorso vero, filtro compreso, non una
        scorciatoia che gli somiglia — e togliendola il dispositivo se ne
        accorge da solo, come farebbe con una bottiglia tolta dal piatto.
        """
        if cosa == "bottiglia":
            amelie._distanza_finta = 20      # sotto la soglia dei 40 mm
        elif cosa == "via":
            amelie._distanza_finta = None    # torna a leggere il sensore vero
        else:
            return JSONResponse({"ok": False,
                                 "motivo": "prova: 'bottiglia' oppure 'via'"})
        return JSONResponse({"ok": True, "finta": amelie._distanza_finta,
                             "stato": amelie.macchina.stato.value})

    @app.get("/pronto")
    async def pronto():
        # La schermata d'avvio e' un file, quindi la sua origine e' `null`: senza
        # questa intestazione il browser le impedisce di LEGGERE la risposta, e
        # resterebbe accesa per sempre davanti a un dispositivo gia' pronto.
        # Si apre solo questo, che dice una parola sola e non tocca niente.
        return JSONResponse({"pronta": amelie._pronta},
                            headers={"Access-Control-Allow-Origin": "*"})

    @app.get("/lingue")
    async def lingue():
        return JSONResponse({"lingua": amelie.lingua,
                             "disponibili": list(amelie.lex.lingue)})

    @app.get("/stato")
    async def stato():
        return JSONResponse({
            "stato": amelie.macchina.stato.value,
            "mcu": amelie.ponte.disponibile,
            # Che protocollo parla il firmware, e cosa vede. Serve montando: lo
            # stato tecnico si apre dal vetro tenendo premuto l'angolo, senza
            # tastiera, ed è l'unico modo di vedere da lì se sull'MCU c'è ancora
            # il firmware di prima — quello in cui i bit dei moduli
            # significavano un'altra cosa. Una chiamata sola per tutti e due:
            # questa pagina si guarda quando qualcosa non risponde.
            **amelie.ponte.diagnosi(),
            "camera": amelie.camera is not None,
            "voce": bool(amelie.voce and amelie.voce.disponibile),
            "volume": amelie.volume,
            "pronta": amelie._pronta,
            "ultimo_livello": amelie._fatti.livello.value,
            "sicurezza": amelie._fatti.sicurezza,
            "transizioni": [f"{t.da.value}->{t.a.value}"
                            for t in amelie.macchina.storia[-12:]],
        })

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Amelie 2.0")
    ap.add_argument("--simula-mcu", action="store_true")
    ap.add_argument("--senza-camera", action="store_true")
    ap.add_argument("--senza-voce", action="store_true")
    ap.add_argument("--con-modello", action="store_true",
                    help="genera dal vivo per cio' che non e' in cache "
                         "(lento e di qualita' incerta: vedi docs/04-QUALITA.md)")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--audio", default="plughw:0,3")
    ap.add_argument("--volume", type=int, default=VOLUME_PREDEFINITO,
                    help="volume iniziale 0-100, se non ce n'e' gia' uno salvato")
    ap.add_argument("-v", "--verboso", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    cfg = Configurazione(
        simula_mcu=args.simula_mcu, senza_camera=args.senza_camera,
        senza_voce=args.senza_voce, senza_modello=not args.con_modello,
        device_audio=args.audio, porta=args.porta, volume=args.volume)

    import uvicorn
    # Il tetto sullo spegnimento e' una rete di sicurezza, non la soluzione:
    # quella e' svegliare i flussi di eventi (vedi ciclo_di_vita). Ma se un
    # domani qualcosa restasse appeso, meglio cinque secondi che il minuto e
    # mezzo che systemd concede prima di uccidere.
    uvicorn.run(crea_app(Amelie(cfg)), host="127.0.0.1", port=args.porta,
                log_level="warning", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
