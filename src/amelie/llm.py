"""Il modello linguistico locale, via llama-server.

Gira come servizio residente su 127.0.0.1, non come processo lanciato a ogni
bottiglia: caricare un modello da qualche centinaio di megabyte costa secondi
che l'ospite pagherebbe in attesa.

## Il numero che decide tutto

Sui quattro Cortex-A53 della board il collo di bottiglia e' il prefill, la
lettura del prompt: e' piu' lento della generazione, e un prompt lungo costa
decine di secondi prima di produrre una parola. Per questo:

1. le istruzioni fisse stanno **all'inizio** del prompt e i fatti in fondo, così
   `--cache-reuse` riconosce il prefisso già elaborato e non lo rilegge;
2. il testo si genera **in streaming**, per far partire la voce sulla prima
   frase invece che alla fine;
3. e soprattutto, la strada predefinita non è questa: il modo «archivio»
   compone il racconto dai fatti (vedi `amelie.narrator`), e il modello
   scrive solo nel modo «generativa», sperimentale.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImpostazioniLLM:
    url: str = "http://127.0.0.1:8081"
    max_token: int = 120
    # Misurato su trenta vini, stesso modello, tre temperature:
    #
    #     0,7   18 su 30 passano la verifica   1,2 parole fuori dai fatti a testo
    #     0,2   20 su 30                       0,7
    #     0     19 su 30                       0,8
    #
    # Un modello da mezzo miliardo non ha varieta' da spendere: a 0,7 le
    # parole in piu' sono quasi tutte invenzioni. Lo zero secco non e' meglio
    # di 0,2 e ripete di piu'.
    temperatura: float = 0.2
    # Sopra 0.9 il modello comincia a divagare e la verifica anti-invenzione
    # scarta troppo spesso, costringendo a rigenerare: si perde piu' tempo di
    # quanto se ne guadagni in varieta'.
    top_p: float = 0.9
    # «con bella acidita' e bella acidita'», «delicato, delicato»: il modello
    # che gira a vuoto. Una penalita' leggera sulle ripetizioni costa niente e
    # toglie il caso piu' frequente; sopra 1,2 comincia a evitare anche le
    # parole giuste, tipo il nome del vitigno detto due volte.
    ripetizione: float = 1.1
    # Le sequenze su cui fermarsi: il modello tende a continuare con un secondo
    # paragrafo o a commentare quello che ha scritto.
    stop: tuple[str, ...] = (
        "\n\n", "FATTI:", "Racconto:", "Descrizione:",
        # Il modello, finito il paragrafo, tende a proseguire con un blocco di
        # codice o con una nota su cio' che ha scritto.
        "```", "Nota:", "(Nota", "---",
    )
    timeout_s: float = 180.0


class Modello:
    """Client di llama-server. Nessuno stato fra una richiesta e l'altra."""

    def __init__(self, impostazioni: ImpostazioniLLM | None = None) -> None:
        self.imp = impostazioni or ImpostazioniLLM()

    # ------------------------------------------------------------ salute

    @property
    def pronto(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.imp.url}/health", timeout=3) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def attendi(self, secondi: float = 60.0) -> bool:
        import time
        scadenza = time.monotonic() + secondi
        while time.monotonic() < scadenza:
            if self.pronto:
                return True
            time.sleep(2)
        return False

    # ---------------------------------------------------------- richieste

    def _corpo(self, prompt: str, **extra) -> bytes:
        d = {
            "prompt": prompt,
            "n_predict": self.imp.max_token,
            "temperature": self.imp.temperatura,
            "top_p": self.imp.top_p,
            "repeat_penalty": self.imp.ripetizione,
            "stop": list(self.imp.stop),
            # Il prefisso costante viene riconosciuto e non rielaborato: e' la
            # differenza fra 34 secondi di prefill e zero.
            "cache_prompt": True,
        }
        d.update(extra)
        return json.dumps(d).encode()

    def genera(self, prompt: str, grammatica: str | None = None) -> str:
        """Genera tutto e restituisce il testo. Blocca fino alla fine.

        Con `grammatica` il server accetta solo le parole che lei ammette:
        vedi `amelie.gabbia`.
        """
        extra = {"grammar": grammatica} if grammatica else {}
        req = urllib.request.Request(
            f"{self.imp.url}/completion", data=self._corpo(prompt, **extra),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.imp.timeout_s) as r:
                d = json.loads(r.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ModelloNonDisponibile(str(e)) from e
        if t := d.get("timings"):
            log.info("prefill %s tok a %.1f t/s, generati %s a %.1f t/s",
                     t.get("prompt_n"), t.get("prompt_per_second", 0),
                     t.get("predicted_n"), t.get("predicted_per_second", 0))
        return d.get("content", "")

    def genera_a_flusso(self, prompt: str) -> Iterator[str]:
        """Restituisce i token man mano che escono.

        È ciò che permette di far partire la voce sulla prima frase: a 4,2
        token/s, aspettare il testo completo significa venticinque secondi di
        silenzio davanti a un ospite.
        """
        req = urllib.request.Request(
            f"{self.imp.url}/completion", data=self._corpo(prompt, stream=True),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.imp.timeout_s) as r:
                for riga in r:
                    riga = riga.decode("utf-8", "replace").strip()
                    if not riga.startswith("data:"):
                        continue
                    try:
                        d = json.loads(riga[5:])
                    except json.JSONDecodeError:
                        continue
                    if pezzo := d.get("content"):
                        yield pezzo
                    if d.get("stop"):
                        break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ModelloNonDisponibile(str(e)) from e

    def scalda(self, prefisso: str) -> None:
        """Fa elaborare il prefisso costante, così resta in cache.

        Da chiamare all'avvio e, meglio ancora, appena il sensore rileva una
        bottiglia: mentre la camera scatta e l'OCR lavora, il modello ha già
        letto le istruzioni.
        """
        try:
            self.genera(prefisso[:2000])
        except ModelloNonDisponibile as e:
            log.warning("riscaldamento fallito: %s", e)


class ModelloNonDisponibile(RuntimeError):
    """llama-server non risponde."""
