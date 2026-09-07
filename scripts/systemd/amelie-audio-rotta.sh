#!/usr/bin/env bash
# Amelie 2.0 - apre la rotta audio verso lo schermo.
#
# Il suono NON esce finche' un solo controllo del mixer resta chiuso, e quel
# controllo torna a zero a ogni avvio: non e' memorizzato da nessuna parte.
#
#   MultiMedia4 (hw:0,3)  ->  SEC_MI2S_RX  ->  I2S  ->  ANX7625  ->  HDMI
#                                                    ->  schermo  ->  jack 3,5
#
# Attenzione ai due impostori. La scheda espone anche
# "DISPLAY_PORT_RX Audio Mixer MultiMedia4" e "HDMI Mixer MultiMedia4", che
# hanno il nome giusto e non servono a niente su questa board: aprendo quelli
# il PCM si apre lo stesso ma il DSP rifiuta la registrazione dello stream con
# "q6asm_dai_prepare: stream reg failed ret:-22", e il messaggio non dice da
# nessuna parte che il problema e' l'instradamento. Il connettore si chiama
# DP-1 perche' il ponte ANX7625 si presenta cosi', ma il lato SoC e' DSI piu'
# I2S: l'audio viaggia su MI2S, non su DisplayPort.
set -uo pipefail

SCHEDA="${AMELIE_SCHEDA:-0}"
ROTTA="${AMELIE_ROTTA:-SEC_MI2S_RX Audio Mixer MultiMedia4}"

# Si aspetta la scheda: all'avvio l'ADSP puo' metterci qualche secondo, e la
# guardia dell'audio potrebbe averla appena fatta ricomparire.
for _ in $(seq 60); do
    amixer -c "$SCHEDA" controls >/dev/null 2>&1 && break
    sleep 1
done

numid=$(amixer -c "$SCHEDA" controls 2>/dev/null \
        | grep -F "name='$ROTTA'" | sed -n "s/^numid=\([0-9]*\).*/\1/p")
if [ -z "$numid" ]; then
    echo "rotta '$ROTTA' non trovata sulla scheda $SCHEDA" >&2
    exit 1
fi

amixer -c "$SCHEDA" cset "numid=$numid" 1 >/dev/null || exit 1
echo "rotta audio aperta: $ROTTA (numid=$numid)"

# Il volume delle uscite: si mette al massimo qui una volta sola, perche' il
# livello vero lo decide l'amplificatore a valle.
for nome in 'HPHL Volume' 'HPHR Volume'; do
    n=$(amixer -c "$SCHEDA" controls 2>/dev/null \
        | grep -F "name='$nome'" | sed -n "s/^numid=\([0-9]*\).*/\1/p")
    [ -n "$n" ] && amixer -c "$SCHEDA" cset "numid=$n" 20 >/dev/null 2>&1
done
exit 0
