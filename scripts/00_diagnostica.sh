#!/usr/bin/env bash
# Amelie 2.0 - collaudo del dispositivo installato.
#
#   bash scripts/00_diagnostica.sh
#
# Va eseguito SULLA BOARD, come utente arduino, dopo scripts/install.sh e un
# riavvio. Non modifica niente: legge e basta, e salva un rapporto in
# /tmp/amelie-diagnostica.txt. Ogni voce e' marcata OK, ATTENZIONE o GRAVE; le
# voci GRAVE dicono che cosa non funzionera'. Guida: docs/it/04-collaudo.md.
#
# Quello che il software dichiara non e' quello che fa l'hardware: dopo questo
# script lo schermo si guarda e l'audio si ascolta (vedi la guida).
set -uo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAPPORTO=/tmp/amelie-diagnostica.txt
exec > >(tee "$RAPPORTO") 2>&1

G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'
[ -t 1 ] || { G=''; Y=''; R=''; B=''; N=''; }
N_OK=0; N_ATT=0; N_GRAVE=0
ok()   { echo "  ${G}OK${N}         $*"; N_OK=$((N_OK + 1)); }
warn() { echo "  ${Y}ATTENZIONE${N} $*"; N_ATT=$((N_ATT + 1)); }
bad()  { echo "  ${R}GRAVE${N}      $*"; N_GRAVE=$((N_GRAVE + 1)); }
info() { echo "             $*"; }
sez()  { echo; echo "${B}== $* ==${N}"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "${B}Amelie 2.0 - collaudo${N}   $(date -Is)"
echo "rapporto: $RAPPORTO"

# ---------------------------------------------------------------- 1. sistema
sez "1. Sistema"
. /etc/os-release 2>/dev/null || true
info "$PRETTY_NAME, kernel $(uname -r), $(uname -m)"
[ "${VERSION_CODENAME:-}" = trixie ] && ok "Debian 13 trixie" \
    || warn "sistema diverso da Debian 13: non e' la configurazione collaudata"
LIBERI=$(df --output=avail -BG "$HOME" | tail -1 | tr -dc 0-9)
[ "${LIBERI:-0}" -ge 1 ] && ok "$LIBERI GB liberi in $HOME" \
    || bad "meno di 1 GB libero in $HOME: il giornale delle scansioni non ha spazio"
RADICE_LIBERI=$(df --output=avail -BM / | tail -1 | tr -dc 0-9)
[ "${RADICE_LIBERI:-0}" -ge 300 ] && ok "$((RADICE_LIBERI / 1024)) GB liberi nella partizione di sistema" \
    || warn "partizione di sistema quasi piena: gli aggiornamenti potrebbero fallire"
MEM=$(awk '/MemTotal/{printf "%.1f", $2/1048576}' /proc/meminfo)
info "memoria: $MEM GB"
for t in /sys/class/thermal/thermal_zone0/temp; do
    [ -r "$t" ] && info "temperatura: $(awk '{printf "%.0f", $1/1000}' "$t") gradi"
done

# ---------------------------------------------------------------- 2. installazione
sez "2. Installazione"
cd "$RADICE" || exit 1
if [ -x venv/bin/python ]; then
    if PYTHONPATH=src venv/bin/python -c \
        "import numpy, cv2, onnxruntime, rapidocr, rapidfuzz, piper, fastapi, uvicorn, msgpack" 2>/dev/null; then
        ok "ambiente Python completo ($(venv/bin/python --version))"
    else
        bad "ambiente Python incompleto: rilancia scripts/install.sh"
    fi
else
    bad "manca l'ambiente Python (venv): rilancia scripts/install.sh"
fi
if (cd models && sha256sum -c --quiet ../scripts/modelli.sha256) >/dev/null 2>&1; then
    ok "voci e modello linguistico presenti e integri"
else
    bad "voci o modello mancanti o diversi da quelli attesi: rilancia scripts/install.sh"
fi
[ -x llama.cpp/build/bin/llama-server ] && ok "llama-server compilato" \
    || warn "llama-server assente: il modo «Scritto sul momento» non funzionera'"
if [ -s data/amelie.db ]; then
    VINI=$(venv/bin/python -c "import sqlite3; print(sqlite3.connect('file:data/amelie.db?mode=ro', uri=True).execute('select count(*) from vino').fetchone()[0])" 2>/dev/null)
    [ "${VINI:-0}" -gt 0 ] && ok "database dei vini: $VINI vini" || bad "database dei vini illeggibile"
else
    bad "manca data/amelie.db: rilancia scripts/install.sh"
fi
[ -s vini.csv ] && ok "carta dei vini: $(($(wc -l < vini.csv) - 1)) righe" \
    || warn "manca vini.csv: il modo «Carta dei vini» non comparira'"
[ -s var/firmware/.caricato ] && ok "firmware del microcontrollore caricato e verificato" \
    || warn "nessuna traccia di un firmware caricato e verificato: bash scripts/firmware.sh"

# ---------------------------------------------------------------- 3. servizi
sez "3. Servizi"
for u in amelie amelie-kiosk amelie-display amelie-audio-guard amelie-audio-rotta amelie-sipario; do
    stato=$(systemctl is-active "$u" 2>/dev/null)
    abil=$(systemctl is-enabled "$u" 2>/dev/null)
    if [ "$stato" = active ] && [ "$abil" = enabled ]; then ok "$u attivo"
    elif [ "$abil" != enabled ]; then bad "$u non abilitato ($abil): rilancia scripts/install.sh"
    else bad "$u $stato: journalctl -u $u"; fi
done
case "$(systemctl is-enabled amelie-llm 2>/dev/null)" in
    enabled) warn "amelie-llm abilitato all'avvio: lo accende gia' l'applicazione quando serve" ;;
    *)       ok "amelie-llm non abilitato all'avvio (lo accende l'applicazione)" ;;
esac
[ -f /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf ] && ok "sessione grafica di Amelie" \
    || warn "sessione grafica di Amelie non impostata: sullo schermo comparira' la scrivania"

# ---------------------------------------------------------------- 4. applicazione
sez "4. Applicazione"
STATO=$(curl -s -m 5 http://127.0.0.1:8080/stato 2>/dev/null)
if [ -z "$STATO" ]; then
    bad "l'applicazione non risponde su 127.0.0.1:8080: journalctl -u amelie"
else
    campo() { printf '%s' "$STATO" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('$1'); print(json.dumps(v) if isinstance(v,(dict,list)) else v)"; }
    info "stato: $(campo stato), modo: $(campo modo), volume: $(campo volume)"
    [ "$(campo pronta)" = True ] && ok "applicazione pronta" || warn "applicazione non ancora pronta (riprova fra qualche secondo)"
    # Il servizio del chiosco risulta attivo anche con Chromium fermo su un
    # avviso, o con la scrivania davanti: che lo schermo mostri Amelie lo dice
    # solo la pagina, che si collega agli eventi dell'applicazione.
    if [ "$(campo pronta)" = True ]; then
        if [ "$(campo schermi)" -ge 1 ] 2>/dev/null; then
            ok "lo schermo mostra l'applicazione"
        else
            warn "nessuno schermo collegato all'applicazione: guarda che cosa mostra, poi sudo systemctl restart amelie-kiosk"
        fi
    fi
    # Il protocollo che il codice si aspetta, letto dal codice: scritto qui a
    # mano resterebbe indietro alla prima versione nuova del firmware.
    ATTESO=$(PYTHONPATH=src venv/bin/python -c \
        "from amelie.bridge import PROTOCOLLO_ATTESO; print(PROTOCOLLO_ATTESO)" 2>/dev/null)
    if [ "$(campo mcu)" = True ] && [ "$(campo protocollo)" = "$ATTESO" ]; then
        ok "microcontrollore raggiungibile (protocollo $ATTESO)"
        MODULI=$(campo moduli)
        grep -q '"anello": true' <<<"$MODULI" && ok "Modulino Pixels visto" \
            || bad "Modulino Pixels non visto: cavo Qwiic, poi spegni e riaccendi"
        grep -q '"distanza": true' <<<"$MODULI" && ok "Modulino Distance visto" \
            || bad "Modulino Distance non visto: senza, nessuna bottiglia viene notata"
    elif [ "$(campo mcu)" = True ]; then
        bad "sul microcontrollore gira un firmware di un'altra versione (protocollo $(campo protocollo)): bash scripts/firmware.sh --sempre"
    elif systemctl is-active -q arduino-router; then
        bad "il router risponde ma lo sketch di Amelie non gira sul microcontrollore: bash scripts/firmware.sh --sempre"
    else
        bad "il microcontrollore non risponde: arduino-router fermo (sudo systemctl restart arduino-router)"
    fi
    # `camera` e' vero anche col cavo staccato: se la camera funziona lo dice
    # `fotogramma_s`, i secondi dall'ultimo fotogramma. A riposo il guardiano ne
    # prende undici al secondo; durante il racconto la camera e' spenta.
    FOTO=$(campo fotogramma_s)
    if [ "$(campo camera)" != True ]; then
        bad "l'applicazione gira senza camera (--senza-camera)"
    elif [ "$FOTO" = None ]; then
        bad "la camera non ha mai dato un fotogramma all'applicazione: cavo della camera, poi sudo systemctl restart amelie"
    elif [ "$(campo stato)" != attesa ]; then
        info "ultimo fotogramma della camera $FOTO s fa (fuori dall'attesa la camera puo' essere spenta)"
    elif awk -v s="$FOTO" 'BEGIN { exit !(s <= 5) }'; then
        ok "la camera da' fotogrammi all'applicazione"
    else
        bad "la camera non da' fotogrammi da $FOTO s: cavo della camera, poi sudo systemctl restart amelie"
    fi
    [ "$(campo voce)" = True ] && ok "voce caricata" || bad "voce non caricata: il racconto si leggera' soltanto"
fi

# ---------------------------------------------------------------- 5. schermo
sez "5. Schermo"
TROVATO=0
for st in /sys/class/drm/card*-DP-*/status; do
    [ -r "$st" ] && [ "$(cat "$st")" = connected ] || continue
    TROVATO=1; ok "uscita video $(basename "$(dirname "$st")") collegata"
done
[ "$TROVATO" = 1 ] || bad "nessuno schermo collegato: cavo HDMI, hub, alimentazione dello schermo"
if have xrandr; then
    MODO=$(DISPLAY=:0 XAUTHORITY="$HOME/.Xauthority" xrandr --query 2>/dev/null | awk '/\*/{print $1; exit}')
    case "$MODO" in
        1280x720) ok "modalita' 1280x720" ;;
        "")       warn "modalita' video non leggibile (la sessione grafica e' partita?)" ;;
        *)        bad "modalita' $MODO: il pannello vuole 1280x720 (systemctl restart amelie-display)" ;;
    esac
fi
if grep -qiE 'touch|mpi5001|qdtech' /proc/bus/input/devices 2>/dev/null; then
    ok "touch dello schermo: $(grep -iE '^N: Name=.*(touch|mpi5001|qdtech)' /proc/bus/input/devices | head -1 | cut -d'"' -f2)"
else
    warn "nessun touch riconosciuto: controlla il cavo micro-USB dello schermo"
fi

# ---------------------------------------------------------------- 6. camera
sez "6. Camera"
CAM=0
for d in /sys/class/video4linux/video*; do
    [ -r "$d/name" ] || continue
    case "$(cat "$d/name")" in *[Vv]enus*) continue ;; esac
    CAM=1; ok "camera USB: $(cat "$d/name") (/dev/$(basename "$d"))"; break
done
[ "$CAM" = 1 ] || bad "nessuna camera USB: controlla il cavo della camera"

# ---------------------------------------------------------------- 7. audio
sez "7. Audio"
if aplay -l 2>/dev/null | grep -q '^card 0'; then
    ok "scheda audio presente: $(aplay -l 2>/dev/null | awk -F'[][]' '/^card 0/{print $2; exit}')"
else
    bad "nessuna scheda audio: sudo systemctl restart amelie-audio-guard, poi riavvia"
fi
ROTTA='SEC_MI2S_RX Audio Mixer MultiMedia4'
if amixer -c 0 cget "name=$ROTTA" 2>/dev/null | grep -q ': values=on'; then
    ok "strada del suono verso l'HDMI aperta"
else
    bad "strada del suono verso l'HDMI chiusa: sudo systemctl restart amelie-audio-rotta"
fi
[ -r /var/lib/amelie/audio-guard.log ] && info "guardia audio: $(tail -1 /var/lib/amelie/audio-guard.log)"
# Le frasi gia' dette restano in una cache. Uno spegnimento subito dopo averne
# scritta una puo' lasciare un file vuoto, e quella frase non si sentirebbe
# piu': il servizio li toglie a ogni avvio, qui si contano.
CACHE_VOCE="$HOME/.cache/amelie/voce"
if [ -d "$CACHE_VOCE" ]; then
    ROVINATE=$(find "$CACHE_VOCE" -maxdepth 1 \( -name '*.raw' -size 0 -o -name '*.parziale' \) | wc -l)
    FRASI=$(find "$CACHE_VOCE" -maxdepth 1 -name '*.raw' | wc -l)
    if [ "$ROVINATE" -eq 0 ]; then
        ok "cache della voce sana ($FRASI frasi)"
    else
        warn "$ROVINATE frasi rovinate nella cache della voce: il servizio le toglie riavviandolo (sudo systemctl restart amelie)"
    fi
fi
info "l'audio si collauda ascoltando: tocca la bandiera gia' attiva sullo schermo"

# ---------------------------------------------------------------- 8. ponte
sez "8. Router verso il microcontrollore"
systemctl is-active -q arduino-router && ok "arduino-router attivo" \
    || bad "arduino-router fermo: sudo systemctl restart arduino-router"
DEF=$(arduino-app-cli properties get default 2>/dev/null)
case "$DEF" in
    *"No default app"*|"") ok "nessuna app di App Lab all'avvio" ;;
    *) bad "App Lab avvia un'app all'accensione ($DEF): sostituirebbe il firmware. arduino-app-cli properties set default none" ;;
esac

sez "Riepilogo"
echo "  ${G}$N_OK OK${N}, ${Y}$N_ATT ATTENZIONE${N}, ${R}$N_GRAVE GRAVE${N}"
echo "  rapporto salvato in $RAPPORTO"
[ "$N_GRAVE" -eq 0 ]
