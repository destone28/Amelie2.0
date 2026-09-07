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
    scatto          0,3 s   flash, scarto dei fotogrammi vecchi, raffica
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
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bridge import (
    AMBRA, BIANCO_FLASH, ROSSO, SPENTO, VERDE,
    Ponte, PonteNonDisponibile, PonteSimulato, Presenza,
)
from .capture import Camera, CameraNonDisponibile, blocca_esposizione
from .matcher import Fatti, Livello, Matcher
from .narrator import Narratore
from .ocr import Lettore, OCRNonDisponibile
from .speech import ImpostazioniVoce, Riproduttore, Voce, VoceNonDisponibile
from .state import DURATE_S, Effetto, Evento, Macchina, Stato

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
        # oggetto illeggibile lasciato sul piatto fa lampeggiare il flash e
        # girare l'OCR per tutta la sera, su una board senza ventola.
        self._tentativi = 0
        self._ferma_voce = threading.Event()
        # Il racconto in riproduzione, se ce n'e' uno. Lo tocca il thread di
        # lavoro che lo crea e lo toccano le richieste HTTP dei pulsanti: due
        # padroni, quindi un lucchetto.
        self._lettore: Riproduttore | None = None
        self._lucchetto_lettore = threading.Lock()

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
        if t.cambia_stato:
            log.info("%s -> %s", t.da.value, t.a.value)
            self._scadenza = (time.monotonic() + t.durata_s) if t.durata_s else None
            self._mostra(t.a)
        for e in t.effetti:
            self._esegui(e)

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

        Se un racconto e' a schermo si rifa' SUBITO nella lingua nuova, senza
        chiedere di rimettere la bottiglia: i fatti sono gia' in mano e si
        portano dietro tutte le lingue proprio per questo.
        """
        if codice not in self.lex.lingue or codice == self.lingua:
            return False
        log.info("lingua: %s -> %s", self.lingua, codice)
        self.lingua = codice
        self.narratore.lingua = codice
        if self.voce is not None:
            self.voce.per_lingua(codice)
        self._manda_lingua()
        self._mostra(self.macchina.stato)
        if self.macchina.stato in (Stato.RACCONTO, Stato.CONCLUSO):
            self._ferma_voce.set()
            if self.voce:
                self.voce.zittisci()
            self.macchina.invia(Evento.RIPETI)
        return True

    # -------------------------------------------------------------- effetti

    def _esegui(self, e: Effetto) -> None:
        try:
            if e in COLORE_ANELLO:
                self.ponte.anello(COLORE_ANELLO[e])
            elif e is Effetto.FLASH_E_SCATTA:
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
        try:
            self.ponte.flash(BIANCO_FLASH)
        except PonteNonDisponibile:
            pass
        try:
            scatto = self.camera.scatta()
        except CameraNonDisponibile as e:
            log.error("camera: %s", e)
            self.macchina.invia(Evento.ERRORE)
            return
        finally:
            try:
                self.ponte.flash(SPENTO)
            except PonteNonDisponibile:
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
            # di riaccendere il flash ogni quattro secondi finche' qualcuno non
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
        try:
            mm = self.ponte.distanza_mm()
        except Exception:                               # noqa: BLE001
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
            # ripete, dopo TENTATIVI_MAX si smette, invece di riaccendere il
            # flash ogni quattro secondi tutta la sera su una board senza
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
            threading.Thread(target=amelie.voce.scalda, daemon=True).start()
        amelie._mostra(amelie.macchina.stato)
        amelie._manda_lingua()
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

    @app.get("/lingue")
    async def lingue():
        return JSONResponse({"lingua": amelie.lingua,
                             "disponibili": list(amelie.lex.lingue)})

    @app.get("/stato")
    async def stato():
        return JSONResponse({
            "stato": amelie.macchina.stato.value,
            "mcu": amelie.ponte.disponibile,
            "camera": amelie.camera is not None,
            "voce": bool(amelie.voce and amelie.voce.disponibile),
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
    ap.add_argument("-v", "--verboso", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    cfg = Configurazione(
        simula_mcu=args.simula_mcu, senza_camera=args.senza_camera,
        senza_voce=args.senza_voce, senza_modello=not args.con_modello,
        device_audio=args.audio, porta=args.porta)

    import uvicorn
    # Il tetto sullo spegnimento e' una rete di sicurezza, non la soluzione:
    # quella e' svegliare i flussi di eventi (vedi ciclo_di_vita). Ma se un
    # domani qualcosa restasse appeso, meglio cinque secondi che il minuto e
    # mezzo che systemd concede prima di uccidere.
    uvicorn.run(crea_app(Amelie(cfg)), host="127.0.0.1", port=args.porta,
                log_level="warning", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
