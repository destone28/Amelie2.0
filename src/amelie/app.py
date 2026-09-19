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

    innesco         0,15 s  il sensore di distanza, tre letture d'accordo
    scatto          ~0 s    il fotogramma si prende dal flusso gia' in moto
    OCR             0,5-1,5 s  il vero costo
    riconoscimento  ~0,05 s SQLite
    racconto        ~0 s    composto dai fatti; decine di secondi dal modello

I numeri sono misurati sul dispositivo, e sono cambiati: lo scatto costava
0,7 s e l'OCR 3,8, e il racconto veniva da un testo pre-generato perche' il
modello era l'unica alternativa. Oggi il racconto si compone dai fatti.
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

from .batteria import Batteria
from .bridge import (
    AMBRA, BIANCO_SCATTO, ROSSO, SPENTO, VERDE,
    Colore, ErroreMCU, Ponte, PonteNonDisponibile, PonteSimulato,
    Presenza as PresenzaDistanza,
)
from .capture import (
    Camera, CameraNonDisponibile, PresenzaOttica, blocca_esposizione,
)
from .carta import Carta, CartaVuota
from .giornale import Giornale
from .mirino import LetturaContinua, Mirino
from .matcher import Fatti, Livello, Matcher
from .narrator import Narratore, _che_tipo_di_vino, spezza_in_frasi
from .ocr import Lettore, OCRNonDisponibile
from .speech import (
    VOCI, VOLUME_PREDEFINITO, ImpostazioniVoce, Riproduttore, Voce,
    VoceNonDisponibile, caratteri_al_secondo, per_la_voce,
)
from .state import (
    DURATE_S, EFFETTI_INGRESSO, TRANSIZIONI, Effetto, Evento, Macchina, Stato,
)

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
# Le «descrizioni generate»: acceso, il modello scrive il racconto per QUESTA
# bottiglia; spento, il racconto si compone dai fatti. Sta accanto al volume e
# si ricorda allo stesso modo, perche' e' la stessa cosa - una scelta di chi
# apre il locale, non un parametro di collaudo.
PERCORSO_GENERATI = RADICE / "var" / "racconti_generati"
# Come il dispositivo racconta. Tre modi, e la differenza fra loro non e' di
# stile: e' DA DOVE VIENE quello che dice.
#
#   archivio    il racconto composto dai dati del registro UE e dal
#               disciplinare, senza modello. Istantaneo, e vero per
#               costruzione: e' il modo predefinito.
#   generativa  gli stessi dati, ma il testo lo scrive il modello sul momento
#               per QUELLA bottiglia. Costa l'attesa della generazione, e passa
#               dalla stessa verifica di sempre.
#   carta       una carta dei vini scritta a mano, in un file. Solo i vini che
#               ci sono dentro, e per quelli il testo e' quello che ha scritto
#               una persona. Vedi `amelie.carta`.
MODI = ("archivio", "generativa", "carta")
PERCORSO_MODO = RADICE / "var" / "modo"
# Il servizio di sistema che tiene su il modello linguistico. Lo accende e lo
# spegne il modo di racconto: vedi `Amelie._accendi_il_modello`.
SERVIZIO_MODELLO = "amelie-llm.service"
PERCORSO_BATTERIA = RADICE / "var" / "batteria.json"
# Dove finiscono le bottiglie che il dispositivo non ha saputo riconoscere,
# quando qualcuno lo segnala toccando lo schermo. Vedi `segnala()`.
CARTELLA_SEGNALAZIONI = RADICE / "var" / "segnalazioni"
# Il piatto vuoto, com'e' quando non c'e' niente sopra. E' una proprieta'
# dell'installazione, non del processo: senza ricordarlo, un dispositivo acceso
# con la bottiglia gia' posata imparerebbe quella come sfondo e resterebbe
# fermo a guardarla. Vedi `PresenzaOttica.ricorda`.
PERCORSO_SFONDO = RADICE / "var" / "sfondo.npy"
# Il giornale di bordo: una riga per scansione e il fotogramma che l'ha
# prodotta. Vedi `amelie.giornale`.
CARTELLA_GIORNALE = RADICE / "var" / "scansioni"
# Ogni quanto si puo' riscrivere lo sfondo, e di quanto deve essere cambiato
# perche' valga la pena. La memoria della board e' flash: un aggiornamento al
# minuto sarebbero settanta megabyte al giorno per un file che quasi non cambia.
RIPOSO_SFONDO_S = 600.0
SFONDO_DA_RISCRIVERE = 0.20
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
    # Il racconto composto dai fatti e' la scelta predefinita, ed e' vero per
    # costruzione. Con --con-modello il modo «generativa» diventa scegliibile
    # dalle impostazioni: il modello scrive per primo, verificato, e ripiega
    # sul testo pronto per quel record e poi sulla composizione.
    senza_modello: bool = True
    # Il modello caricato e' quello affinato su questo progetto? Cambia la
    # FORMA del prompt, non solo il contenuto: il modello addestrato vuole i
    # fatti compatti e una riga di istruzione, quello generico le istruzioni
    # per esteso. Darne una per l'altra costa il doppio del tempo e la
    # qualita' che l'addestramento aveva comprato.
    modello_addestrato: bool = False
    device_audio: str = "plughw:0,3"
    porta: int = 8080
    # Il battito. Era 0,15 s, ed e' sceso perche' adesso e' lui a vedere
    # arrivare la bottiglia: il sensore di distanza risponde in sei millesimi e
    # vuole tre letture d'accordo per dire che c'e' qualcuno, quindi il ritardo
    # dell'innesco e' tre battiti. A 0,15 erano quattrocentocinquanta
    # millesimi, meta' del secondo che abbiamo in tutto; a 0,05 sono
    # centocinquanta, e costano il dodici per cento di un core a non far niente.
    periodo_sensore_s: float = 0.05
    # Ogni quanto si guarda il piatto. Era mezzo secondo, quando una sbirciata
    # costava novanta millesimi di camera: accorgersi di una bottiglia voleva
    # un secondo e mezzo - due letture d'accordo piu' una di assestamento.
    #
    # Col guardiano in moto il fotogramma c'e' gia' e la sbirciata costa la
    # conversione in grigio, una decina di millesimi. Un quarto di secondo
    # porta l'arrivo sotto il secondo, e conta: per le bottiglie di vetro
    # chiaro, che il sensore di distanza non vede, questa e' l'unica via.
    periodo_sbirciata_s: float = 0.25
    # La lingua di partenza. Si cambia a schermo, con un tocco, e il
    # dispositivo torna a questa quando la bottiglia viene tolta: il tavolo
    # dopo trova il dispositivo come lo trova sempre.
    # Una carta dei vini al posto dell'archivio: un CSV con titolo e
    # descrizione, e il dispositivo legge quella invece di comporre dai dati.
    # E' una PROVA - vedi `amelie.carta` - e si spegne togliendo l'opzione.
    carta: str | None = None
    lingua: str = "it"
    # Il volume di partenza, che il file in `var` sovrascrive se c'e'. 100 e'
    # il fondo scala del PCM: sopra non si puo' andare, vedi speech.guadagno_di.
    volume: int = VOLUME_PREDEFINITO


class Amelie:
    def __init__(self, cfg: Configurazione) -> None:
        self.cfg = cfg
        self.macchina = Macchina(su_transizione=self._su_transizione)
        self.ponte: Ponte = PonteSimulato() if cfg.simula_mcu else Ponte()
        # Due modi di accorgersi della bottiglia, e fanno due lavori diversi.
        #
        # Il sensore di distanza dice QUANDO, e lo dice in millesimi: e' lui
        # l'innesco, perche' e' l'unico abbastanza rapido perche' il testo
        # compaia entro un secondo da quando il vetro tocca il piatto.
        #
        # La camera dice DOVE, e continua a servire: e' da lei che viene il
        # riquadro dell'etichetta, che cambia con la forma della bottiglia. Ed
        # e' il ripiego quando il sensore non risponde - un Modulino scollegato
        # non deve rendere cieco il dispositivo.
        self.presenza = PresenzaOttica()
        self.distanza = PresenzaDistanza()
        # Quando la bottiglia e' comparsa: lo scatto deve essere di DOPO.
        self._apparsa = 0.0
        self.camera = None if cfg.senza_camera else Camera()
        self.lettore = None if cfg.senza_camera else Lettore()
        self.giornale = Giornale(CARTELLA_GIORNALE)
        self.batteria = Batteria(PERCORSO_BATTERIA)
        self.carta = self._apri_carta(cfg.carta)
        # La voce della carta scelta per questa bottiglia, in attesa di essere
        # raccontata. Sostituisce i fatti per tutto il giro.
        self._voce: object | None = None
        self.matcher = Matcher()
        self.voce = None if cfg.senza_voce else Voce(
            ImpostazioniVoce(device_alsa=cfg.device_audio))
        self.narratore = Narratore(modello_addestrato=cfg.modello_addestrato,
                                   genera=self._genera if not cfg.senza_modello else None,
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
        # Una bottiglia finta, per il banco e per i test: vedi l'endpoint
        # /prova. Quando c'e' prende il posto di quello che vede la camera, e
        # passa comunque per l'isteresi vera.
        self._bottiglia_finta: bool | None = None
        # Quando tocca guardare di nuovo il piatto.
        self._prossima_sbirciata = 0.0
        # Lo sfondo scritto su disco, e quando si potra' riscrivere.
        self._sfondo_scritto = None
        self._prossimo_sfondo = 0.0
        # Il mirino, quando e' acceso. Non si costruisce qui: ha bisogno del
        # matcher e del lettore gia' aperti, e finche' nessuno lo chiede non
        # deve esistere. Vedi `imposta_mirino`.
        self.mirino: Mirino | None = None
        # Quello che si sa della scansione in corso, da annotare quando
        # finisce. Vedi `_annota`.
        self._scansione: dict[str, Any] = {}
        # Vero finche' non si e' capito che cosa c'e' sul piatto. Succede solo
        # al primo avvio di una installazione, quando nessuno sfondo e' stato
        # ancora imparato: l'unico modo di saperlo e' guardare per bene una
        # volta, cioe' accendere la luce e leggere.
        self._da_capire = False
        # Questa bottiglia e' gia' stata raccontata. Serve da quando la
        # schermata conclusa torna da sola all'invito: in attesa, con la
        # bottiglia ancora sul piatto, il rilancio qui sotto farebbe ripartire
        # una seconda lettura, e poi una terza. Si azzera quando la bottiglia
        # viene tolta - che e' il modo in cui l'ospite dice "ho finito".
        # Questa bottiglia e' gia' stata servita: si e' raccontata fino in
        # fondo, oppure l'ospite ha annullato. Finche' e' alzata, il ciclo non
        # riparte da solo. Si abbassa quando la bottiglia viene tolta davvero.
        self._bottiglia_chiusa = False
        self.volume = self._volume_salvato(cfg.volume)
        if self.voce is not None:
            self.voce.volume = self.volume
        # Spente di partenza: un dispositivo appena acceso deve rispondere
        # subito. Chi vuole la generazione dal vivo la accende sapendo che
        # costa un'attesa.
        self.modo = self._modo_salvato()

    @staticmethod
    def _apri_carta(percorso: str | None):
        """La carta dei vini, se ne e' stata chiesta una.

        Un file illeggibile non deve impedire al dispositivo di accendersi: si
        dice perche', e si torna all'archivio - che c'e' sempre.
        """
        if not percorso:
            return None
        try:
            return Carta(percorso)
        except (OSError, CartaVuota, KeyError) as e:
            log.error("carta dei vini non caricata (%s): uso l'archivio", e)
            return None

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
            # Annullare non vuol dire che il tavolo e' finito: la bottiglia
            # e' ancora li' e sono le stesse persone. Chi aveva scelto
            # l'inglese, premendo la croce, si ritrovava l'invito in italiano e
            # doveva ricercarsi la bandierina per la bottiglia dopo. La lingua
            # torna a casa quando la bottiglia viene TOLTA, che e' il momento
            # in cui il tavolo cambia davvero.
            if (t.cambia_stato and t.a is Stato.ATTESA
                    and t.evento is not Evento.ANNULLA):
                self._torna_alla_lingua_di_casa()
            # Questa bottiglia e' finita, comunque sia finita: perche' il
            # racconto e' arrivato in fondo, o perche' l'ospite ha annullato.
            # In tutti e due i casi il ciclo NON deve ripartire da solo con la
            # bottiglia ancora sul piatto - vedi il ramo di rilancio in
            # `_un_battito`, che senza questa bandiera rilancerebbe al primo
            # battito, cioe' un decimo di secondo dopo il tocco.
            if t.a is Stato.CONCLUSO or t.evento is Evento.ANNULLA:
                self._bottiglia_chiusa = True
            # Nessuno ha scelto, e i dodici secondi sono finiti: si prende il
            # PRIMO CANDIDATO, cioe' la prima riga che l'ospite aveva davanti.
            #
            # Prima si raccontava il match primario, che e' un'altra cosa: lo
            # schermo mostrava tre nomi, nessuno li toccava, e la voce ne
            # diceva un quarto che non era in lista. Visto sul dispositivo con
            # uno spumante rosa: tre candidati Metodo Classico Rose' a schermo,
            # e il racconto del Moscato d'Asti.
            if (t.da is Stato.CONFERMA and t.a is Stato.RACCONTO
                    and t.evento is Evento.SCADENZA):
                self._adotta_candidato(0)
            # Una scansione rimasta senza esito qui ha finito comunque, e va a
            # giornale con il modo in cui e' finita. Succede quando l'ospite
            # chiude la scelta fra candidati, o toglie la bottiglia a meta':
            # senza questa riga, proprio i casi piu' interessanti sarebbero gli
            # unici a non lasciare traccia.
            if self._scansione and t.a in (Stato.ATTESA, Stato.CONCLUSO):
                self._annota(f"chiuso da {t.evento.value}")
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
        if stato in (Stato.RACCONTO, Stato.CONCLUSO):
            f = self._fatti
            if self._la_carta_parla_ora():
                # Quando a raccontare e' la carta, il titolo e' il suo. Prima
                # veniva sempre dai fatti dell'archivio, che in modo carta non
                # si toccavano mai: a schermo restava il nome del vino
                # PRECEDENTE. Visto sul dispositivo, «Garda Cabernet 2008»
                # scritto sopra la descrizione di un Lambrusco Grasparossa.
                m["titolo"] = self._voce.titolo_in(self.lingua)
                m["sottotitolo"] = ""
            else:
                m["titolo"] = f.nome or f.tipologia or f.denominazione or (
                    f.vitigni[0] if f.vitigni else "")
                if not m["titolo"]:
                    # Al livello GENERICO non c'e' nessun nome da mettere - e'
                    # il livello in cui non si e' riconosciuto il vino - e lo
                    # schermo restava senza titolo: il testo saliva in cima,
                    # sotto le linguette della lingua, e l'ospite leggeva una
                    # descrizione senza sapere di CHE COSA.
                    #
                    # Il titolo c'e' lo stesso, ed e' quello che si e' letto
                    # sul vetro: «spumante rosato brut». Sono le stesse parole
                    # con cui il racconto apre, e non ne aggiunge nessuna.
                    m["titolo"] = _che_tipo_di_vino(f, self.lex, self.lingua)
                pezzi = [x for x in (f.cantina,
                                     str(f.annata) if f.annata else None) if x]
                m["sottotitolo"] = " · ".join(pezzi)
            # CONCLUSO mostra la stessa schermata del racconto - la vista non
            # cambia - e il racconto e' quello di prima: il testo NON va
            # svuotato. Senza questa riga, alla fine di ogni racconto l'ospite
            # guardava due secondi di schermo vuoto con sopra il solo pulsante:
            # titolo, testo e barra sparivano tutti insieme, perche' il client
            # ripulisce a ogni messaggio di stato con vista «racconto».
            m["stesso_racconto"] = stato is Stato.CONCLUSO
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
            "annulla": self.lex.frase("schermo", "annulla", lingua=self.lingua),
            # Che cosa scrivere al posto del racconto mentre lo si scrive.
            # Sta qui, con le altre scritte fisse, perche' segua la lingua da
            # sola: il messaggio si rimanda a ogni cambio.
            "sto_scrivendo": self.lex.frase("schermo", "sto_scrivendo",
                                            lingua=self.lingua),
            # Le scritte del pannello delle impostazioni stanno QUI e non nel
            # messaggio «impostazioni», che porta i valori: cosi' seguono la
            # lingua da sole, perche' questo messaggio si rimanda a ogni cambio.
            "impostazioni": {
                chiave: self.lex.frase("schermo", chiave, lingua=self.lingua)
                for chiave in ("impostazioni", "descrizioni_generate",
                               "generate_spiega", "stato_tecnico", "chiudi",
                               "mirino", "mirino_spiega", "mirino_torna",
                               "mirino_legge", "mirino_trova", "mirino_niente",
                               "modo_titolo", "modo_archivio",
                               "modo_archivio_spiega", "modo_generativa",
                               "modo_generativa_spiega", "modo_carta",
                               "modo_carta_spiega", "batteria_ricaricata",
                               "batteria_spiega")
            },
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

    @staticmethod
    def _scrivi_durevole(percorso: Path, valore: str, cosa: str) -> None:
        """Scrive in modo che sopravviva alla spina staccata.

        Questo dispositivo non si spegne con un comando: si toglie corrente a
        fine servizio. Fra la `rename` e il disco possono passare secondi, e in
        quei secondi il valore appena regolato non esiste da nessuna parte -
        chi ha appena tarato il volume e ha spento lo ritroverebbe com'era. Da
        qui i due `fsync`: uno per il contenuto, uno per la cartella, che e'
        cio' che rende durevole il nome nuovo.
        """
        try:
            percorso.parent.mkdir(parents=True, exist_ok=True)
            # Scrittura atomica: un file troncato da uno spegnimento tornerebbe
            # come valore illeggibile, e si ripartirebbe dal predefinito.
            tmp = percorso.with_suffix(".parziale")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{valore}\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(percorso)
            cartella = os.open(percorso.parent, os.O_RDONLY)
            try:
                os.fsync(cartella)
            finally:
                os.close(cartella)
        except OSError as e:
            log.warning("%s non salvato: %s", cosa, e)

    def _salva_volume(self, valore: int) -> None:
        self._scrivi_durevole(PERCORSO_VOLUME, str(valore), "volume")

    # ------------------------------------------------------------- sfondo

    def _sfondo_ricordato(self):
        """Il piatto vuoto dell'ultima volta, se c'è ed è ancora della forma giusta.

        Non solleva mai: un file illeggibile, o scritto quando la fascia era
        grande diversamente, deve costare una scansione in più all'avvio, non
        un dispositivo che non si accende.
        """
        try:
            import numpy as np

            sfondo = np.load(PERCORSO_SFONDO)
        except Exception as e:                              # noqa: BLE001
            log.info("nessuno sfondo ricordato (%s): guardo una volta per capire", e)
            return None
        atteso = (self.camera.imp.sbirciata[1], self.camera.imp.sbirciata[0])
        if sfondo.shape != atteso:
            log.warning("sfondo ricordato di forma %s invece di %s: lo ignoro",
                        sfondo.shape, atteso)
            return None
        return sfondo.astype("float32")

    def _ricorda_sfondo(self) -> None:
        """Scrive il piatto vuoto, ma solo se è cambiato e non troppo spesso."""
        import numpy as np

        from .capture import quanto_diverso

        sfondo = self.presenza.sfondo
        if sfondo is None or time.monotonic() < self._prossimo_sfondo:
            return
        if (self._sfondo_scritto is not None
                and quanto_diverso(self._sfondo_scritto, sfondo) < SFONDO_DA_RISCRIVERE):
            return
        try:
            PERCORSO_SFONDO.parent.mkdir(parents=True, exist_ok=True)
            tmp = PERCORSO_SFONDO.with_suffix(".parziale.npy")
            with open(tmp, "wb") as f:
                np.save(f, sfondo)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(PERCORSO_SFONDO)
            cartella = os.open(PERCORSO_SFONDO.parent, os.O_RDONLY)
            try:
                os.fsync(cartella)
            finally:
                os.close(cartella)
        except OSError as e:
            log.warning("sfondo non salvato: %s", e)
            return
        self._sfondo_scritto = sfondo
        self._prossimo_sfondo = time.monotonic() + RIPOSO_SFONDO_S
        log.info("sfondo del piatto vuoto aggiornato")

    # ------------------------------------------------------- impostazioni

    def _modo_salvato(self) -> str:
        """Come raccontava l'ultima volta.

        Come il volume, non solleva mai: un file illeggibile deve costare le
        impostazioni predefinite, non un dispositivo che non si accende. E un
        modo salvato che non si puo' piu' servire - la carta, quando il file
        non c'e' piu' - torna all'archivio invece di lasciare il dispositivo
        muto: l'archivio c'e' sempre.
        """
        try:
            salvato = PERCORSO_MODO.read_text(encoding="utf-8").strip()
        except OSError:
            salvato = ""
        if salvato not in MODI:
            # Dalla versione di prima, che sapeva dire solo si' e no.
            try:
                acceso = PERCORSO_GENERATI.read_text(encoding="utf-8").strip() == "1"
            except OSError:
                acceso = False
            salvato = "generativa" if acceso else "archivio"
        if salvato == "carta" and self.carta is None:
            log.warning("modo «carta» salvato ma la carta non c'e': uso l'archivio")
            return "archivio"
        if salvato == "generativa" and self.narratore.genera is None:
            return "archivio"
        return salvato

    @property
    def genera_racconti(self) -> bool:
        """Il modello scrive sul momento? È il modo «generativa», detto com'era
        detto prima: lo chiedono il narratore e i test."""
        return self.modo == "generativa"

    def imposta_modo(self, modo: str) -> dict[str, Any]:
        """Il selettore di come raccontare.

        Non tocca il racconto in corso: cambiare a meta' di una lettura
        significherebbe interromperla, e chi sta ascoltando non ha chiesto
        nulla. Vale dalla bottiglia dopo.
        """
        if modo not in MODI:
            return {"ok": False, "motivo": f"modi: {', '.join(MODI)}"}
        if modo == "carta" and self.carta is None:
            return {"ok": False, "motivo": "nessuna carta caricata"}
        if modo == "generativa" and self.narratore.genera is None:
            return {"ok": False, "motivo": "nessun modello caricato"}
        self.modo = modo
        self._scrivi_durevole(PERCORSO_MODO, modo, "il modo di raccontare")
        self._manda_impostazioni()
        log.info("modo di racconto: %s", modo)
        self._accendi_il_modello(modo == "generativa")
        return {"ok": True, "modo": modo}

    def _accendi_il_modello(self, acceso: bool) -> None:
        """Il servizio del modello linguistico si accende solo se serve.

        Misurato sul dispositivo: `llama-server` fermo, senza nessuna richiesta,
        sta all'88% di un core - e sono i quattro core su cui l'OCR deve
        leggere un'etichetta in meno di un secondo. Con la generazione spenta
        dalle impostazioni quel core era regalato a nessuno: la rilevazione
        del testo passava da 274 a 750 millesimi.

        Si accende e si spegne col modo, in un thread perche' avviarlo carica
        ottocento megabyte e nessuno deve aspettarlo. Se il comando fallisce si
        registra e basta: un dispositivo senza modello racconta dall'archivio,
        un dispositivo bloccato non racconta niente.

        Senza `sudo`, di proposito: l'applicazione gira sotto
        `NoNewPrivileges=yes` e `sudo` non puo' alzare niente - falliva con
        exit 1 e nessun altro segno. Il permesso sta in una regola polkit
        (`scripts/systemd/50-amelie-llm.rules`) che lascia all'utente
        `arduino` QUESTA unita' e nessun'altra.
        """
        if self.cfg.senza_modello:
            return

        def esegui() -> None:
            import subprocess
            verbo = "start" if acceso else "stop"
            try:
                subprocess.run(["systemctl", verbo, SERVIZIO_MODELLO],
                               check=True, capture_output=True, timeout=30)
                log.info("modello linguistico: %s", "acceso" if acceso else "spento")
            except Exception as e:                          # noqa: BLE001
                log.warning("modello linguistico, %s fallito: %s", verbo, e)

        threading.Thread(target=esegui, name="modello", daemon=True).start()

    def imposta_generati(self, acceso: bool) -> dict[str, Any]:
        """L'interruttore di prima, tenuto perche' qualcuno lo chiama ancora."""
        return self.imposta_modo("generativa" if acceso else "archivio")

    # --------------------------------------------------------------- mirino

    def imposta_mirino(self, acceso: bool) -> dict[str, Any]:
        """L'interruttore del mirino: il dispositivo smette di raccontare e guarda.

        Sono due modi di usare la stessa camera e non possono convivere: la
        camera si apre un processo per volta, e mentre il mirino tiene lo
        stream per mostrare cosa vede, una scansione non può scattare. Quindi
        accendere il mirino **ferma il ciclo**: niente sbirciate al piatto,
        niente racconti, niente timer. Si spegne dallo stesso interruttore, e
        il dispositivo torna quello di prima.

        Non si ricorda fra un avvio e l'altro, ed è voluto: questa è una
        modalità di taratura, e un dispositivo che si riaccende in sala deve
        riaccendersi come un dispositivo che racconta vini. Chi l'ha lasciata
        accesa la sera prima non se ne ricorderà.

        L'anello va a bianco come durante la raffica, e la posa si cerca una
        volta all'accensione: si tara l'inquadratura con la luce e la posa che
        ci saranno davvero, non con quelle della stanza.
        """
        acceso = bool(acceso)
        if acceso == (self.mirino is not None and self.mirino.acceso):
            return self._stato_mirino()
        if acceso:
            self._accendi_mirino()
        else:
            self._spegni_mirino()
        stato = self._stato_mirino()
        # Si dichiara com'e' andata, non cosa si e' chiesto: senza camera
        # l'accensione non succede, e un giornale che dice «acceso» mentre lo
        # schermo resta nero manda a cercare il guasto dalla parte sbagliata.
        log.info("mirino: %s", "acceso" if stato["acceso"] else "spento")
        self._manda_mirino()
        return stato

    def _accendi_mirino(self) -> None:
        if self.camera is None or self.lettore is None:
            log.warning("mirino senza camera: non c'è niente da inquadrare")
            return
        # Prima si chiude quello che c'era: un racconto che continua a parlare
        # mentre lo schermo mostra il mirino è un dispositivo in due posti.
        self._ferma_racconto()
        self._bottiglia_chiusa = False
        # «La bottiglia non c'e' piu'» e' proprio la notizia giusta: e' il modo
        # in cui si dichiara che il giro e' finito, e riporta in attesa da
        # qualunque stato. Non serve una scorciatoia che gli somigli.
        self.macchina.invia(Evento.BOTTIGLIA_ASSENTE)
        try:
            self.ponte.anello(BIANCO_SCATTO)
        except (PonteNonDisponibile, ErroreMCU):
            pass
        if self.mirino is None:
            # Il mirino apre il SUO lettore e il SUO matcher. Prestargli quelli
            # del dispositivo sembrava un risparmio e invece e' una corsa: se
            # una scansione e' ancora in corso quando si accende il mirino, due
            # fili finiscono dentro allo stesso motore ONNX e alla stessa
            # connessione SQLite. Vedi `LetturaContinua`.
            self.mirino = Mirino(self.camera, LetturaContinua(),
                                 presenza=self.presenza)
        self.mirino.accendi()

    def _spegni_mirino(self) -> None:
        if self.mirino is not None:
            self.mirino.spegni()
        # Lo stream si chiude: la prima sbirciata lo riaccende, e cosi' la
        # camera riparte pulita invece che da uno stream che il mirino stava
        # leggendo a raffica.
        if self.camera is not None:
            self.camera.chiudi()
        # Il piatto vuoto si ripesca da dove sta scritto, invece di
        # reimpararlo da quello che c'e' davanti adesso. Chi tara il mirino ha
        # una bottiglia in mano: reimparando, quella bottiglia diventerebbe lo
        # sfondo, e il dispositivo resterebbe a guardarla senza vederla.
        sfondo = self._sfondo_ricordato() if self.camera is not None else None
        if sfondo is not None:
            self.presenza.ricorda(sfondo)
        else:
            self.presenza.reimposta()
        # E si guarda, come all'accensione. Uscire dal mirino e' la stessa
        # situazione: la camera stava facendo altro, il mondo davanti puo'
        # essere cambiato, e lo sfondo appena ricaricato dice com'era il piatto
        # quando il dispositivo CREDEVA fosse vuoto. Senza questa riga bastava
        # entrare e uscire dal mirino con una bottiglia sul piatto per
        # ritrovarsi a crederlo vuoto - e chi tara l'inquadratura la bottiglia
        # ce l'ha davanti per definizione.
        #
        # E' anche cio' che chi ha appena spostato la camera vuole: la prova
        # che l'aggiustamento ha funzionato, senza doverla chiedere.
        if self.camera is not None:
            self._da_capire = True
        self._mostra(self.macchina.stato)

    def _stato_mirino(self) -> dict[str, Any]:
        acceso = self.mirino is not None and self.mirino.acceso
        return {"ok": True, "acceso": acceso,
                "disponibile": self.camera is not None and self.lettore is not None,
                "nitidezza": round(self.mirino.nitidezza) if acceso else 0}

    def _manda_mirino(self) -> None:
        self._pubblica({"tipo": "mirino", **self._stato_mirino()})

    # -------------------------------------------------------- giornale

    def _annota(self, esito: str) -> None:
        """Mette a giornale la scansione appena conclusa, com'è andata.

        Si chiama dove la scansione FINISCE, e finisce in due posti soli: senza
        niente da leggere, oppure con un racconto pronto. Quello che si sa si
        è accumulato per strada in `_scansione`.
        """
        voce = dict(self._scansione)
        self._scansione = {}
        if not voce:
            return
        voce["esito"] = esito
        voce["lingua"] = self.lingua
        self.giornale.annota(voce, getattr(self, "_ultimo_scatto", None))

    def _manda_impostazioni(self) -> None:
        self._pubblica({"tipo": "impostazioni",
                        "modo": self.modo,
                        # Un modo che non si puo' servire non si mostra: un
                        # comando che non fa niente e' peggio di nessun comando.
                        "modi": [m for m in MODI if self._modo_servibile(m)],
                        "generati": self.genera_racconti,
                        # Senza un modello acceso l'interruttore non si mostra:
                        # un comando che non fa niente e' peggio di nessun
                        # comando. E' lo stesso criterio del volume senza voce.
                        "modello": self.narratore.genera is not None,
                        # Il livello della batteria viaggia anche qui perche'
                        # questo messaggio arriva a ogni pagina che si collega:
                        # la spia di salute passa ogni venti secondi, e venti
                        # secondi di icona vuota all'accensione sono un
                        # allarme falso.
                        "batteria": self._batteria_a_schermo()})

    def _modo_servibile(self, modo: str) -> bool:
        if modo == "carta":
            return self.carta is not None
        if modo == "generativa":
            return self.narratore.genera is not None
        return True

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
        """Chiede di annunciare una lingua, SUBITO, tagliando quella in corso.

        Chi tocca una bandierina mentre il dispositivo sta annunciando l'altra
        ha cambiato idea: sentirsi finire la frase di prima, e solo dopo quella
        chiesta, fa sembrare il tocco perso.

        Questa e' la seconda volta che si sceglie di interrompere, e la prima
        volta era andata male: gli annunci si tagliavano a vicenda e non si
        sentiva NIENTE, come un guasto dell'amplificatore. La causa pero' non
        era l'interruzione — era che il flusso audio si apriva e si chiudeva a
        ogni frase, e il DSP di questa board impiega due secondi ad avviarsi:
        una frase da un secondo spariva dentro quei due. Da quando il flusso
        resta APERTO (vedi `speech.Uscita`) quel costo non c'e' piu', e
        interrompere fa esattamente quello che sembra: tace e riparte.
        """
        with self._lucchetto_annuncio:
            self._lingua_da_annunciare = lingua
            gia_in_corso = self._annunciatore_vivo
            self._annunciatore_vivo = True
        if gia_in_corso:
            # Si butta via cio' che non e' ancora uscito: l'annuncio in corso
            # smette di aspettare la propria coda e torna, e il ciclo trova
            # subito la lingua nuova.
            if self.voce is not None:
                self.voce.zittisci()
            self._didascalia("")
            return
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
        # E l'annuncio deve aver FINITO DI PARLARE. Scrivono tutti e due nello
        # stesso flusso audio: partendo insieme, «English language» e la prima
        # frase del racconto uscivano sovrapposte, e non si capiva ne' l'una ne'
        # l'altra. L'ordine giusto e' quello che ci si aspetta sentendolo:
        # prima la lingua, poi il vino in quella lingua.
        self._attendi_annuncio(6.0)
        self.macchina.invia(Evento.RIPETI)

    def _attendi_annuncio(self, secondi: float) -> None:
        """Aspetta che l'annunciatore abbia smesso di parlare. Mai per sempre."""
        scadenza = time.monotonic() + secondi
        while self._annunciatore_vivo and time.monotonic() < scadenza:
            time.sleep(0.05)

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
        """Ferma la riproduzione in corso e chi la stava aspettando.

        La bandiera si alza SOTTO il lucchetto del riproduttore, non prima: e'
        cio' che rende impossibile passare fra il controllo e l'assegnazione in
        `_racconta` e lasciar partire un racconto gia' annullato.
        """
        with self._lucchetto_lettore:
            self._ferma_voce.set()
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
                # Lo stream della camera si spegne PRIMA di parlare. Con il
                # DisplayPort attivo il link USB scende a 2.0 e camera e audio
                # si dividono un bus solo: e' la ragione per cui questo modulo
                # apriva e chiudeva la camera a ogni scatto, e resta valida
                # adesso che la tiene accesa per guardare il piatto. Si
                # riaccende da sola alla prima sbirciata dopo il racconto.
                if self.camera is not None:
                    self.camera.chiudi()
                self._avvia(self._racconta)
            elif e is Effetto.FERMA_RACCONTO:
                # Non una copia: la fermata e' UNA. Ce n'erano due, e quella
                # che stava qui - cioe' quella che usano l'annullamento e la
                # bottiglia tolta - alzava la bandiera FUORI dal lucchetto del
                # riproduttore, che e' esattamente cio' che apre la finestra
                # descritta in `_racconta`. Una sola copia, un solo invariante.
                self._ferma_racconto()
            elif e is Effetto.MOSTRA_CANDIDATI:
                self._pubblica({"tipo": "candidati", "voci": self._candidati,
                                "nessuno": self.lex.frase("schermo", "nessuno_di_questi",
                                                          lingua=self.lingua)})
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
        # c'è l'OCR, e mezzo secondo di bianco pieno sotto una bottiglia è un
        # lampeggiante, non una luce.
        #
        # Tutto questo vale però solo per la raffica. Quando la camera è già in
        # moto non c'è nessuna raffica da illuminare: il fotogramma buono è
        # quello che sta arrivando comunque, ed è stato esposto con la luce che
        # c'era. Alzare l'anello per poi riabbassarlo un decimo dopo sarebbe un
        # lampo che non illumina niente — cinque livelli su 255, misurati,
        # contro i quaranta che dà la posa.
        inizio_scatto = time.perf_counter()
        scatto = self.camera.al_volo(dopo=self._apparsa)
        if scatto is None:
            try:
                self.ponte.anello(BIANCO_SCATTO)
            except (PonteNonDisponibile, ErroreMCU):
                # Un anello che non si accende costa una foto piu' scura, non
                # una scansione fallita: e' la stessa regola con cui `_esegui`
                # protegge tutti gli effetti. Senza ErroreMCU, un firmware
                # vecchio che non conosce `set_anello` trasformava ogni scatto
                # in un guasto.
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

        durata_scatto = time.perf_counter() - inizio_scatto
        try:
            # Il guardiano si ferma per il tempo della lettura: il fotogramma
            # buono ce l'abbiamo gia', e decodificare MJPEG mentre l'OCR gira
            # vuol dire toglierle un core su quattro.
            with self.camera.in_pausa():
                lettura = self.lettore.leggi_comunque(scatto.immagine)
        except OCRNonDisponibile as e:
            log.error("OCR: %s", e)
            self.macchina.invia(Evento.ERRORE)
            return

        self._righe = [r.testo for r in lettura.righe]
        # Si tiene l'ultimo scatto: se l'ospite segnala che il vino non e' fra
        # quelli proposti, e' l'unica cosa che permette di capire perche'.
        self._ultimo_scatto = scatto.immagine
        log.info("scatto in %.2f s, lette %d righe in %.2f s (nitidezza %.0f)",
                 durata_scatto, len(self._righe), lettura.durata_s,
                 scatto.nitidezza)
        self._scansione = {
            "righe": list(self._righe),
            # Due numeri e non uno: quando la scansione e' lenta, il primo dice
            # se il tempo se n'e' andato davanti alla camera o dentro l'OCR, e
            # da qui non si puo' guardare il dispositivo per capirlo.
            "scatto_s": round(durata_scatto, 2),
            "ocr_s": round(lettura.durata_s, 2),
            "nitidezza": round(scatto.nitidezza),
            "posa": self.camera.imp.esposizione,
            "tentativo": self._tentativi + 1,
        }
        if self._righe:
            self._tentativi = 0
            # Un'etichetta letta e' la prova che sul piatto c'e' qualcosa, e
            # vale piu' di qualunque sbirciata: se il dispositivo si e' acceso
            # con la bottiglia gia' posata, e' l'unica cosa che glielo dice.
            self.presenza.c_e_qualcosa()
            self.macchina.invia(Evento.LETTURA_RIUSCITA)
            return
        self._tentativi += 1
        self._annota("niente da leggere")
        self.macchina.invia(Evento.LETTURA_FALLITA)
        if self._tentativi >= TENTATIVI_MAX:
            # Si e' provato abbastanza: si mostra il messaggio e si tace, invece
            # di riaccendere la luce ogni quattro secondi finche' qualcuno non
            # toglie l'oggetto dal piatto.
            log.info("rinuncio dopo %d tentativi", self._tentativi)
            # E si impara: tre volte con la luce accesa senza trovare una
            # parola vuol dire che quel che si vede non e' un'etichetta. Se lo
            # sfondo era sbagliato - ricaricato da un'altra installazione,
            # imparato con una bottiglia davanti - questo e' cio' che lo
            # rimette a posto, invece di lasciare il dispositivo a credere per
            # sempre di avere qualcosa davanti.
            if self.camera is not None:
                fascia = self.camera.sbircia()
                if fascia is not None:
                    self.presenza.non_e_una_bottiglia(fascia)
                    # Senza aspettare il riposo: questo e' proprio il caso in
                    # cui lo sfondo su disco e' quello sbagliato, e deve
                    # smettere di esserlo anche dopo un riavvio.
                    self._prossimo_sfondo = 0.0
                    self._ricorda_sfondo()
            self.macchina.invia(Evento.RINUNCIA)

    def _riconosci(self) -> None:
        # Niente di questa bottiglia si eredita dalla precedente. Ogni via
        # riempie una delle due - i fatti dell'archivio o la voce della carta -
        # e l'altra deve restare vuota, perche' lo schermo guarda tutt'e due.
        self._voce = None
        self._fatti = Fatti()
        if self.modo == "carta" and self.carta is not None:
            self._riconosci_dalla_carta()
            return
        self._fatti = self.matcher.cerca(getattr(self, "_righe", []))
        self._candidati = self._fatti.candidati
        log.info("livello %s, sicurezza %.0f", self._fatti.livello.value,
                 self._fatti.sicurezza)
        self._scansione.update({
            "livello": self._fatti.livello.value,
            "sicurezza": round(self._fatti.sicurezza),
            "nome": self._fatti.nome or "",
            "cantina": self._fatti.cantina or "",
            "annata": self._fatti.annata or "",
            # A livello di tipologia o denominazione il `nome` e' vuoto, e
            # senza questi due il giornale diceva «riconosciuto» senza dire
            # CHE COSA. Il colore sta qui perche' e' il vincolo che non si puo'
            # sbagliare: nessuna descrizione di un bianco vale per un rosato.
            "tipologia": self._fatti.tipologia or "",
            "denominazione": self._fatti.denominazione or "",
            "colore": self._fatti.colore or "",
            "candidati": list(self._candidati),
        })
        if self._fatti.certo:
            self.macchina.invia(Evento.MATCH_SICURO)
        elif self._fatti.dubbio and self._candidati:
            self.macchina.invia(Evento.MATCH_DUBBIO)
        elif self._fatti.vuoto:
            self._annota("letto ma non riconosciuto")
            self.macchina.invia(Evento.LETTURA_FALLITA)
        else:
            self.macchina.invia(Evento.MATCH_ASSENTE)

    def _riconosci_dalla_carta(self) -> None:
        """Il riconoscimento quando al posto dell'archivio c'e' un file di testo.

        Si cerca il titolo e basta: niente cascata, niente candidati da
        proporre. Una carta dei vini o ce l'ha, quella bottiglia, o non ce
        l'ha - e quando non ce l'ha lo si dice, invece di scendere a qualcosa
        di piu' generico che nel file non esiste.
        """
        righe = getattr(self, "_righe", [])
        self._voce = self.carta.cerca(righe)
        self._candidati = []
        if self._voce is None:
            self._scansione["vicine"] = self.carta.vicine(righe)
            log.info("carta: nessun titolo per %s", righe)
            self._annota("non in carta")
            self.macchina.invia(Evento.LETTURA_FALLITA)
            return
        self._scansione.update({
            "livello": "carta",
            "sicurezza": round(self._voce.somiglianza),
            "titolo": self._voce.titolo,
        })
        # E si cerca ANCHE in archivio, che costa cinquanta millesimi e parla
        # tutte le lingue. Serve quando l'ospite chiede l'inglese e la carta e'
        # scritta solo in italiano: senza, gli arrivava la prima frase tradotta
        # e tutto il resto in italiano, scritto e letto dalla voce inglese.
        self._fatti = self.matcher.cerca(righe)
        self.macchina.invia(Evento.MATCH_SICURO)

    def _aspetta_il_modello(self, secondi: float = 45.0) -> None:
        from .llm import Modello
        if not hasattr(self, "_modello"):
            self._modello = Modello()
        if not self._modello.attendi(secondi):
            log.warning("il modello non risponde: racconto dall'archivio")

    def _si_generera(self) -> bool:
        """Questo racconto passera' dal modello, cioe' fara' aspettare?

        Le stesse condizioni che `Narratore.racconta` applica per primo: il
        modello acceso dalle impostazioni, un modello davvero disponibile, e un
        livello in cui ci sia qualcosa da raccontare. Duplicarle qui non e'
        bello, ma la decisione va presa PRIMA della chiamata che dura secondi,
        e chiederla al narratore vorrebbe dire aver gia' aspettato.
        """
        return (self.genera_racconti
                and self.narratore.genera is not None
                and not self._fatti.vuoto
                and self._fatti.livello is not Livello.GENERICO)

    def _la_carta_parla_ora(self) -> bool:
        """La carta ha questa bottiglia E sa dirla in questa lingua?

        Due condizioni, e la seconda cambia mentre il dispositivo e' acceso:
        l'ospite tocca la bandierina e la carta, che era la voce giusta un
        istante prima, smette di esserlo.
        """
        return (self._voce is not None
                and self._voce.testo_in(self.lingua) is not None)

    def _racconta_dalla_carta(self):
        """Il racconto e' la descrizione scritta nel file, letta com'e'.

        Davanti si mette il titolo, perche' il dispositivo deve prima dire
        CHE COSA ha in mano: la descrizione lo spiega, ma non lo nomina.
        """
        from .narrator import Racconto, _con_articolo
        from .matcher import Livello

        import zlib

        v = self._voce
        titolo = v.titolo_in(self.lingua)
        # Col seme del titolo, come fa il narratore col vino: stessa voce,
        # stesse parole, e voci diverse non aprono tutte allo stesso modo.
        apre = self.lex.frase("apertura", "tipologia_nota", lingua=self.lingua,
                              seme=zlib.crc32(titolo.encode("utf-8")),
                              cosa=_con_articolo(titolo, self.lingua))
        return Racconto(testo=f"{apre} {v.testo_in(self.lingua)}",
                        origine="carta", livello=Livello.TIPOLOGIA)

    def _racconta(self) -> None:
        self._ferma_voce.clear()
        if self._la_carta_parla_ora():
            racconto = self._racconta_dalla_carta()
        else:
            # Generare costa secondi, e in quei secondi lo schermo mostrava il
            # titolo e sotto il vuoto: sembrava rotto. Si dice che si sta
            # scrivendo, e lo si dice PRIMA - non e' una decorazione, e'
            # l'unica differenza fra un dispositivo che lavora e uno fermo.
            if self._si_generera():
                self._pubblica({"tipo": "scrivendo"})
                # Il servizio puo' essere stato acceso un attimo fa, dal
                # selettore, e carica ottocento megabyte: si aspetta che
                # risponda, con la scritta gia' a schermo. Se non arriva si
                # racconta dall'archivio, come se il modo fosse l'altro.
                self._aspetta_il_modello()
            racconto = self.narratore.racconta(
                self._fatti, preferisci_modello=self.genera_racconti)
        log.info("racconto da %s (%d parole)", racconto.origine,
                 len(racconto.testo.split()))
        frasi = racconto.frasi
        # La scansione finisce qui: si e' letto, si e' cercato, e c'e' un
        # racconto pronto. Si mette a giornale con dentro anche COSA si e'
        # detto: un riconoscimento giusto puo' produrre un testo sbagliato, e
        # senza il testo quel caso non si vede.
        self._scansione["racconto_da"] = racconto.origine
        self._scansione["racconto"] = racconto.testo
        self._annota("raccontato")

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
                su_avanzamento=lambda i: self._pubblica({"tipo": "riproduzione", **i}))
        except Exception as e:                              # noqa: BLE001
            log.warning("riproduttore non avviabile: %s", e)
            self._scorri_senza_voce(frasi)
            return

        # Fra la generazione del testo e questa riga puo' essere passato un
        # minuto, e in quel minuto `_lettore` era vuoto: un annullamento caduto
        # li' non trovava niente da fermare e il dispositivo cominciava a
        # parlare sopra la schermata d'invito.
        #
        # Il controllo sta DENTRO il lucchetto, insieme all'assegnazione, e
        # `_ferma_racconto` alza la bandiera dentro lo stesso lucchetto: senza,
        # fra il controllo e l'assegnazione restano pochi bytecode in cui un
        # annullamento passa in mezzo, non trova nessun riproduttore da fermare
        # e ne lascia partire uno subito dopo. Stretta quanto si vuole, e'
        # comunque la finestra che questa correzione doveva chiudere.
        with self._lucchetto_lettore:
            if self._ferma_voce.is_set():
                log.info("racconto annullato prima di cominciare")
                return
            self._lettore = lettore
        lettore.avvia()
        finito = lettore.attendi(timeout=TETTO_RACCONTO_S)
        # Se e' finito da solo, si aspetta che l'ULTIMO SUONO sia uscito davvero
        # prima di fermare: `ferma()` svuota la coda, e fra l'ultimo pezzo
        # consegnato e l'orecchio ci sono la riserva dell'uscita e la latenza di
        # ALSA. Erano i tre quarti di secondo che si perdevano in fondo a ogni
        # racconto, in tutte e due le lingue.
        #
        # Se invece l'hanno fermato - bottiglia tolta - si tronca eccome: e'
        # esattamente quello che serve.
        if finito and not self._ferma_voce.is_set():
            lettore.attendi_la_coda()
        with self._lucchetto_lettore:
            if self._lettore is lettore:
                self._lettore = None
        lettore.ferma()

        if finito and not self._ferma_voce.is_set():
            self.macchina.invia(Evento.RACCONTO_FINITO)

    def _scorri_senza_voce(self, frasi: list[str]) -> None:
        """Il ripiego quando non c'e' voce: il testo si illumina da solo.

        Il ritmo e' quello di una lettura ad alta voce. Era «circa quindici
        caratteri al secondo», dichiarato come stima; ora e' il ritmo MISURATO
        della voce che sta imitando - 17,2 caratteri al secondo in italiano,
        14,4 in inglese - cosi' il testo scorre come sarebbe stato letto.

        E pubblica una quota vera. Prima mandava `durata: 0`, e il client
        saltava l'aggiornamento: quando la lingua non ha voce la barra e'
        nascosta dal foglio di stile e non si notava, ma a questo ripiego ci si
        arriva ANCHE quando la voce per la lingua c'e' e il riproduttore non
        parte. Li' la barra e' bene in vista, e restava ferma a zero per tutto
        il racconto.
        """
        pesi = [max(1, len(per_la_voce(f, self.lingua))) for f in frasi]
        totale = sum(pesi)
        fatto = 0
        # Il ritmo della lingua che si sta MOSTRANDO. Non `voce.imp.modello`:
        # quando la lingua scelta non ha voce, `Voce.per_lingua` esce prima di
        # cambiare il modello, e li' resta quello dell'ultima lingua che una
        # voce ce l'aveva. Il testo inglese sarebbe scorso al ritmo italiano -
        # cioe' proprio nel caso per cui questo ripiego esiste.
        car_s = caratteri_al_secondo(VOCI.get(self.lingua, ""))
        for i, frase in enumerate(frasi):
            if self._ferma_voce.is_set():
                return
            self._pubblica({"tipo": "riproduzione", "frase": i,
                            "posizione": 0.0, "durata": 0.0,
                            "quota": round(fatto / totale, 3),
                            "in_pausa": False, "completo": False,
                            "senza_voce": True})
            # `wait` e non `sleep`: la bandiera e' un Event, e aspettarci
            # sopra fa tornare il thread nell'istante in cui viene alzata.
            # Dormendo, chi annulla lasciava il thread di lavoro vivo fino a
            # sei secondi dopo che lo schermo era gia' tornato all'invito - e
            # una bottiglia rimessa dentro quella finestra trovava il lavoro
            # ancora in corso, cioe' un guasto dichiarato.
            if self._ferma_voce.wait(min(6.0, max(1.0, pesi[i] / car_s))):
                return
            fatto += pesi[i]
        if not self._ferma_voce.is_set():
            self._pubblica({"tipo": "riproduzione", "frase": len(frasi) - 1,
                            "posizione": 0.0, "durata": 0.0, "quota": 1.0,
                            "in_pausa": False, "completo": True,
                            "senza_voce": True})
            self.macchina.invia(Evento.RACCONTO_FINITO)

    # ------------------------------------------------------------- comandi

    def comanda_racconto(self, azione: str) -> dict:
        """I pulsanti sotto il racconto. Nient'altro sullo schermo reagisce.

        Se non c'e' niente in riproduzione si risponde e basta: un tocco che
        arriva mentre il racconto sta finendo non deve sollevare nulla.
        """
        with self._lucchetto_lettore:
            lettore = self._lettore
        # `esaurito` e non solo `None`: il riproduttore resta agganciato ancora
        # mezzo secondo dopo la fine, il tempo che l'ultimo suono esca davvero.
        # In quella finestra i suoi thread sono gia' morti, e un tocco su
        # «indietro» faceva arretrare la barra lasciandocela, perche' nessuno
        # pubblicava piu' niente.
        if lettore is None or lettore.esaurito:
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

    def annulla(self) -> dict:
        """Il tocco su «annulla»: si chiude e si torna all'invito.

        Serve perche' fino a qui l'unico modo di finire era TOGLIERE LA
        BOTTIGLIA. Va benissimo nel caso normale, ma non per chi ha appena
        versato: il vino e' nel bicchiere, la bottiglia sta sul piatto, e
        risollevarla solo per far tacere il dispositivo e' una cosa che non si
        chiede a un ospite.

        Quasi tutto lo spegne la macchina, e va lasciato fare a lei: uscendo da
        RACCONTO scatta FERMA_RACCONTO, entrando in ATTESA tornano l'anello in
        respiro, la schermata d'invito e la lingua di casa, e la scadenza dei
        dodici secondi della conferma si azzera da sola. Scrivere l'annullamento
        fuori dalla macchina significa dimenticarsene meta': la voce tace e
        l'anello resta verde sopra la schermata d'invito.

        Restano due cose che la macchina non puo' sapere, ed e' per quelle che
        questo metodo esiste.

        La PRIMA e' l'annuncio della lingua, che vive in un thread suo. Uscendo
        da RACCONTO viene zittito di rimbalzo, perche' FERMA_RACCONTO svuota il
        flusso; uscendo dalla CONFERMA no. Chi guarda i candidati, tocca una
        bandierina e poi annulla si sentirebbe finire «English» sopra la
        schermata d'invito.

        La SECONDA e' il racconto non ancora cominciato. Fra la generazione del
        testo e l'avvio del riproduttore c'e' una finestra in cui `_lettore` e'
        ancora vuoto: un FERMA_RACCONTO che cade li' non trova niente da
        fermare, e il dispositivo comincia a parlare a schermata d'invito gia'
        disegnata. Con i testi in archivio la finestra e' quasi nulla, col
        modello linguistico acceso arriva a un minuto - e ci mette tanto
        proprio quando qualcuno ha voglia di annullare. `_ferma_voce` resta
        alzata, e `_racconta` la rilegge prima di dare fiato.

        Non promette silenzio istantaneo: i due decimi di secondo gia'
        consegnati ad ALSA escono comunque. Sono gli stessi che si sentono oggi
        togliendo la bottiglia.
        """
        stato = self.macchina.stato
        # Si guarda PRIMA se c'e' qualcosa da annullare, e nel dubbio non si
        # tocca niente. Zittendo prima di sapere, un tocco caduto nel vuoto -
        # arrivato mentre la schermata stava gia' cambiando - lascerebbe
        # `_ferma_voce` alzata addosso al racconto che sta per partire; e
        # riabbassarla dopo sarebbe peggio, perche' potrebbe averla alzata
        # qualcun altro un istante prima, per esempio chi ha tolto la
        # bottiglia. Meglio non entrarci affatto.
        if (stato, Evento.ANNULLA) not in TRANSIZIONI:
            log.info("annulla ignorato: la macchina e' in %s", stato.value)
            return {"ok": False, "stato": stato.value}
        # Ora si puo'. Prima si zittisce e poi si manda l'evento: al contrario,
        # fra l'ingresso in ATTESA e il silenzio ci sarebbe una frase intera.
        self._ferma_voce.set()
        with self._lucchetto_annuncio:
            self._lingua_da_annunciare = None
        if self.voce is not None:
            self.voce.zittisci()
        t = self.macchina.invia(Evento.ANNULLA)
        log.info("annullato da %s", stato.value)
        return {"ok": True, "stato": t.a.value}

    def segnala(self) -> dict:
        """«Nessuno di questi»: si mette da parte la bottiglia per capirla dopo.

        È la sola cosa che il dispositivo non può risolvere da solo — un OCR che
        legge male, un vino che non c'è nel database, un'etichetta con un
        carattere che il modello non conosce — e senza questo bottone quel caso
        sparisce: l'ospite tocca a caso o aspetta, e chi deve correggere non
        sa nemmeno che è successo.

        Si salva quello che serve a rifare il caso a tavolino: **lo scatto vero**
        e le righe che l'OCR ne ha tirato fuori. Un rapporto senza l'immagine
        vale poco: si saprebbe che ha sbagliato, non perché.
        """
        from datetime import datetime

        quando = datetime.now()
        nome = quando.strftime("%Y%m%d-%H%M%S")
        cartella = CARTELLA_SEGNALAZIONI / nome
        rapporto = {
            "quando": quando.isoformat(timespec="seconds"),
            "lingua": self.lingua,
            "righe_lette": list(getattr(self, "_righe", [])),
            "livello": self._fatti.livello.value,
            "sicurezza": round(self._fatti.sicurezza),
            "proposte": list(self._candidati),
            "immagine": None,
        }
        try:
            cartella.mkdir(parents=True, exist_ok=True)
            scatto = getattr(self, "_ultimo_scatto", None)
            if scatto is not None:
                import cv2
                percorso = cartella / "bottiglia.jpg"
                if cv2.imwrite(str(percorso), scatto):
                    rapporto["immagine"] = percorso.name
            (cartella / "segnalazione.json").write_text(
                json.dumps(rapporto, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as e:
            log.warning("segnalazione non salvata: %s", e)
            return {"ok": False}

        log.info("segnalata una bottiglia non riconosciuta in %s", cartella)
        # Il tavolo non deve restare fermo su una schermata di scelta: si
        # racconta comunque il piu' generico che si sa dire, che e' meglio di
        # niente, e la segnalazione resta li' per chi la guardera'.
        self.macchina.invia(Evento.CANDIDATO_SCELTO)
        return {"ok": True, "cartella": nome}

    def scegli(self, indice: int) -> None:
        """L'ospite ha toccato uno dei candidati."""
        self._adotta_candidato(indice)
        self.macchina.invia(Evento.CANDIDATO_SCELTO)

    def _adotta_candidato(self, indice: int) -> bool:
        """Prende per buono il candidato numero `indice`, se c'e'.

        Si compone il record TOCCATO. Rifare la ricerca sul suo nome sarebbe
        un secondo tiro di dadi: la stringa normalizzata di un candidato puo'
        somigliare piu' a un altro record che a se stessa, e l'ospite si
        vedrebbe raccontare un vino diverso da quello che ha scelto.
        """
        rif = self._fatti.riferimenti
        if not 0 <= indice < len(rif):
            return False
        annata = self._fatti.annata
        self._fatti = self.matcher.fatti_di(*rif[indice])
        self._fatti.annata = annata         # l'annata viene dall'etichetta
        return True

    def _genera(self, prompt: str) -> str:
        from .llm import Modello
        if not hasattr(self, "_modello"):
            self._modello = Modello()
        return self._modello.genera(prompt)

    # ------------------------------------------------------------ ciclo

    async def sorveglia(self) -> None:
        """Legge il sensore e fa scadere i timer. È il battito del dispositivo."""
        # Il modello si accende solo se il modo salvato lo vuole: all'avvio
        # nessun servizio lo tira su piu', ci pensa questo.
        self._accendi_il_modello(self.modo == "generativa")
        self.batteria.avvia()
        if self.camera is not None:
            try:
                blocca_esposizione(self.camera.imp, self.camera.percorso)
            except Exception as e:                          # noqa: BLE001
                log.warning("esposizione non bloccata: %s", e)
            sfondo = self._sfondo_ricordato()
            if sfondo is not None:
                self.presenza.ricorda(sfondo)
                self._sfondo_scritto = sfondo
            # E SEMPRE si guarda una volta, anche con uno sfondo in mano.
            #
            # Lo sfondo ricordato dice com'era il piatto l'ultima volta che il
            # dispositivo ha creduto fosse vuoto, e quella convinzione puo'
            # essere sbagliata: basta che la bottiglia sia arrivata mentre lo
            # imparava. Succede, e visto sul dispositivo: lo sfondo salvato
            # conteneva una bottiglia, quindi il piatto sembrava vuoto con la
            # bottiglia sopra, quindi nessuna scansione partiva - e senza
            # scansione non partiva nemmeno la via di scampo, che sta in fondo
            # alla scansione. Cieco fino a che qualcuno non toglieva la
            # bottiglia.
            #
            # Costa un'accensione dell'anello e una lettura per avvio. In
            # cambio, all'accensione il dispositivo sa sempre cosa ha davanti,
            # qualunque cosa dica il file. Ed e' anche l'unico collaudo
            # automatico che questo dispositivo fa di se stesso.
            self._da_capire = True

        while True:
            try:
                await self._un_battito()
            except Exception:                               # noqa: BLE001
                # Il battito del dispositivo non puo' morire per nessun motivo:
                # se muore, nessuna bottiglia viene piu' vista, per sempre.
                log.exception("errore nel ciclo di sorveglianza")
            await asyncio.sleep(self.cfg.periodo_sensore_s)

    async def _un_battito(self) -> None:
        """Un giro solo: sbirciata, presenza, timer. Isolato per poterlo provare."""
        if self.mirino is not None and self.mirino.acceso:
            # Col mirino acceso il dispositivo guarda, non racconta: la camera
            # e' sua, e far scadere un timer qui vorrebbe dire far partire una
            # scansione contro uno stream che qualcun altro sta leggendo.
            return
        c_era = self.presenza.presente
        ora = await self._chi_c_e()
        if ora != c_era:
            if ora:
                self._tentativi = 0     # bottiglia nuova, si riparte da capo
                # Lo scatto dovra' essere di DOPO questo istante: un fotogramma
                # di prima mostra il piatto vuoto, o una mano che scende.
                self._apparsa = time.monotonic()
            else:
                # Tolta la bottiglia, la prossima e' un'altra storia.
                self._bottiglia_chiusa = False
            self.macchina.invia(
                Evento.BOTTIGLIA_PRESENTE if ora else Evento.BOTTIGLIA_ASSENTE)
        elif (ora and self.macchina.stato is Stato.ATTESA
                and not self._bottiglia_chiusa
                and self._tentativi < TENTATIVI_MAX):
            # La bottiglia c'e' ma siamo tornati in attesa: succede dopo un
            # guasto. NON dopo un racconto finito - quello ci torna apposta, e
            # rilanciare li' vorrebbe dire raccontare lo stesso vino all'infinito
            # finche' qualcuno non toglie la bottiglia. Il fronte di salita non si ripresenta mai piu', e senza
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

    async def _chi_c_e(self) -> bool:
        """Dice se c'e' una bottiglia, e intanto guarda dov'e'.

        Chi decide e' il sensore di distanza, a ogni battito: sei millesimi, e
        tre letture d'accordo bastano. La camera continua a guardare al suo
        passo — mezzo secondo — ma non per decidere: per sapere DOVE sta
        l'etichetta e per restare pronta a decidere lei, se il sensore tace.
        """
        if self._bottiglia_finta is not None:
            return self.presenza.aggiorna_a_mano(self._bottiglia_finta)
        deciso = self._lo_dice_il_sensore()
        await self._guarda_il_piatto(deciso)
        return deciso if deciso is not None else self.presenza.presente

    def _lo_dice_il_sensore(self) -> bool | None:
        """La presenza secondo il Modulino Distance, quando lui puo' saperla.

        Il sensore e' autorevole su cio' che ha VISTO ARRIVARE, e su niente
        altro. Misurato sul dispositivo: un Brunello, fondo scuro e opaco, si
        legge a 20 mm; un Cerasuolo, vetro chiaro e vino rosato, da' la stessa
        firma del piatto vuoto - `distanza 0, stato 5` - perche' l'infrarosso
        attraversa il fondo trasparente e non torna. Per il sensore quella
        bottiglia non esiste, e non esiste nemmeno la sua assenza.

        Quindi tre risposte, non due. `True`: vede qualcosa, e vale come
        innesco, che e' il motivo per cui e' tornato. `False`: aveva visto
        qualcosa e non lo vede piu', cioe' una bottiglia opaca e' stata tolta -
        e questo interrompe il racconto anche se la camera non se n'e' ancora
        accorta. `None`: non ha mai visto niente, e allora **non sa**: decide
        la camera, che il vetro chiaro lo vede benissimo.

        Un Modulino scollegato o un firmware vecchio danno `None` per sempre,
        e costano una scansione piu' lenta, non un dispositivo cieco.
        """
        try:
            mm = self.ponte.distanza_mm()
        except (PonteNonDisponibile, ErroreMCU):
            mm = None
        vedeva = self.distanza.presente
        vede = self.distanza.aggiorna(mm)
        if vede:
            return True
        if vedeva:
            # L'ha vista andare via: e' l'unica assenza che puo' dichiarare.
            return False
        return None

    async def _guarda_il_piatto(self, secondo_il_sensore: bool | None = None) -> None:
        """La sbirciata: non decide piu' niente, ma serve ancora a due cose.

        Il riquadro dell'etichetta, che dipende dalla forma della bottiglia, e
        lo sfondo del piatto vuoto, che e' il ripiego quando il sensore tace.
        """
        if self.camera is None:
            return
        if self._va_sorvegliata():
            # Si richiama a ogni giro apposta: e' un no-op se gira gia', e
            # rimette in moto lo stream dopo il racconto, che lo spegne.
            self.camera.sorveglia()
        ora = time.monotonic()
        if ora < self._prossima_sbirciata:
            return
        self._prossima_sbirciata = ora + self.cfg.periodo_sbirciata_s
        # In un thread: col guardiano acceso la sbirciata e' gia' li' e costa
        # la conversione in grigio, ma senza sono novanta millesimi di camera,
        # e fermerebbero anche le pagine che il tablet sta caricando.
        fascia = await asyncio.to_thread(self.camera.sbircia)
        if fascia is None:
            # La camera sta scattando, o non ha dato il fotogramma. Una
            # sbirciata saltata non e' un'informazione: non si decide niente.
            return
        if self._da_capire:
            self._da_capire = False
            # Si dichiara che qualcosa c'e', anche se non si sa cosa: senza,
            # la sbirciata successiva - mezzo secondo dopo, a scansione gia'
            # avviata - imparerebbe come «piatto vuoto» proprio la bottiglia
            # che si sta per fotografare, e la salverebbe pure.
            self.presenza.c_e_qualcosa()
            return
        if secondo_il_sensore is False and self.macchina.stato is Stato.ATTESA:
            # Il sensore dice che sul piatto non c'e' niente, e lo dice meglio
            # di quanto possa dirlo la camera: quello che si vede ORA e' il
            # piatto vuoto, per definizione. Non c'e' niente da dedurre.
            #
            # Non e' pulizia, e' la cura di un guasto vero. Lo sfondo che il
            # rivelatore ottico teneva era stato imparato CON UNA BOTTIGLIA
            # DAVANTI: da allora la differenza restava a zero, il riquadro
            # dell'etichetta non si trovava piu', e all'OCR arrivava il
            # ritaglio fisso con dentro mezza stanza. Misurato sul
            # dispositivo: tredici regioni di testo invece di cinque, e la
            # rilevazione da 274 a 750 millesimi - perche' la
            # post-elaborazione del rilevatore costa per regione trovata, e le
            # regioni di troppo sono il calendario appeso dietro il piatto.
            #
            # Prima questa correzione esisteva, ma arrivava solo dopo tre
            # scansioni fallite di fila: era una via di scampo. Adesso e' la
            # regola, e il caso che la faceva servire non si presenta piu'.
            self.presenza.non_e_una_bottiglia(fascia)
            self.camera.riquadro = None
            self._ricorda_sfondo()
            return
        c_e = self.presenza.aggiorna(fascia)
        # Dove sta la bottiglia, per darlo all'OCR al posto di un riquadro
        # fisso. `None` vuol dire «non si sa», e allora si torna al fisso.
        self.camera.riquadro = self.presenza.riquadro()
        if not c_e and self.macchina.stato is Stato.ATTESA:
            # Lo sfondo si impara solo da fermi. Durante una scansione il
            # rivelatore vede una scena che il dispositivo sta gia' guardando
            # per conto suo, e prenderla per sfondo vuol dire dimenticare la
            # bottiglia che ha davanti.
            self._ricorda_sfondo()

    def _va_sorvegliata(self) -> bool:
        """Lo stream si tiene in moto solo quando serve a qualcosa.

        Non durante il racconto: col DisplayPort attivo il link USB scende a
        2.0 e camera e audio si dividono un bus solo. E' la stessa ragione per
        cui la camera si chiude prima di parlare, e vale anche per il
        guardiano - anzi vale di piu', perche' lui legge senza sosta.
        """
        return self.macchina.stato in (
            Stato.ATTESA, Stato.ASSESTAMENTO, Stato.SCANSIONE,
            Stato.RIPOSIZIONA,
        ) and not (self.mirino is not None and self.mirino.acceso)

    async def salute(self) -> None:
        while True:
            # La stima della batteria avanza a questo passo: venti secondi
            # bastano a integrare la potenza, e la scrittura su disco con
            # fsync ogni venti secondi non consuma la eMMC in nessun tempo
            # ragionevole.
            try:
                self.batteria.aggiorna(
                    voce_accesa=self.macchina.stato is Stato.RACCONTO)
                self.batteria.salva()
            except Exception:                               # noqa: BLE001
                log.exception("stima della batteria")
            self._pubblica({"tipo": "salute", "tutto_bene": self._tutto_bene(),
                            "voce_muta": not self._voce_disponibile(),
                            "batteria": self._batteria_a_schermo()})
            await asyncio.sleep(20)

    def _batteria_a_schermo(self) -> dict[str, Any]:
        return {"tacche": self.batteria.tacche,
                "frazione": round(self.batteria.frazione, 3)}

    def batteria_ricaricata(self) -> dict[str, Any]:
        """Qualcuno ha ricaricato il power bank e lo dice dalle impostazioni."""
        self.batteria.ricaricata()
        log.info("batteria: dichiarata ricaricata")
        self._pubblica({"tipo": "salute", "tutto_bene": self._tutto_bene(),
                        "voce_muta": not self._voce_disponibile(),
                        "batteria": self._batteria_a_schermo()})
        return {"ok": True, **self._batteria_a_schermo()}

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
            # Lo stream della camera resta acceso fra una sbirciata e l'altra:
            # se il servizio si ferma senza spegnerlo, il device resta occupato
            # fino a che il kernel non se ne accorge, e il riavvio successivo
            # trova una camera che non si apre.
            if amelie.camera is not None:
                amelie.camera.chiudi()

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
                amelie._manda_impostazioni()
                amelie._manda_mirino()
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

    @app.post("/annulla")
    async def annulla():
        # `async def`, come tutte le altre: FastAPI manderebbe una `def` in un
        # thread del pool, e `Macchina.invia` non ha lucchetti. Correrebbe
        # contro il battito del sensore, che gira sul loop - cioe' contro la
        # scadenza dei dodici secondi della conferma.
        return JSONResponse(amelie.annulla())

    @app.post("/segnala")
    async def segnala():
        return JSONResponse(amelie.segnala())

    @app.post("/scegli/{indice}")
    async def scegli(indice: int):
        amelie.scegli(indice)
        return JSONResponse({"ok": True})

    @app.post("/racconto/{azione}")
    async def racconto(azione: str):
        return JSONResponse(amelie.comanda_racconto(azione))

    @app.post("/batteria/ricaricata")
    async def batteria_ricaricata():
        return JSONResponse(amelie.batteria_ricaricata())

    @app.get("/batteria")
    async def batteria():
        b = amelie.batteria
        return JSONResponse({**amelie._batteria_a_schermo(),
                             "consumato_wh": round(b.consumato_wh, 2),
                             "capacita_wh": b.capacita,
                             "ore_rimaste_stimate": round(b.ore_rimaste, 1)})

    @app.post("/lingua/{codice}")
    async def lingua(codice: str):
        cambiata = amelie.cambia_lingua(codice)
        return JSONResponse({"ok": cambiata, "lingua": amelie.lingua})

    @app.post("/volume/{valore}")
    async def volume(valore: int):
        return JSONResponse({"ok": True, "valore": amelie.imposta_volume(valore),
                             "passo": PASSO_VOLUME})

    @app.post("/generati/{acceso}")
    async def generati(acceso: int):
        return JSONResponse(amelie.imposta_generati(bool(acceso)))

    @app.post("/modo/{nome}")
    async def modo(nome: str):
        return JSONResponse(amelie.imposta_modo(nome))

    @app.post("/mirino/{acceso}")
    async def mirino(acceso: int):
        return JSONResponse(amelie.imposta_mirino(bool(acceso)))

    @app.get("/mirino/lettura")
    async def mirino_lettura():
        vista = amelie.mirino
        if vista is None or not vista.acceso:
            return JSONResponse({"stato": "mirino spento"})
        return JSONResponse({**vista.esito,
                             "nitidezza": round(vista.nitidezza),
                             "posa": amelie.camera.imp.esposizione
                             if amelie.camera else None})

    @app.get("/mirino/flusso")
    async def mirino_flusso():
        """Il video, in multipart. Un fotogramma per volta, l'ultimo pronto.

        Non è una coda: chi si collega prende quello che c'è adesso, e se
        arriva tardi salta i fotogrammi vecchi invece di rincorrerli. È quello
        che serve a un mirino, dove guardare indietro non ha senso.
        """
        async def fotogrammi():
            ultimo = None
            while True:
                vista = amelie.mirino
                if vista is None or not vista.acceso:
                    return
                jpg = vista.ultimo()
                if jpg is not None and jpg is not ultimo:
                    ultimo = jpg
                    yield (b"--fotogramma\r\nContent-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(jpg)).encode()
                           + b"\r\n\r\n" + jpg + b"\r\n")
                await asyncio.sleep(0.05)

        return StreamingResponse(
            fotogrammi(),
            media_type="multipart/x-mixed-replace; boundary=fotogramma",
            headers={"Cache-Control": "no-store"})

    @app.get("/giornale")
    async def giornale(quante: int = 20):
        """Le ultime scansioni: cosa ha letto, cosa ha concluso, cosa ha detto.

        È il modo di capire perché una bottiglia non è stata riconosciuta
        quando nessuno era lì a guardare. Ogni voce porta il nome del suo
        fotogramma, che si scarica da `/giornale/<nome>`.
        """
        return JSONResponse({"voci": amelie.giornale.ultime(
            max(1, min(200, quante)))})

    @app.get("/giornale/{nome}")
    async def giornale_immagine(nome: str):
        percorso = amelie.giornale.immagine(nome)
        if percorso is None:
            return JSONResponse({"ok": False, "motivo": "non c'è"},
                                status_code=404)
        return FileResponse(percorso, media_type="image/jpeg")

    @app.post("/prova/{cosa}")
    async def prova(cosa: str):
        """Il banco: fa credere al dispositivo che ci sia una bottiglia.

        Serve a provare tutto il resto — lettura, riconoscimento, racconto,
        voce, schermo, comandi — su una macchina che la camera non ce l'ha, o
        davanti a una camera che in quel momento non guarda il piatto.

        Non manda l'evento a mano: dichiara che cosa c'è sul piatto e lascia
        che sia il battito normale a passarlo per l'isteresi. Così si prova il
        percorso vero, filtro compreso, e non una scorciatoia che gli somiglia.

        Tre parole, perché «non c'è una bottiglia» e «guarda tu» sono due cose
        diverse: con il sensore erano la stessa, perché una distanza finta tolta
        lasciava il posto a un sensore che diceva «lontano».

            bottiglia   sul piatto c'è una bottiglia
            via         il piatto è vuoto
            camera      basta con le bugie, si torna a guardare
        """
        finte = {"bottiglia": True, "via": False, "camera": None}
        if cosa not in finte:
            return JSONResponse({"ok": False,
                                 "motivo": "prova: 'bottiglia', 'via' o 'camera'"})
        amelie._bottiglia_finta = finte[cosa]
        return JSONResponse({"ok": True, "finta": amelie._bottiglia_finta,
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
            # Il piatto, come lo vede la camera. Sono i tre numeri con cui si
            # verifica il riconoscimento della bottiglia SENZA smontare niente:
            # si guarda `differenza` a piatto vuoto (deve stare sotto l'uno per
            # cento), poi ci si appoggia una bottiglia e si riguarda (deve
            # saltare oltre la soglia). Senza questi, l'unico modo di sapere
            # perche' il dispositivo non parte e' leggere il giornale di bordo
            # da un'altra macchina.
            "bottiglia": amelie.presenza.presente,
            "differenza": round(amelie.presenza.differenza * 100, 1),
            "soglia": round(amelie.presenza.soglia_arrivo * 100, 1),
            "posa": amelie.camera.imp.esposizione if amelie.camera else None,
            "voce": bool(amelie.voce and amelie.voce.disponibile),
            "volume": amelie.volume,
            "modo": amelie.modo,
            "carta": (amelie.carta.percorso.name if amelie.carta else None),
            "voci_in_carta": (len(amelie.carta.voci) if amelie.carta else 0),
            "racconti_generati": amelie.genera_racconti,
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
    ap.add_argument("--modello-addestrato", action="store_true",
                    help="il modello caricato e' quello affinato su questo "
                         "progetto: vuole il prompt compatto")
    ap.add_argument("--con-modello", action="store_true",
                    help="rende scegliibile il modo «generativa», in cui il modello "
                         "scrive il racconto (lento e di qualita' incerta: vedi "
                         "docs/04-QUALITA.md)")
    ap.add_argument("--carta", metavar="FILE.csv",
                    help="una carta dei vini al posto dell'archivio: un CSV "
                         "con le colonne «titolo» e «descrizione». E' una "
                         "prova, e si spegne togliendo l'opzione")
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
        modello_addestrato=args.modello_addestrato,
        device_audio=args.audio, porta=args.porta, volume=args.volume,
        carta=args.carta)

    import uvicorn
    # Il tetto sullo spegnimento e' una rete di sicurezza, non la soluzione:
    # quella e' svegliare i flussi di eventi (vedi ciclo_di_vita). Ma se un
    # domani qualcosa restasse appeso, meglio cinque secondi che il minuto e
    # mezzo che systemd concede prima di uccidere.
    uvicorn.run(crea_app(Amelie(cfg)), host="127.0.0.1", port=args.porta,
                log_level="warning", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
