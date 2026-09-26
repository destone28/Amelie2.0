# Amelie 2.0

Appoggi una bottiglia di vino e Amelie ne racconta la storia. Una camera legge l'etichetta, l'Arduino UNO Q riconosce il vino e una voce lo descrive: da dove viene, le uve, come si presenta e che sapore ha, con che cosa abbinarlo. Tutto avviene sul dispositivo, in italiano o in inglese, senza connessione a internet.

![Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/insieme.png)

Amelie è un dispositivo da tavolo per un'enoteca, un ristorante o una cantina di casa. Funziona a batteria per tutta una serata, ha un solo interruttore e si ricarica da una presa USB-C sul retro. Questa guida spiega come costruirne uno da zero: i componenti da comprare, la scocca stampata in 3D, i collegamenti, l'installazione del software su una UNO Q appena uscita dalla scatola e l'uso.

[English: README.md](https://github.com/destone28/Amelie2.0/blob/main/README.md)

## Che cosa fa Amelie

Un ospite posa una bottiglia sul piatto rotondo dietro lo schermo, con l'etichetta rivolta verso lo schermo: la camera la guarda dal retro della torre che lo regge. Un sensore di distanza sotto il piatto si accorge della bottiglia, la luce accanto alla camera cambia colore e la camera fotografa l'etichetta. La UNO Q legge il testo dell'etichetta, lo cerca in un database di vini italiani e racconta la storia a voce, mentre il testo scorre sul touchscreen da 5" con la frase che la voce sta dicendo messa in evidenza.

Amelie dice sempre quanto è sicura. Quando riconosce il vino esatto comincia con «Questo è il…»; quando riconosce solo la denominazione, la tipologia o il vitigno lo dice e racconta quello. Non nomina mai qualcosa che non ha letto sull'etichetta. Ogni frase del racconto viene dai fatti del database e dal disciplinare di produzione della denominazione. Niente è inventato.

L'ospite può mettere in pausa, tornare indietro o andare avanti, fermare il racconto con la croce, cambiare lingua con una bandiera e regolare il volume. Sollevare la bottiglia per versare non interrompe il racconto, e rimetterla non lo fa ricominciare. Posarne un'altra fa partire subito il racconto nuovo.

Chi gestisce il locale ha un pannello di impostazioni nascosto. Da lì sceglie da dove vengono i racconti:

- **Dall'archivio** (predefinito): composti dai fatti del database. È immediato e non inventa.
- **Carta dei vini**: le vostre descrizioni, da un file CSV con una riga per vino.
- **Scritto sul momento** (sperimentale): un piccolo modello linguistico che gira sulla UNO Q scrive il testo. È più lento e viene controllato sui fatti prima di essere detto.

Quando Amelie non riconosce una bottiglia, il personale può insegnargliela dal touchscreen, scegliendo il vino giusto o scrivendone la descrizione. La volta dopo quella bottiglia si riconosce dalla foto e dalle parole.

## Come funziona

L'Arduino UNO Q ha due cervelli, e Amelie li usa entrambi.

- **Il lato Linux** (Qualcomm QRB2210, Debian) esegue l'applicazione in Python: cattura dalla camera, OCR, ricerca nel database, composizione del racconto, sintesi vocale e la pagina web mostrata a tutto schermo sul display.
- **Il lato microcontrollore** (STM32U585, Zephyr) esegue un piccolo sketch Arduino. Comanda le due schede Modulino sul connettore Qwiic, la luce e il sensore di distanza. Parla con Linux attraverso l'Arduino Router Bridge.

I pezzi principali del software:

- **OCR**: RapidOCR con le reti PP-OCRv6 su ONNX Runtime. Legge l'etichetta da un ritaglio del fotogramma.
- **Riconoscimento**: una cascata che va dalla corrispondenza più precisa alla più generale (vino, tipologia, denominazione, vitigno). Ogni gradino ha la sua soglia di sicurezza, e un'ipotesi si racconta come certa solo quando le parole dell'etichetta la sostengono. Vedi [docs/it/06-riconoscimento.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/06-riconoscimento.md).
- **Il database**: circa 19.000 vini italiani e tutte le 532 denominazioni italiane del vino (DOCG, DOC, IGT), con le loro tipologie, i vitigni e le descrizioni ufficiali di colore, odore e sapore. Si costruisce sulla board dai dati aperti contenuti in questo repository.
- **Il racconto**: frasi composte da un lessico bilingue, riempite solo con fatti e poi controllate parola per parola prima di essere dette. Vedi [docs/it/07-racconto.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/07-racconto.md).
- **La voce**: Piper, con una voce per lingua, senza connessione.
- **Lo schermo**: una pagina web locale in Chromium a tutto schermo, servita da FastAPI.

## Che cosa serve

Elettronica:

- 1 × Arduino UNO Q, 4 GB
- 1 × Arduino Modulino Pixels
- 1 × Arduino Modulino Distance
- 2 × cavi Qwiic
- 1 × hub USB-C UGREEN Revodok 105 (5 in 1: HDMI, ingresso USB-C PD 100 W, tre porte USB-A, cavo USB-C integrato)
- 1 × touchscreen capacitivo IPS HDMI LAFVIN da 5", 800 × 480
- 1 × camera USB InnoMaker U20CAM-1080P con obiettivo M12
- 1 × coppia di piccole casse stereo alimentate via USB (46 × 46 × 28 mm ciascuna), con jack audio da 3,5 mm
- 1 × power bank sottile Charmast da 26.800 mAh
- 1 × cavo da USB-A a USB-C con interruttore in linea, circa 32 cm, con le spine a 90° a entrambe le estremità
- 1 × prolunga USB-C da pannello, femmina-maschio, per la presa di ricarica
- 1 × cavo HDMI corto, dall'hub allo schermo
- 1 × cavo da USB-A a micro-USB, per il touch dello schermo

Pezzi stampati e minuteria:

- gli 11 pezzi stampati in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl), descritti nella sezione successiva
- 18 × viti da legno svasate, 4 × 16 mm
- 16 × viti M2 svasate: 8 × M2 × 5, 6 × M2 × 6, 2 × M2 × 8
- 4 piedini adesivi in gomma

Attrezzi:

- una stampante 3D; per i pezzi della luce serve un filamento traslucido
- i cacciaviti per le viti qui sopra
- un computer con Arduino App Lab, per la prima configurazione della UNO Q
- un cavo USB-C dati, per la prima configurazione

Non serve saldare niente.

## Stampare i pezzi

La scocca è fatta di 11 pezzi. I file STL sono in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl).

- **Base**: la scocca. Regge la torre, il piatto su cui sta la bottiglia e la presa di ricarica.
- **Piastra**: il fondo removibile. Porta il power bank, l'hub, la UNO Q, le casse e l'interruttore.
- **Torre**: il cuneo a 30° che regge lo schermo davanti e l'ottica dietro.
- **Frontale**: la cornice dello schermo.
- **PannelloOttico**: il pannello dentro la torre, con le sedi della camera e del Modulino.
- **VassoioLuce**, **CerchioLuce**, **PlaccaLuce**: i pezzi che portano e diffondono la luce. CerchioLuce è il disco traslucido su cui sta la bottiglia.
- **FermoHub**, **FermoSwitch**, **FermoUno**: i fermi che tengono giù l'hub, l'interruttore e la UNO Q.

![Tutti i pezzi stampati](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/parti.png)

## Collegamenti

Tutto si innesta; non si salda niente.

![Schema dei collegamenti](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/wiring.png)

- **Alimentazione**: il power bank alimenta l'hub attraverso il cavo con l'interruttore, e l'hub alimenta la UNO Q attraverso il suo cavo USB-C integrato. La UNO Q fa da host USB e riceve la corrente dalla stessa porta.
- **Ricarica**: la presa USB-C sul retro è una prolunga che arriva all'ingresso USB-C del power bank. Amelie si ricarica senza aprirla.
- **Video e suono**: HDMI dall'hub allo schermo. Il suono viaggia sull'HDMI ed esce dal jack da 3,5 mm dello schermo, verso le casse.
- **USB**: la camera, il touch dello schermo (micro-USB, per il tocco e l'alimentazione) e l'alimentazione delle casse vanno alle tre porte USB-A dell'hub.
- **Qwiic**: il connettore Qwiic della UNO Q va a un Modulino, e un secondo cavo Qwiic collega l'altro in catena. L'ordine non conta. Collegali prima di accendere: il microcontrollore li cerca all'accensione.

## Preparare la UNO Q

Una UNO Q nuova ha bisogno di un nome, di una password, della rete Wi-Fi e degli ultimi aggiornamenti di sistema. Il modo più semplice è Arduino App Lab. La procedura completa, compreso come farlo da terminale senza App Lab, è in [docs/it/01-preparare-la-uno-q.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/01-preparare-la-uno-q.md).

**Collega la board.** Installa Arduino App Lab sul computer dal sito di Arduino e aprilo. Collega la UNO Q al computer con un cavo USB-C dati. App Lab trova la board e avvia la prima configurazione.

**Nome, password e Wi-Fi.** Chiama la board `amelie`: il resto della guida la raggiunge come `amelie.local`. Scegli una password per l'utente `arduino` e collega la board alla tua rete Wi-Fi.

**Aggiorna.** Accetta gli aggiornamenti che App Lab propone e aspetta che la board si riavvii.

**Verifica di raggiungerla.** Da un terminale sul computer:

```bash
ssh arduino@amelie.local
```

## Installare il software

L'installazione gira sulla UNO Q. Collegato in SSH, clona il repository nella cartella di casa e avvia l'installatore:

```bash
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

Chiede una volta la password dell'utente `arduino`, poi lavora da solo per circa un'ora, quasi tutta spesa a compilare llama.cpp. Mostra dodici passi numerati:

- i pacchetti di sistema (Chromium, Python, gli strumenti di compilazione)
- una correzione per la scheda audio all'avvio
- l'ambiente Python, con le versioni esatte di `requirements.txt`
- le reti dell'OCR
- llama.cpp, il motore del modello linguistico sperimentale
- le due voci e il modello linguistico, controllati con le loro somme SHA-256
- il database dei vini, costruito dai dati aperti in `data/sources`
- il firmware del microcontrollore, compilato e caricato dalla board stessa
- i servizi di sistema, la sessione a tutto schermo e un avvio silenzioso

Quando finisce, riavvia la board:

```bash
sudo reboot
```

L'installatore si può rilanciare quando si vuole: salta ciò che è già fatto. Per aggiornare Amelie in seguito: `cd ~/amelie && git pull && bash scripts/install.sh`.

Ogni passo è spiegato in [docs/it/02-installazione.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/02-installazione.md).

## Montare

La scocca si chiude in un ordine preciso, perché le viti che tengono la torre alla base si avvitano dall'interno della base, e si raggiungono solo finché il fondo è aperto. La guida completa, con la posizione di ogni componente e di ogni vite, è in [docs/it/03-montaggio.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/03-montaggio.md).

**Prima, la messa a fuoco della camera.** L'obiettivo M12 esce dalla fabbrica a fuoco lontano, e l'etichetta sta a circa 100 mm. Collega la camera a un computer come una webcam e ruota l'obiettivo finché le scritte piccole di un'etichetta a 10 cm sono nitide.

**Fase A, il fondo (Piastra).** Le due casse vanno negli angoli anteriori, membrana in basso. Il power bank va capovolto al centro, porte verso il retro. L'hub va nella culla a destra, cavo integrato verso il retro e porta HDMI verso il fronte, tenuto dal FermoHub. La UNO Q sta su quattro perni fra le casse, USB-C verso il retro, tenuta dal FermoUno. L'interruttore sta nel vano posteriore, levetta attraverso il fondo, chiuso dal FermoSwitch. Poi si collegano il cavo con l'interruttore (Output 3 del power bank nella porta USB-C PD dell'hub), il cavo dell'hub alla UNO Q, l'USB delle casse, il primo cavo Qwiic e la prolunga di ricarica, e si posa il VassoioLuce a ponte sul power bank.

**Fase B, la torre (Torre).** La PlaccaLuce traslucida chiude la finestra della luce sul retro della torre. La camera, ruotata di 90°, e il Modulino Pixels si avvitano al pannello ottico, che poi si avvita dentro la torre. Lo schermo va nella rampa con i cavi HDMI, touch e audio già collegati, e il Frontale lo chiude.

**Fase C, la scocca (Base).** Il Modulino Distance si avvita sotto il disco traslucido (CerchioLuce), che si blocca nella Base con un sesto di giro. La presa di ricarica scatta nella parete posteriore. La torre si avvita alla Base dall'interno.

**Fase D, la chiusura.** Si collegano HDMI, touch, camera e la catena Qwiic, si accende e si controllano schermo, voce e bottiglia, poi si avvita il fondo alla Base e si attaccano i piedini.

![Esploso di Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/esploso.png)

## La prima accensione

Accendi Amelie. Lo schermo mostra il marchio di Amelie mentre le voci si caricano, poi la schermata d'attesa: un calice, «Ogni bottiglia ha una storia.» e tre passi, **Scegli** una bottiglia, **Posa** la bottiglia su Amelie, **Ascolta** la sua storia.

Controlla le tre cose che possono andare storte montando l'hardware:

- **Suono**: tocca la bandiera già evidenziata, in alto a destra. Amelie annuncia la lingua a voce. Se non la senti, controlla il jack fra lo schermo e le casse, e l'alimentazione USB delle casse.
- **Moduli**: mentre Amelie aspetta la luce è ambra. Posa una bottiglia: lo schermo deve dire «Fammi guardare…» e la luce deve cambiare colore. Se la luce resta spenta, o posando la bottiglia non succede niente, un Modulino non viene visto: controlla i cavi Qwiic, poi spegni e riaccendi.
- **Camera**: tieni il dito sull'angolo in basso a destra dello schermo per tre secondi per aprire le impostazioni, e accendi **Debug camera**. Il video mostra il riquadro che va all'OCR, con l'etichetta al centro, e il testo letto.

Per un controllo completo in SSH:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Ogni prova, e che cosa fare quando fallisce, è in [docs/it/04-collaudo.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/04-collaudo.md).

## Usare Amelie

Per gli ospiti non c'è niente da imparare. Si posa la bottiglia sul piatto con l'etichetta rivolta verso lo schermo, e si ascolta. I comandi sotto il testo ricominciano da capo, tornano indietro, mettono in pausa o vanno avanti. La croce in basso a sinistra ferma il racconto. Le bandiere in alto a destra cambiano lingua, e l'altoparlante in alto a sinistra cambia il volume. Quando il racconto è finito e la bottiglia viene tolta, Amelie torna alla lingua di casa, pronta per il tavolo successivo.

Per il personale, le impostazioni si aprono tenendo il dito sull'angolo in basso a destra dello schermo per tre secondi. Contengono:

- **Come racconta**: la fonte dei racconti (Dall'archivio, Carta dei vini, Scritto sul momento).
- **Aggiungi correzioni**: mostra «Correggi la bottiglia» su ogni racconto, e «Mi aiuti a riconoscerla» sulle bottiglie che Amelie non conosce. Una correzione può indicare il vino giusto dell'archivio, oppure portare una descrizione scritta da voi, in una lingua o in tutte e due.
- **Debug camera**: che cosa vede e che cosa legge la camera, per regolare l'inquadratura.
- **Batteria ricaricata**: mostra la stima della batteria; si tocca dopo la ricarica, così la stima riparte da piena.
- **Ripristina il funzionamento**: rimette in moto camera, lettura e voce senza spegnere, se «Qualcosa non ha funzionato» continua a ripresentarsi.
- **Stato tecnico**: microcontrollore, moduli, camera, voce e modo a colpo d'occhio.

Tutto è descritto in [docs/it/05-uso.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/05-uso.md).

## La vostra carta dei vini

La carta dei vini è un file CSV, `vini.csv`, nella cartella del progetto sulla board. Ha una riga d'intestazione e una riga per vino:

```csv
titolo,descrizione,titolo_en,descrizione_en
"Barolo DOCG","La descrizione in italiano, letta così com'è.","Barolo DOCG","The English description."
```

`titolo` e `descrizione` sono obbligatorie; le due colonne inglesi sono facoltative. Il repository contiene una carta d'esempio di denominazioni e tipologie italiane, solo in italiano. Dopo aver modificato il file, riavvia l'applicazione con `sudo systemctl restart amelie` e scegli **Carta dei vini** nelle impostazioni. Quando un vino non è nella carta, Amelie lo racconta dall'archivio.

## Quando qualcosa non va

- **Lo schermo resta nero**: controlla il cavo HDMI e il cavo micro-USB dello schermo. Lo schermo è pilotato a 1280 × 720, una modalità che scala sul suo pannello da 800 × 480; `systemctl status amelie-display` dice quale modalità è stata impostata.
- **Niente suono**: vedi i controlli della prima accensione. Il suono ha bisogno dello schermo acceso: Amelie lo tiene sempre sveglio.
- **Le bottiglie non vengono mai notate**: il sensore di distanza non viene visto. Controlla la catena Qwiic, spegni e riaccendi.
- **Le etichette si leggono male**: accendi Debug camera e controlla che l'etichetta sia centrata e nitida.
- **Qualunque altra cosa**: prova «Ripristina il funzionamento» nelle impostazioni. Il registro dell'applicazione si legge con `journalctl -u amelie`.

## Documentazione

La documentazione completa è in italiano in [docs/it](https://github.com/destone28/Amelie2.0/tree/main/docs/it) e in inglese in [docs/en](https://github.com/destone28/Amelie2.0/tree/main/docs/en):

- [01 Preparare la UNO Q](https://github.com/destone28/Amelie2.0/blob/main/docs/it/01-preparare-la-uno-q.md)
- [02 Installare il software](https://github.com/destone28/Amelie2.0/blob/main/docs/it/02-installazione.md)
- [03 Montare](https://github.com/destone28/Amelie2.0/blob/main/docs/it/03-montaggio.md)
- [04 Collaudare](https://github.com/destone28/Amelie2.0/blob/main/docs/it/04-collaudo.md)
- [05 Usare](https://github.com/destone28/Amelie2.0/blob/main/docs/it/05-uso.md)
- [06 Come si riconosce un'etichetta](https://github.com/destone28/Amelie2.0/blob/main/docs/it/06-riconoscimento.md)
- [07 Come si racconta](https://github.com/destone28/Amelie2.0/blob/main/docs/it/07-racconto.md)
- [08 Attribuzioni e licenze](https://github.com/destone28/Amelie2.0/blob/main/docs/it/08-attribuzioni.md)

Lo sketch del microcontrollore è documentato in [firmware/amelie_mcu/README.md](https://github.com/destone28/Amelie2.0/blob/main/firmware/amelie_mcu/README.md).

## Crediti e licenze

Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

- Il codice è distribuito sotto GNU General Public License v3.0 o successiva ([LICENSE](https://github.com/destone28/Amelie2.0/blob/main/LICENSE)).
- Documentazione, immagini, schemi e file 3D sono distribuiti sotto Creative Commons Attribuzione 4.0 ([LICENSE-DOCS.md](https://github.com/destone28/Amelie2.0/blob/main/LICENSE-DOCS.md)).

Il database dei vini si costruisce da dati aperti ed è distribuito sotto Open Database License 1.0. Le fonti sono:

- Candiago et al., «Quality wines in Italy and France: PDO specifications» (figshare, CC BY 4.0);
- de Azambuja, Morais e Filipe, «X-Wines: A Wine Dataset for Recommender Systems and Machine Learning», Big Data and Cognitive Computing 2023;
- il registro UE delle indicazioni geografiche e i documenti unici, © Unione europea (CC BY 4.0).

Le voci, le reti dell'OCR, il modello linguistico e il carattere hanno licenze proprie, tutte elencate in [docs/it/08-attribuzioni.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/08-attribuzioni.md).
