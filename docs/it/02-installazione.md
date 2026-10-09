# Installare il software

Tutto il software di Amelie si installa con uno script, `scripts/install.sh`,
che gira sulla UNO Q. Questa guida spiega come lanciarlo, che cosa fa passo per
passo, dove mette le cose e come si aggiorna il dispositivo.

Serve una board preparata come in
[Preparare la UNO Q](01-preparare-la-uno-q.md): con il nome `amelie`, la
password dell'utente `arduino` scelta alla prima configurazione, la rete Wi-Fi
e la modalità rete accesa. Su una board nuova la modalità rete è spenta, e con
lei l'SSH e il nome `amelie.local`: quella guida spiega come accenderla. Se hai
dato alla board un altro nome, usalo al posto di `amelie` in tutti i comandi.

Si lavora in due posti:

- **sul computer**, in un terminale (su Windows PowerShell, su macOS e Linux
  l'app Terminale);
- **sulla board**, nel terminale che si apre dal computer con
  `ssh arduino@amelie.local`. SSH è il terminale remoto: quello che scrivi lì
  gira sulla board. Si esce con `exit`.

Dove non è detto altrimenti, i comandi di questa guida si scrivono sulla board.
Quelli che cominciano con `sudo` agiscono da amministratore: `sudo` chiede la
password dell'utente `arduino` (mentre la scrivi non compare niente) e la
ricorda per un quarto d'ora.

## Dove sta la board mentre installi

All'installazione serve solo la rete. La board può stare:

- **sul banco, collegata all'hub**, con l'hub alimentato dal power bank o da un
  alimentatore USB-C, anche senza schermo e camera: è la sistemazione
  consigliata;
- **già montata** nel dispositivo;
- **collegata al computer** con il cavo USB-C, come alla fine di
  [Preparare la UNO Q](01-preparare-la-uno-q.md). Funziona, ma la board prende
  la corrente dal computer, e al passo 6 la compilazione di llama.cpp tiene i
  quattro core al massimo per una ventina di minuti: usa una porta che dia
  almeno 1,5 A. Se durante la compilazione la board si riavvia da sola, la
  corrente non basta: mettila sul banco con l'hub e rilancia l'installazione.

I Modulino non servono per installare: il firmware si carica sul
microcontrollore anche senza.

## Lanciare l'installazione

1. Dal computer, collegati alla board:

   ```bash
   ssh arduino@amelie.local
   ```

2. Facoltativo, ma utile: apri una sessione `tmux`. tmux tiene vivo il
   terminale sulla board anche quando la connessione con il computer cade, e
   l'installazione continua.

   ```bash
   sudo apt update
   sudo apt install tmux
   tmux
   ```

   Se la connessione cade, ricollegati con `ssh arduino@amelie.local` e rientra
   nella sessione con `tmux attach`.

3. Scarica il progetto **nella cartella `~/amelie`**. `~` è la cartella di
   casa dell'utente `arduino`, cioè `/home/arduino`: i servizi di sistema
   cercano il progetto in `/home/arduino/amelie`, e lo script si ferma se lo
   trova altrove.

   ```bash
   git clone https://github.com/destone28/Amelie2.0 ~/amelie
   ```

   Se la board risponde che il comando `git` non esiste, installalo con
   `sudo apt install git` e ripeti.

4. Lancia l'installatore:

   ```bash
   cd ~/amelie
   bash scripts/install.sh
   ```

Lo script scrive un titolo per ogni passo, da `==> [1/12] Controlli` a
`==> [12/12] Console silenziosa`, e sotto qualche riga su che cosa ha fatto.
Alla fine del passo 1 chiede la password dell'utente `arduino`, una volta sola:
serve a `sudo`, e lo script la tiene valida fino alla fine. Poi lavora da solo.

La compilazione di llama.cpp, al passo 6, richiede da sola una ventina di
minuti. Il resto del tempo dipende soprattutto dalla rete: si scaricano i
pacchetti di sistema e di Python, le due voci e il modello linguistico da
380 MB.

Se la connessione cade a metà senza `tmux`, l'installazione si interrompe:
ricollegati e rilancia lo stesso comando. Ogni passo salta ciò che è già fatto.

Alla fine lo script scrive «Installazione completata.» e ricorda tre comandi:
il riavvio, lo stato dei servizi e il collaudo.

### Due variabili facoltative

Si scrivono davanti al comando, sulla stessa riga:

| Variabile | A che cosa serve |
|---|---|
| `AMELIE_FUSO=Europe/Rome` | imposta il fuso orario della board, che di fabbrica è UTC; gli orari del giornale delle scansioni seguono il fuso. Si può impostare anche dopo, con `sudo timedatectl set-timezone Europe/Rome` |
| `AMELIE_URL_MODELLO=…` | scarica il modello linguistico da un altro indirizzo, per esempio da una tua copia. Il file deve essere lo stesso: se la sua somma SHA-256 non è quella attesa, l'installazione si ferma |

Per esempio: `AMELIE_FUSO=Europe/Rome bash scripts/install.sh`.

### Se l'installazione si ferma

Quando un passo non riesce, lo script si ferma e scrive `ERRORE:` seguito dal
motivo. Rilanciarlo è sempre sicuro: riparte saltando ciò che è già fatto.

| Messaggio | Che cosa fare |
|---|---|
| «va eseguito come utente arduino, non come …» | collegati come `arduino` (`ssh arduino@amelie.local`) e lancia lo script senza `sudo` davanti |
| «il repository deve stare in /home/arduino/amelie (e' in …)» | clona il repository in `~/amelie`, come al punto 3 |
| «la board non e' in rete» | la board non raggiunge internet: controlla il Wi-Fi ([Preparare la UNO Q](01-preparare-la-uno-q.md)) |
| «servono almeno 4 GB liberi in /home/arduino (ce ne sono …)» | libera spazio nella cartella di casa; `df -h ~` dice quanto ce n'è |
| «serve la password di arduino per sudo» | la password è stata sbagliata tre volte: rilancia e scrivila con attenzione |
| «la voce … non corrisponde alla somma attesa», «modello non scaricato da …», «il modello non corrisponde alla somma attesa» | un download si è interrotto o è arrivato un file diverso: rilancia. Con `AMELIE_URL_MODELLO`, controlla l'indirizzo |
| «remoteocd non trovato …», «loader o configurazione OpenOCD del core non trovati …», «caricamento non riuscito: …» | il firmware non si è caricato sul microcontrollore: rilancia; se si ripete, togli e ridai corrente alla board e rilancia |
| «arduino-router e' fermo: …» | il servizio che collega Linux al microcontrollore è fermo: `sudo systemctl restart arduino-router`, poi rilancia |

Se a fermarsi è un comando di sistema (`apt-get`, `pip`, `cmake`, `git`,
`curl`), il messaggio è il suo, e quasi sempre la causa è la rete: rilancia.
Il passo 1 avvisa anche, senza fermarsi, se il sistema non è Debian 13
(trixie), la sola configurazione collaudata.

### Il riavvio

```bash
sudo reboot
```

La connessione SSH si chiude. All'accensione possono comparire sullo schermo,
per una decina di secondi, le scritte di avvio della board; poi lo schermo
prende il colore del marchio, compare il marchio di Amelie (il calice e il
nome) mentre il dispositivo carica le voci, e in meno di un minuto la schermata
d'attesa. Se dopo un minuto e mezzo in basso compare «Ci vuole più del
solito.», il dispositivo non è pronto: segui
[Collaudare Amelie](04-collaudo.md).

Se la board è sul banco senza schermo, ricollegati dopo un minuto e controlla
che l'applicazione sia pronta:

```bash
systemctl status amelie        # deve dire «active (running)»; si esce con q
curl -s localhost:8080/pronto  # deve rispondere {"pronta":true}
```

## Che cosa fa, passo per passo

Lo script stampa i passi numerati da 1 a 12.

**1. Controlli.** Verifica di girare come utente `arduino`, nella cartella
`/home/arduino/amelie`, con la rete e almeno 4 GB liberi nella cartella di
casa, e si ferma se manca qualcosa. Avvisa, senza fermarsi, se il sistema non
è Debian 13 (trixie), la configurazione collaudata. Poi chiede la password per
`sudo`.

**2. Pacchetti di sistema.** Python con `venv`, gli strumenti per compilare e
scaricare (`build-essential`, `cmake`, `git`, `curl`), Chromium per lo schermo,
`unclutter` per nascondere il puntatore, `x11-xserver-utils` per la modalità
video, gli strumenti per camera e audio (`v4l-utils`, `alsa-utils`) e il
carattere EB Garamond.

**3. Scheda audio all'avvio.** Su questa board, a volte, la scheda audio non
nasce: il processore audio (ADSP) può partire prima che sia pronto
`qcom_pd_mapper`, il modulo del kernel a cui si rivolge all'avvio. Una riga in
`/etc/modprobe.d/amelie-audio-race.conf` fa caricare quel modulo prima del
driver del processore audio; i casi che restano li recupera il servizio
`amelie-audio-guard` (sotto).

**4. Ambiente Python.** Un ambiente virtuale, cioè una cartella con un suo
Python e i suoi pacchetti, separati da quelli del sistema, in `~/amelie/venv`.
Dentro ci sono le versioni esatte di
[`requirements.txt`](../../requirements.txt), quelle collaudate sulla UNO Q:
OpenCV, ONNX Runtime, RapidOCR, RapidFuzz, FastAPI, Uvicorn, Piper.

**5. Motore OCR.** L'OCR è il riconoscimento del testo nelle immagini. RapidOCR
scarica le sue reti al primo uso, dentro l'ambiente virtuale; il servizio
dell'applicazione gira in una sandbox in cui quella cartella è di sola lettura,
quindi lo script le scarica qui, una volta.

**6. llama.cpp.** Il motore del modello linguistico del modo «Scritto sul
momento». Si scarica al commit collaudato e si compila `llama-server`,
ottimizzato per questo processore. È il passo lungo, una ventina di minuti; se
`llama-server` è già compilato a quel commit, si salta.

**7. Voci e modello linguistico.** Le due voci di Piper, il motore di sintesi
vocale (`it_IT-serena-medium` ed `en_US-ljspeech-medium`), da Hugging Face a
una revisione fissa, e il modello linguistico affinato (380 MB) dalla release
di questo repository. Ogni file si confronta con la sua somma SHA-256 in
[`scripts/modelli.sha256`](../../scripts/modelli.sha256): un file mancante o
diverso si scarica di nuovo, e se una voce o il modello non corrispondono
nemmeno dopo il download l'installazione si ferma.

**8. Database dei vini.** `data/build_db.py` costruisce `data/amelie.db` dai
dati aperti in `data/sources/`, in qualche minuto. Lo ricostruisce quando manca
o quando le sorgenti in `data/` o il codice sono più recenti, per esempio dopo
un `git pull` che li cambia; altrimenti scrive «gia' aggiornato». Le fonti e le
licenze sono in [Attribuzioni e licenze](08-attribuzioni.md).

**9. Firmware del microcontrollore.** Lancia `scripts/firmware.sh`. Con
`arduino-cli` installa il core `arduino:zephyr` (il supporto Arduino per il
microcontrollore della UNO Q) e la libreria `Arduino_RouterBridge` alle
versioni collaudate, compila lo sketch `firmware/amelie_mcu` e lo carica sullo
STM32U585 dalla board stessa, senza password, **insieme al loader del core**: lo
sketch parte solo se il loader sul microcontrollore è della stessa versione del
core con cui è stato compilato. Dice ad App Lab di non avviare nessuna app
all'accensione: una sua app sostituirebbe il firmware di Amelie. Poi aspetta
che il microcontrollore risponda e scrive quali Modulino vede, per esempio
«firmware caricato, il microcontrollore risponde: Pixels visto, Distance
visto». Se sketch e versioni non sono cambiati e il microcontrollore risponde
già, non ricarica niente e lo dice. Se dopo il caricamento il microcontrollore
non risponde, l'installazione prosegue e lo ricorda in fondo: vedi
[Il microcontrollore](04-collaudo.md#il-microcontrollore). Il firmware è
descritto in [`firmware/amelie_mcu/README.md`](../../firmware/amelie_mcu/README.md).

**10. Servizi.** Copia gli script dei servizi in `/usr/local/bin/` e le unità
in `/etc/systemd/system/`, installa il permesso con cui l'applicazione accende e
spegne il modello linguistico, e abilita i servizi della tabella sotto. Se
l'applicazione è già in funzione, come durante un aggiornamento, la riavvia e
ricarica la pagina sullo schermo, e scrive «applicazione riavviata».

**11. Sessione grafica.** Accesso automatico dell'utente `arduino` e, al posto
della scrivania XFCE, la sessione di Amelie: un gestore di finestre e
nient'altro. Sullo schermo compare solo il dispositivo.

**12. Console silenziosa.** Niente righe di sistema sullo schermo all'avvio,
niente Magic SysRq (i comandi d'emergenza del kernel, come «riavvia» o
«rimonta tutto in sola lettura»: la console del kernel sta su una linea seriale
di debug che nel dispositivo montato resta scollegata, e il rumore su quella
linea può essere letto come un comando), e niente cambio di console da
tastiera. Con `AMELIE_FUSO`, qui imposta anche il fuso orario.

## Dove stanno le cose

| Percorso | Che cosa c'è |
|---|---|
| `~/amelie/src/amelie/` | l'applicazione |
| `~/amelie/venv/` | l'ambiente Python |
| `~/amelie/models/` | le voci e il modello linguistico |
| `~/amelie/llama.cpp/` | llama.cpp compilato |
| `~/amelie/data/amelie.db` | il database dei vini |
| `~/amelie/vini.csv` | la carta dei vini |
| `~/amelie/var/` | ciò che il dispositivo ricorda: volume, modo, correzioni, stima della batteria, giornale delle scansioni; in `var/firmware/` il firmware compilato |
| `~/.cache/amelie/voce/` | le frasi già sintetizzate dalla voce |
| `/etc/systemd/system/amelie*.service` | i servizi |
| `/usr/local/bin/amelie-*.sh` | gli script dei servizi e della sessione grafica |
| `/etc/polkit-1/rules.d/50-amelie-llm.rules` | il permesso con cui l'applicazione accende e spegne `amelie-llm` |
| `/etc/lightdm/lightdm.conf.d/50-amelie-autologin.conf`, `/etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf`, `/usr/share/xsessions/amelie.desktop` | l'accesso automatico e la sessione grafica di Amelie |
| `/etc/modprobe.d/amelie-audio-race.conf` | l'ordine dei moduli audio (passo 3) |
| `/etc/systemd/system.conf.d/50-amelie-silenzio.conf`, `/etc/sysctl.d/99-amelie-silenzio.conf`, `/etc/X11/xorg.conf.d/10-amelie-kiosk.conf` | la console silenziosa (passo 12) |
| `/var/lib/amelie/` | il registro della guardia audio (`audio-guard.log`) e il suo contatore dei riavvii (`riavvii-audio`) |

## I servizi

Un servizio è un programma che systemd, il gestore dei servizi di Linux, avvia
all'accensione e tiene in funzione. Quelli di Amelie:

| Servizio | Che cosa fa |
|---|---|
| `amelie` | l'applicazione: camera, OCR, riconoscimento, racconto, voce, e la pagina web sulla porta 8080, che risponde solo alle richieste della board stessa (`localhost`) |
| `amelie-kiosk` | Chromium a tutto schermo: parte dalla schermata con il marchio e passa alla pagina dell'applicazione quando il dispositivo è pronto |
| `amelie-display` | porta lo schermo a 1280 × 720 (alla sua risoluzione nativa, 800 × 480, il pannello resta nero) e gli impedisce di spegnersi: a schermo spento si perde anche l'audio |
| `amelie-audio-guard` | all'avvio controlla che la scheda audio esista; se manca riavvia il processore audio e, se non basta, la board: una volta sola, e solo nei primi dieci minuti dall'accensione |
| `amelie-audio-rotta` | apre la strada del suono verso l'HDMI (un controllo del mixer che a ogni avvio torna chiuso) |
| `amelie-sipario` | tinge la console del colore del marchio e toglie il testo, finché parte la grafica |
| `amelie-scrivania` | spegne ciò che la scrivania XFCE avvia da sola e che sul dispositivo non va (App Lab, il blocco dello schermo, le icone di rete e Bluetooth), nel caso la scrivania torni |
| `amelie-llm` | il modello linguistico (`llama-server`); **non** è abilitato all'avvio: lo accende e lo spegne l'applicazione, solo nel modo «Scritto sul momento» |

Comandi utili, sulla board:

```bash
systemctl status 'amelie*'                 # lo stato di tutti (si esce con q)
journalctl -u amelie -f                    # il giornale dell'applicazione, dal vivo (si esce con Ctrl+C)
sudo systemctl restart amelie              # riavvia l'applicazione
sudo systemctl restart amelie-kiosk        # ricarica la pagina sullo schermo
curl -s localhost:8080/stato | python3 -m json.tool    # lo stato tecnico
```

Il giornale di sistema (journal) è il registro in cui systemd raccoglie i
messaggi dei servizi; `journalctl` lo legge. Lo stato tecnico è lo stesso che
si apre sullo schermo dalle impostazioni, «Stato tecnico» (vedi
[Usare Amelie](05-uso.md)).

## Il servizio parte nel modo «Dall'archivio»

L'applicazione parte con il modello linguistico installato e sceglibile
(`--con-modello --modello-addestrato`) e con la carta dei vini accanto al
codice (`--carta /home/arduino/amelie/vini.csv`), ma un dispositivo appena
installato racconta **dall'archivio**: compone il racconto dai fatti del
database, senza modello. Il modo si cambia dalle impostazioni sullo schermo,
alla voce «Come racconta», e il dispositivo lo ricorda in `var/modo`. Vedi
[Usare Amelie](05-uso.md).

## Aggiornare

Sulla board:

```bash
cd ~/amelie
git pull
bash scripts/install.sh
```

`git pull` scarica le modifiche dal repository. L'installatore rifà solo ciò
che è cambiato: il database se sono cambiate le sorgenti o il codice, il
firmware se sono cambiati lo sketch o le versioni del core e della libreria, o
se il microcontrollore non risponde. Se l'applicazione è in funzione, al passo
10 la riavvia e ricarica la pagina sullo schermo. Le modifiche agli altri
servizi, alla sessione grafica e alla console valgono dal riavvio successivo:
nel dubbio, `sudo reboot`. Le impostazioni e le correzioni in `var/` restano.

Dopo un aggiornamento di App Lab o di sistema (`arduino-app-cli system
update`), rilancia anche il firmware:

```bash
cd ~/amelie
bash scripts/firmware.sh
```

App Lab, aggiornandosi, può portare sul microcontrollore il loader della sua
versione, e lo sketch di Amelie parte solo con un loader della stessa versione
del core con cui è stato compilato. Se il microcontrollore risponde ancora, lo
script lo dice e non tocca niente; altrimenti ricarica sketch e loader insieme.

### Dal PC, senza passare da git

Chi modifica il codice su un PC può provarlo sulla board con
`scripts/rilascio.sh`, che si lancia **sul PC**, dalla cartella del repository:

```bash
bash scripts/rilascio.sh                                         # sulla board arduino@amelie.local
bash scripts/rilascio.sh --host arduino@<indirizzo-della-board>  # su un'altra board
```

Copia sulla board codice, pagina, lessico, database e test (la prima volta
tiene una copia del database della board, `data/amelie.db.prima-del-rilascio`),
fa girare i test sulla board e riavvia l'applicazione e il chiosco. Voci, modello
linguistico e firmware non li tocca. Servono:

- una board già installata con `scripts/install.sh`;
- l'accesso SSH a chiave (`ssh-copy-id`, vedi
  [Preparare la UNO Q](01-preparare-la-uno-q.md)): lo script si collega molte
  volte, e senza chiave chiederebbe la password a ogni collegamento;
- il database costruito sul PC: `PYTHONPATH=src python3 data/build_db.py`;
- per i test, pytest nell'ambiente Python della board (vedi
  [I test automatici](04-collaudo.md#i-test-automatici)).

Il riavvio finale usa `sudo` attraverso SSH, senza un terminale da cui chiedere
la password: se `sudo` sulla board chiede la password, quel passo non riesce e
l'applicazione continua a girare con il codice che aveva. In quel caso, sulla
board: `sudo systemctl restart amelie` e poi
`sudo systemctl restart amelie-kiosk`.

I file copiati in questo modo compaiono nel clone della board come modifiche
locali, e il `git pull` successivo può rifiutarsi di sovrascriverli: sulla
board, `cd ~/amelie && git checkout -- .` li riporta alla versione del
repository.

## Tornare alla scrivania

Per usare la board con schermo, tastiera e mouse come un piccolo computer, con
la scrivania XFCE:

```bash
sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
sudo systemctl disable --now amelie-kiosk
sudo systemctl restart lightdm
```

Il primo comando toglie la sessione di Amelie; il secondo spegne Chromium a
tutto schermo, che altrimenti coprirebbe la scrivania, anche ai riavvii
successivi; il terzo fa ripartire la grafica. L'applicazione continua a girare.

Per tornare alla sessione di Amelie: `cd ~/amelie && bash scripts/install.sh`,
che rimette la sessione e riabilita il chiosco, poi `sudo reboot`.

## Mettere in sicurezza

Il dispositivo sta su un tavolo, dove chiunque può metterci le mani. Prima di
lasciarlo in sala, sulla board:

**sudo senza password.** Una UNO Q nuova chiede la password per `sudo`. Se,
mentre lavoravi sulla board, hai attivato `sudo` senza password, toglilo: qui
il file si chiama `010_arduino-nopasswd`, usa il nome del file che hai creato
in `/etc/sudoers.d/`. Poi controlla:

```bash
sudo rm -f /etc/sudoers.d/010_arduino-nopasswd
sudo -k
sudo -n true 2>/dev/null && echo "sudo senza password ancora attivo" || echo "ok"
```

`sudo -k` fa dimenticare a `sudo` la password appena scritta, e `sudo -n true`
prova a usarlo senza chiederla. L'ultima riga deve stampare `ok`.

**I pacchetti dell'audio.** Blocca i pacchetti da cui dipende l'audio, così un
aggiornamento non può sostituire i profili audio della board:

```bash
sudo apt-mark hold alsa-ucm-conf "linux-image-$(uname -r)"
```

Per sbloccarli, `sudo apt-mark unhold` con gli stessi nomi.

**SSH.** Lascialo acceso solo con l'accesso a chiave. Prima copia la tua chiave
dal computer (`ssh-copy-id arduino@amelie.local`, vedi
[Preparare la UNO Q](01-preparare-la-uno-q.md)) e controlla che
`ssh arduino@amelie.local` entri senza chiedere la password: senza una chiave
che funziona, spente le password, in SSH non si entra più. Poi, sulla board:

```bash
echo 'PasswordAuthentication no' | sudo tee /etc/ssh/sshd_config.d/00-amelie.conf
sudo systemctl restart ssh
sudo sshd -T | grep -i '^passwordauthentication'
```

L'ultimo comando deve rispondere `passwordauthentication no`. In alternativa
si spegne del tutto l'SSH con `sudo systemctl disable --now ssh`. Dopo un
riavvio, dal computer, `ssh arduino@amelie.local` deve fallire; se risponde
ancora, spegni la modalità rete con
`arduino-app-cli system network-mode disable`, che chiede la password di
`arduino`. Per riaccendere l'SSH bisogna poi riaprire il dispositivo e
collegare la board al computer con il cavo USB-C (`adb shell`, vedi
[Preparare la UNO Q](01-preparare-la-uno-q.md)).

I servizi `amelie` e `amelie-llm` girano già confinati da systemd
(`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`): l'applicazione non
può riscrivere il proprio codice né il sistema. La misura più efficace resta
fisica: l'hub e la board stanno dentro la scocca chiusa, e l'unica presa che si
raggiunge da fuori è quella di ricarica, che arriva al power bank e non alla
board.

## Il passo successivo

[Montare Amelie](03-montaggio.md).
