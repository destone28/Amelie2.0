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

# La proposta di tradurre la pagina e' comparsa lo stesso, malgrado i flag:
# nelle versioni recenti e' una bolla, non piu' una infobar, e si spegne solo
# dalle preferenze del profilo. Su un chiosco da ristorante una finestrella di
# Google sopra il marchio non e' un fastidio, e' un difetto.
PROFILO=/home/arduino/.config/amelie-kiosk/Default
mkdir -p "$PROFILO"
if [ ! -s "$PROFILO/Preferences" ] || ! grep -q '"translate"' "$PROFILO/Preferences" 2>/dev/null; then
    printf '%s' '{"translate":{"enabled":false},"translate_site_blacklist":["127.0.0.1"],"intl":{"accept_languages":"it,en"}}' \
        > "$PROFILO/Preferences"
fi

# NON si aspetta il server. Si parte dalla SCHERMATA D'AVVIO, che e' un file e
# quindi esiste gia': compare in un paio di secondi, col marchio, e resta finche'
# il dispositivo non e' pronto davvero - poi e' lei a portarsi sull'applicazione.
#
# Prima si aspettava che il server rispondesse, e per tutta l'attesa - otto
# secondi di ExecStartPre piu' i trenta del caricamento - lo schermo mostrava la
# scrivania del sistema operativo. Aspettare qui significa mostrare qualcos'altro
# li'.
AVVIO="${AMELIE_AVVIO:-/home/arduino/amelie/src/amelie/ui/static/avvio.html}"
if [ -r "$AVVIO" ]; then
    PARTENZA="file://$AVVIO"
else
    # Senza la schermata d'avvio si torna al comportamento di prima, aspettando
    # il server: meglio qualche secondo di scrivania che un errore di Chromium.
    echo "schermata d'avvio non trovata in $AVVIO" >&2
    for _ in $(seq 1 90); do
        curl -sf -m 2 http://127.0.0.1:8080/ >/dev/null 2>&1 && break
        sleep 1
    done
    PARTENZA="http://127.0.0.1:8080/"
fi

# Nessun puntatore, nessun risparmio energetico: uno schermo che si addormenta
# porta via anche l'audio (vedi amelie-display.sh).
command -v unclutter >/dev/null 2>&1 && (unclutter -idle 0 -root &) 2>/dev/null

for browser in chromium chromium-browser google-chrome; do
    command -v "$browser" >/dev/null 2>&1 && break
done
command -v "$browser" >/dev/null 2>&1 || { echo "nessun browser trovato" >&2; exit 1; }

# --kiosk con l'indirizzo, e NON --app=: in modalita' applicazione un cambio di
# origine - che e' esattamente cio' che fa la schermata d'avvio quando si sposta
# sul server - puo' essere espulso in una finestra di browser normale, con la
# barra degli indirizzi. In chiosco non c'e' nessuna interfaccia da nascondere.
#
# --disable-rgba-4444-textures: in modalita' «dispositivo modesto» Chromium
# dipinge lo schermo a riquadri di quattro bit per colore, per risparmiare
# memoria. Sedici livelli per canale: la sfumatura bordeaux del fondo andava a
# gradini, l'oro del marchio si spostava, e riquadri vicini dello stesso nero
# uscivano di due toni diversi - nell'editor della correzione si vedeva un
# rettangolo. Misurato sulla UNO Q: stessi megabyte (GPU 156 contro 147,
# pagina 119 contro 127), e i colori tornano a otto bit.
exec "$browser" \
    --kiosk "$PARTENZA" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI,Translate,TranslateSubFrames \
    --disable-translate \
    --lang=it \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --enable-low-end-device-mode \
    --disable-rgba-4444-textures \
    --renderer-process-limit=1 \
    --disk-cache-size=16777216 \
    --user-data-dir=/home/arduino/.config/amelie-kiosk
