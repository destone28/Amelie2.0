# Collaudare Amelie

Come verificare che il dispositivo montato funzioni, dal controllo automatico
all'esperienza completa con una bottiglia vera. Ogni prova dice che cosa ci si
aspetta e che cosa fare se non torna.

Una regola vale per tutto: **quello che il software dichiara non è quello che
fa l'hardware.** Lo schermo si collauda guardandolo, l'audio ascoltandolo. Un
`xrandr` che dichiara una modalità video attiva e un `aplay` che suona un file
senza errori non dimostrano niente.

Le prove si fanno con il dispositivo montato e acceso. I comandi si scrivono
sulla board, nel terminale che si apre dal computer con
`ssh arduino@amelie.local` (vedi [Installare il software](02-installazione.md)),
nella cartella del progetto, `~/amelie`. Quelli con `sudo` chiedono la password
dell'utente `arduino`.

## Il controllo automatico

Dopo l'installazione e un riavvio, aspetta che lo schermo mostri la schermata
d'attesa, meno di un minuto dall'accensione: prima alcuni servizi stanno ancora
partendo, e lo script li segnalerebbe come guasti. Poi, sulla board:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Lo script legge e basta: non cambia niente. Stampa otto sezioni:

1. **Sistema**: la versione di Debian, lo spazio libero, la memoria, la
   temperatura;
2. **Installazione**: ambiente Python, voci e modello con le loro somme,
   llama.cpp, database, carta dei vini, firmware;
3. **Servizi**: che i servizi siano abilitati e attivi, e la sessione grafica
   di Amelie;
4. **Applicazione**: che risponda e che lo schermo la mostri, il
   microcontrollore, i due Modulino, la camera, la voce;
5. **Schermo**: l'uscita video, la modalità 1280x720, il touch;
6. **Camera**: la camera USB;
7. **Audio**: la scheda audio, la strada del suono verso l'HDMI e la cache
   delle frasi già dette;
8. **Router verso il microcontrollore**: il servizio `arduino-router`, che
   collega Linux al microcontrollore, e che App Lab non avvii app
   all'accensione.

Ogni voce è **OK**, **ATTENZIONE** o **GRAVE**; le righe senza etichetta sono
informazioni. Le voci GRAVE dicono che cosa non funzionerà e, quasi sempre, che
cosa fare. In fondo il **Riepilogo** conta le voci dei tre tipi: è tutto a
posto quando non ci sono voci GRAVE. Il rapporto resta in
`/tmp/amelie-diagnostica.txt` fino al riavvio successivo.

Le voci più frequenti, e che cosa fare:

| Voce | Che cosa fare |
|---|---|
| «l'applicazione non risponde su 127.0.0.1:8080: …» | se hai appena acceso, aspetta un minuto e rilancia lo script; se resta, guarda il giornale dell'applicazione: `journalctl -u amelie -n 50` |
| «applicazione non ancora pronta (riprova fra qualche secondo)» | sta caricando le voci: rilancia lo script fra qualche secondo |
| «nessuno schermo collegato all'applicazione: …» | lo schermo non mostra Amelie: guarda che cosa c'è. Per un avviso di Chromium o una pagina ferma, `sudo systemctl restart amelie-kiosk`; per la scrivania, vedi [Lo schermo](#lo-schermo) |
| «… non abilitato (…): rilancia scripts/install.sh», «manca …: rilancia scripts/install.sh» | rilancia `bash scripts/install.sh` |
| «il router risponde ma lo sketch di Amelie non gira sul microcontrollore: …», «sul microcontrollore gira un firmware di un'altra versione …» | ricarica sketch e loader: `bash scripts/firmware.sh --sempre`. Vedi [Il microcontrollore](#il-microcontrollore) |
| «il microcontrollore non risponde: arduino-router fermo …» | `sudo systemctl restart arduino-router`, poi rilancia lo script |
| «nessuna traccia di un firmware caricato e verificato: …» | `bash scripts/firmware.sh` |
| «voce non caricata: il racconto si leggera' soltanto» | mancano le voci: rilancia `bash scripts/install.sh` |
| «la camera non ha mai dato un fotogramma all'applicazione: …», «la camera non da' fotogrammi da … s: …» | l'applicazione non riceve immagini dalla camera: controlla il cavo USB della camera e la sua presa sull'hub, poi `sudo systemctl restart amelie` |
| «nessuna camera USB: controlla il cavo della camera» | il cavo USB della camera non arriva all'hub |
| «… frasi rovinate nella cache della voce: …» | uno spegnimento ha lasciato vuote delle frasi già dette: il servizio le toglie a ogni avvio, `sudo systemctl restart amelie`. Vedi [L'audio](#laudio) |

Per schermo, touch, audio, microcontrollore e Modulino, le sezioni qui sotto.

## Lo schermo

Guarda il pannello: deve mostrare la schermata d'attesa di Amelie, con il
calice su fondo scuro, a tutto schermo e senza puntatore.

| Sintomo | Causa | Rimedio |
|---|---|---|
| nero, e lo script dice «modalita' 1280x720» | il cavo HDMI o l'alimentazione dello schermo | controlla il cavo HDMI e il cavo micro-USB dello schermo |
| nero, e lo script dice «modalita' 800x480: il pannello vuole 1280x720 …» | il pannello non produce immagine alla sua risoluzione nativa | `sudo systemctl restart amelie-display`; se non basta, `sudo reboot` |
| immagine piccola in un angolo, e lo script segnala un'altra modalità, per esempio 1920x1080 | lo schermo non è a 1280x720 | `sudo systemctl restart amelie-display`; se non basta, `sudo reboot` |
| compare la scrivania | la sessione di Amelie non è impostata (lo script lo segnala come ATTENZIONE) | rilancia `bash scripts/install.sh`, poi `sudo reboot` |
| la pagina non cambia dopo un aggiornamento | il chiosco carica la pagina una volta sola, all'avvio | `sudo systemctl restart amelie-kiosk` |
| un avviso di Chromium al posto di Amelie | il chiosco si è fermato prima di aprire la pagina | `sudo systemctl restart amelie-kiosk` |

Uno schermo che si spegne porta via anche l'audio: il ponte video della board
configura l'audio solo se vede lo schermo acceso. Per questo `amelie-display`
disattiva il risparmio energetico dello schermo.

## Il touch

Tocca la bandiera dell'altra lingua, in alto a destra: le scritte devono
cambiare subito, e Amelie annuncia a voce la lingua nuova. Se il tocco non
risponde, controlla il cavo micro-USB dello schermo (porta il tocco e
l'alimentazione) e che lo script dica «touch dello schermo»; se dice «nessun
touch riconosciuto», quel cavo non arriva all'hub. Alla fine tocca la bandiera
della lingua di partenza.

## L'audio

Tocca la bandiera **già evidenziata**, piena e con l'anello d'oro: non cambia
niente, ma Amelie annuncia la lingua a voce, «Lingua italiana. Da adesso
racconto i vini in italiano.», oppure «English language. From now on I will
describe the wines in English.» se la lingua è l'inglese. È la prova d'audio
più rapida.

| Sintomo | Causa | Rimedio |
|---|---|---|
| silenzio, lo script dice «nessuna scheda audio» | all'avvio la scheda audio non è nata | `sudo systemctl restart amelie-audio-guard`, poi `sudo reboot` |
| silenzio, lo script dice «strada del suono verso l'HDMI chiusa» | il controllo del mixer è rimasto chiuso | `sudo systemctl restart amelie-audio-rotta` |
| silenzio, tutto OK nello script | le casse | controlla il jack fra schermo e casse, il cavo USB che alimenta le casse e il controllo del volume sul loro cavo, che va tenuto al massimo (si raggiunge solo a scocca aperta) |
| suono debole | il volume | alzalo dall'altoparlante in alto a sinistra; se è già al massimo, controlla il controllo del volume sul cavo delle casse |
| si sente solo «Da adesso racconto i vini in italiano.», senza «Lingua italiana.»; oppure a un racconto manca una frase | quella frase è salvata vuota nella cache della voce: succede se si spegne pochi secondi dopo averla sentita per la prima volta | spegni e riaccendi, oppure `sudo systemctl restart amelie`: a ogni avvio il servizio toglie le frasi vuote e le rifà al primo uso. Lo script lo controlla alla sezione 7 |

Per provare l'audio senza l'applicazione ci sono due script, da lanciare con
lo schermo acceso e **a servizio fermo**: `scripts/01_audio.sh` controlla tutta
la catena (kernel, profili audio, schermo collegato, scheda, mixer) e alla fine
fa sentire un suono di prova; con `--solo-diagnosi` guarda soltanto.
`scripts/suona.sh` fa sentire soltanto un tono.

```bash
cd ~/amelie
sudo systemctl stop amelie
bash scripts/suona.sh
sudo systemctl start amelie
```

L'applicazione tiene l'uscita audio sempre aperta, di proposito: il processore
audio della board impiega circa due secondi a cominciare a suonare, e pagarli a
ogni frase farebbe sparire le frasi corte. Un secondo programma che prova ad
aprire l'uscita la trova occupata: per questo gli script si lanciano a servizio
fermo.

Ogni tanto, all'avvio, la scheda audio non si presenta: è una corsa fra due
componenti del sistema. La guardia `amelie-audio-guard` se ne accorge, riavvia
il processore audio e, se non basta, la board: una volta sola, e solo nei primi
dieci minuti dall'accensione. Che cosa ha fatto lo scrive in
`/var/lib/amelie/audio-guard.log`; le ultime righe si leggono con
`tail /var/lib/amelie/audio-guard.log`.

## Il microcontrollore

La luce e il sensore di distanza li comanda il microcontrollore della UNO Q,
con lo sketch di Amelie. Se lo sketch non gira, la luce resta spenta e il
dispositivo non vede nessuna bottiglia, anche con i Modulino collegati: il LED
del Modulino Distance è acceso, perché il modulo è alimentato, ma nessuno lo
interroga.

Si riconosce così:

- lo script, alla sezione 4, dice «il router risponde ma lo sketch di Amelie
  non gira sul microcontrollore»;
- nelle impostazioni, «Stato tecnico» mostra `mcu: false` e `protocollo: null`;
- il giornale dell'applicazione ripete «il router risponde ma lo sketch di
  Amelie non c'e'»: `journalctl -u amelie -n 20`.

La causa più frequente è la coppia fra sketch e loader. Il loader è il
programma che, all'accensione del microcontrollore, avvia lo sketch da un
indirizzo fisso della memoria; loader e indirizzo cambiano con la versione del
core di Arduino. App Lab, aggiornandosi, porta sul microcontrollore il loader
della sua versione, e uno sketch compilato con un core diverso non parte più:
il caricamento riesce, il microcontrollore tace. Il rimedio è ricaricare sketch
e loader insieme, con lo stesso core, come utente `arduino` e senza password:

```bash
cd ~/amelie
bash scripts/firmware.sh --sempre
```

Lo script compila lo sketch se serve, lo carica insieme al loader, aspetta che
il microcontrollore risponda e dice quali Modulino vede: «firmware caricato, il
microcontrollore risponde: Pixels visto, Distance visto». L'applicazione se ne
accorge da sola entro venti secondi, senza riavvii. Nell'istante in cui il
microcontrollore riparte, il router scrive nel suo giornale alcune righe
«decoding packet: invalid packet, expected array»: è normale.

| Messaggio di `firmware.sh` | Che cosa fare |
|---|---|
| «arduino-router e' fermo: …» | `sudo systemctl restart arduino-router`, poi rilancia |
| «caricamento non riuscito: …» | rilancia; se si ripete, spegni e riaccendi con l'interruttore e rilancia |
| «firmware caricato, ma il microcontrollore non risponde» | spegni e riaccendi con l'interruttore e rilancia; se resta, guarda il router: `journalctl -u arduino-router -n 30` |
| «… Pixels NON visto», «… Distance NON visto» | vedi [I Modulino](#i-modulino) |

Dopo ogni aggiornamento di App Lab o di sistema conviene lanciare
`bash scripts/firmware.sh`, senza `--sempre`: se il microcontrollore risponde
ancora non tocca niente. Lo fa anche `scripts/install.sh`, al passo 9.

## I Modulino

Il microcontrollore cerca i Modulino solo nei primi dieci secondi dopo la sua
accensione: un modulo collegato dopo risulta assente fino all'accensione
successiva. Per riprovare, spegni il dispositivo con l'interruttore e
riaccendilo: riavviare Linux (`sudo reboot`) non basta, perché il
microcontrollore non riparte.

- **Modulino Pixels**: all'accensione la luce pulsa lentamente, bianca e
  gialla; quando il dispositivo è pronto resta fissa, al massimo. Se resta
  spenta, il modulo non è visto.
- **Modulino Distance**: posa una bottiglia di vetro scuro. Entro un istante lo
  schermo dice «Fammi guardare…», poi «Sto leggendo l'etichetta…». Se non
  succede niente, il sensore non è visto. Il sensore
  misura con la luce infrarossa, che attraversa il vetro chiaro: una bottiglia
  trasparente può non essere vista, per questo la prova si fa con il vetro
  scuro.

In tutti e due i casi controlla che i cavi Qwiic siano inseriti a fondo alle
due estremità (l'ordine dei moduli nella catena non conta), poi spegni e
riaccendi con l'interruttore. La sezione 4 dello script dice quali moduli vede
il microcontrollore: «Modulino Pixels visto», «Modulino Distance visto». Lo
stesso si vede sullo schermo, senza computer: nelle impostazioni, «Stato
tecnico» mostra `moduli`, con `anello` (il Pixels) e `distanza` (il Distance) a
`true` quando il modulo è visto.

Più in dettaglio, a servizio fermo:

```bash
cd ~/amelie
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/bus.py
sudo systemctl start amelie
```

`bus.py` elenca che cosa risponde sul bus I²C, il bus dei cavi Qwiic, e a
quale indirizzo: `0x36` è il Modulino Pixels, `0x29` il Modulino Distance. Se
ne manca uno, lo dice. Con `--guarda` resta in ascolto e stampa ogni
cambiamento, mentre colleghi un pezzo per volta (si esce con Ctrl+C); con
`--sensore` mostra per dieci secondi le letture del sensore di distanza, mentre
muovi una mano sopra il disco.

## La camera

Apri le impostazioni tenendo il dito fermo sull'angolo in basso a destra dello
schermo per tre secondi, e accendi **Debug camera**. Finché è accesa il
dispositivo non racconta: lo schermo mostra che cosa vede la camera, con sopra
il riquadro che va all'OCR, e a lato che cosa legge.

Posa una bottiglia con l'etichetta rivolta verso lo schermo:

- l'etichetta deve stare nel riquadro, al centro: le due linee sottili segnano
  le mezzerie;
- il riquadro e la scritta `nitidezza N (soglia 40)` devono essere verdi:
  verde vuol dire sopra la soglia, rosso sotto;
- a lato, sotto «Cosa legge», devono comparire le righe dell'etichetta, e sotto
  «Cosa trova» il livello a cui è arrivato il riconoscimento e la sua
  sicurezza. La lettura si aggiorna ogni pochi secondi: l'OCR richiede qualche
  secondo a giro.

Se la nitidezza resta rossa, la lente è fuori fuoco. L'obiettivo M12 si mette
a fuoco ruotandolo nel suo supporto: la distanza giusta è quella
dell'etichetta, circa 100 mm. Ruotalo a piccoli passi finché la nitidezza è
massima, poi bloccalo (il supporto ha una ghiera o una vite di fermo; in
mancanza, una goccia di frenafiletti debole).

Si esce con «torna al racconto», in basso: una bottiglia rimasta sul piatto si
legge subito, ed è la prova che l'inquadratura funziona. La Debug camera non
resta accesa dopo un riavvio.

Per vedere la stessa vista più grande, sul computer: `scripts/mirino.py` gira
sulla board, a servizio fermo, e si guarda nel browser del computer.

```bash
cd ~/amelie
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/mirino.py --ocr
```

Apri nel browser del computer l'indirizzo che lo script stampa,
`http://<indirizzo-della-board>:8090/` (oppure `http://amelie.local:8090/`).
`--ocr` aggiunge le righe lette e che cosa trova nel database; `--luce` accende
la luce in bianco, come durante lo scatto. Si chiude con Ctrl+C; poi
`sudo systemctl start amelie`.

## Il riconoscimento, senza bottiglia

Il riconoscimento si prova anche su un testo scritto a mano, come se lo avesse
letto l'OCR. Sulla board:

```bash
cd ~/amelie
PYTHONPATH=src ./venv/bin/python - <<'EOF'
from amelie.matcher import Matcher
m = Matcher()
for letto in (["BAROLO", "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA", "2016"],
              ["AMARONE DELLA VALPOLICELLA", "CLASSICO"],
              ["Nebbiolo"],
              ["CONTIENE SOLFITI", "750 ml"]):
    f = m.cerca(letto)
    print(f"{f.livello.value:14} {f.sicurezza:5.0f}  "
          f"{f.nome or f.tipologia or f.denominazione or (f.vitigni[0] if f.vitigni else '-')}")
EOF
```

Atteso:

```
tipologia         70  Barolo
tipologia         87  Amarone della Valpolicella Classico
vitigno           60  Nebbiolo
nulla              0  -
```

Ogni riga dice il livello a cui si è fermato il riconoscimento (`tipologia`,
la tipologia di una denominazione; `vitigno`; `nulla`, niente), la sicurezza e
che cosa ha riconosciuto. L'ultima è la più importante: su un testo che non
dice niente del vino il dispositivo non deve inventare.

## I test automatici

Il repository ha circa mille test. Sulla board:

```bash
cd ~/amelie
./venv/bin/pip install -q -r requirements-dev.txt
./venv/bin/python -m pytest -q -p no:cacheprovider tests/
```

Il primo comando aggiunge pytest, il programma che esegue i test, all'ambiente
Python della board; basta farlo una volta. Il secondo li esegue senza lasciare
la cache di pytest nel repository, in un paio di minuti. Alla fine pytest
scrive quanti test sono passati (`passed`) e quanti saltati (`skipped`):
alcuni si saltano di proposito, quando manca qualcosa che sulla board non
serve. Non devono comparire `failed` né `error`. I test che controllano che il
racconto non inventi sono in `tests/test_narrator.py`.

## L'esperienza completa

Con il dispositivo montato, acceso e una bottiglia vera:

1. **A riposo**: il calice, «Ogni bottiglia ha una storia.», i tre passi
   («**Scegli** una bottiglia», «**Posa** la bottiglia su Amelie», «**Ascolta**
   la sua storia»), la luce bianca e gialla accesa.
2. **Posa la bottiglia**: lo schermo dice «Fammi guardare…», poi «Sto
   leggendo l'etichetta…» e «Un attimo…».
3. **Il racconto**: il titolo in alto, il testo con la frase che la voce sta
   dicendo in evidenza, la voce.
4. **Solleva la bottiglia come per versare**: il racconto continua fino in
   fondo. Rimettila: il racconto non ricomincia.
5. **Tocca la croce in basso a sinistra**: la voce si ferma subito e torna la
   schermata d'attesa. La bottiglia rimasta sul piatto non si rilegge: per un
   racconto nuovo, sollevala e rimettila.

| Che cosa guardare | Perché |
|---|---|
| sollevata per versare, il racconto continua | chi versa non ha chiesto silenzio, e un racconto interrotto a metà frase si nota |
| la croce ferma la voce subito | è l'unico modo di chiudere un racconto prima della fine, visto che togliere la bottiglia non lo ferma, e deve funzionare sempre |
| la prima frase dice quanto è sicuro | «Questo è…» e le altre forme certe solo quando lo è; nel dubbio «Direi…», «Dovrebbe essere…», «Mi sembra…» |
| rimessa la stessa bottiglia, il racconto non ricomincia | chi ha appena versato non vuole risentire tutto |
| posata un'altra bottiglia, parte il racconto nuovo | il dispositivo la legge mentre la voce continua, e cambia racconto solo se è davvero un altro vino |

## Prove di rottura

Da fare prima di lasciare il dispositivo in sala, dove nessuno potrà
intervenire.

| Prova | Atteso |
|---|---|
| togli la bottiglia mentre lo schermo dice «Fammi guardare…» o «Sto leggendo l'etichetta…» | il giro si interrompe e torna la schermata d'attesa |
| metti e togli rapidamente dieci volte | nessun blocco, nessuna lettura doppia |
| una bottiglia senza etichetta, o girata | lo schermo chiede «Provi a girare l'etichetta verso di me?», con la luce sempre accesa per rileggere, e riprova; dopo tre tentativi torna all'attesa, e non rilegge quella bottiglia finché non la togli. Con «Aggiungi correzioni» acceso, se dall'etichetta ha letto qualche parola, prima dice «Non ho riconosciuto questa bottiglia.» e offre «Mi aiuti a riconoscerla» |
| scollega la camera e posa una bottiglia | «Qualcosa non ha funzionato. Riprovo fra un istante.», con la luce rossa, poi la schermata d'attesa. Ricollega la camera e tocca «Ripristina il funzionamento» nelle impostazioni: la bottiglia successiva si legge di nuovo |
| nel modo «Scritto sul momento», `sudo systemctl stop amelie-llm`, poi una bottiglia | lo schermo dice «Sto scrivendo la descrizione…» per circa 45 secondi, poi racconta lo stesso, dall'archivio. Alla fine riaccendi il modello con `sudo systemctl start amelie-llm` |
| riavvia dieci volte, con `sudo reboot` o spegnendo e riaccendendo con l'interruttore | l'audio c'è ogni volta (guarda `/var/lib/amelie/audio-guard.log`) |
| stacca la corrente durante il racconto | alla riaccensione riparte pulito, fino alla schermata d'attesa |
| lascia il dispositivo acceso a riposo per un'ora | la schermata resta accesa, senza spegnersi e senza blocco dello schermo; in SSH, `top` (si esce con q) non mostra programmi che stanno di continuo vicino al 100 % di un core. Fa eccezione `llama-server` nel modo «Scritto sul momento», che a riposo tiene occupato quasi un core |

## Prima di lasciarlo in sala

- Segui «Mettere in sicurezza» in
  [Installare il software](02-installazione.md#mettere-in-sicurezza).
- Azzera il contatore dei riavvii della guardia audio, così dopo il collaudo ha
  di nuovo il suo unico tentativo: `sudo rm -f /var/lib/amelie/riavvii-audio`.
- Spegni **Debug camera** se è accesa, e **Aggiungi correzioni** se non serve.
- Se durante il collaudo hai salvato correzioni di prova, cancellale (vedi
  [Usare Amelie](05-uso.md)).
- Ricarica la batteria e tocca **Batteria ricaricata** nelle impostazioni: il
  power bank non comunica la sua carica, e il dispositivo la stima dal tempo e
  dal lavoro fatto dopo la ricarica.
- Spegni con l'interruttore, riaccendi e verifica che il dispositivo arrivi da
  solo alla schermata d'attesa, senza tastiera e senza rete.

## Il passo successivo

[Usare Amelie](05-uso.md).
