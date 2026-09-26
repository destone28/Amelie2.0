# Installare il software

Tutto il software di Amelie si installa con uno script, `scripts/install.sh`,
che gira sulla UNO Q. Questa guida spiega come lanciarlo, che cosa fa passo per
passo, dove mette le cose e come si aggiorna il dispositivo.

Prima serve una board preparata come in
[Preparare la UNO Q](01-preparare-la-uno-q.md): con un nome, una password, la
rete e raggiungibile in SSH.

## Dove sta la board mentre installi

All'installazione serve solo la rete. La board può stare:

- **sul banco, collegata all'hub** con il suo alimentatore o il power bank,
  anche senza schermo e camera: è il modo consigliato;
- **già montata** nel dispositivo;
- **collegata al computer** con il cavo USB-C. Funziona, ma la compilazione di
  llama.cpp tiene i quattro core al massimo per una ventina di minuti: usa una
  porta del computer che dia almeno 1,5 A, oppure un hub alimentato.

I Modulino non servono per installare: il firmware si carica sul
microcontrollore anche senza.

## Lanciare l'installazione

Collegati alla board e clona il repository **in `/home/arduino/amelie`**: i
servizi di sistema cercano il progetto lì.

```bash
ssh arduino@amelie.local
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

Lo script chiede una volta la password dell'utente `arduino` (per `sudo`) e poi
lavora da solo. Ci vuole circa un'ora, quasi tutta per compilare llama.cpp e
scaricare i pacchetti Python. Se la connessione SSH cade a metà, rilancia lo
stesso comando: ogni passo salta ciò che è già fatto. Per non dipendere dalla
connessione puoi lanciarlo dentro `tmux` o `screen`, oppure così:

```bash
nohup bash scripts/install.sh > ~/installazione.log 2>&1 &
tail -f ~/installazione.log
```

Due variabili facoltative:

| Variabile | A che cosa serve |
|---|---|
| `AMELIE_FUSO=Europe/Rome` | imposta il fuso orario; la board nasce in UTC, e gli orari del giornale delle scansioni seguono il fuso |
| `AMELIE_URL_MODELLO=…` | scarica il modello linguistico da un altro indirizzo |

Per esempio: `AMELIE_FUSO=Europe/Rome bash scripts/install.sh`.

Alla fine:

```bash
sudo reboot
```

Dopo il riavvio lo schermo mostra il marchio, poi la schermata d'attesa. Se la
board è ancora sul banco senza schermo, il servizio parte lo stesso: lo si vede
con `systemctl status amelie`.

## Che cosa fa, passo per passo

Lo script stampa i passi numerati da 1 a 12.

**1. Controlli.** Verifica di girare come utente `arduino`, nella cartella
giusta, con la rete e almeno 4 GB liberi. Avvisa se il sistema non è Debian 13,
la configurazione collaudata.

**2. Pacchetti di sistema.** Python con `venv`, gli strumenti di compilazione
(`build-essential`, `cmake`), Chromium per lo schermo, `unclutter` per
nascondere il puntatore, gli strumenti per camera e audio (`v4l-utils`,
`alsa-utils`) e il carattere EB Garamond.

**3. Scheda audio all'avvio.** Su questa board, a volte, la scheda audio non
nasce: il processore audio (ADSP) parte prima che il servizio che lo aspetta sia
pronto. Una riga in `/etc/modprobe.d/amelie-audio-race.conf` fa caricare prima
il modulo giusto; il resto lo fa il servizio `amelie-audio-guard` (sotto).

**4. Ambiente Python.** Un ambiente virtuale in `~/amelie/venv` con le versioni
esatte di [`requirements.txt`](../../requirements.txt), quelle collaudate sulla
UNO Q: OpenCV, ONNX Runtime, RapidOCR, RapidFuzz, FastAPI, Uvicorn, Piper.

**5. Motore OCR.** RapidOCR scarica le sue reti al primo uso. Il servizio gira
in una sandbox che non può scrivere nell'ambiente virtuale, quindi lo script le
carica qui, una volta.

**6. llama.cpp.** Il motore del modello linguistico del modo «Scritto sul
momento». Si scarica al commit collaudato e si compila `llama-server`
ottimizzato per questo processore. È il passo lungo, e al secondo giro si salta.

**7. Voci e modello linguistico.** Le due voci di Piper (`it_IT-serena-medium`
ed `en_US-ljspeech-medium`) da Hugging Face, a una revisione fissa, e il
modello linguistico affinato (380 MB) dalla release di questo repository.
Ogni file si controlla con la sua somma SHA-256 in
[`scripts/modelli.sha256`](../../scripts/modelli.sha256): un file diverso ferma
l'installazione.

**8. Database dei vini.** `data/build_db.py` costruisce `data/amelie.db` dai
dati aperti in `data/sources/`, in qualche minuto. Si rifà da solo quando le
sorgenti o il codice cambiano (dopo un `git pull`). Le fonti e le licenze sono
in [Attribuzioni e licenze](08-attribuzioni.md).

**9. Firmware del microcontrollore.** Installa il core `arduino:zephyr` e la
libreria `Arduino_RouterBridge` alle versioni collaudate, compila lo sketch
`firmware/amelie_mcu` e lo carica sullo STM32U585 dalla board stessa, senza
password. Poi dice ad App Lab di non avviare nessuna app all'accensione: una sua
app sostituirebbe il firmware di Amelie. Il firmware è descritto in
[`firmware/amelie_mcu/README.md`](../../firmware/amelie_mcu/README.md).

**10. Servizi.** Installa e abilita i servizi di sistema (tabella sotto).

**11. Sessione grafica.** Accesso automatico dell'utente `arduino` e, al posto
della scrivania XFCE, la sessione di Amelie: un gestore di finestre e nient'altro.
Sullo schermo compare solo il dispositivo.

**12. Console silenziosa.** Niente righe di sistema sullo schermo all'avvio,
niente Magic SysRq (la console del kernel sta su una linea seriale di debug che
nel dispositivo montato resta scollegata, e il rumore su quella linea può essere
letto come un comando), e niente cambio di console da tastiera.

## Dove stanno le cose

| Percorso | Che cosa c'è |
|---|---|
| `~/amelie/src/amelie/` | l'applicazione |
| `~/amelie/venv/` | l'ambiente Python |
| `~/amelie/models/` | le voci e il modello linguistico |
| `~/amelie/llama.cpp/` | llama.cpp compilato |
| `~/amelie/data/amelie.db` | il database dei vini |
| `~/amelie/vini.csv` | la carta dei vini |
| `~/amelie/var/` | ciò che il dispositivo ricorda: volume, modo, correzioni, giornale delle scansioni |
| `/etc/systemd/system/amelie*.service` | i servizi |
| `/usr/local/bin/amelie-*.sh` | gli script dei servizi |
| `/var/lib/amelie/` | il registro della guardia audio |

## I servizi

| Servizio | Che cosa fa |
|---|---|
| `amelie` | l'applicazione: camera, OCR, riconoscimento, racconto, voce, la pagina web sulla porta 8080 |
| `amelie-kiosk` | Chromium a tutto schermo sulla pagina dell'applicazione |
| `amelie-display` | porta lo schermo a 1280 × 720 e gli impedisce di spegnersi: a schermo spento si perde anche l'audio |
| `amelie-audio-guard` | all'avvio controlla che la scheda audio esista; se manca riavvia il processore audio, e al massimo una volta la board |
| `amelie-audio-rotta` | apre la strada del suono verso l'HDMI (un controllo del mixer che a ogni avvio torna chiuso) |
| `amelie-sipario` | tinge la console del colore del marchio e toglie il testo, finché parte la grafica |
| `amelie-scrivania` | spegne ciò che la scrivania avvierebbe da sola, se la si rimette |
| `amelie-llm` | il modello linguistico; **non** è abilitato: lo accende l'applicazione solo nel modo «Scritto sul momento» |

Comandi utili:

```bash
systemctl status 'amelie*'                 # lo stato di tutti
journalctl -u amelie -f                    # il registro dell'applicazione, dal vivo
sudo systemctl restart amelie              # riavvia l'applicazione
sudo systemctl restart amelie-kiosk        # ricarica la pagina sullo schermo
curl -s localhost:8080/stato | python3 -m json.tool
```

## Il servizio parte nel modo «archivio»

L'applicazione parte con il modello linguistico installato e sceglibile
(`--con-modello --modello-addestrato`) e con la carta dei vini accanto al
codice (`--carta /home/arduino/amelie/vini.csv`), ma un dispositivo appena
installato racconta **dall'archivio**. Il modo si cambia dalle impostazioni
sullo schermo, ed è ricordato in `var/modo`. Vedi [Usare Amelie](05-uso.md).

## Aggiornare

Sulla board:

```bash
cd ~/amelie
git pull
bash scripts/install.sh
```

L'installatore rifà solo ciò che è cambiato: il database se sono cambiate le
sorgenti o il codice, il firmware se è cambiato lo sketch. Alla fine riavvia
l'applicazione e ricarica la pagina sullo schermo. Le impostazioni e le
correzioni in `var/` restano.

Chi modifica il codice su un PC può portarlo sulla board senza passare da git
con `scripts/rilascio.sh`; lo script spiega come in testa.

## Tornare alla scrivania

Per lavorare sulla board con schermo, tastiera e mouse, come un piccolo
computer:

```bash
sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
sudo systemctl restart lightdm
```

Per rimettere la sessione di Amelie basta rilanciare `bash scripts/install.sh`.

## Mettere in sicurezza

Il dispositivo sta su un tavolo, dove chiunque può metterci le mani. Prima di
lasciarlo in sala:

```bash
# Se esiste, togli il sudo senza password: 'sudo -n true' deve poi fallire.
sudo rm -f /etc/sudoers.d/010_arduino-nopasswd
sudo -n true && echo "sudo senza password ancora attivo" || echo "ok"

# Blocca i pacchetti da cui dipende l'audio: un aggiornamento automatico
# potrebbe sostituire i profili audio della board.
sudo apt-mark hold alsa-ucm-conf "linux-image-$(uname -r)"

# SSH solo con chiave (dopo aver copiato la tua con ssh-copy-id), oppure spento.
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
# oppure: sudo systemctl disable --now ssh
```

I servizi `amelie` e `amelie-llm` girano già confinati (`ProtectSystem=strict`,
`NoNewPrivileges`, `PrivateTmp`): l'applicazione non può riscrivere il proprio
codice né il sistema. La misura più efficace resta fisica: le porte USB libere
dell'hub stanno dentro la scocca.

## Il passo successivo

[Montare il dispositivo](03-montaggio.md).
