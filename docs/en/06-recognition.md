# Label recognition

How Amelie goes from a bottle set on the plate to a set of facts to tell: what decides
that the bottle is there, how the picture is taken, how the label is read, how the database is
searched and, above all, when the device does **not** say a name. It is for anyone who wants to
understand the behavior, tune it to their own installation or extend it. Everything runs on the
board, with no network; paths are relative to the repository root.

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
          ├── wine list mode ──► Carta.cerca ──► entry, or "not in the list"
          └── archive ──► Matcher.cerca ──► cascade ──► Fatti ──► narrator
                                                         └─ if in doubt: il_piu_generico
```

The flow follows the state machine in `src/amelie/state.py`:
`ATTESA → ASSESTAMENTO → SCANSIONE → RICONOSCIMENTO → RACCONTO` (waiting, settling, scanning,
recognition, story), with `RIPOSIZIONA` (reposition) when nothing can be read. The work is done
by two methods of `Amelie` in `src/amelie/app.py`: `_scatta_e_leggi` (camera and OCR) and
`_riconosci` (corrections, wine list or archive).

| module | task |
|---|---|
| `src/amelie/bridge.py` | `Presenza`: the trigger from the distance sensor |
| `src/amelie/capture.py` | camera, exposure, sharpness, crop, bottle silhouette |
| `src/amelie/ocr.py` | reading with RapidOCR, fallback orientations, widened re-read |
| `src/amelie/text.py` | normalization, useful words, vintage |
| `src/amelie/matcher.py` | database search, cascade, confidence, rules on names |
| `src/amelie/carta.py` | recognition against a wine list in CSV |
| `src/amelie/correzioni.py` | bottles taught by hand: words and image points |

## Presence: the sensor decides, the camera looks

**The distance sensor is the only trigger.** `Amelie._chi_c_e` reads the distance at every tick
and passes it to `bridge.Presenza`, which applies asymmetric hysteresis: below `vicino_mm`
(100 mm) for 3 readings in a row the bottle has arrived; above `lontano_mm` (140 mm), or with no
measurement, for 5 readings in a row it has gone; in between it does not change its mind. One scan
too many costs little; a story interrupted halfway is very noticeable.

**The camera says where the bottle is, not whether it is there.** `Amelie._guarda_il_piatto`
takes a "peek" at intervals (the whole frame, in grayscale and downscaled) and passes it to
`capture.PresenzaOttica`:

- when the sensor says the plate is empty, what is seen **is** the background:
  `non_e_una_bottiglia` learns it, and the app stores it in `var/sfondo.npy`;
- when the bottle is there, `PresenzaOttica.riquadro` derives its **silhouette** against the
  background: the columns changed by at least `FRAZIONE_SAGOMA` (0.25), then the rows changed
  within those.

The silhouette is discarded, and the fixed crop is used instead, when it is not credible: narrower
than `LARGHEZZA_MINIMA` (0.12 of the frame), shorter than `ALTEZZA_MINIMA` (0.30), wider than
tall, or with more than `SAGOMA_MASSIMA` (0.70) of the frame changed, a sign of a change of scene
or of light.

## The camera

`capture.Camera` finds the USB camera by name among the stable links in `/dev/v4l/by-id`
(`trova_camera`), because the order of `/dev/videoN` changes from one boot to the next, and works
in MJPEG at 1920×1080.

- **It is mounted sideways**: a bottle is tall and narrow, and a rotated 16:9 sensor frames it
  lengthwise. Every frame is straightened with `ImpostazioniCamera.rotazione` (90°) *before* any
  crop or measurement.
- **Exposure and white balance are manual** (`blocca_esposizione`), with gain at zero: automatic
  is not repeatable.
- **The stream stays on** while the plate is being watched (`Camera.sorveglia`, the "guardian"),
  because opening the camera costs much more than reading from an active stream. It is turned off
  while the voice speaks (`Camera.chiudi`), because camera and audio share the USB bus, and it is
  paused during the OCR (`Camera.in_pausa`) to leave the cores to the reading.

The capture has two paths. `Camera.al_volo`, with the stream running, takes the first frame that
arrived **after** the moment the bottle appeared and is sharp enough (variance of the
Laplacian on the crop ≥ `SOGLIA_NITIDEZZA`, 40), otherwise the sharpest one seen within the
maximum wait: the settling is watched instead of waited out. With the stream stopped,
`_scatta_e_leggi` switches the ring to white and calls `Camera.scatta`, which throws away the old
frames in the USB buffer (`fotogrammi_da_scartare`), searches for the exposure and keeps the
sharpest of a burst (`fotogrammi_raffica`). The `Scatto` also carries the whole
straightened frame and the position of the crop (`intero`, `posto`).

## Exposure and light

The light that matters is the mean gray level **on the straightened crop**, that is, where the OCR
will look (`Camera._luce`). The target is `luce_cercata` (90 out of 255) with tolerance
`luce_tollerata` (8); outside that band the exposure is corrected:

```
posa_nuova = posa × (luce_cercata / luce) ^ esponente_posa      clamped to [posa_minima, posa_massima]
```

The exponent (1.5) accounts for the fact that light does not grow in proportion to exposure: the
sensor saturates on the bright spots. The guardian corrects one step at a time while the stream
runs (`_ritocca_la_posa`), so when the bottle arrives the exposure is usually already right; the
capture with the camera stopped makes up to `ritocchi_posa` corrections, each verified by
`_aspetta_la_posa` (two frames in a row with the same light, different from the starting one).
`posa_massima` (4500, in units of 100 µs) is below the maximum declared by the camera, because
beyond a certain exposure the camera stops delivering frames; if the stream stays silent with a
long exposure, `_a_vuoto` restarts from `posa_sicura`.

The LED ring shifts the mean light by a few levels, the exposure multiplies it: that is why the
ring goes white only for the burst of `scatta`. At the start of the reading,
`ocr._contrasto_normalizzato` applies CLAHE to the luminance only (LAB space), which helps in
extreme cases without touching the colors.

> Every test that involves light must also be done **with the room lights off**: that is the
> condition of a restaurant at dinner, and there the starting exposure alone is not enough.

## The crop

`Camera.posto` chooses the rectangle that goes to the OCR. If the silhouette is known
(`Camera.riquadro`) that is used, widened on the sides by `allarga_riquadro` (0.08 of its width):
with a hand holding the neck the silhouette may be shifted. Otherwise a fixed central crop of
`ritaglio_largo` (0.70) by `ritaglio_alto` (0.95) is used.

Two fractions and not one, because the two tasks lie on different axes: in width the crop is
narrowed to leave out the wall, which the detector reads as text (a calendar produces dozens of
lines, and each one costs time); in height almost everything is kept, because that is where the
label is. Narrowing too much does not help: recognition works on whole words, and a word missing
its first or last letter is often not found.

### The widened re-read

With bottles held in the hand the title often ends up against the edge of the crop.
`Lettore.allarga`, called by `Amelie._leggi_scatto`, looks for lines with at least 2 letters
(`LETTERE_DI_UNA_RIGA`) that come within `BORDO_CHE_TAGLIA` (3% of the width) of the left or
right edge; lines made only of digits are not chased. If there are any, it re-reads the crop
**extended to the edge of the frame** on the side where they touch, at the same height and at the
same scale as the initial reading, and adds the lines of the initial reading that the re-read does
not find again. The widened image becomes the reference capture (it is the one a correction
keeps), and the log notes `"allargata": true`.

## The OCR

`ocr.Lettore` uses **RapidOCR** with the **PP-OCRv6 tiny** models on ONNX Runtime
(`ImpostazioniOCR.reti_piccole`). The detector gives one quadrilateral per line, which is rectified
for perspective and then read: that way curvature and foreshortening are compensated line by line.

**The image goes to the OCR in color, at native resolution.** The models are trained on three
channels, and on a gold-on-dark-red label the blue channel alone detects nothing. Grayscale is used
only for measuring (sharpness, light, silhouette, comparisons for corrections).

Reading happens **in two phases** (`_trova_e_leggi`):

1. **the text is found** on a downscaled copy with the short side at `lato_rilevatore` (480 px):
   the detector's cost grows with the number of pixels, and beyond a certain scale the detector
   gets worse;
2. **each line is read**, cropped from the full-resolution image. The `righe_massime` (10) tallest
   lines are kept, because the appellation is written large and the sulfites small, and each line
   is brought to `altezza_riga` (48 px) with a cap of `larghezza_riga` (320 px).

The lines kept are those with confidence ≥ `confidenza_minima` (0.55) and at least 2 characters
long. RapidOCR's parameters are given **when the engine is built** (`Lettore._carica`): passed at
call time, they rebuild the engine at every frame, without any warning.

**Orientation.** The orientation classifier is off (`usa_classificatore = False`) because the
frame arrives already straightened. If the mounting does not match `rotazione`, the OCR does not
degrade: it reads garbage. `Lettore.leggi_comunque` then tries the other three orientations, but
only when the initial reading has fewer than 2 useful words (`parole_che_sono_una_lettura`), fewer
than 8 lines (`righe_che_bastano`: more than that is a wall) and at least one letter; it stops as
soon as an orientation gives 3 useful words (`parole_che_bastano`).

A **useful word** is a line of at least three characters that are not all digits. A reading with
no useful words (`Lettura.utile` false) is a failed attempt: after `TENTATIVI_MAX` (3) the device
stops retrying and relearns the background, because what it sees is not a label.

## From the text read to comparable words

In `src/amelie/text.py` three functions do the work.

- **`normalizza`** prepares the text for comparison: it removes accents and capitals, dissolves the
  dots in abbreviations (`_sciogli_punti`: "D.O.C.G." → `docg`, "F.lli" → `flli`, "13.5" → `135`)
  and maps OCR confusions back to letters (`0→o`, `1→l`, `5→s`, `8→b`, `6→g`, `2→z`), leaving
  tokens made only of digits untouched.
- **`parole_utili`** keeps the words of at least three letters and removes `PAROLE_VUOTE`, the ones
  found on almost every label ("vino", "doc", "cantina", "tenuta", "riserva", "classico"…). The
  recognizer has a second list, `matcher.PAROLE_GENERICHE`: the words that say **what kind** of
  wine it is ("spumante", "brut", "rosso", "metodo") and not **which one**.
- **`estrai_annata`** looks for a year between 1900 and the maximum year, repairing letters
  disguised as digits ("2Ol7" → 2017) but requiring non-alphanumeric boundaries on the repaired
  text. Among several years the most recent wins: the oldest is usually the year the winery was
  founded.

`data/build_db.py` contains a copy of `normalizza`, kept aligned by
`tests/test_build_db.py`. If you change the normalization, regenerate the `*_norm` columns and the
index with `python3 scripts/reindicizza.py`.

## The database

The archive is `data/amelie.db`, an SQLite database built from open sources with
`python3 data/build_db.py`. `Matcher` opens it **read-only** and remembers what it has already
asked; if it is missing, it raises `DatabaseAssente`. The tables read by recognition:

| table | contents |
|---|---|
| `ricerca` | FTS5 index: normalized `testo`, `ambito`, `ambito_id`, `peso` |
| `vino` | commercial wines: name, winery, `*_norm` forms, region, type, alcohol content, `denominazione_id` |
| `denominazione` | DOP and IGP (the EU's PDO and PGI, protected designation of origin and protected geographical indication): name, type, region |
| `tipologia` | the *tipologie* (wine types within an appellation) of each appellation (*denominazione*), with color and EU category |
| `tipologia_vitigno` | grape varieties per tipologia with `ruolo`: `principale` (required) or `ammesso` (permitted) |
| `tipologia_ue` | official descriptions from the production specification (*disciplinare*: color, aroma, taste), with `menzione` and `nome_incerto` |
| `vitigno` | berry color and hand-written profiles, in Italian and English |
| `vino_vitigno`, `vino_abbinamento` | grape varieties and food pairings of the commercial wines |

`ricerca` has one row per record and four **scopes** (`ambito`): `vino` (winery plus name),
`tipologia`, `denominazione`, `vitigno`. The `peso` measures specificity, from the wine (the
highest) down to the grape variety; it is assigned by whatever builds the index
(`scripts/reindicizza.py`). Rows of a scope that the code does not know do not enter the contest
(`Matcher.AMBITI`): the database can be richer than the code.

## The search

`Matcher.cerca(righe)` is the entry point; with no useful words it returns empty `Fatti()`.

1. **FTS5 with BM25** finds up to `CANDIDATI` (200) records by searching for the useful words
   joined with OR. BM25 weighs words by rarity: a word present in hundreds of names counts for
   little.
2. **RapidFuzz** gives each one a similarity (`token_set_ratio`, indifferent to word order and to
   extra words). They are sorted by `somiglianza + peso/100`, with a bonus for an exact match.
3. **The verified confidence** (`_sicurezza_verificata`) is recomputed on *all* the candidates:
   verification lowers the scores, and any candidate left out would keep its inflated one.

Confidence measures the **claim**, not the string. For a commercial wine `_copertura`
looks for each word of the name among those read (`fuzz.ratio`; below `RISCONTRO_PAROLA`, 70, it
counts as zero; each word read confirms only one). The winery is tested only with its **own**
words (`_prova_del_produttore`: the winery's words minus those of the appellation): if they are
not read the candidate is `produttore_letto = False` and is worth 80% of the name coverage; if
they are read it is worth `min(0.6·winery + 0.4·name, 1.15·winery, 1.6·name)`, scaled on the
number of words in the record. For the other scopes confidence is `token_set_ratio` scaled on the
length of the record (`min(1, 0.55 + 0.15·words)`).

Finally a **cap** depends on how many useful words the OCR produced (`TETTO_PER_PAROLE`): 60 with
one, 78 with two, 87 with three, none from four up. A single word can match 100% through set
arithmetic: **to be certain, at least four useful words are needed**.

## The cascade and the thresholds

The answer is never "I don't know": the search goes down until it finds something true to say.

| level (`Livello`) | what is said |
|---|---|
| `vino` | a producer's wine, with name and winery |
| `tipologia` | "it's a Barolo Riserva" |
| `denominazione` | "it's a Barolo" |
| `vitigno` | "it's a Nebbiolo" |
| `generico` | only what is written: "a rosé sparkling wine metodo classico, brut" |
| `nulla` | nothing: the guest is asked to turn the label |

`catena_di_ripiego` gives the steps of each record: a wine goes down to its tipologia
(`_tipologia_del_vino`, which respects the color written in the name and prefers the tipologie with
bubbles when the name declares them), then to the appellation, then to its grape variety, if that
has a profile.

| confidence | in `Fatti` | what `Amelie._riconosci` does |
|---|---|---|
| ≥ `SOGLIA_CERTA` (88) | `certo` | tells the story, with an affirmative opening |
| from `SOGLIA_DUBBIA` (75) to 88 | `dubbio` | chooses the most generic candidate, then tells the story |
| below 75, level not `nulla` | — | tells the story; for wine, tipologia and grape variety the opening declares it a guess |
| level `nulla` | `vuoto` | asks the guest to turn the label; after `TENTATIVI_MAX` it goes quiet |

**Doubt is not put to the guest.** `Matcher.il_piu_generico` takes, among the first candidate and
the alternatives, the one with the most general level (`GENERALITA`); on a tie the first one stays.
If the alternatives are wines from different producers, the doubt is the winery, and it goes down
to the same wine without a producer. The alternatives (at most three, distinct, of the right color
and all read) remain in the `Fatti` and in the log.

## What has not been read is not named

This is the rule that holds up all of recognition: a name spoken aloud at a table is a claim
about a real company or a real place, and getting it wrong is worse than saying something vague.

- **The producer.** A wine is attributed to a producer only if the producer's own words are on
  the label; the appellation's words are on anyone's bottle. Without that proof
  `_senza_produttore` goes down to the generic step: a label that says only "Primitivo di
  Manduria" is told as Primitivo di Manduria, not as the wine of one of its many producers.
- **All names.** `_non_oltre_cio_che_si_e_letto` goes down until the **identifying** words of the
  record (useful words minus `PAROLE_GENERICHE`) are all on the label, each with a match ≥ 70 on a
  different word read (`_tutto_letto`). A similarity threshold cannot do this job: the
  similarities of correct recognitions and of inventions overlap, the words read do not.
- **The generic level.** If no step holds, `_solo_l_etichetta` says the declared color, the
  category deduced from the words read (`CATEGORIA_DETTA`) and the qualifiers in the order in which
  they are spoken (`ORDINE_QUALIFICATORI`). At this level the language model never writes.
- **The declared color.** If the label declares a single color (`COLORE_DETTO`), no record of a
  different color can be that bottle: `_del_colore_giusto` goes down among the first
  `CANDIDATI_PER_COLORE` (16) until it finds one of that color, and `_del_colore_dichiarato`
  corrects the step among the sister tipologie of the same appellation. "Nero" and "rosa" do not
  count as colors (they are parts of grape variety names); two different colors read together
  count as none.
- **The producer without the wine.** When the cascade goes below the wine level,
  `_il_produttore_scritto` puts the winery back into the facts only if its own words (at least
  four letters, not generic, not in the name of a candidate wine, not place names) are read
  with coverage ≥ `PRODUTTORE_SCRITTO` (90), belong only to that winery in the archive, and only
  one producer passes the test.
- **Two producers with equal evidence.** If among the first `RIVALI` (6) there is a wine from
  another winery within `MARGINE_PRODUTTORE` (3 points), the confidence drops just below certainty
  and the doubt is resolved without the winery.
- **Namesake cooperatives.** A producer named after its own appellation has no words of its own:
  it cannot be proved, and its bottles are told as generic.
- **Quotations from the production specification.** `_disciplinare` assigns the descriptions from
  `tipologia_ue` by narrowing down, not by resemblance: same color, same kind of product
  (`PRODOTTO_DIVERSO`: passito, liquoroso, recioto, vendemmia tardiva…), then identical name if
  reliable, then grape varieties and qualifiers. If what remains says the same thing it is quoted;
  otherwise nothing is said.

## Wine list mode

With `--carta vini.csv` and the "carta" mode chosen in the settings, the device recognizes the
titles of a file written by the venue (`src/amelie/carta.py`). Columns `titolo` and `descrizione`,
plus `titolo_xx` and `descrizione_xx` for each other language:

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
- each of its words is on the label (match ≥ 70), except the `TACITE` (DOC, DOCG, IGT…, the
  Italian appellation tiers, and "annata") and the **implied** ones (`Carta._implicate`: present in
  all the entries that contain the identifying words read). "Riserva" or "Extra Brut" in the title
  must be read;
- the implied words that were not read do not outnumber the identifying words that were read.

Among the admitted titles the one with the most words read wins, then the one with the fewest
words not read, then similarity. If none passes, the log notes the closest entries
(`Carta.vicine`). Even in wine list mode the archive is queried, for the languages the wine list
does not have.

## Hand corrections

With "Add corrections" on, the staff in the room can teach the device a bottle: title,
description, and optionally a link to an archive record or to a wine list entry. `Correzioni`
stores in `var/correzioni/<id>/` the `correzione.json` file and one photo per **view**, with the
lines read and the label area. Corrections are looked up **first**, in every storytelling mode
(`Amelie._cerca_correzione`), with two signals:

- **the words**: `parole_identificanti` (at least four letters, not generic) remembered and read
  again, with `fuzz.ratio` ≥ 80 and one word read for each;
- **the image**: ORB points found again in a consistent position (ratio test between the two best
  matches, RANSAC homography), searched **only in the label area** (`zona_etichetta`), because the
  background of the room is the same in all the photos and would make different bottles look
  alike.

The thresholds, in `Regola`, are tuned so that two different bottles are never mistaken for each
other, at the cost of some missed recognitions: a share of words `parole` (0.6) with at least
`parole_minime` (2) and `immagine_con_parole` (16) points, or `immagine_da_sola` (30) points; at
most `viste_confrontate` (6) views are compared, among those with at least one word in common.
Correcting the same bottle again adds a view, and helps it be recognized under different lighting
and angles.

## The bottle swapped during the story

If the sensor sees a bottle arrive while a story is being told, `Amelie._anticipa` reads it in a
separate thread **without stopping the voice** (`_decidi_in_anticipo`):

1. it takes a picture and compares the label area of the previous photo with the new photo
   (`Correzioni.punti_in_comune`): with at least `STESSA_A_OCCHIO` (25) points it is the same
   bottle;
2. otherwise it reads, and `_e_un_altra` decides: the same identifying words (with the corrections'
   `Regola`) mean the same bottle; something else to tell (a correction, a wine list entry, a
   record) means a different one; with no identifying words it does not decide, and the bottle is
   read again when the story is over;
3. if it is a different one, the voice stops (`Evento.CAMBIO_BOTTIGLIA`) and `_scatta_e_leggi`
   reuses the reading already done, as long as it is within `ANTICIPO_VALIDO_S`.

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

The script's default side is the device's (`lato_rilevatore = 480`); `--lato` tries
another one. The benchmark prints how many times winery and wine
name are found in the text read (`partial_ratio` ≥ 80), the plausible vintages, the silent labels,
the average number of lines, the time per label and the five worst. On the PC it measures
quality; on the board, with the service's venv, time as well. It uses `Lettore.leggi` on **flat,
frontal** photos, without fallback orientations or widened re-read: it is an upper bound.

**The recognition benchmark.** `scripts/bench_matcher.py` passes that text to `Matcher.cerca` and
compares the result with the known record: **consistent** (`coerente`: what is said checks out,
even if it went down a level), **inconsistent** (`INCOERENTE`), and **of which declared certain**
(`di cui DICHIARATE CERTE`), that is, inconsistent above `SOGLIA_CERTA`. This last line **must
stay at zero**: those are told as facts. Then come the distribution by level and by confidence
band. The benchmark measures `Matcher.cerca` without the `il_piu_generico` step, and the count by
level does not print the `generico` row (it is obtained by difference).

**On the device.**

- **The log** (`src/amelie/giornale.py`) records each scan in `var/scansioni/giornale.jsonl`
  with the frame next to it: lines read, capture and OCR times, sharpness, exposure, `allargata`,
  `anticipata`, level, confidence, names, color, candidates, `scelto_il_piu_generico`,
  `perche_correzione`, and in wine list mode the `vicine`. It can also be read from
  `GET /giornale?quante=N` and `GET /giornale/<nome>`.
- **The viewfinder** ("Debug camera") shows live the frame, the crop, the sharpness, the reading
  and the recognition; it is turned on from the settings. `scripts/mirino.py`, with the service
  stopped, does the same in a browser and accepts `--esposizione`, `--ritaglio`, `--ritaglio-alto`,
  `--luce`, `--ocr`.
- **`POST /prova/bottiglia`** simulates a bottle on the plate (`/prova/via` removes it,
  `/prova/camera` goes back to the sensor), to test reading and recognition without the sensor.
- **The tests** (`tests/test_matcher.py`, `test_ocr.py`, `test_carta.py`,
  `test_cambio_bottiglia.py`…) are skipped, for the recognition part, if the database or
  `rapidfuzz` is missing.

Aggregate numbers are not enough: every change to a threshold must be replayed on **all** the test
labels and on the real readings in the log, and every difference must be reread by hand. A
tolerance that fixes one case often breaks others, and this is the only way to see it.

## How to tune it

Change one parameter at a time, measure again with the benchmarks and with the log, and check that
the "declared certain" stay at zero.

| where | parameter (default) | when to touch it |
|---|---|---|
| `ImpostazioniCamera` | `rotazione` (90) | the camera is mounted the other way |
| `ImpostazioniCamera` | `esposizione` (900), `posa_massima` (4500) | very dark room or a different camera |
| `ImpostazioniCamera` | `luce_cercata` (90), `luce_tollerata` (8) | labels blown out or too dark |
| `ImpostazioniCamera` | `ritaglio_largo` (0.70), `ritaglio_alto` (0.95), `allarga_riquadro` (0.08) | the wall gets in, or words get cut off |
| `capture.py` | `SOGLIA_NITIDEZZA` (40), `FRAZIONE_SAGOMA` (0.25), `SAGOMA_MASSIMA` (0.70) | blurry frames, wrong silhouettes |
| `bridge.Presenza` | `vicino_mm` (100), `lontano_mm` (140) | different geometry between plate and sensor |
| `ImpostazioniOCR` | `lato_rilevatore` (480), `righe_massime` (10) | trade-off between letters read and time |
| `ImpostazioniOCR` | `confidenza_minima` (0.55), `usa_classificatore` (false) | noise; frame not straightened |
| `ocr.py` | `BORDO_CHE_TAGLIA` (0.03) | when the widened re-read kicks in |
| `matcher.py` | `SOGLIA_CERTA` (88), `SOGLIA_DUBBIA` (75), `TETTO_PER_PAROLE` | how much is claimed |
| `matcher.py` | `RISCONTRO_PAROLA` (70), `PRODUTTORE_SCRITTO` (90), `MARGINE_PRODUTTORE` (3) | tests on names |
| `matcher.py`, `text.py` | `PAROLE_GENERICHE`, `COLORE_DETTO`, `PRODOTTO_DIVERSO`, `PAROLE_VUOTE` | vocabulary of the rules |
| `carta.py` | `SOMIGLIANZA_MINIMA` (55), `RISCONTRO_PEZZO` (75), `TACITE` | strictness of the wine list |
| `correzioni.py` | `Regola` | strictness of the corrections |
| `app.py` | `TENTATIVI_MAX` (3), `STESSA_A_OCCHIO` (25) | attempts; "it's the same bottle" |

To extend recognition to a new type of record you need the rows in the `ricerca` index, the scope
in `Matcher.AMBITI`, `LIVELLO_DELL_AMBITO` and `GENERALITA`, and a builder in
`Matcher._componi`: until the code knows it, its rows stay out of the contest.

## Known limitations

- **Pale glass.** The distance sensor works in infrared, which passes through the bottom of a pale
  bottle and does not come back: the bottle is not seen and the scan does not start. The remedy
  lies in the signal threshold in the sensor's firmware.
- **Curved labels.** On the sides of the cylinder the letters get narrower and are lost: per-line
  rectification compensates for foreshortening, not for what the glass hides, and the widened
  re-read only recovers what the crop cut off.
- **Reflections and darkness.** A specular reflection burns out the letters it covers (the
  exposure looks at the mean light, and CLAHE does not rebuild a saturated spot); in the dark long
  exposures are needed, and a bottle held in the hand moves, so the sharpest frame may not be
  sharp enough.
- **Decorative typefaces and dense patterns.** Ornate scripts and patterned backgrounds confuse
  the detector even when the label is readable by eye; if the wine name is decorative, recognition
  goes down to the tipologia or the appellation.
- **Vintage.** It is often on the neck label, out of frame or too small: then it is not said.
- **Writing behind the plate.** A wall with text on it adds lines and time; a narrow crop and the
  learned background limit this.
- **Archive coverage.** What is in the database is recognized; the rest gets as far as the
  appellation or the generic level, or is taught with a correction. Cooperatives named after their
  own appellation are always told as generic.
- **Mounting orientation.** If `rotazione` does not match the mounting, the label is still read,
  by trying the other orientations, but with more readings per scan.
