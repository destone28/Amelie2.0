#!/usr/bin/env bash
# Amelie 2.0 - collaudo della board
#
# Da eseguire SULLA UNO Q, al primo avvio, prima di scrivere qualunque codice.
# Non modifica niente: legge e basta. Salva un rapporto in /tmp/amelie-diagnostica.txt
#
#   bash scripts/00_diagnostica.sh
#
# Ogni voce e' marcata OK / ATTENZIONE / GRAVE / ? . Le voci GRAVE cambiano il progetto.

set -uo pipefail
RAPPORTO=/tmp/amelie-diagnostica.txt
exec > >(tee "$RAPPORTO") 2>&1

G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'
[ -t 1 ] || { G=''; Y=''; R=''; B=''; N=''; }

ok()   { echo "  ${G}OK${N}         $*"; }
warn() { echo "  ${Y}ATTENZIONE${N} $*"; }
bad()  { echo "  ${R}GRAVE${N}      $*"; }
unk()  { echo "  ?          $*"; }
sez()  { echo; echo "${B}== $* ==${N}"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "${B}Amelie 2.0 - collaudo board${N}   $(date -Is)"
echo "rapporto: $RAPPORTO"

# ---------------------------------------------------------------- 1. sistema
sez "1. Sistema"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "  distribuzione: $PRETTY_NAME"
  case "${VERSION_CODENAME:-}" in
    trixie) ok "Debian 13 trixie, come atteso" ;;
    *)      warn "atteso 'trixie', trovato '${VERSION_CODENAME:-ignoto}': le versioni dei pacchetti nella guida potrebbero non combaciare" ;;
  esac
fi
echo "  kernel:       $(uname -r)   arch: $(uname -m)"
[ "$(uname -m)" = aarch64 ] && ok "arch aarch64" || bad "arch inattesa: le wheel Python aarch64 non si applicano"

PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "?")
echo "  python3:      $PYV"
case "$PYV" in
  3.1[1-4]) ok "onnxruntime ha wheel aarch64 per questa versione" ;;
  3.10)     warn "solo onnxruntime<=1.23.2 ha wheel aarch64 per 3.10 (pip retrocede da solo)" ;;
  *)        unk "verificare la disponibilita' delle wheel onnxruntime aarch64" ;;
esac
PEP668=$(python3 -c 'import sysconfig,os;print(os.path.join(sysconfig.get_paths()["stdlib"],"EXTERNALLY-MANAGED"))' 2>/dev/null)
if [ -n "$PEP668" ] && [ -e "$PEP668" ]; then
  warn "PEP 668 attivo ($PEP668): 'pip install' di sistema fallira'. Si usa un venv."
else
  ok "nessun vincolo PEP 668"
fi
have systemctl && ok "systemd presente" || bad "systemd assente: l'avvio automatico va ripensato"

# ---------------------------------------------------------------- 2. CPU
sez "2. CPU"
grep -m1 'model name\|Processor' /proc/cpuinfo 2>/dev/null | sed 's/^/  /'
echo "  core:         $(nproc)"
FEAT=$(grep -m1 '^Features' /proc/cpuinfo | cut -d: -f2-)
echo "  estensioni:  $FEAT"
if [ -z "${FEAT// /}" ]; then
  unk "nessuna riga 'Features' in /proc/cpuinfo (normale su x86: questo test vale solo su ARM)"
elif grep -qw asimddp <<<"$FEAT"; then
  ok "asimddp (dot product) PRESENTE: llama.cpp puo' andare ~2x piu' veloce del previsto"
else
  warn "asimddp ASSENTE (atteso su Cortex-A53 ARMv8.0): ~5,5 tok/s e' il tetto, non c'e' margine da recuperare"
fi
for c in /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; do
  [ -r "$c" ] && { echo "  governor:     $(cat $c)"; grep -q performance "$c" || warn "governor non 'performance': in inferenza conviene alzarlo"; }
done

# ---------------------------------------------------------------- 3. memoria
sez "3. Memoria"
awk '/MemTotal|MemAvailable|SwapTotal/ {printf "  %-14s %6.2f GB\n", $1, $2/1048576}' /proc/meminfo
MEMG=$(awk '/MemTotal/{print int($2/1048576*10)}' /proc/meminfo)
if   [ "$MEMG" -ge 34 ]; then ok "RAM visibile a Linux sufficiente per LLM 0.8B + OCR + UI"
elif [ "$MEMG" -ge 28 ]; then warn "RAM visibile ridotta: tenere il modello sotto 700 MB"
else bad "RAM visibile troppo bassa: rivedere la scelta del modello"; fi
SW=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
[ "${SW:-0}" -gt 0 ] && warn "swap attivo su eMMC: se ci si finisce dentro, la latenza esplode" || ok "nessuna swap"

# ---------------------------------------------------------------- 4. disco
sez "4. Spazio su disco"
df -h / /var 2>/dev/null | sed 's/^/  /'
FREE=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
if   [ "${FREE:-0}" -ge 12 ]; then ok "spazio sufficiente per modelli LLM + OCR + TTS"
elif [ "${FREE:-0}" -ge 6 ];  then warn "spazio limitato: rifare il flash con --root-size 20GB prima di procedere"
else bad "spazio insufficiente: reflash OBBLIGATORIO con --root-size 20GB (irreversibile senza reflash)"; fi

# ---------------------------------------------------------------- 5. video
sez "5. Video (il rischio n.1 dopo l'alimentazione)"
# Si legge da sysfs, non da xrandr: via SSH xrandr non ha l'autorizzazione X del
# greeter e fallisce anche quando lo schermo funziona benissimo. /sys/class/drm e'
# il kernel, e non dipende da chi sta guardando.
TROVATO_DP=0
for st in /sys/class/drm/card*-DP-*/status; do
  [ -r "$st" ] || continue
  CONN=$(dirname "$st"); NOME=$(basename "$CONN")
  S=$(cat "$st")
  echo "  $NOME: $S"
  [ "$S" = connected ] || continue
  TROVATO_DP=1
  ok "$NOME connesso"
  [ -r "$CONN/enabled" ] && echo "    abilitato: $(cat "$CONN/enabled")"
  if [ -s "$CONN/modes" ]; then
    echo "    modalita': $(tr '\n' ' ' < "$CONN/modes" | cut -c1-100)"
    # ATTENZIONE: essere ELENCATA non significa FUNZIONARE. Sul pannello LAFVIN
    # da 5" xrandr elenca 800x480 per prima e la marca come preferita, ma se la
    # si attiva il pannello resta NERO. Solo 1280x720 e 1920x1080 - modalita' CEA
    # vere - producono immagine. L'unico criterio valido resta guardare il
    # pannello, non leggere questa lista.
    if grep -qx '1280x720' "$CONN/modes"; then
      ok "1280x720 disponibile: e' la modalita' di produzione (CEA, scalata dal pannello)"
    else
      warn "1280x720 non offerta: ripiegare su 1920x1080"
    fi
    grep -qx '800x480' "$CONN/modes" && \
      warn "800x480 e' elencata, ma sul pannello LAFVIN NON produce immagine: non usarla"
  else
    warn "nessuna modalita' elencata"
  fi
  E="$CONN/edid"
  [ -s "$E" ] && ok "EDID letto ($(stat -c%s "$E") byte)" \
    || warn "EDID vuoto: il pannello non si descrive attraverso l'hub (le modalita' sopra restano valide)"
done
[ "$TROVATO_DP" = 1 ] || bad "nessun DisplayPort connesso: controllare hub, cavo HDMI e alimentazione dello schermo"
if have xrandr && [ -n "${DISPLAY:-}" ] && xrandr --query >/dev/null 2>&1; then
  echo "  --- xrandr (sessione grafica accessibile) ---"
  xrandr --query 2>/dev/null | grep -E "^(Screen|DP|HDMI)" | sed 's/^/  /'
fi
echo "  --- driver grafico ---"
if have glxinfo; then
  glxinfo -B 2>/dev/null | grep -i 'renderer\|OpenGL version' | sed 's/^/  /'
  if glxinfo -B 2>/dev/null | grep -qi 'FD702\|freedreno'; then ok "accelerazione hardware Adreno attiva"
  elif glxinfo -B 2>/dev/null | grep -qi llvmpipe; then bad "llvmpipe: rendering software. Serve Mesa >= 25.2 o il pacchetto Qualcomm -1qcom1"
  fi
else unk "glxinfo assente (apt install mesa-utils) - serve per sapere se la GPU e' davvero attiva"; fi
have apt-cache && apt-cache policy libgl1-mesa-dri 2>/dev/null | sed -n '1,3p' | sed 's/^/  /'

# ---------------------------------------------------------------- 6. touch
sez "6. Touch"
if have xinput && [ -n "${DISPLAY:-}" ]; then
  xinput list 2>/dev/null | sed 's/^/  /'
  xinput list 2>/dev/null | grep -qi 'touch\|egalax\|ilitek\|hid' && ok "dispositivo touch enumerato" || warn "nessun touch riconosciuto: controllare il cavo micro-USB dello schermo"
else unk "xinput non disponibile"; fi
have libinput && { echo "  --- libinput ---"; libinput list-devices 2>/dev/null | grep -A2 -i touch | head -20 | sed 's/^/  /'; }

# ---------------------------------------------------------------- 7. camera
sez "7. Camera"
if have v4l2-ctl; then
  v4l2-ctl --list-devices 2>/dev/null | sed 's/^/  /'
  for d in /dev/video*; do
    [ -e "$d" ] || continue
    if v4l2-ctl -d "$d" --list-formats 2>/dev/null | grep -q MJPG; then
      ok "$d espone MJPEG"
      v4l2-ctl -d "$d" --list-formats-ext 2>/dev/null | grep -A1 MJPG | grep -o '[0-9]\+x[0-9]\+' | sort -u | tr '\n' ' ' | sed 's/^/    risoluzioni: /'; echo
      break
    fi
  done
  ls /dev/video* >/dev/null 2>&1 || bad "nessun /dev/video*: la camera non e' enumerata"
else unk "v4l2-ctl assente (apt install v4l-utils)"; fi

# ---------------------------------------------------------------- 8. audio
sez "8. Audio (decide la catena voce)"
echo "  --- schede ALSA ---"
if [ -r /proc/asound/cards ]; then cat /proc/asound/cards | sed 's/^/  /'; else echo "  (/proc/asound/cards assente)"; fi
have aplay && { echo "  --- aplay -l ---"; aplay -l 2>&1 | sed 's/^/  /'; }
if aplay -l 2>/dev/null | grep -qi 'hdmi\|displayport\|dp'; then
  ok "esiste un device audio HDMI/DP: la catena schermo->PAM8403 e' possibile. Verificare che non sia MUTO (amixer)."
elif aplay -l 2>/dev/null | grep -q '^card'; then
  warn "esistono schede audio ma nessuna HDMI/DP"
else
  bad "nessuna scheda audio: senza HDMI e senza dongle USB non c'e' voce"
fi
echo "  --- device audio USB collegati ---"
have lsusb && lsusb 2>/dev/null | grep -i 'audio\|c-media\|cmedia\|headset' | sed 's/^/  /' || true
echo "  --- dai-link nel device tree vivo ---"
if [ -d /proc/device-tree/sound ]; then
  DTLINKS=$(for d in /proc/device-tree/sound/*/; do
              tr -d '\0' < "$d/link-name" 2>/dev/null && echo
            done | grep -v '^$')
  echo "$DTLINKS" | sed 's/^/    /'
  echo "$DTLINKS" | grep -q 'HDMI/I2S' \
    && ok "il device tree espone 'HDMI/I2S Playback'" \
    || warn "nessun dai-link HDMI/I2S nel device tree"
fi
echo "  --- moduli audio caricati ---"
lsmod 2>/dev/null | grep -i 'snd' | awk '{print "  "$1}' | head -15
echo "  --- mixer (cerca canali mutati) ---"
have amixer && for c in $(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]\+\).*/\1/p' | sort -u); do
  echo "  card $c:"; amixer -c "$c" scontrols 2>/dev/null | sed 's/^/    /'
done

# ---------------------------------------------------------------- 9. USB
sez "9. Albero USB e velocita' di link"
have lsusb && lsusb -t 2>/dev/null | sed 's/^/  /'
echo "  --- errori di banda nel dmesg ---"
USBERR=$(dmesg 2>/dev/null | grep -iE 'no space left|not enough bandwidth|cannot enable|over-current' | tail -5)
if [ -n "$USBERR" ]; then
  echo "$USBERR" | sed 's/^/  /'
  bad "errori USB nel dmesg: con DP attivo camera e audio condividono un solo bus 2.0"
else
  ok "nessun errore di banda USB nel dmesg"
fi

# ---------------------------------------------------------------- 10. alimentazione
sez "10. Alimentazione"
dmesg 2>/dev/null | grep -iE 'under.?voltage|brown.?out|power.?supply|reset reason|watchdog' | tail -8 | sed 's/^/  /'
echo "  uptime: $(uptime -p 2>/dev/null || uptime)"
for t in /sys/class/thermal/thermal_zone*/temp; do
  [ -r "$t" ] && echo "  $(basename $(dirname $t)): $(awk '{printf "%.1f C", $1/1000}' $t)"
done
warn "il test vero dell'alimentazione e' con un power meter USB inline, 30 minuti sotto carico (>= 4,75 V, zero reset)"

# ---------------------------------------------------------------- 11. bridge MCU
sez "11. Ponte verso l'MCU (STM32U585)"
for s in /var/run/arduino-router.sock /run/arduino-router.sock; do
  [ -S "$s" ] && { ok "socket del router presente: $s"; FOUND=1; }
done
[ -n "${FOUND:-}" ] || warn "socket arduino-router non trovato: verificare 'systemctl status arduino-router'"
systemctl list-units --type=service 2>/dev/null | grep -i 'arduino' | sed 's/^/  /'
ls /dev/ttyAMA* /dev/ttyMSM* /dev/ttyHS* 2>/dev/null | sed 's/^/  seriale: /' || true
ls /dev/ttyS* 2>/dev/null | head -4 | sed 's/^/  seriale: /' || true

# ---------------------------------------------------------------- 12. software
sez "12. Software gia' presente"
for c in arduino-app-cli arduino-cli llama-cli llama-server llama-bench ollama piper tesseract chromium ffmpeg; do
  if have "$c"; then ok "$c -> $(command -v $c)"; else echo "  -          $c assente"; fi
done
echo "  --- modelli gia' scaricati ---"
for d in /var/lib/arduino-app-cli/models /home/arduino/.cache; do
  [ -d "$d" ] && find "$d" -name '*.gguf' -o -name '*.onnx' 2>/dev/null | head -10 | sed 's/^/  /'
done

sez "Fine"
echo "Rapporto salvato in $RAPPORTO"
echo "Rileggi le voci ${R}GRAVE${N} e ${Y}ATTENZIONE${N}: sono quelle che cambiano il piano."
