"""Il ponte verso il microcontrollore.

Il connettore Qwiic della UNO Q è cablato sull'**I²C4 dello STM32U585**, non del
processore Linux. I Modulino — i due anelli di LED e il sensore di distanza —
li vede quindi solo l'MCU, e Linux ci parla attraverso il router.

Questa divisione non è un fastidio: è ciò che permette al dispositivo di stare
in attesa a consumo bassissimo. L'MCU fa la guardia sul sensore e sveglia Linux
solo quando qualcuno appoggia una bottiglia.

## Il protocollo

`/run/arduino-router.sock`, MessagePack-RPC standard. Verificato sul campo: una
richiesta `[0, msgid, metodo, parametri]` riceve `[1, msgid, errore, risultato]`.
I metodi disponibili sono quelli che lo sketch dichiara con `Bridge.provide()`.

## La trappola

Chiamare `Bridge.call()` **dentro** un gestore registrato con `provide()` manda
in stallo il canale: è documentato da Arduino. Per questo la macchina a stati di
Amelie vive su Linux e l'MCU si limita a eseguire e a notificare — gli handler
qui sotto non richiamano mai l'MCU, mettono solo una bandiera.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

SOCKET = "/run/arduino-router.sock"

# Indirizzi I2C dei Modulino, in forma a 7 bit. I due Pixels nascono entrambi
# a 0x36: il secondo va riprogrammato una volta con lo sketch AddressChanger
# della libreria Arduino_Modulino, e l'indirizzo resta in memoria.
ANELLO = 0x36     # l'anello sotto la bottiglia
FLASH = 0x37      # l'illuminatore per la camera, riprogrammato
DISTANZA = 0x29   # VL53L4CD, indirizzo fisso


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


# I due Pixels insieme, a piena luminosità, assorbirebbero oltre mezzo ampere
# sul rail 3,3 V passando dai cavetti Qwiic da 28 AWG. L'anello resta basso in
# permanenza; il flash sale solo per la frazione di secondo dello scatto.
AMBRA = Colore(255, 150, 40, 22)      # attesa: caldo, discreto
BIANCO_FLASH = Colore(255, 255, 255, 90)
VERDE = Colore(60, 220, 90, 30)
ROSSO = Colore(230, 60, 40, 30)
SPENTO = Colore(0, 0, 0, 0)


class Ponte:
    """Client MessagePack-RPC del router.

    Ogni chiamata apre e chiude la connessione: il traffico è di poche decine
    di byte a bottiglia e una connessione persistente aggiungerebbe solo stati
    da gestire quando l'MCU si riavvia.
    """

    def __init__(self, percorso: str = SOCKET, timeout: float = 5.0) -> None:
        self.percorso = percorso
        self.timeout = timeout
        self._msgid = 0
        self._lock = threading.Lock()

    @property
    def disponibile(self) -> bool:
        """C'e' un MCU che risponde E che sa fare quello che gli si chiede.

        Non basta che il socket del router esista: il router c'e' anche quando
        sull'MCU non gira lo sketch di Amelie, e in quel caso ogni chiamata
        fallisce con "method not available". Controllare solo il socket faceva
        dichiarare `mcu: true` a un dispositivo che non poteva ne' leggere il
        sensore ne' accendere l'anello - ed e' esattamente lo stato in cui si
        trova una board appena preparata, prima di caricare il firmware.
        """
        try:
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

        richiesta = msgpack.packb([0, msgid, metodo, list(parametri)], use_bin_type=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.percorso)
            s.sendall(richiesta)
            unpacker = msgpack.Unpacker(raw=False)
            scadenza = time.monotonic() + self.timeout
            while time.monotonic() < scadenza:
                dati = s.recv(4096)
                if not dati:
                    break
                unpacker.feed(dati)
                for msg in unpacker:
                    if not isinstance(msg, list) or len(msg) < 4:
                        continue
                    if msg[0] == 1 and msg[1] == msgid:
                        if msg[2] is not None:
                            raise ErroreMCU(f"{metodo}: {msg[2]}")
                        return msg[3]
            raise PonteNonDisponibile(f"{metodo}: nessuna risposta")
        except OSError as e:
            raise PonteNonDisponibile(f"{metodo}: {e}") from e
        finally:
            s.close()

    # ------------------------------------------------------------- comandi

    def anello(self, c: Colore) -> None:
        self.chiama("set_anello", c.r, c.g, c.b, c.luminosita)

    def flash(self, c: Colore) -> None:
        self.chiama("set_flash", c.r, c.g, c.b, c.luminosita)

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

    def chiama(self, metodo: str, *parametri: Any) -> Any:
        self.comandi.append((metodo, parametri))
        if metodo == "distanza":
            return -1 if self.distanza_finta is None else self.distanza_finta
        return True


class Presenza:
    """Decide se c'è una bottiglia, filtrando il sensore.

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
        vicino_mm: int = 40,
        lontano_mm: int = 70,
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


class ErroreMCU(RuntimeError):
    """L'MCU ha risposto con un errore."""
