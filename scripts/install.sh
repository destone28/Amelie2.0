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
VOCE="it_IT-serena-medium"
URL_VOCE="https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/serena/medium"

SALTA_MODELLO=0
[ "${1:-}" = "--senza-modello" ] && SALTA_MODELLO=1

G=$'\033[32m'; N=$'\033[0m'
passo() { echo; echo "${G}==>${N} $*"; }

passo "1/8  Pacchetti di sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv python3-pip python3-dev build-essential cmake git curl \
    v4l-utils alsa-utils \
    chromium unclutter x11-xserver-utils \
    libcurl4-openssl-dev

passo "2/8  Correzione della corsa all'avvio dell'audio"
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

passo "3/8  Ambiente Python"
mkdir -p "$RADICE"
cd "$RADICE"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q \
    numpy opencv-python-headless onnxruntime rapidocr rapidfuzz msgpack \
    fastapi "uvicorn[standard]" piper-tts

passo "4/8  llama.cpp"
if [ ! -x "$RADICE/llama.cpp/build/bin/llama-server" ]; then
    [ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp
    cd llama.cpp
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON >/dev/null
    cmake --build build -j"$(nproc)" --target llama-server llama-cli llama-bench >/dev/null
    cd "$RADICE"
fi

passo "5/8  Modelli"
mkdir -p models
if [ "$SALTA_MODELLO" = 0 ] && [ ! -f "models/$MODELLO_LLM" ]; then
    echo "    scarico il modello linguistico (~700 MB)"
    curl -sL --retry 3 -o "models/$MODELLO_LLM" "$URL_LLM"
fi
for est in onnx onnx.json; do
    [ -f "models/$VOCE.$est" ] || curl -sL --retry 3 \
        -o "models/$VOCE.$est" "$URL_VOCE/$VOCE.$est" || true
done

passo "6/8  Database dei vini"
[ -f data/amelie.db ] || ./venv/bin/python data/build_db.py

passo "7/8  Servizi"
sudo install -m755 scripts/systemd/amelie-*.sh scripts/systemd/azzera-*.sh /usr/local/bin/
sudo install -m644 scripts/systemd/amelie-*.service /etc/systemd/system/
sudo mkdir -p /var/lib/amelie
sudo systemctl daemon-reload
sudo systemctl enable amelie-llm amelie-audio-guard amelie-display amelie amelie-kiosk

passo "8/8  Avvio automatico della sessione grafica"
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

echo
echo "${G}Fatto.${N}  Riavvia per verificare l'avvio completo:  sudo reboot"
echo "Stato dei servizi:      systemctl status 'amelie*'"
echo "Collaudo:               bash scripts/00_diagnostica.sh"
echo
echo "PRIMA DI LASCIARLO IN SALA, togliere sudo senza password:"
echo "    sudo rm -f /etc/sudoers.d/010_arduino-nopasswd"
