"""La carta dei vini: un file di testo al posto dell'archivio.

Un CSV con due colonne — `titolo` e `descrizione` — dove ogni riga è una
denominazione e il suo racconto già scritto, da leggere così com'è. Niente
cascata, niente composizione dai fatti, niente modello: si riconosce il titolo
e si legge la descrizione.

**È una prova, non la strada.** Si accende con `--carta vini.csv` e il
dispositivo dimentica l'archivio per tutto il tempo che resta accesa; si spegne
togliendo l'opzione. Serve a vedere, su bottiglie vere, che effetto fa un testo
scritto da una persona al posto di uno composto dai dati.

Quello che NON cambia è la regola: **non si nomina ciò che non si è letto.**
Vale qui come nell'archivio, e vale di più: le descrizioni sono lunghe e
convincenti, e attaccarne una alla bottiglia sbagliata sarebbe un errore
raccontato benissimo. Il titolo si può dire solo se le parole che lo
identificano — Barolo, Amarone, Chablis, non «DOCG» né «Riserva» — erano sul
vetro.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .matcher import PAROLE_GENERICHE
from .text import normalizza, parole_utili, token

log = logging.getLogger(__name__)

# Sotto questa somiglianza non si propone niente. La regola sulle parole
# identificanti fa il lavoro pesante — è lei che impedisce di attribuire un
# Chablis a chi ha in mano un Soave — ma serve anche un minimo sotto il quale
# due titoli che condividono una parola sola non si contendono la bottiglia.
SOMIGLIANZA_MINIMA = 55.0

# Le parole che un titolo può contenere senza che l'etichetta le scriva.
#
# I marchi di denominazione, perché una bottiglia dice «Soave» e il «DOC» sta
# scritto piccolo o non si legge. E «annata», che nel Chianti Classico è il
# nome del gradino base e sull'etichetta non compare mai — chi imbottiglia
# un'Annata scrive «Chianti Classico» e basta.
#
# Tutto il resto no: se il titolo dice «Extra Brut», «Riserva» o «Classico»,
# quelle parole devono essere sul vetro. Promettono un vino diverso, e
# prometterlo senza averlo letto è l'errore che la carta rende peggiore —
# perché qui la descrizione è lunga, dettagliata e convincente.
# Quanto deve somigliare un pezzo di parola per ritrovare la parola intera,
# quando il titolo si accetta parola per parola: vedi `_somiglianza`. I pezzi
# veri, lasciati dal vetro curvo, stanno sopra - «parossa» per «grasparossa»
# fa 78, «castelve» per «castelvetro» 84, «lambrus» per «lambrusco» 88 - e
# le coincidenze sotto: «raccolta» per «franciacorta» fa 70.
RISCONTRO_PEZZO = 75.0

TACITE = frozenset((
    "doc", "docg", "dop", "igt", "igp", "aoc", "aop", "ava", "doca", "vdp",
    "qba", "annata",
))


@dataclass
class Voce:
    """Una riga della carta: un titolo e il suo racconto, in ogni lingua che c'e'.

    `titolo` e `descrizione` sono l'italiano, che e' obbligatorio; le altre
    lingue stanno in `altre`, e possono non esserci.
    """

    titolo: str
    descrizione: str
    somiglianza: float = 0.0
    # {"en": (titolo, descrizione)} per le lingue oltre l'italiano.
    altre: dict[str, tuple[str, str]] = field(default_factory=dict)

    def titolo_in(self, lingua: str) -> str:
        if lingua == "it" or lingua not in self.altre:
            return self.titolo
        return self.altre[lingua][0] or self.titolo

    def testo_in(self, lingua: str) -> str | None:
        """La descrizione in questa lingua, o `None` se la carta non ce l'ha.

        `None` e' un'informazione, non un guasto: vuol dire che questa bottiglia
        va raccontata da un'altra parte. Senza questa distinzione, all'ospite
        che aveva scelto l'inglese arrivava la prima frase tradotta e poi tutto
        il resto in italiano - scritto **e letto**, con la voce inglese che
        compita l'italiano.
        """
        if lingua == "it":
            return self.descrizione
        testo = self.altre.get(lingua, ("", ""))[1]
        return testo or None


class Carta:
    """Le voci del file, e come si trova la giusta a partire da cosa si è letto."""

    def __init__(self, percorso: str | Path) -> None:
        self.percorso = Path(percorso)
        self.voci: list[Voce] = []
        # Le lingue che il file parla. Si sa dalle colonne, e si sa all'avvio.
        self.lingue: set[str] = {"it"}
        self._voci_indice: list[str] = []
        # Due elenchi di parole per ogni titolo, e servono a due cose diverse.
        # `_token` passa dal filtro delle parole vuote ed è quello su cui si
        # misura la somiglianza. `_tutte` no, e serve a contare QUANTO di un
        # titolo si è letto: il filtro butta via «classico», «riserva» e
        # «superiore» — parole che non identificano un vino ma distinguono
        # benissimo un Chianti da un Chianti Classico. Contare senza di loro
        # faceva pareggiare i due titoli, e vinceva quello che veniva prima
        # nel file.
        self._token: list[list[str]] = []
        self._tutte: list[list[str]] = []
        # Quali voci contengono ciascuna parola. Serve a capire cosa una parola
        # letta IMPLICA: vedi `_implicate`.
        self._dove: dict[str, set[int]] = {}
        self._carica()

    def _carica(self) -> None:
        with open(self.percorso, encoding="utf-8", newline="") as f:
            lettore = csv.DictReader(f)
            # Le lingue che questo file parla, dalle colonne che ha: oltre
            # all'italiano, ogni `descrizione_xx` ne aggiunge una. Un file con
            # la sola `descrizione` parla italiano e basta, e il dispositivo lo
            # sa PRIMA di provare a leggerlo in inglese.
            intestazioni = lettore.fieldnames or []
            self.lingue = {"it"} | {
                c.split("_", 1)[1] for c in intestazioni
                if c.startswith("descrizione_") and len(c.split("_", 1)[1]) == 2
            }
            for r in lettore:
                titolo = (r.get("titolo") or "").strip()
                testo = (r.get("descrizione") or "").strip()
                if not titolo or not testo:
                    continue
                altre = {}
                for lingua in self.lingue - {"it"}:
                    t = (r.get(f"descrizione_{lingua}") or "").strip()
                    if t:
                        altre[lingua] = ((r.get(f"titolo_{lingua}") or "").strip(), t)
                self.voci.append(Voce(titolo=titolo, descrizione=testo, altre=altre))
                self._token.append(parole_utili(normalizza(titolo)))
                self._tutte.append(token(titolo))
                for p in self._tutte[-1]:
                    self._dove.setdefault(p, set()).add(len(self._voci_indice))
                self._voci_indice.append(titolo)
        log.info("carta dei vini: %d voci da %s, in %s", len(self.voci),
                 self.percorso.name, ", ".join(sorted(self.lingue)))
        if not self.voci:
            raise CartaVuota(f"nessuna voce utilizzabile in {self.percorso}")

    def voce(self, titolo: str) -> Voce | None:
        """La voce con questo titolo esatto: quella scelta nell'editor delle
        correzioni. Si ritrova per titolo e non per posizione, perche' il file
        si puo' riscrivere fra un avvio e l'altro."""
        return next((v for v in self.voci if v.titolo == titolo), None)

    def suggerisci(self, testo: str, quanti: int = 5) -> list[Voce]:
        """Le voci il cui titolo contiene ogni parola scritta, l'ultima come
        inizio di parola: «barolo ris» trova «Barolo DOCG Riserva»."""
        from .text import normalizza
        parole = normalizza(testo).split()
        if not parole:
            return []
        fuori = []
        for v in self.voci:
            sue = normalizza(v.titolo).split()
            if (all(p in sue for p in parole[:-1])
                    and any(s.startswith(parole[-1]) for s in sue)):
                fuori.append(v)
        fuori.sort(key=lambda v: len(v.titolo))
        return fuori[:quanti]

    def cerca(self, righe: Sequence[str]) -> Voce | None:
        """Il titolo che la bottiglia dichiara, se lo dichiara.

        Due filtri, e l'ordine conta. Prima la somiglianza, che dice quale
        titolo assomiglia di più a quello che si è letto; poi la regola sulle
        parole identificanti, che dice se quel titolo lo si può PRONUNCIARE.
        Il secondo non è un raffinamento del primo: un titolo può somigliare
        moltissimo e restare impronunciabile, ed è esattamente il caso da cui
        la regola nasce.
        """
        from rapidfuzz import fuzz

        testo = normalizza(" ".join(righe))
        lette = parole_utili(testo)
        if not lette:
            return None

        tutte_lette = token(" ".join(righe))
        implicate = self._implicate(tutte_lette)
        migliore: Voce | None = None
        meglio = (-1, 1, -1.0)
        for voce, chiavi, parole in zip(self.voci, self._token, self._tutte):
            if not chiavi:
                continue
            punti = _somiglianza(testo, chiavi, lette)
            if punti < SOMIGLIANZA_MINIMA:
                continue
            # Ogni parola del titolo che promette qualcosa dev'essere sul
            # vetro, o essere IMPLICATA da quello che c'è. È la regola
            # dell'archivio — non si nomina ciò che non si è letto — portata
            # fino in fondo: lì il veto riguarda le parole che IDENTIFICANO,
            # qui anche quelle che distinguono, perché una carta ha «Champagne
            # Extra Brut» e «Champagne Brut Sans Année» come voci separate e
            # sono due vini diversi.
            #
            # Regge solo perché esistono le voci generiche: scartando chi
            # promette troppo si deve poter atterrare da qualche parte, e
            # quella parte è «Champagne AOC».
            if any(not _si_e_letta(p, tutte_lette)
                   for p in parole if p not in TACITE and p not in implicate):
                continue
            # Fra i titoli che si POSSONO dire, vince quello che spiega di più
            # dell'etichetta. La somiglianza da sola non basta e sceglie male:
            # su «CHIANTI CLASSICO DOCG» sia «Chianti DOCG» sia «Chianti
            # Classico DOCG Annata» fanno cento, perché il primo è un
            # sottoinsieme del secondo, e vinceva quello che capitava prima nel
            # file. Ma «classico» sulla bottiglia c'era scritto, e un Chianti
            # Classico non è un Chianti: contare le parole del titolo che si
            # sono davvero lette sceglie il più specifico fra i veri.
            lette_qui = [p for p in parole if _si_e_letta(p, tutte_lette)]
            # A parità di parole lette vince chi ne ha meno di NON lette: fra
            # «Champagne Rosé AOC» e «Champagne AOC», letto solo «champagne»,
            # il secondo promette meno e mantiene tutto.
            quante, mute = len(lette_qui), len(parole) - len(lette_qui)
            if (quante, -mute, punti) <= meglio:
                continue
            meglio = (quante, -mute, punti)
            migliore = Voce(titolo=voce.titolo, descrizione=voce.descrizione,
                            somiglianza=punti, altre=voce.altre)
        if migliore is not None:
            log.info("carta: «%s» al %.0f%% (%d parole lette, %d no)",
                     migliore.titolo, migliore.somiglianza, meglio[0], -meglio[1])
        return migliore

    def _implicate(self, lette: Sequence[str]) -> set[str]:
        """Le parole che non serve leggere, perché la carta le dà per scontate.

        Sul dispositivo, etichetta vera: l'OCR ha letto «Brunello» e tre
        frammenti, e la regola ha scartato «Brunello di Montalcino DOCG»
        perché «Montalcino» sul vetro non c'era. Ma in carta **non esiste un
        altro Brunello**: ogni voce che contiene quella parola contiene anche
        «Montalcino», e dirlo non aggiunge nessun rischio.

        Non è un'eccezione scritta a mano, è una proprietà del file: una parola
        si può dire senza averla letta quando compare in TUTTE le voci che
        contengono quelle lette. Cambiando la carta, cambia da sola.

        Non tocca «Riserva», che sta in una delle due voci e non nell'altra:
        quella resta una promessa da guadagnarsi sul vetro. E non tocca
        «Extra», per la stessa ragione, su otto Champagne diversi.
        """
        # Solo le parole che IDENTIFICANO restringono la famiglia. Se
        # restringesse anche «brut», leggere «CHAMPAGNE BRUT» lascerebbe in
        # piedi il solo «Champagne Extra Brut» e da li' «extra» risulterebbe
        # implicato - cioe' la regola si smentirebbe da sola proprio sul caso
        # che l'ha fatta nascere. Provato, e succedeva.
        insiemi = [self._dove[p] for p in lette
                   if p in self._dove and p not in PAROLE_GENERICHE]
        if not insiemi:
            return set()
        compatibili = set.intersection(*insiemi) if len(insiemi) > 1 else insiemi[0]
        if not compatibili:
            return set()
        return {p for p, dove in self._dove.items() if compatibili <= dove}

    def vicine(self, righe: Sequence[str], quante: int = 3) -> list[str]:
        """I titoli che si sarebbero potuti dire, ma che non si sono letti.

        Non finiscono in bocca al dispositivo: servono al giornale, per capire
        DOPO perché una bottiglia non è stata riconosciuta. Se il titolo giusto
        è qui dentro, il problema è la regola o l'OCR; se non c'è, il problema
        è la carta.
        """
        from rapidfuzz import fuzz

        testo = normalizza(" ".join(righe))
        if not parole_utili(testo):
            return []
        punteggi = [(fuzz.token_set_ratio(testo, " ".join(k)), v.titolo)
                    for v, k in zip(self.voci, self._token) if k]
        punteggi.sort(reverse=True)
        return [f"{titolo} ({punti:.0f})" for punti, titolo in punteggi[:quante]]


def _somiglianza(testo: str, chiavi: Sequence[str], lette: Sequence[str]) -> float:
    """Quanto un titolo somiglia a ciò che si è letto: la migliore di due misure.

    `token_set_ratio` da sola è tutto-o-niente sulle parole, e un'etichetta
    letta a pezzi la manda sotto la soglia anche quando ogni parola del titolo
    c'è. Sul dispositivo, un Lambrusco tenuto in mano davanti alla camera:
    «LAMBRUSCO / PAROSSA DI CASTELVETN» faceva 54 con «Lambrusco Grasparossa
    di Castelvetro», e il titolo non arrivava nemmeno alla regola che l'avrebbe
    accettato - «parossa» e «castelvetn» sono proprio le parole del titolo, con
    la curva del vetro che se ne mangia un pezzo.

    La seconda misura è quella dell'archivio, parola per parola: ogni parola
    del titolo cerca la sua fra quelle lette. Ma vale solo a tre condizioni,
    e ognuna viene da un errore visto rigiocando milleduecento letture del
    giornale: il titolo ha almeno due parole, le ritrova TUTTE, e almeno una
    l'ha letta esatta. Senza, una parola sola somigliante bastava: «SALENTO»
    diventava «Alentejo DOC», «MARO» diventava «Marino DOC». Con due parole
    di cui una esatta, il resto può essere un pezzo di parola: è ciò che il
    vetro curvo lascia leggere.

    Il pezzo deve somigliare un po' più di quanto chieda la regola sulle
    parole: a settanta, «raccolta» della retroetichetta ritrovava
    «franciacorta», e con «BRUT» esatto uno spumante pugliese diventava un
    Franciacorta. Vedi `RISCONTRO_PEZZO`.
    """
    from rapidfuzz import fuzz

    punti = fuzz.token_set_ratio(testo, " ".join(chiavi))
    if len(chiavi) < 2 or punti >= SOMIGLIANZA_MINIMA:
        return punti
    migliori = [max((fuzz.ratio(c, l) for l in lette), default=0.0) for c in chiavi]
    if min(migliori) < RISCONTRO_PEZZO or max(migliori) < 100:
        return punti
    return max(punti, sum(migliori) / len(migliori))


def _si_e_letta(parola: str, lette: Sequence[str]) -> bool:
    """Questa parola del titolo si ritrova fra quelle lette?

    Stessa soglia per parola del riconoscitore: sotto settanta non è un
    riscontro debole, è un non-riscontro, e un refuso vale ottanta e passa.
    """
    from rapidfuzz import fuzz

    from .matcher import RISCONTRO_PAROLA

    return any(fuzz.ratio(parola, l) >= RISCONTRO_PAROLA for l in lette)


class CartaVuota(RuntimeError):
    """Il file c'è ma non contiene voci utilizzabili."""
