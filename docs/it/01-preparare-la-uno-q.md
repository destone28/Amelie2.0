# Preparare la UNO Q

Una Arduino UNO Q appena uscita dalla scatola ha già il suo sistema operativo,
Debian, sulla memoria interna. Prima di installare Amelie le servono quattro
cose: un nome, una password, la rete Wi-Fi e gli ultimi aggiornamenti. Questa
guida le fa in due modi, con Arduino App Lab oppure da terminale, e finisce con
la board raggiungibile in SSH come `amelie.local`.

## Che cosa serve

- la UNO Q, **da sola**: niente hub, niente schermo, niente Modulino;
- un computer con Windows, macOS o Linux;
- un cavo USB-C **dati**, non solo di ricarica (è la prima causa di una board
  che il computer non vede), collegato a una porta del computer, non a un hub;
- il nome e la password della rete Wi-Fi.

La UNO Q ha una sola porta USB-C, e quella porta lavora in due modi:

- **collegata al computer** fa da periferica: prende corrente dal computer e si
  lascia configurare. È il modo di questa guida;
- **collegata all'hub**, come nel dispositivo montato, fa da host: alimenta
  schermo, camera e casse e riceve corrente dal power bank attraverso l'hub. Da
  lì in poi la si raggiunge solo in Wi-Fi.

Le due cose non stanno insieme: quando la board è nell'hub, il computer non la
vede via cavo. Per questo la rete si configura adesso.

## Con Arduino App Lab

1. Scarica Arduino App Lab da <https://www.arduino.cc/en/software/> e
   installalo. Su Linux segui anche le istruzioni per le regole udev della
   pagina di download: senza, il sistema non dà all'utente il permesso di
   parlare con la board.
2. Apri App Lab e collega la UNO Q con il cavo USB-C. Dopo qualche secondo la
   board compare fra i dispositivi; selezionala.
3. App Lab avvia la prima configurazione. Quando chiede il **nome della
   board**, scrivi `amelie`: il resto della documentazione la raggiunge come
   `amelie.local`. Scegli la disposizione della tastiera, la rete **Wi-Fi** e
   una **password** per l'utente `arduino`. Tienila da parte: serve per l'SSH e
   per l'installazione.
4. Se App Lab propone un **aggiornamento** della board, accettalo e aspetta
   che finisca: la board si riavvia da sola.

Non serve creare né avviare nessuna app di App Lab: Amelie ha il suo firmware e
il suo servizio, e l'installatore lo carica da sé.

## Da terminale, senza App Lab

Serve `adb`, lo strumento Android per il debug via USB (su Debian e Ubuntu
`sudo apt install adb`; su macOS e Windows è nel pacchetto «platform-tools» di
Android). Con la board collegata al computer:

```bash
adb devices          # la board deve comparire come «device»
adb shell            # una shell sulla board, come utente arduino
```

Dalla shell della board:

```bash
# La rete Wi-Fi
sudo nmcli device wifi connect "NOME-DELLA-RETE" password "PASSWORD-DELLA-RETE"

# Il nome: la board risponderà come amelie.local
sudo arduino-app-cli system set-name amelie

# La password dell'utente arduino
passwd

# Gli aggiornamenti del sistema e dei pacchetti Arduino
sudo arduino-app-cli system update --yes

# L'accesso via SSH
sudo systemctl enable --now ssh

sudo reboot
```

## Verificare

Dal computer, con la board ancora collegata o già staccata:

```bash
ping -c 3 amelie.local
ssh arduino@amelie.local
```

La prima volta SSH chiede di confermare l'impronta della board, poi la
password. Dentro, controlla spazio e sistema:

```bash
df -h /home          # servono almeno 4 GB liberi
cat /etc/os-release  # Debian GNU/Linux 13 (trixie)
```

Se `amelie.local` non risponde, il computer non risolve i nomi `.local`
(capita su alcune reti aziendali e su Windows senza Bonjour): usa l'indirizzo
IP, che si legge nella shell della board con `hostname -I`.

Per non scrivere la password ogni volta, copia sulla board la tua chiave SSH:

```bash
ssh-copy-id arduino@amelie.local
```

## Se la board non si avvia, o vuoi ripartire da zero

Non serve quasi mai. Il sistema di fabbrica va bene, e tutto quello che Amelie
installa sta in `/home/arduino`, dove c'è spazio in abbondanza. Se però la board
non si avvia più, o vuoi riportarla com'era uscita dalla fabbrica, Arduino
spiega come riscrivere l'immagine del sistema con Arduino Flasher CLI:
<https://docs.arduino.cc/tutorials/uno-q/update-image/>. Riscrivere l'immagine
cancella tutto quello che c'è sulla board; dopo si riparte da questa pagina.

## Il passo successivo

[Installare il software](02-installazione.md).
