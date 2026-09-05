#!/usr/bin/env bash
# Amelie 2.0 - fissa la modalita' video e impedisce che lo schermo si addormenti.
#
# Non e' un'ottimizzazione, e' un requisito funzionale. Due ragioni:
#
# 1. Il pannello LAFVIN da 5" NON funziona alla sua risoluzione nativa 800x480,
#    benche' xrandr la elenchi per prima e la marchi come preferita: la modalita'
#    viene accettata e attivata, e il pannello resta NERO. E' il modo di fallire
#    documentato su questa board. Si pilota 1280x720, che e' una modalita' CEA
#    vera e la risoluzione dichiarata "optimal" da Arduino, e si lascia che sia
#    il pannello a scalare sui suoi 800x480 fisici.
#
# 2. Se lo schermo si addormenta si perde anche l'AUDIO. Il driver ANX7625
#    configura l'audio solo se rileva il sink DisplayPort nell'istante in cui si
#    apre il flusso: a schermo in powerdown lo stream viene accettato e buttato
#    via senza alcun errore. Un Amelie che si addormenta diventa muto, non solo
#    cieco.
set -uo pipefail

MODO="${AMELIE_MODO:-1280x720}"
FREQ="${AMELIE_FREQ:-60}"

export DISPLAY="${DISPLAY:-:0}"
if [ -z "${XAUTHORITY:-}" ]; then
  for x in /var/lib/lightdm/.Xauthority /run/lightdm/root/:0 /var/run/lightdm/root/:0; do
    [ -r "$x" ] && { export XAUTHORITY="$x"; break; }
  done
fi

# L'uscita si chiama DP-1, ma non diamolo per scontato: si prende la prima connessa.
USCITA=$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')
[ -z "$USCITA" ] && { echo "nessuna uscita connessa" >&2; exit 1; }

xrandr --output "$USCITA" --mode "$MODO" --rate "$FREQ" 2>/dev/null \
  || xrandr --output "$USCITA" --mode "$MODO" 2>/dev/null \
  || echo "modalita' $MODO rifiutata su $USCITA" >&2

# L'ordine conta: 'dpms force on' RIABILITA il DPMS, quindi va prima di '-dpms'.
xset dpms force on
xset s off
xset s noblank
xset -dpms

command -v unclutter >/dev/null 2>&1 && pgrep -x unclutter >/dev/null 2>&1 \
  || (command -v unclutter >/dev/null 2>&1 && unclutter -idle 0 -root &) 2>/dev/null

echo "$USCITA -> $(xrandr --query 2>/dev/null | grep '\*' | awk '{print $1, $2}')"
xset q 2>/dev/null | grep -E "timeout|DPMS is"
