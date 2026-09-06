#!/usr/bin/env bash
# Amelie 2.0 - garantisce che al termine dell'avvio la scheda audio esista.
#
# ## Il guasto
#
# Circa un avvio su tre la scheda audio non si presenta. Misurato: 2 su 6.
# La catena e' lunga e basta che il primo anello arrivi tardi:
#
#   qcom_pd_mapper (bus auxiliary)  ->  l'ADSP registra la protection domain
#     "msm/adsp/audio_pd"  ->  il PDR manda SERVICE_STATE_UP  ->  apr.c crea
#     q6core/q6afe/q6asm/q6adm su aprbus  ->  q6afecc registra il clock "audio"
#     ->  pinctrl@a7c0000 ottiene il clock e registra gli stati pin
#     ->  la scheda audio esce dal deferred probe
#
# Su qcm2290 TUTTI i servizi APR audio hanno `qcom,protection-domain`, e apr.c
# li crea SOLO quando il PDR dice UP. Se quel momento non arriva, /sys/bus/
# aprbus/devices resta vuoto e non esiste alcuna scheda: e' la firma del guasto.
#
# In /etc/modprobe.d/amelie-audio-race.conf c'e' gia' il softdep che carica
# qcom_pd_mapper prima di qcom_common (la mitigazione proposta upstream da Loic
# Poulain). Aiuta, ma NON basta: il device ausiliario del mapper nasce dentro
# rproc_boot(), quindi l'ADSP puo' interrogarlo prima che il driver si sia
# agganciato. Da qui questa guardia.
#
# ## Il rimedio
#
# Riavviare il solo remoteproc dell'ADSP. Provato sul guasto reale: i device
# aprbus ricompaiono dopo 1 secondo e la scheda torna. E' anche l'unico percorso
# pulito, perche' qcom_glink_native_remove() smonta e rimonta i canali glink in
# modo ordinato. NON si tocca il modulo `apr` ne' con modprobe -r ne' con
# unbind: e' un percorso che puo' far cadere il kernel.
#
# ## Le funi di sicurezza
#
# Questo script puo' riavviare il dispositivo, quindi ogni condizione e' scritta
# per NON farlo:
#   - non fa nulla se la scheda audio c'e' gia';
#   - non tocca l'ADSP se un PCM e' aperto (qualcuno sta ascoltando);
#   - non riavvia se il dispositivo e' in servizio da piu' di TETTO_UPTIME
#     secondi: un guasto tardivo non deve spegnere un tavolo;
#   - riavvia UNA volta sola, con contatore su disco persistente;
#   - si ferma del tutto se esiste il file di emergenza, che si crea da remoto
#     per fermare un ciclo senza dover riflashare.
set -uo pipefail

STATO=/var/lib/amelie
CONTATORE=$STATO/riavvii-audio
EMERGENZA=$STATO/niente-riavvii
REGISTRO=$STATO/audio-guard.log
TETTO_UPTIME=600          # oltre 10 minuti dall'avvio non si riavvia piu'
ATTESA_APR=25

mkdir -p "$STATO" 2>/dev/null || true
log() { printf '%s  %s\n' "$(date -Is)" "$*" | tee -a "$REGISTRO" >&2; }

scheda_presente() { aplay -l 2>/dev/null | grep -qE '^card [0-9]+:'; }
pcm_in_uso() { grep -l RUNNING /proc/asound/card*/pcm*/sub*/status 2>/dev/null | grep -q .; }
n_apr() { ls /sys/bus/aprbus/devices/ 2>/dev/null | wc -l; }   # aprbus, NON apr
uptime_s() { awk '{print int($1)}' /proc/uptime; }

# ------------------------------------------------------------------ 1. serve?

if scheda_presente; then
    log "scheda audio presente, niente da fare (aprbus: $(n_apr))"
    exit 0
fi
log "NESSUNA scheda audio (aprbus: $(n_apr), uptime: $(uptime_s)s) - avvio il recupero"

if pcm_in_uso; then
    log "un PCM risulta in uso: non tocco l'ADSP"
    exit 0
fi

# ------------------------------------------------- 2. recupero: riavvio ADSP

ADSP=""
for d in /sys/class/remoteproc/remoteproc*; do
    [ "$(cat "$d/name" 2>/dev/null)" = adsp ] && { ADSP="$d"; break; }
done

if [ -n "$ADSP" ] && [ -e "$ADSP/state" ]; then
    log "riavvio $ADSP (stato: $(cat "$ADSP/state" 2>/dev/null))"

    # Se lo script viene ucciso fra lo stop e lo start si resterebbe con l'ADSP
    # spento, cioe' peggio di come si e' cominciato. Il trap ritenta lo start.
    riparti() { [ "$(cat "$ADSP/state" 2>/dev/null)" = offline ] \
        && echo start > "$ADSP/state" 2>/dev/null || true; }
    trap riparti EXIT TERM INT

    if ! echo stop > "$ADSP/state" 2>/dev/null; then
        log "stop rifiutato"
    else
        sleep 3
        avviato=0
        for i in 1 2 3; do
            echo start > "$ADSP/state" 2>/dev/null || true
            sleep 5
            if [ "$(cat "$ADSP/state" 2>/dev/null)" = running ]; then
                avviato=1; log "ADSP ripartito (tentativo $i)"; break
            fi
            log "tentativo $i non riuscito"
            sleep 3
        done
        if [ "$avviato" = 0 ]; then
            log "ADSP NON ripartito: stato peggiore di prima"
        else
            for i in $(seq 1 "$ATTESA_APR"); do
                [ "$(n_apr)" -gt 0 ] && { log "device aprbus dopo ${i}s: $(n_apr)"; break; }
                sleep 1
            done
        fi
    fi
    trap - EXIT TERM INT
else
    log "nessun remoteproc 'adsp' trovato"
fi

if scheda_presente; then
    log "RECUPERATA a caldo: $(aplay -l 2>/dev/null | grep -m1 '^card')"
    exit 0
fi

# ---------------------------------------------- 3. ultima risorsa: un riavvio

if [ -e "$EMERGENZA" ]; then
    log "recupero fallito, ma $EMERGENZA esiste: NON riavvio"
    exit 1
fi

fatti=$(cat "$CONTATORE" 2>/dev/null || echo 0)
case "$fatti" in ''|*[!0-9]*) fatti=0;; esac

if [ "$fatti" -ge 1 ]; then
    log "recupero fallito e ho gia' riavviato $fatti volta/e: mi fermo, resto muto"
    exit 1
fi

su=$(uptime_s)
if [ "$su" -gt "$TETTO_UPTIME" ]; then
    log "recupero fallito ma il dispositivo e' in servizio da ${su}s: NON riavvio"
    exit 1
fi

echo $((fatti + 1)) > "$CONTATORE"
sync
log "recupero fallito: riavvio UNA volta (contatore -> $((fatti + 1)))"
systemctl --no-block reboot
exit 1
