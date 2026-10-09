# Firmware del microcontrollore

*[English version](README.en.md)*

La Arduino UNO Q ha due processori: un Qualcomm QRB2210 con Debian Linux, che
esegue l'applicazione di Amelie, e un microcontrollore **STM32U585**, che esegue
uno sketch Arduino (un programma per microcontrollore) sopra Zephyr, un sistema
operativo in tempo reale. `amelie_mcu.ino` è lo sketch di Amelie: gira sul
microcontrollore, non su Linux.

Il connettore **Qwiic** della UNO Q è cablato sul microcontrollore. Qwiic è un
connettore a quattro fili (3,3 V, massa, SDA, SCL) che collega in catena
piccoli moduli sul bus **I²C**: un bus seriale a due linee, i dati (SDA) e il
clock (SCL), su cui ogni dispositivo risponde a un proprio indirizzo a 7 bit.
Sul microcontrollore quel bus è l'I²C4, che nello sketch si chiama `Wire1`. Per
questo i due moduli di Amelie, la luce e il sensore di distanza, li vede solo il
microcontrollore, e Linux ci arriva attraverso il collegamento descritto qui
sotto.

## Il collegamento con Linux

Linux e microcontrollore si parlano attraverso il **router di Arduino**,
`arduino-router`: un servizio di Linux che riceve le richieste dei programmi
sul socket `/run/arduino-router.sock` e le passa al microcontrollore su una
linea seriale interna, e viceversa. I messaggi seguono il protocollo
**MessagePack-RPC**. Una **RPC** (*remote procedure call*, chiamata di
procedura remota) è la chiamata per nome di una funzione che gira su un altro
processore, con i suoi parametri e il suo risultato; **MessagePack** è il
formato binario compatto in cui viaggiano i dati.

Dal lato del microcontrollore lo sketch usa la libreria **Arduino_RouterBridge**:
il suo oggetto `Bridge` registra le funzioni che Linux può chiamare
(`Bridge.provide()`) e manda le notifiche (`Bridge.notify()`). Dal lato Linux le
chiama il modulo `amelie.bridge` (`src/amelie/bridge.py`).

## I due moduli

| modulo | indirizzo | dove sta e a che cosa serve |
|---|---|---|
| **Modulino Pixels** | `0x36` | la luce del dispositivo, che nel codice si chiama «anello»: otto LED sul pannello ottico nella torre, accanto alla camera, che illuminano l'etichetta attraverso la placchetta traslucida. Sale a bianco durante la raffica di scatti |
| **Modulino Distance** | `0x29` | il sensore di distanza VL53L4CD, sotto il disco su cui si appoggia la bottiglia: sente che la bottiglia è arrivata. È un sensore a tempo di volo (*time of flight*, ToF): misura il tempo che una luce infrarossa impiega a tornare, e lo sketch lo chiama `tof` |

Entrambi gli indirizzi sono quelli di fabbrica: **non c'è niente da
riprogrammare prima di montare.**

Gli indirizzi sono scritti nella forma a 7 bit. Il datasheet del Modulino Pixels
indica anche `0x6C`, l'indirizzo «Modulino»: è lo stesso `0x36` scritto su otto
bit, cioè spostato di un posto a sinistra per far spazio al bit di lettura o
scrittura. Chi scrive un proprio sketch con la libreria `Arduino_Modulino` deve
passarle `0x36`: con `0x6C` l'errore passa sotto **silenzio**, perché `begin()`
con un indirizzo esplicito restituisce `true` senza interrogare il bus.

## Quando si cercano i moduli

I moduli si cercano **solo all'avvio del microcontrollore**: per questo vanno
collegati a board spenta. L'anello si cerca subito; il sensore appena il
collegamento con Linux è pronto (vedi [All'accensione](#allaccensione)). La
ricerca si chiude quando li ha trovati tutti e due o quando sono passati dieci
secondi dall'avvio del microcontrollore (`ATTESA_MODULI_MS`), dopo almeno un
tentativo per ciascuno: all'accensione il collegamento con Linux arriva più
tardi, e il sensore ha un tentativo solo.

Un modulo è presente solo dopo una risposta vera: l'anello dopo una scrittura
riuscita, il sensore dopo aver restituito il suo codice di identità (`0xEBAA`)
e aver completato l'avvio. Un modulo collegato dopo, o un sensore che smette di
rispondere, risulta assente fino all'accensione successiva o al prossimo
caricamento del firmware, che riavvia il microcontrollore.

## Le librerie

Il **core** è il pacchetto che permette ad `arduino-cli`, lo strumento di
Arduino a riga di comando, di compilare per una scheda: per la UNO Q è
`arduino:zephyr`. Sulla UNO Q `arduino-cli` è già installato; su un altro
computer si installa come spiegato in
<https://arduino.github.io/arduino-cli/latest/installation/>. Lo sketch include
una sola libreria esterna, **Arduino_RouterBridge**; `Wire`, la libreria del
bus I²C, e le intestazioni di Zephyr fanno parte del core.

Le versioni fissate, le stesse che installa `scripts/firmware.sh`, sono il core
`arduino:zephyr` 1.0.0 e `Arduino_RouterBridge` 0.4.3:

```bash
arduino-cli core update-index
arduino-cli core install arduino:zephyr@1.0.0
arduino-cli lib install Arduino_RouterBridge@0.4.3
```

Il core è lo stesso che usa App Lab: vedi più sotto «Sketch e loader vanno in
coppia».

`arduino-cli` installa da sé le librerie da cui Arduino_RouterBridge dipende:
Arduino_RPClite e, a cascata, MsgPack con ArxContainer, ArxTypeTraits e
DebugLog. Di queste non si fissa la versione: la sceglie `arduino-cli`.

Lo sketch non usa la libreria `Arduino_Modulino`: ogni transazione I²C, verso
l'anello e verso il sensore, è scritta a mano nello sketch, con un'attesa
limitata. Il perché è nel commento in testa ad `amelie_mcu.ino`: senza
`Modulino.begin()` la libreria usa un puntatore nullo; `begin()` con un
indirizzo esplicito e `write()` restituiscono `true` anche quando il modulo non
risponde; il driver del sensore può ritentare un trasferimento all'infinito.

## Caricarlo sul microcontrollore

### Dalla board, con `firmware.sh`

`scripts/firmware.sh` installa core e libreria alle versioni fissate, compila lo
sketch sulla board e lo carica sul microcontrollore con `remoteocd`, **insieme al
loader del core**. `remoteocd` è lo strumento del core che carica il firmware
attraverso OpenOCD (*Open On-Chip Debugger*), un programma libero che scrive la
memoria di un microcontrollore dalla sua porta di debug. Lanciato sulla board
senza indirizzo né numero di serie, `remoteocd` lavora in locale, con l'OpenOCD
della board, e **non chiede password**. `scripts/install.sh` lo lancia al
passo 9.

Dopo il caricamento lo script aspetta che il microcontrollore risponda con il
protocollo che l'applicazione si aspetta, e solo allora lo dichiara caricato:
ne tiene un'impronta in `var/firmware/.caricato`, insieme alle versioni di core
e libreria. A ogni lancio chiede al microcontrollore se risponde, e ricarica
anche quando l'impronta dice che è tutto a posto ma il microcontrollore tace.
Prima di caricare dice ad App Lab, l'ambiente di Arduino per creare e avviare
app sulla UNO Q, di non avviare nessuna app all'accensione: un'app di App Lab
sostituirebbe questo firmware sul microcontrollore.

Per ricaricare il firmware a mano dalla board, per esempio per far ripartire la
ricerca dei moduli, come utente `arduino`:

```bash
cd ~/amelie
bash scripts/firmware.sh --sempre
```

`--sempre` ricarica anche se il microcontrollore risponde già. In fondo lo
script dice quali Modulino vede. I comandi che esegue, per chi vuole farli a
mano:

```bash
cd ~/amelie
arduino-cli compile -b arduino:zephyr:unoq --output-dir var/firmware firmware/amelie_mcu
CORE=~/.arduino15/packages/arduino/hardware/zephyr/1.0.0
OCD=$(find ~/.arduino15/packages/arduino/tools/remoteocd -name remoteocd -type f | sort -V | tail -1)
"$OCD" upload -f "$CORE/variants/arduino_uno_q_stm32u585xx/flash_sketch.cfg" \
    "$CORE/firmwares/zephyr-arduino_uno_q_stm32u585xx.elf" \
    var/firmware/amelie_mcu.ino.elf-zsk.bin
```

Il primo file dopo `-f …cfg` è il loader, il secondo lo sketch: lo script
OpenOCD del core riscrive il loader solo se è diverso da quello che c'è, e
scrive sempre lo sketch.

### Sketch e loader vanno in coppia

Sul microcontrollore della UNO Q gira un *loader* Zephyr che, all'accensione,
avvia lo sketch da un indirizzo fisso della flash. Il loader e quell'indirizzo
cambiano con la versione del core: nel core 0.52.0 lo sketch sta a
`0x80F0000`, nel core 1.0.0 a `0x8100000`. Quando App Lab si aggiorna porta
sul microcontrollore il loader della sua versione; uno sketch caricato da solo,
compilato con un core diverso, finisce dove quel loader non guarda.

Il sintomo è preciso: il caricamento **riesce**, il LED del Modulino Distance è
acceso, ma il microcontrollore non risponde. `/stato` dice `mcu: false`, il
giornale dell'applicazione ripete «il router risponde ma lo sketch di Amelie
non c'è», e la luce non si accende. Senza sensore di distanza il dispositivo
non vede nessuna bottiglia.

Il rimedio è ricaricare sketch e loader insieme, con lo stesso core:
`bash scripts/firmware.sh --sempre`. Per questo lo script carica sempre i due
file insieme e, dopo ogni aggiornamento di App Lab, conviene rilanciarlo.

`arduino:zephyr:unoq` è il nome completo della scheda per `arduino-cli` (il
FQBN, *fully qualified board name*).

### Da un altro computer, in rete

Su un computer nella stessa rete della board, con core e libreria installati
come sopra:

```bash
arduino-cli board list      # mostra la board e il suo indirizzo di rete
arduino-cli compile -b arduino:zephyr:unoq --upload -p <indirizzo-della-board> firmware/amelie_mcu
```

In questo modo `remoteocd` si collega alla board in SSH, il terminale remoto
cifrato, per eseguirvi OpenOCD, e chiede la **password dell'utente `arduino`**.
Il comando va quindi lanciato da un terminale interattivo: da uno script non
interattivo il caricamento fallisce con *«user input not supported in non
interactive mode»*. Per caricare senza password si usano, sulla board,
`install.sh` o i comandi della sezione precedente.

### Compilarlo senza la board

Con core e libreria installati come sopra, lo sketch si compila su qualunque
computer, senza board e senza moduli:

```bash
arduino-cli compile -b arduino:zephyr:unoq firmware/amelie_mcu
```

Per caricarlo serve la board.

## I metodi esposti a Linux

| metodo | parametri | restituisce |
|---|---|---|
| `set_anello` | r, g, b (0-255), luminosità (0-100) | `true`; tutti gli otto LED dello stesso colore, applicato al giro successivo di `loop()`, se l'anello è presente |
| `set_luce` | due colori come interi `0xRRGGBB`, luminosità (0-100) | `true`; i LED pari del primo colore e i dispari del secondo. È la luce di Amelie: bianco e giallo |
| `distanza` | — | l'ultima misura in millimetri, oppure `-1` se l'ultima misura non è valida o il sensore non è presente |
| `moduli` | — | quali moduli vede, come somma di bit: **1** l'anello, **2** il sensore (da 0 a 3) |
| `versione` | — | la versione del **protocollo**: `3` |

C'è poi una **notifica**, cioè un messaggio che il microcontrollore manda di sua
iniziativa, senza attendere risposta: `bottiglia(presente, mm)`, mandata quando
`presente` cambia, al massimo dieci volte al secondo. `presente` è vero con una
misura valida sotto i 10 cm. L'applicazione su Linux non la usa: interroga
`distanza` e decide lei se la bottiglia c'è, con un'isteresi, cioè con due
soglie distinte per l'arrivo e per l'uscita e con più letture di fila prima di
cambiare idea, così una misura che oscilla vicino a una soglia non fa scattare
niente (la classe `Presenza` in `amelie.bridge`).

`versione` non dice quale build gira: dice **che cosa significano le
risposte**, e cambia solo quando cambia un significato, non quando cambia il
codice. Per questo `Ponte.moduli()` chiede prima la versione e, se non è quella
attesa (`PROTOCOLLO_ATTESO` in `amelie.bridge`), risponde «non vedo niente» e lo
scrive nel log: un Linux e un microcontrollore con due protocolli diversi
leggerebbero gli stessi bit con due significati, e «non lo so» è meglio di una
risposta rovesciata a chi sta montando.

Tre metodi servono alla diagnosi, e li usa `scripts/bus.py`:

| metodo | parametri | restituisce |
|---|---|---|
| `scansiona` | blocco 0-3 | una maschera di 32 bit: il bit *i* vale 1 se risponde l'indirizzo blocco × 32 + *i*. Quattro chiamate coprono tutti gli indirizzi a 7 bit; quelli riservati, sotto `0x08` e sopra `0x77`, non si provano |
| `stato_tof` | — | dove si è fermato l'avvio del sensore: `0` riuscito, `-1` mai tentato, da `1` a `6` il passo che non è andato (l'elenco è nello sketch) |
| `registro_tof` | 0-5 | un registro grezzo del sensore (l'elenco è nello sketch); `-1` se il sensore non risponde alla lettura, `-2` se il sensore non è presente, `-3` se il numero è fuori da 0-5 |

## All'accensione

Uno sketch Arduino ha due funzioni fisse: `setup()`, eseguita una volta
all'avvio, e `loop()`, ripetuta all'infinito.

Il microcontrollore è pronto in pochi millisecondi. Il collegamento con Linux
arriva quando parte `arduino-router`, una quarantina di secondi dopo
l'accensione, e fino ad allora `Bridge.begin()` aspetta e `setup()` non finisce.
Nel frattempo l'anello **respira in bianco e giallo**, per dire che il
dispositivo è acceso: lo sketch lo accende prima di mettersi in attesa, e un
thread separato lo fa respirare durante l'attesa. Il respiro si ferma al primo
comando di luce da Linux, che l'applicazione manda appena è pronta; da lì la
luce la decide lei.

Come prima cosa, a ogni avvio, il firmware libera il bus I²C con
`i2c_recover_bus()`. Un modulo resettato a metà di un byte può restare convinto
di trasmettere e tenere SDA a zero: allora nessuna transazione parte, nemmeno
verso l'anello, e il dispositivo sembra senza firmware. La manovra di recupero
batte il clock finché il modulo rilascia la linea, poi manda uno STOP. Senza di
essa servirebbe togliere corrente a tutto: ricaricare il firmware riavvia il
microcontrollore, non il modulo che tiene giù la linea.

## Tre modi di fallire in silenzio, e come sono evitati

**Un modulo che non risponde non deve fermare `setup()`.** Se `setup()` non
finisce, Linux non vede mai i metodi: il router accetta la connessione e ogni
chiamata risponde *«method not available»*, lo stesso sintomo di un firmware
assente. Per questo ogni transazione I²C dello sketch ha un'attesa limitata, i
moduli si **cercano** invece di darli per presenti, e un modulo è presente solo
dopo una scrittura o una lettura andata a buon fine. `Bridge.provide()` arriva
appena il collegamento è pronto, e nessun modulo può impedirlo.

**Un gestore non chiama il ponte.** Un gestore è la funzione che lo sketch
registra con `Bridge.provide()` e che Linux chiama per nome. Chiamare
`Bridge.call()` o `Monitor.print()` (la stampa di messaggi verso Linux) dentro
un gestore manda in stallo il canale. I gestori dello sketch scrivono in una
variabile che poi applica `loop()`, o al più leggono il bus sotto un lucchetto,
un mutex di Zephyr: girano su un thread della libreria, non dentro `loop()`, e
due thread sullo stesso bus mescolerebbero le risposte.

**Un `.ino` non è un `.cpp`.** Arduino genera i prototipi di tutte le funzioni e
li inserisce subito prima della prima definizione di funzione del file: un tipo
dichiarato dopo quel punto non esiste ancora quando il prototipo lo nomina, e il
compilatore dà un `has not been declared` su una riga che sta *sotto* la
dichiarazione e sembra corretta. Per questo nello sketch tutti i tipi e le
variabili stanno in cima, e le funzioni dopo.

## Alimentazione

Gli otto LED si alimentano dal cavetto Qwiic, da 28 AWG, a 3,3 V, sullo
stesso bus del sensore di distanza. La luce di Amelie li tiene **al massimo**
per tutto il tempo in cui il dispositivo è acceso, bianchi e gialli alternati
(rossi per un guasto o a batteria scarica). Prima di adottarla si è misurato il
caso peggiore: due minuti con tutti gli otto LED **bianchi** al massimo, e il
sensore di distanza ha risposto 1124 volte su 1124, con i due moduli sempre
visti. Bianco e giallo alternati consumano meno di così.

Se la tensione a 3,3 V cedesse, cadrebbe anche l'I²C, e il guasto sembrerebbe
dei moduli: se compare con un anello diverso da quello del progetto, la prima
cosa da provare è una luminosità più bassa (`LUCE` in `src/amelie/bridge.py`).
Il prezzo della luce al massimo si paga in batteria: circa un watt in più,
che la stima della batteria conta (`POTENZA_ANELLO_W`).
