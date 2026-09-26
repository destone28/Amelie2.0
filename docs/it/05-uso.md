# Usare Amelie

Amelie racconta il vino che le appoggi davanti: legge l'etichetta con la
camera, riconosce la bottiglia e ne dice la storia sullo schermo e a voce, in
italiano o in inglese, senza nessuna connessione.

Questa guida descrive che cosa vede e che cosa può fare chi siede al tavolo,
che cosa trova chi gestisce il dispositivo nelle impostazioni, e dove guardare
quando qualcosa non va. Le frasi fra caporali sono le scritte esatte dello
schermo (`data/lessico/frasi.json`). Come si arriva dall'etichetta al vino è in
[06-riconoscimento.md](06-riconoscimento.md).

## La schermata d'attesa

Quando il dispositivo è pronto mostra il calice, il nome, la frase «Ogni
bottiglia ha una storia.» e tre passi, ciascuno con la sua icona:

| | italiano | inglese |
|---|---|---|
| 1 | **Scegli** una bottiglia | **Choose** a bottle |
| 2 | **Posa** la bottiglia su Amelie | **Place** the bottle on Amelie |
| 3 | **Ascolta** la sua storia | **Listen** to its story |

I tre passi sono un'insegna, come su un cartello, e per questo danno del tu;
tutte le altre scritte si rivolgono all'ospite con il «Lei».

In alto a destra ci sono le bandiere delle lingue, in alto a sinistra
l'altoparlante del volume. Sono gli unici punti che rispondono al tocco,
insieme a un angolo nascosto che apre le impostazioni. Il resto dello schermo è
inerte di proposito: su un tavolo un tocco accidentale è la norma. Ogni
pulsante agisce quando alzi il dito, e solo se il dito è ancora sopra: un tocco
partito per sbaglio si annulla scivolando via.

All'accensione compare prima il marchio da solo, e resta finché le voci non
sono caricate: così la prima bottiglia trova la voce già pronta.

## Una bottiglia, dall'inizio alla fine

### Posarla

Che una bottiglia ci sia lo decide il sensore di distanza, e solo lui; la
camera serve a sapere dove sta l'etichetta. Appena la posi lo schermo dice
«Fammi guardare…», poi «Sto leggendo l'etichetta…» mentre la camera scatta e
l'OCR legge, e «Un attimo…» mentre cerca il vino. Intanto un'animazione mostra
una bottiglia che versa in un calice.

Posa la bottiglia con l'etichetta verso la camera: un'etichetta di lato si
legge male, o non si legge.

### Il racconto

La schermata del racconto mostra:

- in alto il **titolo**: il nome del vino, oppure la tipologia, la
  denominazione o il vitigno quando il riconoscimento si ferma lì; sotto,
  cantina e annata, se le conosce;
- il **testo** intero, con accesa la frase che la voce sta dicendo; il testo
  scorre da solo per tenerla in vista;
- una **barra** che si riempie fino alla fine del racconto;
- i **comandi**, e la croce di Annulla in basso a sinistra.

La prima frase dice quanto il dispositivo è sicuro: «Questo è il …» quando il
riconoscimento è certo, «Direi il …» o «Dovrebbe essere il …» quando è una
supposizione. Quando l'etichetta si legge ma in archivio non c'è niente che si
possa nominare, il dispositivo dice soltanto ciò che è scritto sulla bottiglia
(per esempio che è uno spumante rosato brut) e chiude con «Questa bottiglia non
è nel mio archivio; la descrizione è stata generata in autonomia sulla base dei
dati e del catalogo a mia disposizione.»

Se per la lingua scelta non c'è una voce, il racconto si legge e basta: il
testo scorre da solo al ritmo di una lettura, comandi e barra spariscono, e in
basso compare «In questa lingua il racconto si legge, non si ascolta.»

### I comandi del racconto

| Comando | Dove | Che cosa fa |
|---|---|---|
| Da capo | primo cerchio | ricomincia il racconto dall'inizio |
| Indietro | secondo cerchio | torna indietro di 5 secondi |
| Pausa / riprendi | cerchio grande | ferma la voce; toccato di nuovo, riparte da lì |
| Avanti | quarto cerchio | salta avanti di 5 secondi |
| Annulla | croce in basso a sinistra | chiude il racconto e torna alla schermata d'attesa |

Finito il racconto, il testo resta a schermo un momento e poi torna la
schermata d'attesa. In quel momento i cerchi non hanno più niente da comandare,
e al primo tocco si spengono.

**Annulla** serve a chi ha già versato e vuole il silenzio senza sollevare di
nuovo la bottiglia. Funziona anche quando il racconto non è ancora cominciato
(per esempio mentre il modello sta scrivendo). Dopo Annulla la lingua resta
quella scelta, e la bottiglia rimasta sul piatto non si rilegge: il
dispositivo aspetta che venga tolta.

Una pausa non occupa il dispositivo per sempre: oltre un tetto
(`TETTO_RACCONTO_S` in `src/amelie/app.py`) il racconto si ferma, il testo
resta a schermo con i comandi spenti, e se ne esce con Annulla.

### Togliere la bottiglia

| Quando la togli | Che cosa succede |
|---|---|
| durante «Fammi guardare…», la lettura o la richiesta di girare l'etichetta | il giro si interrompe e torna la schermata d'attesa |
| durante il racconto | il racconto continua fino in fondo |
| sulla schermata finale del racconto | torna subito la schermata d'attesa |
| dopo il ritorno all'attesa | niente: la prossima bottiglia posata comincia un giro nuovo |

Il racconto continua perché chi solleva la bottiglia per versare non ha chiesto
silenzio: un racconto che muore a metà frase si nota più di uno che finisce.
Per zittire il dispositivo c'è Annulla.

### Rimettere la stessa bottiglia

Se la rimetti mentre il racconto è in corso, il dispositivo la guarda subito,
senza fermare la voce. Se la foto ritrova l'etichetta di prima, o le parole
lette sono le stesse, il racconto va avanti e alla fine la bottiglia non si
rilegge. Due etichette dello stesso vino, fronte e retro, contano come la
stessa bottiglia, perché raccontano la stessa storia. Se dalla nuova lettura
non esce nessuna parola il dispositivo non può decidere: lascia finire il
racconto e rilegge la bottiglia dopo.

Se la rimetti quando lo schermo è già tornato all'attesa, è un giro nuovo e il
racconto ricomincia da capo. È anche il modo di riascoltare una bottiglia.

### Cambiarla con un'altra

Una bottiglia diversa posata durante il racconto, o sulla schermata finale, si
legge subito mentre la voce parla ancora della precedente. Appena le parole
lette dicono che è un altro vino, la voce tace e parte il racconto della
nuova, già letta: non serve un'altra foto. La decisione la prende il testo e
non la foto: la foto sa dire in fretta che una bottiglia è la stessa, ma una
bottiglia rimessa girata ritrova pochi punti dell'etichetta di prima, e da lì
non si può concludere che sia un'altra.

### La bottiglia che non si riconosce

Due casi portano alla stessa schermata: l'OCR non trova nessuna parola, oppure
trova parole ma nessun vino (nel modo «Carta dei vini»: nessuna voce della
carta). Lo schermo mostra «Provi a girare l'etichetta verso di me?», l'anello
diventa rosso, e dopo qualche istante il dispositivo riprova con una foto
nuova: è il momento di girare la bottiglia.

Dopo tre letture fallite (`TENTATIVI_MAX`) il dispositivo smette:

- con «Aggiungi correzioni» acceso e almeno una parola identificante letta,
  compare «Non ho riconosciuto questa bottiglia.» con il pulsante «Mi aiuti a
  riconoscerla», e la schermata resta abbastanza a lungo da arrivarci
  (`CONCLUSO_CON_CORREZIONE_S`);
- altrimenti torna subito la schermata d'attesa.

In tutti e due i casi la bottiglia rimasta sul piatto non si rilegge: per
riprovare, sollevala e rimettila. Senza questo tetto un oggetto qualunque
lasciato sul piatto (un bicchiere, una bottiglia senza etichetta) terrebbe
accesi camera, anello e OCR per tutta la sera. Con le correzioni accese «Mi
aiuti a riconoscerla» compare anche fra un tentativo e l'altro, sotto la
richiesta di girare l'etichetta.

### L'anello di luce

| Momento | Anello |
|---|---|
| schermata d'attesa, lettura, ricerca del vino | ambra |
| scatto a camera ferma | bianco, solo per la durata dello scatto |
| bottiglia appena posata, racconto, schermata finale (anche «Non ho riconosciuto questa bottiglia.») | verde |
| «Provi a girare l'etichetta verso di me?», guasto | rosso |
| Debug camera accesa | bianco |

Di norma la camera è già in moto quando la bottiglia arriva, e il fotogramma si
prende dal flusso senza accendere il bianco.

## Le lingue

Le bandiere stanno in alto a destra in ogni schermata, racconto compreso.
Quella della lingua in uso è piena, con un anello d'oro; le altre sono
smorzate.

- **Tocchi l'altra bandiera**: le scritte cambiano subito e il dispositivo lo
  conferma a voce con «Lingua italiana. Da adesso racconto i vini in
  italiano.» oppure «English language. From now on I will describe the wines
  in English.» Fuori dalla schermata del racconto la frase compare anche
  scritta in basso, come un sottotitolo. Se un racconto è in corso, si ferma
  e, finito l'annuncio, ricomincia da capo nella lingua nuova: stesso vino,
  senza rimettere la bottiglia.
- **Tocchi la bandiera già attiva**: non cambia niente, ma l'annuncio si fa lo
  stesso. È il modo più rapido di provare voce e casse senza una bottiglia.
- **Tocchi mentre un annuncio sta parlando**: l'annuncio si interrompe e parte
  quello della lingua appena scelta.

La lingua di partenza è l'italiano (`Configurazione.lingua` in
`src/amelie/app.py`; non c'è un'opzione da riga di comando). Il dispositivo ci
torna da solo, senza annunciarlo, quando la bottiglia viene tolta dal piatto:
chi arriva dopo trova la lingua di casa. Finché la bottiglia resta sul piatto la
lingua scelta resta: a racconto finito, dopo Annulla, dopo un guasto, perché al
tavolo ci sono ancora le stesse persone.

Toccare una bandiera quando il racconto è appena finito allunga di qualche
secondo la schermata del racconto (`LINGUA_A_RACCONTO_FINITO_S`), così
l'annuncio e il racconto nella lingua nuova hanno il tempo di arrivare.

Nomi di vini, cantine e annate non si traducono: sono ciò che è stampato sulla
bottiglia. Una carta dei vini o una correzione senza testo nella lingua scelta
lasciano parlare l'archivio (vedi le sezioni relative).

## Il volume

Tocca l'altoparlante in alto a sinistra: si apre un cursore. Trascina il
pomello, o tocca il punto del binario che vuoi. Il cursore si richiude da solo
dopo qualche istante senza tocchi, e quando cambia la schermata.

- **L'icona dice il livello anche a comando chiuso**: due onde da metà corsa in
  su, una sotto metà, nessuna e un taglio a zero. A zero il dispositivo
  racconta lo stesso, in silenzio.
- **A mano ferma** il dispositivo fa sentire un colpetto su un calice al
  livello nuovo, così lo regoli senza appoggiare una bottiglia. Mentre racconta
  o annuncia una lingua il colpetto non c'è: il livello si sente già.
- **La scala va da 0 a 100 e il guadagno è il quadrato del valore**: metà corsa
  vale circa −12 dB, che all'orecchio è «metà volume». 100 è il massimo che il
  segnale digitale porta senza distorcere, e oltre non si va.
- **Si ricorda** fra un'accensione e l'altra (`var/volume`). L'opzione
  `--volume` del servizio vale solo quando non c'è un valore salvato.

La catena audio non ha un controllo di volume hardware: il suono esce dalla
board via HDMI e arriva alle casse attraverso lo schermo. Quello che si regola
è il segnale, un istante prima dell'uscita. Se il servizio parte senza voce
(`--senza-voce`) il comando non compare.

## Le impostazioni

### Come si aprono

Tieni il dito fermo **sull'angolo in basso a destra** dello schermo per **tre
secondi**. L'area sensibile è un piccolo quadrato nell'angolo; se il dito si
sposta oltre una piccola tolleranza (`ANGOLO_SCARTO` in `index.html`) il gesto
si annulla e va ripetuto. Funziona dalle schermate del ciclo (attesa, lettura,
racconto, avvisi). L'ingresso è nascosto di proposito: raggiungibile con un
tocco, lo aprirebbe per sbaglio chi appoggia una bottiglia.

Il pannello copre lo schermo, l'elenco scorre col dito, e si chiude con la
croce in basso a sinistra, nello stesso posto di Annulla. Non ferma il
dispositivo: una bottiglia posata intanto viene letta e raccontata sotto. Le
righe, dall'alto:

### Come racconta

| Modo | Da dove viene il testo | Quando compare |
|---|---|---|
| «Dall'archivio» (predefinito) | composto dai dati dell'archivio e dal disciplinare, senza modello: non inventa ed è immediato | sempre |
| «Scritto sul momento» | gli stessi dati, ma il testo lo scrive il modello linguistico per quella bottiglia; sperimentale, può sbagliare e fa aspettare | solo se il servizio parte con `--con-modello` |
| «Carta dei vini» | le descrizioni scritte a mano nel file della carta, e solo per i vini che contiene | solo se una carta è caricata con `--carta` |

La differenza fra i modi non è di stile, è la fonte di quello che il
dispositivo dice. Il modo scelto ha il segno di spunta, vale dalla bottiglia
successiva (cambiarlo a metà lettura interromperebbe chi ascolta) e si ricorda
in `var/modo`. Un modo salvato che il dispositivo non può più servire (la carta
che manca, il modello non abilitato) torna all'archivio.

Nel modo «Scritto sul momento»:

- scegliere il modo accende `amelie-llm.service`, sceglierne un altro lo
  spegne: fermo a vuoto il modello occupa un core che serve all'OCR;
- mentre il modello scrive, al posto del testo compare «Sto scrivendo la
  descrizione…» con un piccolo calice;
- quello che il modello scrive passa da una verifica; se inventa due volte di
  fila si usa il testo già pronto per quel vino, se c'è, e altrimenti la
  composizione dai fatti. Si ripiega allo stesso modo se il modello non
  risponde;
- quando si sa soltanto ciò che è scritto sull'etichetta il modello non scrive
  mai: si racconta la composizione.

Le correzioni a mano hanno la precedenza in tutti e tre i modi.

### Aggiungi correzioni

Spento finché non lo accendi, e resta com'è anche dopo un riavvio
(`var/correzioni_attive`). Acceso, su ogni racconto compare sotto il titolo
«Correggi la bottiglia», o «Modifica la correzione» su una bottiglia già
corretta, e le bottiglie non riconosciute offrono «Mi aiuti a riconoscerla»;
la schermata finale resta più a lungo, per lasciare il tempo di arrivare al
pulsante. Spento, nessun ospite vede un pulsante per correggere, ma le
correzioni già salvate si riconoscono comunque. Cambia subito anche sul
racconto a schermo; spegnendolo con l'editor aperto, l'editor si chiude senza
salvare. Oltre all'interruttore non c'è un PIN.

### Debug camera

Mostra a tutto schermo che cosa vede la camera e che cosa riesce a leggere,
per mettere a punto l'inquadratura:

- sul video, il **riquadro** che va all'OCR (fuori da lì non si legge niente),
  con le due mezzerie per centrare l'etichetta e la scritta `nitidezza N
  (soglia S)`: verde sopra la soglia, rosso sotto;
- di lato, «Cosa legge» con le righe trovate (le prime dieci; «nessuna riga di
  testo» se non ce ne sono) e «Cosa trova» con livello, sicurezza, vino e
  candidati, più nitidezza e posa. Questa colonna interroga l'archivio, non la
  carta né le correzioni.

Accenderla **ferma il ciclo**: la camera la usa un processo alla volta, quindi
niente racconti né letture finché è accesa. L'anello va a bianco e la posa si
cerca una volta, così inquadri con la luce che ci sarà davvero. Dallo schermo
si esce solo dal pulsante in basso «torna al racconto», perché la debug camera
copre il pannello; uscendo, una bottiglia rimasta sul piatto si legge subito, e
questa è la prova che l'inquadratura funziona. Non si ricorda fra un avvio e
l'altro, e la riga non compare se la camera non c'è.

Per guardare da un PC su uno schermo grande c'è anche `scripts/mirino.py`, con
la stessa logica, da lanciare a servizio fermo.

### Batteria ricaricata

Il power bank non comunica niente: il dispositivo stima quanta energia ha
speso da quanto è acceso e da quanto lavora la CPU, su una capacità utile
dichiarata in `CAPACITA_WH` (`src/amelie/batteria.py`). La stima si vede solo
qui, come un'icona a quattro tacche; senza un numero, perché è una stima.
L'ultima tacca sparisce prima dello zero, dove il power bank può spegnersi
senza avvisare; a zero tacche il contorno diventa rosso.

Tocca la riga dopo aver ricaricato: la stima riparte da piena. All'accensione
il dispositivo lo fa da solo se è rimasto spento abbastanza a lungo da
supporre una ricarica notturna (`RICARICATA_DOPO_S`); dopo un riavvio breve la
stima riprende da dov'era.

### Ripristina il funzionamento

Rimette in moto camera, lettura e voce senza spegnere, quando «Qualcosa non ha
funzionato. Riprovo fra un istante.» si ripete. La riga mostra che il lavoro è
in corso, poi un segno di spunta, e il pannello si chiude. Che cosa fa è
descritto in [Quando qualcosa non va](#quando-qualcosa-non-va).

### Stato tecnico

Apre sopra il pannello il contenuto di `/stato`, da leggere senza tastiera;
«chiudi» riporta alle impostazioni. I campi più utili:

| Campo | Che cosa dice |
|---|---|
| `stato` | lo stato della macchina a stati (`attesa`, `racconto`…) |
| `mcu`, `protocollo`, `moduli` | se il microcontrollore risponde, con quale protocollo, e se vede anello e sensore di distanza |
| `camera`, `posa` | se la camera c'è, e l'esposizione in uso |
| `bottiglia`, `differenza`, `soglia` | se il sensore vede una bottiglia, e quanto il piatto differisce da quello vuoto rispetto alla soglia |
| `voce`, `volume`, `pronta` | se la voce è caricata, il volume, se il dispositivo ha finito di prepararsi |
| `modo`, `racconti_generati`, `carta`, `voci_in_carta` | il modo di racconto, se il testo lo scrive il modello, il file della carta e quante voci contiene |
| `ultimo_livello`, `sicurezza` | l'esito dell'ultimo riconoscimento |
| `transizioni` | gli ultimi passaggi di stato |

## Le correzioni

Una correzione insegna al dispositivo una bottiglia: che cosa dire di lei, o a
quale vino conosciuto corrisponde. Richiede «Aggiungi correzioni» acceso.

### Aprire l'editor

- **Da un racconto**, con «Correggi la bottiglia» (o «Modifica la correzione»
  su una bottiglia già corretta). La voce si ferma. Su una bottiglia già
  corretta l'editor riapre la correzione com'è. Altrimenti, se il dispositivo
  ha riconosciuto un vino, una tipologia o una denominazione dell'archivio, o
  una voce della carta, l'editor si apre già collegato a quello, col suo nome
  nel titolo; se no, col titolo vuoto.
- **Da una bottiglia non riconosciuta**, con «Mi aiuti a riconoscerla»:
  l'editor si apre col titolo vuoto. Il pulsante c'è solo se dall'etichetta si
  è letta almeno una parola identificante, perché la volta dopo la bottiglia si
  ritrova dalle parole e dalla foto insieme, e senza parole non tornerebbe mai.

La foto e la lettura si fissano all'apertura: se nel frattempo qualcuno cambia
bottiglia, la correzione resta attaccata a quella giusta. Mentre l'editor è
aperto il dispositivo non guarda il piatto, e un editor dimenticato si chiude
da solo (`CORREZIONE_TETTO_S`).

### L'editor

Copre lo schermo: la foto appena scattata, il campo **titolo**, il campo
**descrizione** e una tastiera italiana disegnata dalla pagina, con le
accentate sui tasti, l'apostrofo accanto alla virgola e «?123» per numeri e
simboli (€, %, °, «»). La maiuscola si accende da sola a inizio campo e dopo
un punto; un doppio tocco la blocca; il tasto che cancella, tenuto premuto,
continua a cancellare. Invio nel titolo passa alla descrizione.

**Il titolo cerca.** Dalla seconda lettera, al posto della descrizione
compaiono le bottiglie che il dispositivo conosce il cui nome contiene le
parole scritte (l'ultima come inizio di parola): prima quelle già corrette,
poi la carta dei vini, poi l'archivio, cinque per volta. Sotto ognuna c'è la
provenienza: «corretta a mano», «carta dei vini», «archivio · vino»,
«archivio · tipologia», «archivio · denominazione». Nell'archivio vengono
prima i nomi che cominciano come hai scritto, poi i più corti: la
denominazione prima dei vini dei singoli produttori. L'ultima casella è
«Nessuna di queste»: con sotto «altre N» passa alle successive, con sotto
«scrivo la descrizione» torna al campo descrizione.

- **Scegli un vino della carta o dell'archivio**: la bottiglia gli viene
  **collegata**. Sopra i campi compare «Collegata a: …» con una crocetta per
  togliere il collegamento, e il campo descrizione dice «Descrizione
  (facoltativa: vuota, racconto la sua scheda)». Vuota, la bottiglia si
  racconta con la scheda del vino collegato: dall'archivio secondo il modo di
  racconto, dalla carta con la sua descrizione. Scritta, parla la tua
  descrizione.
- **Scegli una bottiglia già corretta**: la foto di adesso si aggiunge a quella
  correzione invece di crearne un doppione.
- **Riscrivi il titolo dopo una scelta**: il collegamento si toglie da sé.

Se la bottiglia somiglia a una già corretta senza essere stata riconosciuta,
all'apertura l'editor chiede «È una di queste?» con le foto delle candidate:
toccarne una vuol dire «è lei».

Senza collegamento la descrizione è obbligatoria: «Salva» scrive «Scriva un
titolo» o «Scriva una descrizione» ed evidenzia il campo che manca. Il
dispositivo racconta
una correzione aprendo con una frase che la nomina («Questo è …») e poi
leggendo la descrizione così com'è: non serve ripetere il nome in apertura.

### Salvare, e l'altra lingua

«Salva» mostra «Salvata. La riconoscerò.», l'editor si chiude e la bottiglia
si racconta subito con il testo nuovo: è la prova che la correzione funziona.
Il testo vale per la lingua in cui lo schermo era all'apertura dell'editor.

Se hai scritto una descrizione, prima di chiudersi l'editor chiede «Vuole
scrivere la descrizione anche in inglese?» (o in italiano, se l'hai scritta in
inglese), e il racconto aspetta la risposta. «Sì, la scrivo» riapre l'editor
sulla stessa correzione, intitolato «Descrizione in inglese» (o «in
italiano»), col titolo già scritto e la descrizione che c'era, se c'era; non
aggiunge un'altra foto.
«No, grazie», o la croce, racconta la bottiglia com'è. Senza descrizione (una
bottiglia solo collegata) la domanda non c'è: la scheda del vino collegato
parla già tutte le lingue.

Se chiudi l'editor con la croce senza aver salvato niente, un racconto
interrotto si dà per finito; da una bottiglia non riconosciuta il dispositivo
riprende da dove si era fermato.

### Come si riconosce la volta dopo

Una correzione si cerca prima dell'archivio, del modello e della carta, in
qualunque modo di racconto. Una bottiglia è quella corretta quando:

- la maggior parte delle parole identificanti salvate, e almeno due, si
  rileggono, e i punti dell'immagine ritrovati sull'etichetta lo confermano;
  oppure
- l'immagine da sola somiglia moltissimo, anche se stavolta l'OCR ha letto
  male le parole.

Le parole identificanti hanno almeno quattro lettere e non sono di quelle che
stanno su migliaia di etichette («rosso», «doc», «brut»). L'immagine si
confronta solo nella zona dell'etichetta, così lo sfondo della sala, sempre
uguale, non fa somigliare due bottiglie diverse. Le soglie sono in `Regola`
(`src/amelie/correzioni.py`), il perché in
[06-riconoscimento.md](06-riconoscimento.md).

Ogni salvataggio aggiunge la foto di adesso come vista in più: se una bottiglia
corretta non viene riconosciuta, girata o con un'altra luce, riaprila e
sceglila fra «È una di queste?» o fra le proposte «corretta a mano».

Nella lingua in cui la correzione non ha una descrizione la bottiglia parla con
la scheda del vino collegato; senza collegamento si racconta come se la
correzione non ci fosse. Il pulsante resta «Modifica la correzione», per
aggiungere il testo mancante.

### Dove stanno, e come si cancellano

Ogni correzione è una cartella in `var/correzioni/<id>/` (sulla board
`/home/arduino/amelie/var/correzioni/`), dove `<id>` è data e ora di creazione:

- `correzione.json`: i testi per lingua (`titolo`, `descrizione`), il
  collegamento (`riferimento`) e le viste (foto, righe lette, parole, zona
  dell'etichetta);
- `vista-1.jpg`, `vista-2.jpg`…: le foto.

Dallo schermo una correzione si modifica ma non si cancella. Per toglierla:

```bash
rm -r ~/amelie/var/correzioni/<id>
sudo systemctl restart amelie.service
```

Le correzioni si caricano all'avvio del servizio: anche un ritocco a mano al
JSON vale dal riavvio. Non stanno in git: per conservarle, copia la cartella.

## La carta dei vini

La carta è un file scritto a mano che fa raccontare al dispositivo i vini del
locale con parole proprie. Si sceglie dalle impostazioni come «Carta dei
vini».

### Il formato

Un CSV in UTF-8, separato da virgole, con una riga d'intestazione. Racchiudi
fra virgolette i campi che contengono virgole.

| Colonna | | Contenuto |
|---|---|---|
| `titolo` | obbligatoria | il nome del vino, come si dice e come compare a schermo |
| `descrizione` | obbligatoria | il racconto in italiano, letto così com'è |
| `descrizione_en` | facoltativa | il racconto in inglese; la sua presenza aggiunge l'inglese alla carta |
| `titolo_en` | facoltativa | il titolo in inglese; se manca vale quello italiano |

Una riga senza titolo o senza descrizione si salta. Il dispositivo apre con una
frase che nomina il titolo (per esempio «Questo è un Barolo DOCG.») e poi legge
la descrizione: comincia la descrizione dal contenuto, non dal nome.

Nella lingua che la carta non ha, il dispositivo racconta quello che trova in
archivio per la stessa etichetta, invece di far leggere l'italiano alla voce
inglese.

### Dove sta

Il servizio la carica con l'opzione `--carta`. In
`scripts/systemd/amelie.service` (installato in `/etc/systemd/system/`) è:

```
--carta /home/arduino/amelie/vini.csv
```

cioè `vini.csv` nella cartella del progetto sulla board, lo stesso file che sta
alla radice del repository. Il repository ne contiene uno d'esempio, solo in
italiano. La carta si legge
all'avvio: dopo averla modificata, `sudo systemctl restart amelie.service`.
Per usare un altro file cambia il percorso nell'unità, poi `sudo systemctl
daemon-reload` e il riavvio.

Se il file manca, non si legge o non ha righe utilizzabili, il dispositivo si
accende lo stesso: nel giornale di sistema compare «carta dei vini non caricata
(…): uso l'archivio», il modo «Carta dei vini» non compare nelle impostazioni e
un modo salvato «carta» torna all'archivio. `/stato` riporta il nome del file
(`carta`) e quante voci ha caricato (`voci_in_carta`).

### Non si nomina ciò che non si è letto

Nel modo carta una bottiglia si riconosce solo per titolo: niente cascata e
niente ripiego sull'archivio. Se nessun titolo va bene, la bottiglia è non
riconosciuta. Un titolo si può dire solo se le sue parole sono sul vetro:

- ogni parola del titolo di almeno tre lettere dev'essere stata letta,
  comprese quelle che distinguono un vino dall'altro («Riserva», «Classico»,
  «Extra Brut»), con due eccezioni:
  - i marchi di denominazione, che sull'etichetta stanno piccoli: DOC, DOCG,
    DOP, IGT, IGP, AOC, AOP, AVA, DOCa, VdP, QbA, e «Annata»;
  - le parole che nel file accompagnano sempre quelle lette: se l'unica voce
    con «Brunello» è «Brunello di Montalcino DOCG», «Montalcino» è implicato.
    Le parole date per implicate non possono essere più di quelle
    identificanti lette davvero;
- fra i titoli che si possono dire vince quello che spiega più parole
  dell'etichetta, e a parità quello che ne promette meno di non lette.

Una carta sbaglia raccontando benissimo: le sue descrizioni sono lunghe e
convincenti, e attaccarne una alla bottiglia sbagliata è l'errore peggiore. Da
qui due consigli pratici. Scrivi i titoli con le parole che stanno davvero
sulle etichette. E accanto alle voci specifiche tieni una voce generica per la
denominazione («Champagne AOC» accanto a «Champagne Extra Brut»): se la parola
che distingue non si legge, la bottiglia trova comunque una voce vera invece di
restare non riconosciuta. Il dettaglio dell'algoritmo è in
[06-riconoscimento.md](06-riconoscimento.md).

## Diagnostica

### Il giornale delle scansioni

Ogni scansione, riuscita o no, lascia una riga in `var/scansioni/giornale.jsonl`
e accanto il fotogramma letto, in `var/scansioni/<data-ora>.jpg`. Ogni riga
contiene:

- quando, in che lingua, e l'`esito`: `raccontato`, `niente da leggere`, `letto
  ma non riconosciuto`, `non in carta`, `corretta a mano`, oppure `chiuso da
  <evento>` quando la scansione si interrompe (bottiglia tolta, Annulla);
- le righe lette, la nitidezza, la posa, il tentativo, i tempi di scatto e di
  OCR, e se la lettura è stata allargata o fatta in anticipo durante il
  racconto (`anticipata`);
- livello e sicurezza del riconoscimento, nome, cantina, annata, tipologia,
  denominazione, colore, candidati; nel modo carta, quando la bottiglia non si
  trova, i titoli più vicini (`vicine`); per una correzione il suo `id` e il
  perché;
- da dove viene il racconto (`racconto_da`: `template` per la composizione,
  `modello`, `cache`, `carta`, `correzione`) e il testo detto.

Si tengono le foto delle ultime scansioni (`IMMAGINI_TENUTE`, le più vecchie se
ne vanno) e il giornale, oltre una certa taglia, ruota in `giornale.1.jsonl`:
la memoria della board è flash, e un archivio che cresce per sempre diventa un
guasto. Se il giornale non si può scrivere il dispositivo continua a
raccontare. Date e ore, qui e nei nomi delle correzioni, vengono dall'orologio
della board.

### Le rotte HTTP

Il servizio ascolta solo sulla board, su `127.0.0.1:8080`. Dalla board:

```bash
curl -s localhost:8080/stato | python3 -m json.tool
```

Da un PC, apri prima un tunnel e usa `localhost:8080` allo stesso modo:

```bash
ssh -L 8080:localhost:8080 arduino@<nome-board>.local
```

| Rotta | Che cosa restituisce |
|---|---|
| `GET /stato` | lo stato tecnico, lo stesso delle impostazioni |
| `GET /pronto` | `{"pronta": true}` quando le voci sono caricate |
| `GET /giornale?quante=N` | le ultime N scansioni (da 1 a 200, predefinito 20), la più recente per prima |
| `GET /giornale/<nome>.jpg` | il fotogramma di una scansione, col nome scritto nella sua riga |
| `GET /batteria` | tacche, frazione, energia consumata, capacità, ore stimate |
| `GET /lingue` | la lingua in uso e quelle disponibili |
| `GET /mirino/lettura`, `GET /mirino/flusso` | a Debug camera accesa: la lettura in JSON e il video |

| Comando | Che cosa fa |
|---|---|
| `POST /ripristina` | come «Ripristina il funzionamento» |
| `POST /modo/<archivio\|generativa\|carta>` | cambia il modo di racconto |
| `POST /lingua/<it\|en>` | come toccare una bandiera, annuncio compreso |
| `POST /volume/<0-100>` | imposta il volume |
| `POST /mirino/<1\|0>` | accende o spegne la Debug camera |
| `POST /correzioni/<1\|0>` | accende o spegne «Aggiungi correzioni» |
| `POST /prova/<bottiglia\|via\|camera>` | finge una bottiglia sul piatto, o il piatto vuoto; `camera` torna al sensore vero |

`/prova` serve al banco: prova lettura, racconto, voce e schermo senza toccare
il piatto. Ricordati di chiudere con `/prova/camera`, altrimenti il dispositivo
continua a credere a ciò che gli hai detto.

### Che cosa il dispositivo ricorda

Tutto sta in `var/`, l'unica cartella del progetto che il servizio può
scrivere. Ogni file si scrive in modo da sopravvivere alla corrente staccata;
cancellare un file d'impostazione riporta al valore predefinito.

| File | Contenuto |
|---|---|
| `var/volume` | il volume |
| `var/modo` | il modo di racconto |
| `var/correzioni_attive` | l'interruttore «Aggiungi correzioni» |
| `var/batteria.json` | la stima della batteria |
| `var/sfondo.npy` | il piatto vuoto visto dalla camera, che si riaggiorna da sé quando il sensore dice che il piatto è vuoto |
| `var/correzioni/` | le correzioni |
| `var/scansioni/` | il giornale e i fotogrammi |

La lingua e la Debug camera non si ricordano: all'accensione il dispositivo
racconta, in italiano.

## Quando qualcosa non va

### Il guasto isolato

Quando un passo del lavoro fallisce (la camera non dà un fotogramma, l'OCR non
parte, una lettura non torna entro il suo tetto) lo schermo mostra «Qualcosa
non ha funzionato. Riprovo fra un istante.» con l'anello rosso. La schermata
scade da sola e torna all'attesa; se la bottiglia è ancora sul piatto, il
dispositivo la rilegge, per un numero limitato di volte (`TENTATIVI_MAX`). Non
serve fare niente. Se la camera smette di dare fotogrammi con una posa lunga,
riparte da sola dalla posa di partenza.

### Il ripristino automatico

Tre guasti ravvicinati (`GUASTI_PER_RIPRISTINO` entro `FINESTRA_GUASTI_S`)
vogliono dire che qualcosa si è inceppato davvero. Allora il dispositivo si
ripristina da solo, esattamente come con «Ripristina il funzionamento»:

1. ferma racconto, annuncio, editor aperto e Debug camera;
2. aspetta brevemente il lavoro in corso e, se non esce, lo lascia andare;
3. rimette la camera com'era all'accensione: flusso chiuso, posa di partenza,
   device ricercato;
4. chiude e riapre l'uscita audio;
5. nel modo «Scritto sul momento», riavvia il modello;
6. azzera i tentativi e torna all'attesa; una bottiglia ancora sul piatto si
   rilegge.

### Il riavvio del servizio

Se i guasti tornano poco dopo un ripristino (`DOPO_RIPRISTINO_S`), ripristinare
non è bastato: il processo esce e systemd lo fa ripartire (`Restart=always`).
È quello che otterresti spegnendo e riaccendendo, senza spegnere. Succede solo
sotto systemd; lanciato a mano, il servizio si ripristina e basta. A mano:

```bash
sudo systemctl restart amelie.service
journalctl -u amelie.service -f
```

Nel giornale di sistema i passi si riconoscono dalle righe `ripristino (…)` e
`riavvio del servizio: …`.

### Sintomi e rimedi

| Sintomo | Dove guardare |
|---|---|
| la bottiglia non fa partire niente | il sensore di distanza è l'unico che decide: con `mcu: false` in `/stato`, o `distanza: false` fra i `moduli`, il dispositivo non vede nessuna bottiglia. Il sensore lavora a infrarossi e può non vedere il vetro molto chiaro |
| la voce non si sente | tocca la bandiera già attiva: se l'annuncio non si sente, il problema è nell'audio. Non provare l'audio con `aplay` a servizio acceso: il servizio tiene l'uscita aperta, e un secondo programma la trova occupata |
| «In questa lingua il racconto si legge, non si ascolta.» | la voce di quella lingua non è stata caricata: guarda `voce` in `/stato` e il giornale di sistema |
| un modo non compare nelle impostazioni | «Scritto sul momento» richiede `--con-modello`; «Carta dei vini» una carta caricata |
| le letture falliscono, o l'etichetta esce dal riquadro | accendi la Debug camera e guarda riquadro, nitidezza e righe lette; poi il giornale delle scansioni |
| il puntino in basso a destra dello schermo è rosso | il microcontrollore non risponde (`mcu: false` in `/stato`), oppure la pagina ha perso il collegamento col servizio: in quel caso si riaggancia da sola quando il servizio risponde, e se non basta `sudo systemctl restart amelie-kiosk.service` |
| «Qualcosa non ha funzionato» si ripete | «Ripristina il funzionamento», poi il giornale di sistema |
