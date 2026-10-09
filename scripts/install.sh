#!/usr/bin/env bash
# Amelie 2.0 - installa il dispositivo su una Arduino UNO Q.
#
#   git clone https://github.com/destone28/Amelie2.0 ~/amelie
#   cd ~/amelie && bash scripts/install.sh
#
# Va eseguito SULLA BOARD, come utente `arduino`, con la board in rete. La guida
# passo passo e' in docs/it/02-installazione.md (docs/en/02-install.md).
#
# Si puo' rilanciare quante volte si vuole: ogni passo salta cio' che e' gia'
# a posto. Per aggiornare un dispositivo gia' installato:
#
#   cd ~/amelie && git pull && bash scripts/install.sh
#
# Variabili facoltative:
#   AMELIE_FUSO=Europe/Rome     imposta il fuso orario (la board nasce in UTC)
#   AMELIE_URL_MODELLO=...      da dove scaricare il modello linguistico
set -euo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASA=/home/arduino/amelie

# Le versioni collaudate. Ognuna e' fissata: una board installata fra un anno
# deve essere uguale a quella di oggi.
LLAMA_COMMIT=74a7c897f049c17e7080423aa2111776eff6ebbf
# Quelle del microcontrollore stanno in scripts/firmware.sh.
VOCI_REV=ea046e8458f6acd997706d6e6066a022b42f6fb1
URL_VOCI="https://huggingface.co/rhasspy/piper-voices/resolve/$VOCI_REV"
VOCI="it/it_IT/serena/medium/it_IT-serena-medium en/en_US/ljspeech/medium/en_US-ljspeech-medium"
MODELLO=studente-q4_k_m.gguf
URL_MODELLO="${AMELIE_URL_MODELLO:-https://github.com/destone28/Amelie2.0/releases/download/v1.0.0/$MODELLO}"

G=$'\033[32m'; R=$'\033[31m'; N=$'\033[0m'
PASSI=12
passo() { echo; echo "${G}==> [$1/$PASSI]${N} $2"; }
avviso() { echo "    ${R}!${N} $*"; }
muori() { echo; echo "${R}ERRORE:${N} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
passo 1 "Controlli"
[ "$(id -un)" = arduino ] || muori "va eseguito come utente arduino, non come $(id -un)"
# Le unita' systemd puntano a /home/arduino/amelie: il repository deve stare li'.
[ "$RADICE" = "$CASA" ] || muori "il repository deve stare in $CASA (e' in $RADICE)"
grep -q 'VERSION_CODENAME=trixie' /etc/os-release \
    || avviso "sistema diverso da Debian 13 (trixie): non e' la configurazione collaudata"
curl -sfI -m 10 https://deb.debian.org >/dev/null || muori "la board non e' in rete"
LIBERI=$(df --output=avail -BG "$HOME" | tail -1 | tr -dc 0-9)
[ "$LIBERI" -ge 4 ] || muori "servono almeno 4 GB liberi in $HOME (ce ne sono $LIBERI)"
echo "    utente arduino, $CASA, in rete, ${LIBERI} GB liberi"

# Una sola password per tutta l'installazione: la compilazione di llama.cpp
# dura piu' dei quindici minuti per cui sudo la ricorda. `sudo -v` la chiede
# anche a chi ha sudo senza password, se una qualunque regola la vuole: prima
# si prova senza.
sudo -n true 2>/dev/null || sudo -v || muori "serve la password di arduino per sudo"
( while kill -0 "$$" 2>/dev/null; do sudo -n true; sleep 50; done ) 2>/dev/null &

cd "$RADICE"
mkdir -p models var

# ---------------------------------------------------------------------------
passo 2 "Pacchetti di sistema"
sudo apt-get update -qq
# fonts-ebgaramond: il carattere dell'interfaccia, anche fuori dalla pagina.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3-venv python3-pip python3-dev build-essential cmake git curl \
    libcurl4-openssl-dev v4l-utils alsa-utils \
    chromium unclutter x11-xserver-utils fonts-ebgaramond >/dev/null
echo "    fatto"

# ---------------------------------------------------------------------------
passo 3 "Scheda audio all'avvio"
# Il PD mapper va caricato prima del driver remoteproc: se l'ADSP parte prima
# che il servizio sia pronto la scheda audio non nasce. Una riga softdep
# equivale alla correzione proposta upstream da Loic Poulain (Linaro) con
# MODULE_SOFTDEP("pre: qcom_pd_mapper"), senza ricompilare il kernel. Il resto
# lo fa amelie-audio-guard, al passo 10.
CONF=/etc/modprobe.d/amelie-audio-race.conf
if [ ! -f "$CONF" ]; then
    sudo tee "$CONF" >/dev/null <<'EOF'
# Il PD mapper prima del driver remoteproc: senza, l'ADSP puo' partire prima
# che il servizio sia pronto e la scheda audio non nasce.
softdep qcom_common pre: qcom_pd_mapper
EOF
    sudo update-initramfs -u >/dev/null 2>&1 || true
fi
echo "    fatto"

# ---------------------------------------------------------------------------
passo 4 "Ambiente Python"
[ -x venv/bin/python ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
echo "    $(./venv/bin/python --version), $(./venv/bin/pip list 2>/dev/null | wc -l) pacchetti"

# ---------------------------------------------------------------------------
passo 5 "Motore OCR"
# I modelli PP-OCR li scarica RapidOCR al primo uso, dentro l'ambiente
# virtuale. Il servizio li troverebbe in una cartella di sola lettura
# (ProtectSystem=strict), quindi si caricano qui, una volta.
PYTHONPATH=src ./venv/bin/python - <<'PY'
import logging
logging.disable(logging.WARNING)
from amelie.ocr import Lettore
Lettore()._carica()
print("    modelli OCR pronti")
PY

# ---------------------------------------------------------------------------
passo 6 "llama.cpp"
# Il modello linguistico gira su llama-server. La compilazione richiede una
# ventina di minuti; al secondo giro si salta.
LLAMA="$RADICE/llama.cpp"
if [ -x "$LLAMA/build/bin/llama-server" ] \
        && [ "$(git -C "$LLAMA" rev-parse HEAD 2>/dev/null)" = "$LLAMA_COMMIT" ]; then
    echo "    gia' compilato al commit ${LLAMA_COMMIT:0:7}"
else
    if [ ! -d "$LLAMA/.git" ]; then
        rm -rf "$LLAMA"
        git init -q "$LLAMA"
        git -C "$LLAMA" remote add origin https://github.com/ggml-org/llama.cpp
    fi
    git -C "$LLAMA" fetch -q --depth 1 origin "$LLAMA_COMMIT"
    git -C "$LLAMA" checkout -q --force FETCH_HEAD
    echo "    compilo llama-server (una ventina di minuti)"
    cmake -S "$LLAMA" -B "$LLAMA/build" -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON >/dev/null
    cmake --build "$LLAMA/build" -j"$(nproc)" --target llama-server >/dev/null
    echo "    llama-server compilato"
fi

# ---------------------------------------------------------------------------
passo 7 "Voci e modello linguistico"
scarica() {   # scarica URL FILE: su un file temporaneo, e lo rinomina a fine riuscita
    curl -fL --retry 3 --progress-bar -o "$2.parziale" "$1" && mv "$2.parziale" "$2"
}
controlla() { # il file c'e' e ha la somma attesa
    [ -f "models/$1" ] && (cd models && grep " $1\$" ../scripts/modelli.sha256 | sha256sum -c --status)
}
for percorso in $VOCI; do
    voce="${percorso##*/}"
    for est in onnx onnx.json; do
        controlla "$voce.$est" || scarica "$URL_VOCI/$percorso.$est" "models/$voce.$est"
    done
    for est in onnx onnx.json; do
        controlla "$voce.$est" || muori "$voce.$est non corrisponde alla somma attesa"
    done
done
echo "    voci: it_IT-serena-medium, en_US-ljspeech-medium"
if ! controlla "$MODELLO"; then
    echo "    scarico il modello linguistico (380 MB)"
    scarica "$URL_MODELLO" "models/$MODELLO" \
        || muori "modello non scaricato da $URL_MODELLO"
fi
controlla "$MODELLO" || muori "il modello non corrisponde alla somma attesa"
echo "    modello: $MODELLO"

# ---------------------------------------------------------------------------
passo 8 "Database dei vini"
# Si ricostruisce dalle sorgenti in data/ quando manca o quando le sorgenti
# sono piu' recenti: dopo un `git pull` che le cambia, si rifa' da solo.
DB=data/amelie.db
if [ ! -f "$DB" ] || [ -n "$(find data src/amelie -type f -newer "$DB" \
        \( -path 'data/sources/*' -o -path 'data/lessico/*' -o -name '*.py' -o -name vitigni.json \) \
        -not -path '*/__pycache__/*' -print -quit)" ]; then
    PYTHONPATH=src ./venv/bin/python data/build_db.py | tail -2
else
    echo "    gia' aggiornato"
fi

# ---------------------------------------------------------------------------
passo 9 "Firmware del microcontrollore"
# Lo sketch gira sullo STM32U585 e parla con Linux attraverso il router. Lo
# compila e lo carica scripts/firmware.sh, insieme al loader del core, e lo
# dichiara caricato solo se il microcontrollore poi risponde: vedi la sua
# intestazione. Se non risponde l'installazione prosegue, perche' il resto del
# dispositivo serve anche a capire il guasto, e lo ricorda in fondo.
MCU_OK=1
bash "$RADICE/scripts/firmware.sh" || MCU_OK=0

# ---------------------------------------------------------------------------
passo 10 "Servizi"
sudo install -m755 scripts/systemd/*.sh /usr/local/bin/
sudo install -m644 scripts/systemd/*.service /etc/systemd/system/
# Il permesso con cui l'applicazione accende e spegne il modello linguistico.
sudo install -m644 scripts/systemd/50-amelie-llm.rules /etc/polkit-1/rules.d/
sudo mkdir -p /var/lib/amelie /usr/share/xsessions
sudo install -m644 scripts/systemd/amelie.desktop /usr/share/xsessions/
sudo systemctl daemon-reload
# amelie-llm non si abilita: lo accende l'applicazione quando il modo di
# racconto e' «generativa», e lo spegne altrimenti. Acceso a vuoto costa un core.
sudo systemctl disable amelie-llm >/dev/null 2>&1 || true
sudo systemctl enable -q amelie-audio-guard amelie-audio-rotta \
    amelie-sipario amelie-display amelie amelie-kiosk amelie-scrivania
# Su un dispositivo gia' in servizio (un aggiornamento) il codice nuovo vale
# solo dopo il riavvio dell'applicazione, e la pagina nuova solo ricaricandola.
if systemctl is-active -q amelie; then
    sudo systemctl restart amelie
    sudo systemctl try-restart amelie-kiosk
    echo "    applicazione riavviata"
fi
echo "    fatto"

# ---------------------------------------------------------------------------
passo 11 "Sessione grafica"
# Autologin: senza, il server X appartiene al greeter e Chromium non riesce ad
# aprirlo («The platform failed to initialize»).
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-amelie-autologin.conf >/dev/null <<'EOF'
[Seat:*]
autologin-user=arduino
autologin-user-timeout=0
EOF
# E la sessione e' quella di Amelie, non la scrivania XFCE: sul pannello
# compare solo il dispositivo. Per riavere la scrivania:
#     sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
#     sudo systemctl restart lightdm
sudo tee /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf >/dev/null <<'EOF'
[Seat:*]
user-session=amelie
autologin-session=amelie
EOF
echo "    fatto"

# ---------------------------------------------------------------------------
passo 12 "Console silenziosa"
# Niente righe «[ OK ] Started ...» sul pannello: restano nel journal.
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/50-amelie-silenzio.conf >/dev/null <<'EOF'
[Manager]
ShowStatus=no
EOF
# 99, non 50: i file di sysctl.d si applicano in ordine alfabetico, e Debian
# mette il suo kernel.sysrq in 50-default.conf, che sovrascriverebbe il nostro.
sudo tee /etc/sysctl.d/99-amelie-silenzio.conf >/dev/null <<'EOF'
# Solo le emergenze sulla console; tutto il resto e' nel journal.
kernel.printk = 1 4 1 3

# Niente Magic SysRq. La console del kernel sta su ttyMSM0, la UART di debug,
# che nel dispositivo montato non ha niente collegato e resta flottante: il
# rumore sulla linea viene letto come tasti SysRq, e fra questi ci sono
# «rimonta tutto in sola lettura», «riavvia» e «spegni».
kernel.sysrq = 0
EOF
# Nemmeno da tastiera: Ctrl+Alt+F2 su una tastiera collegata a una porta USB
# porterebbe a un prompt di login a schermo intero.
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/10-amelie-kiosk.conf >/dev/null <<'EOF'
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap"      "true"
EndSection
EOF
if [ -n "${AMELIE_FUSO:-}" ]; then
    sudo timedatectl set-timezone "$AMELIE_FUSO" && echo "    fuso orario: $AMELIE_FUSO"
fi
echo "    fatto"

echo
echo "${G}Installazione completata.${N}"
echo
echo "  Riavvia la board:        sudo reboot"
echo "  Stato dei servizi:       systemctl status 'amelie*'"
echo "  Collaudo:                bash scripts/00_diagnostica.sh"
echo
echo "  Per mettere il dispositivo in sicurezza prima di lasciarlo in sala"
echo "  vedi docs/it/02-installazione.md, «Mettere in sicurezza»."
if [ "$MCU_OK" = 0 ]; then
    echo
    avviso "Il microcontrollore non risponde: luce e sensore di distanza non"
    avviso "funzioneranno, e senza sensore il dispositivo non vede le bottiglie."
    avviso "Dopo il riavvio: bash scripts/firmware.sh --sempre"
    avviso "Guida: docs/it/04-collaudo.md, «Il microcontrollore»."
fi
