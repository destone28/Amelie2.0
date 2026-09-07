"""La voce.

Piper sintetizza **una frase alla volta**, e questo cambia tutto: si può
cominciare a parlare appena la prima frase è pronta, mentre il modello sta
ancora scrivendo la seconda. Su questa board sono venti secondi di silenzio
risparmiati — la differenza fra un dispositivo che risponde e uno che sembra
bloccato.

## La voce scelta

`it_IT-serena-medium`, e la ragione è di licenza, non di gusto. La più diffusa
`it_IT-paola-medium` dichiara nella sua scheda ufficiale di essere un
*finetuning* della voce inglese `lessac`, il cui dataset — Blizzard Challenge
2013 — vieta esplicitamente *«any commercial purpose, including the development,
marketing, commercialisation, sale or licencing of voice synthesis products»*.
Il dispositivo può essere usato in un locale. `serena` è addestrata da zero su dataset
CC BY 4.0, ha la stessa architettura e lo stesso costo di calcolo — i due file
ONNX differiscono di un byte — e chiede solo una riga di attribuzione.

## La pronuncia

Il motore fonetico se la cava benissimo con l'italiano, ma inciampa esattamente
dove un dispositivo sul vino non può permetterselo: le sigle e i nomi stranieri.
«DOCG» letto come parola è imbarazzante. Il dizionario qui sotto riscrive il
testo **prima** della sintesi: è più affidabile di qualunque markup, perché
agisce su ciò che il motore legge davvero.
"""

from __future__ import annotations

import bisect
import hashlib
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger(__name__)

VOCE_PREDEFINITA = "it_IT-serena-medium"

# Il PCM e' lineare: un secondo di parlato sono sempre gli stessi byte. E' cio'
# che rende possibile un player vero - saltare avanti di cinque secondi e'
# aritmetica su un offset, non una ricerca dentro un formato compresso.
def byte_al_secondo(frequenza: int = 22050) -> int:
    return frequenza * 2          # 16 bit, un canale


# Quanto si scrive ad aplay per volta. Cento millisecondi: abbastanza piccolo
# perche' una pausa si senta subito, abbastanza grande da non costare nulla.
PEZZO_S = 0.1
# Il buffer che si lascia ad ALSA. Piu' e' grande, piu' il suono sopravvive a un
# picco di carico - e questa board ha quattro core contesi da OCR e sintesi - ma
# piu' la posizione dichiarata corre avanti a quella che l'orecchio sente. Due
# decimi sono il compromesso: impercettibile, e regge l'OCR in parallelo.
BUFFER_ALSA_US = 200_000

# Il DSP di questa board non comincia a rendere il suono nell'istante in cui si
# apre il flusso, e `aplay` esce PRIMA che l'ultimo pezzo sia uscito davvero.
# Misurato qui: su ogni durata, dai tre secondi al secondo scarso, aplay
# impiega 0,35 s in meno del dovuto. Su nove secondi di racconto non si nota;
# su una frase da un secondo se ne mangia i due terzi e resta un rumorino - che
# e' esattamente come e' stato descritto la prima volta che si e' provato
# l'annuncio della lingua in cuffia.
#
# Il rimedio NON e' imbottire di silenzio: e' non chiudere mai il flusso. Vedi
# `Uscita`. Questi margini restano solo per chi suona un file da fuori.
MARGINE_APERTURA_S = 0.6
MARGINE_CHIUSURA_S = 0.5


def silenzio(secondi: float, frequenza: int = 22050) -> bytes:
    return b"\x00\x00" * int(frequenza * secondi)


class Uscita:
    """Un flusso audio che si apre una volta sola e non si chiude mai.

    Il DSP di questa board impiega **circa due secondi** a cominciare a rendere
    il suono dopo l'apertura del flusso. Non e' una stima: si sono fatti
    ascoltare sei bip a un secondo l'uno dall'altro, e se ne sono sentiti
    quattro. Aprire e chiudere `aplay` a ogni frase significa pagare quei due
    secondi ogni volta - e una frase da un secondo sparisce del tutto, ne resta
    l'ultima sillaba.

    Allungare le frasi sarebbe un cerotto: i primi due secondi del racconto
    verrebbero mangiati lo stesso, e sono quelli che dicono che vino e'.

    Qui il flusso resta aperto: quando non c'e' niente da dire si versa
    silenzio, che costa quarantaquattro kilobyte al secondo e nessun problema.
    Il prezzo si paga una volta all'accensione, dove non lo sente nessuno.
    """

    # Quanto si tiene in pancia prima di far aspettare chi scrive. Serve a due
    # cose: che il suono non si interrompa se il sistema e' occupato, e che chi
    # scrive non corra troppo avanti - altrimenti la posizione dichiarata dal
    # player scappa avanti a quella che l'orecchio sente.
    RISERVA_S = 0.3
    PEZZO_S = 0.08

    def __init__(self, voce: "Voce") -> None:
        self.voce = voce
        self._bps = byte_al_secondo(voce.imp.frequenza)
        self._coda = bytearray()
        self._stato = threading.Lock()
        self._spazio = threading.Condition(self._stato)
        self._fermo = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._filo: threading.Thread | None = None

    @property
    def aperta(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def avvia(self) -> None:
        if self.aperta:
            return
        self._fermo.clear()
        self._proc = self.voce.apri_uscita()
        self._filo = threading.Thread(target=self._versa, daemon=True)
        self._filo.start()
        log.info("uscita audio aperta e tenuta aperta")

    def scrivi(self, pcm: bytes) -> None:
        """Accoda del suono. Aspetta se la riserva e' gia' piena."""
        if not pcm:
            return
        soglia = int(self.RISERVA_S * self._bps)
        with self._spazio:
            while len(self._coda) > soglia and not self._fermo.is_set():
                self._spazio.wait(0.1)
            self._coda.extend(pcm)

    def svuota(self) -> None:
        """Butta via cio' che non e' ancora uscito. E' il "taci adesso"."""
        with self._spazio:
            self._coda.clear()
            self._spazio.notify_all()

    def in_pancia_s(self) -> float:
        with self._stato:
            return len(self._coda) / self._bps

    def chiudi(self) -> None:
        self._fermo.set()
        with self._spazio:
            self._spazio.notify_all()
        if self._filo is not None:
            self._filo.join(timeout=3)
        with self._stato:
            proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:                               # noqa: BLE001
                pass
            try:
                proc.kill(); proc.wait(timeout=2)
            except Exception:                               # noqa: BLE001
                pass

    def _versa(self) -> None:
        pezzo = int(self.PEZZO_S * self._bps)
        muto = silenzio(self.PEZZO_S, self.voce.imp.frequenza)
        while not self._fermo.is_set():
            with self._spazio:
                dati = bytes(self._coda[:pezzo])
                del self._coda[:len(dati)]
                self._spazio.notify_all()
                proc = self._proc
            if proc is None:
                return
            try:
                # Silenzio quando non c'e' niente da dire: e' cio' che tiene
                # sveglio il DSP e fa parlare tutto il resto all'istante.
                proc.stdin.write(dati or muto)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                log.warning("uscita audio chiusa sotto di noi")
                return

# Una voce per lingua. La scelta e' di LICENZA prima che di gusto: vedi la nota
# in testa al modulo per l'italiano, e docs/ATTRIBUZIONI.md per l'inglese.
# Se per una lingua non c'e' voce, il dispositivo mostra il testo e tace: e'
# meglio del sentire un motore italiano leggere l'inglese.
VOCI = {
    "it": "it_IT-serena-medium",
    # Addestrata DA ZERO sul dataset LJ Speech, di pubblico dominio. La scelta
    # e' la stessa dell'italiano e per la stessa ragione: le voci inglesi piu'
    # diffuse di Piper - `lessac` e tutte quelle rifinite a partire da lei,
    # `alba` e `libritts_r` comprese - poggiano sul dataset Blizzard Challenge
    # 2013, che vieta esplicitamente l'uso commerciale. Qui l'uso puo' essere
    # commerciale, quindi non basta che la scheda dica CC BY: bisogna guardare
    # anche da CHE COSA e' stata rifinita.
    "en": "en_US-ljspeech-medium",
}
CARTELLA_CACHE = Path.home() / ".cache" / "amelie" / "voce"


# --------------------------------------------------------------- pronuncia

# Sostituzioni applicate al testo prima della sintesi. La chiave è
# un'espressione regolare con i confini di parola già inclusi.
PRONUNCIA: dict[str, str] = {
    # Sigle: lette come parole diventano incomprensibili.
    r"\bD\.?O\.?C\.?G\.?\b": "denominazione di origine controllata e garantita",
    r"\bD\.?O\.?C\.?\b": "denominazione di origine controllata",
    r"\bI\.?G\.?T\.?\b": "indicazione geografica tipica",
    r"\bI\.?G\.?P\.?\b": "indicazione geografica protetta",
    r"\bD\.?O\.?P\.?\b": "denominazione di origine protetta",
    r"\bV\.?S\.?Q\.?\b": "vino spumante di qualità",
    # Nomi stranieri ricorrenti nel mondo del vino.
    r"\bCh[âa]teauneuf[- ]du[- ]Pape\b": "sciatonèf du pap",
    r"\bCh[âa]teau\b": "sciatò",
    r"\bGew[üu]rztraminer\b": "ghevürtstraminer",
    r"\bSauvignon\b": "sovignòn",
    r"\bCabernet\b": "cabernè",
    r"\bMerlot\b": "merlò",
    r"\bPinot\b": "pinò",
    r"\bSyrah\b": "sirà",
    r"\bShiraz\b": "sciràz",
    r"\bChardonnay\b": "sciardonè",
    r"\bRiesling\b": "rìsling",
    r"\bMüller[- ]Thurgau\b": "müller turgau",
    r"\bBrut\b": "brut",
    r"\bCuv[ée]e\b": "cüvè",
    # Unità e simboli.
    r"(\d+)\s*°C\b": r"\1 gradi",
    r"(\d+)\s*%": r"\1 per cento",
    r"\bcl\b": "centilitri",
    r"\bml\b": "millilitri",
}

_COMPILATE = [(re.compile(k, re.I), v) for k, v in PRONUNCIA.items()]


def per_la_voce(testo: str) -> str:
    """Riscrive il testo come va pronunciato.

    >>> per_la_voce("Un Barolo DOCG al 14%.")
    'Un Barolo denominazione di origine controllata e garantita al 14 per cento.'
    """
    for pattern, sostituto in _COMPILATE:
        testo = pattern.sub(sostituto, testo)
    # Il trattino fra numeri si legge "meno": va sciolto.
    testo = re.sub(r"(\d)\s*-\s*(\d)", r"\1 e \2", testo)
    return re.sub(r"\s+", " ", testo).strip()


# ------------------------------------------------------------------- voce

@dataclass(frozen=True)
class ImpostazioniVoce:
    modello: str = VOCE_PREDEFINITA
    # Dove suonare. Sulla UNO Q l'HDMI e' il PCM 3 della scheda del SoC: non
    # esiste un device che si chiami "HDMI", e' il backend di MultiMedia4.
    # plughw, non hw: il device HDMI accetta SOLO 32000-48000 Hz e uno o due
    # canali, mentre Piper produce 22050 mono. Con `hw:` ogni riproduzione
    # falliva con "Unable to install hw params", e il primo sintomo era che non
    # si sentiva niente. `plughw` mette in mezzo la conversione di ALSA, che su
    # questa board costa una frazione di punto percentuale di CPU.
    device_alsa: str = "plughw:0,3"
    # Due thread su quattro: gli altri due servono al modello linguistico, che
    # su questa board e' sempre il collo di bottiglia.
    thread: int = 2
    frequenza: int = 22050
    usa_cache: bool = True


class Voce:
    """Sintetizza e riproduce. Il modello si carica una volta sola.

    Caricare Piper costa alcuni secondi: se lo si facesse a ogni bottiglia,
    quei secondi si sommerebbero all'attesa proprio nel momento peggiore.
    """

    def __init__(self, impostazioni: ImpostazioniVoce | None = None) -> None:
        self.imp = impostazioni or ImpostazioniVoce()
        # Le voci caricate, per nome di modello. Si tengono TUTTE: caricarne una
        # costa quindici secondi su questa board, e un ospite che tocca la
        # bandierina non puo' restare quindici secondi in silenzio a chiedersi
        # se ha rotto qualcosa. Sono sessanta megabyte l'una, su tre giga e
        # mezzo: si pagano una volta e non si ripagano piu'.
        self._voci: dict[str, object] = {}
        self._lock = threading.Lock()
        # Falso quando la lingua a schermo non ha una voce: il racconto si legge
        # ma non si sente. Meglio del silenzio inspiegato, e molto meglio di un
        # motore italiano che prova a leggere l'inglese.
        self.disponibile_per_lingua = True
        # Il flusso verso lo schermo si apre una volta e resta aperto: vedi
        # `Uscita` per il perche'.
        self._uscita: Uscita | None = None
        self.cache = CARTELLA_CACHE
        self.cache.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- motore

    def _carica(self, modello: str | None = None):
        nome = modello or self.imp.modello
        if (gia := self._voci.get(nome)) is not None:
            return gia
        with self._lock:
            if (gia := self._voci.get(nome)) is not None:
                return gia
            try:
                from piper import PiperVoice
            except ImportError as e:  # pragma: no cover
                raise VoceNonDisponibile(
                    "il pacchetto 'piper-tts' non è installato"
                ) from e
            percorso = self._percorso_modello(nome)
            log.info("carico la voce %s", percorso)
            self._voci[nome] = PiperVoice.load(str(percorso))
            return self._voci[nome]

    def uscita(self) -> "Uscita":
        """Il flusso sempre aperto. Si apre alla prima richiesta."""
        with self._lock:
            if self._uscita is None:
                self._uscita = Uscita(self)
        if not self._uscita.aperta:
            self._uscita.avvia()
        return self._uscita

    def scalda(self, lingue: Iterable[str] = ()) -> None:
        """Carica in anticipo le voci delle lingue indicate.

        Va chiamata all'avvio, fuori dal percorso dell'ospite: quindici secondi
        mentre nessuno guarda non li vede nessuno, gli stessi quindici secondi
        dopo un tocco sono un guasto.
        """
        for lingua in (lingue or VOCI):
            modello = VOCI.get(lingua)
            if not modello:
                continue
            try:
                self._carica(modello)
            except VoceNonDisponibile as e:
                log.warning("voce %s non caricata: %s", modello, e)

    def _percorso_modello(self, modello: str | None = None) -> Path:
        nome = modello or self.imp.modello
        for base in (Path.home() / ".local" / "share" / "piper" / "voices",
                     Path.home() / "amelie" / "models",
                     Path("/usr/share/piper-voices")):
            p = base / f"{nome}.onnx"
            if p.exists():
                return p
        raise VoceNonDisponibile(
            f"modello {nome}.onnx non trovato. "
            f"Scaricalo con scripts/fetch_voce.sh"
        )

    @property
    def disponibile(self) -> bool:
        try:
            self._percorso_modello()
            return True
        except VoceNonDisponibile:
            return False

    # --------------------------------------------------------------- cache

    def _chiave(self, frase: str) -> Path:
        h = hashlib.sha256(f"{self.imp.modello}|{frase}".encode()).hexdigest()[:20]
        return self.cache / f"{h}.raw"

    # ------------------------------------------------------------ sintesi

    def sintetizza(self, frase: str) -> bytes:
        """PCM grezzo a 16 bit per una frase. Usa la cache se può.

        Un ristorante ha poche decine di etichette: alla seconda bottiglia
        uguale la voce parte istantaneamente.
        """
        frase = per_la_voce(frase)
        if not frase:
            return b""
        percorso = self._chiave(frase)
        if self.imp.usa_cache and percorso.exists():
            return percorso.read_bytes()

        voce = self._carica()
        pezzi = [c.audio_int16_bytes for c in voce.synthesize(frase)]
        pcm = b"".join(pezzi)
        if self.imp.usa_cache and pcm:
            # Scrittura atomica: un file di cache troncato da un'interruzione
            # verrebbe riletto come audio valido e produrrebbe un crepitio.
            tmp = percorso.with_suffix(".parziale")
            tmp.write_bytes(pcm)
            tmp.replace(percorso)
        return pcm

    def apri_uscita(self) -> subprocess.Popen:
        """Un aplay pronto a ricevere PCM grezzo sullo standard input.

        Il buffer ALSA e' tenuto corto di proposito: e' la distanza fra cio' che
        il dispositivo dice di star riproducendo e cio' che l'orecchio sente, e
        quando c'e' un pulsante di pausa quella distanza si nota.
        """
        if not shutil.which("aplay"):
            raise VoceNonDisponibile("aplay non è installato (pacchetto alsa-utils)")
        return subprocess.Popen(
            ["aplay", "-D", self.imp.device_alsa, "-t", "raw", "-f", "S16_LE",
             "-r", str(self.imp.frequenza), "-c", "1", "-q",
             "--buffer-time", str(BUFFER_ALSA_US), "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    # Il nome vecchio, per chi lo usava.
    _aplay = apri_uscita

    def parla(self, frasi: Iterable[str]) -> None:
        """Pronuncia un flusso di frasi e aspetta che siano uscite davvero.

        Versa nel flusso sempre aperto: non si apre e non si chiude niente, e
        quindi non si pagano i due secondi che il DSP impiega ad avviarsi.
        """
        uscita = self.uscita()
        for frase in frasi:
            pcm = self.sintetizza(frase)
            if pcm:
                uscita.scrivi(pcm)
        # Si aspetta che la pancia si svuoti, altrimenti chi ha chiamato crede
        # di aver finito mentre l'ultima parola non e' ancora uscita.
        scadenza = time.monotonic() + 60
        while uscita.in_pancia_s() > 0.01 and time.monotonic() < scadenza:
            time.sleep(0.05)
        time.sleep(BUFFER_ALSA_US / 1_000_000)

    def per_lingua(self, codice: str) -> bool:
        """Passa alla voce di quella lingua, se ce n'e' una.

        Restituisce False quando la lingua non ha voce: chi chiama lo sa e puo'
        dirlo a schermo, invece di far leggere l'inglese a un motore italiano -
        che non e' un accento, e' incomprensibile.
        """
        nuovo = VOCI.get(codice)
        if not nuovo:
            log.info("nessuna voce per %r: il racconto resta scritto", codice)
            self.disponibile_per_lingua = False
            return False
        self.disponibile_per_lingua = True
        if nuovo == self.imp.modello:
            return True
        with self._lock:
            # ImpostazioniVoce e' congelato di proposito - e' configurazione,
            # non stato - quindi se ne costruisce uno nuovo invece di mutarlo.
            self.imp = replace(self.imp, modello=nuovo)
        log.info("voce: %s", nuovo)
        return True

    def zittisci(self) -> None:
        """Interrompe qualunque riproduzione in corso.

        Serve quando si toglie la bottiglia mentre il dispositivo parla: deve
        smettere subito, non finire la frase su un tavolo vuoto.

        Si butta via cio' che non e' ancora uscito, e il flusso resta APERTO:
        chiuderlo costerebbe altri due secondi alla prossima parola.
        """
        if self._uscita is not None:
            self._uscita.svuota()

    def chiudi(self) -> None:
        if self._uscita is not None:
            self._uscita.chiudi()
            self._uscita = None


class VoceNonDisponibile(RuntimeError):
    """Il motore o il modello vocale non ci sono."""


def prepara_cache(voce: Voce, frasi: Iterable[str]) -> int:
    """Pre-sintetizza le frasi fisse: attese, errori, inviti.

    Sono poche e sempre uguali, e pre-generarle toglie l'unico caso in cui il
    dispositivo tace proprio quando dovrebbe rassicurare.
    """
    n = 0
    for f in frasi:
        try:
            if voce.sintetizza(f):
                n += 1
        except VoceNonDisponibile:
            break
    return n


# Le frasi che il dispositivo dice sempre uguali.
FRASI_FISSE = (
    "Un attimo, sto leggendo l'etichetta.",
    "Non riesco a leggere questa etichetta. Prova a girarla verso di me.",
    "Fammi guardare meglio.",
)


# --------------------------------------------------------------- riproduzione


class Riproduttore:
    """Un racconto che si puo' governare: pausa, salto, ricomincia da capo.

    Il problema che risolve non e' far uscire il suono - per quello bastava
    `Voce.parla` - ma sapere SEMPRE a che punto si e'. Prima il testo a schermo
    avanzava a stima, con un `sleep` proporzionale alla lunghezza della frase,
    mentre la voce andava per conto suo: finche' si va dritti la finzione
    regge, ma al primo tocco di pausa le due cose divergono e non si
    riallineano piu'.

    Qui c'e' una sola verita', la POSIZIONE in byte dentro il buffer, e tutto
    si ricava da quella: i secondi trascorsi, la frase da evidenziare, dove
    ripartire dopo una pausa.

    La sintesi corre avanti in un thread suo, perche' la prima frase deve
    poter suonare dopo due secondi come prima, senza aspettare tutto il testo.
    Su questa board la sintesi va a circa il doppio del tempo reale (RTF 0,54),
    quindi dopo la prima frase resta comodamente in vantaggio sulla lettura.
    """

    def __init__(self, voce: "Voce", frasi: list[str], *,
                 su_avanzamento=None, passo_s: float = 5.0) -> None:
        self.voce = voce
        self.frasi = [f for f in frasi if f and f.strip()]
        self.su_avanzamento = su_avanzamento
        self.passo_s = passo_s

        self._bps = byte_al_secondo(voce.imp.frequenza)
        self._pcm = bytearray()
        # Offset in byte a cui comincia ogni frase: e' quello che permette di
        # dire QUALE frase si sta ascoltando, invece di indovinarlo.
        self._inizi: list[int] = []
        self._posizione = 0
        self._in_pausa = False
        self._completo = False
        self._errore: Exception | None = None

        # Il flusso e' quello sempre aperto della voce: non se ne apre uno
        # proprio, perche' aprirlo costa i due secondi di avvio del DSP - e
        # dopo ogni pausa e ogni salto si pagherebbero di nuovo.
        self._uscita = voce.uscita()
        self._stato = threading.Lock()
        self._sveglia = threading.Condition(self._stato)
        self._fermo = threading.Event()
        self._finito = threading.Event()
        self._thread: list[threading.Thread] = []

    # ------------------------------------------------------------ lettura

    @property
    def posizione_s(self) -> float:
        return self._posizione / self._bps

    @property
    def durata_s(self) -> float:
        """Quanto c'e' GIA' sintetizzato. Cresce mentre si ascolta."""
        return len(self._pcm) / self._bps

    @property
    def in_pausa(self) -> bool:
        return self._in_pausa

    @property
    def completo(self) -> bool:
        return self._completo

    @property
    def indice_frase(self) -> int:
        """L'ultima frase cominciata prima della posizione attuale."""
        i = bisect.bisect_right(self._inizi, self._posizione) - 1
        return max(0, i)

    def istantanea(self) -> dict:
        return {"posizione": round(self.posizione_s, 2),
                "durata": round(self.durata_s, 2),
                "frase": self.indice_frase,
                "in_pausa": self._in_pausa,
                "completo": self._completo}

    # ------------------------------------------------------------ comandi

    def avvia(self) -> None:
        for bersaglio in (self._sintetizza_tutto, self._suona):
            t = threading.Thread(target=bersaglio, daemon=True)
            t.start()
            self._thread.append(t)

    def pausa(self) -> None:
        # Quello che era gia' stato consegnato ma non ancora sentito va
        # riascoltato: riprendere piu' avanti taglierebbe una parola.
        indietro = self._uscita.in_pancia_s() + BUFFER_ALSA_US / 1_000_000
        with self._sveglia:
            if self._in_pausa:
                return
            self._in_pausa = True
            self._posizione = max(0, self._posizione - int(self._bps * indietro))
            self._taci()
            self._sveglia.notify_all()
        self._avvisa()

    def riprendi(self) -> None:
        with self._sveglia:
            if not self._in_pausa:
                return
            self._in_pausa = False
            self._sveglia.notify_all()
        self._avvisa()

    def alterna(self) -> bool:
        """Il tocco sul pulsante centrale. Restituisce True se ora e' in pausa."""
        if self._in_pausa:
            self.riprendi()
        else:
            self.pausa()
        return self._in_pausa

    def salta(self, secondi: float) -> None:
        """Avanti o indietro. Il limite in avanti e' cio' che e' gia' sintetizzato.

        Non e' un difetto ma un fatto: non si puo' saltare dentro un audio che
        non esiste ancora. Con la sintesi al doppio del tempo reale il caso si
        presenta solo nei primissimi secondi.
        """
        with self._sveglia:
            nuovo = self._posizione + int(secondi * self._bps)
            self._posizione = max(0, min(nuovo, len(self._pcm)))
            self._taci()                  # si butta cio' che non e' ancora uscito
            self._sveglia.notify_all()
        self._avvisa()

    def ricomincia(self) -> None:
        with self._sveglia:
            self._posizione = 0
            self._in_pausa = False
            self._taci()
            self._sveglia.notify_all()
        self._avvisa()

    def ferma(self) -> None:
        """Basta, e subito: la bottiglia e' stata tolta dal tavolo."""
        self._fermo.set()
        with self._sveglia:
            self._taci()
            self._sveglia.notify_all()

    def attendi(self, timeout: float | None = None) -> bool:
        """True se il racconto e' arrivato in fondo, False se l'hanno fermato."""
        self._finito.wait(timeout)
        return self._finito.is_set() and not self._fermo.is_set()

    # ------------------------------------------------------------ interni

    def _avvisa(self) -> None:
        if self.su_avanzamento is None:
            return
        try:
            self.su_avanzamento(self.istantanea())
        except Exception:                                   # noqa: BLE001
            log.exception("errore nell'avviso di avanzamento")

    def _taci(self) -> None:
        """Butta via cio' che e' stato consegnato ma non ancora sentito.

        Il flusso NON si chiude: chiuderlo costerebbe due secondi alla
        riapertura, e la ripresa dopo una pausa sarebbe muta per metа.
        """
        self._uscita.svuota()

    def _sintetizza_tutto(self) -> None:
        try:
            for frase in self.frasi:
                if self._fermo.is_set():
                    return
                pcm = self.voce.sintetizza(frase)
                with self._sveglia:
                    self._inizi.append(len(self._pcm))
                    self._pcm.extend(pcm)
                    self._sveglia.notify_all()
        except Exception as e:                              # noqa: BLE001
            log.warning("sintesi interrotta: %s", e)
            self._errore = e
        finally:
            with self._sveglia:
                self._completo = True
                self._sveglia.notify_all()

    def _suona(self) -> None:
        pezzo = int(PEZZO_S * self._bps)
        try:
            while not self._fermo.is_set():
                with self._sveglia:
                    # Si aspetta di avere qualcosa da suonare e il permesso di
                    # farlo. Il timeout tiene vivo l'avviso di avanzamento anche
                    # mentre si e' in pausa.
                    while (not self._fermo.is_set()
                           and (self._in_pausa
                                or self._posizione >= len(self._pcm))):
                        if (not self._in_pausa and self._completo
                                and self._posizione >= len(self._pcm)):
                            return                     # arrivati in fondo
                        self._sveglia.wait(0.25)
                    if self._fermo.is_set():
                        return
                    inizio = self._posizione
                    dati = bytes(self._pcm[inizio:inizio + pezzo])

                if not dati:
                    continue
                # Scrivere BLOCCA quando la riserva e' piena, ed e' quello che
                # tiene il passo: non serve un orologio, lo detta ALSA.
                self._uscita.scrivi(dati)
                with self._sveglia:
                    if self._in_pausa or self._fermo.is_set():
                        # Il permesso e' stato tolto mentre si scriveva: si
                        # butta via quel pezzo invece di farlo uscire dopo.
                        self._uscita.svuota()
                        continue
                    if self._posizione == inizio:
                        self._posizione = inizio + len(dati)
                self._avvisa()
        finally:
            self._finito.set()
            self._avvisa()
