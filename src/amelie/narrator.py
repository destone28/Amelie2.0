"""Il racconto: dai fatti alla prosa, senza inventare.

Un modello da 0,8 miliardi di parametri non sa nulla di vino. Se gli si chiede
di raccontare un Sagrantino, inventa premi, punteggi e note di degustazione che
suonano benissimo e sono false. In sala, davanti a un ospite, è una figuraccia.

Per questo il modello **non è la fonte dei fatti, è solo lo stile**. Tutto ciò
che il racconto afferma viene da `Fatti`, e ciò che non c'è nei fatti non si
dice. La difesa è a quattro strati, in ordine di costo crescente:

1. **Testo pre-generato.** Per ciò che il database conosce già, il racconto è
   stato scritto una volta e riletto. Latenza zero, rischio zero.
2. **Generazione dal vivo vincolata.** Per l'ignoto: il modello riceve solo il
   blocco dei fatti e un divieto esplicito di aggiungerne. ~20 secondi.
3. **Verifica deterministica.** Ogni numero e ogni nome proprio del testo
   generato deve comparire nei fatti. Se non ci compare, il testo si scarta.
   Questa non è una preferenza espressa nel prompt: è un controllo in Python
   che il modello non può aggirare.
4. **Template.** Frasi concatenate dai campi del database, senza modello. È
   l'unica cosa che garantisce che il dispositivo dica qualcosa di vero anche
   se tutto il resto fallisce.

Il tono cambia con il livello raggiunto dalla cascata: sotto il primo gradino
non si attribuisce mai a un produttore sconosciuto ciò che non si è verificato.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .lessico import Lessico, carica, elenca_in_lingua
from .matcher import Fatti, Livello

log = logging.getLogger(__name__)

# Un racconto piu' lungo di così non lo ascolta nessuno in piedi davanti a un
# tavolo, e ogni parola in piu' costa ~0,2 s di generazione sui Cortex-A53.
PAROLE_MAX = 130


@dataclass
class Racconto:
    testo: str
    origine: str          # 'cache' | 'modello' | 'template'
    livello: Livello
    verificato: bool = True

    @property
    def frasi(self) -> list[str]:
        """Spezza in frasi, che è l'unità con cui il TTS può iniziare a parlare
        prima che il testo sia finito."""
        return [f.strip() for f in re.split(r"(?<=[.!?…])\s+", self.testo) if f.strip()]


# ---------------------------------------------------------------- verifica

_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
# Un nome proprio: maiuscola iniziale, almeno tre lettere, non a inizio frase.
_PROPRIO = re.compile(r"(?<![.!?…]\s)(?<!^)\b([A-ZÀ-Ý][a-zà-ÿ']{2,})\b")

# Parole che iniziano per maiuscola senza essere nomi propri di vino: mesi,
# regioni generiche del discorso, e l'inizio di ogni frase.
_MAIUSCOLE_INNOCENTI = frozenset("""
    Il Lo La I Gli Le Un Uno Una Questo Questa Queste Questi Nel Nella Nelle Nei
    Dal Dalla Dalle Dai Del Della Delle Dei Con Per Tra Fra Ma Se Come Quando
    Dove Ogni Anche Ancora Oggi Qui Si No Non Suo Sua Sue Suoi Loro
    Gennaio Febbraio Marzo Aprile Maggio Giugno Luglio Agosto Settembre Ottobre
    Novembre Dicembre Italia Italiano Italiana
""".split())


def _senza_accenti(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def verifica(testo: str, fatti: Fatti) -> tuple[bool, list[str]]:
    """Il testo afferma solo cose presenti nei fatti?

    Restituisce (va bene, elenco delle invenzioni). Il controllo è volutamente
    grossolano ma **deterministico**: cerca numeri e nomi propri che non
    compaiano da nessuna parte nel blocco dei fatti. Preferisce un falso
    allarme — che costa una rigenerazione — a una bugia detta all'ospite.

    >>> f = Fatti(livello=Livello.VINO, nome="Cannubi", cantina="Marchesi")
    >>> verifica("Il Cannubi di Marchesi.", f)[0]
    True
    >>> verifica("Il Cannubi ha vinto tre stelle Gambero Rosso.", f)[0]
    False
    """
    ammesso = _senza_accenti(
        " ".join(filter(None, [
            fatti.blocco_fatti(),
            " ".join(fatti.vitigni),
            fatti.note_vitigno or "",
            fatti.denominazione or "",
            fatti.tipologia or "",
            fatti.nome or "",
            fatti.cantina or "",
            fatti.regione or "",
            str(fatti.annata or ""),
            fatti.temperatura_c or "",
        ]))
    )
    invenzioni = []

    for m in _NUMERO.finditer(testo):
        n = m.group(0).replace(",", ".")
        if n not in ammesso and n.replace(".", ",") not in ammesso:
            invenzioni.append(n)

    for m in _PROPRIO.finditer(testo):
        parola = m.group(1)
        if parola in _MAIUSCOLE_INNOCENTI:
            continue
        if _senza_accenti(parola) not in ammesso:
            invenzioni.append(parola)

    return (not invenzioni), invenzioni


# ---------------------------------------------------------------- template

def _apertura(f: Fatti, lex: Lessico, lingua: str) -> str:
    """La prima frase dice CHE COSA si ha davanti, con l'onestà del livello."""
    colore = lex.traduci("tipo", f.colore, lingua=lingua) if f.colore else None
    if f.livello is Livello.VINO and f.nome:
        pezzi = [f"«{f.nome}»"]
        if f.cantina:
            pezzi.append(f"di {f.cantina}")
        if f.annata:
            pezzi.append(f"annata {f.annata}")
        return "Questo è il " + " ".join(pezzi) + "."
    if f.livello is Livello.TIPOLOGIA and f.tipologia:
        return (f"Non riesco a leggere l'etichetta con certezza, "
                f"ma questo è un {f.tipologia}.")
    if f.livello is Livello.DENOMINAZIONE and f.denominazione:
        etichetta = "DOCG o DOC" if f.tipo_denominazione == "DOP" else "IGT"
        return (f"L'etichetta non è nitida, ma riconosco la denominazione: "
                f"{f.denominazione}, {etichetta}.")
    if f.livello is Livello.VITIGNO and f.vitigni:
        return (f"Del produttore non sono sicuro, ma il vitigno sì: "
                f"{f.vitigni[0]}.")
    return "Non riesco a leggere questa etichetta."


def _corpo(f: Fatti, lex: Lessico, lingua: str) -> list[str]:
    frasi = []
    if f.note_vitigno:
        frasi.append(f.note_vitigno)
    elif f.vitigni:
        frasi.append("Nasce da " + elenca_in_lingua(f.vitigni[:3], lingua) + ".")

    tratti = []
    if f.corpo:
        tratti.append(lex.traduci("corpo", f.corpo, lingua=lingua, forma="narrativa"))
    if f.acidita:
        tratti.append(lex.traduci("acidita", f.acidita, lingua=lingua, forma="narrativa"))
    if tratti:
        frasi.append("È un vino " + elenca_in_lingua(tratti, lingua) + ".")

    if f.abbinamenti:
        piatti = lex.traduci_molti("abbinamento", f.abbinamenti[:3], lingua=lingua)
        frasi.append("Si accompagna bene a " + elenca_in_lingua(piatti, lingua) + ".")
    if f.temperatura_c:
        # "16-18" letto ad alta voce diventa "sedici trattino diciotto": va
        # sciolto, perche' questo testo lo pronuncia una voce sintetica.
        t = f.temperatura_c.replace("–", "-")
        frasi.append(
            f"Servilo fra {t.replace('-', ' e ')} gradi." if "-" in t
            else f"Servilo a {t} gradi.")
    return frasi


def template(f: Fatti, lex: Lessico | None = None, lingua: str = "it") -> str:
    """Il racconto senza modello: la rete di sicurezza.

    Non è bello come un testo generato, ma è **vero per costruzione**: ogni
    frase nasce da un campo del database. È quello che il dispositivo dice se
    tutto il resto fallisce.
    """
    lex = lex or carica()
    return " ".join([_apertura(f, lex, lingua)] + _corpo(f, lex, lingua)).strip()


# ---------------------------------------------------------------- il prompt

ISTRUZIONI = """Sei la voce di un supporto da tavolo che racconta i vini in un ristorante.

Scrivi UN SOLO paragrafo in italiano, da 60 a 100 parole, caldo e discorsivo,
come lo direbbe un sommelier gentile a un ospite seduto.

REGOLE INDEROGABILI:
- Usa ESCLUSIVAMENTE le informazioni del blocco FATTI qui sotto.
- Non aggiungere premi, punteggi, medaglie, annate, gradi, nomi di persone,
  luoghi o vitigni che non siano scritti nei FATTI.
- Se un'informazione non c'è, non nominarla: non tentare di indovinarla.
- Niente elenchi puntati, niente titoli, niente virgolette: solo prose.
- Non rivolgerti al lettore con domande.

FATTI:
{fatti}

Racconto:"""

ISTRUZIONI_INCERTO = """
NOTA: l'etichetta non è stata letta con certezza. Non attribuire nulla a un
produttore specifico: parla della denominazione o del vitigno, non della
bottiglia.
"""


def prompt(f: Fatti) -> str:
    testo = ISTRUZIONI.format(fatti=f.blocco_fatti())
    if f.livello is not Livello.VINO:
        testo = testo.replace("\nFATTI:", ISTRUZIONI_INCERTO + "\nFATTI:")
    return testo


# ---------------------------------------------------------------- narratore

class Narratore:
    """Sceglie da dove far venire il racconto, nell'ordine che costa meno."""

    def __init__(
        self,
        percorso_db: str | Path | None = None,
        genera: Callable[[str], str] | None = None,
        lingua: str = "it",
    ) -> None:
        from .matcher import PERCORSO_DB

        self.percorso = Path(percorso_db) if percorso_db else PERCORSO_DB
        self.genera = genera          # None = nessun modello disponibile
        self.lingua = lingua
        self.lex = carica()
        self.con = sqlite3.connect(f"file:{self.percorso}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row

    def chiudi(self) -> None:
        self.con.close()

    def racconta(self, f: Fatti, *, consenti_modello: bool = True) -> Racconto:
        if f.vuoto:
            return Racconto(
                testo="Non riesco a leggere questa etichetta. Prova a girarla verso di me.",
                origine="template", livello=f.livello)

        if (pronto := self._dalla_cache(f)) is not None:
            return pronto

        if consenti_modello and self.genera is not None:
            if (vivo := self._dal_modello(f)) is not None:
                return vivo

        return Racconto(testo=template(f, self.lex, self.lingua),
                        origine="template", livello=f.livello)

    # -------------------------------------------------------------- strati

    def _dalla_cache(self, f: Fatti) -> Racconto | None:
        ambito, ident = self._chiave(f)
        if ident is None:
            return None
        r = self.con.execute(
            "SELECT testo FROM racconto WHERE ambito=? AND ambito_id=? AND lingua=?",
            (ambito, ident, self.lingua),
        ).fetchone()
        if not r:
            return None
        return Racconto(testo=r["testo"], origine="cache", livello=f.livello)

    def _chiave(self, f: Fatti) -> tuple[str, int | None]:
        """A che cosa è agganciato il testo pre-generato.

        Si pre-genera per denominazione, tipologia e vitigno — poche centinaia
        di testi — non per i 19.358 vini commerciali, che sarebbero giorni di
        calcolo.
        """
        mappa = {
            Livello.VINO: ("tipologia", None),
            Livello.TIPOLOGIA: ("tipologia", None),
            Livello.DENOMINAZIONE: ("denominazione", None),
            Livello.VITIGNO: ("vitigno", None),
        }
        ambito, _ = mappa.get(f.livello, ("tipologia", None))
        nome = {"tipologia": f.tipologia or f.denominazione,
                "denominazione": f.denominazione,
                "vitigno": f.vitigni[0] if f.vitigni else None}[ambito]
        if not nome:
            return ambito, None
        tabella = {"tipologia": "tipologia", "denominazione": "denominazione",
                   "vitigno": "vitigno"}[ambito]
        from .text import normalizza
        r = self.con.execute(
            f"SELECT id FROM {tabella} WHERE nome_norm = ? LIMIT 1", (normalizza(nome),)
        ).fetchone()
        return ambito, (r["id"] if r else None)

    def _dal_modello(self, f: Fatti) -> Racconto | None:
        """Genera e verifica. Un solo secondo tentativo, poi si rinuncia.

        Rigenerare all'infinito su un modello che continua a inventare
        significherebbe far aspettare l'ospite per nulla: meglio il template.
        """
        for tentativo in (1, 2):
            try:
                testo = (self.genera(prompt(f)) or "").strip()
            except Exception as e:                       # noqa: BLE001
                log.warning("generazione fallita: %s", e)
                return None
            if not testo:
                continue
            testo = _ripulisci(testo)
            ok, invenzioni = verifica(testo, f)
            if ok:
                return Racconto(testo=testo, origine="modello", livello=f.livello)
            log.warning("tentativo %d scartato, ha inventato: %s", tentativo, invenzioni)
        return None


def _ripulisci(testo: str) -> str:
    """Toglie le abitudini dei modelli: virgolette, titoli, elenchi, code."""
    testo = testo.strip().strip('"«»')
    testo = re.sub(r"^\s*(Racconto|Testo|Risposta)\s*:\s*", "", testo, flags=re.I)
    testo = re.sub(r"^\s*[-*•]\s*", "", testo, flags=re.M)
    testo = re.sub(r"\s+", " ", testo).strip()
    parole = testo.split()
    if len(parole) > PAROLE_MAX:
        testo = " ".join(parole[:PAROLE_MAX])
        # Si preferisce chiudere su una frase intera, ma solo se questo non
        # butta via piu' di meta' del testo: meglio un troncamento dichiarato
        # con i puntini che due parole al posto di cento.
        punto = testo.rfind(".")
        if punto >= len(testo) // 2:
            testo = testo[: punto + 1]
        elif not testo.endswith(("…", ".", "!", "?")):
            testo = testo.rstrip(" ,;:") + "…"
    return testo


def a_frasi(flusso: Iterator[str]) -> Iterator[str]:
    """Raggruppa un flusso di token in frasi complete.

    Serve al TTS: si può cominciare a parlare appena la prima frase è finita,
    invece di aspettare tutto il racconto. Su questa board sono venti secondi
    di attesa risparmiati.
    """
    buffer = ""
    for pezzo in flusso:
        buffer += pezzo
        while (m := re.search(r"[.!?…]\s", buffer)):
            frase, buffer = buffer[: m.end()].strip(), buffer[m.end():]
            if frase:
                yield frase
    if buffer.strip():
        yield buffer.strip()
