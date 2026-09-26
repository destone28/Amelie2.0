# Attributions and licenses

Amelie 2.0 uses data, models and software written by others. Here is every
source, its license and what it asks of anyone who builds or redistributes the
device.

## The project's licenses

| What | License |
|---|---|
| Code: `src/`, `scripts/`, `firmware/`, `data/*.py`, `tests/` | **GPL-3.0-or-later**, see [LICENSE](../../LICENSE) |
| Documentation, images, schematics, 3D printing files, lexicon (`data/lessico/`), grape variety profiles (`data/vitigni.json`), wine list (`vini.csv`) | **CC BY 4.0**, see [LICENSE-DOCS.md](../../LICENSE-DOCS.md) |
| The built database, `data/amelie.db` | **ODbL 1.0**, because of X-Wines (below) |
| The fine-tuned language model, `studente-q4_k_m.gguf` | **Apache-2.0**, like the models it derives from |

The attribution required by CC BY 4.0 is:

> Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

## Wine data

Everything that `data/build_db.py` reads is in `data/sources/`, with its
provenance described in [`data/sources/LEGGIMI.md`](../../data/sources/LEGGIMI.md).

### Quality wines in Italy and France: PDO specifications

**CC BY 4.0** · Candiago, Tscholl, Bassani, Fraga, Egarter Vigl (2024) ·
<https://doi.org/10.6084/m9.figshare.25393261>

The **tipologie** (the wine types within each appellation) of the 408 Italian
DOPs (PDOs, protected designations of origin): color, category, main and
permitted grape varieties, yields. File: `data/sources/PDO_wine_data_IT_FR.csv`.

### Primary vine varieties of European wine PDOs

**CC BY 4.0** · Candiago et al. (2022) · <https://doi.org/10.5281/zenodo.7257126>

File: `data/sources/EU_PDO_id_varieties.csv`. It is in the repository as a
reference; the database builder does not read it.

### X-Wines

**Citation required** · <https://github.com/rogerioxavier/X-Wines>

> de Azambuja, R. X.; Morais, A. J.; Filipe, V. **X-Wines: A Wine Dataset for
> Recommender Systems and Machine Learning.** *Big Data and Cognitive
> Computing* 2023, 7(1), 20. <https://doi.org/10.3390/bdcc7010020>

The **19,358 Italian wines** with winery, region, grape varieties, food
pairings and vintages, in `data/sources/xwines_italia.csv`, extracted from the
full dataset with `data/estrai_xwines.py`.

The license changes depending on where you look: the repository's `LICENSE`
file is CC0 1.0, the `README` requires citing the paper, the Kaggle page
declares ODbL 1.0 + DbCL 1.0. The project follows the most restrictive reading,
ODbL: a visible citation, a reference to the paper, a public build script, and
the built database distributed under ODbL 1.0. That way all three are
respected.

The full dataset (1.9 GB, with millions of ratings and the photographs of the
labels) is not in the repository.

### EU register of geographical indications and single documents

**CC BY 4.0** (Decision 2011/833/EU) · © European Union ·
<https://ec.europa.eu/geographical-indications-register/> ·
<https://webgate.ec.europa.eu/eambrosia-api/>

The register provides the appellations that the figshare dataset does not have
(the IGPs, protected geographical indications) and the DOCG, DOC or IGT
mention (the Italian quality tiers) of all of them; the text of the **single
documents** provides the official color, aroma and taste of the tipologie, that
is, the quotations from the production specification (*disciplinare*) that the
story reports. Files: `data/sources/eambrosia_it_wine.tsv`
and `data/sources/documenti_unici.jsonl`. Personal contact details (email
addresses and phone numbers) have been removed from the texts; the rest is as
published.

The single document reproduces the production specification, which is an
official act of the State: in Italy the texts of official acts are not covered
by copyright (art. 5, law 633/1941).

### The list of DOCGs

`data/sources/docg.txt`: one name per line, written by hand from the public
list of DOCGs. They are facts, not a work.

### The built database

`data/amelie.db` is not in the repository: it is built by `data/build_db.py`,
which `scripts/install.sh` runs on the board. It is distributed under **ODbL
1.0** with the attributions above: Candiago et al. (figshare), de Azambuja
et al. (X-Wines), © European Union (register and single documents).

On purpose, it **does not contain**: awards and scores from wine guides,
indexes derived from retailer catalogs, data from large-scale retail,
producers' tasting notes.

### Sources evaluated and rejected

For anyone who wants to extend the database, these look suitable and are not:

| Source | Why not |
|---|---|
| Wine Reviews / winemag (Kaggle) | CC BY-NC-SA 4.0: excludes commercial use |
| SommBench | the data are CC BY-NC 4.0; the repository's Apache-2.0 license covers only the evaluation code |
| Wikipedia texts | CC BY-SA 4.0: prose given to a model risks making the story a derivative work, subject to share-alike. The production specifications cover the same need without that problem |
| Open Food Facts | few Italian wines: coverage too low to recognize a label |

## Models

### OCR: RapidOCR and PP-OCR

**Apache-2.0** · <https://github.com/RapidAI/RapidOCR> ·
<https://github.com/PaddlePaddle/PaddleOCR>

The PP-OCRv6 networks ("tiny" detector and recognizer) are downloaded by
RapidOCR during installation.

### Voice: Piper

**GPL-3.0** · <https://github.com/OHF-Voice/piper1-gpl>

One voice per language, both trained from scratch on data that also allows
commercial use:

| Language | Voice | Dataset | License |
|---|---|---|---|
| Italian | `it_IT-serena-medium` | [serena-synthetic-it-27h](https://huggingface.co/datasets/committa/serena-synthetic-it-27h) | **CC BY 4.0** |
| English | `en_US-ljspeech-medium` | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | **public domain** |

`scripts/install.sh` downloads them from <https://huggingface.co/rhasspy/piper-voices>
at a fixed revision and checks their SHA-256 sums.

The most widely used voices are not suitable for a device that may be used in a
commercial venue. The model card of `it_IT-paola-medium` states "Finetuned from
U.S. English lessac voice", and the dataset of `en_US-lessac-medium` (Blizzard
Challenge 2013) excludes any commercial use, including the development and sale
of speech synthesis products. `en_GB-alba` and `en_US-libritts_r` also declare
CC BY 4.0, but that is the license of the fine-tuning dataset: further down both
say "Finetuned from … lessac". The license line is not enough: what matters is
what the voice was fine-tuned from.

### Language model

The experimental "generativa" mode uses a small model that runs on the board
with **llama.cpp** (MIT, <https://github.com/ggml-org/llama.cpp>).

- **Qwen2.5-0.5B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct>)
  is the base model, fine-tuned with LoRA for this project.
- **Qwen2.5-7B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-7B-Instruct>)
  wrote part of the training texts, starting from the facts in the
  database; the other part is composed from the facts with the lexicon. All the
  texts went through the same verification that checks the story.

The fine-tuned model is distributed under **Apache-2.0** as a release
attachment; `scripts/install.sh` downloads it and checks its SHA-256 sum.

## Software

### On the board

| Component | License |
|---|---|
| Python, [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) | PSF, MIT, BSD-3-Clause |
| [OpenCV](https://opencv.org/), [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Apache-2.0, MIT |
| [NumPy](https://numpy.org/), [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), [msgpack](https://github.com/msgpack/msgpack-python) | BSD-3-Clause, MIT, Apache-2.0 |
| Chromium, Debian and the system packages | their respective licenses |

The exact versions are in [`requirements.txt`](../../requirements.txt).

### In the microcontroller

| Component | License |
|---|---|
| Arduino core `arduino:zephyr` | Apache-2.0 |
| [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), Arduino_RPClite | MPL-2.0 |
| [MsgPack](https://github.com/hideakitai/MsgPack) | MIT |

### The typeface

**EB Garamond**, © 2017 The EB Garamond Project Authors · **SIL Open Font License
1.1** · <https://github.com/octaviopardo/EBGaramond12>

The `.woff2` files are in `src/amelie/ui/static/fonts/`, with the license in
`OFL.txt` next to them.
