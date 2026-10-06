# Il racconto e la voce

Questo documento spiega come Amelie trasforma i fatti di una bottiglia in un
testo, come quel testo si controlla prima di essere detto e come arriva
all'altoparlante dello schermo. Serve a chi vuole cambiare le frasi, aggiungere
una lingua, accendere il modello linguistico o capire perché il dispositivo dice
quello che dice.

Il punto di partenza sono i `Fatti` prodotti dal riconoscimento (vedi
[06-riconoscimento.md](06-riconoscimento.md)). Tutto gira sulla board, senza
rete. I riferimenti al codice sono relativi alla radice del repository.

## Le parole che servono

| termine | che cosa vuol dire qui |
|---|---|
| fatti | l'oggetto `Fatti` che il riconoscimento restituisce: livello, sicurezza, nomi, uve, citazioni, abbinamenti; tutto e solo ciò che l'archivio sa di quella bottiglia |
| livello, sicurezza | fin dove è scesa la cascata del riconoscimento (vino, tipologia, denominazione, vitigno, generico) e quanto si può sostenere ciò che si afferma, da 0 a 100 |
| denominazione, DOP, IGP | il nome protetto di una zona di produzione; DOP e IGP sono le due categorie europee (denominazione di origine protetta, indicazione geografica protetta) |
| tipologia | uno dei vini che una denominazione prevede, con nome, colore e categoria |
| disciplinare | il regolamento di produzione di una denominazione, con una descrizione ufficiale di colore, odore e sapore di ogni tipologia; una **citazione** è una di quelle descrizioni, riportata nel racconto |
| lessico | i file di `data/lessico/`: le frasi del racconto e i vocabolari che traducono i valori dei dataset |
| seme | un numero ricavato dall'identità del vino, che sceglie fra le forme equivalenti di una frase |
| modello linguistico | una rete neurale che scrive testo; qui Qwen2.5-0.5B-Instruct, da mezzo miliardo di parametri |
| token | il pezzo di testo, una parola o una sua parte, con cui un modello linguistico legge e scrive |
| LoRA | *low-rank adaptation*: un modo di affinare un modello addestrando solo piccole matrici aggiunte ai suoi pesi |
| GGUF, Q4_K_M | GGUF è il formato dei file di modello di llama.cpp; Q4_K_M è una quantizzazione, cioè i pesi conservati per lo più a 4 bit invece che a 16, per occupare meno memoria e girare più in fretta sulla CPU |
| llama.cpp | il programma che esegue il modello sulla CPU della board; `llama-server` lo offre come servizio HTTP |
| Piper | il sintetizzatore vocale: una rete neurale per voce, in formato ONNX |
| ALSA, PCM | ALSA è il sistema audio di Linux; PCM è il suono non compresso, una sequenza di campioni |

## La catena in un colpo d'occhio

```
riconoscimento ──► Amelie._racconta ──┬─ correzione scritta in sala ──► apertura col titolo + testo com'è
                                      ├─ modo «carta» ────────────────► apertura col titolo + descrizione del CSV
                                      └─ Narratore.racconta
                                           ├─ «archivio»   ► template()        composizione dai fatti
                                           └─ «generativa» ► modello ► verifica
                                                             └ no ► racconto pronto ► verifica
                                                                    └ no ► template()
testo ──► spezza_in_frasi ──► schermo (messaggio «racconto»)
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
`POST /modo/{archivio|generativa|carta}`. Si salva in
`var/modo` e vale **dalla bottiglia dopo**: il racconto in corso non si
interrompe. Un'installazione nuova, senza un modo salvato, racconta
dall'archivio. Un modo che il dispositivo non può servire non compare fra le
scelte, e un modo salvato che il dispositivo non può servire torna all'archivio
(`Amelie._modo_salvato`).

In `Amelie._racconta` l'ordine è fisso: prima una **correzione** scritta in sala
per quella bottiglia, se ha il testo nella lingua corrente (vale in tutti i modi
e si legge com'è); poi la **carta**, se ha il testo nella lingua corrente; poi il
`Narratore`. Correzione e carta si aprono con il titolo, nella forma
`apertura.tipologia_nota` («Questo è un …»). Ogni racconto porta la sua `origine`
— `template`, `cache`, `modello`, `carta` o `correzione` — che viaggia nel
messaggio `racconto` del flusso `GET /eventi` e finisce nel giornale di bordo
(`racconto_da`) insieme al testo detto.

## La composizione dai fatti

È il modo «archivio»: `narrator.template(fatti, lessico, lingua)`. Ogni frase
nasce da un campo dell'archivio o da una citazione del disciplinare, dentro una
forma presa da `data/lessico/frasi.json`. Il codice decide *quale* frase dire; il
testo delle frasi sta nel lessico, una versione per lingua.

### I fatti che entrano

| Campo di `Fatti` | Da dove viene | Come si usa |
|---|---|---|
| `nome`, `cantina` | il vino commerciale riconosciuto; la cantina anche quando è scritta sull'etichetta e il livello è più basso | nell'apertura, o nella frase sul produttore |
| `annata` | letta sull'etichetta | nell'apertura, al livello vino |
| `tipologia`, `denominazione`, `tipo_denominazione` | il registro delle denominazioni | nell'apertura (DOP o IGP) |
| `vitigni` | per un vino commerciale le sue uve, in ordine alfabetico; per una tipologia le uve principali del disciplinare, ordinate per quanti vini di quella denominazione, in archivio, le dichiarano (`matcher._USO_NEI_VINI`); per una denominazione le uve principali in almeno metà delle sue tipologie, con lo stesso ordine | «Nasce da …», al massimo quattro; la prima dà la scheda |
| `vitigni_ammessi` | le uve che il disciplinare tollera | **mai dette** |
| `note_vitigno` | la scheda del primo vitigno (`data/vitigni.json`) | la sua prima frase |
| `disciplinare` | le descrizioni ufficiali della tipologia: colore, odore, sapore | citate (in inglese: rese) |
| `corpo`, `acidita` | il vino commerciale, come chiavi dei vocabolari controllati | solo se il disciplinare tace |
| `abbinamenti` | il vino commerciale o la scheda del vitigno | al massimo tre piatti |
| `temperatura_c` | la categoria per spumanti (6-8 gradi), frizzanti (8-10), passiti e vini da uve stramature (10-12) e liquorosi (12-14); altrimenti la scheda del vitigno | con i piatti, in una frase |
| `regione` | l'archivio; in inglese si traduce con il vocabolario `regione` (Toscana → Tuscany, Piemonte → Piedmont) | solo quando c'è poco altro da dire |
| `qualificatori` | parole lette sull'etichetta (livello generico) | «uno spumante rosato, brut» |

I fatti si portano dietro le schede in tutte le lingue (`Fatti.per_lingua`,
`nota_in`, `abbinamenti_in`, `sensoriali_in`): cambiare lingua non richiede di
rileggere l'etichetta.

### Come si monta

1. **L'apertura** (`_apertura`): che cosa si ha davanti, con l'onestà del livello
   e della sicurezza del riconoscimento (tabella sotto).
2. **Il produttore**, se si è letto ma il livello è sotto «vino»
   (`apertura.cantina_sola`: «Lo produce …»).
3. **Da dove viene** (`_corpo`): le uve per nome, se il nome del vino non le
   contiene già, e la prima frase della scheda del primo vitigno. Con un'uva sola
   la scheda si aggancia con i due punti («Nasce da Chardonnay: …»); con più uve,
   o senza la frase delle uve, porta davanti il nome del vitigno
   (`corpo.scheda_vitigno`, «Barbera: …»), salvo quando la sua prima frase lo
   nomina già. La regione entra solo se finora ci sono meno di due frasi e non è
   già nel nome della denominazione.
4. **Il disciplinare**: colore e sapore, l'odore solo se uno dei due manca; se
   prima ci sono già due frasi, resta una citazione sola, il sapore se c'è.
5. **Corpo e acidità**, nelle forme `narrativa` dei vocabolari, solo se non c'è
   nessuna citazione.
6. **A tavola**: temperatura e piatti in una frase. «16-18» diventa «fra 16 e 18
   gradi» (in inglese «between 16 and 18 degrees»), perché una voce sintetica non
   legge bene il trattino fra due numeri.
7. Al livello generico, se l'etichetta ha dato almeno un qualificatore o un
   colore, l'ultima frase dichiara che la bottiglia non è nell'archivio
   (`corpo.generico_limite`).

Il corpo ha al massimo quattro frasi dopo l'apertura; in italiano un ultimo
passaggio mette la «d» eufonica («abbinato ad antipasti»). Ogni chiave del
lessico può avere un **elenco di forme equivalenti**, e le sceglie un seme:
`seme_di(fatti)`, un `crc32` (una somma di controllo a 32 bit) dell'identità del
vino, stabile fra un avvio e l'altro, declinato per ogni frase da `_seme_per`. Lo
stesso vino si racconta sempre con le stesse parole; due vini diversi non suonano
come lo stesso modulo.

### L'apertura: livello e sicurezza

Le soglie sono `SOGLIA_CERTA` (88) e `SOGLIA_DUBBIA` (75) in
`src/amelie/matcher.py`. Gli esempi sono le forme di riferimento, cioè le prime
dell'elenco.

| Livello | Sicurezza | Chiave in `frasi.json` | Esempio (italiano) |
|---|---|---|---|
| `VINO` | certa | `apertura.vino_certo` | `Questo è il «…» di … annata ….` |
| `VINO` | dubbia / sotto la soglia dubbia | `vino_dubbio`, `vino_incerto` | `Direi il «…» di ….` |
| `TIPOLOGIA` | sopra / sotto la soglia dubbia | `tipologia_nota`, `tipologia_incerta` | `Questo è un ….` / `Direi un ….` |
| `DENOMINAZIONE` | — | `denominazione` + `sigle` | `Questo è un …, a denominazione di origine protetta.` |
| `VITIGNO` | sopra / sotto la soglia dubbia | `vitigno_noto`, `vitigno_incerto` | `Questo è un vino di ….` / `Direi un ….` |
| `GENERICO` | — | `generico` | `Questo è uno spumante rosato, brut.` |
| niente di leggibile | — | `illeggibile`, `schermo.illeggibile_con_invito` | `Provi a girare l'etichetta verso di me.` |

### Le citazioni del disciplinare

Le descrizioni organolettiche della tipologia sono l'unica prosa dei fatti che
il progetto non ha scritto: sono il testo ufficiale. Entrano nei fatti già
ripulite dal riconoscimento (`matcher._citazioni_utili`): si tolgono i tronconi
lasciati dal taglio del documento d'origine, le parole rimaste appese in fondo
(«…, il»), il verbo iniziale e le parole ripetute di seguito, e si scartano le
citazioni che contengono parametri di legge o superano i 120 caratteri.

- **In italiano** si riportano parola per parola. `_senza_coda_tronca` toglie
  l'ultimo inciso di un campo troncato a metà («…, dal»), e
  `_senza_doppioni_di_elenco` le voci che ripetono la precedente con un'aggiunta
  («giallo paglierino, giallo paglierino carico»).
- **In inglese** passano da `organolettico.Organolettico.rendi`, che spezza la
  citazione su virgole e punti e virgola e ricompone ogni frammento dagli atomi
  di `data/lessico/organolettico.json` con regole fisse: intervalli («da X a
  Y»), tendenze, riflessi, avverbi, inversione nome-aggettivo. **Non indovina**:
  un frammento che non sa rendere cade e la citazione esce più corta; intervalli
  e alternative passano interi o cadono interi, un elenco unito dalla «e» si può
  accorciare. Il risultato (`Reso`) dichiara se è `integrale` e che è
  `tradotto`.
- Poiché è una traduzione, le frasi inglesi dicono che cosa il disciplinare
  *prevede* («The specification calls for it to be …») e non lo presentano come
  le sue parole; il blocco dei fatti con le etichette, quello del prompt per un
  modello generico (`Fatti.blocco_fatti`), la dichiara *translated from the
  Italian*.

La forma della frase dipende da come comincia la citazione
(`_forma_della_citazione`): «che va dal…» usa le chiavi `*_relativa`, un verbo
(«sono asciutti…», o in inglese «may be…») usa `disciplinare_verbo`, un
participio inglese («ranging from…») vuole una forma con la virgola; una forma
che ripete una parola della citazione si scarta («il sapore è … di sapore
pieno»).

### Un esempio

La tipologia «Barbera d’Asti», riconosciuta con una sicurezza di almeno 75 e
senza annata leggibile, nelle due lingue:

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

Il nome «Barbera d’Asti» contiene già l'uva, quindi manca la frase «Nasce da» e
la scheda porta il nome davanti. Nella resa inglese «con adeguato invecchiamento
più armonico» è caduto: non tutti i suoi pezzi si sapevano rendere.

### La regola: non si inventa

- Un campo assente non produce una frase: non esiste un testo di riempimento.
- Le uve solo tollerate e i vitigni fittizi del registro (`matcher.VITIGNI_FINTI`:
  «na», «n.d.» e simili, che stanno dove il registro non ha un'uva) non si
  nominano.
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
avviene contro tutto ciò che i fatti contengono, composto anche **nella lingua
del racconto** (un testo inglese si confronta con «Tuscany», non soltanto con
«Toscana»), senza accenti e con gli apostrofi uniformati.

| Che cosa cerca | Dove |
|---|---|
| numeri in cifre che nei fatti non ci sono | `verifica`, `_NUMERO` |
| nomi propri che nei fatti non ci sono (non a inizio frase né dopo i due punti, non le maiuscole d'uso) | `_PROPRIO`, `_MAIUSCOLE_INNOCENTI` |
| colore contraddetto (rosso su un bianco, bianco su un rosso, l'uno o l'altro su un rosato) e «colori» che sono categorie | `_colore_sbagliato` |
| gradazione e temperatura dette in lettere, confrontate con i valori veri | `_gradi_sbagliati` |
| il disciplinare invocato quando non c'è nessuna citazione | `verifica` |
| piatti e provenienze regionali che i fatti non danno | `_cibi_inventati`, `_provenienze_inventate` |
| nomi veri messi al posto delle uve: note olfattive, il nome del vino, la cantina, la denominazione; «X in purezza» se X non è un'uva | `_vitigni_che_non_lo_sono` |
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

Il modello è **Qwen2.5-0.5B-Instruct**, da mezzo miliardo di parametri,
**affinato con LoRA per questo dispositivo** e quantizzato in Q4_K_M: un file
GGUF di circa 380 MB, `studente-q4_k_m.gguf`. È affinato su racconti di due
provenienze, tutti filtrati dalla stessa `verifica`: scritti da
Qwen2.5-7B-Instruct a partire dai fatti del database, e composti dai fatti con il
lessico. Entrambi i modelli Qwen sono Apache-2.0, e così il modello affinato
(vedi [08-attribuzioni.md](08-attribuzioni.md)).

Lo esegue `llama-server`, compilato da `scripts/install.sh` da llama.cpp a una
versione fissata. Lo avvia l'unità systemd `scripts/systemd/amelie-llm.service`
con il file `/home/arduino/amelie/models/studente-q4_k_m.gguf`, in ascolto su
`127.0.0.1:8081`, con 4 thread, un contesto di 2048 token, `--cache-reuse 256`
(riusa la parte iniziale del prompt già elaborata in una richiesta precedente) e
un tetto `MemoryMax=1400M`: se lo sfora, il servizio cade invece di mandare la
board in swap. Il client è `amelie.llm.Modello`; i parametri stanno in
`ImpostazioniLLM`: temperatura 0,2, `top_p` 0,9, penalità sulle ripetizioni 1,1,
al massimo 120 token, 180 s di attesa massima per una risposta, e sequenze di
arresto contro il secondo paragrafo e le note a margine.

Il prompt, cioè il testo che si dà al modello, ha due forme, e
`--modello-addestrato` sceglie quella giusta:

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
   `_ripulisci` (virgolette, titoli, elenchi, tetto di `PAROLE_MAX` parole, cioè
   130, chiusura sull'ultima frase intera) e poi da `verifica`. Se il server non
   risponde, la richiesta fallisce con `ModelloNonDisponibile` e si passa subito
   al gradino successivo;
3. **il racconto pronto** in archivio per quel record esatto, verificato (ce
   n'è uno per ogni tipologia, denominazione e vitigno con qualcosa da dire, non
   per i vini commerciali);
4. **la composizione dai fatti**.

Quando il modello sta per scrivere, lo schermo mostra «Sto scrivendo la
descrizione…» (messaggio `scrivendo`) e `Amelie._aspetta_il_modello` attende
fino a 45 s che il server risponda su `/health`: il servizio può essere appena
partito e deve caricare il modello. Se non arriva, si scende ai gradini
successivi: acceso non vuol dire mai silenzio.

### Acceso e spento

Il modello è installato sul dispositivo ma **spento in modo predefinito**:
`scripts/install.sh` installa l'unità senza abilitarla all'avvio, e un'installazione
nuova racconta dall'archivio. Lo accende e lo spegne l'applicazione col modo di
racconto (`Amelie._accendi_il_modello`): `systemctl start` scegliendo
«generativa», `stop` scegliendo un altro modo, `restart` con «Ripristina il
funzionamento» quando il modo è «generativa»; all'avvio dell'applicazione lo
accende solo se il modo salvato è «generativa». L'applicazione gira senza
privilegi: il permesso di gestire quell'unica unità viene dalla regola polkit
`scripts/systemd/50-amelie-llm.rules` (polkit è il componente di Linux che decide
quali azioni di sistema un utente può fare).

Il file dei pesi non sta nel repository: è un allegato della release v1.0.0, e
`scripts/install.sh` lo scarica in `models/` e ne controlla la somma SHA-256
(`scripts/modelli.sha256`); la variabile `AMELIE_URL_MODELLO` permette di
scaricarlo da un altro indirizzo. Con l'installazione standard il resto è già al
suo posto: `scripts/systemd/amelie.service` avvia l'applicazione con
`--con-modello --modello-addestrato`. Senza `--con-modello` il modo «generativa»
non compare e un modo salvato torna all'archivio. Per usarlo si sceglie «Scritto
sul momento» nelle impostazioni, oppure:

```bash
curl -X POST http://127.0.0.1:8080/modo/generativa
systemctl status amelie-llm             # il servizio parte da solo
curl http://127.0.0.1:8081/health        # risponde quando il modello è caricato
```

Per provare un altro modello si mette un GGUF compatibile al posto di quel file
e si riavvia `amelie-llm`; se non è il modello affinato, l'applicazione va
avviata senza `--modello-addestrato`, perché gli serve il prompt generico.
`scripts/install.sh`, rilanciato, rimette il file ufficiale, perché la somma non
coincide più.

### Limiti

- **È lento.** La composizione è immediata; il modello richiede qualche decina di
  secondi, coperti a schermo dalla scritta di lavoro. Il selettore lo dichiara
  sperimentale.
- **Costa CPU anche fermo.** `llama-server` in attesa occupa quasi un core intero
  (l'88 %, misurato), e su quei quattro core l'OCR deve leggere: per questo si
  accende solo nel modo che lo usa.
- **Può essere scartato.** Quando i due tentativi non passano la verifica, o la
  bottiglia non ha citazioni del disciplinare, il racconto è composto dai fatti,
  già pronto in archivio o composto sul momento. Il campo `origine` e il
  giornale di bordo dicono da dove viene quello che si è sentito.
- **Una verifica passata non è una garanzia**: gli aggettivi plausibili non si
  intercettano. Il modo «archivio» è l'unico in cui ogni parola viene dai dati.
- Scrive in italiano e in inglese (`ISTRUZIONE_ADDESTRATA` ha una riga per
  ciascuna).

### La gabbia (spenta)

`src/amelie/gabbia.py` costruisce per ogni bottiglia una grammatica GBNF (il
formato con cui llama.cpp riceve una grammatica che limita le parole
ammesse): solo le parole dei suoi fatti, un lessico chiuso di 310 parole di
raccordo (`data/lessico/gabbia_it.txt`), cifre e punteggiatura. `Modello.genera`
la passa al server come `grammar` e llama.cpp la applica token per token. Esiste
solo per l'italiano ed è spenta (`gabbia=False` dove `app.py` crea il
`Narratore`): sui record poveri il vocabolario chiuso costringe il modello alla
parola ammessa più vicina, e l'italiano ne esce rotto.

### Misurare sulla board

Dalla cartella `~/amelie` della board, con il servizio del modello acceso:

```bash
venv/bin/python scripts/bench_llm.py                    # un'etichetta, due giri
venv/bin/python scripts/bench_llm.py --tutti            # quattro casi diversi
venv/bin/python scripts/bench_llm.py --prompt-generico  # il prompt per un modello non affinato
```

Lo script aspetta fino a 30 s che il server risponda; poi, per ogni caso, stampa
livello, sicurezza e lunghezza del prompt, e per ogni giro la durata, l'esito
della verifica e l'inizio del testo (`--giri N` cambia il numero di giri). Il
secondo giro mostra la cache del prefisso. Usa la stessa forma di prompt del
dispositivo, `prompt_addestrato`, e lavora in italiano.

## La carta dei vini

Con `--carta FILE.csv` il dispositivo può raccontare da un file scritto a mano
(`src/amelie/carta.py`); il servizio di sistema punta a
`/home/arduino/amelie/vini.csv`, cioè al file `vini.csv` del repository: 526 voci,
solo in italiano, quindi in inglese il racconto viene dall'archivio.

```csv
titolo,descrizione,titolo_en,descrizione_en
"Nome della denominazione","Il racconto in italiano…","Name","The story in English…"
```

`titolo` e `descrizione` sono obbligatori; ogni colonna `descrizione_xx` aggiunge
una lingua. Si cerca solo il titolo, e ogni sua parola deve essere stata letta
sul vetro, tranne le sigle di denominazione e «annata» (`TACITE`) e le parole
che la carta dà per scontate (le regole sono in
[06-riconoscimento.md](06-riconoscimento.md)). Non c'è cascata: una bottiglia che
la carta non ha conta come lettura fallita, e il dispositivo chiede di girare
l'etichetta. Il racconto è l'apertura con il titolo (`apertura.tipologia_nota`)
seguita dalla descrizione com'è; se la descrizione manca nella lingua scelta si
racconta dai fatti dell'archivio, che si cercano comunque subito dopo il titolo.
Un file assente o senza voci utilizzabili non ferma l'avvio: il modo «carta»
semplicemente non compare.

## La voce

| Lingua | Voce Piper (`speech.VOCI`) | Licenza |
|---|---|---|
| italiano | `it_IT-serena-medium` | CC BY 4.0 |
| inglese | `en_US-ljspeech-medium` | dataset LJ Speech, pubblico dominio |

Piper è GPL-3.0; le due voci sono addestrate da zero su dati che ne permettono
anche l'uso commerciale (attribuzioni in [08-attribuzioni.md](08-attribuzioni.md)).
`scripts/install.sh` scarica i file `.onnx` e `.onnx.json` di ogni voce in
`models/` e ne controlla le somme SHA-256; `Voce._percorso_modello` cerca ogni
voce in `~/.local/share/piper/voices`, in `~/amelie/models` e in
`/usr/share/piper-voices`, in quest'ordine. All'avvio `Amelie._scalda_voci` apre
l'uscita audio, carica tutte e due le voci e pre-sintetizza l'annuncio di
lingua. Una lingua senza voce mostra il testo, che scorre al ritmo di una lettura
(`_scorri_senza_voce`), e lo schermo lo dice (`schermo.voce_assente`).

### Dal testo all'altoparlante

```
frase ──► per_la_voce()              sigle sciolte, nomi stranieri, «16-18» → «16 e 18» (in inglese «16 to 18»)
      ──► Piper (ONNX)               PCM 16 bit, 22.050 Hz, mono
      ──► ~/.cache/amelie/voce/*.raw cache per voce e frase
      ──► Riproduttore               buffer in memoria, posizione in byte
      ──► Uscita                     flusso sempre aperto, volume applicato qui
      ──► aplay -D plughw:0,3        ALSA converte la frequenza per l'HDMI
      ──► MultiMedia4 ─► SEC_MI2S_RX ─► I2S ─► ANX7625 ─► HDMI ─► schermo
```

- **La pronuncia** (`speech.PRONUNCIA`, `PRONUNCIA_EN`) riscrive il testo prima
  della sintesi: le sigle di denominazione diventano la dicitura per esteso nella
  lingua giusta, la voce italiana riceve una grafia fonetica dei nomi stranieri
  più comuni del vino (Chardonnay, Château, Gewürztraminer…), le virgolette non
  si pronunciano. La cache è indicizzata sulla voce e sul testo riscritto.
- **L'uscita** (`speech.Uscita`) apre `aplay`, il riproduttore da riga di comando
  di ALSA, all'avvio e non lo chiude più: quando non c'è niente da dire versa
  silenzio. Il processore audio della board impiega circa due secondi a rendere il
  suono dopo l'apertura del flusso, e tenerlo aperto evita di pagare quel ritardo
  a ogni frase. I dati si scrivono a passo d'orologio, a pezzi di 80 ms, così la
  posizione dichiarata resta vicina a ciò che si sente.
- **Il dispositivo ALSA** è `plughw:0,3` (opzione `--audio`), cioè il
  dispositivo 3 della scheda audio 0: il suono parte dal flusso MultiMedia4,
  passa dalla porta SEC_MI2S_RX al bus audio digitale I2S e dal chip ANX7625
  all'HDMI. `plughw` e non `hw`, perché l'HDMI accetta solo frequenze fra 32 e
  48 kHz e Piper produce 22.050 Hz, e `plughw` aggiunge la conversione. La
  rotta del mixer (`SEC_MI2S_RX Audio Mixer MultiMedia4`) la apre a ogni avvio
  `scripts/systemd/amelie-audio-rotta.sh`, e `amelie-audio-guard.sh` si
  assicura che alla fine dell'avvio la scheda audio esista. Il suono esce dagli
  altoparlanti dello schermo o dalla sua uscita cuffie.
- **Il volume** non ha un controllo hardware su questa catena: si applica al PCM
  in `Uscita._versa`, a tutto ciò che esce. Va da 0 a 100 e diventa guadagno col
  quadrato (`guadagno_di`: metà corsa è circa −12 dB, mai oltre 1). Il cursore
  dello schermo lo sposta a passi di 5 (`PASSO_CURSORE` in `index.html`) con
  `POST /volume/{valore}`; si salva in `var/volume` (al primo avvio vale
  `--volume`, 100 se non lo si dà), e un tocco di calice sintetizzato
  (`Voce.colpetto`) fa sentire il livello scelto. A 0 il racconto continua sullo
  schermo.

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
| avanti / indietro | `avanti`, `indietro` | `salta(±SALTO_S)`, 5 secondi; in avanti non oltre ciò che è già sintetizzato |
| da capo | `ricomincia` | dall'inizio |
| annulla | `POST /annulla` | chiude il racconto e torna all'invito |

Togliere la bottiglia per versare non interrompe il racconto. Lo stato arriva
alla pagina sul flusso `GET /eventi` come messaggio `riproduzione`
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
- Il registro è impersonale quando si descrive il vino («Si serve fra…», in
  inglese «Best served between…») e dà del lei quando ci si rivolge all'ospite.
- Se una forma nuova introduce le uve con un giro di frase che la verifica non
  conosce, va aggiunto a `_CONTESTO_VITIGNI` in `narrator.py`.

**`data/lessico/vocabolari.json`**: i vocabolari controllati dei dataset
(`tipo`, `colore`, `categoria_ue`, `elaborazione`, `corpo`, `acidita`,
`abbinamento`), le cui **chiavi sono i valori esatti delle fonti** e non si
cambiano: sono chiavi di collegamento. In più `regione`, con i nomi delle regioni
italiane come li scrive l'archivio («Toscana», che in inglese diventa
«Tuscany»). Ogni termine ha, per lingua, un'`etichetta` per lo schermo e,
facoltativa, una forma `narrativa` per dentro una frase («bella acidità» invece
di «alta»).

**`data/lessico/organolettico.json`**: gli atomi italiano → inglese delle
citazioni, in `termini` (colori, riflessi, intensità, olfatto, materia, gusto,
effervescenza, menzioni, idiomi), più `per_ambito` per le parole che cambiano
senso fra colore, odore e sapore («vivace», «rosa») e `nomi` per i sostantivi.
Un atomo mancante fa cadere il frammento che lo contiene: aggiungerlo allunga le
citazioni inglesi senza toccare il codice.

**`data/vitigni.json`**: le 131 schede dei vitigni, scritte a mano
(`descrizione`, `note_sensoriali`, `abbinamenti` con le versioni `_en`,
`temperatura_c`, `colore_bacca`) e gli `alias` con cui i dataset chiamano lo
stesso vitigno, dichiarati uno per uno: un aggancio per somiglianza di nome
legherebbe vitigni diversi. Si riapplicano al database esistente con
`python3 data/build_db.py --solo-vitigni`.

**La pronuncia**: una sigla letta male o un nome storpiato si corregge con una
coppia espressione regolare → sostituzione in `PRONUNCIA` o `PRONUNCIA_EN`
(`src/amelie/speech.py`). La cache è indicizzata sul testo riscritto, quindi la
correzione vale subito.

### Aggiungere una lingua

1. La sigla in `lingue` di `vocabolari.json` e la voce per ogni termine.
2. Ogni chiave di `frasi.json` nella nuova lingua, con gli stessi segnaposto.
3. Una voce Piper in `speech.VOCI` e il suo ritmo in `CARATTERI_AL_SECONDO`;
   senza, il racconto si legge soltanto.
4. Nel codice, i punti che conoscono solo italiano e inglese: le citazioni del
   disciplinare (`organolettico.json` rende solo in inglese), le tabelle di
   pronuncia (`_COMPILATE`), la congiunzione di `elenca_in_lingua`, l'articolo di
   `_con_articolo`, le forme riconosciute da `_forma_della_citazione`, le
   espressioni regolari della verifica (`_CONTESTO_VITIGNI` e gli altri
   `_CONTESTO_*` in `narrator.py`), le etichette del blocco dei fatti
   (`_ETICHETTE_BLOCCO`, `Fatti._INTESTAZIONE_DISCIPLINARE` e
   `Fatti._VOCI_DISCIPLINARE` in `matcher.py`) e, per il modello,
   `ISTRUZIONE_ADDESTRATA`.
5. Nella carta, le colonne `titolo_xx` e `descrizione_xx`.
6. Facoltativo: una bandiera disegnata in `src/amelie/ui/static/index.html`;
   senza, il selettore mostra la sigla della lingua.

### Dopo ogni modifica

```bash
python3 -m pytest tests/test_lessico.py tests/test_narrator.py tests/test_organolettico.py
```

I test del lessico falliscono se una frase manca in una lingua, se i segnaposto
non coincidono o se un valore dei dataset non ha traduzione; quelli del narratore
controllano, fra l'altro, che i testi composti superino la verifica. Poi si porta
tutto sulla board, in uno di due modi.

- Con `git pull` e `bash scripts/install.sh` sulla board: il database si
  ricostruisce da solo quando lessico, schede o sorgenti sono cambiati, racconti
  pronti compresi.
- Con `scripts/rilascio.sh` dal PC: copia codice, interfaccia, lessico, schede,
  database e test, fa girare i test sulla board e riavvia l'applicazione e il
  chiosco; alla prima copia tiene sulla board una copia di sicurezza del
  database. Il database è quello del PC, quindi prima si rigenerano i racconti
  pronti (sezione sotto).

## Rigenerare i racconti pronti

La tabella `racconto` del database contiene un racconto già composto per ogni
tipologia, denominazione e vitigno descritto che abbia qualcosa da dire, in ogni
lingua: 9.876 righe nel database costruito. Il testo è il **corpo senza
apertura** (`narrator.corpo_neutro`): l'apertura dipende dalla sicurezza del
riconoscimento, che si conosce solo al momento, e la compone il `Narratore`
quando lo usa. Questi testi servono nel modo «generativa», come secondo gradino
dopo il modello; il modo «archivio» compone sempre dal vivo e risente subito di
ogni modifica al lessico.

```bash
python3 scripts/genera_corpus.py                  # scrive ciò che manca
python3 scripts/genera_corpus.py --rigenera       # riscrive anche ciò che c'è
python3 scripts/genera_corpus.py --lingua en      # una lingua sola (ripetibile)
python3 scripts/genera_corpus.py --solo vitigno   # un ambito solo (ripetibile)
python3 scripts/genera_corpus.py --limite 50      # i primi N per ambito
```

Lo script scrive in `data/amelie.db` (o nel file dato con `--db`), che
l'applicazione apre in sola lettura; `data/build_db.py` lo lancia da sé alla fine
di ogni costruzione del database, salvo `--senza-racconti`, quindi serve a mano
solo per provare una modifica al lessico senza ricostruire tutto. Ordina
denominazioni e tipologie per quanti vini vi fanno capo, così un lavoro
interrotto lascia pronto ciò che si incontra più spesso, e salta i record senza
niente da dire: una riga vuota impedirebbe il ripiego sul gradino successivo. La
colonna `modello` dice la provenienza di ogni riga; le righe composte hanno
`template`, e `--rigenera` riscrive solo quelle. Va rilanciato con `--rigenera`
dopo ogni modifica a `frasi.json`, ai vocabolari, agli atomi organolettici o alle
schede dei vitigni.
