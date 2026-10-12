# Attribuzioni e licenze

Amelie 2.0 usa dati, modelli e programmi scritti da altri. Questa pagina elenca
ogni fonte e ogni componente, con la sua licenza e con ciò che chiede a chi
costruisce, modifica o ridistribuisce il dispositivo.

## Le licenze del progetto

| Che cosa | Licenza |
|---|---|
| Codice: `src/`, `scripts/`, `firmware/`, `data/*.py`, `tests/` | **MIT**, vedi [LICENSE](../../LICENSE) |
| Documentazione (`docs/` e i file README), immagini (`docs/images/`), schema dei collegamenti (`hardware/wiring.svg`), file di stampa 3D (`hardware/stl/`), lessico (`data/lessico/`), schede dei vitigni (`data/vitigni.json`), carta dei vini (`vini.csv`) | **CC BY 4.0**, vedi [LICENSE-DOCS.md](../../LICENSE-DOCS.md) |
| Il database costruito, `data/amelie.db` | **ODbL 1.0**, per via di X-Wines (più sotto) |
| Il modello linguistico affinato, `studente-q4_k_m.gguf` | **Apache-2.0**, come i modelli da cui deriva |

Restano sotto la propria licenza i file di terzi che il repository contiene: i
dati in `data/sources/` (più sotto), il carattere in
`src/amelie/ui/static/fonts/` (SIL OFL 1.1) e `tests/etichette/manifesto.csv`,
ricavato da X-Wines.

L'attribuzione richiesta da CC BY 4.0 è:

> Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

## Le licenze, in breve

| Licenza | Che cosa permette e che cosa chiede |
|---|---|
| **GPL-3.0** (GNU General Public License, versione 3) | usare, studiare, modificare e ridistribuire il programma, anche a fini commerciali. Chi lo ridistribuisce, modificato o no, deve farlo con la stessa licenza e mettere a disposizione il codice sorgente |
| **CC BY 4.0** (Creative Commons Attribuzione 4.0 Internazionale) | copiare, ridistribuire e modificare l'opera, anche a fini commerciali, con tre obblighi: citare l'autore, indicare la licenza con un collegamento, dire se si è modificato qualcosa |
| **CC BY-SA 4.0** | come CC BY 4.0, e in più ogni opera derivata va distribuita con la stessa licenza (*share-alike*, «condividi allo stesso modo») |
| **CC BY-NC 4.0**, **CC BY-NC-SA 4.0** | come le due precedenti, ma vietano l'uso commerciale (*NC*, *non commercial*) |
| **CC0 1.0** | l'autore rinuncia a ogni diritto, per quanto la legge lo permette: l'opera si usa come se fosse di pubblico dominio |
| **ODbL 1.0** (Open Database License, di Open Data Commons) | usare, ridistribuire e modificare un database, anche a fini commerciali, citandone le fonti. Un database derivato, se lo si distribuisce o lo si usa in pubblico, va offerto con la stessa licenza |
| **DbCL 1.0** (Database Contents License) | accompagna l'ODbL e copre i singoli contenuti del database: lascia liberi di usarli |
| **Apache-2.0** | usare, modificare e ridistribuire, anche a fini commerciali, conservando gli avvisi di copyright e di licenza e segnalando i file modificati |
| **MIT**, **BSD-3-Clause** | licenze permissive: chiedono di conservare l'avviso di copyright e il testo della licenza. La BSD vieta anche di usare il nome degli autori per promuovere i prodotti derivati |
| **MPL-2.0** (Mozilla Public License 2.0) | i file coperti, se modificati e ridistribuiti, restano sotto MPL-2.0 con il loro sorgente; possono far parte di un programma con un'altra licenza |
| **PSF** (Python Software Foundation License) | la licenza permissiva dell'interprete Python |
| **SIL OFL 1.1** (SIL Open Font License) | usare, incorporare, modificare e ridistribuire i caratteri, anche dentro prodotti commerciali, ma non venderli da soli |
| **pubblico dominio** | nessun diritto d'autore, quindi nessun obbligo |

## Dati sul vino

I dati di terzi che `data/build_db.py` legge stanno in `data/sources/`, salvati
nel repository; provenienza e formato di ogni file sono descritti in
[`data/sources/LEGGIMI.md`](../../data/sources/LEGGIMI.md).

Qualche termine torna spesso. Una **denominazione** è il nome protetto di un
vino legato a una zona di produzione (Barolo, Chianti Classico). Le
denominazioni europee sono di due tipi: **DOP** (denominazione di origine
protetta) e **IGP** (indicazione geografica protetta). In Italia le DOP si
chiamano **DOCG** (denominazione di origine controllata e garantita) o **DOC**
(denominazione di origine controllata), e le IGP portano la menzione **IGT**
(indicazione geografica tipica). Il **disciplinare di produzione** è il
regolamento di una denominazione: vitigni, rese, caratteristiche del vino. Una
**tipologia** è uno dei vini che il disciplinare definisce, per esempio il
Barolo Riserva.

### Quality wines in Italy and France: a dataset of protected designation of origin specifications

**CC BY 4.0** · Sebastian Candiago, Simon Tscholl, Leonardo Bassani, Helder
Fraga, Lukas Egarter Vigl (2024), figshare ·
<https://doi.org/10.6084/m9.figshare.25393261>

Le **tipologie** delle DOP italiane e francesi: colore, categoria, vitigni
principali e ammessi, rese massime. Il costruttore del database usa le righe
delle 408 DOP italiane. File: `data/sources/PDO_wine_data_IT_FR.csv`.

### Primary vine varieties of European wine PDOs

**CC BY 4.0** · Simon Tscholl, Sebastian Candiago (2022), Zenodo ·
<https://doi.org/10.5281/zenodo.7257126>

I vitigni principali e gli altri vitigni delle DOP europee. File:
`data/sources/EU_PDO_id_varieties.csv`. È nel repository come riferimento; il
costruttore del database non lo legge.

### X-Wines

**Citazione obbligatoria** · <https://github.com/rogerioxavier/X-Wines>

> de Azambuja, R. X.; Morais, A. J.; Filipe, V. **X-Wines: A Wine Dataset for
> Recommender Systems and Machine Learning.** *Big Data and Cognitive
> Computing* 2023, 7(1), 20. <https://doi.org/10.3390/bdcc7010020>

I **19.358 vini italiani** del dataset, con cantina, regione, vitigni,
abbinamenti e annate, in `data/sources/xwines_italia.csv`, estratti dal dataset
completo con `data/estrai_xwines.py`. Lo stesso script scrive
`tests/etichette/manifesto.csv`, l'elenco dei vini italiani di cui X-Wines ha
la fotografia dell'etichetta. Le fotografie non sono nel repository, perché
sono opere grafiche dei produttori: chi ha scaricato X-Wines le ricava in
locale con `python3 data/estrai_xwines.py --estrai-immagini`.

La licenza di X-Wines dipende da dove la si legge. Il file `LICENSE` del
repository è CC0 1.0; il `README` dello stesso repository impone di citare
l'articolo qui sopra in ogni pubblicazione basata sul dataset; la pagina Kaggle
della versione ridotta (*X-Wines Slim*) dichiara ODbL 1.0 per il database e DbCL
1.0 per i contenuti. Il progetto segue la lettura più restrittiva, l'ODbL:
citazione visibile, riferimento all'articolo, script di costruzione pubblico, e
il database costruito distribuito sotto ODbL 1.0. Così sono rispettate tutte e
tre.

Il dataset completo (quasi 2 GB, con oltre 21 milioni di valutazioni degli
utenti e le fotografie delle etichette) non è nel repository.

### Registro UE delle indicazioni geografiche e documenti unici

**CC BY 4.0** (Decisione 2011/833/UE) · © Unione europea ·
<https://ec.europa.eu/geographical-indications-register/> ·
<https://webgate.ec.europa.eu/eambrosia-api/>

eAmbrosia è il registro pubblico delle indicazioni geografiche dell'Unione
europea. Dal registro vengono le 124 denominazioni che il dataset di figshare
non ha (119 IGP e 5 DOP) e la menzione DOCG, DOC o IGT di tutte. Il **documento
unico** è la sintesi del disciplinare che il registro pubblica per ogni
denominazione: dal suo testo vengono colore, odore e sapore ufficiali delle
tipologie, cioè le citazioni del disciplinare che il racconto riporta. File:
`data/sources/eambrosia_it_wine.tsv` e `data/sources/documenti_unici.jsonl`.

Le modifiche rispetto ai documenti pubblicati sono due: il testo è estratto dai
PDF, quindi senza impaginazione, e non riporta i recapiti personali (indirizzi
di posta elettronica, numeri di telefono e di fax). Per il resto è il testo
pubblicato.

Il disciplinare di produzione è un atto ufficiale dello Stato, e in Italia i
testi degli atti ufficiali non sono coperti dal diritto d'autore (art. 5, legge
633/1941).

### L'elenco delle DOCG

`data/sources/docg.txt`: un nome per riga, scritto a mano dall'elenco pubblico
delle DOCG. Sono fatti, non un'opera tutelata.

### Il database costruito

`data/amelie.db` non è nel repository: lo costruisce `data/build_db.py`, che
`scripts/install.sh` esegue sulla board. Si distribuisce sotto **ODbL 1.0**
con le attribuzioni di questa pagina: Candiago et al. (figshare), de Azambuja
et al. (X-Wines), © Unione europea (registro e documenti unici), e
l'attribuzione del progetto riportata in cima, per le schede dei vitigni e per
i racconti composti con il lessico, che il database contiene. Il database porta
con sé le sue fonti: la tabella `fonte` ne elenca nome, indirizzo, licenza e
attribuzione.

Di proposito **non contiene**: premi e punteggi delle guide, indici ricavati da
cataloghi di rivenditori, dati della grande distribuzione, note di degustazione
dei produttori, valutazioni degli utenti di X-Wines.

### Fonti valutate e scartate

Per chi vuole estendere il database, queste sembrano adatte e non lo sono:

| Fonte | Perché no |
|---|---|
| Wine Reviews / winemag (Kaggle) | CC BY-NC-SA 4.0: esclude l'uso commerciale |
| SommBench | i dati, pubblicati su Hugging Face, sono CC BY-NC 4.0; la licenza del repository GitHub copre solo il codice di valutazione |
| Testi di Wikipedia | CC BY-SA 4.0: la prosa data a un modello rischia di rendere il racconto un'opera derivata, soggetta allo *share-alike*. I disciplinari coprono lo stesso bisogno senza il problema |
| Open Food Facts | pochi vini italiani: copertura troppo bassa per riconoscere un'etichetta |

## Modelli

### OCR: RapidOCR e PP-OCR

**Apache-2.0** · <https://github.com/RapidAI/RapidOCR> ·
<https://github.com/PaddlePaddle/PaddleOCR>

L'OCR (*optical character recognition*, riconoscimento ottico dei caratteri)
legge il testo dell'etichetta. RapidOCR esegue con ONNX Runtime le reti PP-OCR
di PaddleOCR; il dispositivo usa le PP-OCRv6 «tiny», sia per il rilevatore, che
trova le righe di testo, sia per il riconoscitore, che le legge. Le scarica
RapidOCR durante l'installazione (passo 5 di `scripts/install.sh`).

### Voce: Piper

**GPL-3.0** · <https://github.com/OHF-Voice/piper1-gpl>

Piper è il programma di sintesi vocale che legge il racconto ad alta voce; ogni
voce è una rete neurale a sé. Il dispositivo usa una voce per lingua, entrambe
addestrate da zero su dati che ne permettono anche l'uso commerciale:

| Lingua | Voce | Dataset | Licenza del dataset |
|---|---|---|---|
| italiano | `it_IT-serena-medium` | [serena-synthetic-it-27h](https://huggingface.co/datasets/committa/serena-synthetic-it-27h), di committa | **CC BY 4.0** |
| inglese | `en_US-ljspeech-medium` | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | **pubblico dominio** |

`scripts/install.sh` le scarica da <https://huggingface.co/rhasspy/piper-voices>
a una revisione fissa e ne controlla l'impronta SHA-256, elencata in
`scripts/modelli.sha256`: un file diverso da quello atteso ferma
l'installazione.

Le voci più diffuse non vanno bene per un dispositivo che si può usare in un
locale. La scheda di `it_IT-paola-medium` dichiara «Finetuned from U.S. English
lessac voice», cioè affinata a partire dalla voce inglese lessac, e il dataset
di `en_US-lessac-medium` (Blizzard Challenge 2013) esclude qualunque uso
commerciale, compreso lo sviluppo e la vendita di prodotti di sintesi vocale.
Anche le schede di `en_GB-alba-medium` ed `en_US-libritts_r-medium` dichiarano
CC BY 4.0, ma è la licenza del dataset di affinamento: più sotto entrambe dicono
di essere affinate dalla voce lessac. La riga della licenza non basta: conta da
quale voce una voce è stata affinata.

Piper non è nel repository: lo installa `scripts/install.sh` da PyPI, e
l'applicazione lo usa come libreria. La licenza MIT del codice di Amelie è
compatibile con la GPL; chi distribuisce un dispositivo con Piper installato
deve rispettarne la licenza, cioè mettere a disposizione il suo codice
sorgente, che è pubblico all'indirizzo qui sopra.

### Modello linguistico

Il modo di racconto sperimentale «Scritto sul momento» (`generativa` nel codice)
fa scrivere il testo a un modello linguistico piccolo, che gira sulla board con
**llama.cpp** (MIT, <https://github.com/ggml-org/llama.cpp>);
`scripts/install.sh` compila llama.cpp sulla board a un commit fisso.

- **Qwen2.5-0.5B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct>)
  è il modello di partenza, affinato per questo progetto con LoRA, una tecnica
  che addestra solo piccole matrici aggiunte al modello invece di tutti i suoi
  pesi.
- **Qwen2.5-7B-Instruct** (Apache-2.0, <https://huggingface.co/Qwen/Qwen2.5-7B-Instruct>)
  ha scritto una parte dei testi di addestramento, a partire dai fatti del
  database; l'altra parte è composta dai fatti con il lessico. Tutti i testi di
  addestramento superano la stessa verifica che controlla il racconto.

Il modello affinato, `studente-q4_k_m.gguf`, si distribuisce sotto
**Apache-2.0** come allegato della release del repository;
`scripts/install.sh` lo scarica e ne controlla l'impronta SHA-256. Come lo usa
il dispositivo è spiegato in [Il racconto e la voce](07-racconto.md).

## Programmi

### Sulla board

| Componente | A che cosa serve | Licenza |
|---|---|---|
| Python | il linguaggio dell'applicazione | PSF |
| [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) | il server web dell'applicazione | MIT, BSD-3-Clause |
| [OpenCV](https://opencv.org/) | cattura ed elabora le immagini della camera | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | esegue le reti dell'OCR e della voce | MIT |
| [NumPy](https://numpy.org/) | il calcolo sulle immagini | BSD-3-Clause |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | il confronto approssimato fra il testo letto e i nomi del database | MIT |
| [msgpack](https://github.com/msgpack/msgpack-python) | il formato dei messaggi verso il microcontrollore | Apache-2.0 |
| Chromium, Debian, i programmi di Arduino preinstallati sulla UNO Q (fra cui `arduino-router`) e gli altri pacchetti del sistema | la pagina a tutto schermo, il sistema operativo, il collegamento con il microcontrollore | le rispettive licenze |

Le versioni esatte di questi pacchetti Python e delle loro dipendenze, ciascuna
con la propria licenza, sono in [`requirements.txt`](../../requirements.txt).

### Nel microcontrollore

| Componente | Licenza |
|---|---|
| core Arduino `arduino:zephyr`, con il sistema operativo Zephyr | Apache-2.0 |
| [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), [Arduino_RPClite](https://github.com/arduino-libraries/Arduino_RPCLite) | MPL-2.0 |
| [MsgPack](https://github.com/hideakitai/MsgPack), [ArxContainer](https://github.com/hideakitai/ArxContainer), [ArxTypeTraits](https://github.com/hideakitai/ArxTypeTraits), [DebugLog](https://github.com/hideakitai/DebugLog), di Hideaki Tai | MIT |

Lo sketch include solo Arduino_RouterBridge; le altre librerie sono quelle da
cui dipende, e `arduino-cli` le installa da sé. Il firmware è descritto in
[`firmware/amelie_mcu/README.md`](../../firmware/amelie_mcu/README.md).

### Il carattere

**EB Garamond**, © 2017 The EB Garamond Project Authors · **SIL Open Font
License 1.1** · <https://github.com/octaviopardo/EBGaramond12>

I file `.woff2` sono in `src/amelie/ui/static/fonts/`, con la licenza in
`OFL.txt` accanto.
