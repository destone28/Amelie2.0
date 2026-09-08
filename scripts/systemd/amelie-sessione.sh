#!/usr/bin/env bash
# Amelie 2.0 - la sessione grafica del dispositivo. Non c'e' una scrivania.
#
# ── PERCHE' NON BASTA SPEGNERE LE COSE UNA PER UNA ───────────────────────────
#
# L'immagine della UNO Q avvia XFCE completo: xfdesktop disegna uno sfondo e le
# icone, xfce4-panel una barra, e l'autostart apre App Lab. Amelie-scrivania.sh
# ne spegneva i pezzi peggiori uno per uno, ed era una rincorsa: ogni cosa nuova
# che la distribuzione decide di avviare va scoperta e disattivata dopo averla
# vista comparire davanti a un ospite.
#
# Qui la scrivania non c'e' proprio. Questa sessione avvia due cose: un gestore
# di finestre e nient'altro. Il chiosco resta un servizio a se' (amelie-kiosk),
# cosi' conserva il suo Restart=always e i suoi tetti di memoria - se lo si
# avviasse da qui, un Chromium che muore porterebbe via la sessione e con lei
# il server X.
#
# ── PER TORNARE ALLA SCRIVANIA, IN SVILUPPO ──────────────────────────────────
#
#     sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
#     sudo systemctl restart lightdm
#
# e per rimetterla com'era, di nuovo `bash scripts/install.sh`.
set -uo pipefail

export DISPLAY="${DISPLAY:-:0}"

# Il fondo del marchio, steso sulla radice di X. E' il primo colore che il
# pannello riceve dalla sessione grafica, e deve essere lo stesso della
# schermata d'avvio e dell'interfaccia: senza, fra il sipario del framebuffer e
# la prima pagina di Chromium si vede un lampo di grigio - la trama a scacchi
# che X disegna quando nessuno gli ha detto altro.
xsetroot -solid '#3D1512' 2>/dev/null || true

# Lo schermo non si addormenta MAI. Non e' risparmio energetico mancato: a
# pannello in powerdown si perde anche l'audio, perche' il ponte ANX7625
# configura il flusso solo se vede il sink DisplayPort (amelie-display.sh).
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset -dpms 2>/dev/null || true

# Nessun puntatore. Su un vetro capacitivo il cursore non ha significato, e
# resta fermo dove l'ultimo tocco l'ha lasciato.
command -v unclutter >/dev/null 2>&1 && (unclutter -idle 0 -root &) 2>/dev/null

# Un gestore di finestre serve: senza, la finestra a schermo intero di Chromium
# non ha nessuno con cui negoziare la dimensione. xfwm4 c'e' gia' sull'immagine,
# pesa pochi megabyte e senza compositor non contende la GPU alla pagina.
#
# In secondo piano, NON in `exec`. La vita della sessione non va legata a quella
# del gestore di finestre: se questo script esce, lightdm considera finita la
# sessione e fa ripartire il server X, e con lui il chiosco - un xfwm4 che non
# parte diventerebbe un ciclo di riavvii dello schermo invece di una finestra
# mal dimensionata.
command -v xfwm4 >/dev/null 2>&1 && (xfwm4 --compositor=off &) 2>/dev/null

# La sessione resta viva e non fa altro. Il chiosco e' un servizio a se'
# (amelie-kiosk), cosi' conserva Restart=always e i suoi tetti di memoria.
exec sleep infinity
