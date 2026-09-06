# Firmware del microcontrollore

Va caricato sullo **STM32U585** della UNO Q, non sul lato Linux.

## Prima di tutto: riprogrammare il secondo anello

I Modulino Pixels nascono **tutti** all'indirizzo `0x36`. Ne servono due a
indirizzi diversi, quindi uno va riprogrammato una volta sola.

1. Collega **un solo** Pixels — quello che diventerà l'illuminatore.
2. Carica `examples/Utilities/AddressChanger` dalla libreria `Arduino_Modulino`.
3. Monitor seriale a 115200, comando: `36 37`
4. **Togli e ridai corrente**: l'indirizzo si scrive in memoria ma diventa
   effettivo al riavvio del modulo.
5. Segnalo con un pennarello sul rettangolo bianco della serigrafia.

Se qualcosa va storto, `0 0` riporta tutto ai valori di fabbrica.

> L'auto-discovery della libreria cerca solo `0x36`: il secondo modulo **non**
> verrà mai trovato da solo, e va costruito con l'indirizzo esplicito. È già
> così nello sketch.

## Le librerie

Servono `Arduino_RouterBridge` e `Arduino_Modulino`. Quest'ultima ha sette
dipendenze che App Lab **non** risolve da sola, perché costruisce per profilo:
vanno installate a mano dal Library Manager, cercandole per nome **senza
estensione** (`Arduino_LTR381RGB`, non `Arduino_LTR381RGB.h`).

## Il tetto che fa fallire in silenzio

App Lab carica il binario in SRAM con un limite di **131.072 byte**. Oltre
quella soglia lo sketch **compila senza errori** e poi va in bus fault al
caricamento, senza alcuna diagnostica utile.

Includere `<Modulino.h>` tira dentro tutte e sette le librerie — due driver ToF
completi, IMU, barometro, umidità, sensore RGB e grafica — ed è il modo più
rapido per superarlo. Lo sketch include quindi **solo** `ModulinoPixels.h` e
`ModulinoDistance.h`.

**Verifica la dimensione dopo ogni modifica**: se si avvicina ai 131.072 byte,
toglierne prima di caricare.

## I metodi esposti a Linux

| metodo | parametri | restituisce |
|---|---|---|
| `set_anello` | r, g, b, luminosità | `true` |
| `set_flash` | r, g, b, luminosità | `true` |
| `distanza` | — | millimetri, oppure `-1` se la misura non è valida |

E una notifica: `bottiglia(presente, mm)` a ogni cambiamento.

## Alimentazione

I due Pixels a piena luminosità assorbirebbero oltre **mezzo ampere** sul rail
3,3 V, passando dai cavetti Qwiic da 28 AWG e in cascata attraverso il PCB del
primo modulo. L'anello resta quindi sotto il 25 % in permanenza, e il flash sale
solo per la frazione di secondo dello scatto.
