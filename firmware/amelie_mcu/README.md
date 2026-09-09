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

Va lanciato **da un terminale vero**, collegandosi alla board: il protocollo di
rete può chiedere la password dell'utente `arduino`, e da uno script
non interattivo fallisce con *«user input not supported in non interactive
mode»*.

## Il tetto che non è quello che sembra

App Lab carica il binario in SRAM con un limite di **131.072 byte**, e oltre
quella soglia uno sketch **compila senza errori** e poi va in bus fault al
caricamento, senza alcuna diagnostica utile.

Da lì era nata l'idea di includere solo gli header dei Modulino usati invece di
`<Modulino.h>`, che ne tira dentro sette. **L'idea era sbagliata due volte.**
Primo: `Arduino_Modulino` 0.9.0 non espone `ModulinoPixels.h` né
`ModulinoDistance.h`, quindi lo sketch non compilava affatto — e non se ne era
accorto nessuno, perché non era mai stato compilato. Secondo: **misurato** con
`arduino-cli` sul core `arduino:zephyr`, `<Modulino.h>` compreso, il binario
occupa 33.000 byte di programma su 1.966.080 e 3.772 di RAM su 523.624. L'uno
per cento. Il tetto dei 131 KB riguarda un'altra via di caricamento, non questa.

## I metodi esposti a Linux

| metodo | parametri | restituisce |
|---|---|---|
| `set_anello` | r, g, b, luminosità | `true` |
| `distanza` | — | millimetri, oppure `-1` se la misura non è valida |
| `moduli` | — | somma di bit: **1** anello, **2** sensore |

E una notifica: `bottiglia(presente, mm)` a ogni cambiamento.

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
