# Attribuzioni e licenze

Amelie 2.0 usa dati, modelli e programmi scritti da altri. Qui c'è ogni fonte,
la sua licenza e cosa chiede a chi costruisce o ridistribuisce il dispositivo.

## Le licenze del progetto

| Cosa | Licenza |
|---|---|
| Codice: `src/`, `scripts/`, `firmware/`, `data/*.py`, `tests/` | **GPL-3.0-or-later**, vedi [LICENSE](../../LICENSE) |
| Documentazione, immagini, schemi, file di stampa 3D, lessico (`data/lessico/`), schede dei vitigni (`data/vitigni.json`), carta dei vini (`vini.csv`) | **CC BY 4.0**, vedi [LICENSE-DOCS.md](../../LICENSE-DOCS.md) |
| Il database costruito, `data/amelie.db` | **ODbL 1.0**, per via di X-Wines (sotto) |
| Il modello linguistico affinato, `studente-q4_k_m.gguf` | **Apache-2.0**, come i modelli da cui deriva |

L'attribuzione richiesta da CC BY 4.0 è:

> Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

## Dati sul vino

Tutto ciò che `data/build_db.py` legge sta in `data/sources/`, con la sua
provenienza descritta in [`data/sources/LEGGIMI.md`](../../data/sources/LEGGIMI.md).

### Quality wines in Italy and France: PDO specifications

**CC BY 4.0** · Candiago, Tscholl, Bassani, Fraga, Egarter Vigl (2024) ·
<https://doi.org/10.6084/m9.figshare.25393261>

Le **tipologie** delle 408 DOP italiane: colore, categoria, vitigni principali
e ammessi, rese. File: `data/sources/PDO_wine_data_IT_FR.csv`.

### Primary vine varieties of European wine PDOs

**CC BY 4.0** · Candiago et al. (2022) · <https://doi.org/10.5281/zenodo.7257126>

File: `data/sources/EU_PDO_id_varieties.csv`. È nel repository come
riferimento; il costruttore del database non lo legge.

### X-Wines

**Citazione obbligatoria** · <https://github.com/rogerioxavier/X-Wines>

> de Azambuja, R. X.; Morais, A. J.; Filipe, V. **X-Wines: A Wine Dataset for
> Recommender Systems and Machine Learning.** *Big Data and Cognitive
> Computing* 2023, 7(1), 20. <https://doi.org/10.3390/bdcc7010020>

I **19.358 vini italiani** con cantina, regione, vitigni, abbinamenti e
annate, in `data/sources/xwines_italia.csv`, estratti dal dataset completo con
`data/estrai_xwines.py`.

La licenza cambia a seconda di dove si guarda: il file `LICENSE` del
repository è CC0 1.0, il `README` impone la citazione del paper, la pagina
Kaggle dichiara ODbL 1.0 + DbCL 1.0. Il progetto segue l'ipotesi più
restrittiva, ODbL: citazione visibile, riferimento al paper, script di
costruzione pubblico, e il database costruito distribuito sotto ODbL 1.0. Così
sono rispettate tutte e tre.

Il dataset completo (1,9 GB, con milioni di valutazioni e le fotografie delle
etichette) non è nel repository.

### Registro UE delle indicazioni geografiche e documenti unici

**CC BY 4.0** (Decisione 2011/833/UE) · © Unione europea ·
<https://ec.europa.eu/geographical-indications-register/> ·
<https://webgate.ec.europa.eu/eambrosia-api/>

Dal registro vengono le denominazioni che il dataset figshare non ha (le IGP) e
la menzione DOCG, DOC o IGT di tutte; dal testo dei **documenti unici**
vengono colore, odore e sapore ufficiali delle tipologie, cioè le citazioni del
disciplinare che il racconto riporta. File: `data/sources/eambrosia_it_wine.tsv`
e `data/sources/documenti_unici.jsonl`. Dai testi sono stati tolti i recapiti
personali (indirizzi di posta elettronica e numeri di telefono); il resto è
com'è pubblicato.

Il documento unico riproduce il disciplinare di produzione, che è un atto
ufficiale dello Stato: in Italia i testi degli atti ufficiali non sono coperti
dal diritto d'autore (art. 5, legge 633/1941).

### L'elenco delle DOCG

`data/sources/docg.txt`: un nome per riga, scritto a mano dall'elenco pubblico
delle DOCG. Sono fatti, non un'opera.

### Il database costruito

`data/amelie.db` non è nel repository: lo costruisce `data/build_db.py`, e lo
esegue `scripts/install.sh` sulla board. Si distribuisce sotto **ODbL 1.0**
riportando le attribuzioni qui sopra: Candiago et al. (figshare), de Azambuja
et al. (X-Wines), © Unione europea (registro e documenti unici).

Di proposito **non contiene**: premi e punteggi delle guide, indici ricavati da
cataloghi di rivenditori, dati della grande distribuzione, note di degustazione
dei produttori.

### Fonti valutate e scartate

Per chi vuole estendere il database, queste sembrano adatte e non lo sono:

| Fonte | Perché no |
|---|---|
| Wine Reviews / winemag (Kaggle) | CC BY-NC-SA 4.0: esclude l'uso commerciale |
| SommBench | i dati sono CC BY-NC 4.0; la licenza Apache-2.0 del repository copre solo il codice di valutazione |
| Testi di Wikipedia | CC BY-SA 4.0: la prosa data a un modello rischia di rendere il racconto un'opera derivata, soggetta allo share-alike. I disciplinari coprono lo stesso bisogno senza il problema |
| Open Food Facts | pochi vini italiani: copertura troppo bassa per riconoscere un'etichetta |

## Modelli

### OCR: RapidOCR e PP-OCR

**Apache-2.0** · <https://github.com/RapidAI/RapidOCR> ·
<https://github.com/PaddlePaddle/PaddleOCR>

Le reti PP-OCRv6 (rilevatore e riconoscitore «tiny») le scarica RapidOCR
durante l'installazione.

### Voce: Piper

**GPL-3.0** · <https://github.com/OHF-Voice/piper1-gpl>

Una voce per lingua, entrambe addestrate da zero su dati che ne permettono
anche l'uso commerciale:

| Lingua | Voce | Dataset | Licenza |
|---|---|---|---|
| italiano | `it_IT-serena-medium` | [serena-synthetic-it-27h](https://huggingface.co/datasets/committa/serena-synthetic-it-27h) | **CC BY 4.0** |
| inglese | `en_US-ljspeech-medium` | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | **pubblico dominio** |

`scripts/install.sh` le scarica da <https://huggingface.co/rhasspy/piper-voices>
a una revisione fissa e ne controlla le somme SHA-256.

Le voci più diffuse non vanno bene per un dispositivo che si può usare in un
locale. La scheda di `it_IT-paola-medium` dichiara «Finetuned from U.S. English
lessac voice», e il dataset di `en_US-lessac-medium` (Blizzard Challenge 2013)
esclude qualunque uso commerciale, compreso lo sviluppo e la vendita di
prodotti di sintesi vocale. Anche `en_GB-alba` ed `en_US-libritts_r` dichiarano
CC BY 4.0, ma è la licenza del dataset di rifinitura: più sotto entrambe dicono
«Finetuned from … lessac». Non basta la riga della licenza: conta da che cosa
la voce è stata rifinita.

### Modello linguistico

Il modo «generativa», sperimentale, usa un modello piccolo che gira sulla board
con **llama.cpp** (MIT, <https://github.com/ggml-org/llama.cpp>).

- **Qwen2.5-0.5B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct>)
  è il modello di partenza, affinato con LoRA per questo progetto.
- **Qwen2.5-7B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-7B-Instruct>)
  ha scritto una parte dei testi di addestramento, a partire dai fatti del
  database; l'altra parte è composta dai fatti con il lessico. Tutti i testi
  sono passati dalla stessa verifica che controlla il racconto.

Il modello affinato si distribuisce sotto **Apache-2.0** come allegato della
release; `scripts/install.sh` lo scarica e ne controlla la somma SHA-256.

## Programmi

### Sulla board

| Componente | Licenza |
|---|---|
| Python, [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) | PSF, MIT, BSD-3-Clause |
| [OpenCV](https://opencv.org/), [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Apache-2.0, MIT |
| [NumPy](https://numpy.org/), [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), [msgpack](https://github.com/msgpack/msgpack-python) | BSD-3-Clause, MIT, Apache-2.0 |
| Chromium, Debian e i pacchetti del sistema | le rispettive licenze |

Le versioni esatte sono in [`requirements.txt`](../../requirements.txt).

### Nel microcontrollore

| Componente | Licenza |
|---|---|
| core Arduino `arduino:zephyr` | Apache-2.0 |
| [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), Arduino_RPClite | MPL-2.0 |
| [MsgPack](https://github.com/hideakitai/MsgPack) | MIT |

### Il carattere

**EB Garamond**, © 2017 The EB Garamond Project Authors · **SIL Open Font License
1.1** · <https://github.com/octaviopardo/EBGaramond12>

I file `.woff2` sono in `src/amelie/ui/static/fonts/`, con la licenza in
`OFL.txt` accanto.
