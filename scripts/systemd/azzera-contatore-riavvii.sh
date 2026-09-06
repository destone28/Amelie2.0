#!/usr/bin/env bash
# Azzera il contatore dei riavvii della guardia audio, una volta che il
# dispositivo ha dimostrato di funzionare. Senza questo, dopo un riavvio di
# recupero il contatore resterebbe a 1 per sempre e la guardia non riproverebbe
# mai piu'. Va lanciato quando l'applicazione e' su e la scheda audio c'e'.
set -uo pipefail
if aplay -l 2>/dev/null | grep -qE '^card [0-9]+:'; then
    rm -f /var/lib/amelie/riavvii-audio
    exit 0
fi
exit 0
