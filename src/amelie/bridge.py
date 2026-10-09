"""Il ponte verso il microcontrollore.

Il connettore Qwiic della UNO Q è cablato sull'**I²C4 dello STM32U585**, non del
processore Linux. I Modulino — il Pixels che fa da luce e il sensore di
distanza — li vede quindi solo l'MCU, e Linux ci parla attraverso il router.

L'MCU legge il sensore di continuo e tiene pronta l'ultima misura; Linux la
chiede a ogni battito (vedi `Configurazione.periodo_sensore_s` in
`amelie.app`), e una chiamata risponde in pochi millesimi.

## Il protocollo

`/run/arduino-router.sock`, MessagePack-RPC standard. Verificato sul campo: una
richiesta `[0, msgid, metodo, parametri]` riceve `[1, msgid, errore, risultato]`.
I metodi disponibili sono quelli che lo sketch dichiara con `Bridge.provide()`.

## La trappola

Chiamare `Bridge.call()` **dentro** un gestore registrato con `provide()` manda
in stallo il canale: è documentato da Arduino. Per questo la macchina a stati di
Amelie vive su Linux e l'MCU si limita a eseguire e a notificare — i gestori
dello sketch non chiamano mai il ponte, mettono solo una bandiera che il
`loop()` applica.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

SOCKET = "/run/arduino-router.sock"

# Indirizzi I2C dei Modulino, in forma a 7 bit. Un solo Pixels, quindi
# l'indirizzo di fabbrica va bene com'è e non c'è niente da riprogrammare prima
# di montare.
ANELLO = 0x36     # il Pixels nella torre, che illumina l'etichetta
DISTANZA = 0x29   # VL53L4CD, indirizzo fisso

# L'ordine è quello dei bit che lo sketch somma in `moduli()`: 1, 2.
NOMI_MODULI = ("anello", "distanza")

# La versione del PROTOCOLLO, non del firmware: si alza quando cambia il
# significato di qualcosa, per esempio dei bit di `moduli()`.
#
# Serve perché un cambiamento del genere è **silenzioso e rovesciato**: un
# Linux e un MCU con due versioni diverse leggerebbero gli stessi bit con due
# significati, e un sensore collegato risulterebbe assente. È il guasto
# peggiore che si possa avere montando — il montaggio è giusto e il dispositivo
# dice di no — e senza questo numero non c'è modo di accorgersene.
PROTOCOLLO_ATTESO = 3


@dataclass(frozen=True)
class Colore:
    r: int = 0
    g: int = 0
    b: int = 0
    luminosita: int = 25       # 0-100

    def __post_init__(self) -> None:
        for v in (self.r, self.g, self.b):
            if not 0 <= v <= 255:
                raise ValueError(f"componente fuori scala: {v}")
        if not 0 <= self.luminosita <= 100:
            raise ValueError(f"luminosità fuori scala: {self.luminosita}")

    @property
    def esadecimale(self) -> int:
        """Il colore in un intero 0xRRGGBB, come lo vuole `set_luce`."""
        return (self.r << 16) | (self.g << 8) | self.b


@dataclass(frozen=True)
class Luce:
    """Gli otto LED dell'anello: i pari di un colore, i dispari di un altro.

    La luminosità è una sola, perché il modulo ne ha una per scrittura: i due
    colori devono dichiarare la stessa.
    """
    pari: Colore
    dispari: Colore

    def __post_init__(self) -> None:
        if self.pari.luminosita != self.dispari.luminosita:
            raise ValueError(
                "i due colori di una luce vogliono la stessa luminosità: "
                f"{self.pari.luminosita} e {self.dispari.luminosita}")


# La luce di Amelie: i LED pari bianchi e i dispari gialli, al massimo, in ogni
# stato in cui il dispositivo lavora; rossa per un guasto, e a riposo quando la
# batteria è quasi scarica. È l'unica luce del dispositivo, e illumina
# l'etichetta: la stessa in attesa e durante la raffica, perché la posa che la
# camera trova a riposo valga anche per lo scatto.
#
# Gli otto LED si alimentano dal cavetto Qwiic, a 3,3 V, sullo stesso bus del
# sensore di distanza: se la tensione cedesse, cadrebbe anche il sensore, e il
# guasto sembrerebbe dei moduli. Misurato: due minuti con tutti gli otto LED
# bianchi al massimo - più del bianco e giallo alternati - e il sensore ha
# risposto 1124 volte su 1124, i moduli sempre visti.
#
# Il conto si paga in batteria: vedi `POTENZA_BASE_W` in `amelie.batteria`.
BIANCO = Colore(255, 255, 255, 100)
GIALLO = Colore(255, 200, 0, 100)
ROSSO = Colore(255, 30, 10, 100)
SPENTO = Colore(0, 0, 0, 0)

LUCE = Luce(BIANCO, GIALLO)
LUCE_ROSSA = Luce(ROSSO, ROSSO)
LUCE_SPENTA = Luce(SPENTO, SPENTO)


class Ponte:
    """Client MessagePack-RPC del router, su una connessione sola.

    La connessione si apre alla prima chiamata e resta aperta. Il router scrive
    due righe nel giornale di sistema per ogni connessione, e il sensore si
    interroga a ogni battito: con una connessione per chiamata sono decine di
    righe al secondo, e il giornale - che sulla board tiene 50 MB - si riempie
    in un giorno e cancella tutto il resto.

    Le chiamate passano una per volta, perche' le risposte arrivano sullo
    stesso canale. Se il router si riavvia la connessione cade: la chiamata se
    ne accorge, si riconnette e riprova una volta. Si puo' riprovare perche'
    ogni metodo dello sketch si puo' ripetere senza danni: legge, oppure
    imposta un valore.
    """

    def __init__(self, percorso: str = SOCKET, timeout: float = 5.0) -> None:
        self.percorso = percorso
        self.timeout = timeout
        self._msgid = 0
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._unpacker: Any = None

    @property
    def disponibile(self) -> bool:
        """C'e' un MCU che risponde E che sa fare quello che gli si chiede.

        Non basta che il socket del router esista: il router c'e' anche quando
        sull'MCU non gira lo sketch di Amelie, e in quel caso ogni chiamata
        fallisce con "method not available". Controllando solo il socket, un
        dispositivo che non puo' ne' leggere il sensore ne' accendere l'anello
        dichiarerebbe `mcu: true` - ed e' esattamente lo stato in cui si trova
        una board appena preparata, prima di caricare il firmware.
        """
        try:
            # Si chiede la distanza perche' e' il metodo piu' innocuo che lo
            # sketch di Amelie espone: non cambia niente sull'MCU, e se
            # risponde lo sketch c'e'.
            self.chiama("distanza")
        except ErroreMCU:
            log.warning("il router risponde ma lo sketch di Amelie non c'e': "
                        "carica firmware/amelie_mcu")
            return False
        except (PonteNonDisponibile, OSError):
            return False
        return True

    def chiama(self, metodo: str, *parametri: Any) -> Any:
        """Invoca un metodo esposto dallo sketch. Solleva se l'MCU risponde male."""
        try:
            import msgpack
        except ImportError as e:  # pragma: no cover
            raise PonteNonDisponibile("manca il pacchetto 'msgpack'") from e

        with self._lock:
            self._msgid = (self._msgid + 1) % 0xFFFF
            msgid = self._msgid
            richiesta = msgpack.packb([0, msgid, metodo, list(parametri)],
                                      use_bin_type=True)
            for tentativo in (1, 2):
                try:
                    if self._sock is None:
                        self._connetti(msgpack)
                    try:
                        self._sock.sendall(richiesta)
                    except (BrokenPipeError, ConnectionResetError) as e:
                        raise _ConnessioneCaduta(str(e)) from e
                    return self._risposta(metodo, msgid)
                except _ConnessioneCaduta as e:
                    # Il router si e' riavviato, o ha chiuso: si riapre e si
                    # riprova una volta sola.
                    self._chiudi()
                    if tentativo == 2:
                        raise PonteNonDisponibile(f"{metodo}: {e}") from e
                except (socket.timeout, TimeoutError) as e:
                    # Nessuna risposta in tempo: non si riprova - si
                    # aspetterebbe di nuovo altrettanto - ma si riparte da una
                    # connessione pulita, senza la risposta in ritardo.
                    self._chiudi()
                    raise PonteNonDisponibile(f"{metodo}: nessuna risposta") from e
                except OSError as e:
                    self._chiudi()
                    raise PonteNonDisponibile(f"{metodo}: {e}") from e
        raise PonteNonDisponibile(f"{metodo}: nessuna risposta")  # pragma: no cover

    def chiudi(self) -> None:
        """Chiude la connessione col router. La prossima chiamata la riapre."""
        with self._lock:
            self._chiudi()

    def _connetti(self, msgpack: Any) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.percorso)
        except OSError:
            s.close()
            raise
        self._sock = s
        self._unpacker = msgpack.Unpacker(raw=False)

    def _chiudi(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._unpacker = None

    def _risposta(self, metodo: str, msgid: int) -> Any:
        """Legge finche' arriva la risposta a `msgid`.

        Le risposte con un altro numero sono di chiamate andate in tempo
        scaduto, arrivate tardi: si scartano.
        """
        scadenza = time.monotonic() + self.timeout
        while True:
            for msg in self._unpacker:
                if not isinstance(msg, list) or len(msg) < 4:
                    continue
                if msg[0] == 1 and msg[1] == msgid:
                    if msg[2] is not None:
                        raise ErroreMCU(f"{metodo}: {msg[2]}")
                    return msg[3]
            resto = scadenza - time.monotonic()
            if resto <= 0:
                raise TimeoutError("nessuna risposta")
            self._sock.settimeout(resto)
            try:
                dati = self._sock.recv(4096)
            except (ConnectionResetError, BrokenPipeError) as e:
                raise _ConnessioneCaduta(str(e)) from e
            if not dati:
                raise _ConnessioneCaduta("il router ha chiuso la connessione")
            self._unpacker.feed(dati)

    # ------------------------------------------------------------- comandi

    def anello(self, c: Colore) -> None:
        """Tutti gli otto LED dello stesso colore."""
        self.chiama("set_anello", c.r, c.g, c.b, c.luminosita)

    def luce(self, luce: Luce) -> None:
        """I LED pari di un colore e i dispari di un altro."""
        self.chiama("set_luce", luce.pari.esadecimale, luce.dispari.esadecimale,
                    luce.pari.luminosita)

    def versione(self) -> int | None:
        """La versione del protocollo dichiarata dall'MCU, o None se non la dice.

        `None` significa un firmware che non dichiara il protocollo, e i cui
        bit di `moduli()` non si possono interpretare (vedi `PROTOCOLLO_ATTESO`).
        """
        try:
            return int(self.chiama("versione"))
        except (ErroreMCU, PonteNonDisponibile, OSError, TypeError, ValueError):
            return None

    def scansiona(self) -> list[int] | None:
        """Ogni indirizzo che risponde sul bus Qwiic, in ordine.

        `moduli()` dice se ci sono i due che il dispositivo si aspetta; questo
        dice **che cosa c'è davvero**, ed è la domanda che viene dopo. Un modulo
        scambiato, uno a un indirizzo inatteso e nessun modulo sono tre guasti
        diversi che da fuori si somigliano — e distinguerli guardando due schede
        blu quasi identiche è il modo più rapido di sbagliarsi.

        `None` se il firmware non lo sa fare.
        """
        trovati: list[int] = []
        for blocco in range(4):
            try:
                maschera = int(self.chiama("scansiona", blocco))
            except (ErroreMCU, PonteNonDisponibile, OSError, TypeError, ValueError):
                return None
            for i in range(32):
                if maschera & (1 << i):
                    trovati.append(blocco * 32 + i)
        return trovati

    def nomi_noti(self, indirizzi: Iterable[int]) -> dict[int, str]:
        """Che cos'è ciascun indirizzo, per chi ha i cavetti in mano.

        I Modulino sono schede quasi identiche: stesso blu, stessa forma, stessi
        due connettori, e a distinguerli c'è solo il componente al centro e una
        piccola icona serigrafata. Sbagliare scheda è facile, e il sintomo —
        «non fa niente» — è lo stesso di un guasto.

        Qui si nominano solo gli indirizzi di cui si è certi. Tutto il resto è
        «un altro Modulino», senza inventarsi quale: dire il nome sbagliato
        sarebbe peggio che non dirlo.
        """
        noti = {ANELLO: "Modulino Pixels — la luce del dispositivo",
                DISTANZA: "Modulino Distance — il sensore che vede arrivare "
                          "la bottiglia",
                0x6C: "indirizzo «Modulino» di un Pixels: lo sketch usa 0x36"}
        return {a: noti.get(a, "un altro Modulino — non serve a questo "
                               "dispositivo, toglilo dalla catena")
                for a in indirizzi}

    def moduli(self) -> dict[str, bool]:
        """Quali Modulino il microcontrollore vede in questo momento.

        Serve a montare: si chiede al dispositivo se vede i moduli, invece di
        dedurlo da un LED che non si accende. Il firmware li cerca solo
        all'accensione del microcontrollore, quindi un modulo collegato dopo
        risulta assente fino alla prossima accensione.

        Non solleva mai. Chi chiede questo sta cercando un guasto, e un firmware
        che non conosce il metodo è uno dei guasti possibili: rispondere
        «non vedo niente» lo racconta meglio di un'eccezione.

        E **prima chiede la versione**. I bit di `moduli()` non significano la
        stessa cosa in tutte le versioni del protocollo: interpretarli senza
        sapere con chi si sta parlando vuol dire dire il contrario del vero
        proprio a chi sta montando. Meglio «non lo so» che una risposta
        rovesciata.
        """
        return self._moduli_secondo(self.versione())

    def diagnosi(self) -> dict[str, Any]:
        """Versione e moduli in una volta sola.

        La pagina di stato le vuole tutte e due, e chiederle separatamente
        significherebbe interrogare l'MCU tre volte invece di due: ogni chiamata
        aspetta il suo turno sulla connessione, e la pagina di stato si guarda
        proprio quando qualcosa non risponde.
        """
        v = self.versione()
        return {"protocollo": v, "moduli": self._moduli_secondo(v)}

    def _moduli_secondo(self, v_mcu: int | None) -> dict[str, bool]:
        if v_mcu != PROTOCOLLO_ATTESO:
            log.warning(
                "l'MCU parla il protocollo %s, qui si aspetta il %d: i bit dei "
                "moduli avrebbero un altro significato. Ricarica "
                "firmware/amelie_mcu prima di fidarti di questa risposta.",
                "1 o precedente" if v_mcu is None else v_mcu, PROTOCOLLO_ATTESO)
            return dict.fromkeys(NOMI_MODULI, False)
        try:
            v = int(self.chiama("moduli"))
        except (ErroreMCU, PonteNonDisponibile, OSError, TypeError, ValueError):
            return dict.fromkeys(NOMI_MODULI, False)
        return {nome: bool(v & (1 << i)) for i, nome in enumerate(NOMI_MODULI)}

    def stato_sensore(self) -> int | None:
        """Dove si è fermato l'avvio del sensore sull'MCU.

        0 riuscito, -1 mai tentato, e da 2 a 6 il passo che non è andato: il
        chip che non finisce di avviarsi, la configurazione, la calibrazione, i
        tempi di misura, l'avvio della misura continua. `None` se il firmware
        non lo sa dire.

        Senza questo, un sensore che non parte dice soltanto «non ci sono», e
        per sapere perché bisognerebbe ricaricare il firmware con delle stampe
        dentro.
        """
        try:
            return int(self.chiama("stato_tof"))
        except (ErroreMCU, PonteNonDisponibile, OSError, TypeError, ValueError):
            return None

    # I registri che `registro_tof` sa mostrare, nell'ordine in cui li chiede.
    REGISTRI_TOF = ("misura pronta", "stato della misura", "SPAD attivi",
                    "distanza mm", "polarita' interrupt", "piedino interrupt")

    def registri_sensore(self) -> dict[str, int] | None:
        """I registri grezzi del sensore, per quando la distanza non torna.

        `distanza_mm()` dice quanti millimetri; quando quel numero e' assurdo —
        zero fisso, per esempio — non dice **perche'**. Questi sono i numeri che
        il sensore risponde davvero.
        """
        fuori: dict[str, int] = {}
        for i, nome in enumerate(self.REGISTRI_TOF):
            try:
                fuori[nome] = int(self.chiama("registro_tof", i))
            except (ErroreMCU, PonteNonDisponibile, OSError, TypeError, ValueError):
                return None
        return fuori

    def distanza_mm(self) -> int | None:
        """Distanza letta dal sensore, o None se la misura non è valida.

        `available()` della libreria Modulino ritorna falso quando lo stato
        della misura non è buono, e quel «non so» è già un ottimo segnale di
        «non c'è niente sopra».
        """
        v = self.chiama("distanza")
        return None if v is None or v < 0 else int(v)


class PonteSimulato(Ponte):
    """Sostituto per sviluppare senza hardware.

    Registra i comandi invece di inviarli, così l'orchestratore e l'interfaccia
    si collaudano su un portatile. La distanza si pilota da fuori.
    """

    def __init__(self) -> None:  # noqa: D107
        self.comandi: list[tuple] = []
        self.distanza_finta: int | None = None

    @property
    def disponibile(self) -> bool:
        return True

    def chiudi(self) -> None:
        pass

    def chiama(self, metodo: str, *parametri: Any) -> Any:
        self.comandi.append((metodo, parametri))
        if metodo == "distanza":
            return -1 if self.distanza_finta is None else self.distanza_finta
        if metodo == "moduli":
            # Un banco simulato ha tutto collegato: senza questo `True` varrebbe
            # 1, cioè «vedo solo l'anello», e la simulazione racconterebbe un
            # guasto che non c'è.
            return (1 << len(NOMI_MODULI)) - 1
        if metodo == "versione":
            return PROTOCOLLO_ATTESO
        if metodo == "scansiona":
            blocco = parametri[0] if parametri else 0
            maschera = 0
            for a in (ANELLO, DISTANZA):
                if blocco * 32 <= a < (blocco + 1) * 32:
                    maschera |= 1 << (a - blocco * 32)
            return maschera
        return True


class Presenza:
    """Decide se c'è una bottiglia dal sensore di distanza.

    Affianca la camera invece di sostituirla, e fa da innesco: guardare costa
    secondi — una lettura dell'etichetta, il riquadro, la sagoma — e il
    sensore risponde in millesimi. Per far comparire il testo in
    meno di un secondo da quando la bottiglia si appoggia, l'innesco deve
    costare quasi niente, e questo è il solo pezzo che lo sa fare.

    Il fondo di una bottiglia è quasi speculare: se non è centrato, il lobo
    riflesso esce dal cono di ricezione e la misura salta. Per questo la
    decisione non si prende su una lettura sola.

    L'isteresi è **asimmetrica** di proposito: bastano poche letture vicine per
    dire che è arrivata, ne servono molte lontane per dire che è andata via.
    Sbagliare in un senso fa partire una scansione di troppo; sbagliare
    nell'altro interrompe un racconto a metà, che si nota molto di più.
    """

    def __init__(
        self,
        vicino_mm: int = 100,
        lontano_mm: int = 140,
        letture_per_arrivare: int = 3,
        letture_per_andarsene: int = 5,
    ) -> None:
        self.vicino, self.lontano = vicino_mm, lontano_mm
        self.n_arrivo, self.n_uscita = letture_per_arrivare, letture_per_andarsene
        self.presente = False
        self._vicine = 0
        self._lontane = 0

    def aggiorna(self, mm: int | None) -> bool:
        """Aggiunge una lettura e restituisce se ora la bottiglia c'è."""
        if mm is not None and mm < self.vicino:
            self._vicine += 1
            self._lontane = 0
        elif mm is None or mm > self.lontano:
            self._lontane += 1
            self._vicine = 0
        # Fra vicino e lontano non si cambia idea: è la zona morta che evita il
        # tremolio quando la bottiglia è appoggiata sul bordo della soglia.

        if not self.presente and self._vicine >= self.n_arrivo:
            self.presente = True
        elif self.presente and self._lontane >= self.n_uscita:
            self.presente = False
        return self.presente

    def reimposta(self) -> None:
        self.presente = False
        self._vicine = self._lontane = 0


class PonteNonDisponibile(RuntimeError):
    """Il router non risponde: l'MCU non è raggiungibile."""


class _ConnessioneCaduta(Exception):
    """La connessione col router si è chiusa: si riapre e si riprova."""


class ErroreMCU(RuntimeError):
    """L'MCU ha risposto con un errore."""
