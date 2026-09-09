# Firmware del microcontrollore

Va caricato sullo **STM32U585** della UNO Q, non sul lato Linux. Il connettore
Qwiic è cablato sull'I²C4 dell'MCU: l'anello di LED e il sensore di distanza li
vede solo lui, e Linux ci parla attraverso il router.

## Due moduli, e nessun indirizzo da riprogrammare

| modulo | indirizzo | a cosa serve |
|---|---|---|
| **Modulino Pixels** | `0x36` | l'anello sotto la bottiglia, e la luce dello scatto |
| **Modulino Distance** | `0x29` | sente che la bottiglia è arrivata |

Entrambi gli indirizzi sono quelli di fabbrica: **non c'è niente da
riprogrammare prima di montare.**

> **Cosa c'era prima.** Un secondo Pixels faceva da flash per la camera. Poiché
> i Pixels nascono *tutti* a `0x36`, il secondo andava riprogrammato una volta
> per sempre con lo sketch `AddressChanger`, togliendo e ridando corrente — e da
> fuori i due moduli restano identici, quindi chi scambiava i cavetti si
> ritrovava il flash sotto la bottiglia e l'anello puntato sull'etichetta. Era
> il passo più fragile di tutto l'assemblaggio ed è sparito insieme al modulo.
>
> L'etichetta si illumina lo stesso: l'anello sale a bianco per la durata della
> raffica e poi torna al colore del lavoro. E il grosso del segnale non l'hanno
> mai dato i LED — viene dalla posa lunga a guadagno zero che questa geometria
> si può permettere, perché bottiglia e camera sono ferme entrambe (vedi
> `amelie.capture`).

L'indirizzo `0x36` è quello **hardware**. Il datasheet chiama `0x6C` l'indirizzo
"Modulino": passare quello fallisce in **silenzio**, perché `begin()` ritorna
comunque `true`.

## Le librerie

Servono `Arduino_RouterBridge` e `Arduino_Modulino`:

```bash
arduino-cli lib install Arduino_RouterBridge Arduino_Modulino
```

Da App Lab, invece, le sette dipendenze di `Arduino_Modulino` **non** si
risolvono da sole, perché costruisce per profilo: vanno installate a mano dal
Library Manager, cercandole per nome **senza estensione**
(`Arduino_LTR381RGB`, non `Arduino_LTR381RGB.h`).

## Caricarlo

```bash
arduino-cli board list      # dà l'indirizzo di rete, es. <indirizzo-della-board>
arduino-cli compile -b arduino:zephyr:unoq --upload -p <indirizzo> firmware/amelie_mcu
```

Va lanciato **da un terminale vero**, collegandosi alla board: chiede la
password dell'utente `arduino`, e da uno script non interattivo fallisce con
*«user input not supported in non interactive mode»*.

Non è aggirabile. L'upload passa da `remoteocd`, che apre una connessione SSH
verso la board e ci esegue OpenOCD, e quel programma accetta **solo la
password**: `ssh: unable to authenticate, attempted methods [none password]`.
Una chiave già configurata non serve, e `--upload-field password=` vuoto viene
rifiutato. La compilazione invece non chiede niente.

## Compilarlo senza la board

Serve più spesso di quanto sembri: la board è un pezzo solo, si stacca, e un
firmware che non compila non lo si scopre volentieri con i Modulino già in mano.

```bash
arduino-cli core install arduino:zephyr          # ~1,2 GB, una volta sola
arduino-cli lib install Arduino_RouterBridge Arduino_Modulino
arduino-cli compile -b arduino:zephyr:unoq firmware/amelie_mcu
```

Il caricamento, quello sì, vuole la board.

## Il tetto che non è quello che sembra

App Lab carica il binario in SRAM con un limite di **131.072 byte**, e oltre
quella soglia uno sketch **compila senza errori** e poi va in bus fault al
caricamento, senza alcuna diagnostica utile.

Da lì era nata l'idea di includere solo gli header dei Modulino usati invece di
`<Modulino.h>`, che ne tira dentro sette. **L'idea era sbagliata due volte.**
Primo: `Arduino_Modulino` 0.9.0 non espone `ModulinoPixels.h` né
`ModulinoDistance.h`, quindi lo sketch non compilava affatto — e non se ne era
accorto nessuno, perché non era mai stato compilato. Secondo: il tetto dei
131 KB riguarda la via di caricamento di App Lab, non `arduino-cli --upload`,
che scrive la memoria dello STM32U585.

**Ma la dimensione dipende dalla catena di compilazione, e parecchio.** Misurata
due volte sullo stesso sorgente:

| dove | programma | RAM | tetto dichiarato |
|---|---|---|---|
| sulla board | 33.000 | 3.772 | 1.966.080 / 523.624 |
| su PC, core `arduino:zephyr` 1.0.0, Modulino 0.9.0, RouterBridge 0.4.3 | 115.864 (14 %) | 47.272 (18 %) | 786.432 / 262.144 |

Non è un errore di misura: cambia anche il **tetto**, quindi le due catene
partizionano diversamente. La conseguenza pratica è una sola: **il numero va
misurato, non ricordato**, e se un domani si torna a caricare da App Lab i
115.864 byte sono già vicini ai 131.072 — con `arduino-cli` non lo sono affatto.

## I metodi esposti a Linux

| metodo | parametri | restituisce |
|---|---|---|
| `set_anello` | r, g, b, luminosità | `true` |
| `distanza` | — | millimetri, oppure `-1` se la misura non è valida |
| `moduli` | — | somma di bit: **1** anello, **2** sensore |
| `versione` | — | la versione del **protocollo**: oggi `2` |

E una notifica: `bottiglia(presente, mm)` a ogni cambiamento.

`versione` non dice quale build gira, dice **che cosa significano le risposte**.
Si alza quando cambia un significato, non il codice. Alla 2 il secondo Pixels è
stato tolto e il bit 2 di `moduli()` è passato da «flash» a «sensore», mentre il
sensore lasciava il bit 4: un Linux alla 2 che legge un MCU alla 1 direbbe
«sensore presente» con il flash collegato e «sensore assente» con il sensore.
Perciò `Ponte.moduli()` chiede prima la versione, e se non è quella attesa
risponde «non vedo niente» e lo scrive nel log — meglio «non lo so» che una
risposta rovesciata a chi ha i cavetti in mano.

`moduli` è lo strumento del montaggio: si collega un pezzo per volta e si chiede
al dispositivo se lo vede, invece di dedurlo da un LED che resta spento per una
qualsiasi di cinque ragioni. Il firmware sonda il bus **ogni due secondi**,
quindi i moduli si possono collegare a dispositivo acceso.

## Due modi di fallire in silenzio, e come sono evitati

**I metodi si dichiarano prima di toccare l'I²C.** Se un Modulino non risponde —
non ancora collegato, un cavetto staccato, un indirizzo sbagliato — `begin()`
può **non tornare**, `setup()` non finisce, e Linux non vede mai i metodi. Il
sintomo è identico a un firmware assente: il router accetta la connessione e
ogni chiamata dice *«method not available»*. È successo, e ci si perde un'ora a
cercare nel posto sbagliato. Perciò `Bridge.provide()` viene **prima** di
`Wire1.begin()`, e i moduli si **cercano** invece di darli per presenti.

**Un `.ino` non è un `.cpp`.** Arduino genera i prototipi di tutte le funzioni e
li infila subito prima della prima definizione di funzione del file: un tipo
dichiarato dopo quel punto non esiste ancora quando il prototipo lo nomina, e si
prende un `has not been declared` su una riga che sta *sotto* la dichiarazione e
sembra corretta. Per questo nello sketch tutti i tipi e le variabili stanno in
cima, e le funzioni dopo.

## Alimentazione

Otto LED su un cavetto Qwiic da 28 AWG. Fuori dalla raffica l'anello sta fra
**22 e 30** di luminosità — 22 in attesa, 30 negli stati che chiedono qualcosa —
e sale a **90 in bianco** per la durata della raffica.

Che non è un lampo: sono **circa 1,7 secondi**, perché `Camera.scatta` apre il
device, aspetta che la luce si assesti, butta cinque fotogrammi e ne legge altri
cinque. Con un solo Pixels il picco è circa la metà di quello di prima, ma dura
molto più di quanto suggerisca la parola «flash»: non tenerlo acceso al massimo
«per vedere se funziona». Se il rail 3,3 V cede, cade anche l'I²C e sembra un
guasto del modulo.
