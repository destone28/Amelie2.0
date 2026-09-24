"""Le bottiglie corrette a mano, e come si riconoscono la volta dopo.

Quando una bottiglia non e' in archivio, chi sta in sala puo' scriverne il
titolo e la descrizione dalla tastiera a schermo. Il dispositivo conserva
tre cose - **la foto dell'etichetta, le parole che ne ha letto, il testo
scritto** - e quando la stessa bottiglia torna sul piatto la riconosce da
quelle, prima dell'archivio e in qualunque modo di racconto.

Riconoscerla e' la parte delicata, perche' sbagliare qui vuol dire raccontare
un vino con la descrizione di un altro: e' la bugia che tutto il resto del
progetto si sforza di non dire. Due segnali, e nessuno dei due basta da solo
se non e' fortissimo:

- **le parole**: quante di quelle lette la volta scorsa si rileggono adesso.
  Sono le parole che identificano - lunghe, non numeri, non «rosso» o «doc»,
  che stanno su migliaia di bottiglie;
- **l'immagine**: quanti punti dell'etichetta si ritrovano nella foto nuova,
  in una posizione coerente (ORB e un'omografia robusta).

L'immagine si guarda **solo dove sta l'etichetta**, cioe' attorno alle righe in
cui l'OCR ha trovato quelle parole. Misurato sulle scansioni vere del
dispositivo: dietro al piatto c'era un calendario, e due foto di bottiglie
diverse si somigliavano attraverso lo sfondo fino a 49 punti - quanto basta a
confondersi. Un ristorante avra' il suo sfondo, sempre lo stesso: e' un rischio
che va tolto alla radice, non tarato.

Le soglie sono in `Regola`, con la misura che le giustifica.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger(__name__)

RADICE = Path(__file__).resolve().parents[2]
CARTELLA_CORREZIONI = RADICE / "var" / "correzioni"

# Le foto si confrontano tutte alla stessa altezza: una etichetta fotografata
# un po' piu' vicina non deve sembrare un'altra etichetta.
ALTEZZA_CONFRONTO = 720


@dataclass(frozen=True)
class Regola:
    """Quando una lettura e' la bottiglia corretta.

    Tarata su 119 scansioni vere del dispositivo, rilette con l'OCR della board
    ed etichettate a mano per bottiglia: sei vini, da due a diciassette letture
    ciascuno, e cinquantacinque letture a piatto vuoto. Con l'immagine guardata
    sull'etichetta sola:

                             parole in comune     punti d'immagine in comune
        stessa bottiglia     mediana 0,67         mediana 27, fino a 883
        bottiglie diverse    MAI oltre 0,50       MAI oltre 12
        contro piatto vuoto  mai nessuna          mai oltre 7

    Le soglie stanno sopra quei massimi con un margine, non sul bordo: su 470
    coppie della stessa bottiglia se ne riconoscono 268, su 4.084 coppie
    diverse nessuna. Si poteva arrivare a 280 abbassando le parole a 0,5 - che
    e' esattamente il massimo visto fra bottiglie diverse - e non lo si e'
    fatto: un riconoscimento mancato si ripara con un tocco, uno sbagliato
    racconta un vino con le parole scritte per un altro.
    """

    # Le parole in comune, come frazione di quelle lette la volta scorsa, e in
    # quante: una parola sola in comune e' una coincidenza, non un riscontro.
    parole: float = 0.6
    parole_minime: int = 2
    # Con le parole d'accordo, l'immagine deve almeno non dire di no: sedici
    # punti, contro i dodici che due bottiglie diverse non hanno mai superato.
    immagine_con_parole: int = 16
    # Da sola, l'immagine decide quando e' due volte e mezzo il massimo visto
    # fra bottiglie diverse. Serve quando l'OCR stavolta ha letto male le
    # parole - «APADOSEN» per NEGROAMARO - ma la bottiglia e' la stessa.
    immagine_da_sola: int = 30
    # Quante viste si confrontano con l'immagine, al massimo, per lettura. Sulla
    # board un confronto costa 38 millesimi: con venti bottiglie corrette e tre
    # viste l'una sarebbero due secondi. Si confrontano solo le viste che hanno
    # almeno una parola in comune con quella letta - su 268 riconoscimenti
    # nessuno e' avvenuto senza - e di quelle le piu' vicine.
    viste_confrontate: int = 6


REGOLA = Regola()


# ---------------------------------------------------------------- parole

def parole_identificanti(righe: Sequence[str]) -> list[str]:
    """Le parole che dicono QUALE bottiglia e', non che tipo di bottiglia.

    Almeno quattro lettere, solo lettere, e non fra quelle che stanno su
    migliaia di etichette («rosso», «doc», «brut», «vino»): quelle sono
    `PAROLE_GENERICHE` del riconoscitore, e qui valgono lo stesso.
    """
    from .matcher import PAROLE_GENERICHE
    from .text import normalizza, parole_utili

    fuori = set()
    for p in parole_utili(normalizza(" ".join(righe))):
        if len(p) >= 4 and p.isalpha() and p not in PAROLE_GENERICHE:
            fuori.add(p)
    return sorted(fuori)


def parole_in_comune(memoria: Sequence[str], lette: Sequence[str]) -> tuple[float, int]:
    """Quante delle parole ricordate si rileggono adesso: (frazione, numero).

    Il confronto e' tollerante - l'OCR scrive «NECROAMARO» per NEGROAMARO una
    volta su due - ma ogni parola letta ne conferma una sola.
    """
    from rapidfuzz import fuzz

    if not memoria or not lette:
        return 0.0, 0
    libere = list(lette)
    prese = 0
    for m in memoria:
        if not libere:
            break
        i = max(range(len(libere)), key=lambda k: fuzz.ratio(m, libere[k]))
        if fuzz.ratio(m, libere[i]) >= 80:
            prese += 1
            libere.pop(i)
    return prese / len(memoria), prese


# ---------------------------------------------------------------- immagine

def zona_etichetta(righe: Sequence[Any], forma: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Il rettangolo dell'etichetta, dalle righe che portano parole vere.

    `righe` sono le `Riga` dell'OCR, col loro quadrilatero. Si prendono quelle
    che contengono almeno una parola identificante, se ne fa il rettangolo che
    le contiene, e lo si allarga quanto basta a prendere stemmi e fregi che
    stanno attorno alle scritte - non tanto da riprendere il muro dietro.

    None se non c'e' nessuna parola: allora di etichetta non se ne vede, e
    l'immagine non deve dire niente.
    """
    alto, largo = forma
    punti, altezze = [], []
    for r in righe:
        testo = getattr(r, "testo", "")
        quad = getattr(r, "riquadro", ())
        if len(quad) < 3 or not parole_identificanti([testo]):
            continue
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        punti.append((min(xs), min(ys), max(xs), max(ys)))
        altezze.append(max(ys) - min(ys))
    if not punti:
        return None
    x0 = min(p[0] for p in punti); y0 = min(p[1] for p in punti)
    x1 = max(p[2] for p in punti); y1 = max(p[3] for p in punti)
    riga = sorted(altezze)[len(altezze) // 2]
    dy = max(2.0 * riga, .06 * alto)
    dx = .12 * (x1 - x0)
    return (max(0, int(x0 - dx)), max(0, int(y0 - dy)),
            min(largo, int(x1 + dx)), min(alto, int(y1 + dy)))


class _Occhio:
    """ORB e il suo confronto. Uno solo per tutto il processo: crearlo costa."""

    def __init__(self) -> None:
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=900, scaleFactor=1.2, nlevels=8,
                                  fastThreshold=12)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def descrivi(self, immagine, zona: tuple[int, int, int, int] | None):
        """I punti dell'etichetta, e solo dell'etichetta."""
        import numpy as np
        cv2 = self.cv2
        if immagine is None or zona is None:
            return None
        grigia = immagine if immagine.ndim == 2 else cv2.cvtColor(immagine, cv2.COLOR_BGR2GRAY)
        k = ALTEZZA_CONFRONTO / grigia.shape[0]
        piccola = cv2.resize(grigia, (max(1, round(grigia.shape[1] * k)), ALTEZZA_CONFRONTO),
                             interpolation=cv2.INTER_AREA)
        piccola = self.clahe.apply(piccola)
        maschera = np.zeros(piccola.shape, np.uint8)
        x0, y0, x1, y1 = (round(v * k) for v in zona)
        maschera[y0:y1, x0:x1] = 255
        punti, desc = self.orb.detectAndCompute(piccola, maschera)
        if desc is None or len(punti) < 8:
            return None
        return np.float32([p.pt for p in punti]), desc

    def in_comune(self, a, b) -> int:
        """Quanti punti di A si ritrovano in B al posto giusto."""
        import numpy as np
        if a is None or b is None:
            return 0
        (pa, da), (pb, db) = a, b
        coppie = self.bf.knnMatch(da, db, k=2)
        buone = [m for m, *n in coppie if n and m.distance < .75 * n[0].distance]
        if len(buone) < 8:
            return 0
        sa = np.float32([pa[m.queryIdx] for m in buone])
        sb = np.float32([pb[m.trainIdx] for m in buone])
        _, maschera = self.cv2.findHomography(sa, sb, self.cv2.RANSAC, 6.0)
        return int(maschera.sum()) if maschera is not None else 0


# ---------------------------------------------------------------- dati

@dataclass
class Vista:
    """Una lettura della bottiglia: la foto, dove sta l'etichetta, le parole."""

    immagine: str
    righe: list[str]
    parole: list[str]
    zona: tuple[int, int, int, int] | None
    quando: str = ""
    # I descrittori si ricavano dalla foto al caricamento, non si salvano:
    # sono la parte che cambierebbe se cambiasse il modo di confrontare.
    _occhiata: Any = field(default=None, repr=False, compare=False)


@dataclass
class Correzione:
    id: str
    testi: dict[str, dict[str, str]]
    viste: list[Vista]
    creata: str = ""
    modificata: str = ""
    # A quale bottiglia conosciuta e' stata collegata, se qualcuno l'ha scelta
    # dalla ricerca dell'editor: {"tipo": "archivio", "ambito": "vino",
    # "id": 510, "titolo": ...} oppure {"tipo": "carta", "titolo": ...}. Con un
    # collegamento la descrizione e' facoltativa: senza, si racconta la scheda
    # di quella bottiglia.
    riferimento: dict | None = None

    def testo_in(self, lingua: str) -> dict[str, str] | None:
        """Titolo e descrizione in questa lingua, se ci sono entrambi."""
        t = self.testi.get(lingua) or {}
        if t.get("titolo") and t.get("descrizione"):
            return t
        return None

    def titolo(self) -> str:
        """Un titolo qualunque, in qualunque lingua: serve a riempire l'editor."""
        for t in self.testi.values():
            if t.get("titolo"):
                return t["titolo"]
        return (self.riferimento or {}).get("titolo", "")

    def descrizione_in(self, lingua: str) -> str:
        """La descrizione scritta in questa lingua, anche senza titolo; o ""."""
        return (self.testi.get(lingua) or {}).get("descrizione", "")


@dataclass
class Riscontro:
    """Questa lettura e' quella bottiglia, e perche'."""

    correzione: Correzione
    parole: float
    parole_prese: int
    immagine: int

    @property
    def perche(self) -> str:
        return (f"parole {self.parole:.2f} ({self.parole_prese}), "
                f"immagine {self.immagine}")


# ---------------------------------------------------------------- archivio

class Correzioni:
    """Le correzioni sul disco, e il confronto con una lettura nuova."""

    def __init__(self, cartella: Path | str = CARTELLA_CORREZIONI,
                 regola: Regola = REGOLA) -> None:
        self.cartella = Path(cartella)
        self.regola = regola
        self._lucchetto = threading.RLock()
        self._occhio: _Occhio | None = None
        self._elenco: list[Correzione] = []
        self._carica()

    # --------------------------------------------------------- lettura

    def _vede(self) -> _Occhio | None:
        """L'occhio si crea al primo uso, e solo se OpenCV c'e'."""
        if self._occhio is None:
            try:
                self._occhio = _Occhio()
            except Exception as e:                          # noqa: BLE001
                log.warning("correzioni: confronto delle immagini non disponibile (%s)", e)
                return None
        return self._occhio

    def _carica(self) -> None:
        elenco = []
        if self.cartella.is_dir():
            for sotto in sorted(self.cartella.iterdir()):
                f = sotto / "correzione.json"
                if not f.is_file():
                    continue
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    elenco.append(Correzione(
                        id=d["id"], testi=d.get("testi", {}),
                        viste=[Vista(immagine=v["immagine"], righe=v.get("righe", []),
                                     parole=v.get("parole", []),
                                     zona=tuple(v["zona"]) if v.get("zona") else None,
                                     quando=v.get("quando", ""))
                               for v in d.get("viste", [])],
                        creata=d.get("creata", ""), modificata=d.get("modificata", ""),
                        riferimento=d.get("riferimento")))
                except (OSError, ValueError, KeyError) as e:
                    # Una correzione rovinata non deve fermare le altre.
                    log.warning("correzione illeggibile in %s: %s", sotto.name, e)
        with self._lucchetto:
            self._elenco = elenco
        if elenco:
            log.info("correzioni caricate: %d", len(elenco))

    def tutte(self) -> list[Correzione]:
        with self._lucchetto:
            return list(self._elenco)

    def trova(self, ident: str) -> Correzione | None:
        with self._lucchetto:
            return next((c for c in self._elenco if c.id == ident), None)

    def _occhiata(self, c: Correzione, v: Vista):
        """I descrittori di una vista, ricavati una volta sola."""
        if v._occhiata is None:
            occhio = self._vede()
            if occhio is None:
                return None
            import cv2
            immagine = cv2.imread(str(self.cartella / c.id / v.immagine))
            v._occhiata = occhio.descrivi(immagine, v.zona) or False
        return v._occhiata or None

    # --------------------------------------------------------- confronto

    def cerca(self, righe: Sequence[Any], immagine=None) -> Riscontro | None:
        """La correzione di questa bottiglia, se ce n'e' una. Altrimenti None.

        `righe` sono le `Riga` dell'OCR (col quadrilatero) oppure solo i testi:
        senza quadrilateri l'immagine non si guarda, e decidono le parole.
        """
        elenco = self.tutte()
        if not elenco:
            return None
        testi = [getattr(r, "testo", r) for r in righe]
        lette = parole_identificanti(testi)
        occhiata = None
        if immagine is not None and righe and hasattr(righe[0], "riquadro"):
            occhio = self._vede()
            if occhio is not None:
                zona = zona_etichetta(righe, immagine.shape[:2])
                occhiata = occhio.descrivi(immagine, zona)

        # Prima le parole, che costano niente: si guardano con l'immagine solo
        # le viste che ne condividono almeno una, le piu' vicine per prime.
        vicine = []
        for c in elenco:
            for v in c.viste:
                quota, prese = parole_in_comune(v.parole, lette)
                if prese:
                    vicine.append((quota, prese, c, v))
        vicine.sort(key=lambda x: (-x[0], -x[1]))

        migliore: Riscontro | None = None
        for quota, prese, c, v in vicine[:self.regola.viste_confrontate]:
            punti = 0
            if occhiata is not None:
                punti = self._vede().in_comune(self._occhiata(c, v), occhiata)
            r = Riscontro(c, quota, prese, punti)
            if not self._basta(r):
                continue
            if migliore is None or (r.immagine, r.parole) > (migliore.immagine, migliore.parole):
                migliore = r
        if migliore is not None:
            log.info("bottiglia corretta a mano riconosciuta: %s (%s)",
                     migliore.correzione.id, migliore.perche)
        return migliore

    def vicine(self, righe: Sequence[Any], quante: int = 3) -> list[Correzione]:
        """Le correzioni che somigliano a questa lettura senza bastare.

        Servono all'editor: se una bottiglia gia' corretta non e' stata
        riconosciuta - girata, o con una luce diversa - chi la ricorregge
        deve poter dire «e' questa», e aggiungerle una vista, invece di
        creare un doppione che la volta dopo si contenderebbe la bottiglia
        con l'originale. Decide una persona, quindi basta una parola in comune.
        """
        testi = [getattr(r, "testo", r) for r in righe]
        lette = parole_identificanti(testi)
        punteggi: dict[str, tuple[float, Correzione]] = {}
        for c in self.tutte():
            migliore = max((parole_in_comune(v.parole, lette)[0] for v in c.viste), default=0.0)
            if migliore > 0:
                punteggi[c.id] = (migliore, c)
        return [c for _, c in sorted(punteggi.values(), key=lambda x: -x[0])[:quante]]

    def foto(self, ident: str) -> Path | None:
        """La prima foto di una correzione, per riconoscerla a occhio."""
        c = self.trova(ident)
        if c is None or not c.viste:
            return None
        percorso = self.cartella / c.id / c.viste[0].immagine
        return percorso if percorso.is_file() else None

    def _basta(self, r: Riscontro) -> bool:
        g = self.regola
        if r.immagine >= g.immagine_da_sola:
            return True
        return (r.parole >= g.parole and r.parole_prese >= g.parole_minime
                and r.immagine >= g.immagine_con_parole)

    # --------------------------------------------------------- scrittura

    def salva(self, *, righe: Sequence[Any], immagine, titolo: str, descrizione: str,
              lingua: str, ident: str | None = None,
              riferimento: dict | None | object = ...) -> Correzione:
        """Scrive una correzione nuova, o aggiunge a una esistente.

        Aggiungere vuol dire due cose: il testo in questa lingua sostituisce
        quello di prima, e la foto di adesso diventa una vista IN PIU'. Piu'
        viste della stessa bottiglia, prese quando qualcuno ha confermato che
        e' lei, sono il modo onesto di riconoscerla meglio: girata un po' di
        piu', con un'altra luce.

        `riferimento` collega la bottiglia a una conosciuta (vedi il campo di
        `Correzione`); lasciato fuori, il collegamento che c'era resta, e
        `None` lo toglie. Con un collegamento la descrizione puo' mancare.
        """
        import cv2

        titolo = _pulito(titolo, 120)
        descrizione = _pulito(descrizione, 2000)
        if not titolo:
            raise ValueError("serve un titolo")
        ora = datetime.now()
        testi_righe = [getattr(r, "testo", r) for r in righe]
        with self._lucchetto:
            c = self.trova(ident) if ident else None
            collegata = (riferimento if riferimento is not ... else
                         (c.riferimento if c is not None else None))
            if not descrizione and not collegata:
                raise ValueError("senza un vino collegato serve una descrizione")
            if c is None:
                c = Correzione(id=self._nuovo_id(ora), testi={}, viste=[],
                               creata=ora.isoformat(timespec="seconds"))
                self._elenco.append(c)
            c.riferimento = collegata
            c.testi[lingua] = {"titolo": titolo, "descrizione": descrizione}
            c.modificata = ora.isoformat(timespec="seconds")
            cartella = self.cartella / c.id
            cartella.mkdir(parents=True, exist_ok=True)
            if immagine is not None:
                nome = f"vista-{len(c.viste) + 1}.jpg"
                if not cv2.imwrite(str(cartella / nome), immagine,
                                   [cv2.IMWRITE_JPEG_QUALITY, 92]):
                    raise OSError(f"foto non scritta in {cartella / nome}")
                _durevole_cartella(cartella)
                zona = (zona_etichetta(righe, immagine.shape[:2])
                        if righe and hasattr(righe[0], "riquadro") else None)
                c.viste.append(Vista(immagine=nome, righe=list(testi_righe),
                                     parole=parole_identificanti(testi_righe),
                                     zona=zona, quando=ora.isoformat(timespec="seconds")))
            self._scrivi(c)
        log.info("correzione salvata: %s (%s), %d viste", c.id, lingua, len(c.viste))
        return c

    def elimina(self, ident: str) -> bool:
        with self._lucchetto:
            c = self.trova(ident)
            if c is None:
                return False
            self._elenco.remove(c)
            cartella = self.cartella / c.id
            for f in cartella.glob("*"):
                f.unlink(missing_ok=True)
            try:
                cartella.rmdir()
            except OSError:
                pass
        log.info("correzione eliminata: %s", ident)
        return True

    def _nuovo_id(self, ora: datetime) -> str:
        base = ora.strftime("%Y%m%d-%H%M%S")
        ident, n = base, 1
        while (self.cartella / ident).exists() or self.trova(ident):
            n += 1
            ident = f"{base}-{n}"
        return ident

    def _scrivi(self, c: Correzione) -> None:
        """Scrittura atomica e durevole: il dispositivo si spegne togliendo la
        corrente, e un file troncato tornerebbe come correzione illeggibile."""
        d = {"id": c.id, "creata": c.creata, "modificata": c.modificata,
             "testi": c.testi, "riferimento": c.riferimento,
             "viste": [{"immagine": v.immagine, "righe": v.righe, "parole": v.parole,
                        "zona": list(v.zona) if v.zona else None, "quando": v.quando}
                       for v in c.viste]}
        cartella = self.cartella / c.id
        tmp = cartella / "correzione.json.parziale"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(cartella / "correzione.json")
        _durevole_cartella(cartella)


def _pulito(testo: str, massimo: int) -> str:
    """Spazi normalizzati, niente caratteri di controllo, lunghezza con un tetto."""
    testo = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(testo or ""))
    testo = re.sub(r"[ \t]+", " ", testo)
    testo = re.sub(r"\n{3,}", "\n\n", testo).strip()
    return testo[:massimo].strip()


def _durevole_cartella(cartella: Path) -> None:
    try:
        fd = os.open(cartella, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
