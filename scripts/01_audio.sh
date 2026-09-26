#!/usr/bin/env bash
# Amelie 2.0 - la prova dell'audio HDMI
#
# Decide in dieci minuti se la voce puo' uscire dal jack dello schermo, senza
# comprare niente. Va eseguito SULLA UNO Q, CON LO SCHERMO GIA' ACCESO E
# COLLEGATO: il driver ANX7625 esce in silenzio se il sink DP non e' rilevato
# nel momento in cui si apre il flusso, e su questo collegamento non e'
# registrato alcun jack, quindi niente commuta da solo.
#
#   bash scripts/01_audio.sh          verifica e, se serve, alza il mixer e suona
#   bash scripts/01_audio.sh --solo-diagnosi   guarda e basta
#
# Se il suono esce, l'intera catena e' provata in un colpo solo: kernel, device
# tree, ALSA, ANX7625, DisplayPort, hub UGREEN, schermo. Se non esce, il piano B
# e' un adattatore audio USB da 5 euro sull'hub, che salta tutta questa catena.

set -uo pipefail
G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'
[ -t 1 ] || { G=''; Y=''; R=''; B=''; N=''; }
ok(){ echo "  ${G}OK${N}    $*"; }; warn(){ echo "  ${Y}!${N}     $*"; }
bad(){ echo "  ${R}NO${N}    $*"; }; sez(){ echo; echo "${B}== $* ==${N}"; }

SOLO_DIAGNOSI=0
[ "${1:-}" = "--solo-diagnosi" ] && SOLO_DIAGNOSI=1

MIXER='SEC_MI2S_RX Audio Mixer MultiMedia4'
DTB=/boot/efi/dtb/qcom/qrb2210-arduino-imola.dtb
UCM=/usr/share/alsa/ucm2/Qualcomm/qcm2290

echo "${B}Amelie 2.0 - prova dell'audio HDMI${N}"
echo "Lo schermo deve essere acceso e collegato PRIMA di lanciare questo script."

# ------------------------------------------------------------------ 1
sez "1. Kernel"
echo "  $(uname -r)"
# I kernel Arduino portano l'hash del commit nella release, es.
# 7.0.0-g122c2c22d838. Servono almeno 8 cifre esadecimali, altrimenti "-generic"
# passerebbe per un hash.
if uname -r | grep -qE -- '-g[0-9a-f]{8,}|unoq'; then
  ok "kernel Arduino: il dai-link HDMI/I2S e' presente in tutte le linee pubblicate"
else
  warn "non sembra un kernel Arduino per UNO Q: i controlli sotto restano quelli che contano"
fi

# ------------------------------------------------------------------ 2
sez "2. Profilo ALSA del costruttore"
# La UCM per qcm2290 NON esiste in Debian: arriva solo dal pacchetto Arduino.
# Un 'apt full-upgrade' che la sostituisce con quella Debian la fa sparire.
dpkg -l alsa-ucm-conf 2>/dev/null | tail -1 | sed 's/^/  /'
# Cio' che conta e' che i profili per qcm2290 ci siano: Debian non li ha, quindi
# se ci sono vuol dire che l'immagine li porta, comunque sia numerato il pacchetto.
# Controllare la stringa di versione darebbe un falso allarme sull'immagine di lancio.
if [ -d "$UCM" ]; then
  ok "profili qcm2290 presenti: $(ls "$UCM" | tr '\n' ' ')"
  [ -f "$UCM/HDMI.conf" ] && ok "HDMI.conf c'e'" \
    || bad "HDMI.conf manca: senza, PipeWire non espone alcun sink HDMI"
else
  bad "$UCM assente: Debian non fornisce i profili per qcm2290, li porta solo"
  echo "        l'immagine Arduino. Un 'apt full-upgrade' puo' averli rimossi."
  echo "        rimedio: reinstallare alsa-ucm-conf dal repo Arduino, poi apt-mark hold"
fi

# ------------------------------------------------------------------ 3
sez "3. Identita' della board"
for f in board_vendor product_name board_name; do
  v=$(cat /sys/devices/virtual/dmi/id/$f 2>/dev/null || echo "?")
  echo "  $f: $v"
done
if grep -qi imola /sys/devices/virtual/dmi/id/product_name 2>/dev/null; then
  ok "il DMI corrisponde: la UCM verra' applicata"
else
  warn "DMI inatteso: la UCM si attiva su 'Arduino-Imola*', altrimenti restano i PCM grezzi"
fi

# ------------------------------------------------------------------ 4
sez "4. Device tree"
# Si interroga il device tree VIVO, non il file .dtb: su alcune immagini quel file
# non sta affatto in /boot/efi (la 6.16.7 di lancio ci mette la collezione DTB
# completa di upstream) e un controllo con 'strings' darebbe un falso negativo.
# /proc/device-tree e' l'albero effettivamente caricato: e' l'unica fonte che conta.
if [ -d /proc/device-tree/sound ]; then
  LINKS=$(for d in /proc/device-tree/sound/*/; do
            tr -d '\0' < "$d/link-name" 2>/dev/null && echo
          done | grep -v '^$')
  echo "$LINKS" | sed 's/^/  dai-link: /'
  if echo "$LINKS" | grep -q 'HDMI/I2S'; then
    ok "il device tree caricato espone 'HDMI/I2S Playback': l'audio ha la strada"
  else
    bad "nessun dai-link HDMI/I2S: l'audio non ha proprio la strada"
    echo "        causa tipica: un pannello DSI abilitato, che esclude l'overlay video_sound-usbc"
  fi
else
  warn "/proc/device-tree/sound assente: device tree non ispezionabile"
fi

# ------------------------------------------------------------------ 5
sez "5. Schermo collegato davvero"
# Il driver ANX7625 configura l'audio solo se HPD e' asserito quando si apre
# il flusso. Uno schermo spento, o un hub che non propaga HPD, danno silenzio
# senza alcun messaggio di errore.
trovato=0
for s in /sys/class/drm/card*-DP-*/status; do
  [ -r "$s" ] || continue
  st=$(cat "$s"); echo "  $(basename $(dirname $s)): $st"
  [ "$st" = connected ] && trovato=1
done
[ "$trovato" = 1 ] && ok "un connettore DisplayPort risulta collegato" \
  || bad "nessun DisplayPort collegato: accendi lo schermo e ricollega l'hub, poi rilancia"

# ------------------------------------------------------------------ 6
sez "6. Schede audio"
aplay -l 2>&1 | sed 's/^/  /'
# Attenzione: l'HDMI qui NON compare come device di nome "HDMI". E' il backend
# di MultiMedia4, cioe' il PCM numero 3 della scheda.
CARD=$(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]\+\):.*\(MultiMedia\|qrb\|Imola\|sndcard\).*/\1/p' | head -1)
[ -z "$CARD" ] && CARD=$(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]\+\):.*/\1/p' | head -1)
if [ -n "$CARD" ]; then
  ok "scheda scelta: card $CARD  (l'HDMI e' il PCM 3, non un device chiamato 'HDMI')"
else
  bad "nessuna scheda audio"
  exit 1
fi

# ------------------------------------------------------------------ 7
sez "7. L'interruttore che conta"
# Questo e' il gate di q6routing. Con il mixer a 0 non esce nulla E aplay
# riporta comunque successo: e' la ragione per cui l'audio sembra rotto.
# Il nome cambia fra le immagini: sulla 6.16.7 di lancio il controllo comandato
# dalla UCM e' 'SEC_MI2S_RX Audio Mixer MultiMedia4'. Esiste anche un piu' generico
# 'HDMI Mixer MultiMedia4' del routing q6, che NON e' quello giusto.
if ! amixer -c "$CARD" cget name="$MIXER" >/dev/null 2>&1; then
  for alt in "HDMI Mixer MultiMedia4" "DISPLAY_PORT_RX Audio Mixer MultiMedia4"; do
    if amixer -c "$CARD" cget name="$alt" >/dev/null 2>&1; then
      warn "'$MIXER' assente su questa immagine, uso '$alt'"
      MIXER="$alt"; break
    fi
  done
fi
amixer -c "$CARD" cget name="$MIXER" 2>&1 | sed 's/^/  /'
if [ "$SOLO_DIAGNOSI" = 1 ]; then
  echo; echo "  (--solo-diagnosi: mi fermo qui)"; exit 0
fi
if amixer -c "$CARD" cset name="$MIXER" 1 >/dev/null 2>&1; then
  ok "mixer '$MIXER' alzato a 1"
else
  bad "il controllo '$MIXER' non esiste su card $CARD"
  echo "        elenco dei controlli disponibili:"
  amixer -c "$CARD" controls 2>/dev/null | grep -i 'mi2s\|hdmi' | sed 's/^/          /'
fi

# ------------------------------------------------------------------ 8
sez "8. Prova del suono"
SUONO=/usr/share/sounds/alsa/Front_Center.wav
[ -f "$SUONO" ] || SUONO=""
echo "  alza il volume dello schermo dall'OSD, poi ascolta il jack."
echo
if [ -n "$SUONO" ]; then
  echo "  aplay -D hw:$CARD,3 $SUONO"
  aplay -D "hw:$CARD,3" "$SUONO" 2>&1 | sed 's/^/    /'
else
  echo "  speaker-test -D hw:$CARD,3 -c 2 -t sine -f 440 -l 1"
  speaker-test -D "hw:$CARD,3" -c 2 -t sine -f 440 -l 1 2>&1 | tail -5 | sed 's/^/    /'
fi

cat <<FINE

${B}== Come si legge l'esito ==${N}

  ${G}Si sente${N}
      Tutta la catena e' provata: kernel, device tree, ALSA, ANX7625,
      DisplayPort, hub UGREEN e schermo. Nessun acquisto, nessuna modifica alla
      scocca. Il cancello del mixer si richiude a ogni avvio: a riaprirlo ci
      pensa  amelie-audio-guard.service  (e  amelie-audio-rotta.service  se la
      rotta cambia). Sono gia' abilitati da scripts/install.sh; verifica con
          systemctl is-enabled amelie-audio-guard amelie-audio-rotta
      e blocca i pacchetti che possono far sparire la scheda:
          sudo apt-mark hold alsa-ucm-conf linux-image-\$(uname -r)

  ${Y}Si sente ma pianissimo${N}
      E' un caso noto, con un rimedio in userspace:
          echo 'api.alsa.soft-mixer = true' | \\
            sudo tee /etc/wireplumber/wireplumber.conf.d/50-alsa-soft-mixer.conf
          systemctl --user restart wireplumber
      Il jack dello schermo e' un'uscita cuffie, non un line-out: parti con il
      volume dello schermo e il potenziometro del PAM8403 bassi, e sali.

  ${R}Silenzio${N}
      Il piano B costa 5 euro, dieci minuti e zero rischio: un adattatore
      audio USB (USB Audio Class) in una delle porte USB-A dell'hub, e da li'
      al PAM8403. Salta HDMI, hub e schermo in un colpo solo.
      Prima di passarci, due controlli: che il punto 5 dica "connected", e
      che PipeWire non stia tenendo attivo un profilo diverso —
          wpctl status
          wpctl set-profile <id-scheda> <indice-profilo-HDMI>
      (su questa board "HDMI" e' un profilo della scheda, non una scheda a se':
      se il profilo attivo e' Headphones, un sink HDMI non esiste proprio)
FINE
