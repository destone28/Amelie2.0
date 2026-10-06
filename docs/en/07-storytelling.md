# The story and the voice

This document explains how Amelie turns the facts about a bottle into a text,
how that text is checked before it is spoken and how it reaches the screen's
speaker. It is for anyone who wants to change the sentences, add a language,
turn on the language model or understand why the device says what it says.

The starting point is the `Fatti` (facts) produced by recognition (see
[06-recognition.md](06-recognition.md)). Everything runs on the board, with no
network. Code references are relative to the repository root.

## The words you need

| term | what it means here |
|---|---|
| facts | the `Fatti` object that recognition hands over: level, confidence, names, grapes, quotations, pairings; everything, and only, what the archive knows about that bottle |
| level, confidence | how far down the recognition cascade went (wine, *tipologia*, appellation, grape variety, generic) and how far what is claimed can be stood behind, from 0 to 100 |
| appellation, DOP, IGP | the protected name of a production area; DOP and IGP are the two European categories (protected designation of origin, protected geographical indication) |
| *tipologia* | one of the wines an appellation provides for, with its name, colour and category |
| production specification (*disciplinare*) | the production rules of an appellation, with an official description of the colour, aroma and taste of each *tipologia*; a **quotation** is one of those descriptions, reported in the story |
| lexicon | the files in `data/lessico/`: the sentences of the story and the vocabularies that translate the values of the datasets |
| seed | a number derived from the identity of the wine, which chooses among the equivalent forms of a sentence |
| language model | a neural network that writes text; here Qwen2.5-0.5B-Instruct, with half a billion parameters |
| token | the piece of text, a word or part of one, with which a language model reads and writes |
| LoRA | *low-rank adaptation*: a way of fine-tuning a model by training only small matrices added to its weights |
| GGUF, Q4_K_M | GGUF is the model file format of llama.cpp; Q4_K_M is a quantisation, that is the weights stored mostly at 4 bits instead of 16, to take less memory and run faster on the CPU |
| llama.cpp | the program that runs the model on the board's CPU; `llama-server` offers it as an HTTP service |
| Piper | the speech synthesiser: one neural network per voice, in ONNX format |
| ALSA, PCM | ALSA is the Linux audio system; PCM is uncompressed sound, a sequence of samples |

## The chain at a glance

```
recognition ──► Amelie._racconta ──┬─ hand correction ────────► opening with the title + text as is
                                   ├─ carta mode ─────────────► opening with the title + CSV description
                                   └─ Narratore.racconta
                                        ├─ archivio   ► template()        composition from the facts
                                        └─ generativa ► model ► verifica
                                                        └ no ► ready-made story ► verifica
                                                               └ no ► template()
text ──► spezza_in_frasi ──► screen ("racconto" message)
     └─► Riproduttore ──► Piper ──► Uscita ──► aplay ──► HDMI ──► screen
```

The code lives in `src/amelie/narrator.py` (composition, verification, choice
of source), `organolettico.py` (quotations in English), `lessico.py` (sentences
and vocabularies), `llm.py` and `gabbia.py` (the model), `speech.py` (voice and
player) and `app.py` (storytelling modes). The texts are in `data/lessico/` and
in `data/vitigni.json`.

## Three ways of telling

The mode does not change the style: it changes **where the text comes from**.

| Mode (`app.MODI`) | On screen | Source of the text | Check | When available |
|---|---|---|---|---|
| `archivio` | "From the archive" | composition from the facts, `narrator.template` | true by construction | always; it is the default |
| `generativa` | "Written on the spot" | the fine-tuned model; if its text does not pass, the ready-made story in the archive; finally the composition | `verifica` on every text from the model and from the archive | with `--con-modello` |
| `carta` | "Wine list" | the hand-written description in a CSV | none: it is a person's text | with `--carta FILE.csv` |

The mode is chosen from the settings panel or with
`POST /modo/{archivio|generativa|carta}`. It is saved
in `var/modo` and applies **from the next bottle**: the story in progress is not
interrupted. A new installation, with no saved mode, tells from the archive. A
mode that the device cannot serve does not appear among the choices, and a saved
mode that the device cannot serve falls back to the archive
(`Amelie._modo_salvato`).

In `Amelie._racconta` the order is fixed: first a **correction** written on site
for that bottle, if it has the text in the current language (it applies in all
modes and is read as it is); then the **wine list**, if it has the text in the
current language; then the `Narratore`. Correction and wine list open with the
title, in the `apertura.tipologia_nota` form ("This is a …"). Each story carries
its `origine` — `template`, `cache`, `modello`, `carta` or `correzione` — which
travels in the `racconto` message of the `GET /eventi` stream and ends up in the
log (`racconto_da`) together with the text spoken.

## The composition from the facts

This is the `archivio` mode: `narrator.template(fatti, lessico, lingua)`. Every
sentence comes from a field in the archive or from a quotation from the
production specification, inside a form taken from `data/lessico/frasi.json`.
The code decides *which* sentence to say; the text of the sentences lives in
the lexicon, one version per language.

### The facts that go in

| Field of `Fatti` | Where it comes from | How it is used |
|---|---|---|
| `nome`, `cantina` | the recognised commercial wine; the winery also when it is written on the label and the level is lower | in the opening, or in the sentence about the producer |
| `annata` | read on the label | in the opening, at the wine level |
| `tipologia`, `denominazione`, `tipo_denominazione` | the register of appellations | in the opening (DOP or IGP) |
| `vitigni` | for a commercial wine its grapes, in alphabetical order; for a *tipologia* the principal grapes of the production specification, ordered by how many wines of that appellation in the archive declare them (`matcher._USO_NEI_VINI`); for an appellation the grapes that are principal in at least half of its *tipologie*, in the same order | "It is made from …", at most four; the first one gives the profile |
| `vitigni_ammessi` | the grapes the production specification tolerates | **never said** |
| `note_vitigno` | the profile of the first grape variety (`data/vitigni.json`) | its first sentence |
| `disciplinare` | the official descriptions of the *tipologia*: colour, aroma, taste | quoted (in English: rendered) |
| `corpo`, `acidita` | the commercial wine, as keys of the controlled vocabularies | only if the production specification is silent |
| `abbinamenti` | the commercial wine or the grape variety profile | at most three dishes |
| `temperatura_c` | the category for sparkling wines (6-8 degrees), semi-sparkling (8-10), wines from dried or overripe grapes (10-12) and fortified wines (12-14); otherwise the grape variety profile | with the dishes, in one sentence |
| `regione` | the archive; in English it is translated with the `regione` vocabulary (Toscana → Tuscany, Piemonte → Piedmont) | only when there is little else to say |
| `qualificatori` | words read on the label (generic level) | "a rosé sparkling wine, brut" |

The facts carry the profiles in all languages with them (`Fatti.per_lingua`,
`nota_in`, `abbinamenti_in`, `sensoriali_in`): changing language does not
require reading the label again.

### How it is assembled

1. **The opening** (`_apertura`): what is in front of you, with the honesty of
   the level and of the confidence of the recognition (table below).
2. **The producer**, if it was read but the level is below "vino"
   (`apertura.cantina_sola`: "It is made by …").
3. **Where it comes from** (`_corpo`): the grapes by name, if the name of the
   wine does not already contain them, and the first sentence of the profile of
   the first grape variety. With a single grape the profile is attached with a
   colon ("It is made from Chardonnay: …"); with several grapes, or without the
   grapes sentence, it carries the name of the grape variety in front
   (`corpo.scheda_vitigno`, "Barbera: …"), unless its first sentence already
   names it. The region comes in only if so far there are fewer than two
   sentences and it is not already in the name of the appellation.
4. **The production specification**: colour and taste, aroma only if one of the
   two is missing; if there are already two sentences before, only one
   quotation remains, the taste if there is one.
5. **Body and acidity**, in the `narrativa` forms of the vocabularies, only if
   there is no quotation at all.
6. **At the table**: temperature and dishes in one sentence. "16-18" becomes
   "between 16 and 18 degrees" (in Italian "fra 16 e 18 gradi"), because a
   synthetic voice does not read the dash between two numbers well.
7. At the generic level, if the label gave at least one qualifier or a colour,
   the last sentence declares that the bottle is not in the archive
   (`corpo.generico_limite`).

The body has at most four sentences after the opening; in Italian a final pass
adds the euphonic "d" ("abbinato ad antipasti"). Every lexicon key can have a
**list of equivalent forms**, and a seed chooses among them: `seme_di(fatti)`,
a `crc32` (a 32-bit checksum) of the wine's identity, stable from one startup to
the next, varied for each sentence by `_seme_per`. The same wine is always told
with the same words; two different wines do not sound like the same form letter.

### The opening: level and confidence

The thresholds are `SOGLIA_CERTA` (88) and `SOGLIA_DUBBIA` (75) in
`src/amelie/matcher.py`. The examples are the reference forms, that is the
first ones in the list.

| Level | Confidence | Key in `frasi.json` | Example (English) |
|---|---|---|---|
| `VINO` | certain | `apertura.vino_certo` | `This is the “…” by … … vintage.` |
| `VINO` | doubtful / below the doubt threshold | `vino_dubbio`, `vino_incerto` | `I'd say the “…” by ….` |
| `TIPOLOGIA` | above / below the doubt threshold | `tipologia_nota`, `tipologia_incerta` | `This is a ….` / `I'd say a ….` |
| `DENOMINAZIONE` | — | `denominazione` + `sigle` | `This is …, a protected designation of origin.` |
| `VITIGNO` | above / below the doubt threshold | `vitigno_noto`, `vitigno_incerto` | `The grape is ….` / `I'd say a ….` |
| `GENERICO` | — | `generico` | `This is a rosé sparkling wine, brut.` |
| nothing readable | — | `illeggibile`, `schermo.illeggibile_con_invito` | `Please turn the label towards me.` |

### Quotations from the production specification

The organoleptic descriptions of the *tipologia* are the only prose among the
facts that the project did not write: they are the official text. They enter
the facts already cleaned up by recognition (`matcher._citazioni_utili`): the
stubs left by the cut of the source document, the words left dangling at the
end ("…, il"), the leading verb and words repeated in a row are removed, and
quotations that contain legal parameters or exceed 120 characters are
discarded.

- **In Italian** they are reported word for word. `_senza_coda_tronca` removes
  the last clause of a field truncated halfway ("…, dal"), and
  `_senza_doppioni_di_elenco` removes the items that repeat the previous one
  with an addition ("giallo paglierino, giallo paglierino carico").
- **In English** they go through `organolettico.Organolettico.rendi`, which
  splits the quotation on commas and semicolons and recomposes each fragment
  from the atoms in `data/lessico/organolettico.json` with fixed rules: ranges
  ("da X a Y", from X to Y), tendencies, highlights, adverbs, noun-adjective
  inversion. **It does not guess**: a fragment it cannot render is dropped and
  the quotation comes out shorter; ranges and alternatives go through whole or
  are dropped whole, a list joined by "e" (and) can be shortened. The result
  (`Reso`) declares whether it is `integrale` (complete) and that it is
  `tradotto` (translated).
- Since it is a translation, the English sentences say what the production
  specification *calls for* ("The specification calls for it to be …") and do
  not present it as its own words; the labelled block of facts, the one in the
  prompt for a generic model (`Fatti.blocco_fatti`), declares it *translated
  from the Italian*.

The form of the sentence depends on how the quotation begins
(`_forma_della_citazione`): "che va dal…" (ranging from…) uses the
`*_relativa` keys, a verb ("sono asciutti…", they are dry…, or in English
"may be…") uses `disciplinare_verbo`, an English participle ("ranging from…")
needs a form with a comma; a form that repeats a word of the quotation is
discarded ("il sapore è … di sapore pieno", the taste is … of full taste).

### An example

The *tipologia* "Barbera d’Asti", recognised with a confidence of at least 75
and with no readable vintage, in both languages:

> Questo è un Barbera d’Asti. Barbera: piemontese, generosa e di acidità
> spiccata, con tannino discreto. Il disciplinare prevede che sia rosso rubino
> tendente al rosso granato con l'invecchiamento. Al palato, asciutto,
> tranquillo, di corpo, con adeguato invecchiamento più armonico, gradevole, di
> gusto pieno. In tavola arriva fra 16 e 18 gradi, accanto a salumi, pasta al
> ragu e carni bianche.

> This is a Barbera d’Asti. Barbera: Piedmontese, generous and markedly acidic,
> with restrained tannin. The appellation rules describe it as ruby red, tending
> to garnet red with age. In the mouth, it is dry, still, with body, pleasant and
> of full taste. It comes to the table between 16 and 18 degrees, paired with
> cured meats, pasta with ragù and white meat.

The name "Barbera d’Asti" already contains the grape, so the "It is made from"
sentence is missing and the profile carries the name in front. In the English
rendering "con adeguato invecchiamento più armonico" (more harmonious with
adequate ageing) has been dropped: not all of its pieces could be rendered.

### The rule: nothing is invented

- An absent field does not produce a sentence: there is no filler text.
- Grapes that are only tolerated and the fictitious grape varieties of the
  register (`matcher.VITIGNI_FINTI`: "na", "n.d." and the like, which stand
  where the register has no grape) are not named.
- At the generic level only what is written on the bottle is said, filtered
  through a closed list (`_che_tipo_di_vino`).
- Below the certainty threshold the opening declares that it is a guess, and
  nothing that has not been verified is attributed to a producer.
- A value that a vocabulary does not know comes back as it is, in the language
  of the source: the coverage tests exist to find it first (`Lessico.manca`).

The composition does not go through verification at every story, because it
has nothing to invent; the tests check that the composed texts pass it
(`TestIlRaccontoCompostoDaiFatti` in `tests/test_narrator.py`).

### Languages

The languages are those declared in `vocabolari.json` (`lingue`: Italian and
English). The language is changed on screen with the little flag
(`POST /lingua/{codice}`): the device announces the language aloud
(`voce.conferma_lingua`) and, if a story was in progress, tells it again
immediately in the new language with the same facts. When the bottle is
removed the device goes back to the starting language, silently. The on-screen
text is also in `frasi.json` (group `schermo`), so screen and story never speak
two different languages.

## Verification

`narrator.verifica(testo, fatti, lingua)` answers one question: *does the text
claim only things present in the facts?* It returns `(va_bene, invenzioni)`
(whether it is fine, and the list of inventions). It is a deterministic check in
Python, which the model cannot get around; it is deliberately coarse and prefers
a false alarm, which costs another attempt or a fallback, to a false claim
spoken at the table. The comparison is made against everything the facts
contain, composed also **in the language of the story** (an English text is
compared with "Tuscany", not only with "Toscana"), without accents and with
apostrophes normalised.

| What it looks for | Where |
|---|---|
| numbers in digits that are not in the facts | `verifica`, `_NUMERO` |
| proper names that are not in the facts (not at the start of a sentence nor after a colon, not customary capitals) | `_PROPRIO`, `_MAIUSCOLE_INNOCENTI` |
| a contradicted colour (red on a white, white on a red, either one on a rosé) and "colours" that are categories | `_colore_sbagliato` |
| alcohol content and temperature spelt out in words, compared with the true values | `_gradi_sbagliati` |
| the production specification invoked when there is no quotation | `verifica` |
| dishes and regional origins that the facts do not give | `_cibi_inventati`, `_provenienze_inventate` |
| real names put in place of grapes: aroma notes, the name of the wine, the winery, the appellation; "X in purezza" (100% X) if X is not a grape | `_vitigni_che_non_lo_sono` |
| bubbles on a still wine | `_categoria_sbagliata` |
| the winery stated as a place, the grapes stated as the producer | `_produttore_al_posto_del_luogo`, `_uve_al_posto_del_produttore` |
| the colour stated in the phrasing meant for taste | `_colore_al_posto_del_gusto` |
| the grape variety profile hung on the name of the wine | `_scheda_attaccata_al_vino` |
| aroma notes stated as grapes or as dishes, dishes stated as aromas | `_note_al_posto_sbagliato`, `_cibi_al_posto_dei_profumi` |
| text going round in circles: repeated words or word pairs, except inside quotations | `_parole_ripetute`, `_coppie_ripetute` |

It is applied to every attempt by the model (`Narratore._dal_modello`), to
every ready-made story read from the archive (`_dalla_cache`, which also
discards the texts that name a fictitious grape variety) and to every sentence
of the streaming path (`racconta_a_frasi`, which the application does not use).
It is not applied to the wine list and to the corrections, which are a
person's words.

What it does **not** see: the meaning of an adjective. A "fruity" or a
"velvety" absent from the facts gets through, because to understand that they
are false one would have to understand the sentence. And it compares the text
with the facts, not the facts with reality: if a value in the archive is wrong,
the story repeats it faithfully.

## The generative mode

### The model

The model is **Qwen2.5-0.5B-Instruct**, with half a billion parameters,
**fine-tuned with LoRA for this device** and quantised to Q4_K_M: a GGUF file of
about 380 MB, `studente-q4_k_m.gguf`. It is fine-tuned on stories from two
sources, all filtered through the same `verifica`: written by
Qwen2.5-7B-Instruct starting from the facts in the database, and composed from
the facts with the lexicon. Both Qwen models are Apache-2.0, and so is the
fine-tuned model (see [08-attributions.md](08-attributions.md)).

It is run by `llama-server`, built by `scripts/install.sh` from llama.cpp at a
pinned version. It is started by the systemd unit
`scripts/systemd/amelie-llm.service` with the file
`/home/arduino/amelie/models/studente-q4_k_m.gguf`, listening on
`127.0.0.1:8081`, with 4 threads, a 2048-token context, `--cache-reuse 256`
(it reuses the initial part of the prompt already processed in a previous
request) and a cap of `MemoryMax=1400M`: if it goes over, the service dies
instead of pushing the board into swap. The client is `amelie.llm.Modello`; the
parameters are in `ImpostazioniLLM`: temperature 0.2, `top_p` 0.9, repetition
penalty 1.1, at most 120 tokens, at most 180 s of waiting for a response, and
stop sequences against a second paragraph and side notes.

The prompt, that is the text given to the model, has two forms, and
`--modello-addestrato` picks the right one:

- **fine-tuned model** (`prompt_addestrato`): Qwen's chat format, one
  instruction line per language (`ISTRUZIONE_ADDESTRATA`) and the compact facts
  (`Fatti.blocco_compatto`). It is the form the model expects, word for word:
  with the other one it answers worse and more slowly;
- **generic model** (`prompt`): the full instructions (`ISTRUZIONI`) and the
  block of facts with labels (`Fatti.blocco_fatti`).

### When it writes, and what happens if it gets it wrong

In `generativa` mode `Narratore.racconta(fatti, preferisci_modello=True)`
follows this order:

1. **the gate**: the model writes only if the facts contain a quotation from
   the production specification (`_abbastanza_per_il_modello`) and the level is
   not generic. Without a quotation it has only a list of fields and tends to
   fill the gaps; at the generic level there is nothing to claim beyond what is
   written;
2. **the model**, two attempts (`_dal_modello`): every text goes through
   `_ripulisci` (quotation marks, titles, lists, a cap of `PAROLE_MAX` words,
   that is 130, ending on the last complete sentence) and then through
   `verifica`. If the server does not respond, the request fails with
   `ModelloNonDisponibile` and the next step follows at once;
3. **the ready-made story** in the archive for that exact record, verified
   (there is one for each *tipologia*, appellation and grape variety with
   something to say, none for commercial wines);
4. **the composition from the facts**.

When the model is about to write, the screen shows "I'm writing the
description…" (`scrivendo` message) and `Amelie._aspetta_il_modello` waits up to
45 s for the server to respond on `/health`: the service may have just started
and has to load the model. If it does not, the device goes down to the next
steps: the model being on never means silence.

### On and off

The model is installed on the device but **off by default**:
`scripts/install.sh` installs the unit without enabling it at boot, and a new
installation tells from the archive. The application turns it on and off
together with the storytelling mode (`Amelie._accendi_il_modello`):
`systemctl start` when `generativa` is chosen, `stop` when another mode is
chosen, `restart` with "Restore operation" when the mode is `generativa`; when
the application starts it turns it on only if the saved mode is `generativa`.
The application runs without privileges: permission to manage that one unit
comes from the polkit rule `scripts/systemd/50-amelie-llm.rules` (polkit is the
Linux component that decides which system actions a user may perform).

The weights file is not in the repository: it is an attachment of the v1.0.0
release, and `scripts/install.sh` downloads it into `models/` and checks its
SHA-256 sum (`scripts/modelli.sha256`); the `AMELIE_URL_MODELLO` variable lets
it be downloaded from another address. With the standard installation the rest
is already in place: `scripts/systemd/amelie.service` starts the application
with `--con-modello --modello-addestrato`. Without `--con-modello` the
`generativa` mode does not appear and a saved mode falls back to the archive. To
use it, choose "Written on the spot" in the settings, or:

```bash
curl -X POST http://127.0.0.1:8080/modo/generativa
systemctl status amelie-llm             # the service starts by itself
curl http://127.0.0.1:8081/health        # responds once the model is loaded
```

To try another model, put a compatible GGUF in place of that file and restart
`amelie-llm`; if it is not the fine-tuned model, the application must be
started without `--modello-addestrato`, because it needs the generic prompt.
`scripts/install.sh`, when run again, puts the official file back, because the
sum no longer matches.

### Limitations

- **It is slow.** The composition is immediate; the model takes a few tens of
  seconds, covered on screen by the working message. The selector declares it
  experimental.
- **It costs CPU even when idle.** `llama-server` waiting for requests takes up
  almost a whole core (88%, measured), and on those four cores the OCR has to
  read: that is why it is turned on only in the mode that uses it.
- **It can be discarded.** When the two attempts do not pass verification, or
  the bottle has no quotations from the production specification, the story is
  composed from the facts, either ready-made in the archive or composed on the
  spot. The `origine` field and the log say where what was heard came from.
- **Passing verification is not a guarantee**: plausible adjectives are not
  caught. The `archivio` mode is the only one in which every word comes from
  the data.
- It writes in Italian and English (`ISTRUZIONE_ADDESTRATA` has one line for
  each).

### The cage (off)

`src/amelie/gabbia.py` builds a GBNF grammar for each bottle (the format in
which llama.cpp receives a grammar that limits the words allowed): only the
words of its facts, a closed lexicon of 310 connecting words
(`data/lessico/gabbia_it.txt`), digits and punctuation. `Modello.genera` passes
it to the server as `grammar` and llama.cpp enforces it token by token. It
exists only for Italian and is off (`gabbia=False` where `app.py` creates the
`Narratore`): on sparse records the closed vocabulary forces the model onto the
nearest allowed word, and the Italian comes out broken.

### Measuring on the board

From the board's `~/amelie` folder, with the model service on:

```bash
venv/bin/python scripts/bench_llm.py                    # one label, two rounds
venv/bin/python scripts/bench_llm.py --tutti            # four different cases
venv/bin/python scripts/bench_llm.py --prompt-generico  # the prompt for a model that is not fine-tuned
```

The script waits up to 30 s for the server to respond; then, for each case, it
prints the level, the confidence and the length of the prompt, and for each
round the duration, the verification outcome and the start of the text
(`--giri N` changes the number of rounds). The second round shows the prefix
cache at work. It uses the same prompt form as the device, `prompt_addestrato`,
and works in Italian.

## The wine list

With `--carta FILE.csv` the device can tell stories from a hand-written file
(`src/amelie/carta.py`); the system service points to
`/home/arduino/amelie/vini.csv`, that is the repository's `vini.csv` file: 526
entries, in Italian only, so in English the story comes from the archive.

```csv
titolo,descrizione,titolo_en,descrizione_en
"Nome della denominazione","Il racconto in italiano…","Name","The story in English…"
```

`titolo` (title) and `descrizione` (description) are required; each
`descrizione_xx` column adds a language. Only the title is searched, and each of
its words must have been read on the glass, except the appellation
abbreviations and "annata" (`TACITE`) and the words the wine list takes for
granted (the rules are in [06-recognition.md](06-recognition.md)). There is no
cascade: a bottle that the wine list does not have counts as a failed reading,
and the device asks for the label to be turned. The story is the opening with
the title (`apertura.tipologia_nota`) followed by the description as it is; if
the description is missing in the chosen language the story is told from the
archive facts, which are looked up anyway right after the title. A missing
file, or one with no usable entries, does not stop startup: the `carta` mode
simply does not appear.

## The voice

| Language | Piper voice (`speech.VOCI`) | Licence |
|---|---|---|
| Italian | `it_IT-serena-medium` | CC BY 4.0 |
| English | `en_US-ljspeech-medium` | LJ Speech dataset, public domain |

Piper is GPL-3.0; the two voices are trained from scratch on data that also
allows commercial use (attributions in [08-attributions.md](08-attributions.md)).
`scripts/install.sh` downloads the `.onnx` and `.onnx.json` files of each voice
into `models/` and checks their SHA-256 sums; `Voce._percorso_modello` looks for
each voice in `~/.local/share/piper/voices`, in `~/amelie/models` and in
`/usr/share/piper-voices`, in that order. At startup `Amelie._scalda_voci` opens
the audio output, loads both voices and pre-synthesises the language
announcement. A language without a voice shows the text, which scrolls at
reading pace (`_scorri_senza_voce`), and the screen says so
(`schermo.voce_assente`).

### From text to speaker

```
sentence ──► per_la_voce()              abbreviations expanded, foreign names, "16-18" → "16 to 18" (in Italian "16 e 18")
         ──► Piper (ONNX)               16-bit PCM, 22,050 Hz, mono
         ──► ~/.cache/amelie/voce/*.raw cache per voice and sentence
         ──► Riproduttore               in-memory buffer, position in bytes
         ──► Uscita                     stream always open, volume applied here
         ──► aplay -D plughw:0,3        ALSA converts the sample rate for HDMI
         ──► MultiMedia4 ─► SEC_MI2S_RX ─► I2S ─► ANX7625 ─► HDMI ─► screen
```

- **Pronunciation** (`speech.PRONUNCIA`, `PRONUNCIA_EN`) rewrites the text
  before synthesis: appellation abbreviations become the full wording in the
  right language, the Italian voice receives a phonetic spelling of the most
  common foreign wine names (Chardonnay, Château, Gewürztraminer…), and
  quotation marks are not pronounced. The cache is keyed on the voice and on the
  rewritten text.
- **The output** (`speech.Uscita`) opens `aplay`, ALSA's command-line player,
  at startup and never closes it again: when there is nothing to say it pours
  silence. The board's audio processor takes about two seconds to render sound
  after the stream is opened, and keeping it open avoids paying that delay at
  every sentence. The data is written at clock pace, in 80 ms chunks, so the
  declared position stays close to what is heard.
- **The ALSA device** is `plughw:0,3` (option `--audio`), that is device 3 of
  sound card 0: the sound starts from the MultiMedia4 stream, goes through the
  SEC_MI2S_RX port onto the I2S digital audio bus and through the ANX7625 chip
  to HDMI. `plughw` and not `hw`, because HDMI accepts only sample rates between
  32 and 48 kHz and Piper produces 22,050 Hz, and `plughw` adds the
  conversion. The mixer route (`SEC_MI2S_RX Audio Mixer MultiMedia4`) is opened
  at every boot by `scripts/systemd/amelie-audio-rotta.sh`, and
  `amelie-audio-guard.sh` makes sure the sound card exists at the end of the
  boot. The sound comes out of the
  screen's speakers or its headphone output.
- **Volume** has no hardware control on this chain: it is applied to the PCM
  in `Uscita._versa`, to everything that goes out. It goes from 0 to 100 and
  becomes a gain through the square (`guadagno_di`: halfway is about −12 dB,
  never above 1). The on-screen slider moves it in steps of 5 (`PASSO_CURSORE`
  in `index.html`) with `POST /volume/{valore}`; it is saved in `var/volume` (on the first start
  it is `--volume`, 100 if not given), and a synthesised tap on a glass
  (`Voce.colpetto`) lets you hear the chosen level. At 0 the story continues on
  the screen.

## The player

`speech.Riproduttore` makes the story controllable. It has a single source of
truth, the **position in bytes** in the story buffer, and from it derives the
elapsed seconds, the sentence to highlight and the point to resume from. One
thread synthesises the sentences one after the other and notes where each one
begins (`_sintetizza_tutto`), the other sends the audio to the `Uscita` from
the current position (`_suona`): the first sentence plays as soon as it is
ready.

| Button | `POST /racconto/{azione}` | Effect |
|---|---|---|
| play / pause | `alterna` (or `pausa`, `riprendi`) | on pause it goes back by what had been sent but not yet heard, so that resuming does not cut off a word |
| forward / back | `avanti`, `indietro` | `salta(±SALTO_S)`, 5 seconds; forward not beyond what has already been synthesised |
| restart | `ricomincia` | from the beginning |
| cancel | `POST /annulla` | closes the story and returns to the waiting screen |

Removing the bottle to pour does not interrupt the story. The state reaches
the page on the `GET /eventi` stream as a `riproduzione` message
(`Riproduttore.istantanea`: `posizione`, `durata`, `quota`, `frase`,
`in_pausa`, `completo`). The bar uses `quota`: the position divided by the
audio already synthesised **plus** the estimated duration of the sentences
still to come (`byte_stimati`, from the characters that will actually be
pronounced, with digits weighted by `CIFRA_VALE` and the pace of each voice in
`CARATTERI_AL_SECONDO`). A floor keeps it from moving backwards when an
estimate becomes a real duration; it moves back only with pause, skip and
"restart". The text reaches the screen all at once, split by `spezza_in_frasi`,
which does not split inside abbreviations or after dotted initials.

## Changing sentences, vocabularies and pronunciation

**`data/lessico/frasi.json`**: groups `apertura`, `corpo`, `generico`, `sigle`
for the story, `schermo` for the on-screen text, `voce` for sentences that are
only spoken. Each key has one entry per language, either a single sentence or a
list of equivalent forms; keys that start with `_` are notes.

- The **placeholders** in braces are the same in all languages and variants;
  the article in front of names is added by the code (`_con_articolo`).
- A **variant** says the same thing as the first form, which is the reference
  one, without adding anything. Adding one changes the seed's choice for many
  wines: the story stays true, but its words change.
- The register is impersonal when describing the wine ("Si serve fra…", in
  English "Best served between…") and uses the formal "lei" when addressing the
  guest.
- If a new form introduces the grapes with a phrasing that verification does
  not know, that phrasing must be added to `_CONTESTO_VITIGNI` in
  `narrator.py`.

**`data/lessico/vocabolari.json`**: the controlled vocabularies of the datasets
(`tipo`, `colore`, `categoria_ue`, `elaborazione`, `corpo`, `acidita`,
`abbinamento`), whose **keys are the exact values from the sources** and must
not be changed: they are join keys. In addition `regione`, with the names of
the Italian regions as the archive writes them ("Toscana", which in English
becomes "Tuscany"). Each term has, per language, an `etichetta` (label) for the
screen and, optionally, a `narrativa` form for use inside a sentence ("bright
acidity" instead of "high").

**`data/lessico/organolettico.json`**: the Italian → English atoms for the
quotations, in `termini` (colours, highlights, intensity, smell, substance,
taste, effervescence, mentions, idioms), plus `per_ambito` for words that
change meaning between colour, aroma and taste ("vivace", "rosa") and `nomi`
for nouns. A missing atom drops the fragment that contains it: adding it makes
the English quotations longer without touching the code.

**`data/vitigni.json`**: the 131 grape variety profiles, written by hand
(`descrizione`, `note_sensoriali`, `abbinamenti` with their `_en` versions,
`temperatura_c`, `colore_bacca`) and the `alias` names by which the datasets
call the same grape variety, declared one by one: matching by name similarity
would tie different grape varieties together. They are reapplied to the
existing database with `python3 data/build_db.py --solo-vitigni`.

**Pronunciation**: a badly read abbreviation or a mangled name is fixed with a
regular expression → replacement pair in `PRONUNCIA` or `PRONUNCIA_EN`
(`src/amelie/speech.py`). The cache is keyed on the rewritten text, so the fix
takes effect immediately.

### Adding a language

1. The language code in `lingue` in `vocabolari.json`, and the entry for every
   term.
2. Every key of `frasi.json` in the new language, with the same placeholders.
3. A Piper voice in `speech.VOCI` and its pace in `CARATTERI_AL_SECONDO`;
   without it, the story can only be read.
4. In the code, the places that know only Italian and English: the quotations
   from the production specification (`organolettico.json` renders only into
   English), the pronunciation tables (`_COMPILATE`), the conjunction in
   `elenca_in_lingua`, the article in `_con_articolo`, the forms recognised by
   `_forma_della_citazione`, the regular expressions of verification
   (`_CONTESTO_VITIGNI` and the other `_CONTESTO_*` in `narrator.py`), the
   labels of the facts block (`_ETICHETTE_BLOCCO`,
   `Fatti._INTESTAZIONE_DISCIPLINARE` and `Fatti._VOCI_DISCIPLINARE` in
   `matcher.py`) and, for the model, `ISTRUZIONE_ADDESTRATA`.
5. In the wine list, the `titolo_xx` and `descrizione_xx` columns.
6. Optional: a flag drawn in `src/amelie/ui/static/index.html`; without it, the
   selector shows the language code.

### After every change

```bash
python3 -m pytest tests/test_lessico.py tests/test_narrator.py tests/test_organolettico.py
```

The lexicon tests fail if a sentence is missing in a language, if the
placeholders do not match or if a dataset value has no translation; the
narrator tests check, among other things, that the composed texts pass
verification. Then everything is brought over to the board, in one of two ways.

- With `git pull` and `bash scripts/install.sh` on the board: the database is
  rebuilt by itself when the lexicon, the profiles or the sources have changed,
  ready-made stories included.
- With `scripts/rilascio.sh` from the PC: it copies code, interface, lexicon,
  profiles, database and tests, runs the tests on the board and restarts the
  application and the kiosk; on the first copy it keeps a backup copy of the
  database on the board. The database is the PC's, so the ready-made stories
  are regenerated first (section below).

## Regenerating the ready-made stories

The `racconto` table of the database contains an already composed story for
every *tipologia*, appellation and described grape variety that has something
to say, in every language: 9,876 rows in the built database. The text is the
**body without the opening** (`narrator.corpo_neutro`): the opening depends on
the confidence of the recognition, which is known only at that moment, and the
`Narratore` composes it when it uses the text. These texts are used in
`generativa` mode, as the second step after the model; the `archivio` mode
always composes live and reflects every change to the lexicon immediately.

```bash
python3 scripts/genera_corpus.py                  # writes what is missing
python3 scripts/genera_corpus.py --rigenera       # also rewrites what is there
python3 scripts/genera_corpus.py --lingua en      # a single language (repeatable)
python3 scripts/genera_corpus.py --solo vitigno   # a single scope (repeatable)
python3 scripts/genera_corpus.py --limite 50      # the first N per scope
```

The script writes to `data/amelie.db` (or to the file given with `--db`), which
the application opens read-only; `data/build_db.py` runs it by itself at the
end of every database build, unless `--senza-racconti` is given, so it is
needed by hand only to try out a change to the lexicon without rebuilding
everything. It sorts appellations and *tipologie* by how many wines belong to
them, so that an interrupted run leaves ready what is encountered most often,
and it skips the records with nothing to say: an empty row would prevent the
fallback to the next step. The `modello` column says where each row comes
from; the composed rows have `template`, and `--rigenera` rewrites only those.
It must be rerun with `--rigenera` after every change to `frasi.json`, to the
vocabularies, to the organoleptic atoms or to the grape variety profiles.
