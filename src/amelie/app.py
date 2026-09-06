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
from .speech import ImpostazioniVoce, Voce, VoceNonDisponibile
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
    senza_modello: bool = False
    device_audio: str = "hw:0,3"
    porta: int = 8080
    periodo_sensore_s: float = 0.15


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
        self.narratore = Narratore(genera=self._genera if not cfg.senza_modello else None)

        self._ascoltatori: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lavoro: threading.Thread | None = None
        self._scadenza: float | None = None
        self._fatti: Fatti = Fatti()
        self._candidati: list[str] = []
        self._ferma_voce = threading.Event()

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
        m: dict[str, Any] = {"tipo": "stato", "vista": VISTA[stato]}
        if stato is Stato.RACCONTO:
            f = self._fatti
            m["titolo"] = f.nome or f.tipologia or f.denominazione or (
                f.vitigni[0] if f.vitigni else "")
            pezzi = [x for x in (f.cantina, str(f.annata) if f.annata else None) if x]
            m["sottotitolo"] = " · ".join(pezzi)
        elif stato is Stato.SCANSIONE:
            m["frase"] = "Sto leggendo l'etichetta…"
        elif stato is Stato.RICONOSCIMENTO:
            m["frase"] = "Un attimo…"
        elif stato is Stato.ASSESTAMENTO:
            m["frase"] = "Fammi guardare…"
        elif stato is Stato.RIPOSIZIONA:
            m["simbolo"] = "↻"
            m["frase"] = "Non riesco a leggere l'etichetta. Provi a girarla verso di me?"
        elif stato is Stato.GUASTO:
            m["simbolo"] = "⚠"
            m["frase"] = "Qualcosa non ha funzionato. Riprovo fra un istante."
        self._pubblica(m)

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
                if self.voce:
                    self.voce.zittisci()
            elif e is Effetto.MOSTRA_CANDIDATI:
                self._pubblica({"tipo": "candidati", "voci": self._candidati})
        except PonteNonDisponibile as ex:
            log.warning("MCU non raggiungibile: %s", ex)

    def _avvia(self, funzione) -> None:
        """Esegue in un thread. Uno alla volta: la pipeline è sequenziale."""
        if self._lavoro and self._lavoro.is_alive():
            log.warning("lavoro già in corso, ignoro %s", funzione.__name__)
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
        self.macchina.invia(
            Evento.LETTURA_RIUSCITA if self._righe else Evento.LETTURA_FALLITA)

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

        # Il testo compare a schermo frase per frase, al ritmo della voce: se
        # arrivasse tutto insieme mentre la voce comincia, si leggerebbe la fine
        # mentre si ascolta l'inizio.
        frasi = racconto.frasi

        def dillo() -> None:
            if self.voce is None:
                return
            try:
                self.voce.parla(f for f in frasi if not self._ferma_voce.is_set())
            except VoceNonDisponibile as e:
                log.warning("voce non disponibile: %s", e)

        parlante = threading.Thread(target=dillo, daemon=True)
        parlante.start()

        for i, frase in enumerate(frasi):
            if self._ferma_voce.is_set():
                break
            self._pubblica({"tipo": "testo", "pezzo": frase + " ",
                            "finito": i == len(frasi) - 1})
            # Il ritmo segue la lettura: circa quindici caratteri al secondo,
            # che e' la velocita' con cui una voce italiana pronuncia.
            time.sleep(min(6.0, max(1.0, len(frase) / 15)))

        parlante.join(timeout=90)
        if not self._ferma_voce.is_set():
            self.macchina.invia(Evento.RACCONTO_FINITO)

    def scegli(self, indice: int) -> None:
        """L'ospite ha toccato uno dei candidati."""
        if 0 <= indice < len(self._candidati):
            self._righe = [self._candidati[indice]]
            self._fatti = self.matcher.cerca(self._righe)
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
                mm = self.ponte.distanza_mm()
            except PonteNonDisponibile:
                mm = None
            c_era = self.presenza.presente
            ora = self.presenza.aggiorna(mm)
            if ora != c_era:
                self.macchina.invia(
                    Evento.BOTTIGLIA_PRESENTE if ora else Evento.BOTTIGLIA_ASSENTE)

            if self._scadenza and time.monotonic() >= self._scadenza:
                self._scadenza = None
                self.macchina.invia(Evento.SCADENZA)

            await asyncio.sleep(self.cfg.periodo_sensore_s)

    async def salute(self) -> None:
        while True:
            self._pubblica({"tipo": "salute", "tutto_bene": self._tutto_bene()})
            await asyncio.sleep(20)

    def _tutto_bene(self) -> bool:
        return self.ponte.disponibile and (self.camera is None or True)


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
        amelie._mostra(amelie.macchina.stato)
        try:
            yield
        finally:
            for c in compiti:
                c.cancel()

    # docs_url e redoc_url spenti: il dispositivo espone solo cio' che serve.
    app = FastAPI(title="Amelie", docs_url=None, redoc_url=None,
                  lifespan=ciclo_di_vita)

    @app.get("/")
    async def pagina():
        return FileResponse(STATICI / "index.html")

    @app.get("/eventi")
    async def eventi():
        coda: asyncio.Queue = asyncio.Queue(maxsize=100)
        amelie._ascoltatori.add(coda)

        async def flusso():
            try:
                # Appena la pagina si apre le si dice dove siamo: se il browser
                # si e' riavviato a meta' racconto, deve ritrovare la scena.
                amelie._mostra(amelie.macchina.stato)
                while True:
                    dati = await coda.get()
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
    ap.add_argument("--senza-modello", action="store_true")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--audio", default="hw:0,3")
    ap.add_argument("-v", "--verboso", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    cfg = Configurazione(
        simula_mcu=args.simula_mcu, senza_camera=args.senza_camera,
        senza_voce=args.senza_voce, senza_modello=args.senza_modello,
        device_audio=args.audio, porta=args.porta)

    import uvicorn
    uvicorn.run(crea_app(Amelie(cfg)), host="127.0.0.1", port=args.porta,
                log_level="warning")


if __name__ == "__main__":
    main()
