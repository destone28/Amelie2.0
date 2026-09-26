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
  for x in "$HOME/.Xauthority" /var/lib/lightdm/.Xauthority /run/lightdm/root/:0; do
    [ -r "$x" ] && { export XAUTHORITY="$x"; break; }
  done
fi

# L'uscita si chiama DP-1, ma non diamolo per scontato: si prende la prima
# connessa. E si ASPETTA che compaia: ad avvio freddo il collegamento
# DisplayPort attraverso l'ANX7625 non e' pronto nei primi secondi, e con un
# controllo solo il servizio morirebbe, il chiosco che ne dipende non
# partirebbe nemmeno, e il dispositivo si accenderebbe a schermo spento. E' la
# stessa forma di corsa dell'audio (vedi amelie-audio-guard.sh): non si sa
# quando l'hardware c'e', si sa solo aspettarlo.
ATTESA="${AMELIE_ATTESA_VIDEO:-60}"
USCITA=""
for _ in $(seq "$ATTESA"); do
  USCITA=$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')
  [ -n "$USCITA" ] && break
  sleep 1
done
if [ -z "$USCITA" ]; then
  echo "nessuna uscita connessa dopo ${ATTESA}s" >&2
  exit 1
fi

imposta_modo() {
  xrandr --output "$USCITA" --mode "$MODO" --rate "$FREQ" 2>/dev/null \
    || xrandr --output "$USCITA" --mode "$MODO" 2>/dev/null
}
modo_attivo() {
  xrandr --query 2>/dev/null | awk '/\*/{print $1; exit}'
}

imposta_modo

# Se il CRTC rifiuta il cambio - "Configure crtc 0 failed" - non c'e' niente da
# fare a X gia' avviato: il pannello resta a 800x480, che su questo schermo NON
# produce immagine. L'unica via e' far ripartire X, che riapre il connettore e
# accetta la modalita'. Si fa UNA volta per avvio, con lo stesso criterio della
# guardia audio: recuperare a caldo va bene, entrare in ciclo no.
# Il segno sta in /run, quindi sparisce a ogni avvio: un tentativo per accensione.
SEGNO=/run/amelie-video-ritentato
if [ "$(modo_attivo)" != "$MODO" ] && [ ! -e "$SEGNO" ]; then
  echo "modalita' $MODO rifiutata su $USCITA: faccio ripartire X" >&2
  : > "$SEGNO"
  # Staccato, perche' riavviare lightdm da qui dentro ucciderebbe questo stesso
  # script a meta'. Si esce in errore di proposito: ci ripensa Restart=on-failure
  # fra dieci secondi, quando X sara' tornato su.
  systemd-run --no-block --collect --unit=amelie-video-ripristino \
    /usr/bin/systemctl restart lightdm
  exit 1
fi

if [ "$(modo_attivo)" != "$MODO" ]; then
  echo "modalita' $MODO rifiutata su $USCITA anche dopo il riavvio di X" >&2
fi

# L'ordine conta: 'dpms force on' RIABILITA il DPMS, quindi va prima di '-dpms'.
xset dpms force on
xset s off
xset s noblank
xset -dpms

command -v unclutter >/dev/null 2>&1 && pgrep -x unclutter >/dev/null 2>&1 \
  || (command -v unclutter >/dev/null 2>&1 && unclutter -idle 0 -root &) 2>/dev/null

echo "$USCITA -> $(xrandr --query 2>/dev/null | grep '\*' | awk '{print $1, $2}')"
xset q 2>/dev/null | grep -E "timeout|DPMS is"

# L'esito del servizio non puo' dipendere da un grep: con Restart=on-failure
# un'uscita diversa da zero qui farebbe ripartire tutto in cerchio.
exit 0
