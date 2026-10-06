# Label recognition

How Amelie goes from a bottle set on the plate to a set of facts to tell: what decides that the
bottle is there, how the picture is taken, how the label is read, how the archive is searched and,
above all, when the device does **not** say a name. It is for anyone who wants to understand the
behaviour, tune it to their own installation or extend it. Everything runs on the board, with no
network; paths are relative to the repository root. What is told from the facts is described in
[07-storytelling.md](07-storytelling.md).

## The words you need

| term | what it means here |
|---|---|
| OCR | *optical character recognition*: the software that turns the image of a text into characters |
| appellation (*denominazione*) | the protected name of a production area and its wines, for example Barolo or Chianti Classico |
| DOP, IGP | the two European categories of wines tied to a place: protected designation of origin (PDO) and protected geographical indication (PGI) |
| DOCG, DOC, IGT | the Italian labelling terms: DOCG (controlled and guaranteed designation of origin) and DOC (controlled) are used for DOPs, IGT (typical geographical indication) for IGPs |
| *tipologia* | one of the wines an appellation provides for, with its name, colour and category: "Barolo Riserva" is a *tipologia* of the Barolo appellation |
| production specification (*disciplinare*) | the production rules of an appellation: required and permitted grapes, yields, and an official description of colour, aroma and taste |
| single document (*documento unico*) | the official summary of the production specification filed in the European Union register; the descriptions the story quotes come from there |
| grape variety (*vitigno*) | Nebbiolo, Sangiovese, Garganega… |
| archive | the SQLite database `data/amelie.db`, built from open sources (see "The archive") |
| confidence (*sicurezza*) | a score from 0 to 100: how far the device can stand behind what it is about to claim (see "The search") |

## The chain at a glance

```
distance sensor ──► "there is a bottle"                         bridge.Presenza
          │
camera running ──► silhouette against the empty plate ──► box   capture.PresenzaOttica
          │
sharp frame ──► crop ──► OCR                                    capture.Camera, ocr.Lettore
          │               └─ line on the edge? ──► widened re-read
          ▼
lines of text ──► hand correction? ── yes ──► that one is told  correzioni.Correzioni
          │ no
          ├── carta mode ──► Carta.cerca ──► wine list entry, or "not in the list"
          └── archivio, generativa modes ──► Matcher.cerca ──► cascade ──► Fatti ──► narrator
                                                                           └─ if in doubt: il_piu_generico
```

The flow follows the state machine in `src/amelie/state.py`:
`ATTESA → ASSESTAMENTO → SCANSIONE → RICONOSCIMENTO → RACCONTO → CONCLUSO` (waiting, settling,
scanning, recognition, story, finished). `ASSESTAMENTO` lasts 0.15 s, the time for the hand that
set the bottle down to leave the frame; `SCANSIONE` is capture and OCR; `RICONOSCIMENTO` is the
archive search. When nothing can be read, or what is read leads nowhere, the machine goes through
`RIPOSIZIONA` (reposition), which asks for the label to be turned and tries again; a technical
error leads to `GUASTO` (fault), which returns to waiting by itself. The work is done by two
methods of `Amelie` in `src/amelie/app.py`: `_scatta_e_leggi` (camera and OCR) and `_riconosci`
(corrections, wine list or archive).

| module | task |
|---|---|
| `src/amelie/bridge.py` | `Presenza`: the trigger from the distance sensor |
| `src/amelie/capture.py` | camera, exposure, sharpness, crop, bottle silhouette |
| `src/amelie/ocr.py` | reading with RapidOCR, fallback orientations, widened re-read |
| `src/amelie/text.py` | normalisation, useful words, vintage |
| `src/amelie/matcher.py` | archive search, cascade, confidence, rules on names |
| `src/amelie/carta.py` | recognition against a wine list in CSV |
| `src/amelie/correzioni.py` | bottles taught by hand: words and image points |

## Presence: the sensor decides, the camera looks

**The distance sensor is the only trigger.** It is a Modulino module with the VL53L4CD, a
time-of-flight sensor that measures distance with an infrared pulse; it sits on the Qwiic connector
of the UNO Q's microcontroller, and Linux reads it through the Arduino router, the service that
links Linux programs to the microcontroller on the board (`Ponte.distanza_mm`). `Amelie._chi_c_e`
reads the distance at every tick, that is every 0.05 s (`Configurazione.periodo_sensore_s`), and
passes it to `bridge.Presenza`, which applies asymmetric hysteresis: below `vicino_mm` (100 mm) for
3 readings in a row (`letture_per_arrivare`) the bottle has arrived; above `lontano_mm` (140 mm),
or with no valid measurement, for 5 readings in a row (`letture_per_andarsene`) it has gone; in
between it does not change its mind. The trigger therefore costs three ticks, 0.15 s. One scan too
many costs little; a story interrupted halfway is very noticeable.

**The camera says where the bottle is, not whether it is there.** Every 0.25 s
(`Configurazione.periodo_sbirciata_s`) `Amelie._guarda_il_piatto` takes a "peek": the whole frame,
straightened, in greyscale and scaled down to 96 × 170 pixels (`ImpostazioniCamera.sbirciata`). It
passes it to `capture.PresenzaOttica`:

- while waiting, when the sensor says the plate is empty, what is seen **is** the background:
  `non_e_una_bottiglia` learns it, and the app stores it in `var/sfondo.npy` to find it again
  after a restart (at most every 10 minutes, `RIPOSO_SFONDO_S`, and only if at least 20% of the
  pixels have changed, `SFONDO_DA_RISCRIVERE`);
- when the bottle is there, `PresenzaOttica.riquadro` derives its **silhouette** against the
  background: the changed pixels are those that differ from the background by more than 20 grey
  levels; it keeps the columns in which at least the fraction `FRAZIONE_SAGOMA` (0.25) of the
  pixels changed, then, within those columns, the rows with the same proportion. The rectangle
  that contains them is the bottle's box.

The silhouette is discarded, and the fixed crop is used instead, when it is not credible: fewer
columns than the fraction `LARGHEZZA_MINIMA` (0.12) of the width, fewer rows than
`ALTEZZA_MINIMA` (0.30) of the height, a box that is not taller than it is wide (measured in
fractions of the frame), or more than `SAGOMA_MASSIMA` (0.70) of the frame changed, a sign of a
change of scene or of light.

## The camera

`capture.Camera` looks for the USB camera by name (`ImpostazioniCamera.nome_camera`, `"U20CAM"`,
that is the InnoMaker U20CAM-1080P) among the stable links that Linux creates for video cameras in
`/dev/v4l/by-id` (`trova_camera`), because the order of the `/dev/videoN` devices changes from one
boot to the next; if those links are missing it queries every `/dev/video*` with `v4l2-ctl --info`,
and `ImpostazioniCamera.device` forces a specific path. It works in MJPEG (each frame compressed as
a JPEG) at 1920 × 1080.

- **It is mounted sideways**: a bottle is tall and narrow, and a 16:9 sensor turned on its side
  frames it lengthwise. Every frame is straightened by `ImpostazioniCamera.rotazione` (90°,
  clockwise) *before* any crop or measurement.
- **Exposure and white balance are manual** (`blocca_esposizione`, at startup: exposure 900, white
  balance at 4600 K, gain at zero): automatic is not repeatable.
- **The stream stays on** while the plate is being watched (`Camera.sorveglia`: a thread, the
  "guardian", reads frames continuously), because opening the camera costs much more than reading
  from an active stream. It is turned off while the voice speaks (`Camera.chiudi`), because camera
  and audio share the USB bus, and it is paused during the OCR (`Camera.in_pausa`) to leave the
  cores to the reading.

The capture has two paths.

- **With the stream running**, `Camera.al_volo` takes the first sufficiently sharp frame among
  those that arrived **after** the moment the bottle appeared, otherwise the sharpest one seen
  within one second: the settling is watched instead of waited out. Sharpness is the variance of the
  Laplacian on the crop, a measure of local contrast that rises when the image is in focus; the
  threshold is `SOGLIA_NITIDEZZA` (40).
- **With the stream stopped**, `_scatta_e_leggi` switches the LED ring to white and calls
  `Camera.scatta`, which waits 0.15 s for the light to settle (`assestamento_luce_s`), throws away
  the old frames left in the USB buffer (`fotogrammi_da_scartare`, 3), searches for the exposure
  and keeps the sharpest of a burst (`fotogrammi_raffica`, 3); then the ring goes back to the
  colour of the state.

The `Scatto` also carries the whole straightened frame and the position of the crop (`intero`,
`posto`).

## Exposure and light

The light that matters is the mean grey level **on the straightened crop**, that is, where the OCR
will look (`Camera._luce`). The target is `luce_cercata` (90 out of 255) with tolerance
`luce_tollerata` (8); outside that band the exposure is corrected:

```
posa_nuova = posa × (luce_cercata / luce) ^ esponente_posa      clamped to [posa_minima, posa_massima]
```

The exponent (1.5) accounts for the fact that light does not grow in proportion to exposure: the
sensor saturates on the bright spots. The guardian corrects one step at a time while the stream
runs, about once a second (`_ritocca_la_posa`), so when the bottle arrives the exposure is usually
already right; the capture with the stream stopped makes up to `ritocchi_posa` (3) corrections,
each verified by `_aspetta_la_posa` (two frames in a row with the same light, different from the
starting one). Exposure is measured in units of 100 µs: `posa_minima` is 300, `posa_massima` 4500.
The maximum is below the one declared by the camera (5000) because beyond a certain exposure the
camera stops delivering frames; if the stream stays silent with a long exposure, `_a_vuoto`
restarts from `posa_sicura` (900).

The LED ring shifts the mean light by a few levels, the exposure multiplies it: that is why the
ring goes white only for the burst of `scatta`. At the start of the reading,
`ocr._contrasto_normalizzato` applies CLAHE (*contrast limited adaptive histogram equalisation*: a
contrast stretch done region by region, with a limit that avoids amplifying noise) to the
luminance only, in the LAB colour space: it helps in extreme cases without touching the colours.

> Every test that involves light must also be done **with the room lights off**: that is the
> condition of a restaurant at dinner, and there the starting exposure alone is not enough.

## The crop

`Camera.posto` chooses the rectangle that goes to the OCR. If the silhouette is known
(`Camera.riquadro`) that is used, widened on the sides by `allarga_riquadro` (0.08 of its width):
with a hand holding the neck the silhouette may be shifted. Otherwise a fixed central crop of
`ritaglio_largo` (0.70 of the width) by `ritaglio_alto` (0.95 of the height) is used.

Two fractions and not one, because the two tasks lie on different axes: in width the crop is
narrowed to leave out the wall, which the detector reads as text (a calendar produces dozens of
lines, and each one costs time); in height almost everything is kept, because that is where the
label is. Narrowing too much does not help: recognition works on whole words, and a word missing
its first or last letter is often not found.

### The widened re-read

With bottles held in the hand the title often ends up against the edge of the crop.
`Lettore.allarga`, called by `Amelie._leggi_scatto`, looks for lines with at least 2 letters
(`LETTERE_DI_UNA_RIGA`) that come within `BORDO_CHE_TAGLIA` (3% of the width of the crop, and at
least 4 pixels) of the left or right edge, on a side where the crop does not already coincide with
the edge of the frame; lines made only of digits are not chased. If there are any, it re-reads the
crop **extended to the edge of the frame** on the side where they touch, at the same height and at
the same scale as the initial reading, and adds the lines of the initial reading that the re-read
does not find again. The widened image becomes the reference capture (it is the one a correction
keeps), and the log notes `"allargata": true`.

## The OCR

`ocr.Lettore` uses **RapidOCR**, an open-source library that runs the **PP-OCR** neural networks
(those of the PaddleOCR project) with ONNX Runtime, an engine for running neural networks on the
CPU. The networks are those of the v6 series in the "tiny" size, **PP-OCRv6 tiny**
(`ImpostazioniOCR.reti_piccole`), and there are two of them: the **detector**, which finds where the
text is and returns one quadrilateral per line, and the **recogniser**, which reads one line at a
time. Each quadrilateral is rectified for perspective before it is read: that way curvature and
foreshortening are compensated line by line.

**The image goes to the OCR in colour, at native resolution.** The networks are trained on three
channels, and on a gold-on-dark-red label the blue channel alone detects nothing. Greyscale is used
only for measuring (sharpness, light, silhouette, comparisons for corrections).

Reading happens **in two phases** (`_trova_e_leggi`):

1. **the text is found** on a scaled-down copy with the short side at `lato_rilevatore` (480 px):
   the detector's cost grows with the number of pixels, and 480 is the best measured value,
   because lower down letters are lost and higher up the detector costs more and gets worse again;
2. **each line is read**, cropped from the full-resolution image. The `righe_massime` (10) tallest
   lines are kept, because the appellation is written large and the sulphites small, and each line
   is brought to `altezza_riga` (48 px) with a cap of `larghezza_riga` (320 px).

The lines kept are those with confidence ≥ `confidenza_minima` (0.55) and at least
`lunghezza_minima` (2) characters long. RapidOCR's parameters are given **when the engine is
built** (`Lettore._carica`): passed at call time, they rebuild the engine at every frame, without
any warning.

**Orientation.** PP-OCR's orientation classifier is off (`usa_classificatore = False`) because the
frame arrives already straightened. If the mounting does not match `rotazione`, the OCR does not
degrade: it reads garbage. `Lettore.leggi_comunque` then tries the other three orientations, but
only when the initial reading has fewer than 2 useful words (`parole_che_sono_una_lettura`), fewer
than 8 lines (`righe_che_bastano`: more than that is a wall) and at least one letter; it stops as
soon as an orientation gives 3 useful words (`parole_che_bastano`).

Here a **useful word** is a line of at least three characters not made only of digits
(`_parole_utili` in `ocr.py`); it should not be confused with the useful words of
`text.parole_utili`, described below. A reading with none of these lines (`Lettura.utile` false) is
a failed attempt: after `TENTATIVI_MAX` (3) the device stops retrying and relearns the background,
because what it sees is not a label.

## From the text read to comparable words

In `src/amelie/text.py` three functions do the work.

- **`normalizza`** prepares the text for comparison: it removes accents and capitals, dissolves
  the dots in abbreviations (`_sciogli_punti`: "D.O.C.G." → `docg`, "F.lli" → `flli`, "13.5" →
  `135`), splits words on anything that is not a letter or a digit and maps OCR confusions back to
  letters (`0→o`, `1→l`, `5→s`, `8→b`, `6→g`, `2→z`), leaving words made only of digits untouched.
- **`parole_utili`** keeps the normalised words of at least three characters and removes
  `PAROLE_VUOTE`, the ones found on almost every label ("vino", "doc", "cantina", "tenuta",
  "riserva", "classico"…). The recogniser has a second list, `matcher.PAROLE_GENERICHE`: the
  words that say **what kind** of wine it is ("spumante", "brut", "rosso", "metodo") and not
  **which one**.
- **`estrai_annata`** looks for a year between 1900 (`ANNO_MINIMO`) and 2100, or a maximum year
  given by the caller, repairing letters disguised as digits ("2Ol7" → 2017) but requiring, on the
  repaired text, that the year is not attached to letters or digits. Among several years the most
  recent wins: the oldest is usually the year the winery was founded.

`data/build_db.py` contains a copy of `normalizza`, because it must run without the package
installed; `tests/test_build_db.py` checks that the two copies give the same result. If you change
the normalisation, change it in both places and regenerate the `*_norm` columns and the index with
`python3 scripts/reindicizza.py`, which does not touch the identifiers of the records.

## The archive

The archive is `data/amelie.db`, an SQLite database built from open sources with
`python3 data/build_db.py`; on the board it is run by `scripts/install.sh`, which also rebuilds it
when the sources or the code change. The file is not in the repository: it is rebuilt identically
from the sources versioned in `data/sources/`. `Matcher` opens it **read-only** and remembers what
it has already asked; if the file is missing, it raises `DatabaseAssente`.

### Where the data comes from

| source | file | what it provides | licence |
|---|---|---|---|
| figshare, Candiago et al. (2024) | `data/sources/PDO_wine_data_IT_FR.csv` | 408 Italian DOPs with their *tipologie*: colour, EU category, required and permitted grapes | CC BY 4.0 |
| X-Wines, de Azambuja et al. (2023) | `data/sources/xwines_italia.csv` | 19,358 Italian commercial wines: winery, region, grapes, food pairings, body, acidity | ODbL 1.0 (the most restrictive of those declared) |
| EU register eAmbrosia | `data/sources/eambrosia_it_wine.tsv` | the 532 Italian wine geographical indications: the 124 figshare lacks (119 IGPs and 5 DOPs) and the DOCG, DOC or IGT term of all of them | © European Union, CC BY 4.0 |
| EU single documents | `data/sources/documenti_unici.jsonl` | the official colour, aroma and taste of the *tipologie* | © European Union, CC BY 4.0 |
| list of the DOCGs | `data/sources/docg.txt` | which DOPs are DOCGs, which the EU register does not distinguish from DOCs | facts |
| the project | `data/vitigni.json`, `data/geografia.py` | the hand-written grape variety profiles, with their aliases; the region of each appellation | CC BY 4.0 (profiles), GPL-3.0-or-later (code) |

The built database is distributed under ODbL 1.0, because of X-Wines; attributions and mandatory
citations are in [08-attributions.md](08-attributions.md), the provenance of each file in
`data/sources/README.md`.

`build_db.py` proceeds in this order, and the order fixes the identifiers: the same sources give
the same numbers.

1. Appellations and DOP *tipologie* from figshare.
2. Commercial wines from X-Wines. Each wine is linked to the appellation from step 1 whose
   normalised name, the longest possible, is contained in the name of the wine or of its region:
   "Chianti Classico" beats "Chianti".
3. The profiles in `data/vitigni.json`, applied to the name of each grape variety and to its
   aliases, and the Italian names of the X-Wines grape varieties that are missing.
4. The appellations of the EU register that figshare lacks, and the term of all of them.
5. The region of each appellation, from the hand-written map in `data/geografia.py`; one the map
   cannot place stays empty.
6. The colour, aroma and taste of each *tipologia*, extracted from the single documents.
7. The normalised forms and the search index (`scripts/reindicizza.py`).
8. The ready-made stories (`scripts/genera_corpus.py`, see
   [07-storytelling.md](07-storytelling.md)); `--senza-racconti` skips this step.

The result, measured on the built database: 532 appellations (413 DOPs, of which 74 DOCG and 339
DOC, and 119 IGPs, all IGT), 4,301 *tipologie*, 19,358 commercial wines (13,829 linked to an
appellation), 618 grape varieties (223 with a hand-written profile), 2,223 official descriptions
for 515 appellations.

### The tables

| table | contents |
|---|---|
| `ricerca` | the full-text search index: normalised `testo`, `ambito`, `ambito_id`, `peso` |
| `vino` | commercial wines: name, winery, `*_norm` forms, region, type, alcohol content, body, acidity, `denominazione_id` |
| `denominazione` | DOPs and IGPs: name, EU file number, type (DOP or IGP), term (DOCG, DOC or IGT), region |
| `tipologia` | the *tipologie* of each appellation, with colour and EU category (still, sparkling, semi-sparkling, from dried grapes, fortified…) |
| `tipologia_vitigno` | grape varieties per *tipologia* with `ruolo`: `principale` (required by the production specification) or `ammesso` (permitted) |
| `tipologia_ue` | the official descriptions from the single documents (colour, aroma, taste), with `menzione` and `nome_incerto` (true when the name of the *tipologia* is reconstructed and must not be relied on) |
| `vitigno` | berry colour and hand-written profiles, in Italian and English |
| `vino_vitigno`, `vino_abbinamento` | grape varieties and food pairings of the commercial wines |
| `racconto` | the ready-made stories for *tipologie*, appellations and grape varieties, in both languages (used only by the `generativa` mode) |
| `fonte` | the sources, with licence and attribution |

`ricerca` is an FTS5 table, SQLite's full-text search extension: it has one row per record (24,809
in all) and four **scopes** (`ambito`): `vino` (winery plus name), `tipologia`, `denominazione`,
`vitigno`. The `peso` (weight) measures how specific the record is: 100 for a wine, 70 for an
appellation, 50 for a *tipologia*, 30 for a grape variety. The appellation weighs more than its
*tipologie* because "Barolo" read on a label is the appellation, not the first of its
*tipologie*. It is assigned by whatever builds the index (`scripts/reindicizza.py`, `PESO`). Rows
of a scope that the code does not know do not enter the contest (`Matcher.AMBITI`): the database
can be richer than the code.

## The search

`Matcher.cerca(righe)` is the entry point. It extracts the vintage (`estrai_annata`) and the useful
words of the whole reading (`text.parole_utili`); with no useful words, or no candidates, it
returns empty `Fatti()`, at the `nulla` level. The candidates are found in three steps
(`_candidati`):

1. **FTS5 with BM25** finds up to `CANDIDATI` (200) records that contain at least one of the
   useful words. BM25 is FTS5's ranking function: it weighs words by rarity, and a word present in
   hundreds of names counts for little.
2. **RapidFuzz**, a library for approximate string comparison that gives scores from 0 to 100,
   gives each one a **similarity** with `token_set_ratio`, a comparison between sets of words that
   is indifferent to word order and to extra words. The candidates are sorted by
   `somiglianza + peso/100`; a record identical to the whole normalised reading is worth 100 and
   gets 15 extra points (`Candidato.punteggio`).
3. **The verified confidence** (`_sicurezza_verificata`) replaces the similarity of *all* the
   non-identical candidates, and they are sorted again: verification lowers the scores, and a
   candidate left out would keep its inflated one.

Confidence measures the **claim**, not the string. The building block is coverage (`_copertura`):
each word of the record looks for the most similar word read using `fuzz.ratio` (RapidFuzz's
character-by-character comparison); below `RISCONTRO_PAROLA` (70) it counts as zero, each word read
confirms only one, and the result is the average over the words of the record.

- **A commercial wine** needs two confirmations, the name and the winery; without a winery it is
  worth 80% of the name coverage. The winery is tested only with its **own** words
  (`_prova_del_produttore`: the useful words of the winery minus those of its appellation). If they
  are not read, that is if their coverage over the useful words of the label stays below 70, the
  candidate has `produttore_letto = False` and is also worth 80% of the name coverage. If they are
  read it is worth `min(0.6·winery + 0.4·name, 1.15·winery, 1.6·name)`, multiplied by
  `min(1, 0.55 + 0.15·n)`, where `n` is the number of distinct words in the name and the winery.
- **The other scopes** are worth `token_set_ratio` multiplied by the same factor, with `n` the
  words of the record: a one-word record reaches at most 70, a three-word record 100.

Finally a **cap** depends on how many useful words the reading produced (`TETTO_PER_PAROLE`): 60
with one, 78 with two, 87 with three, none from four up. A single word can match 100% through set
arithmetic: **to be certain, at least four useful words are needed**.

The complete order of `Matcher.cerca`, after the candidates:

1. the cap by number of words, applied to all the candidates;
2. if the label declares a colour and the first candidate contradicts it, `_del_colore_giusto`
   goes down to the first candidate of that colour;
3. `_componi` builds the `Fatti` (facts) of the chosen candidate, with its confidence;
4. if the producer has not been read, `_senza_produttore` goes down to the wine without a winery;
5. `_non_oltre_cio_che_si_e_letto` goes down until the name to be said is all on the label, as
   far as the generic level (`_solo_l_etichetta`);
6. `_del_colore_dichiarato` corrects the step among the *tipologie* of the same appellation;
7. `_il_produttore_scritto` puts the winery back, if it has been read;
8. `_c_e_un_altro_produttore` lowers the confidence if two wineries have equal evidence;
9. the vintage, the fallback chain and up to three alternatives are added.

The rules of steps 2 and 4-8 are in "What has not been read is not named".

## The cascade and the thresholds

The answer is never "I don't know": the search goes down until it finds something true to say. The
examples are the opening sentences of the story in their reference form (the narrator chooses
among equivalent forms, see [07-storytelling.md](07-storytelling.md)); for `nulla`, the text on
the screen.

| level (`Livello`) | what is said | example |
|---|---|---|
| `vino` | a producer's wine, with name and winery | `This is the “Cannubi Barolo” by Marchesi di Barolo 2016 vintage.` |
| `tipologia` | a *tipologia* of an appellation | `This is a Barolo Riserva.` |
| `denominazione` | the appellation | `This is Barolo, a protected designation of origin.` |
| `vitigno` | the grape variety | `The grape is Nebbiolo.` |
| `generico` | only what is written on the label | `This is a rosé sparkling wine metodo classico, brut.` |
| `nulla` | nothing: the screen asks for the label to be turned and it tries again | `Could you turn the label towards me?` |

`catena_di_ripiego` gives the steps of each record: a wine goes down to its *tipologia*
(`_tipologia_del_vino`, which respects the colour written in the name and prefers the *tipologie*
with bubbles when the name declares them), then to the appellation, then to the first of its grape
varieties, if that has a profile; a *tipologia* goes down to the appellation and to the grape
variety; an appellation to the grape variety.

The two thresholds are in `src/amelie/matcher.py`.

| confidence | in `Fatti` | what `Amelie._riconosci` does |
|---|---|---|
| ≥ `SOGLIA_CERTA` (88) | `certo` | tells the story, with an affirmative opening |
| from `SOGLIA_DUBBIA` (75) to 88 | `dubbio` | goes through `il_piu_generico`, then tells the story |
| below 75, level not `nulla` | — | tells the story; for wine, *tipologia* and grape variety the opening declares it a guess |
| level `nulla` | `vuoto` | asks for the label to be turned and tries again; after `TENTATIVI_MAX` (3) attempts it stops |

**Doubt is not put to the guest.** `Matcher.il_piu_generico` takes, among the first candidate and
the alternatives, the one with the most general level according to `GENERALITA` (wine,
*tipologia*, appellation, grape variety, generic); on a tie the first one stays. If instead the
first is a wine with its winery and among the alternatives there is a wine from another winery,
the doubt is the winery, and it goes down to the same wine without a producer. The alternatives (at
most three, distinct from each other, of the right colour and with all their identifying words
read) remain in the `Fatti` and in the log.

After `TENTATIVI_MAX` attempts without a result the device stops retrying: if "Add corrections" is
on and at least one identifying word has been read, the screen says "I couldn't recognise this
bottle." and offers "Help me recognise it"; otherwise it returns to the waiting screen. It tries
again when the bottle is removed and put back.

## What has not been read is not named

This is the rule that holds up all of recognition: a name spoken aloud at a table is a claim about
a real company or a real place, and getting it wrong is worse than saying something vague.

- **The producer.** A wine is attributed to a producer only if the producer's own words are on the
  label; the appellation's words are on anyone's bottle. Without that proof `_senza_produttore`
  goes down to the next step of the chain: a label that says only "Primitivo di Manduria" is told
  as Primitivo di Manduria, not as the wine of one of its many producers.
- **All names.** `_non_oltre_cio_che_si_e_letto` goes down the chain until the **identifying**
  words of the record (useful words minus `PAROLE_GENERICHE`) are all on the label, each with a
  match ≥ 70 on a different word read (`_tutto_letto`). A similarity threshold cannot do this job:
  the similarities of correct recognitions and of inventions overlap, the words read do not.
- **The generic level.** If no step holds, `_solo_l_etichetta` says the declared colour, the
  category deduced from the words read (`CATEGORIA_DETTA`: "spumante", "metodo", "frizzante",
  "passito"…) and the qualifiers in the order in which they are spoken (`ORDINE_QUALIFICATORI`).
  The confidence stays below certainty and below the cap by number of words. At this level the
  language model never writes.
- **The declared colour.** If the label declares a single colour (`COLORE_DETTO`: "rosato",
  "rosé", "rosso", "bianco" and their foreign forms), no record of a different colour can be that
  bottle: `_del_colore_giusto` goes down among the first `CANDIDATI_PER_COLORE` (16) until it finds
  one of that colour, except when the appellation of the first has a sister *tipologia* of that
  colour whose name has been read in full; `_del_colore_dichiarato` then corrects the step among
  the sister *tipologie* of the same appellation. "Nero" and "rosa" do not count as colours (they
  are parts of grape variety names); two different colours read together count as none.
- **The producer without the wine.** When there is no winery in the facts, usually because the
  cascade went below the wine level, `_il_produttore_scritto` puts it back only if its own words
  (at least four letters, not generic, not in the name of a candidate wine, not place names) are
  read with coverage ≥ `PRODUTTORE_SCRITTO` (90), belong only to that winery in the archive, and
  only one producer passes the test.
- **Two producers with equal evidence.** If the first candidate is the wine of one winery and among
  the first `RIVALI` (6) there is the wine of another winery within `MARGINE_PRODUTTORE` (3
  points), the confidence drops just below certainty (87.5): the recognition becomes doubtful and
  goes through `il_piu_generico`.
- **Namesake cooperatives.** A producer named after its own appellation has no words of its own:
  it cannot be proved, and its bottles are told without a producer, at the level of the
  *tipologia* or of the appellation.
- **Quotations from the production specification.** `_disciplinare` assigns the descriptions from
  `tipologia_ue` by narrowing down, not by resemblance: same colour, same kind of product
  (`PRODOTTO_DIVERSO`: passito, liquoroso, recioto, vendemmia tardiva…), then identical name if
  reliable, then grape varieties and qualifiers. If what remains says the same thing it is quoted;
  otherwise nothing is said.

## Wine list mode

With `--carta vini.csv` and the "Wine list" mode chosen in the settings, the device recognises the
titles of a file written by the venue (`src/amelie/carta.py`); the system service loads
`/home/arduino/amelie/vini.csv`. Columns `titolo` (title) and `descrizione` (description), plus
`titolo_xx` and `descrizione_xx` for each other language (`xx` is the two-letter code):

```csv
titolo,descrizione,titolo_en,descrizione_en
Barolo DOCG,"Il testo che il dispositivo legge.",Barolo DOCG,"The text it reads."
```

`Carta.cerca` has no cascade: the wine list either has the entry or it does not. A title is
admitted if:

- the similarity (`_somiglianza`) is at least `SOMIGLIANZA_MINIMA` (55). For readings that come in
  pieces there is a word-by-word measure, valid only if the title has at least two words, finds
  them all with a match ≥ `RISCONTRO_PEZZO` (75) and at least one of them is read exactly, is not
  generic and is at least `ESATTA_CHE_PROVA` (4) letters long;
- each of its words of at least three characters is on the label (match ≥ 70), except the
  `TACITE` (DOC, DOCG, IGT, the other appellation abbreviations and "annata") and the **implied**
  ones (`Carta._implicate`: present in all the entries that contain the identifying words read).
  "Riserva" or "Extra Brut" in the title must be read;
- the implied words that were not read do not outnumber the identifying words that were read.

Among the admitted titles the one with the most words read wins, then the one with the fewest
words not read, then similarity. If none passes, the reading counts as a failed attempt, the guest
is asked to turn the label and the log notes the closest entries (`Carta.vicine`). When a title
passes, the archive is also queried, to tell the story in the languages the wine list does not
have.

## Hand corrections

With "Add corrections" on, the staff in the room can teach the device a bottle: a title and a
description, which becomes optional if the bottle is linked to an archive record or to a wine list
entry. `Correzioni` stores in `var/correzioni/<id>/` the `correzione.json` file and one photo per
**view**, with the lines read and the label area. Corrections are looked up **first**, in every
storytelling mode (`Amelie._cerca_correzione`), with two signals:

- **the words**: `parole_identificanti` (at least four letters, letters only, not generic)
  remembered and read again, with `fuzz.ratio` ≥ 80 and one word read for each;
- **the image**: ORB points found again in a consistent position. ORB is an algorithm that finds
  distinctive points in a photo and describes them so that they can be found again in another
  photo; a match counts only if it is clearly better than the second best (the "ratio test"), and
  the points kept are those consistent with a single perspective transformation between the two
  photos (a homography estimated with RANSAC, which discards scattered matches). The points are
  searched **only in the label area** (`zona_etichetta`), because the background of the room is the
  same in all the photos and would make different bottles look alike.

The thresholds, in `Regola`, are tuned so that two different bottles are never mistaken for each
other, at the cost of some missed recognitions: a share of words `parole` (0.6) with at least
`parole_minime` (2) and `immagine_con_parole` (16) points, or `immagine_da_sola` (30) points; at
most `viste_confrontate` (6) views are compared, among those with at least one word in common.
Correcting the same bottle again adds a view, and helps it be recognised under different lighting
and angles.

## The bottle swapped during the story

If the sensor sees a bottle arrive while a story is being told, `Amelie._anticipa` reads it in a
separate thread **without stopping the voice** (`_decidi_in_anticipo`):

1. it waits for the settling (0.15 s), takes a picture (up to 1.5 s for a sharp frame) and
   compares the label area of the previous photo with the new photo
   (`Correzioni.punti_in_comune`): with at least `STESSA_A_OCCHIO` (25) points it is the same
   bottle;
2. otherwise it reads, and `_e_un_altra` decides: the same identifying words (with the
   corrections' `Regola`) mean the same bottle; otherwise what would be told (a correction, a wine
   list entry, an archive record) is compared with what is being told, and if it differs it is a
   different bottle; with no identifying words it does not decide, and the bottle is read again
   when the story is over;
3. if it is a different one, the voice stops (`Evento.CAMBIO_BOTTIGLIA`) and `_scatta_e_leggi`
   reuses the reading already done, as long as it is not older than `ANTICIPO_VALIDO_S` (30 s).

The photo can say "it's the same one" but not "it's a different one": a bottle put back turned
around matches few points, and the text is needed. A bottle removed during the story does not
interrupt it.

## How it is measured

**The OCR benchmark.** `scripts/bench_ocr.py` reads the 139 photographed Italian labels from the
X-Wines dataset, with winery, name and vintages known in `tests/etichette/manifesto.csv`. The
photos are not in the repository (they are third-party graphic works): download X-Wines into
`data/sources/X-Wines_Official_Repository/` and regenerate the set.

```bash
python3 data/estrai_xwines.py --estrai-immagini
python3 scripts/bench_ocr.py --lato 480 --salva /tmp/ocr.json     # -n N for the first N
python3 scripts/bench_matcher.py /tmp/ocr.json
```

The script's default side is the device's (`lato_rilevatore = 480`); `--lato` tries another one,
`--thread` changes the number of threads. The benchmark prints how many times winery and wine name
are found in the text read (`partial_ratio` ≥ 80, that is the best match between a part of the
text and the expected name), how many times at least one of the two, the plausible vintages, the
silent labels, the average number of lines, the time per label and the five worst. On the PC it
measures quality; on the board, with the service's Python environment (`venv/bin/python`), time as
well. It uses `Lettore.leggi` on **flat, frontal** photos, without fallback orientations or widened
re-read: it is an upper bound.

**The recognition benchmark.** `scripts/bench_matcher.py` passes that text to `Matcher.cerca`,
applies `il_piu_generico` to doubtful recognitions as the device does, and compares what would be
said with the known record: **consistent** (`coerente`: what is said checks out, even if it went
down a level), **inconsistent** (`INCOERENTE`), and **of which declared certain**
(`di cui DICHIARATE CERTE`), that is, inconsistent above `SOGLIA_CERTA`. This last line **must
stay at zero**: those are told as facts. Then come the distribution by level (from `vino` to
`nulla`, plus the labels with no text), the distribution by confidence band, counted before
`il_piu_generico`, and a few examples of inconsistent recognitions.

**On the device.**

- **The log** (`src/amelie/giornale.py`) records each scan in `var/scansioni/giornale.jsonl` with
  the frame next to it: lines read, capture and OCR times, sharpness, exposure, `allargata`,
  `anticipata`, level, confidence, names, colour, candidates, `scelto_il_piu_generico`,
  `perche_correzione`, in wine list mode the `vicine`, and the story told with its origin
  (`racconto_da`). It can also be read from `GET /giornale?quante=N` and `GET /giornale/<nome>`.
- **The viewfinder** shows live the frame, the crop, the sharpness, the reading and the
  recognition; it is turned on with the "Debug camera" switch in the settings, which open by
  holding the bottom-right corner of the screen for three seconds. `scripts/mirino.py`, with the
  service stopped, does the same in a browser (port 8090) and accepts `--esposizione`,
  `--ritaglio`, `--ritaglio-alto`, `--luce`, `--ocr`.
- **`POST /prova/bottiglia`** simulates a bottle on the plate (`/prova/via` removes it,
  `/prova/camera` goes back to the sensor), to test reading and recognition without the sensor.
- **The tests** (`tests/test_matcher.py`, `test_ocr.py`, `test_carta.py`,
  `test_cambio_bottiglia.py`…) are skipped instead of failing when what they need is missing: the
  database or `rapidfuzz` for recognition, OpenCV and NumPy for the bottle swap.

Aggregate numbers are not enough: every change to a threshold must be replayed on **all** the test
labels and on the real readings in the log, and every difference must be reread by hand. A
tolerance that fixes one case often breaks others, and this is the only way to see it.

## How to tune it

Change one parameter at a time, measure again with the benchmarks and with the log, and check that
the "declared certain" stay at zero.

| where | parameter (default) | when to touch it |
|---|---|---|
| `ImpostazioniCamera` | `nome_camera` (`"U20CAM"`), `device` (none) | a camera of another model |
| `ImpostazioniCamera` | `rotazione` (90) | the camera is mounted the other way |
| `ImpostazioniCamera` | `esposizione` (900), `posa_massima` (4500) | very dark room or a different camera |
| `ImpostazioniCamera` | `luce_cercata` (90), `luce_tollerata` (8) | labels blown out or too dark |
| `ImpostazioniCamera` | `ritaglio_largo` (0.70), `ritaglio_alto` (0.95), `allarga_riquadro` (0.08) | the wall gets in, or words get cut off |
| `capture.py` | `SOGLIA_NITIDEZZA` (40), `FRAZIONE_SAGOMA` (0.25), `SAGOMA_MASSIMA` (0.70) | blurry frames, wrong silhouettes |
| `bridge.Presenza` | `vicino_mm` (100), `lontano_mm` (140) | different geometry between plate and sensor |
| `ImpostazioniOCR` | `lato_rilevatore` (480), `righe_massime` (10) | trade-off between letters read and time |
| `ImpostazioniOCR` | `confidenza_minima` (0.55), `usa_classificatore` (false) | noise; frame not straightened |
| `ocr.py` | `BORDO_CHE_TAGLIA` (0.03) | when the widened re-read kicks in |
| `matcher.py` | `SOGLIA_CERTA` (88), `SOGLIA_DUBBIA` (75), `TETTO_PER_PAROLE` (60, 78, 87) | how much is claimed |
| `matcher.py` | `RISCONTRO_PAROLA` (70), `PRODUTTORE_SCRITTO` (90), `MARGINE_PRODUTTORE` (3) | tests on names |
| `matcher.py`, `text.py` | `PAROLE_GENERICHE`, `COLORE_DETTO`, `PRODOTTO_DIVERSO`, `PAROLE_VUOTE` | vocabulary of the rules |
| `carta.py` | `SOMIGLIANZA_MINIMA` (55), `RISCONTRO_PEZZO` (75), `TACITE` | strictness of the wine list |
| `correzioni.py` | `Regola` | strictness of the corrections |
| `app.py` | `TENTATIVI_MAX` (3), `STESSA_A_OCCHIO` (25) | attempts; "it's the same bottle" |

To extend recognition to a new type of record you need the rows in the `ricerca` index, the scope
in `Matcher.AMBITI`, a `Livello` with its place in `LIVELLO_DELL_AMBITO` and `GENERALITA`, and a
builder in `Matcher._componi`: until the code knows it, its rows stay out of the contest.

## Known limitations

- **Pale glass.** The distance sensor works in infrared, which passes through the bottom of a pale
  bottle and does not come back: the bottle is not seen and the scan does not start. The remedy
  lies in the signal threshold of the VL53L4CD, in the microcontroller's firmware.
- **Curved labels.** On the sides of the cylinder the letters get narrower and are lost: per-line
  rectification compensates for foreshortening, not for what the glass hides, and the widened
  re-read only recovers what the crop cut off.
- **Reflections and darkness.** A specular reflection burns out the letters it covers (the exposure
  looks at the mean light, and CLAHE does not rebuild a saturated spot); in the dark long exposures
  are needed, and a bottle held in the hand moves, so the sharpest frame may not be sharp enough.
- **Decorative typefaces and dense patterns.** Ornate scripts and patterned backgrounds confuse the
  detector even when the label is readable by eye; if the wine name is decorative, recognition
  goes down to the *tipologia* or the appellation.
- **Vintage.** It is often on the neck label, out of frame or too small: then it is not said.
- **Writing behind the plate.** A wall with text on it adds lines and time; a narrow crop and the
  learned background limit this.
- **Archive coverage.** What is in the archive is recognised; the rest gets as far as the
  appellation or the generic level, or is taught with a correction. Cooperatives named after their
  own appellation are always told without a producer.
- **Mounting orientation.** If `rotazione` does not match the mounting, the label is still read, by
  trying the other orientations, but with more readings per scan.
