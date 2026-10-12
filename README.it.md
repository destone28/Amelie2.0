# Amelie 2.0

Appoggi una bottiglia di vino e Amelie ne racconta la storia. Una camera legge l'etichetta, l'Arduino UNO Q riconosce il vino e una voce lo descrive: da dove viene, le uve, come si presenta e che sapore ha, con che cosa abbinarlo. Tutto avviene sul dispositivo, in italiano o in inglese, senza connessione a internet.

![Amelie 2.0, con la schermata d'attesa](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/amelie.jpg)

Amelie è un dispositivo da tavolo per un'enoteca, un ristorante o una cantina di casa. Funziona a batteria per tutta una serata, ha un solo interruttore e si ricarica da una presa USB-C sul retro. Questa guida spiega come costruirne uno da zero: i componenti da comprare, la scocca stampata in 3D, i collegamenti, l'installazione del software su una UNO Q appena uscita dalla fabbrica e l'uso.

[English: README.md](https://github.com/destone28/Amelie2.0/blob/main/README.md)

## Che cosa fa Amelie

Un ospite posa una bottiglia sul piatto rotondo dietro lo schermo, con l'etichetta rivolta verso lo schermo: la camera guarda l'etichetta dal retro della torre che regge lo schermo. Un sensore di distanza sotto il piatto si accorge della bottiglia, e la camera fotografa l'etichetta illuminata dalla luce accanto a lei, bianca e gialla, sempre accesa. La camera regola da sola l'esposizione mentre il dispositivo aspetta, così la bottiglia trova la luce giusta già pronta. La UNO Q legge il testo dell'etichetta, lo cerca in un database di vini italiani e racconta la storia a voce, mentre il testo scorre sul touchscreen da 5" con la frase che la voce sta dicendo messa in evidenza.

![Il lato del piatto: il disco, la finestra della luce e la camera](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/piatto-camera-luce.jpg)

*Il lato del piatto: il disco su cui si posa la bottiglia e, nella torre, la finestra della luce e la camera. In basso a destra, la presa di ricarica.*

Amelie dice sempre quanto è sicura. Quando riconosce il vino esatto comincia con «Questo è il…»; quando riconosce solo la denominazione, la tipologia o il vitigno, lo dice e racconta quello. Non nomina mai qualcosa che non ha letto sull'etichetta. Ogni frase del racconto viene dai fatti del database e dal disciplinare di produzione della denominazione: niente è inventato.

L'ospite può mettere in pausa, tornare indietro o andare avanti, fermare il racconto con la croce, cambiare lingua con una bandiera e regolare il volume. Sollevare la bottiglia per versare non interrompe il racconto, e rimetterla non lo fa ricominciare. Posarne un'altra fa partire subito il racconto nuovo.

Chi gestisce il locale ha un pannello di impostazioni nascosto. Da lì sceglie da dove vengono i racconti:

- **Dall'archivio** (predefinito): composti dai fatti del database. È immediato e non inventa.
- **Carta dei vini**: le vostre descrizioni, da un file CSV con una riga per vino.
- **Scritto sul momento** (sperimentale): un piccolo modello linguistico che gira sulla UNO Q scrive il testo. È più lento, e quello che scrive viene controllato sui fatti prima di essere detto.

Quando Amelie non riconosce una bottiglia, il personale può insegnargliela dal touchscreen, scegliendo il vino giusto o scrivendone la descrizione. La volta dopo quella bottiglia si riconosce dalla foto e dalle parole.

## Come funziona

L'Arduino UNO Q ha due processori, e Amelie li usa entrambi.

- **Il lato Linux** (Qualcomm QRB2210, con Debian) esegue l'applicazione, scritta in Python: cattura dalla camera, OCR (riconoscimento ottico dei caratteri), ricerca nel database, composizione del racconto, sintesi vocale e la pagina web mostrata a tutto schermo sul display.
- **Il lato microcontrollore** (STM32U585, con Zephyr) esegue un piccolo sketch Arduino. Comanda le due schede Modulino sul connettore Qwiic, la luce e il sensore di distanza, e parla con Linux attraverso l'Arduino Router Bridge.

I pezzi principali del software:

- **OCR**: RapidOCR con le reti PP-OCRv6 su ONNX Runtime. Legge l'etichetta da un ritaglio del fotogramma.
- **Riconoscimento**: una cascata che va dalla corrispondenza più precisa alla più generale (vino, tipologia, denominazione, vitigno). Ogni corrispondenza ha un punteggio di sicurezza: sopra una soglia si racconta come certa, sopra una soglia più bassa come un'ipotesi, e il punteggio non può mai superare quello che le parole lette sull'etichetta permettono. Vedi [docs/it/06-riconoscimento.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/06-riconoscimento.md).
- **Il database**: circa 19.000 vini italiani e tutte le 532 denominazioni italiane del vino (DOCG, DOC e IGT), con le loro tipologie, i vitigni e le descrizioni ufficiali di colore, odore e sapore. Si costruisce sulla board dai dati aperti contenuti in questo repository.
- **Il racconto**: frasi composte da un lessico bilingue, riempite solo con fatti e poi controllate parola per parola prima di essere dette. Vedi [docs/it/07-racconto.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/07-racconto.md).
- **La voce**: Piper, con una voce per lingua, senza connessione.
- **Lo schermo**: una pagina web locale mostrata da Chromium a tutto schermo, servita da FastAPI.

## Che cosa serve

Questi sono i componenti con cui è costruita Amelie 2.0. I link portano ai prodotti usati per questa costruzione, sull'Arduino Store e su Amazon Italia; gli stessi prodotti si trovano sugli altri Amazon con lo stesso nome.

Elettronica:

- 1 × [Arduino UNO Q, 4 GB](https://store.arduino.cc/products/uno-q-4gb)
- 1 × [Arduino Modulino Pixels](https://store.arduino.cc/products/modulino-pixels): la luce
- 1 × [Arduino Modulino Distance](https://store.arduino.cc/products/modulino-distance): sente la bottiglia
- 2 × cavi Qwiic: ogni Modulino ne ha uno nella confezione
- 1 × [hub USB-C UGREEN Revodok 105](https://www.amazon.it/dp/B0BR3M8XHK): 5 in 1, con HDMI, un ingresso USB-C PD da 100 W, tre porte USB-A e un cavo USB-C integrato
- 1 × [touchscreen capacitivo IPS LAFVIN da 5", HDMI, 800 × 480](https://www.amazon.it/dp/B0BWJ8YP7S)
- 1 × [camera USB 2.0 UVC Innomaker 1080P](https://www.amazon.it/dp/B0CNCSFQC1) (U20CAM-1080P): scheda da 32 × 32 mm con quattro fori M2 e obiettivo M12, con il suo cavo USB
- 1 × [mini casse USB GOEDCH](https://www.amazon.it/dp/B0DKXML9X6): una coppia di piccole casse stereo, circa 46 × 46 × 28 mm ciascuna, alimentate via USB, con jack audio da 3,5 mm e controllo del volume sul cavo
- 1 × [power bank sottile Charmast da 26.800 mAh](https://www.amazon.it/dp/B073FJ9X2J): nella confezione c'è un cavo da USB-A a micro-USB, che serve per il touch dello schermo
- 1 × [cavo YINGAYOU da USB-A a USB-C con interruttore, 0,3 m](https://www.amazon.it/dp/B0FD9JVC9B): la spina USB-C è a 90°
- 1 × [prolunga USB-C Thsucords, maschio-femmina, 0,1 m, a 90°](https://www.amazon.it/dp/B0C8JBSXNJ): si vende in coppia, ne basta una; la sua estremità femmina diventa la presa di ricarica sul retro
- 1 × cavo HDMI maschio-maschio, il più corto possibile: hub e schermo sono a pochi centimetri

Pezzi stampati e minuteria:

- gli 11 pezzi stampati in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl), descritti nella sezione successiva
- filamento PLA per nove pezzi e PETG traslucido per i due che diffondono la luce
- 18 × viti da legno svasate, 4 × 16 mm
- 16 × viti M2 svasate: 8 × M2 × 5 mm, 6 × M2 × 6 mm, 2 × M2 × 8 mm
- 4 × piedini adesivi in gomma, spessi 3 mm

Attrezzi:

- una stampante 3D
- i cacciaviti per le viti qui sopra
- un computer (Windows, macOS o Linux) con [Arduino App Lab](https://www.arduino.cc/en/software/), per la prima configurazione della UNO Q
- un cavo USB-C dati (non un cavo di sola ricarica), per la prima configurazione
- un caricatore USB-C, per ricaricare il power bank dalla presa sul retro

Non serve saldare niente.

## Stampare i pezzi

La scocca è fatta di 11 pezzi. I file STL sono in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl).

- **Base**: la scocca. Regge la torre, il piatto su cui sta la bottiglia e la presa di ricarica.
- **Piastra**: il fondo removibile. Porta il power bank, l'hub, la UNO Q, le casse e l'interruttore.
- **Torre**: il cuneo a 30° che regge lo schermo davanti e l'ottica dietro.
- **Frontale**: la cornice dello schermo.
- **PannelloOttico**: il pannello dentro la torre, con le sedi della camera e del Modulino Pixels.
- **CerchioLuce**: il disco traslucido su cui sta la bottiglia; sotto si avvita il Modulino Distance.
- **PlaccaLuce**: la placca traslucida che chiude la finestra della luce sul retro della torre e la diffonde.
- **VassoioLuce**: il ponte sopra il power bank, sotto il disco.
- **FermoHub**, **FermoSwitch**, **FermoUno**: i fermi che tengono giù l'hub, l'interruttore e la UNO Q.

CerchioLuce e PlaccaLuce si stampano in PETG traslucido, tutto il resto in PLA. La Base si stampa capovolta, con il piano superiore sul piatto della stampante. Il materiale e le note di stampa di ogni pezzo sono in [docs/it/03-montaggio.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/03-montaggio.md).

![Gli 11 pezzi stampati](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/parti.png)

![Due esemplari costruiti dagli stessi file](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/due-esemplari.jpg)

*Due esemplari costruiti dagli stessi file di stampa, con alcuni pezzi in colori diversi.*

## Collegamenti

Tutto si innesta; non si salda niente.

![Schema dei collegamenti](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/wiring.png)

- **Alimentazione**: il power bank alimenta l'hub attraverso il cavo con l'interruttore, e l'hub alimenta la UNO Q attraverso il suo cavo USB-C integrato. La UNO Q fa da host USB e riceve la corrente dalla stessa porta.
- **Ricarica**: la presa USB-C sul retro è la prolunga che arriva all'ingresso USB-C del power bank. Amelie si ricarica senza aprirla.
- **Video e suono**: HDMI dall'hub allo schermo. Il suono viaggia sull'HDMI ed esce dal jack da 3,5 mm dello schermo, verso le casse.
- **USB**: la camera, il touch dello schermo (micro-USB, per il tocco e l'alimentazione) e la spina di alimentazione delle casse vanno nelle tre porte USB-A dell'hub.
- **Qwiic**: il connettore Qwiic della UNO Q va a un Modulino, e il secondo cavo Qwiic collega l'altro in catena; l'ordine non conta. Collegali prima di accendere: il microcontrollore li cerca all'avvio.

## Preparare la UNO Q

Una UNO Q appena uscita dalla fabbrica ha bisogno di un nome, di una password, della rete Wi-Fi, degli ultimi aggiornamenti Arduino e della modalità rete accesa. Il modo più semplice è Arduino App Lab. La procedura completa, compreso come fare tutto da terminale senza App Lab, è in [docs/it/01-preparare-la-uno-q.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/01-preparare-la-uno-q.md).

**Collega la board.** Installa [Arduino App Lab](https://www.arduino.cc/en/software/) sul computer e aprilo. Collega la UNO Q, da sola, al computer con il cavo USB-C dati. App Lab trova la board e avvia la prima configurazione.

**Nome, Wi-Fi e password.** Chiama la board `amelie`: il resto della guida la raggiunge come `amelie.local`. Se costruisci più di una Amelie, dai a ogni board un nome diverso (`amelie2`, `amelie3`…). Collegala alla rete Wi-Fi. Poi scegli una password per l'utente `arduino`: quella di fabbrica va cambiata alla prima configurazione. Tienila da parte: serve per l'SSH e per l'installazione.

**Aggiorna.** Accetta gli aggiornamenti che App Lab propone e aspetta che finiscano.

**Modalità rete.** La modalità rete accende l'SSH, il terminale remoto usato nei passi successivi, e fa rispondere la board come `amelie.local`. Controllala dal terminale della board, quello che si apre con `adb shell` (vedi la guida completa), con `arduino-app-cli system network-mode status`. Se risponde `disabled`, accendila con `arduino-app-cli system network-mode enable`, che chiede la password appena scelta.

**Verifica di raggiungerla.** Da un terminale sul computer:

```bash
ssh arduino@amelie.local
```

La prima volta l'SSH chiede di confermare l'impronta della board (scrivi `yes`), poi la password dell'utente `arduino`.

## Installare il software

L'installazione gira sulla UNO Q. Collegato in SSH, clona il repository nella cartella di casa e avvia l'installatore:

```bash
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

L'installatore chiede una volta la password dell'utente `arduino`, poi lavora da solo per circa un'ora, quasi tutta spesa a compilare llama.cpp. Stampa dodici passi numerati:

- i pacchetti di sistema (Chromium, Python, gli strumenti di compilazione)
- una correzione per la scheda audio all'avvio
- l'ambiente Python, con le versioni esatte elencate in `requirements.txt`
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

L'installatore si può rilanciare quando si vuole: salta ciò che è già fatto. Per aggiornare Amelie in seguito, sulla board: `cd ~/amelie && git pull && bash scripts/install.sh`.

Ogni passo è spiegato in [docs/it/02-installazione.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/02-installazione.md).

## Montare

La scocca si chiude in un ordine preciso, perché le viti che tengono la torre alla base si avvitano dall'interno della base, e si raggiungono solo finché il fondo è aperto. La guida completa, con la posizione di ogni componente e di ogni vite, è in [docs/it/03-montaggio.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/03-montaggio.md).

**Prima, la messa a fuoco della camera.** L'obiettivo M12 esce dalla fabbrica a fuoco lontano, e l'etichetta sta a circa 100 mm. Collega la camera a un computer come una webcam e ruota l'obiettivo finché le scritte piccole di un'etichetta a 10 cm sono nitide.

**Fase A, il fondo (Piastra).** Le due casse vanno negli angoli anteriori, con la membrana verso il basso. Il power bank va capovolto al centro, con le porte verso il retro. L'hub va nella culla a destra, con il cavo integrato verso il retro e la porta HDMI verso il fronte, tenuto dal fermo FermoHub. La UNO Q sta su quattro perni fra le casse, con la USB-C verso il retro, tenuta dal ponticello FermoUno. L'interruttore sta nel vano posteriore con la levetta attraverso il fondo, chiuso dal coperchio FermoSwitch. Poi si collegano il cavo con l'interruttore (Output 3 del power bank nella porta USB-C PD dell'hub), il cavo dell'hub alla UNO Q, la spina USB delle casse, il primo cavo Qwiic e la prolunga di ricarica, e si posa il ponte VassoioLuce sul power bank.

**Fase B, la torre (Torre).** La PlaccaLuce traslucida chiude la finestra della luce sul retro della torre. La camera, ruotata di 90°, e il Modulino Pixels si avvitano al pannello ottico, che poi si avvita dentro la torre. Lo schermo va nella rampa con i cavi HDMI, touch e audio già collegati, e la cornice Frontale lo chiude.

**Fase C, la scocca (Base).** Il Modulino Distance si avvita sotto il disco traslucido (CerchioLuce), che si blocca nella Base con un sesto di giro. La presa di ricarica entra nella parete posteriore. La torre si avvita alla Base dall'interno.

**Fase D, la chiusura.** Si collegano HDMI, touch, camera e la catena Qwiic, si accende e si controllano lo schermo, la voce e il rilevamento della bottiglia, poi si avvita il fondo alla Base e si attaccano i piedini.

![Esploso di Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/esploso.png)

<img src="https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/piastra.jpg" alt="La Piastra montata" width="480">

*La Piastra montata, vista dall'alto: le due casse e la UNO Q verso il fronte, il power bank al centro, l'hub accanto e i cavi.*

## La prima accensione

![L'interruttore nella finestra del fondo](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/interruttore.jpg)

*L'interruttore si aziona da sotto, dalla finestra nel fondo.*

Accendi Amelie. Lo schermo mostra il marchio di Amelie mentre le voci si caricano, poi la schermata d'attesa: un calice, «Ogni bottiglia ha una storia.» e tre passi, **Scegli** una bottiglia, **Posa** la bottiglia su Amelie, **Ascolta** la sua storia.

Controlla le tre cose che possono andare storte montando l'hardware:

- **Suono**: tocca la bandiera già evidenziata, in alto a destra. Amelie annuncia la lingua a voce. Se non la senti, controlla il jack fra lo schermo e le casse, l'alimentazione USB delle casse e il loro controllo del volume.
- **Moduli**: mentre Amelie aspetta, la luce è accesa, bianca e gialla; diventa rossa solo per un guasto, o in attesa quando la batteria è quasi scarica. Posa una bottiglia: lo schermo deve dire «Fammi guardare…». Se la luce resta spenta, o posando la bottiglia non succede niente, un Modulino non viene visto: controlla i cavi Qwiic, poi spegni e riaccendi.
- **Camera**: tieni il dito sull'angolo in basso a destra dello schermo per tre secondi per aprire le impostazioni, e accendi **Debug camera**. Lo schermo mostra il riquadro che va all'OCR, con l'etichetta al centro, e il testo letto.

Per un controllo completo, collegato in SSH:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Ogni prova, e che cosa fare quando una fallisce, è in [docs/it/04-collaudo.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/04-collaudo.md).

## Usare Amelie

Per gli ospiti non c'è niente da imparare. Si posa la bottiglia sul piatto con l'etichetta rivolta verso lo schermo, e si ascolta. I comandi sotto il testo ricominciano da capo, tornano indietro, mettono in pausa o vanno avanti. La croce in basso a sinistra ferma il racconto. Le bandiere in alto a destra cambiano la lingua, e l'altoparlante in alto a sinistra cambia il volume. Quando il racconto è finito e la bottiglia viene tolta, Amelie torna alla lingua di casa, pronta per il tavolo successivo.

Per il personale, le impostazioni si aprono tenendo il dito sull'angolo in basso a destra dello schermo per tre secondi. Contengono:

- **Come racconta**: la fonte dei racconti (Dall'archivio, Carta dei vini, Scritto sul momento).
- **Aggiungi correzioni**: mostra «Correggi la bottiglia» su ogni racconto, e «Mi aiuti a riconoscerla» sulle bottiglie che Amelie non conosce. Una correzione può indicare il vino giusto dell'archivio, oppure portare una descrizione scritta da voi, in una lingua o in tutte e due.
- **Debug camera**: che cosa vede e che cosa legge la camera, per regolare l'inquadratura.
- **Batteria ricaricata**: mostra la stima della batteria; si tocca dopo la ricarica, così la stima riparte da piena.
- **Ripristina il funzionamento**: rimette in moto camera, lettura e voce senza spegnere, quando «Qualcosa non ha funzionato» continua a ripresentarsi.
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

- **Lo schermo resta nero**: controlla il cavo HDMI e il cavo micro-USB dello schermo. Lo schermo è pilotato a 1280 × 720, una modalità che riduce al suo pannello da 800 × 480; `systemctl status amelie-display` dice quale modalità è stata impostata.
- **Niente suono**: vedi i controlli della prima accensione. Il suono ha bisogno dello schermo acceso, e Amelie lo tiene sempre sveglio.
- **Le bottiglie non vengono mai notate e la luce resta spenta**: sul microcontrollore non gira lo sketch di Amelie, di solito dopo un aggiornamento di App Lab. Sulla board lancia `bash ~/amelie/scripts/firmware.sh --sempre`, che ricarica sketch e loader insieme.
- **La luce c'è, ma le bottiglie non vengono notate**: il sensore di distanza non viene visto. Controlla la catena Qwiic, spegni e riaccendi.
- **All'annuncio della lingua manca «Lingua italiana», o a un racconto manca una frase**: uno spegnimento subito dopo una frase nuova l'ha lasciata vuota nella cache della voce. Spegni e riaccendi: all'avvio il servizio toglie le frasi vuote e le rifà.
- **Le etichette si leggono male**: accendi Debug camera e controlla che l'etichetta sia al centro del riquadro e nitida.
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

- Il codice è distribuito sotto licenza MIT ([LICENSE](https://github.com/destone28/Amelie2.0/blob/main/LICENSE)).
- Documentazione, immagini, schemi e file 3D sono distribuiti sotto Creative Commons Attribuzione 4.0 Internazionale ([LICENSE-DOCS.md](https://github.com/destone28/Amelie2.0/blob/main/LICENSE-DOCS.md)).

Il database dei vini si costruisce da dati aperti ed è distribuito sotto Open Database License 1.0. Le fonti sono:

- Candiago et al., «Quality wines in Italy and France: PDO specifications» (figshare, CC BY 4.0);
- de Azambuja, Morais e Filipe, «X-Wines: A Wine Dataset for Recommender Systems and Machine Learning», Big Data and Cognitive Computing 2023;
- il registro UE delle indicazioni geografiche e i documenti unici, © Unione europea (CC BY 4.0).

Le voci, le reti dell'OCR, il modello linguistico e il carattere hanno licenze proprie, tutte elencate in [docs/it/08-attribuzioni.md](https://github.com/destone28/Amelie2.0/blob/main/docs/it/08-attribuzioni.md).
