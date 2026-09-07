#!/usr/bin/env bash
# Amelie 2.0 - spegne cio' che la scrivania avvia da sola e che qui non va.
#
# L'immagine della UNO Q avvia una scrivania XFCE completa, e due delle cose
# che parte da sola sono incompatibili con un oggetto da tavolo di ristorante:
#
#   ArduinoAppLab  apre una finestra propria e ci si mette DAVANTI al chiosco.
#                  E' successo: una sua finestra di aggiornamenti ha coperto
#                  Amelie mentre il dispositivo era acceso e in servizio.
#   light-locker   e' un blocca-schermo. Qui lo schermo non si deve MAI
#                  spegnere: a schermo addormentato si perde anche l'audio,
#                  perche' il ponte ANX7625 configura il flusso solo se vede il
#                  sink DisplayPort (vedi amelie-display.sh).
#
# Si mascherano con una voce nella cartella dell'UTENTE, che ha la precedenza
# su quella di sistema: cosi' un aggiornamento del pacchetto non le riaccende,
# e non si tocca niente fuori da /home.
set -uo pipefail

CARTELLA="${HOME}/.config/autostart"
mkdir -p "$CARTELLA"

for voce in ArduinoAppLab light-locker blueman nm-applet; do
    origine="/etc/xdg/autostart/${voce}.desktop"
    [ -f "$origine" ] || continue
    cat > "$CARTELLA/${voce}.desktop" <<VOCE
[Desktop Entry]
Type=Application
Name=${voce}
Exec=/bin/true
Hidden=true
X-GNOME-Autostart-enabled=false
VOCE
    echo "  spento all'avvio: ${voce}"
done

# E quelli gia' in esecuzione: si chiudono adesso, senza aspettare un riavvio.
for processo in app-lab light-locker; do
    if pkill -x "$processo" 2>/dev/null; then
        echo "  chiuso: $processo"
    fi
done
exit 0
