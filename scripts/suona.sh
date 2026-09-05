#!/usr/bin/env bash
# Amelie 2.0 - fa uscire un suono dal jack dello schermo.
#
# Da tenere a portata di mano: quando l'audio "non va", questo dice in dieci
# secondi se il problema e' la catena hardware o il software sopra.
#
#   bash scripts/suona.sh              tono di prova
#   bash scripts/suona.sh file.wav     riproduce un file
#   bash scripts/suona.sh -v           dice una frase (serve Piper)
#
# Lo schermo dev'essere acceso e collegato PRIMA: il driver ANX7625 configura
# l'audio solo se rileva il sink DisplayPort nel momento in cui si apre il
# flusso, e su questo collegamento non c'e' alcun jack che commuti da solo.

set -uo pipefail
MIXER='SEC_MI2S_RX Audio Mixer MultiMedia4'

# La scheda e' quella del SoC; l'HDMI e' il PCM 3 (MultiMedia4), non un device
# che si chiami "HDMI". Cercarlo per nome non funziona: non esiste.
CARD=$(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]\+\).*MultiMedia1.*/\1/p' | head -1)
if [ -z "$CARD" ]; then
  echo "Nessuna scheda audio." >&2
  echo "E' la corsa all'avvio nota: la catena ADSP -> APR -> clock 'audio' ->" >&2
  echo "pinctrl LPI -> scheda audio non si e' completata. Rimedio: riavvia." >&2
  echo "  sudo systemctl restart amelie-audio   (se l'unita' e' installata)" >&2
  exit 1
fi
PCM="hw:${CARD},3"

# Il gate di q6routing. Con il mixer a 0 non esce nulla e aplay riporta
# comunque successo: e' la ragione per cui l'audio sembra rotto quando non lo e'.
amixer -c "$CARD" cset name="$MIXER" 1 >/dev/null 2>&1 \
  || echo "attenzione: non ho potuto alzare '$MIXER'" >&2

case "${1:-}" in
  -v|--voce)
    FRASE="${2:-Un Barolo del duemiladiciannove, dalle colline delle Langhe.}"
    if command -v piper >/dev/null 2>&1; then
      echo "$FRASE" | piper --model it_IT-serena-medium --output-raw 2>/dev/null \
        | aplay -D "$PCM" -r 22050 -f S16_LE -t raw -
    else
      echo "piper non installato: uso il tono." >&2
      speaker-test -D "$PCM" -c 2 -t sine -f 440 -l 1
    fi
    ;;
  "")
    echo "Tono di prova su $PCM. Alza il volume dall'OSD dello schermo."
    speaker-test -D "$PCM" -c 2 -t sine -f 440 -l 1
    ;;
  *)
    aplay -D "$PCM" "$1"
    ;;
esac
