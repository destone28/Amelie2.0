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

import hashlib
import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger(__name__)

VOCE_PREDEFINITA = "it_IT-serena-medium"

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
    device_alsa: str = "hw:0,3"
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

    def _aplay(self) -> subprocess.Popen:
        if not shutil.which("aplay"):
            raise VoceNonDisponibile("aplay non è installato (pacchetto alsa-utils)")
        return subprocess.Popen(
            ["aplay", "-D", self.imp.device_alsa, "-t", "raw", "-f", "S16_LE",
             "-r", str(self.imp.frequenza), "-c", "1", "-q", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def parla(self, frasi: Iterable[str]) -> None:
        """Riproduce un flusso di frasi, cominciando dalla prima.

        `aplay` resta aperto per tutta la durata: riaprirlo a ogni frase
        introdurrebbe un buco di silenzio e uno schiocco fra una e l'altra.
        """
        proc = self._aplay()
        try:
            for frase in frasi:
                pcm = self.sintetizza(frase)
                if not pcm:
                    continue
                try:
                    proc.stdin.write(pcm)
                    proc.stdin.flush()
                except BrokenPipeError:
                    log.warning("riproduzione interrotta")
                    break
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()

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
        """
        subprocess.run(["pkill", "-f", f"aplay.*{self.imp.device_alsa}"],
                       capture_output=True)


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
