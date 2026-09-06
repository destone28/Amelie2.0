#!/usr/bin/env bash
# Amelie 2.0 - il browser a schermo intero.
#
# Chromium in modalita' chiosco su una pagina locale. La scelta e' di tempo, non
# di eleganza: HTML e' l'unico ambiente in cui in due giorni si ottiene una
# tipografia da tavolo di ristorante, con font serif veri e testo che appare
# mentre viene scritto.
#
# Il consumo di memoria e' l'unico rischio, ed e' tenuto sotto controllo dai
# flag e dal MemoryMax dell'unita': su 3,6 GiB condivisi con un modello da
# 800 MB non c'e' margine per un browser lasciato libero.
set -uo pipefail

export DISPLAY="${DISPLAY:-:0}"
# L'autorizzazione X della SESSIONE dell'utente, non quella del greeter: con
# l'autologin attivo il server X appartiene ad arduino, e il file del greeter
# non e' leggibile da lui. Chromium fallisce con "The platform failed to
# initialize" ed e' un errore che non dice quale sia il problema.
if [ -z "${XAUTHORITY:-}" ]; then
    for x in "$HOME/.Xauthority" /var/lib/lightdm/.Xauthority; do
        [ -r "$x" ] && { export XAUTHORITY="$x"; break; }
    done
fi

# Il server deve rispondere prima di aprire la pagina, altrimenti Chromium
# mostra un errore e ci resta.
for i in $(seq 1 60); do
    curl -sf -m 2 http://127.0.0.1:8080/ >/dev/null 2>&1 && break
    sleep 1
done

# Nessun puntatore, nessun risparmio energetico: uno schermo che si addormenta
# porta via anche l'audio (vedi amelie-display.sh).
command -v unclutter >/dev/null 2>&1 && (unclutter -idle 0 -root &) 2>/dev/null

for browser in chromium chromium-browser google-chrome; do
    command -v "$browser" >/dev/null 2>&1 && break
done
command -v "$browser" >/dev/null 2>&1 || { echo "nessun browser trovato" >&2; exit 1; }

exec "$browser" \
    --kiosk \
    --app=http://127.0.0.1:8080/ \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI,Translate \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --enable-low-end-device-mode \
    --renderer-process-limit=1 \
    --disk-cache-size=16777216 \
    --user-data-dir=/home/arduino/.config/amelie-kiosk
