#!/usr/bin/env bash
# Amelie 2.0 - cala il sipario sulla console di testo.
#
# Un dispositivo da tavolo di ristorante non deve mai mostrare il sistema
# operativo. All'accensione, pero', il pannello riceve nell'ordine: i messaggi
# del bootloader, quelli del kernel, quelli di systemd, e solo dopo quaranta
# secondi la sessione grafica. Sono quaranta secondi di testo bianco su nero
# davanti a un ospite seduto.
#
# ── COSA SI PUO' TOGLIERE, E COSA NO ─────────────────────────────────────────
#
# Il `quiet` andrebbe sulla riga di comando del kernel, che qui vive dentro
# un'immagine unificata: cambiarla vuol dire rifare l'immagine di avvio, e una
# board che non riparte piu' costa molto piu' di dodici secondi di testo. Non
# si tocca. Quello che si puo' fare senza rischio e' tutto il resto:
#
#   · i messaggi del KERNEL dopo l'avvio      -> kernel.printk, in sysctl.d
#   · le righe «[ OK ] Started ...» di SYSTEMD -> ShowStatus=no, in system.conf
#   · il testo gia' stampato e il cursore      -> qui sotto
#   · il grigio del framebuffer fra una cosa e l'altra -> qui sotto
#
# Restano visibili i circa dodici secondi di firmware, loader e kernel. Sono
# scritti nella guida, perche' un limite noto e' meno grave di uno scoperto in
# sala.
#
# ── IL COLORE ────────────────────────────────────────────────────────────────
#
# Il framebuffer si tinge del fondo del marchio, lo stesso che amelie-sessione
# stende sulla radice di X e lo stesso della schermata d'avvio: dall'istante in
# cui questo servizio gira fino al racconto non c'e' un solo stacco di colore.
set -uo pipefail

FONDO="${AMELIE_FONDO:-3D1512}"

# 1. Basta messaggi del kernel sulla console. Il livello 1 lascia passare solo
#    le emergenze: se il dispositivo sta per morire, e' giusto che lo dica.
echo "1 4 1 3" > /proc/sys/kernel/printk 2>/dev/null || true

# 2. La console di testo: pulita, senza cursore, e che non si spenga mai da
#    sola - un pannello che va in powerdown si porta via anche l'audio.
for tty in /dev/tty1 /dev/console; do
    [ -w "$tty" ] || continue
    TERM=linux setterm --clear all --cursor off --blank 0 --powersave off \
        > "$tty" 2>/dev/null || true
done

# 3. E il pannello, tinto del fondo del marchio.
python3 - "$FONDO" <<'PY' 2>/dev/null || true
import sys
from pathlib import Path

fb = Path("/dev/fb0")
sysfs = Path("/sys/class/graphics/fb0")
try:
    bpp = int((sysfs / "bits_per_pixel").read_text())
    larghezza, altezza = (int(v) for v in
                          (sysfs / "virtual_size").read_text().strip().split(","))
    passo = int((sysfs / "stride").read_text())
except (OSError, ValueError):
    sys.exit(0)

# Solo 32 bit. Con un formato diverso il rischio non e' un colore sbagliato, e'
# una schermata di rumore: meglio lasciare il nero che c'era.
if bpp != 32:
    sys.exit(0)

colore = sys.argv[1].lstrip("#")
r, g, b = (int(colore[i:i + 2], 16) for i in (0, 2, 4))
# I formati a 32 bit di questi pannelli sono XRGB in little endian, cioe' i
# byte escono B, G, R, X.
riga = bytes((b, g, r, 0xFF)) * larghezza
# Il passo puo' essere piu' largo della riga visibile: il resto si lascia stare.
riga = riga.ljust(passo, b"\x00")[:passo]
try:
    with fb.open("r+b") as f:
        f.write(riga * altezza)
except OSError:
    pass
PY

exit 0
