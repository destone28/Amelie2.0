"""Vocabolari controllati, tradotti.

I dataset di partenza sono in inglese: X-Wines dice `Medium-bodied`, il
registro UE dice `Quality Sparkling Wine`. Il dispositivo deve raccontare in
italiano, ed è previsto che racconti anche in altre lingue.

La regola che tiene insieme la cosa: **le chiavi restano i valori inglesi
originali dei dataset**, esattamente come compaiono nelle fonti. Sono la chiave
di join, e cambiarle romperebbe il collegamento con i dati. La traduzione è un
livello sopra, non una riscrittura dei dati.

Ogni termine ha una forma `etichetta`, breve, per lo schermo, e facoltativamente
una forma `narrativa` da usare dentro una frase: sono cose diverse. «alta» è
l'etichetta giusta per un'acidità in una scheda, ma dentro una frase si dice
«bella acidità», non «acidità alta».

Aggiungere una lingua significa aggiungere la sua sigla a `lingue` nel JSON e la
voce corrispondente a ogni termine; il test di copertura fallisce finché non
sono complete, così una lingua non può restare tradotta a metà senza che nessuno
se ne accorga.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

PERCORSO_PREDEFINITO = (
    Path(__file__).resolve().parents[2] / "data" / "lessico" / "vocabolari.json"
)
PERCORSO_FRASI = (
    Path(__file__).resolve().parents[2] / "data" / "lessico" / "frasi.json"
)

# Le chiavi di primo livello che non sono vocabolari.
_META = {"_nota", "lingue", "predefinita"}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lessico:
    """I vocabolari caricati, interrogabili per lingua."""

    vocabolari: dict[str, dict[str, dict]]
    lingue: tuple[str, ...]
    predefinita: str
    # gruppo -> chiave -> lingua -> frase, o ELENCO di frasi equivalenti.
    # Vedi data/lessico/frasi.json.
    frasi: dict[str, dict[str, dict[str, str | list[str]]]] = field(default_factory=dict)

    def frase(self, gruppo: str, chiave: str, *, lingua: str | None = None,
              seme: int | None = None, **segnaposto: object) -> str:
        """Una frase del racconto, nella lingua chiesta, coi buchi riempiti.

        Se la lingua non ha quella frase si ripiega sulla predefinita: meglio
        una riga in italiano dentro un testo inglese che un buco nero a
        schermo. Se manca del tutto si restituisce stringa vuota, e chi chiama
        se ne accorge perche' la frase sparisce - non perche' il dispositivo si
        ferma davanti a un tavolo.

        Una voce puo' avere PIU' frasi equivalenti, e `seme` sceglie quale:
        sempre la stessa per lo stesso seme, cosi' lo stesso vino si racconta
        sempre con le stesse parole e due vini diversi con parole diverse.
        Senza seme si prende la prima, che e' quella di riferimento: le
        varianti dicono la stessa cosa in un altro modo, e la prima e' quella
        su cui si e' scritto tutto il resto.
        """
        voce = self.frasi.get(gruppo, {}).get(chiave, {})
        modelli = voce.get(lingua or self.predefinita) or voce.get(self.predefinita)
        if isinstance(modelli, str):
            modelli = [modelli]
        if not modelli:
            log.warning("frase mancante: %s.%s in %s", gruppo, chiave, lingua)
            return ""
        modello = modelli[(seme or 0) % len(modelli)]
        try:
            return modello.format(**segnaposto)
        except KeyError as e:
            log.warning("segnaposto %s mancante per %s.%s", e, gruppo, chiave)
            return modello

    def varianti(self, gruppo: str, chiave: str, lingua: str | None = None) -> list[str]:
        """Tutte le forme equivalenti di una frase, per chi le deve controllare."""
        modelli = self.frasi.get(gruppo, {}).get(chiave, {}).get(lingua or self.predefinita)
        if isinstance(modelli, str):
            return [modelli]
        return list(modelli or [])

    def traduci(
        self,
        vocabolario: str,
        valore: str,
        *,
        lingua: str | None = None,
        forma: str = "etichetta",
    ) -> str:
        """Traduce un valore di un vocabolario.

        Un valore sconosciuto viene restituito com'è, invece di sollevare
        un'eccezione: se un domani il dataset aggiunge un termine, il
        dispositivo deve continuare a funzionare dicendo la parola inglese, non
        fermarsi. Il test di copertura è il posto dove quel buco viene segnalato.

        >>> lex = carica()
        >>> lex.traduci("corpo", "Full-bodied")
        'strutturato'
        >>> lex.traduci("corpo", "Full-bodied", forma="narrativa")
        'di bella struttura'
        >>> lex.traduci("corpo", "Full-bodied", lingua="en")
        'full-bodied'
        """
        lingua = lingua or self.predefinita
        voce = self.vocabolari.get(vocabolario, {}).get(valore)
        if not voce:
            return valore
        per_lingua = voce.get(lingua) or voce.get(self.predefinita) or {}
        # `narrativa` è facoltativa: dove manca, l'etichetta va benissimo.
        return per_lingua.get(forma) or per_lingua.get("etichetta") or valore

    def traduci_molti(
        self,
        vocabolario: str,
        valori: Iterable[str],
        *,
        lingua: str | None = None,
        forma: str = "etichetta",
    ) -> list[str]:
        return [
            self.traduci(vocabolario, v, lingua=lingua, forma=forma) for v in valori
        ]

    def elenco(self, vocabolario: str) -> list[str]:
        """Le chiavi di un vocabolario, cioè i valori attesi nei dataset."""
        return sorted(self.vocabolari.get(vocabolario, {}))

    def nomi_vocabolari(self) -> list[str]:
        return sorted(self.vocabolari)

    def manca(self, vocabolario: str, valori: Iterable[str]) -> set[str]:
        """I valori che il vocabolario non sa tradurre.

        È il controllo che protegge dalla deriva: quando una fonte viene
        aggiornata e introduce un termine nuovo, questo lo trova.
        """
        noti = self.vocabolari.get(vocabolario, {})
        return {v for v in valori if v and v not in noti}


@lru_cache(maxsize=4)
def carica(percorso: str | Path | None = None) -> Lessico:
    """Carica i vocabolari. Il risultato è memorizzato: si legge una volta sola."""
    p = Path(percorso) if percorso else PERCORSO_PREDEFINITO
    dati = json.loads(p.read_text(encoding="utf-8"))

    vocabolari = {
        nome: {k: v for k, v in contenuto.items() if not k.startswith("_")}
        for nome, contenuto in dati.items()
        if nome not in _META and isinstance(contenuto, dict)
    }

    frasi: dict[str, dict[str, dict[str, str | list[str]]]] = {}
    percorso_frasi = p.parent / "frasi.json"
    if percorso_frasi.exists():
        grezze = json.loads(percorso_frasi.read_text(encoding="utf-8"))
        frasi = {
            gruppo: {k: v for k, v in contenuto.items()
                     if not k.startswith("_") and isinstance(v, dict)}
            for gruppo, contenuto in grezze.items()
            if not gruppo.startswith("_") and isinstance(contenuto, dict)
        }

    return Lessico(
        vocabolari=vocabolari,
        lingue=tuple(dati.get("lingue", ["it"])),
        predefinita=dati.get("predefinita", "it"),
        frasi=frasi,
    )


def elenca_in_lingua(voci: list[str], lingua: str = "it") -> str:
    """Unisce un elenco come lo direbbe una persona: «a, b e c».

    >>> elenca_in_lingua(["manzo", "agnello", "cacciagione"])
    'manzo, agnello e cacciagione'
    >>> elenca_in_lingua(["manzo"], "en")
    'manzo'
    """
    voci = [v for v in voci if v]
    if not voci:
        return ""
    if len(voci) == 1:
        return voci[0]
    congiunzione = {"it": "e", "en": "and"}.get(lingua, "e")
    return f"{', '.join(voci[:-1])} {congiunzione} {voci[-1]}"
