#!/usr/bin/env bash
# Amelie 2.0 - compila e carica il firmware del microcontrollore.
#
#   bash scripts/firmware.sh            carica solo se serve
#   bash scripts/firmware.sh --sempre   ricarica comunque
#
# Va eseguito SULLA BOARD, come utente arduino. Non chiede password: compila con
# arduino-cli e carica con remoteocd, che senza indirizzo ne' numero di serie
# lavora in locale, con l'OpenOCD della board. Lo lancia scripts/install.sh al
# passo 9; da solo serve quando il microcontrollore non risponde (vedi
# docs/it/04-collaudo.md, «Il microcontrollore»).
#
# SKETCH E LOADER VANNO IN COPPIA. Sul microcontrollore della UNO Q gira un
# loader Zephyr, che all'accensione avvia lo sketch da un indirizzo fisso della
# flash. Loader e indirizzo cambiano col core: nel core 0.52.0 lo sketch sta a
# 0x80F0000, nel core 1.0.0 a 0x8100000. App Lab, aggiornandosi, porta il
# suo loader; uno sketch caricato da solo con un core diverso finisce dove quel
# loader non guarda. Il caricamento riesce, e il microcontrollore tace.
#
# Per questo:
# - si caricano sempre loader e sketch insieme, con lo script OpenOCD del core,
#   che riscrive il loader solo se e' diverso da quello che c'e';
# - il firmware si dichiara caricato solo quando il microcontrollore RISPONDE,
#   non quando il caricamento finisce;
# - a ogni lancio si chiede al microcontrollore se risponde, e se tace si
#   ricarica anche quando l'impronta dice che e' gia' tutto fatto.
set -euo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Le versioni collaudate. Il core deve essere lo stesso di App Lab: e' il suo
# loader quello che resta sul microcontrollore.
CORE_MCU="arduino:zephyr@1.0.0"
LIBRERIE_MCU="Arduino_RouterBridge@0.4.3"
FQBN=arduino:zephyr:unoq
VARIANTE=arduino_uno_q_stm32u585xx

USCITA="$RADICE/var/firmware"
SKETCH="$USCITA/amelie_mcu.ino.elf-zsk.bin"
PACCHETTI="$HOME/.arduino15/packages/arduino"
CORE_DIR="$PACCHETTI/hardware/zephyr/${CORE_MCU##*@}"
LOADER="$CORE_DIR/firmwares/zephyr-$VARIANTE.elf"
CFG="$CORE_DIR/variants/$VARIANTE/flash_sketch.cfg"

R=$'\033[31m'; N=$'\033[0m'
[ -t 1 ] || { R=''; N=''; }
avviso() { echo "    ${R}!${N} $*"; }
muori() { echo "    ${R}ERRORE:${N} $*" >&2; exit 1; }

SEMPRE=0
case "${1:-}" in
    --sempre) SEMPRE=1 ;;
    "") ;;
    *) echo "uso: bash scripts/firmware.sh [--sempre]" >&2; exit 2 ;;
esac

[ "$(id -un)" = arduino ] || muori "va eseguito come utente arduino, non come $(id -un)"
cd "$RADICE"
mkdir -p "$USCITA"

# Chiede al microcontrollore, attraverso il router, se c'e' lo sketch di Amelie
# con il protocollo che l'applicazione si aspetta. Serve l'ambiente Python
# (passo 4 dell'installazione): senza, si considera che non risponda.
python_amelie() {
    PYTHONPATH="$RADICE/src" "$RADICE/venv/bin/python" - "$@" 2>/dev/null
}
risponde() {
    [ -x "$RADICE/venv/bin/python" ] || return 1
    python_amelie <<'PY'
import logging, sys
logging.disable(logging.WARNING)
from amelie.bridge import PROTOCOLLO_ATTESO, Ponte
sys.exit(0 if Ponte(timeout=2.0).versione() == PROTOCOLLO_ATTESO else 1)
PY
}
# Quali Modulino vede. Il firmware li cerca nei primi secondi dopo l'avvio del
# microcontrollore: si riprova per quindici secondi, non di piu'.
moduli() {
    python_amelie <<'PY'
import logging, time
logging.disable(logging.WARNING)
from amelie.bridge import Ponte
p = Ponte(timeout=2.0)
fine = time.monotonic() + 15
while True:
    m = p.moduli()
    if all(m.values()) or time.monotonic() > fine:
        break
    time.sleep(1)
nomi = {"anello": "Pixels", "distanza": "Distance"}
print(", ".join(f"{nomi[n]} {'visto' if v else 'NON visto'}" for n, v in m.items()))
PY
}
# Il resoconto finale: i moduli, e cosa fare se ne manca uno.
riferisci() {
    local visti
    visti=$(moduli) || visti=""
    echo "    $1: ${visti:-moduli non leggibili}"
    case "$visti" in
        *"NON visto"*)
            avviso "un Modulino manca: controlla il cavo Qwiic, poi spegni e riaccendi" \
                "(i moduli si cercano solo all'accensione del microcontrollore)" ;;
    esac
}

# Il core e le librerie, alle versioni collaudate.
arduino-cli core update-index >/dev/null
arduino-cli core install "$CORE_MCU" >/dev/null
# shellcheck disable=SC2086
arduino-cli lib install $LIBRERIE_MCU >/dev/null
[ -f "$LOADER" ] && [ -f "$CFG" ] || muori "loader o configurazione OpenOCD del core non trovati in $CORE_DIR"
OCD=$(find "$PACCHETTI/tools/remoteocd" -name remoteocd -type f 2>/dev/null | sort -V | tail -1)
[ -n "$OCD" ] || muori "remoteocd non trovato in $PACCHETTI/tools"

# Si ricompila quando cambiano lo sketch, il core o le librerie.
FIRMA=$( (cat firmware/amelie_mcu/*.ino; echo "$CORE_MCU $LIBRERIE_MCU") | sha256sum | cut -c1-16)
if [ "$(cat "$USCITA/.compilato" 2>/dev/null)" != "$FIRMA" ] || [ ! -f "$SKETCH" ]; then
    echo "    compilo lo sketch (un paio di minuti)"
    arduino-cli compile -b "$FQBN" --output-dir "$USCITA" firmware/amelie_mcu >/dev/null
    echo "$FIRMA" > "$USCITA/.compilato"
fi

if [ "$SEMPRE" = 0 ] && [ "$(cat "$USCITA/.caricato" 2>/dev/null)" = "$FIRMA" ] && risponde; then
    riferisci "gia' caricato, e il microcontrollore risponde"
    exit 0
fi

# App Lab puo' avviare una sua app all'accensione, che sostituirebbe questo
# firmware sul microcontrollore: nessuna app predefinita.
arduino-app-cli properties set default none >/dev/null 2>&1 || true

systemctl is-active -q arduino-router \
    || muori "arduino-router e' fermo: sudo systemctl restart arduino-router, poi rilancia"

rm -f "$USCITA/.caricato"
if ! "$OCD" upload -f "$CFG" "$LOADER" "$SKETCH" > "$USCITA/caricamento.log" 2>&1; then
    tail -5 "$USCITA/caricamento.log" | sed 's/^/      /'
    muori "caricamento non riuscito: rilancia; se si ripete, spegni e riaccendi la board"
fi

# Il microcontrollore si riavvia col firmware nuovo: si aspetta che risponda.
for _ in $(seq 1 30); do
    if risponde; then
        echo "$FIRMA" > "$USCITA/.caricato"
        riferisci "firmware caricato, il microcontrollore risponde"
        exit 0
    fi
    sleep 1
done
avviso "firmware caricato, ma il microcontrollore non risponde"
avviso "guarda il router: journalctl -u arduino-router -n 30"
exit 1
