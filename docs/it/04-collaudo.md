# Collaudare Amelie

Come verificare che il dispositivo montato funzioni, dal controllo automatico
all'esperienza completa con una bottiglia vera. Ogni prova dice che cosa ci si
aspetta e che cosa fare se non torna.

Una regola vale per tutto: **quello che il software dichiara non è quello che
fa l'hardware.** Lo schermo si collauda guardandolo, l'audio ascoltandolo. Un
`xrandr` che dichiara una modalità attiva e un `aplay` che non dà errori non
dimostrano niente.

## Il controllo automatico

Dopo l'installazione e un riavvio, collegati alla board ed esegui:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Lo script legge e basta. Controlla il sistema, l'installazione (ambiente
Python, voci e modello con le loro somme, llama.cpp, database, carta dei vini,
firmware), i servizi, l'applicazione (microcontrollore, i due Modulino, camera,
voce), lo schermo, la camera, l'audio e il router verso il microcontrollore.
Ogni voce è **OK**, **ATTENZIONE** o **GRAVE**, e ogni voce GRAVE dice che cosa
fare. Il rapporto resta in `/tmp/amelie-diagnostica.txt`.

Tutto a posto quando il riepilogo non ha voci GRAVE.

## Lo schermo

Guarda il pannello: deve mostrare la schermata d'attesa di Amelie, con il
calice su fondo scuro, a tutto schermo e senza puntatore.

| Sintomo | Causa | Rimedio |
|---|---|---|
| nero, ma lo script dice 1280x720 | cavo HDMI o alimentazione dello schermo | controlla il cavo HDMI e il cavo micro-USB dello schermo |
| nero, con la modalità 800x480 | il pannello LAFVIN non produce immagine alla sua risoluzione nativa | `sudo systemctl restart amelie-display` |
| immagine piccola in un angolo | modalità 1920x1080 | `sudo systemctl restart amelie-display` |
| compare la scrivania | la sessione di Amelie non è impostata | rilancia `bash scripts/install.sh` |
| la pagina non cambia dopo un aggiornamento | il chiosco apre la pagina una volta sola | `sudo systemctl restart amelie-kiosk` |

Uno schermo che si spegne porta via anche l'audio: il ponte video della board
configura l'audio solo se vede lo schermo acceso. Per questo
`amelie-display` disattiva il risparmio energetico dello schermo.

## Il touch

Tocca la bandiera dell'altra lingua, in alto a destra: le scritte devono
cambiare subito. Se il tocco non risponde, controlla il cavo micro-USB dello
schermo (porta il tocco e l'alimentazione) e che lo script dica «touch dello
schermo».

## L'audio

Tocca la bandiera **già evidenziata**: non cambia niente, ma Amelie annuncia la
lingua a voce. È la prova d'audio più rapida.

| Sintomo | Causa | Rimedio |
|---|---|---|
| silenzio, lo script dice «nessuna scheda audio» | all'avvio la scheda audio non è nata | `sudo systemctl restart amelie-audio-guard`, poi riavvia |
| silenzio, «strada del suono verso l'HDMI chiusa» | il controllo del mixer è tornato a zero | `sudo systemctl restart amelie-audio-rotta` |
| silenzio, tutto OK nello script | casse | controlla il jack fra schermo e casse, l'alimentazione USB delle casse e il loro volume |
| suono debole | volume | alzalo dall'altoparlante in alto a sinistra |

Per provare l'audio senza l'applicazione ci sono `scripts/01_audio.sh` (diagnosi
completa, poi un tono) e `scripts/suona.sh` (solo il tono), ma **a servizio
fermo**:

```bash
sudo systemctl stop amelie
bash scripts/suona.sh
sudo systemctl start amelie
```

L'applicazione tiene l'uscita audio aperta per sempre, di proposito: il
processore audio della board impiega due secondi ad avviarsi, e pagarli a ogni
frase renderebbe muta ogni frase corta. Un secondo programma che prova ad
aprirla la trova occupata.

Ogni tanto, all'avvio, la scheda audio non si presenta: è una corsa fra due
componenti del sistema all'avvio. La guardia `amelie-audio-guard` se ne accorge,
riavvia il processore audio e, se non basta, la board, una volta sola. Che cosa
ha fatto lo scrive in `/var/lib/amelie/audio-guard.log`.

## I Modulino

Il microcontrollore cerca i Modulino **all'accensione**: un modulo collegato
dopo risulta assente fino al riavvio successivo.

- **Modulino Pixels**: a riposo la luce è ambra tenue. Se resta spenta, il
  modulo non è visto.
- **Modulino Distance**: posa una bottiglia. Entro un istante lo schermo dice
  «Fammi guardare…». Se non succede niente, il sensore non è visto.

In tutti e due i casi controlla i cavi Qwiic e la loro sequenza, poi spegni e
riaccendi. Lo script dice quali moduli vede il microcontrollore; più in
dettaglio, a servizio fermo:

```bash
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/bus.py
sudo systemctl start amelie
```

`bus.py` elenca che cosa risponde sul bus I²C, a quale indirizzo, e le letture
del sensore di distanza.

## La camera

Apri le impostazioni tenendo il dito sull'angolo in basso a destra dello schermo
per tre secondi, e accendi **Debug camera**. Lo schermo mostra che cosa vede la
camera, il riquadro che va all'OCR e che cosa legge.

Posa una bottiglia con l'etichetta rivolta verso lo schermo:

- l'etichetta deve stare nel riquadro, al centro;
- la scritta `nitidezza` deve essere verde (sopra la soglia);
- nella colonna «Cosa legge» devono comparire le righe dell'etichetta.

Se la nitidezza resta rossa, la lente è fuori fuoco. L'obiettivo M12 si mette
a fuoco ruotandolo nel suo supporto: la distanza giusta è quella dell'etichetta,
circa 100 mm. Ruotalo a piccoli passi finché la nitidezza è massima, poi
bloccalo (il supporto ha una ghiera o una vite di fermo; in mancanza, una goccia
di frenafiletti debole).

Si esce con «torna al racconto» in basso: una bottiglia rimasta sul piatto si
legge subito.

Dal PC, a servizio fermo, `scripts/mirino.py` mostra la stessa vista in una
finestra più grande; le istruzioni sono in testa allo script.

## Il riconoscimento, senza bottiglia

Il riconoscimento si prova anche su un testo scritto a mano, come se lo avesse
letto l'OCR:

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

L'ultima riga è la più importante: su un testo che non dice niente del vino il
dispositivo non deve inventare.

## I test automatici

Il repository ha circa mille test. Sulla board:

```bash
cd ~/amelie
./venv/bin/pip install -q -r requirements-dev.txt
./venv/bin/python -m pytest -q -p no:cacheprovider tests/
```

Ci vogliono un paio di minuti. I test che controllano che il racconto non
inventi sono in `tests/test_narrator.py`.

## L'esperienza completa

Con il dispositivo montato, acceso e una bottiglia vera:

1. **A riposo**: il calice, «Ogni bottiglia ha una storia.», i tre passi, la
   luce ambra tenue.
2. **Posa la bottiglia**: la luce cambia e lo schermo dice «Fammi guardare…»,
   poi «Sto leggendo l'etichetta…» e «Un attimo…».
3. **Il racconto**: il titolo in alto, il testo con la frase che la voce sta
   dicendo in evidenza, la voce.
4. **Solleva la bottiglia come per versare**: il racconto continua fino in
   fondo. Rimettila: il racconto non ricomincia.
5. **Tocca la croce in basso a sinistra**: la voce si ferma subito. Solleva la
   bottiglia: torna la schermata d'attesa.

| Che cosa guardare | Perché |
|---|---|
| sollevata per versare, il racconto continua | chi versa non ha chiesto silenzio, e un racconto interrotto a metà frase si nota |
| la croce ferma la voce subito | è l'unico modo di zittire il dispositivo, e deve funzionare sempre |
| la prima frase dice quanto è sicuro | «Questo è…» solo quando lo è |
| rimessa la stessa bottiglia, il racconto non ricomincia | chi ha versato non vuole risentire tutto |
| posata un'altra bottiglia, parte il racconto nuovo | |

## Prove di rottura

Da fare prima di lasciare il dispositivo in sala, dove nessuno potrà
intervenire.

| Prova | Atteso |
|---|---|
| togli la bottiglia durante «Fammi guardare…» | il giro si interrompe e torna la schermata d'attesa |
| metti e togli rapidamente dieci volte | nessun blocco, nessuna lettura doppia |
| una bottiglia senza etichetta, o girata | chiede di girare l'etichetta verso di sé e riprova; dopo tre tentativi torna all'attesa (con «Aggiungi correzioni» acceso dice «Non ho riconosciuto questa bottiglia.») |
| scollega la camera e posa una bottiglia | un messaggio di errore, poi il ritorno all'attesa |
| nel modo «Scritto sul momento», `sudo systemctl stop amelie-llm`, poi una bottiglia | racconta lo stesso, dai fatti |
| riavvia dieci volte | l'audio c'è ogni volta (guarda `/var/lib/amelie/audio-guard.log`) |
| stacca la corrente durante il racconto | riparte pulito |
| lascia il dispositivo acceso a riposo per un'ora | la schermata resta accesa, la batteria scende poco (l'icona sulla riga «Batteria ricaricata» delle impostazioni) |

## Prima di lasciarlo in sala

- Segui «Mettere in sicurezza» in [Installare il software](02-installazione.md).
- Azzera il contatore dei riavvii della guardia audio, così dopo il collaudo ha
  di nuovo il suo unico tentativo: `sudo rm -f /var/lib/amelie/riavvii-audio`.
- Spegni **Debug camera** e **Aggiungi correzioni** se non servono.
- Riavvia e verifica che il dispositivo arrivi da solo alla schermata d'attesa,
  senza tastiera e senza rete.

## Il passo successivo

[Usare Amelie](05-uso.md).
