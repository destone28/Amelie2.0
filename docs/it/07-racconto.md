# Il racconto e la voce

Questo documento spiega come Amelie trasforma i fatti di una bottiglia in un
testo, come quel testo si controlla prima di essere detto e come arriva
all'altoparlante dello schermo. Serve a chi vuole cambiare le frasi, aggiungere
una lingua, accendere il modello linguistico o capire perché il dispositivo dice
quello che dice.

Il punto di partenza sono i `Fatti` prodotti dal riconoscimento (vedi
[Riconoscimento dell'etichetta](06-riconoscimento.md)). Tutto gira sulla board,
senza rete. I riferimenti al codice sono relativi alla radice del repository.

## La catena in un colpo d'occhio

```
Fatti ──► Amelie._racconta ──┬─ correzione scritta in sala ──────► testo com'è
                             ├─ modo «carta» ────────────────────► descrizione del CSV
                             └─ Narratore.racconta
                                  ├─ «archivio»   ► template()        composizione dai fatti
                                  └─ «generativa» ► modello ► verifica
                                                    └ no ► racconto pronto ► verifica
                                                           └ no ► template()
testo ──► spezza_in_frasi ──► schermo (evento «racconto»)
      └─► Riproduttore ──► Piper ──► Uscita ──► aplay ──► HDMI ──► schermo
```

Il codice sta in `src/amelie/narrator.py` (composizione, verifica, scelta della
fonte), `organolettico.py` (citazioni in inglese), `lessico.py` (frasi e
vocabolari), `llm.py` e `gabbia.py` (il modello), `speech.py` (voce e
riproduttore) e `app.py` (modi di racconto). I testi stanno in `data/lessico/` e
in `data/vitigni.json`.

## Tre modi di raccontare

Il modo non cambia lo stile: cambia **da dove viene il testo**.

| Modo (`app.MODI`) | A schermo | Fonte del testo | Controllo | Quando c'è |
|---|---|---|---|---|
| `archivio` | «Dall'archivio» | composizione dai fatti, `narrator.template` | vero per costruzione | sempre; è il predefinito |
| `generativa` | «Scritto sul momento» | il modello affinato; se non passa, il racconto pronto in archivio; infine la composizione | `verifica` su ogni testo del modello e dell'archivio | con `--con-modello` |
| `carta` | «Carta dei vini» | la descrizione scritta a mano in un CSV | nessuno: è testo di una persona | con `--carta FILE.csv` |

Il modo si sceglie dal pannello delle impostazioni oppure con
`POST /modo/{archivio|generativa|carta}` (`POST /generati/{0|1}` è l'interruttore
a due posizioni equivalente). Si salva in `var/modo` e vale **dalla bottiglia
dopo**: il racconto in corso non si interrompe. Un modo che il dispositivo non
può servire non compare fra le scelte, e uno salvato che non è più servibile
torna all'archivio (`Amelie._modo_salvato`).

In `Amelie._racconta` l'ordine è fisso: prima una **correzione** scritta in sala
per quella bottiglia (vale in tutti i modi e si legge com'è), poi la **carta** se
ha il testo nella lingua corrente, poi il `Narratore`. Ogni racconto porta la sua
`origine` — `template`, `cache`, `modello`, `carta` o `correzione` — che viaggia
nell'evento `racconto` e finisce nel giornale di bordo (`racconto_da`) insieme
al testo detto.

## La composizione dai fatti

È il modo «archivio»: `narrator.template(fatti, lessico, lingua)`. Ogni frase
nasce da un campo dell'archivio o da una citazione del disciplinare, dentro una
forma presa da `data/lessico/frasi.json`. Il codice decide *quale* frase dire; il
testo delle frasi sta nel lessico, una versione per lingua.

### I fatti che entrano

| Campo di `Fatti` | Da dove viene | Come si usa |
|---|---|---|
| `nome`, `cantina`, `annata` | il vino riconosciuto | nell'apertura |
| `tipologia`, `denominazione`, `tipo_denominazione` | il registro delle denominazioni | nell'apertura (DOP/IGP) |
| `vitigni` | le uve contenute o imposte dal disciplinare | «Nasce da …», al massimo quattro |
| `vitigni_ammessi` | le uve che il disciplinare tollera | **mai dette** |
| `note_vitigno` | la scheda del vitigno (`data/vitigni.json`) | la sua prima frase |
| `disciplinare` | le descrizioni ufficiali della tipologia: colore, odore, sapore | citate (in inglese: rese) |
| `corpo`, `acidita` | chiavi dei vocabolari controllati | solo se il disciplinare tace |
| `abbinamenti`, `temperatura_c` | il vino commerciale o la scheda del vitigno | una frase, al massimo tre piatti |
| `regione` | l'archivio | solo quando c'è poco altro da dire |
| `qualificatori` | parole lette sull'etichetta (livello generico) | «uno spumante rosato, brut» |

I fatti si portano dietro le schede in tutte le lingue (`Fatti.per_lingua`,
`nota_in`, `abbinamenti_in`, `sensoriali_in`): cambiare lingua non richiede di
rileggere l'etichetta.

### Come si monta

1. **L'apertura** (`_apertura`): che cosa si ha davanti, con l'onestà del livello
   e della sicurezza del riconoscimento (tabella sotto).
2. **Il produttore**, se si è letto ma il livello è sotto «vino»
   (`apertura.cantina_sola`).
3. **Da dove viene** (`_corpo`): le uve per nome, se il nome del vino non le
   contiene già, e la prima frase della scheda del vitigno — agganciata con i due
   punti se l'uva è una sola, altrimenti col nome del vitigno davanti
   (`corpo.scheda_vitigno`). La regione entra solo se finora ci sono meno di due
   frasi.
4. **Il disciplinare**: colore e sapore, l'odore solo se uno dei due manca; se uve
   e scheda hanno già occupato due frasi, resta il solo sapore.
5. **Corpo e acidità**, nelle forme `narrativa` dei vocabolari, solo se non c'è
   nessuna citazione.
6. **A tavola**: temperatura e piatti in una frase. «16-18» diventa «fra 16 e 18
   gradi», perché il trattino letto dalla voce suonerebbe «meno».
7. Al livello generico, se si è detto qualcosa, l'ultima frase dichiara che la
   bottiglia non è in archivio (`corpo.generico_limite`).

Il corpo ha al massimo quattro frasi dopo l'apertura; in italiano un ultimo
passaggio mette la «d» eufonica («abbinato ad antipasti»). Ogni chiave del
lessico può avere un **elenco di forme equivalenti**, e le sceglie un seme:
`seme_di(fatti)`, un `crc32` dell'identità del vino stabile fra un avvio e
l'altro, declinato per ogni frase da `_seme_per`. Lo stesso vino si racconta
sempre con le stesse parole; due vini diversi non suonano come lo stesso modulo.

### L'apertura: livello e sicurezza

Le soglie sono `SOGLIA_CERTA` e `SOGLIA_DUBBIA` in `src/amelie/matcher.py`.

| Livello | Sicurezza | Chiave in `frasi.json` | Esempio (italiano) |
|---|---|---|---|
| `VINO` | certa | `apertura.vino_certo` | `Questo è il «…» di … annata ….` |
| `VINO` | dubbia / incerta | `vino_dubbio`, `vino_incerto` | `Direi il «…» di ….` |
| `TIPOLOGIA` | sopra / sotto la soglia dubbia | `tipologia_nota`, `tipologia_incerta` | `Questo è un ….` / `Direi un ….` |
| `DENOMINAZIONE` | — | `denominazione` + `sigle` | `Questo è un …, a denominazione di origine protetta.` |
| `VITIGNO` | sopra / sotto la soglia dubbia | `vitigno_noto`, `vitigno_incerto` | `Questo è un vino di ….` |
| `GENERICO` | — | `generico` | `Questo è uno spumante rosato, brut.` |
| niente di leggibile | — | `illeggibile`, `schermo.illeggibile_con_invito` | `Provi a girare l'etichetta verso di me.` |

### Le citazioni del disciplinare

Le descrizioni organolettiche della tipologia sono l'unica prosa dei fatti che
il progetto non ha scritto: sono il testo ufficiale.

- **In italiano** si riportano parola per parola. `_senza_coda_tronca` toglie
  l'ultimo inciso di un campo troncato a metà («…, dal»), e
  `_senza_doppioni_di_elenco` le voci che ripetono la precedente con un'aggiunta
  («giallo paglierino, giallo paglierino carico»).
- **In inglese** passano da `organolettico.Organolettico.rendi`, che spezza la
  citazione sui separatori e ricompone ogni frammento dagli atomi di
  `data/lessico/organolettico.json` con regole fisse: intervalli («da X a Y»),
  tendenze, riflessi, avverbi, inversione nome-aggettivo. **Non indovina**: un
  frammento che non sa rendere cade e la citazione esce più corta; intervalli e
  alternative passano interi o cadono interi, un elenco unito dalla «e» si può
  accorciare. Il risultato (`Reso`) dichiara se è `integrale` e che è `tradotto`.
- Poiché è una traduzione, le frasi inglesi dicono che cosa il disciplinare
  *prevede* («The specification calls for it to be …») invece di virgolettare, e
  il blocco dei fatti per il modello la dichiara *translated from the Italian*.

La forma della frase dipende da come comincia la citazione
(`_forma_della_citazione`): «che va dal…» usa le chiavi `*_relativa`, un verbo
(«sono asciutti…») usa `disciplinare_verbo`, un participio inglese («ranging
from…») vuole una forma con la virgola; una forma che ripete una parola della
citazione si scarta («il sapore è … di sapore pieno»).

### Un esempio

Una tipologia riconosciuta con sicurezza alta, nelle due lingue:

> Questo è un Barbera d’Asti. Barbera: Piemontese, generosa e di acidità
> spiccata, con tannino discreto. Secondo il disciplinare, deve presentarsi rosso
> rubino tendente al rosso granato con l'invecchiamento. Al palato, asciutto,
> tranquillo, di corpo, con adeguato invecchiamento più armonico, gradevole, di
> gusto pieno. Si serve fra 16 e 18 gradi, con salumi, pasta al ragu e carni
> bianche.

> This is a Barbera d’Asti. Barbera: Piedmontese, generous and markedly acidic,
> with restrained tannin. Under the production rules, it should be ruby red,
> tending to garnet red with age. In the mouth, it is dry, still, with body,
> pleasant and of full taste. Best served between 16 and 18 degrees, with cured
> meats, pasta with ragù and white meat.

Nella resa inglese «con adeguato invecchiamento più armonico» è caduto: non tutti
i suoi pezzi si sapevano rendere.

### La regola: non si inventa

- Un campo assente non produce una frase: non esiste un testo di riempimento.
- Le uve solo tollerate e i vitigni fittizi del registro (`matcher.VITIGNI_FINTI`)
  non si nominano.
- Al livello generico si dice soltanto ciò che sta scritto sulla bottiglia,
  filtrato da un elenco chiuso (`_che_tipo_di_vino`).
- Sotto la soglia di certezza l'apertura dichiara la supposizione, e non si
  attribuisce a un produttore ciò che non si è verificato.
- Un valore che un vocabolario non conosce torna com'è, nella lingua della fonte:
  i test di copertura esistono per trovarlo prima (`Lessico.manca`).

La composizione non passa dalla verifica a ogni racconto, perché non ha niente da
inventare; i test controllano che i testi composti la superino
(`TestIlRaccontoCompostoDaiFatti` in `tests/test_narrator.py`).

### Le lingue

Le lingue sono quelle dichiarate in `vocabolari.json` (`lingue`: italiano e
inglese). Si cambia a schermo con la bandierina (`POST /lingua/{codice}`): il
dispositivo annuncia la lingua a voce (`voce.conferma_lingua`) e, se un racconto
era in corso, lo rifà subito nella lingua nuova con gli stessi fatti. Quando la
bottiglia viene tolta si torna alla lingua di partenza, in silenzio. Anche le
scritte dello schermo stanno in `frasi.json` (gruppo `schermo`), così schermo e
racconto non parlano mai due lingue diverse.

## La verifica

`narrator.verifica(testo, fatti, lingua)` risponde a una domanda: *il testo
afferma solo cose presenti nei fatti?* Restituisce `(va_bene, invenzioni)`. È un
controllo deterministico in Python, che il modello non può aggirare; è
volutamente grossolano e preferisce un falso allarme, che costa un altro
tentativo o un ripiego, a un'affermazione falsa detta al tavolo. Il confronto
avviene contro tutto ciò che i fatti contengono, composto **nella lingua del
racconto** (un testo inglese si confronta con «Tuscany», non con «Toscana»),
senza accenti e con gli apostrofi uniformati.

| Che cosa cerca | Dove |
|---|---|
| numeri in cifre che nei fatti non ci sono | `verifica`, `_NUMERO` |
| nomi propri che nei fatti non ci sono (non a inizio frase, non le maiuscole d'uso) | `_PROPRIO`, `_MAIUSCOLE_INNOCENTI` |
| colore contraddetto (rosso su un bianco, bianco su un rosso, l'uno o l'altro su un rosato) e «colori» che sono categorie | `_colore_sbagliato` |
| gradazione e temperatura dette in lettere, confrontate con i valori veri | `_gradi_sbagliati` |
| il disciplinare invocato quando non c'è nessuna citazione | `verifica` |
| piatti e provenienze regionali che i fatti non danno | `_cibi_inventati`, `_provenienze_inventate` |
| nomi veri messi al posto delle uve: note olfattive, il nome del vino, la cantina, un luogo; «X in purezza» se X non è un'uva | `_vitigni_che_non_lo_sono` |
| bollicine su un vino fermo | `_categoria_sbagliata` |
| la cantina detta come luogo, le uve dette come produttore | `_produttore_al_posto_del_luogo`, `_uve_al_posto_del_produttore` |
| il colore detto nel giro di frase del gusto | `_colore_al_posto_del_gusto` |
| la scheda del vitigno appesa al nome del vino | `_scheda_attaccata_al_vino` |
| note olfattive dette come uve o come piatti, piatti detti come profumi | `_note_al_posto_sbagliato`, `_cibi_al_posto_dei_profumi` |
| il testo che gira a vuoto: parole o coppie ripetute, salvo dentro le citazioni | `_parole_ripetute`, `_coppie_ripetute` |

Si applica a ogni tentativo del modello (`Narratore._dal_modello`), a ogni
racconto pronto letto dall'archivio (`_dalla_cache`, che scarta anche i testi che
nominano un vitigno fittizio) e a ogni frase della via a flusso
(`racconta_a_frasi`, che l'applicazione non usa). Non si applica alla carta e
alle correzioni, che sono parole di una persona.

Che cosa **non** vede: il senso di un aggettivo. Un «fruttato» o un «vellutato»
assenti dai fatti passano, perché per capire che sono falsi bisognerebbe capire
la frase. E confronta il testo con i fatti, non i fatti con la realtà: se un dato
dell'archivio è sbagliato, il racconto lo ripete fedelmente.

## Il modo generativo

### Il modello

Il modello è un **Qwen2.5 da 0,5 miliardi di parametri affinato per questo
dispositivo** su racconti costruiti a partire dai fatti del database,
quantizzato in Q4_K_M (circa 400 MB). Lo serve `llama-server` di llama.cpp,
avviato da `scripts/systemd/amelie-llm.service` con il file
`/home/arduino/amelie/models/studente-q4_k_m.gguf`, su `127.0.0.1:8081`, 4
thread, contesto di 2048 token, `--cache-reuse 256` e un tetto
`MemoryMax=1400M` (se sfora, il servizio cade invece di mandare la board in
swap). Il client è `amelie.llm.Modello`; i parametri stanno in `ImpostazioniLLM`:
temperatura 0,2, `top_p` 0,9, penalità sulle ripetizioni 1,1, al massimo 120
token, sequenze di arresto contro il secondo paragrafo e le note a margine.

Il prompt ha due forme, e `--modello-addestrato` sceglie quella giusta:

- **modello affinato** (`prompt_addestrato`): il formato di chat di Qwen, una
  riga di istruzione per lingua (`ISTRUZIONE_ADDESTRATA`) e i fatti compatti
  (`Fatti.blocco_compatto`). È la forma che il modello si aspetta, parola per
  parola: con l'altra risponde peggio e più lentamente;
- **modello generico** (`prompt`): le istruzioni per esteso (`ISTRUZIONI`) e il
  blocco dei fatti con le etichette (`Fatti.blocco_fatti`).

### Quando scrive, e che cosa succede se sbaglia

In modo «generativa» `Narratore.racconta(fatti, preferisci_modello=True)` segue
quest'ordine:

1. **il cancello**: il modello scrive solo se i fatti contengono una citazione
   del disciplinare (`_abbastanza_per_il_modello`) e il livello non è generico.
   Senza citazione ha solo un elenco di campi e tende a riempire i buchi; al
   livello generico non c'è niente da affermare oltre a ciò che è scritto;
2. **il modello**, due tentativi (`_dal_modello`): ogni testo passa da
   `_ripulisci` (virgolette, titoli, elenchi, tetto di `PAROLE_MAX` parole,
   chiusura sull'ultima frase intera) e poi da `verifica`;
3. **il racconto pronto** in archivio per quel record esatto, verificato;
4. **la composizione dai fatti**.

Mentre il modello lavora lo schermo mostra «Sto scrivendo la descrizione…»
(evento `scrivendo`) e `Amelie._aspetta_il_modello` attende, entro un tetto, che
il server sia pronto. Se non lo è, la richiesta fallisce con
`ModelloNonDisponibile` e si scende ai gradini successivi: acceso non vuol dire
mai silenzio.

### Acceso e spento

Il modello è installato sul dispositivo ma **spento in modo predefinito**:
`scripts/install.sh` installa l'unità senza abilitarla, e il modo predefinito è
«archivio». Lo accende e lo spegne l'applicazione col modo di racconto
(`Amelie._accendi_il_modello`): `systemctl start` entrando in «generativa»,
`stop` uscendone, `restart` con «Ripristina il funzionamento»; all'avvio lo
accende solo se il modo salvato lo chiede. L'applicazione gira senza privilegi:
il permesso di gestire quell'unica unità viene dalla regola polkit
`scripts/systemd/50-amelie-llm.rules`.

Per usarlo:

1. il file del modello deve stare in `models/studente-q4_k_m.gguf` sulla board;
2. l'applicazione deve partire con `--con-modello --modello-addestrato`, come fa
   `scripts/systemd/amelie.service`; senza `--con-modello` il modo «generativa»
   non compare e un modo salvato torna all'archivio;
3. si sceglie «Scritto sul momento» nelle impostazioni, oppure:

```bash
curl -X POST http://127.0.0.1:8080/modo/generativa
systemctl status amelie-llm             # il servizio parte da solo
curl http://127.0.0.1:8081/health        # risponde quando il modello è caricato
```

Il file dei pesi non sta nel repository: è un allegato della release, e
`scripts/install.sh` lo scarica in `models/` e ne controlla la somma SHA-256
(`scripts/modelli.sha256`). È Qwen2.5-0.5B-Instruct affinato con LoRA su
racconti di due provenienze, tutti filtrati dalla stessa `verifica`: scritti da
Qwen2.5-7B-Instruct a partire dai fatti del database, e composti dai fatti con
il lessico. È quantizzato in Q4_K_M con il llama.cpp che lo esegue sulla board.
Entrambi i modelli Qwen sono Apache-2.0, e così il modello affinato. Per provarne
un altro basta mettere un GGUF compatibile al posto di quel file e riavviare
`amelie-llm`.

### Limiti

- **È lento.** La composizione è immediata; il modello richiede un'attesa ben
  percepibile, coperta a schermo dalla scritta di lavoro. Il selettore lo
  dichiara sperimentale.
- **Costa CPU anche fermo.** `llama-server` in attesa occupa un core, lo stesso
  di cui ha bisogno l'OCR: per questo si accende solo nel modo che lo usa.
- **Può essere scartato.** Quando i due tentativi non passano la verifica, o la
  bottiglia non ha citazioni del disciplinare, il racconto è composto dai fatti,
  già pronto in archivio o composto sul momento. Il campo `origine` e il
  giornale di bordo dicono da dove viene quello che si è sentito.
- **Una verifica passata non è una garanzia**: gli aggettivi plausibili non si
  intercettano. Il modo «archivio» è l'unico in cui ogni parola viene dai dati.
- Scrive in italiano e in inglese (`ISTRUZIONE_ADDESTRATA`).

### La gabbia (spenta)

`src/amelie/gabbia.py` costruisce per ogni bottiglia una grammatica GBNF: solo
le parole dei suoi fatti, un lessico chiuso di raccordo
(`data/lessico/gabbia_it.txt`), cifre e punteggiatura. `Modello.genera` la passa
al server come `grammar` e llama.cpp la applica token per token. Esiste solo per
l'italiano ed è spenta (`gabbia=False` dove `app.py` crea il `Narratore`): sui
record poveri il vocabolario chiuso costringe il modello alla parola ammessa più
vicina, e l'italiano ne esce rotto.

### Misurare sulla board

```bash
python3 scripts/bench_llm.py            # un'etichetta, due giri
python3 scripts/bench_llm.py --tutti    # alcuni casi diversi
```

Con il servizio acceso, stampa per ogni caso livello, sicurezza, durata di ogni
giro ed esito della verifica; il secondo giro mostra la cache del prefisso. Usa
il prompt del modello generico (`narrator.prompt`), non `prompt_addestrato`:
misura server e verifica, non la resa del modello affinato come la usa il
dispositivo.

## La carta dei vini

Con `--carta FILE.csv` il dispositivo può raccontare da un file scritto a mano
(`src/amelie/carta.py`); il servizio di sistema punta a
`/home/arduino/amelie/vini.csv`.

```csv
titolo,descrizione,titolo_en,descrizione_en
"Nome della denominazione","Il racconto in italiano…","Name","The story in English…"
```

`titolo` e `descrizione` sono obbligatori; ogni colonna `descrizione_xx` aggiunge
una lingua. Si cerca solo il titolo, e le parole che lo identificano devono essere
state lette sul vetro (fanno eccezione le sigle di denominazione, `TACITE`). Non
c'è cascata: una bottiglia che la carta non ha conta come lettura fallita, e il
dispositivo chiede di girare l'etichetta. Il racconto è l'apertura con il titolo
(`apertura.tipologia_nota`) seguita dalla descrizione com'è; se la descrizione
manca nella lingua scelta si racconta dai fatti dell'archivio, cercati comunque
in parallelo. Un file assente o senza voci utilizzabili non ferma l'avvio: il
modo «carta» semplicemente non compare.

## La voce

| Lingua | Voce Piper (`speech.VOCI`) | Licenza |
|---|---|---|
| italiano | `it_IT-serena-medium` | CC BY 4.0 |
| inglese | `en_US-ljspeech-medium` | dataset LJ Speech, pubblico dominio |

Piper è GPL-3.0; le due voci sono addestrate da zero su dati che ne permettono
anche l'uso commerciale (attribuzioni in [08-attribuzioni.md](08-attribuzioni.md)). I file `.onnx`
li scarica `scripts/install.sh` in `models/`; `Voce._percorso_modello` li cerca
anche in `~/.local/share/piper/voices` e `/usr/share/piper-voices`. All'avvio
`Amelie._scalda_voci` carica tutte e due le voci e pre-sintetizza l'annuncio di
lingua. Una lingua senza voce mostra il testo, che scorre al ritmo di una lettura
(`_scorri_senza_voce`), e lo schermo lo dice (`schermo.voce_assente`).

### Dal testo all'altoparlante

```
frase ──► per_la_voce()              sigle sciolte, nomi stranieri, «16-18» → «16 e 18»
      ──► Piper (ONNX)               PCM 16 bit, 22 050 Hz, mono
      ──► ~/.cache/amelie/voce/*.raw cache per voce e frase
      ──► Riproduttore               buffer in memoria, posizione in byte
      ──► Uscita                     flusso sempre aperto, volume applicato qui
      ──► aplay -D plughw:0,3        ALSA converte la frequenza per l'HDMI
      ──► MultiMedia4 ─► SEC_MI2S_RX ─► I2S ─► ANX7625 ─► HDMI ─► schermo
```

- **La pronuncia** (`speech.PRONUNCIA`, `PRONUNCIA_EN`) riscrive il testo prima
  della sintesi: le sigle di denominazione diventano la dicitura per esteso nella
  lingua giusta, la voce italiana riceve una grafia fonetica dei nomi francesi e
  tedeschi più comuni, le virgolette non si pronunciano. La cache è indicizzata
  sulla voce e sul testo riscritto.
- **L'uscita** (`speech.Uscita`) apre `aplay` all'avvio e non lo chiude più:
  quando non c'è niente da dire versa silenzio. Il DSP della scheda tarda a
  rendere il suono dopo l'apertura del flusso, e tenerlo aperto evita di pagare
  quel ritardo a ogni frase. I dati si scrivono a passo d'orologio, a pezzi
  piccoli, così la posizione dichiarata resta vicina a ciò che si sente.
- **Il dispositivo ALSA** è `plughw:0,3` (opzione `--audio`): `plughw` e non
  `hw`, perché l'HDMI accetta solo 32–48 kHz e Piper produce 22 050 Hz. La rotta
  del mixer (`SEC_MI2S_RX Audio Mixer MultiMedia4`) la apre a ogni avvio
  `scripts/systemd/amelie-audio-rotta.sh`, e `amelie-audio-guard.sh` si assicura
  che la scheda audio esista. Il suono esce dagli altoparlanti dello schermo o
  dalla sua uscita cuffie.
- **Il volume** non ha un controllo hardware su questa catena: si applica al PCM
  in `Uscita._versa`, a tutto ciò che esce. Va da 0 a 100 e diventa guadagno col
  quadrato (`guadagno_di`: metà corsa è circa −12 dB, mai oltre 1). Si regola
  con `POST /volume/{valore}` a passi di `PASSO_VOLUME`, si salva in
  `var/volume` (il valore iniziale viene da `--volume`), e un tocco di calice
  sintetizzato (`Voce.colpetto`) fa sentire il livello scelto. A 0 il racconto
  continua sullo schermo.

## Il riproduttore

`speech.Riproduttore` rende il racconto governabile. Ha una sola verità, la
**posizione in byte** nel buffer del racconto, e da quella ricava i secondi
trascorsi, la frase da illuminare e il punto da cui ripartire. Un thread
sintetizza le frasi una dopo l'altra e annota dove comincia ciascuna
(`_sintetizza_tutto`), l'altro manda l'audio all'`Uscita` dalla posizione
corrente (`_suona`): la prima frase suona appena è pronta.

| Pulsante | `POST /racconto/{azione}` | Effetto |
|---|---|---|
| play / pausa | `alterna` (o `pausa`, `riprendi`) | in pausa torna indietro di quanto era stato inviato ma non ancora sentito, così la ripresa non taglia una parola |
| avanti / indietro | `avanti`, `indietro` | `salta(±SALTO_S)`, un passo fisso; in avanti non oltre ciò che è già sintetizzato |
| da capo | `ricomincia` | dall'inizio |
| annulla | `POST /annulla` | chiude il racconto e torna all'invito |

Togliere la bottiglia per versare non interrompe il racconto. Lo stato arriva
alla pagina sul flusso `GET /eventi` come evento `riproduzione`
(`Riproduttore.istantanea`: `posizione`, `durata`, `quota`, `frase`, `in_pausa`,
`completo`). La barra usa `quota`: la posizione divisa per l'audio già
sintetizzato **più** la durata stimata delle frasi che mancano (`byte_stimati`,
dai caratteri che verranno davvero pronunciati, con le cifre pesate da
`CIFRA_VALE` e il ritmo di ogni voce in `CARATTERI_AL_SECONDO`). Un pavimento le
impedisce di arretrare quando una stima diventa una durata vera; arretra solo con
pausa, salto e «da capo». Il testo arriva a schermo tutto insieme, spezzato da
`spezza_in_frasi`, che non spezza dentro le sigle né dopo le iniziali puntate.

## Cambiare frasi, vocabolari e pronuncia

**`data/lessico/frasi.json`**: gruppi `apertura`, `corpo`, `generico`, `sigle`
per il racconto, `schermo` per le scritte, `voce` per le frasi solo pronunciate.
Ogni chiave ha una voce per lingua, frase singola o elenco di forme equivalenti;
le chiavi che cominciano con `_` sono note.

- I **segnaposto** fra graffe sono gli stessi in tutte le lingue e varianti;
  l'articolo davanti ai nomi lo mette il codice (`_con_articolo`).
- Una **variante** dice la stessa cosa della prima, che è quella di riferimento,
  senza aggiungere niente. Aggiungerne una cambia la scelta del seme per molti
  vini: il racconto resta vero, ma cambia parole.
- Il registro è impersonale quando si descrive il vino («Si serve fra…») e dà del
  lei quando ci si rivolge all'ospite.
- Se una forma nuova introduce le uve con un giro di frase che la verifica non
  conosce, va aggiunto a `_CONTESTO_VITIGNI` in `narrator.py`.

**`data/lessico/vocabolari.json`**: i vocabolari controllati dei dataset
(`tipo`, `colore`, `categoria_ue`, `elaborazione`, `corpo`, `acidita`,
`abbinamento`). Le **chiavi sono i valori esatti delle fonti** e non si cambiano:
sono chiavi di collegamento. Ogni termine ha, per lingua, un'`etichetta` per lo
schermo e, facoltativa, una forma `narrativa` per dentro una frase («bella
acidità» invece di «alta»).

**`data/lessico/organolettico.json`**: gli atomi italiano → inglese delle
citazioni, in `termini` (colori, riflessi, intensità, olfatto, materia, gusto,
effervescenza, menzioni, idiomi), più `per_ambito` per le parole che cambiano
senso fra colore, odore e sapore («vivace», «rosa») e `nomi` per i sostantivi.
Un atomo mancante fa cadere il frammento che lo contiene: aggiungerlo allunga le
citazioni inglesi senza toccare il codice.

**`data/vitigni.json`**: le schede dei vitigni, scritte a mano (`descrizione`,
`note_sensoriali`, `abbinamenti` con le versioni `_en`, `temperatura_c`) e gli
`alias` con cui i dataset chiamano lo stesso vitigno, dichiarati uno per uno: un
aggancio per somiglianza di nome legherebbe vitigni diversi. Si riapplicano al
database esistente con `python3 data/build_db.py --solo-vitigni`.

**La pronuncia**: una sigla letta male o un nome storpiato si corregge con una
coppia espressione regolare → sostituzione in `PRONUNCIA` o `PRONUNCIA_EN`
(`src/amelie/speech.py`). La cache è indicizzata sul testo riscritto, quindi la
correzione vale subito.

### Aggiungere una lingua

1. La sigla in `lingue` di `vocabolari.json` e la voce per ogni termine.
2. Ogni chiave di `frasi.json` nella nuova lingua, con gli stessi segnaposto.
3. Una voce Piper in `speech.VOCI` e il suo ritmo in `CARATTERI_AL_SECONDO`;
   senza, il racconto si legge soltanto.
4. Nel codice, i punti che oggi conoscono italiano e inglese: le citazioni del
   disciplinare (`organolettico.json` rende solo in inglese), le tabelle di
   pronuncia (`_COMPILATE`), la congiunzione di `elenca_in_lingua`, l'articolo di
   `_con_articolo`, le etichette del blocco dei fatti (`_ETICHETTE_BLOCCO` in
   `matcher.py`) e, per il modello, `ISTRUZIONE_ADDESTRATA`.
5. Nella carta, le colonne `titolo_xx` e `descrizione_xx`.

### Dopo ogni modifica

```bash
python3 -m pytest tests/test_lessico.py tests/test_narrator.py tests/test_organolettico.py
```

I test del lessico falliscono se una frase manca in una lingua, se i segnaposto
non coincidono o se un valore dei dataset non ha traduzione; quelli del narratore
controllano, fra l'altro, che i testi composti superino la verifica. Poi si
rigenerano i racconti pronti e si porta tutto sulla board: con `git pull` e
`bash scripts/install.sh` sulla board, che ricostruisce il database quando le
sorgenti cambiano, oppure dal PC con `scripts/rilascio.sh`, che copia codice,
lessico, schede e database e tiene sulla board una copia di sicurezza del
database.

## Rigenerare i racconti pronti

La tabella `racconto` del database contiene un racconto già composto per ogni
tipologia, denominazione e vitigno descritto, in ogni lingua. Il testo è il
**corpo senza apertura** (`narrator.corpo_neutro`): l'apertura dipende dalla
sicurezza del riconoscimento, che si conosce solo al momento, e la compone il
`Narratore` quando lo usa. Questi testi servono nel modo «generativa», come
secondo gradino dopo il modello; il modo «archivio» compone sempre dal vivo e
risente subito di ogni modifica al lessico.

```bash
python3 scripts/genera_corpus.py                  # scrive ciò che manca
python3 scripts/genera_corpus.py --rigenera       # riscrive anche ciò che c'è
python3 scripts/genera_corpus.py --lingua en      # una lingua sola (ripetibile)
python3 scripts/genera_corpus.py --solo vitigno   # un ambito solo (ripetibile)
python3 scripts/genera_corpus.py --limite 50      # i primi N per ambito
```

Lo script scrive in `data/amelie.db`, che l'applicazione apre in sola
lettura; `data/build_db.py` lo lancia da sé alla fine di ogni costruzione del
database, quindi serve a mano solo per provare una modifica al lessico senza
ricostruire tutto. Ordina denominazioni e tipologie per quanti vini vi fanno
capo, così un lavoro interrotto lascia pronto ciò che si incontra più spesso, e
salta i record senza niente da dire: una riga vuota impedirebbe il ripiego sul
gradino successivo. La colonna `modello` dice la provenienza di ogni riga; le
righe composte hanno `template`, e `--rigenera` riscrive solo quelle. Va
rilanciato con `--rigenera` dopo ogni modifica a `frasi.json`, ai vocabolari, agli
atomi organolettici o alle schede dei vitigni.
