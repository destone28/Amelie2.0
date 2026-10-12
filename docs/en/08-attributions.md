# Attributions and licences

Amelie 2.0 uses data, models and software written by others. This page lists
every source and every component, with its licence and with what it asks of
anyone who builds, modifies or redistributes the device.

## The project's licences

| What | Licence |
|---|---|
| Code: `src/`, `scripts/`, `firmware/`, `data/*.py`, `tests/` | **MIT**, see [LICENSE](../../LICENSE) |
| Documentation (`docs/` and the README files), images (`docs/images/`), wiring diagram (`hardware/wiring.svg`), 3D printing files (`hardware/stl/`), lexicon (`data/lessico/`), grape variety sheets (`data/vitigni.json`), wine list (`vini.csv`) | **CC BY 4.0**, see [LICENSE-DOCS.md](../../LICENSE-DOCS.md) |
| The built database, `data/amelie.db` | **ODbL 1.0**, because of X-Wines (below) |
| The fine-tuned language model, `studente-q4_k_m.gguf` | **Apache-2.0**, like the models it derives from |

The third-party files that the repository contains keep their own licences:
the data in `data/sources/` (below), the typeface in
`src/amelie/ui/static/fonts/` (SIL OFL 1.1) and `tests/etichette/manifesto.csv`,
derived from X-Wines.

The attribution required by CC BY 4.0 is:

> Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

## The licences in brief

| Licence | What it allows and what it asks |
|---|---|
| **GPL-3.0** (GNU General Public License, version 3) | using, studying, modifying and redistributing the program, also commercially. Anyone who redistributes it, modified or not, must do so under the same licence and make the source code available |
| **CC BY 4.0** (Creative Commons Attribution 4.0 International) | copying, redistributing and adapting the work, also commercially, with three obligations: credit the author, name the licence with a link, say whether anything was changed |
| **CC BY-SA 4.0** | like CC BY 4.0, and in addition every derivative work must be distributed under the same licence (*share-alike*) |
| **CC BY-NC 4.0**, **CC BY-NC-SA 4.0** | like the two previous ones, but they forbid commercial use (*NC*, *non-commercial*) |
| **CC0 1.0** | the author waives every right, as far as the law allows: the work can be used as if it were in the public domain |
| **ODbL 1.0** (Open Database License, by Open Data Commons) | using, redistributing and adapting a database, also commercially, crediting its sources. A derivative database, if distributed or used publicly, must be offered under the same licence |
| **DbCL 1.0** (Database Contents License) | goes with the ODbL and covers the individual contents of the database: it leaves them free to use |
| **Apache-2.0** | using, modifying and redistributing, also commercially, keeping the copyright and licence notices and marking the modified files |
| **MIT**, **BSD-3-Clause** | permissive licences: they ask you to keep the copyright notice and the licence text. The BSD licence also forbids using the authors' names to promote derived products |
| **MPL-2.0** (Mozilla Public License 2.0) | the covered files, if modified and redistributed, stay under MPL-2.0 with their source; they can be part of a program under another licence |
| **PSF** (Python Software Foundation License) | the permissive licence of the Python interpreter |
| **SIL OFL 1.1** (SIL Open Font License) | using, embedding, modifying and redistributing the typefaces, also inside commercial products, but not selling them on their own |
| **public domain** | no copyright, so no obligations |

## Wine data

The third-party data that `data/build_db.py` reads is in `data/sources/`,
stored in the repository; the origin and format of each file are described in
[`data/sources/README.md`](../../data/sources/README.md).

A few terms come up often. An **appellation** (*denominazione*) is the
protected name of a wine tied to a production area (Barolo, Chianti Classico).
European appellations are of two kinds: **DOP** (*denominazione di origine
protetta*, PDO, protected designation of origin) and **IGP** (*indicazione
geografica protetta*, PGI, protected geographical indication). In Italy DOPs
are called **DOCG** (*denominazione di origine controllata e garantita*,
controlled and guaranteed designation of origin) or **DOC** (*denominazione di
origine controllata*, controlled designation of origin), and IGPs carry the
term **IGT** (*indicazione geografica tipica*, typical geographical
indication). The **production specification** (*disciplinare di produzione*) is
the rulebook of an appellation: grape varieties, yields, characteristics of the
wine. A **tipologia** is one of the wines that the specification defines, for
example Barolo Riserva.

### Quality wines in Italy and France: a dataset of protected designation of origin specifications

**CC BY 4.0** · Sebastian Candiago, Simon Tscholl, Leonardo Bassani, Helder
Fraga, Lukas Egarter Vigl (2024), figshare ·
<https://doi.org/10.6084/m9.figshare.25393261>

The **tipologie** of the Italian and French DOPs: colour, category, main and
permitted grape varieties, maximum yields. The database builder uses the rows
of the 408 Italian DOPs. File: `data/sources/PDO_wine_data_IT_FR.csv`.

### Primary vine varieties of European wine PDOs

**CC BY 4.0** · Simon Tscholl, Sebastian Candiago (2022), Zenodo ·
<https://doi.org/10.5281/zenodo.7257126>

The main and the other grape varieties of the European PDOs. File:
`data/sources/EU_PDO_id_varieties.csv`. It is in the repository as a
reference; the database builder does not read it.

### X-Wines

**Citation required** · <https://github.com/rogerioxavier/X-Wines>

> de Azambuja, R. X.; Morais, A. J.; Filipe, V. **X-Wines: A Wine Dataset for
> Recommender Systems and Machine Learning.** *Big Data and Cognitive
> Computing* 2023, 7(1), 20. <https://doi.org/10.3390/bdcc7010020>

The **19,358 Italian wines** of the dataset, with winery, region, grape
varieties, food pairings and vintages, in `data/sources/xwines_italia.csv`,
extracted from the full dataset with `data/estrai_xwines.py`. The same script
writes `tests/etichette/manifesto.csv`, the list of the Italian wines for which
X-Wines has a photograph of the label. The photographs are not in the repository,
because they are the producers' graphic works: anyone who has downloaded
X-Wines extracts them locally with
`python3 data/estrai_xwines.py --estrai-immagini`.

The licence of X-Wines depends on where you read it. The repository's
`LICENSE` file is CC0 1.0; the `README` of the same repository requires citing
the paper above in every publication based on the dataset; the Kaggle page of
the reduced version (*X-Wines Slim*) declares ODbL 1.0 for the database and
DbCL 1.0 for the contents. The project follows the most restrictive reading,
the ODbL: a visible citation, a reference to the paper, a public build script,
and the built database distributed under ODbL 1.0. That way all three are
respected.

The full dataset (almost 2 GB, with more than 21 million user ratings and the
photographs of the labels) is not in the repository.

### EU register of geographical indications and single documents

**CC BY 4.0** (Decision 2011/833/EU) · © European Union ·
<https://ec.europa.eu/geographical-indications-register/> ·
<https://webgate.ec.europa.eu/eambrosia-api/>

eAmbrosia is the public register of the geographical indications of the
European Union. The register provides the 124 appellations that the figshare
dataset does not have (119 IGPs and 5 DOPs) and the DOCG, DOC or IGT term of
all of them. The **single document** is the summary of the production
specification that the register publishes for each appellation: its text
provides the official colour, aroma and taste of the tipologie, that is, the
quotations from the production specification that the story reports. Files:
`data/sources/eambrosia_it_wine.tsv` and `data/sources/documenti_unici.jsonl`.

There are two changes from the published documents: the text is extracted
from the PDFs, so it has no layout, and it does not include personal contact
details (email addresses, telephone and fax numbers). Otherwise it is the
published text.

The production specification is an official act of the State, and in Italy the
texts of official acts are not covered by copyright (art. 5, law 633/1941).

### The list of DOCGs

`data/sources/docg.txt`: one name per line, written by hand from the public
list of DOCGs. They are facts, not a protected work.

### The built database

`data/amelie.db` is not in the repository: it is built by `data/build_db.py`,
which `scripts/install.sh` runs on the board. It is distributed under **ODbL
1.0** with the attributions on this page: Candiago et al. (figshare),
de Azambuja et al. (X-Wines), © European Union (register and single
documents), and the project's attribution given at the top, for the grape
variety sheets and for the stories composed with the lexicon, which the
database contains. The database carries its sources with it: the `fonte` table
lists their name, address, licence and attribution.

On purpose, it **does not contain**: awards and scores from wine guides,
indexes derived from retailers' catalogues, data from large-scale retail,
producers' tasting notes, X-Wines user ratings.

### Sources evaluated and rejected

For anyone who wants to extend the database, these look suitable and are not:

| Source | Why not |
|---|---|
| Wine Reviews / winemag (Kaggle) | CC BY-NC-SA 4.0: excludes commercial use |
| SommBench | the data, published on Hugging Face, are CC BY-NC 4.0; the licence of the GitHub repository covers only the evaluation code |
| Wikipedia texts | CC BY-SA 4.0: prose given to a model risks making the story a derivative work, subject to *share-alike*. The production specifications cover the same need without that problem |
| Open Food Facts | few Italian wines: coverage too low to recognise a label |

## Models

### OCR: RapidOCR and PP-OCR

**Apache-2.0** · <https://github.com/RapidAI/RapidOCR> ·
<https://github.com/PaddlePaddle/PaddleOCR>

OCR (optical character recognition) reads the text of the label. RapidOCR runs
PaddleOCR's PP-OCR networks with ONNX Runtime; the device uses the PP-OCRv6
"tiny" ones, both for the detector, which finds the lines of text, and for the
recogniser, which reads them. RapidOCR downloads them during installation
(step 5 of `scripts/install.sh`).

### Voice: Piper

**GPL-3.0** · <https://github.com/OHF-Voice/piper1-gpl>

Piper is the speech synthesis program that reads the story aloud; each voice is
a neural network of its own. The device uses one voice per language, both
trained from scratch on data that also allows commercial use:

| Language | Voice | Dataset | Dataset licence |
|---|---|---|---|
| Italian | `it_IT-serena-medium` | [serena-synthetic-it-27h](https://huggingface.co/datasets/committa/serena-synthetic-it-27h), by committa | **CC BY 4.0** |
| English | `en_US-ljspeech-medium` | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | **public domain** |

`scripts/install.sh` downloads them from <https://huggingface.co/rhasspy/piper-voices>
at a fixed revision and checks their SHA-256 fingerprint, listed in
`scripts/modelli.sha256`: a file different from the expected one stops the
installation.

The most widely used voices are not suitable for a device that may be used in a
commercial venue. The model card of `it_IT-paola-medium` states "Finetuned from
U.S. English lessac voice", that is, fine-tuned starting from the English
lessac voice, and the dataset of `en_US-lessac-medium` (Blizzard Challenge
2013) excludes any commercial use, including the development and sale of
speech synthesis products. The model cards of `en_GB-alba-medium` and
`en_US-libritts_r-medium` also declare CC BY 4.0, but that is the licence of
the fine-tuning dataset: further down both say they are fine-tuned from the
lessac voice. The licence line is not enough: what matters is which voice a
voice was fine-tuned from.

Piper is not in the repository: `scripts/install.sh` installs it from PyPI, and
the application uses it as a library. The MIT licence of Amelie's code is
compatible with the GPL; anyone who distributes a device with Piper installed
must respect Piper's licence, that is, make its source code available, which
is public at the address above.

### Language model

The experimental storytelling mode "Written on the spot" (`generativa` in the
code) has the text written by a small language model, which runs on the board
with **llama.cpp** (MIT, <https://github.com/ggml-org/llama.cpp>);
`scripts/install.sh` compiles llama.cpp on the board at a fixed commit.

- **Qwen2.5-0.5B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct>)
  is the base model, fine-tuned for this project with LoRA, a technique that
  trains only small matrices added to the model instead of all its weights.
- **Qwen2.5-7B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-7B-Instruct>)
  wrote part of the training texts, starting from the facts in the database;
  the other part is composed from the facts with the lexicon. All the training
  texts pass the same verification that checks the story.

The fine-tuned model, `studente-q4_k_m.gguf`, is distributed under
**Apache-2.0** as an attachment to the repository's release;
`scripts/install.sh` downloads it and checks its SHA-256 fingerprint. How the
device uses it is explained in [The story and the voice](07-storytelling.md).

## Software

### On the board

| Component | What it is for | Licence |
|---|---|---|
| Python | the language of the application | PSF |
| [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) | the application's web server | MIT, BSD-3-Clause |
| [OpenCV](https://opencv.org/) | captures and processes the camera images | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | runs the OCR and voice networks | MIT |
| [NumPy](https://numpy.org/) | computation on the images | BSD-3-Clause |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | approximate comparison between the text read and the names in the database | MIT |
| [msgpack](https://github.com/msgpack/msgpack-python) | the format of the messages to the microcontroller | Apache-2.0 |
| Chromium, Debian, the Arduino programs preinstalled on the UNO Q (including `arduino-router`) and the other system packages | the full-screen page, the operating system, the link with the microcontroller | their respective licences |

The exact versions of these Python packages and of their dependencies, each
with its own licence, are in [`requirements.txt`](../../requirements.txt).

### In the microcontroller

| Component | Licence |
|---|---|
| Arduino core `arduino:zephyr`, with the Zephyr operating system | Apache-2.0 |
| [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), [Arduino_RPClite](https://github.com/arduino-libraries/Arduino_RPCLite) | MPL-2.0 |
| [MsgPack](https://github.com/hideakitai/MsgPack), [ArxContainer](https://github.com/hideakitai/ArxContainer), [ArxTypeTraits](https://github.com/hideakitai/ArxTypeTraits), [DebugLog](https://github.com/hideakitai/DebugLog), by Hideaki Tai | MIT |

The sketch includes only Arduino_RouterBridge; the other libraries are the ones
it depends on, and `arduino-cli` installs them by itself. The firmware is
described in [`firmware/amelie_mcu/README.en.md`](../../firmware/amelie_mcu/README.en.md).

### The typeface

**EB Garamond**, © 2017 The EB Garamond Project Authors · **SIL Open Font
License 1.1** · <https://github.com/octaviopardo/EBGaramond12>

The `.woff2` files are in `src/amelie/ui/static/fonts/`, with the licence in
`OFL.txt` next to them.
