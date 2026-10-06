# Preparare la UNO Q

Una Arduino UNO Q nuova esce dalla fabbrica con il suo sistema operativo,
Debian Linux, già installato sulla memoria interna. Prima di installare Amelie le
servono cinque cose:

- un **nome**, con cui la si raggiunge in rete;
- una **password** per l'utente `arduino`: quella di fabbrica va cambiata alla
  prima configurazione;
- la **rete Wi-Fi**;
- gli **aggiornamenti** dei pacchetti Arduino;
- la **modalità rete** accesa: è lei che accende l'SSH, il terminale remoto con
  cui si lavora sulla board dal computer, e che fa rispondere la board al suo
  nome seguito da `.local`.

Questa guida le fa in due modi, con Arduino App Lab oppure da terminale, e
finisce con la board raggiungibile in SSH come `amelie.local`.

## Che cosa serve

- la UNO Q, **da sola**: niente hub, niente schermo, niente Modulino;
- un computer con Windows, macOS o Linux;
- un cavo USB-C **dati**, non solo di ricarica (è la prima causa di una board
  che il computer non vede), collegato direttamente a una porta del computer,
  non a un hub;
- il nome e la password della rete Wi-Fi.

La UNO Q ha una sola porta USB-C, e quella porta lavora in due modi:

- **collegata al computer** fa da periferica: prende la corrente dal computer e
  si lascia configurare. È il modo di questa guida;
- **collegata all'hub**, come nel dispositivo montato, fa da host: alimenta
  schermo, camera e casse e riceve la corrente dal power bank attraverso l'hub.
  Da lì in poi la si raggiunge solo in Wi-Fi.

Le due cose non stanno insieme: quando la board è nell'hub, il computer non la
vede via cavo. Per questo la rete si configura adesso.

## Con Arduino App Lab

1. Scarica Arduino App Lab da <https://www.arduino.cc/en/software/> e
   installalo. Su Linux, la pagina di download spiega anche come installare le
   regole udev: senza, il sistema non dà al tuo utente il permesso di parlare
   con la board via USB.
2. Apri App Lab e collega la UNO Q con il cavo USB-C. Dopo qualche secondo la
   board compare fra i dispositivi; selezionala.
3. App Lab avvia la prima configurazione:
   - come **nome della board** scrivi `amelie`: il resto della documentazione
     la raggiunge come `amelie.local`. Se costruisci più di una Amelie, dai a
     ogni board un nome diverso (`amelie2`, `amelie3`…) e usa quel nome al posto
     di `amelie` in tutti i comandi;
   - scegli la disposizione della tastiera e la **rete Wi-Fi**;
   - scegli la **password** dell'utente `arduino`. Tienila da parte: serve per
     l'SSH e per l'installazione.
4. Se App Lab propone un **aggiornamento** della board, accettalo e aspetta che
   finisca.
5. Controlla la **modalità rete** (vedi sotto, «Il terminale della board»):
   `arduino-app-cli system network-mode status` deve rispondere `enabled`.

Non serve creare né avviare nessuna app di App Lab: Amelie ha il suo firmware e i
suoi servizi, e l'installatore li carica da sé.

## Il terminale della board

Per i comandi di questa guida serve un terminale sulla board. Finché la board è
collegata al computer con il cavo USB-C, lo si apre con `adb`, lo strumento
Android per il debug via USB:

- su Debian e Ubuntu si installa con `sudo apt install adb`;
- su macOS e Windows è nel pacchetto «SDK Platform-Tools» di Android,
  <https://developer.android.com/tools/releases/platform-tools>.

Con la board collegata, dal computer:

```bash
adb devices          # la board deve comparire come «device»
adb shell            # apre un terminale sulla board, come utente arduino
```

Si esce dal terminale della board con `exit`. Su Linux, se `adb devices` non
mostra la board o dice «no permissions», mancano le regole udev del punto 1.

## Da terminale, senza App Lab

Gli stessi passi si fanno dal terminale della board (`adb shell`), in
quest'ordine. Il primo imposta la password; poi solo l'accensione della modalità
rete la chiede: per gli altri l'utente `arduino` ha già i permessi.

```bash
# La password dell'utente arduino. Scrivi la password nuova e premi Invio:
# mentre la scrivi non compare niente.
sudo arduino-passwd

# La rete Wi-Fi
nmcli device wifi connect "NOME-DELLA-RETE" password "PASSWORD-DELLA-RETE"

# Il nome: la board risponderà come amelie.local
arduino-app-cli system set-name amelie

# Gli aggiornamenti dei pacchetti Arduino
arduino-app-cli system update --only-arduino --yes

# La modalità rete: accende l'SSH e il nome .local. Chiede la password
# appena scelta.
arduino-app-cli system network-mode enable
arduino-app-cli system network-mode status    # deve rispondere «enabled»
```

## Verificare

Dal computer, con la board ancora collegata o già staccata:

```bash
ping -c 3 amelie.local
ssh arduino@amelie.local
```

La prima volta l'SSH chiede di confermare l'impronta della board: scrivi `yes`.
Poi chiede la password dell'utente `arduino`. Una volta dentro, controlla spazio
e sistema:

```bash
df -h ~              # servono almeno 4 GB liberi
cat /etc/os-release  # Debian GNU/Linux 13 (trixie)
```

Se `amelie.local` non risponde:

- controlla che la modalità rete sia accesa (`arduino-app-cli system
  network-mode status` dal terminale della board);
- alcune reti (Wi-Fi ospiti, reti aziendali) bloccano i nomi `.local`: usa
  l'indirizzo IP della board, che si legge dal suo terminale con `hostname -I`,
  per esempio `ssh arduino@192.168.1.50`;
- su alcuni computer Windows i nomi `.local` non si risolvono: anche lì usa
  l'indirizzo IP.

Per non scrivere la password a ogni collegamento, copia sulla board la tua
chiave SSH (se non ne hai una, `ssh-keygen` la crea):

```bash
ssh-copy-id arduino@amelie.local
```

## Se la board non si avvia, o vuoi ripartire da zero

Non serve quasi mai. Il sistema di fabbrica va bene, e tutto quello che Amelie
installa sta nella cartella `/home/arduino`, che ha una partizione sua, con
spazio in abbondanza. Se però la board non si avvia più, o vuoi riportarla com'era
uscita dalla fabbrica, Arduino spiega come riscrivere l'immagine del sistema con
Arduino Flasher CLI: <https://docs.arduino.cc/tutorials/uno-q/update-image/>.
Riscrivere l'immagine cancella tutto quello che c'è sulla board; dopo si riparte
da questa pagina.

## Il passo successivo

[Installare il software](02-installazione.md).
