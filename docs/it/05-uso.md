# Usare Amelie

Amelie racconta il vino che le appoggi davanti: legge l'etichetta con la
camera, riconosce la bottiglia e ne dice la storia sullo schermo e a voce, in
italiano o in inglese, senza nessuna connessione.

Davanti c'è lo schermo, inclinato verso chi siede al tavolo. Dietro lo schermo
c'è il piatto, il disco traslucido su cui si posa la bottiglia. La camera e la
luce stanno nella torre che regge lo schermo, rivolte verso il piatto; il
sensore di distanza sta sotto il disco.

Questa guida descrive che cosa vede e che cosa può fare chi siede al tavolo,
che cosa trova chi gestisce il dispositivo nelle impostazioni, e dove guardare
quando qualcosa non va. Le frasi fra caporali sono le scritte esatte dello
schermo e le parole esatte della voce (`data/lessico/frasi.json` e
`src/amelie/ui/static/index.html`). Come si arriva dall'etichetta al vino è in
[06-riconoscimento.md](06-riconoscimento.md), come si compone il racconto in
[07-racconto.md](07-racconto.md).

## La schermata d'attesa

All'accensione lo schermo mostra il marchio da solo, il calice e il nome, con
il vino che oscilla piano nel calice, e resta così finché le voci non sono
caricate: così la prima bottiglia trova la voce già pronta. Di norma ci vuole
meno di un minuto. Se dopo novanta secondi il dispositivo non è ancora pronto,
in basso compaiono «Ci vuole più del solito.» e, sotto, «This is taking longer
than usual.» (vedi [Sintomi e rimedi](#sintomi-e-rimedi)).

Quando il dispositivo è pronto mostra la schermata d'attesa: il calice, il
nome, la frase «Ogni bottiglia ha una storia.» e tre passi, ciascuno con la
sua icona:

| | italiano | inglese |
|---|---|---|
| 1 | **Scegli** una bottiglia | **Choose** a bottle |
| 2 | **Posa** la bottiglia su Amelie | **Place** the bottle on Amelie |
| 3 | **Ascolta** la sua storia | **Listen** to its story |

I tre passi sono un'insegna, come su un cartello, e per questo in italiano
danno del tu; quando il dispositivo si rivolge all'ospite gli dà del Lei
(«Provi a girare l'etichetta verso di me?»).

In alto a destra ci sono le bandiere delle lingue, in alto a sinistra
l'altoparlante del volume. Sono gli unici punti che rispondono al tocco,
insieme a un angolo nascosto che apre le impostazioni
([Come si aprono](#come-si-aprono)). Il resto dello schermo è inerte di
proposito: su un tavolo un tocco accidentale è la norma. Ogni pulsante agisce
quando alzi il dito, e solo se il dito è ancora sopra: un tocco partito per
sbaglio si annulla scivolando via. Fanno eccezione i tasti della tastiera
delle correzioni, che scrivono appena li premi.

Nell'angolo in basso a destra c'è un puntino minuscolo, di norma quasi
invisibile: diventa rosso quando il microcontrollore non risponde o quando la
pagina ha perso il collegamento col servizio (vedi
[Sintomi e rimedi](#sintomi-e-rimedi)).

## Una bottiglia, dall'inizio alla fine

### Posarla

Posa la bottiglia in piedi sul piatto, con l'etichetta rivolta verso lo
schermo: la camera la guarda dalla torre, e un'etichetta girata di lato si
legge male, o non si legge.

Che una bottiglia ci sia lo decide il sensore di distanza, e solo lui: se ne
accorge in un attimo (tre letture concordi, circa 0,15 secondi). La camera
serve a sapere dove sta l'etichetta. Appena posi la bottiglia lo schermo dice
«Fammi guardare…»; poi «Sto leggendo l'etichetta…» mentre la camera scatta e
l'OCR legge, e «Un attimo…» mentre cerca il vino. Intanto un'animazione mostra una bottiglia che versa in
un calice.

### Il racconto

Poi parte il racconto, sullo schermo e a voce. La schermata mostra:

- in alto il **titolo**: il nome del vino; oppure la tipologia, la
  denominazione o il vitigno, quando il riconoscimento si ferma lì; oppure,
  quando in archivio non c'è niente che si possa nominare, ciò che si è letto
  sul vetro (per esempio «Spumante rosato, brut»). Sotto, cantina e annata, se
  le conosce. Per una bottiglia corretta a mano o raccontata dalla carta dei
  vini il titolo è quello scritto lì, senza riga sotto;
- con «Aggiungi correzioni» acceso, sotto il titolo, il pulsante «Correggi la
  bottiglia» ([Le correzioni](#le-correzioni));
- il **testo** intero, con accesa la frase che la voce sta dicendo; il testo
  scorre da solo per tenerla in vista, e col dito non si trascina;
- i **comandi**, quattro cerchi in basso al centro, con sotto una **barra** che
  si riempie fino alla fine del racconto;
- la **croce** in basso a sinistra: è Annulla.

La prima frase dice che cosa c'è sul piatto e quanto il dispositivo ne è
sicuro: «Questo è il …» quando il riconoscimento è certo, «Direi il …» o
«Dovrebbe essere il …» quando è una supposizione. Molte frasi hanno più forme
equivalenti, e per lo stesso vino esce sempre la stessa. Quando l'etichetta si
legge ma in archivio non c'è niente che si possa nominare, il dispositivo dice
soltanto ciò che è scritto sulla bottiglia (per esempio che è uno spumante
rosato, brut) e chiude con «Questa bottiglia non è nel mio archivio; la
descrizione è stata generata in autonomia sulla base dei dati e del catalogo a
mia disposizione.»

Se per la lingua scelta non c'è una voce, il racconto si legge e basta: il
testo scorre da solo al ritmo di una lettura, comandi e barra spariscono, e in
basso, su ogni schermata, compare «In questa lingua il racconto si legge, non
si ascolta.» L'italiano e l'inglese hanno tutte e due la loro voce (`VOCI` in
`src/amelie/speech.py`): succede solo con una lingua aggiunta al lessico senza
una voce.

### I comandi del racconto

| Comando | Dove | Che cosa fa |
|---|---|---|
| Da capo | primo cerchio, la freccia circolare | ricomincia il racconto dall'inizio, anche se era in pausa |
| Indietro | secondo cerchio, due triangoli verso sinistra | torna indietro di 5 secondi |
| Pausa / riprendi | terzo cerchio, il più grande: due barre, o un triangolo quando è in pausa | ferma la voce; toccato di nuovo, riparte da lì, ripetendo l'ultimo istante per non tagliare una parola |
| Avanti | quarto cerchio, due triangoli verso destra | salta avanti di 5 secondi, fin dove la voce è già pronta |
| Annulla | la croce in basso a sinistra | chiude il racconto e torna alla schermata d'attesa |

I salti valgono `SALTO_S` (`src/amelie/app.py`).

Finito il racconto, il testo resta a schermo due secondi, dodici con «Aggiungi
correzioni» acceso (`CONCLUSO_CON_CORREZIONE_S`, il tempo di arrivare al
pulsante), poi torna la schermata d'attesa. Su questa schermata finale i
cerchi non hanno più niente da comandare e al primo tocco si spengono; la
croce invece funziona, e torna subito all'attesa.

**Annulla** serve a chi ha già versato e vuole il silenzio senza sollevare di
nuovo la bottiglia. Funziona anche quando il racconto non è ancora cominciato
(per esempio mentre il modello sta scrivendo). Dopo Annulla la lingua resta
quella scelta, e la bottiglia rimasta sul piatto non si rilegge: il
dispositivo aspetta che venga tolta.

Una pausa non occupa il dispositivo per sempre: quindici minuti dopo l'inizio
del racconto (`TETTO_RACCONTO_S` in `src/amelie/app.py`) la voce si ferma
comunque. Il testo resta a schermo, i cerchi non rispondono più, e se ne esce
con la croce.

### Togliere la bottiglia

| Quando la togli | Che cosa succede |
|---|---|
| durante «Fammi guardare…», la lettura, la ricerca del vino o «Provi a girare l'etichetta verso di me?» | il giro si interrompe e torna subito la schermata d'attesa |
| durante il racconto | non si ferma niente: il racconto va fino in fondo (o resta in pausa), poi la schermata finale e l'attesa |
| sulla schermata finale, anche su «Non ho riconosciuto questa bottiglia.» | torna subito la schermata d'attesa |
| durante «Qualcosa non ha funzionato. Riprovo fra un istante.» | la schermata finisce i suoi sei secondi, poi torna l'attesa |
| dopo il ritorno all'attesa | la prossima bottiglia posata comincia un giro nuovo |

In tutti questi casi, quando lo schermo torna all'attesa col piatto vuoto, la
lingua torna quella di casa ([Le lingue](#le-lingue)).

Il racconto continua perché chi solleva la bottiglia per versare non ha chiesto
silenzio: un racconto che muore a metà frase si nota più di uno che finisce.
Per zittire il dispositivo c'è Annulla.

### Rimettere la stessa bottiglia

Se la rimetti mentre il racconto è in corso, o sulla schermata finale, il
dispositivo la guarda subito, senza fermare la voce. Se la foto ritrova
l'etichetta di prima (almeno 25 punti dell'immagine, `STESSA_A_OCCHIO`), o se
si rileggono le stesse parole (con la regola delle correzioni, vedi
[Come si riconosce la volta dopo](#come-si-riconosce-la-volta-dopo)), il
racconto va avanti e alla fine la bottiglia non si rilegge. Due etichette
dello stesso vino, fronte e retro, contano come la stessa bottiglia, perché
raccontano la stessa storia. Se dalla nuova lettura non esce nessuna parola che
identifichi la bottiglia, il dispositivo non può decidere: lascia finire il
racconto e rilegge la bottiglia dopo.

Se la rimetti quando lo schermo è già tornato all'attesa, è un giro nuovo e il
racconto ricomincia da capo. È anche il modo di riascoltare una bottiglia.

### Cambiarla con un'altra

Una bottiglia diversa posata durante il racconto, o sulla schermata finale, si
legge subito, mentre la voce parla ancora della precedente. Appena le parole
lette dicono che è un altro vino, la voce tace e parte il racconto della
nuova, già letta: non serve un'altra foto. La decisione la prende il testo e
non la foto: la foto sa dire in fretta che una bottiglia è la stessa, ma una
bottiglia rimessa girata ritrova pochi punti dell'etichetta di prima, e da lì
non si può concludere che sia un'altra.

### La bottiglia che non si riconosce

Due casi portano alla stessa schermata: l'OCR non trova nessuna parola (cifre
e frammenti non contano), oppure trova parole ma nessun vino (nel modo «Carta
dei vini»: nessuna voce della carta). Lo schermo mostra il simbolo ↻ e «Provi
a girare l'etichetta verso di me?», e dopo quattro secondi il dispositivo
riprova con una foto nuova: è il momento di girare la bottiglia. La luce resta
accesa: serve a rileggere.

Dopo tre letture fallite (`TENTATIVI_MAX` in `src/amelie/app.py`) il
dispositivo smette:

- con «Aggiungi correzioni» acceso e almeno una parola identificante letta,
  compare il simbolo ? con «Non ho riconosciuto questa bottiglia.» e il
  pulsante «Mi aiuti a riconoscerla»; la schermata resta dodici secondi
  (`CONCLUSO_CON_CORREZIONE_S`), il tempo di arrivarci, poi torna l'attesa;
- altrimenti torna subito la schermata d'attesa.

In tutti e due i casi la bottiglia rimasta sul piatto non si rilegge: per
riprovare, sollevala e rimettila. Senza questo tetto un oggetto qualunque
lasciato sul piatto (un bicchiere, una bottiglia senza etichetta) terrebbe
accesi camera, luce e OCR per tutta la sera. Con le correzioni accese «Mi
aiuti a riconoscerla» compare anche fra un tentativo e l'altro, sotto la
richiesta di girare l'etichetta.

### La luce

La luce sta nella torre e illumina l'etichetta attraverso una finestra
traslucida: otto LED, alternati bianchi e gialli, al massimo.

| Momento | Luce |
|---|---|
| accensione, finché il dispositivo non è pronto | bianca e gialla, che pulsa piano |
| attesa, lettura, racconto, Debug camera | bianca e gialla, fissa |
| attesa con la batteria quasi scarica (sotto il 15 % della stima) | rossa |
| «Qualcosa non ha funzionato. Riprovo fra un istante.» | rossa |

La pulsazione dell'accensione la fa il microcontrollore da solo, per dire che
il dispositivo è vivo mentre il sistema si avvia. Poi la luce resta la stessa
in attesa e durante la lettura: la camera regola la sua esposizione a riposo,
con la luce che troverà allo scatto, e la bottiglia trova la posa già quasi
giusta. Con la batteria quasi scarica la luce diventa rossa solo in attesa:
mentre legge resta bianca e gialla, perché illumina l'etichetta. Quanta
batteria resta lo dice anche l'icona nelle impostazioni.

## Le lingue

Le bandiere stanno in alto a destra su ogni schermata del ciclo, racconto
compreso; impostazioni, Debug camera ed editor delle correzioni coprono tutto
lo schermo, bandiere comprese. Quella della lingua in uso è piena, con un
cerchio d'oro attorno; le altre sono smorzate.

- **Tocchi l'altra bandiera**: le scritte cambiano subito e il dispositivo lo
  conferma a voce, nella lingua nuova: «Lingua italiana. Da adesso racconto i
  vini in italiano.» oppure «English language. From now on I will describe the
  wines in English.» Fuori dalla schermata del racconto la frase compare anche
  scritta in basso, come un sottotitolo. Se un racconto è in corso si ferma
  subito, e finito l'annuncio ricomincia da capo nella lingua nuova; lo stesso
  vale per un racconto appena finito: stesso vino, senza rimettere la
  bottiglia. Sulla schermata finale il
  tocco la tiene accesa fino a quindici secondi
  (`LINGUA_A_RACCONTO_FINITO_S`), il tempo perché l'annuncio e il racconto
  nella lingua nuova arrivino.
- **Tocchi la bandiera già attiva**: non cambia niente, ma l'annuncio si fa lo
  stesso. È il modo più rapido di provare voce e casse senza una bottiglia.
- **Tocchi mentre un annuncio sta parlando**: l'annuncio si interrompe e parte
  quello della lingua appena scelta.

La lingua di partenza è l'italiano (`Configurazione.lingua` in
`src/amelie/app.py`; non c'è un'opzione da riga di comando). Il dispositivo ci
torna da solo, senza annunciarlo, quando la bottiglia è stata tolta e lo
schermo torna all'attesa: chi arriva dopo trova la lingua di casa. Se la
bottiglia si toglie durante il racconto, la lingua torna a casa quando, finito
il racconto, lo schermo torna all'attesa. Finché la bottiglia resta sul piatto
la lingua scelta resta: a racconto finito, dopo Annulla, dopo un guasto,
perché al tavolo ci sono ancora le stesse persone. Annulla e «Ripristina il
funzionamento», di per sé, non cambiano lingua: se si tocca la croce quando il
piatto è già vuoto, la lingua scelta resta anche per la bottiglia successiva.

Nomi di vini, cantine e annate non si traducono: sono ciò che è stampato sulla
bottiglia. Una carta dei vini o una correzione senza testo nella lingua scelta
lasciano parlare l'archivio (vedi le sezioni relative).

## Il volume

Tocca l'altoparlante in alto a sinistra: accanto si apre un cursore. Trascina
il pomello, o tocca il punto del binario che vuoi; il livello va da 0 a 100 a
passi di 5. Il cursore si richiude da solo dopo quattro secondi e mezzo senza
tocchi, quando cambia la schermata, o toccando di nuovo l'altoparlante.

- **L'icona dice il livello anche a cursore chiuso**: due onde da metà corsa in
  su, una sotto metà, nessuna e un taglio a zero. A zero il dispositivo
  racconta lo stesso, in silenzio.
- **A mano ferma** il dispositivo fa sentire un colpetto su un calice al
  livello nuovo, così lo regoli senza appoggiare una bottiglia. Mentre racconta
  o annuncia una lingua il colpetto non c'è: il livello si sente già.
- **Il guadagno è il quadrato del valore**: metà corsa vale circa −12 dB, che
  all'orecchio suona come metà volume. 100 è il massimo che il segnale digitale
  porta senza distorcere, e oltre non si va.
- **Si ricorda** fra un'accensione e l'altra (`var/volume`). Senza un valore
  salvato vale l'opzione `--volume` del servizio, e senza opzione 100.

La catena audio non ha un controllo di volume hardware: il suono esce dalla
board via HDMI e arriva alle casse attraverso lo schermo. Quello che si regola
è il segnale, un istante prima dell'uscita. Se il servizio parte senza voce
(`--senza-voce`) l'altoparlante non compare.

## Le impostazioni

### Come si aprono

Tieni il dito fermo **sull'angolo in basso a destra** dello schermo per **tre
secondi**. L'area sensibile è un quadrato di circa un centimetro nell'angolo;
mentre tieni premuto non compare niente, e allo scadere dei tre secondi si
apre il pannello. Se alzi il dito prima, o lo sposti di più di qualche
millimetro (30 pixel, `ANGOLO_SCARTO` in `src/amelie/ui/static/index.html`),
il gesto si annulla e va ripetuto. Funziona dalle schermate del ciclo (attesa,
lettura, racconto, avvisi), non sopra l'editor delle correzioni o la Debug
camera. L'ingresso è nascosto di proposito: raggiungibile con un tocco, lo
aprirebbe per sbaglio chi appoggia una bottiglia.

Il pannello, intitolato «Impostazioni», copre lo schermo; l'elenco scorre col
dito, e si chiude con la croce in basso a sinistra, nello stesso posto di
Annulla. Non si chiude da solo: chiudilo prima di lasciare il dispositivo agli
ospiti. Non ferma il dispositivo: una bottiglia posata intanto viene letta e
raccontata sotto, e la voce si sente. Quasi ogni riga ha, sotto il nome, una
riga di spiegazione. Le righe, dall'alto:

### Come racconta

La prima sezione, «Come racconta», sceglie da dove viene il testo. Ogni modo è
una riga, e quello in uso ha il segno di spunta.

| Modo | Da dove viene il testo | Quando compare |
|---|---|---|
| «Dall'archivio» (predefinito) | composto dai dati dell'archivio e dal disciplinare, senza modello: non inventa ed è immediato | sempre |
| «Scritto sul momento» | gli stessi dati, ma il testo lo scrive il modello linguistico per quella bottiglia; sperimentale, può sbagliare e fa aspettare qualche decina di secondi | solo se il servizio parte con `--con-modello`, come fa l'unità installata |
| «Carta dei vini» | le descrizioni scritte a mano nel file della carta, e solo per i vini che contiene | solo se una carta è caricata con `--carta`, come fa l'unità installata ([La carta dei vini](#la-carta-dei-vini)) |

La differenza fra i modi non è di stile, è la fonte di quello che il
dispositivo dice. Il modo scelto vale dalla bottiglia successiva (cambiarlo a
metà lettura interromperebbe chi ascolta) e si ricorda in `var/modo`. Un modo
salvato che il dispositivo non può servire (la carta che manca, il modello non
abilitato) torna all'archivio.

Nel modo «Scritto sul momento»:

- scegliere il modo accende `amelie-llm.service`, sceglierne un altro lo
  spegne: fermo a vuoto il modello occupa un core che serve all'OCR;
- prima di ogni racconto il dispositivo aspetta che il modello risponda, fino
  a 45 secondi (appena acceso, il modello si sta ancora caricando); mentre il
  modello scrive, al posto del testo compare «Sto scrivendo la descrizione…»
  con un piccolo calice;
- quello che il modello scrive passa da una verifica; se inventa due volte di
  fila si usa il testo già pronto per quel vino, se c'è, e altrimenti la
  composizione dai fatti. Si ripiega allo stesso modo se il modello non
  risponde;
- quando si sa soltanto ciò che è scritto sull'etichetta il modello non scrive
  mai: si racconta la composizione.

Le correzioni a mano hanno la precedenza in tutti e tre i modi.

### Aggiungi correzioni

Un interruttore, spento finché non lo accendi; resta com'è anche dopo un
riavvio (`var/correzioni_attive`). Acceso:

- sotto il titolo di ogni racconto compare «Correggi la bottiglia», o
  «Modifica la correzione» su una bottiglia già corretta;
- le bottiglie non riconosciute offrono «Mi aiuti a riconoscerla»;
- la schermata finale del racconto resta dodici secondi invece di due, per
  lasciare il tempo di arrivare al pulsante.

Spento, nessun ospite vede un pulsante per correggere, ma le correzioni già
salvate si riconoscono comunque. Il cambio vale subito, anche sul racconto a
schermo; se si spegne con l'editor aperto (da `POST /correzioni/0`), l'editor
si chiude senza salvare. Oltre al gesto nascosto e all'interruttore non c'è un
PIN: accendilo quando vuoi correggere, e spegnilo prima di lasciare il
dispositivo agli ospiti.

### Debug camera

Un interruttore che mostra a tutto schermo che cosa vede la camera e che cosa
riesce a leggere, per mettere a punto l'inquadratura:

- a sinistra il video, con il **riquadro** che va all'OCR (fuori da lì non si
  legge niente; se il dispositivo ha trovato la bottiglia è il riquadro
  attorno a lei, se no quello fisso), le due mezzerie per centrare l'etichetta
  e la scritta `nitidezza N (soglia S)`: tutto in verde dalla soglia in su, in
  rosso sotto;
- a destra «Cosa legge», con il tempo della lettura e le righe trovate (le
  prime dieci, poi «e altre N»; «nessuna riga di testo» se non ce ne sono), e
  «Cosa trova», con livello e sicurezza (in verde se il riconoscimento è
  certo, in ambra se è dubbio, in rosso altrimenti), vino, cantina e annata,
  fino a tre candidati, e in fondo nitidezza e posa. Questa colonna interroga
  l'archivio, non la carta né le correzioni, e resta qualche secondo indietro
  rispetto al video: è il tempo dell'OCR.

Accenderla **ferma il ciclo**: la camera la usa un processo alla volta, quindi
niente racconti né letture finché è accesa, e un racconto in corso si
interrompe. La luce resta quella di sempre, bianca e gialla, e la posa si
cerca una volta, così inquadri con la luce che ci sarà davvero. Dallo schermo si esce solo dal pulsante
«torna al racconto», in basso a destra, perché la Debug camera copre il
pannello; uscendo, una bottiglia rimasta sul piatto si legge subito, e questa è
la prova che l'inquadratura funziona. Non si ricorda fra un avvio e l'altro, e
la riga non compare se il servizio è partito senza camera (`--senza-camera`).

Per guardare da un PC, su uno schermo grande, c'è anche `scripts/mirino.py`,
con la stessa logica. Va lanciato a servizio fermo, perché la camera la usa un
processo alla volta:

```bash
sudo systemctl stop amelie.service
cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/mirino.py --ocr --luce
```

poi si apre `http://<nome-board>.local:8090/` nel browser del PC. Ctrl-C lo
chiude, e `sudo systemctl start amelie.service` rimette in moto il
dispositivo.

### Batteria ricaricata

Il power bank non comunica niente: il dispositivo stima quanta energia ha
speso da quanto è acceso, da quanto lavora la CPU e da quanto parla, su una
capacità utile di 60 Wh (`CAPACITA_WH` in `src/amelie/batteria.py`). La stima
si vede solo in questa riga, come un'icona a quattro tacche, senza un numero,
perché è una stima: quattro tacche dal 75 % in su, tre dal 50 %, due dal 25 %,
una dall'8 %. L'ultima tacca sparisce all'8 % e non a zero, perché lì il power
bank può spegnersi senza avvisare; a zero tacche il contorno diventa rosso e
pulsa.

Tocca la riga dopo aver ricaricato: la stima riparte da piena e l'icona torna a
quattro tacche. All'accensione il dispositivo lo fa da solo se è rimasto spento
almeno tre ore (`RICARICATA_DOPO_S`), come dopo una ricarica notturna; dopo un
riavvio breve la stima riprende da dov'era. Se all'accensione l'orologio della
board risulta tornato indietro, o avanti di più di sessanta giorni, la stima
resta quella di prima: in quel caso tocca la riga a mano.

### Ripristina il funzionamento

Rimette in moto camera, lettura e voce senza spegnere, quando «Qualcosa non ha
funzionato. Riprovo fra un istante.» si ripete. Mentre lavora la riga si
smorza (ci vuole qualche secondo), poi compare un segno di spunta e il
pannello si chiude sulla schermata d'attesa. Che cosa fa è descritto in
[Il ripristino automatico](#il-ripristino-automatico).

### Stato tecnico

Apre sopra il pannello il contenuto di `/stato`, da leggere senza tastiera: è
la fotografia del momento in cui lo apri. «chiudi» riporta alle impostazioni.
I campi più utili:

| Campo | Che cosa dice |
|---|---|
| `stato` | lo stato del dispositivo (vedi sotto) |
| `mcu`, `protocollo`, `moduli` | se il microcontrollore risponde con il firmware di Amelie, con quale versione del protocollo (quella attesa è 3), e se vede la luce (`anello`) e il sensore di distanza (`distanza`) |
| `camera`, `fotogramma_s`, `posa` | se il servizio usa la camera; da quanti secondi la camera non dà un fotogramma (a riposo meno di un secondo, `null` se non ne ha mai dato uno; durante il racconto la camera è spenta e il numero cresce); l'esposizione in uso |
| `bottiglia` | se il sensore di distanza vede una bottiglia |
| `differenza`, `soglia` | quanto il piatto, visto dalla camera, differisce da quello vuoto, in percentuale, e la soglia oltre la quale la camera ci vede qualcosa |
| `voce`, `volume`, `pronta` | se c'è il modello della voce in uso, il volume, se il dispositivo ha finito di prepararsi |
| `modo`, `racconti_generati`, `carta`, `voci_in_carta` | il modo di racconto, se il testo lo scrive il modello, il file della carta e quante voci contiene |
| `ultimo_livello`, `sicurezza` | l'esito dell'ultimo riconoscimento: il livello (`vino`, `tipologia`, `denominazione`, `vitigno`, `generico`, `nulla`) e la sicurezza, da 0 a 100 |
| `transizioni` | gli ultimi dodici passaggi di stato |

Gli stati, nell'ordine di un giro: `attesa` (la schermata d'attesa),
`assestamento` («Fammi guardare…»), `scansione` (la lettura),
`riconoscimento` (la ricerca del vino), `racconto`, `concluso` (la schermata
finale, o «Non ho riconosciuto questa bottiglia.»); `riposiziona` è «Provi a
girare l'etichetta verso di me?», `guasto` è «Qualcosa non ha funzionato.
Riprovo fra un istante.».

## Le correzioni

Una correzione insegna al dispositivo una bottiglia: che cosa dire di lei, o a
quale vino conosciuto corrisponde. Si fa dallo schermo, con «Aggiungi
correzioni» acceso.

### Aprire l'editor

- **Da un racconto**, con «Correggi la bottiglia» (o «Modifica la correzione»
  su una bottiglia già corretta). Il pulsante compare insieme al testo e resta
  anche sulla schermata finale. La voce si ferma. Su una bottiglia già
  corretta l'editor riapre la correzione com'è. Altrimenti, se il dispositivo
  ha riconosciuto un vino, una tipologia o una denominazione dell'archivio, o
  una voce della carta, l'editor si apre già collegato a quello, col suo nome
  nel titolo; se no, col titolo vuoto.
- **Da una bottiglia non riconosciuta**, con «Mi aiuti a riconoscerla», fra un
  tentativo e l'altro o su «Non ho riconosciuto questa bottiglia.»: l'editor si
  apre col titolo vuoto. Il pulsante c'è solo se dall'etichetta si è letta
  almeno una parola identificante, perché la volta dopo la bottiglia si
  ritrova dalle parole e dalla foto insieme, e senza parole non tornerebbe mai.

La foto e la lettura si fissano all'apertura: se nel frattempo qualcuno cambia
bottiglia, la correzione resta attaccata a quella giusta. Mentre l'editor è
aperto il dispositivo non guarda il piatto, e un editor dimenticato si chiude
da solo dopo dieci minuti (`CORREZIONE_TETTO_S`), come se si fosse toccata la
croce.

### L'editor

Copre tutto lo schermo, bandiere e volume compresi. In alto ci sono la croce a
sinistra, il nome dell'editor al centro («Correggi la bottiglia», «Modifica la
correzione» o «Mi aiuti a riconoscerla») e «Salva» a destra. Sotto, una riga
di note, che di norma dice «Scriva il nome e scelga il vino giusto, o ne
scriva la descrizione: la prossima volta riconoscerò la bottiglia.». Poi la
foto appena scattata, il campo «Titolo» e il campo «Descrizione», e in basso
una tastiera italiana disegnata dalla pagina:

- le accentate stanno sui tasti (è, é, à, ò, ù, ì), l'apostrofo accanto alla
  virgola; «?123» passa a numeri e simboli (€, %, °, «», …) e «ABC» torna
  alle lettere;
- i tasti scrivono appena li premi;
- la maiuscola si accende da sola a inizio campo, dopo un punto e a capo; un
  tocco la spegne, un doppio tocco la blocca;
- il tasto che cancella, tenuto premuto, continua a cancellare;
- Invio nel titolo passa alla descrizione, nella descrizione va a capo;
- toccando un campo ci si sposta lì, nel punto toccato.

Il titolo tiene fino a 120 caratteri, la descrizione fino a 2000.

**Il titolo cerca.** Dalla seconda lettera, al posto della descrizione
compaiono le bottiglie che il dispositivo conosce il cui nome contiene le
parole scritte (l'ultima anche solo come inizio di parola): prima quelle già
corrette, poi la carta dei vini, poi l'archivio, cinque per volta, fino a
venti. Sotto ognuna c'è la provenienza: «corretta a mano», «carta dei vini»,
«archivio · vino», «archivio · tipologia», «archivio · denominazione»; i vini
dell'archivio portano accanto al nome la cantina. Nell'archivio vengono prima
i nomi che cominciano come hai scritto, poi i più corti: la denominazione
prima dei vini dei singoli produttori. L'ultima casella è «Nessuna di queste»:
con sotto «altre N» passa alle successive, con sotto «scrivo la descrizione»
torna al campo descrizione.

- **Scegli un vino della carta o dell'archivio**: la bottiglia gli viene
  **collegata**. Nella riga di note compare «Collegata a: …» con una crocetta
  per togliere il collegamento, e il campo descrizione dice «Descrizione
  (facoltativa: vuota, racconto la sua scheda)». Vuota, la bottiglia si
  racconta con la scheda del vino collegato: dall'archivio secondo il modo di
  racconto, dalla carta con la sua descrizione. Scritta, parla la tua
  descrizione.
- **Scegli una bottiglia già corretta**: la foto di questa lettura si aggiunge
  a quella correzione invece di crearne un doppione; se la descrizione è
  vuota, si riempie con la sua.
- **Riscrivi il titolo dopo una scelta**: il collegamento si toglie da sé.

Se la bottiglia somiglia a una già corretta senza essere stata riconosciuta,
all'apertura la riga di note chiede «È una di queste?» e mostra fino a tre
candidate, ognuna con la sua foto e il suo titolo. Toccarne una vuol dire che
è lei: titolo e descrizione si riempiono con i suoi, e salvando la foto si
aggiunge a quella correzione. Toccarla di nuovo annulla la scelta.

Senza collegamento la descrizione è obbligatoria. «Salva» con un campo che
manca scrive nella riga di note «Scriva un titolo» o «Scriva una descrizione»
e contorna di rosso quel campo. Il dispositivo racconta una correzione aprendo
con una frase che la nomina («Questo è un …») e poi leggendo la descrizione
così com'è: non serve ripetere il nome in apertura.

### Salvare, e l'altra lingua

«Salva» scrive «Salvata. La riconoscerò.» nella riga di note, l'editor si
chiude e la bottiglia si racconta subito con il testo nuovo: è la prova che la
correzione funziona. Il testo vale per la lingua in cui era lo schermo
all'apertura dell'editor.

Se la correzione ha una descrizione, prima di chiudersi l'editor chiede, nella
lingua dello schermo, se la si vuole anche nell'altra: «Vuole scrivere la
descrizione anche in inglese?» con lo schermo in italiano, «Would you like to
write the description in Italian too?» con lo schermo in inglese. Il racconto
aspetta la risposta. «Sì, la scrivo» riapre l'editor sulla stessa correzione,
intitolato «Descrizione in inglese» (con lo schermo in inglese «Description in
Italian»), col titolo già scritto, perché il nome di un vino di solito non si
traduce, e con la descrizione che c'era, se c'era; salvando non aggiunge
un'altra foto. «No, grazie», o la croce, racconta la bottiglia com'è; anche la
croce nell'editor della seconda lingua racconta quello che si è già salvato.
Senza descrizione (una bottiglia solo collegata) la domanda non c'è: la scheda
del vino collegato parla già tutte le lingue.

Se chiudi l'editor con la croce senza aver salvato niente, un racconto
interrotto si dà per finito (la schermata finale, poi l'attesa; la bottiglia
sul piatto non si rilegge); da una bottiglia non riconosciuta il dispositivo
riprende da dove si era fermato.

### Come si riconosce la volta dopo

Una correzione si cerca prima dell'archivio, del modello e della carta, in
qualunque modo di racconto. Una bottiglia è quella corretta quando:

- si rileggono almeno due delle parole identificanti salvate, e almeno sei su
  dieci, e l'immagine lo conferma (almeno 16 punti dell'etichetta ritrovati);
  oppure
- l'immagine da sola somiglia moltissimo (almeno 30 punti), anche se stavolta
  l'OCR ha riletto una sola delle parole salvate.

Le parole identificanti hanno almeno quattro lettere, solo lettere, e non sono
di quelle che stanno su migliaia di etichette («rosso», «brut», «spumante»).
L'immagine si confronta solo nella zona dell'etichetta, così lo sfondo della
sala, sempre uguale, non fa somigliare due bottiglie diverse. Le soglie sono in
`Regola` (`src/amelie/correzioni.py`), il perché in
[06-riconoscimento.md](06-riconoscimento.md).

Ogni salvataggio aggiunge la foto di quella lettura come vista in più: se una
bottiglia corretta non viene riconosciuta, girata o con un'altra luce,
riaprila e sceglila fra «È una di queste?» o fra le proposte «corretta a
mano».

Nella lingua in cui la correzione non ha una descrizione la bottiglia parla con
la scheda del vino collegato; senza collegamento si racconta come se la
correzione non ci fosse. Il pulsante resta «Modifica la correzione», per
aggiungere il testo mancante.

### Dove stanno, e come si cancellano

Ogni correzione è una cartella in `var/correzioni/<id>/` (sulla board
`/home/arduino/amelie/var/correzioni/`), dove `<id>` è data e ora di
creazione, `AAAAMMGG-hhmmss`:

- `correzione.json`: le date di creazione e di modifica (`creata`,
  `modificata`), i testi per lingua (`testi`, con `titolo` e `descrizione`),
  il collegamento (`riferimento`) e le viste (`viste`: foto, righe lette,
  parole, zona dell'etichetta);
- `vista-1.jpg`, `vista-2.jpg`…: le foto.

Dallo schermo una correzione si modifica ma non si cancella. Per toglierla,
sulla board:

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

Un file CSV in UTF-8, con la virgola come separatore e una prima riga con i
nomi delle colonne. Racchiudi fra virgolette i campi che contengono virgole.

| Colonna | | Contenuto |
|---|---|---|
| `titolo` | obbligatoria | il nome del vino, come si dice e come compare a schermo |
| `descrizione` | obbligatoria | il racconto in italiano, letto così com'è |
| `descrizione_en` | facoltativa | il racconto in inglese; la sua presenza aggiunge l'inglese alla carta |
| `titolo_en` | facoltativa | il titolo in inglese; se manca vale quello italiano |

```csv
titolo,descrizione,titolo_en,descrizione_en
"Barolo DOCG","La descrizione in italiano, letta così com'è.","Barolo DOCG","The English description."
```

Una riga senza titolo o senza descrizione si salta; una riga con
`descrizione_en` vuota non ha l'inglese. Il dispositivo apre con una frase che
nomina il titolo (per esempio «Questo è un Barolo DOCG.») e poi legge la
descrizione: comincia la descrizione dal contenuto, non dal nome.

Nella lingua che la carta non ha, il dispositivo racconta quello che trova in
archivio per la stessa etichetta, invece di far leggere l'italiano alla voce
inglese.

Attenzione a come si salva il file. Alcuni fogli di calcolo, salvando in CSV,
usano il punto e virgola come separatore, o mettono in testa al file il segno
BOM: in quei casi il dispositivo non trova la colonna `titolo`, scarta tutte le
righe e si accende senza carta. Un file in un'altra codifica (per esempio
Windows-1252) che contiene lettere accentate impedisce invece al servizio di
partire. Prima di usarlo, provalo sulla board con lo stesso codice che lo
legge:

```bash
cd ~/amelie && PYTHONPATH=src ./venv/bin/python -c "from amelie.carta import Carta; c = Carta('/home/arduino/carta.csv'); print(len(c.voci), 'voci, lingue:', ' '.join(sorted(c.lingue)))"
```

Un file buono risponde col numero delle voci e le lingue, per esempio
`48 voci, lingue: en it`; `CartaVuota` vuol dire separatore, BOM o nomi delle
colonne sbagliati, `UnicodeDecodeError` un file che non è in UTF-8.

### Dove sta

Il servizio la carica con l'opzione `--carta`. Nell'unità installata
(`scripts/systemd/amelie.service`, copiata in `/etc/systemd/system/`) è:

```
--carta /home/arduino/amelie/vini.csv
```

cioè `vini.csv` nella cartella del progetto sulla board, lo stesso file che sta
alla radice del repository: una carta d'esempio di denominazioni e tipologie
italiane, solo in italiano. La carta si legge all'avvio del servizio: dopo
averla modificata, `sudo systemctl restart amelie.service`.

Il modo più diretto è riscrivere `vini.csv`. È però un file del repository: se
un aggiornamento lo cambia, `git pull` si ferma per non sovrascrivere il tuo.
Per tenere la carta del locale al riparo dagli aggiornamenti, mettila in un
file tuo, per esempio `/home/arduino/carta.csv`, e indicala con un'aggiunta
all'unità, che l'installatore non tocca:

```bash
sudo systemctl edit amelie.service
```

Nell'editor che si apre, nello spazio indicato in alto, scrivi:

```ini
[Service]
ExecStart=
ExecStart=/home/arduino/amelie/venv/bin/python -m amelie.app --porta 8080 --con-modello --modello-addestrato --carta /home/arduino/carta.csv
```

Salva, poi `sudo systemctl restart amelie.service`. La riga `ExecStart=` vuota
cancella il comando dell'unità, quella dopo lo riscrive col file nuovo.
Modificare a mano l'unità in `/etc/systemd/system/` invece non dura: a ogni
esecuzione l'installatore rimette quella del repository.

Se il file manca o non ha righe utilizzabili, il dispositivo si accende lo
stesso: nel giornale di sistema compare la riga
`carta dei vini non caricata (…): uso l'archivio`, il modo «Carta dei vini»
non compare nelle impostazioni e un modo salvato `carta` torna all'archivio.
`/stato` riporta il nome del file (`carta`) e quante voci ha caricato
(`voci_in_carta`).

### Non si nomina ciò che non si è letto

Nel modo carta una bottiglia si riconosce solo per titolo: niente cascata e
niente ripiego sull'archivio (le correzioni valgono comunque, e prima). Se
nessun titolo va bene, la bottiglia è non riconosciuta. Un titolo si può dire
solo se le sue parole sono sul vetro:

- ogni parola del titolo di almeno tre lettere dev'essere stata letta,
  comprese quelle che distinguono un vino dall'altro («Riserva», «Classico»,
  «Extra Brut»), con due eccezioni:
  - i marchi di denominazione, che sull'etichetta stanno piccoli: DOC, DOCG,
    DOP, IGT, IGP, AOC, AOP, AVA, DOCa, VdP, QbA, e «Annata»;
  - le parole che nel file accompagnano sempre quelle lette: se l'unica voce
    con «Brunello» è «Brunello di Montalcino DOCG», «Montalcino» è implicato.
    Le parole date per implicate non possono essere più di quelle
    identificanti lette davvero;
- fra i titoli che si possono dire vince quello di cui si sono lette più
  parole, e a parità quello che ne ha meno di non lette.

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

Ogni scansione che arriva alla lettura, riuscita o no, lascia una riga in
`var/scansioni/giornale.jsonl` e accanto il fotogramma letto, in
`var/scansioni/AAAAMMGG-hhmmss-mmm.jpg` (il nome sta nel campo `immagine` della
riga); un guasto della camera o dell'OCR prima della lettura finisce solo nel
giornale di sistema. Ogni riga contiene:

- quando (`quando`), in che lingua (`lingua`), e l'esito (`esito`):
  `raccontato`, `niente da leggere`, `letto ma non riconosciuto`, `non in
  carta`, oppure `chiuso da <evento>` quando la scansione si interrompe prima
  del racconto (`chiuso da bottiglia_assente` se la bottiglia è stata tolta,
  `chiuso da annulla` dopo Annulla);
- le righe lette (`righe`), la nitidezza, la posa, il tentativo, i secondi di
  scatto e di OCR (`scatto_s`, `ocr_s`), e se la lettura è stata allargata
  (`allargata`) o fatta in anticipo durante il racconto (`anticipata`);
- livello e sicurezza del riconoscimento, nome, cantina, annata, tipologia,
  denominazione, colore, candidati; nel modo carta, quando la bottiglia non si
  trova, i titoli più vicini con la loro somiglianza (`vicine`); per una
  correzione il suo identificativo (`correzione`) e il perché
  (`perche_correzione`);
- da dove viene il racconto (`racconto_da`: `template` per la composizione dai
  fatti, `modello`, `cache` per un testo già pronto, `carta`, `correzione`) e
  il testo detto (`racconto`).

Quando un racconto riparte (un cambio di lingua, una correzione salvata) si
aggiunge una riga `raccontato` con il solo racconto nuovo. Le ultime righe si
leggono sulla board con `tail -n 3 ~/amelie/var/scansioni/giornale.jsonl`, o
con `GET /giornale` (sotto).

Si tengono le foto delle ultime 120 scansioni (`IMMAGINI_TENUTE` in
`src/amelie/giornale.py`; le più vecchie si cancellano), e il giornale, oltre i
4 MB, ruota in `giornale.1.jsonl`, che tiene solo la copia precedente: la
memoria della board è flash, e un archivio che cresce per sempre diventa un
guasto. Se il giornale non si può scrivere il dispositivo continua a
raccontare. Date e ore, qui e nei nomi delle correzioni, vengono dall'orologio
della board.

### Le rotte HTTP

Il servizio ascolta solo sulla board, su `127.0.0.1:8080`: dalla rete non si
raggiunge. Dalla board:

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
| `GET /pronto` | `{"pronta": true}` quando le voci sono caricate, `false` prima |
| `GET /giornale?quante=N` | le ultime N scansioni (da 1 a 200, predefinito 20), la più recente per prima, nel campo `voci` |
| `GET /giornale/<nome>.jpg` | il fotogramma di una scansione, col nome scritto nella sua riga |
| `GET /batteria` | tacche, frazione, energia consumata, capacità, ore stimate |
| `GET /lingue` | la lingua in uso e quelle disponibili |
| `GET /mirino/lettura`, `GET /mirino/flusso` | a Debug camera accesa: la lettura in JSON e il video |

I comandi si mandano in POST, per esempio
`curl -s -X POST localhost:8080/prova/bottiglia`. Rispondono in JSON;
`"ok": false` vuol dire che non c'era niente da fare, spesso con il motivo.

| Comando | Che cosa fa |
|---|---|
| `POST /annulla` | come la croce del racconto |
| `POST /racconto/<azione>` | come i cerchi del racconto: `ricomincia`, `indietro`, `alterna` (pausa e ripresa), `avanti`; ci sono anche `pausa` e `riprendi` |
| `POST /lingua/<it\|en>` | come toccare una bandiera, annuncio compreso |
| `POST /volume/<0-100>` | imposta il volume |
| `POST /modo/<archivio\|generativa\|carta>` | cambia il modo di racconto |
| `POST /correzioni/<1\|0>` | accende o spegne «Aggiungi correzioni» |
| `POST /mirino/<1\|0>` | accende o spegne la Debug camera |
| `POST /batteria/ricaricata` | come «Batteria ricaricata» |
| `POST /ripristina` | come «Ripristina il funzionamento» |
| `POST /prova/<bottiglia\|via\|camera>` | finge una bottiglia sul piatto, o il piatto vuoto; `camera` torna al sensore vero |

`/prova` serve al banco: prova lettura, racconto, voce e schermo senza toccare
il piatto; la camera fotografa comunque quello che ha davanti. Ricordati di
chiudere con `/prova/camera`, altrimenti il dispositivo continua a credere a
ciò che gli hai detto; un riavvio del servizio lo dimentica comunque.

Le altre rotte (`/`, `/eventi`, `/fonts/…`, `/correzione/…`) servono alla
pagina dello schermo.

### Che cosa il dispositivo ricorda

Tutto sta in `var/`, l'unica cartella del progetto che il servizio può
scrivere. I file d'impostazione e le correzioni si scrivono in modo da
sopravvivere alla corrente staccata; cancellare un file d'impostazione riporta
al valore predefinito.

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
parte, una lettura non torna entro il suo tetto: 50 secondi per leggere, 15 per
cercare il vino), lo schermo mostra il simbolo ⚠ e «Qualcosa non ha
funzionato. Riprovo fra un istante.», con la luce rossa. Dopo sei secondi la
schermata torna all'attesa; se la bottiglia è ancora sul piatto, il
dispositivo la rilegge, fino a tre tentativi in tutto (`TENTATIVI_MAX`). Non
serve fare niente. Se la camera smette di dare fotogrammi con una posa lunga,
riparte da sola dalla posa di partenza.

### Il ripristino automatico

Tre guasti in tre minuti (`GUASTI_PER_RIPRISTINO` entro `FINESTRA_GUASTI_S`)
vogliono dire che qualcosa si è inceppato davvero. Allora il dispositivo si
ripristina da solo, esattamente come con «Ripristina il funzionamento»:

1. ferma racconto, annuncio, editor aperto e Debug camera;
2. aspetta fino a cinque secondi il lavoro in corso e, se non esce, lo lascia
   andare;
3. rimette la camera com'era all'accensione: flusso chiuso, posa di partenza,
   device ricercato;
4. chiude e riapre l'uscita audio;
5. nel modo «Scritto sul momento», riavvia il modello;
6. azzera i tentativi e torna all'attesa; una bottiglia ancora sul piatto si
   rilegge.

### Il riavvio del servizio

Se i guasti tornano entro dieci minuti da un ripristino (`DOPO_RIPRISTINO_S`),
ripristinare non è bastato: il processo esce e systemd lo fa ripartire dopo
cinque secondi (`Restart=always` e `RestartSec=5` in
`scripts/systemd/amelie.service`); in una quarantina di secondi il dispositivo
è di nuovo pronto, voci comprese. È quello che otterresti spegnendo e
riaccendendo, senza spegnere. Succede solo sotto systemd; lanciato a mano, il
servizio si ripristina e basta. A mano:

```bash
sudo systemctl restart amelie.service
journalctl -u amelie.service -f
```

Nel giornale di sistema i passi si riconoscono dalle righe `ripristino (…)` e
`riavvio del servizio: …`.

### Sintomi e rimedi

| Sintomo | Dove guardare |
|---|---|
| all'accensione il marchio resta e compaiono «Ci vuole più del solito.» / «This is taking longer than usual.» | il servizio non è partito, o non ha finito di prepararsi: `systemctl status amelie.service` e `journalctl -u amelie.service -b`. Una carta dei vini che non è in UTF-8 impedisce l'avvio ([Il formato](#il-formato)) |
| la bottiglia non fa partire niente | se è rimasta sul piatto dopo un racconto, dopo Annulla o dopo tre tentativi, il dispositivo aspetta che la si tolga: sollevala e rimettila. Altrimenti decide il sensore di distanza, e solo lui: con `mcu: false` in `/stato`, o `distanza: false` fra i `moduli`, il dispositivo non vede nessuna bottiglia: vedi [Il microcontrollore](04-collaudo.md#il-microcontrollore). Il sensore lavora a infrarossi e può non vedere il vetro molto chiaro |
| la voce non si sente | guarda l'icona del volume (il taglio vuol dire zero) e `voce` in `/stato`: `false` vuol dire che manca il modello della voce di quella lingua, e il giornale di sistema ha la riga `voce … non caricata`. Poi tocca la bandiera già attiva: se l'annuncio non si sente, il problema è nell'audio. Non provare l'audio con `aplay` a servizio acceso: il servizio tiene l'uscita aperta, e un secondo programma la trova occupata |
| «In questa lingua il racconto si legge, non si ascolta.» | la lingua scelta non ha una voce in `VOCI` (`src/amelie/speech.py`) |
| un modo non compare nelle impostazioni | «Scritto sul momento» richiede `--con-modello`; «Carta dei vini» una carta caricata (se non lo è, il giornale di sistema dice perché) |
| le letture falliscono, o l'etichetta esce dal riquadro | accendi la Debug camera e guarda riquadro, nitidezza e righe lette; poi il giornale delle scansioni |
| il puntino in basso a destra dello schermo è rosso | il microcontrollore non risponde (`mcu: false` in `/stato`: vedi [Il microcontrollore](04-collaudo.md#il-microcontrollore)), oppure la pagina ha perso il collegamento col servizio: in quel caso si riaggancia da sola quando il servizio risponde, e se non basta `sudo systemctl restart amelie-kiosk.service` |
| «Qualcosa non ha funzionato» si ripete | «Ripristina il funzionamento», poi il giornale di sistema |
