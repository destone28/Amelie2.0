#!/usr/bin/env bash
# Amelie 2.0 - installazione completa su una UNO Q pulita.
#
# Non esiste un modo affidabile di clonare la eMMC: il `dd` di una UNO Q
# ripristinato su un'altra va in kernel panic. Questo script E' il modo di
# riprodurre il dispositivo.
#
#   bash scripts/install.sh                 installa tutto
#   bash scripts/install.sh --senza-modello salta lo scaricamento dell'LLM
#
# Va eseguito SULLA BOARD, come utente arduino, con sudo senza password oppure
# rispondendo alle richieste.
set -euo pipefail

RADICE="${RADICE:-$HOME/amelie}"
MODELLO_LLM="gemma-3-1b-it-Q4_K_M.gguf"
URL_LLM="https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/$MODELLO_LLM"
# Una voce per lingua. Entrambe addestrate DA ZERO su dataset liberi: vedi
# docs/ATTRIBUZIONI.md per il perche' non si prendono le piu' diffuse.
BASE_VOCI="https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOCI="it/it_IT/serena/medium/it_IT-serena-medium en/en_US/ljspeech/medium/en_US-ljspeech-medium"

SALTA_MODELLO=0
[ "${1:-}" = "--senza-modello" ] && SALTA_MODELLO=1

G=$'\033[32m'; N=$'\033[0m'
passo() { echo; echo "${G}==>${N} $*"; }

passo "1/10  Pacchetti di sistema"
sudo apt-get update -qq
# fonts-ebgaramond: l'interfaccia lo DICHIARA, e finche' non era installato il
# testo usciva col serif generico della distribuzione. Non e' la stessa cosa: un
# Garamond ha l'occhio medio molto piu' piccolo di un Noto Serif, quindi a
# parita' di corpo il testo cambia di misura apparente e di dove va a capo, e
# tutte le misure su cui e' disegnata questa interfaccia saltano.
sudo apt-get install -y -qq \
    python3-venv python3-pip python3-dev build-essential cmake git curl \
    v4l-utils alsa-utils \
    chromium unclutter x11-xserver-utils \
    libcurl4-openssl-dev \
    fonts-ebgaramond

passo "2/10  Correzione della corsa all'avvio dell'audio"
# Mitigazione proposta upstream da Loic Poulain (Linaro) per la UNO Q:
# MODULE_SOFTDEP("pre: qcom_pd_mapper"). Una riga softdep qui e' equivalente,
# quindi il fix si applica senza ricompilare il kernel.
sudo tee /etc/modprobe.d/amelie-audio-race.conf >/dev/null <<'EOF'
# Carica il PD mapper prima del driver remoteproc: senza, l'ADSP puo' partire
# prima che il servizio sia pronto, la protection domain audio non nasce e la
# scheda audio non esiste. Misurato: succedeva in 2 avvii su 6.
softdep qcom_common pre: qcom_pd_mapper
EOF
sudo update-initramfs -u >/dev/null 2>&1 || true

passo "3/10  Ambiente Python"
mkdir -p "$RADICE"
cd "$RADICE"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q \
    numpy opencv-python-headless onnxruntime rapidocr rapidfuzz msgpack \
    fastapi "uvicorn[standard]" piper-tts

passo "4/10  llama.cpp"
if [ ! -x "$RADICE/llama.cpp/build/bin/llama-server" ]; then
    [ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp
    cd llama.cpp
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON >/dev/null
    cmake --build build -j"$(nproc)" --target llama-server llama-cli llama-bench >/dev/null
    cd "$RADICE"
fi

passo "5/10  Modelli"
mkdir -p models
if [ "$SALTA_MODELLO" = 0 ] && [ ! -f "models/$MODELLO_LLM" ]; then
    echo "    scarico il modello linguistico (~700 MB)"
    curl -sL --retry 3 -o "models/$MODELLO_LLM" "$URL_LLM"
fi
# I Gemma Terms of Use, par. 3.1, impongono che ogni distribuzione dei pesi sia
# accompagnata da questo avviso. Cedere un dispositivo con il modello a
# bordo E' una distribuzione.
cat > models/NOTICE <<'EOF'
Gemma is provided under and subject to the Gemma Terms of Use found at
ai.google.dev/gemma/terms
EOF
for percorso in $VOCI; do
    voce="${percorso##*/}"
    for est in onnx onnx.json; do
        [ -f "models/$voce.$est" ] || curl -sL --retry 3 \
            -o "models/$voce.$est" "$BASE_VOCI/$percorso.$est" || true
    done
done

passo "6/10  Database dei vini"
[ -f data/amelie.db ] || ./venv/bin/python data/build_db.py

passo "7/10  Librerie del microcontrollore"
# Il firmware gira sullo STM32U585, non su Linux: si carica a parte e va
# lanciato da un terminale vero, perche' il caricamento in rete puo' chiedere la
# password dell'utente. Le librerie, pero', si installano bene da qui - sono
# l'unico pezzo che manca per poter compilare, ed e' scomodo scoprirlo davanti
# ai Modulino gia' collegati.
if command -v arduino-cli >/dev/null 2>&1; then
    arduino-cli lib install Arduino_RouterBridge Arduino_Modulino >/dev/null 2>&1 \
        && echo "    Arduino_RouterBridge e Arduino_Modulino installate" \
        || echo "    librerie non installate: rifallo a mano prima di caricare il firmware"
    # L'indirizzo risolto, non la formula: questo comando si copia e si incolla.
    IP_BOARD="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "    il firmware si carica a parte, da un terminale sulla board:"
    echo "      arduino-cli compile -b arduino:zephyr:unoq --upload -p ${IP_BOARD:-<indirizzo>} firmware/amelie_mcu"
else
    echo "    arduino-cli non trovato: vedi firmware/amelie_mcu/README.md"
fi

passo "8/10  Servizi"
sudo install -m755 scripts/systemd/amelie-*.sh scripts/systemd/azzera-*.sh /usr/local/bin/
sudo install -m644 scripts/systemd/amelie-*.service /etc/systemd/system/
sudo mkdir -p /var/lib/amelie /usr/share/xsessions
# La sessione grafica del dispositivo: vedi il passo 8 per come la si sceglie.
sudo install -m644 scripts/systemd/amelie.desktop /usr/share/xsessions/
sudo systemctl daemon-reload
sudo systemctl enable amelie-llm amelie-audio-guard amelie-audio-rotta \
    amelie-sipario amelie-display amelie amelie-kiosk amelie-scrivania

passo "9/10  Avvio automatico della sessione grafica"
# Senza autologin il server X appartiene al greeter e Chromium non riesce ad
# aprirlo: fallisce con "The platform failed to initialize", che non dice quale
# sia il problema. Con l'autologin la sessione e' di arduino e ~/.Xauthority
# funziona.
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-amelie-autologin.conf >/dev/null <<'EOF'
[Seat:*]
autologin-user=arduino
autologin-user-timeout=0
EOF

# E la sessione e' quella di Amelie, non XFCE. L'immagine della UNO Q avvia una
# scrivania completa - sfondo, barra, icone, App Lab - e per una decina di
# secondi a ogni accensione e' quella che si vede sul pannello. Spegnerne i
# pezzi uno per uno era una rincorsa: qui la scrivania non parte proprio.
#
# Per riaverla, in sviluppo:
#     sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
#     sudo systemctl restart lightdm
sudo tee /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf >/dev/null <<'EOF'
[Seat:*]
user-session=amelie
autologin-session=amelie
EOF

passo "10/10  Silenzio sulla console"
# Niente testo sul pannello durante l'avvio. Il `quiet` del kernel starebbe
# sulla riga di comando, che qui vive dentro un'immagine unificata: rifarla per
# dodici secondi di testo non vale il rischio di una board che non riparte. Il
# resto si toglie senza toccare l'avvio.
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/50-amelie-silenzio.conf >/dev/null <<'EOF'
# Niente righe «[ OK ] Started ...» sul pannello. Restano tutte nel journal:
# `journalctl -b` le mostra esattamente come prima.
[Manager]
ShowStatus=no
EOF
sudo tee /etc/sysctl.d/50-amelie-silenzio.conf >/dev/null <<'EOF'
# Solo le emergenze sulla console. Se il dispositivo sta per morire e' giusto
# che lo dica; tutto il resto e' nel journal.
kernel.printk = 1 4 1 3
EOF

# E la console di testo non si raggiunge nemmeno da tastiera. Sul tavolo di un
# ristorante le porte USB sono raggiungibili, e Ctrl+Alt+F2 su una tastiera
# infilata porta a un prompt di login a schermo intero. Ha effetto dal riavvio
# successivo, perche' il server X legge questa cartella all'avvio.
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/10-amelie-kiosk.conf >/dev/null <<'EOF'
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap"      "true"
EndSection
EOF

echo
echo "${G}Fatto.${N}  Riavvia per verificare l'avvio completo:  sudo reboot"
echo "Stato dei servizi:      systemctl status 'amelie*'"
echo "Collaudo:               bash scripts/00_diagnostica.sh"
echo
echo "PRIMA DI LASCIARLO IN SALA, togliere sudo senza password:"
echo "    sudo rm -f /etc/sudoers.d/010_arduino-nopasswd"
