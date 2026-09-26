# Firmware del microcontrollore

`amelie_mcu.ino` gira sullo **STM32U585** della UNO Q, non sul lato Linux. Il
connettore Qwiic è cablato sull'I²C4 dell'MCU, che nello sketch si chiama
`Wire1`: l'anello di LED e il sensore di distanza li vede solo il
microcontrollore, e Linux ci parla attraverso il router di Arduino
(`arduino-router`), con la libreria Bridge.

## I due moduli

| modulo | indirizzo | a cosa serve |
|---|---|---|
| **Modulino Pixels** | `0x36` | l'anello sotto la bottiglia; sale a bianco durante la raffica dello scatto |
| **Modulino Distance** | `0x29` | sente che la bottiglia è arrivata |

Entrambi gli indirizzi sono quelli di fabbrica: **non c'è niente da
riprogrammare prima di montare.**

`0x36` è l'indirizzo **hardware**. Il datasheet chiama `0x6C` l'indirizzo
"Modulino" (è lo stesso `0x36` scritto su otto bit): passarlo alla libreria
`Arduino_Modulino` fallisce in **silenzio**, perché `begin()` ritorna comunque
`true`.

I moduli si cercano **all'accensione del microcontrollore**: vanno collegati a
board spenta. Un modulo collegato dopo, o un sensore che smette di rispondere,
risulta assente fino all'accensione successiva o al prossimo caricamento del
firmware.

## Le librerie

Le versioni provate sono il core `arduino:zephyr` 0.52.0,
`Arduino_RouterBridge` 0.4.3 e `Arduino_Modulino` 0.9.0:

```bash
arduino-cli core install arduino:zephyr@0.52.0          # ~1,2 GB, una volta sola
arduino-cli lib install Arduino_RouterBridge@0.4.3 Arduino_Modulino@0.9.0
```

Per compilare lo sketch basta `Arduino_RouterBridge`: `Arduino_Modulino` non è
inclusa, perché ogni transazione I²C è scritta a mano nello sketch (il perché è
nel commento in testa ad `amelie_mcu.ino`). La si installa per i suoi esempi,
comodi per provare un modulo da solo.

## Caricarlo

`scripts/install.sh` lo compila e lo carica. A mano:

```bash
arduino-cli board list      # dà l'indirizzo di rete della board, es. <indirizzo-della-board>
arduino-cli compile -b arduino:zephyr:unoq --upload -p <indirizzo-della-board> firmware/amelie_mcu
```

Il caricamento chiede la **password dell'utente `arduino`**, quindi va lanciato
da un terminale interattivo: da uno script non interattivo fallisce con
*«user input not supported in non interactive mode»*.

Non è aggirabile. L'upload passa da `remoteocd`, che apre una connessione SSH
verso la board e ci esegue OpenOCD, e quel programma accetta **solo la
password**: una chiave SSH già configurata non serve, e `--upload-field
password=` vuoto viene rifiutato. La compilazione invece non chiede niente.

Si carica con `arduino-cli`, non da App Lab.

## Compilarlo senza la board

Con il core e le librerie installati come sopra:

```bash
arduino-cli compile -b arduino:zephyr:unoq firmware/amelie_mcu
```

È il modo di sapere che il firmware compila prima di avere i Modulino in mano.
Il caricamento, quello sì, vuole la board.

## I metodi esposti a Linux

| metodo | parametri | restituisce |
|---|---|---|
| `set_anello` | r, g, b (0-255), luminosità (0-100) | `true` |
| `distanza` | — | millimetri, oppure `-1` se la misura non è valida |
| `moduli` | — | somma di bit: **1** anello, **2** sensore |
| `versione` | — | la versione del **protocollo**: oggi `2` |

E una notifica: `bottiglia(presente, mm)`, mandata a ogni cambiamento e non più
di dieci volte al secondo. `presente` vuol dire una misura valida sotto i 10 cm;
la decisione vera, con la sua isteresi, la prende Linux in `amelie.bridge`.

`versione` non dice quale build gira, dice **che cosa significano le risposte**:
si alza quando cambia un significato, non il codice. Per questo `Ponte.moduli()`
chiede prima la versione, e se non è quella attesa (`PROTOCOLLO_ATTESO` in
`amelie.bridge`) risponde «non vedo niente» e lo scrive nel log: un Linux e un
MCU con due protocolli diversi leggerebbero gli stessi bit con due significati,
e meglio «non lo so» che una risposta rovesciata a chi ha i cavetti in mano.

Tre metodi servono alla diagnosi, e li usa `scripts/bus.py`:

| metodo | parametri | restituisce |
|---|---|---|
| `scansiona` | blocco 0-3 | i bit degli indirizzi che rispondono, 32 per blocco |
| `stato_tof` | — | dove si è fermato l'avvio del sensore: `0` riuscito, `-1` mai tentato, altrimenti il passo |
| `registro_tof` | 0-5 | un registro grezzo del sensore (vedi lo sketch); `-1` se non risponde, `-2` se il sensore non c'è |

## All'accensione

Il microcontrollore è pronto in millisecondi, Linux in una quarantina di
secondi. Nel frattempo l'anello **respira in ambra**, per dire che il
dispositivo è vivo; smette al primo `set_anello` da Linux, e da lì il colore lo
decide l'applicazione.

Prima di tutto il firmware sblocca il bus I²C (`i2c_recover_bus()`): un modulo
resettato a metà di un byte può tenere SDA a zero, e allora nessuna
transazione parte più, nemmeno verso l'anello. Ricaricare il firmware non basta,
perché resetta il microcontrollore e non il modulo che tiene giù la linea.

## Tre modi di fallire in silenzio, e come sono evitati

**Un modulo che non risponde non deve fermare `setup()`.** Se `setup()` non
finisce, Linux non vede mai i metodi: il router accetta la connessione e ogni
chiamata dice *«method not available»*, lo stesso sintomo di un firmware
assente. Per questo ogni transazione I²C dello sketch ha un'attesa limitata, i
moduli si **cercano** invece di darli per presenti, e un modulo è presente solo
dopo una scrittura o una lettura andata a buon fine. `Bridge.provide()` arriva
appena il ponte è pronto, e nessun modulo può impedirlo.

**Un gestore non chiama il ponte.** Chiamare `Bridge.call()` o `Monitor.print()`
dentro un gestore registrato con `provide()` manda in stallo il canale. I
gestori dello sketch scrivono in una variabile che poi applica `loop()`, o al
più leggono il bus sotto un lucchetto: i gestori girano su un thread della
libreria, non nel `loop()`, e due thread sullo stesso bus mescolano le risposte.

**Un `.ino` non è un `.cpp`.** Arduino genera i prototipi di tutte le funzioni e
li infila subito prima della prima definizione di funzione del file: un tipo
dichiarato dopo quel punto non esiste ancora quando il prototipo lo nomina, e si
prende un `has not been declared` su una riga che sta *sotto* la dichiarazione e
sembra corretta. Per questo nello sketch tutti i tipi e le variabili stanno in
cima, e le funzioni dopo.

## Alimentazione

Otto LED su un cavetto Qwiic da 28 AWG. Fuori dalla raffica l'anello sta fra
**22 e 30** di luminosità — 22 in attesa, 30 negli stati che chiedono qualcosa —
e sale a **90 in bianco** per la durata della raffica: secondi, non un lampo.
Non tenerlo acceso al massimo «per vedere se funziona»: se il rail a 3,3 V cede,
cade anche l'I²C, e sembra un guasto del modulo.
