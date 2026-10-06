#!/usr/bin/env bash
# Amelie 2.0 - porta sulla board la copia di lavoro di un PC.
#
#   bash scripts/rilascio.sh                                         su arduino@amelie.local
#   bash scripts/rilascio.sh --host arduino@<indirizzo-della-board>  su un'altra board
#
# E' uno strumento per chi modifica il codice su un PC e vuole provarlo sul
# dispositivo senza passare dal repository. Per aggiornare una board basta,
# sulla board stessa, nella cartella del repository:
#
#     git pull && bash scripts/install.sh
#
# La board deve essere gia' installata con scripts/install.sh: questo script
# copia codice, interfaccia, lessico, database e test, fa girare la suite sulla
# board e riavvia l'applicazione e il chiosco. Il modello linguistico, le voci e
# il firmware del microcontrollore non li tocca.
#
# Se ~/amelie sulla board e' un clone git, i file copiati da qui vi compaiono
# come modifiche locali, e un `git pull` successivo puo' rifiutarsi di
# sovrascriverli: `git checkout -- .` li riporta alla versione del repository.
#
# Non usa `rsync`, che sulla UNO Q non c'e': tutto passa da `scp`, e ogni file
# copiato si riconfronta con md5 dopo essere arrivato.
set -euo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST=arduino@amelie.local

while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift ;;
        *) echo "argomento sconosciuto: $1" >&2; exit 2 ;;
    esac
    shift
done

cd "$RADICE"
REMOTO=/home/arduino/amelie
ora() { date +%H:%M:%S; }

# Un file e' arrivato davvero solo se il suo md5 coincide: `scp` che fallisce a
# meta' lascia un file troncato e un codice d'uscita che non sempre lo dice.
# I percorsi sono relativi alla radice, che sulla board e' $REMOTO; si
# confrontano tutti con una connessione sola.
verifica() {
    local locali remoti
    locali=$(md5sum "$@")
    remoti=$(ssh "$HOST" "cd $REMOTO && md5sum $* 2>/dev/null" || true)
    if [ "$locali" != "$remoti" ]; then
        echo "  DIVERSI dopo la copia:" >&2
        diff <(echo "$locali") <(echo "$remoti") | sed -n 's/^< [0-9a-f]*  /    /p' >&2
        return 1
    fi
}

echo "### $(ora) board: $HOST"
ssh -o ConnectTimeout=8 "$HOST" "test -d $REMOTO" || {
    echo "non trovo $REMOTO su $HOST: la board e' installata? (scripts/install.sh)" >&2
    exit 3
}

echo "### $(ora) codice"
scp -q src/amelie/*.py "$HOST:$REMOTO/src/amelie/"
verifica src/amelie/*.py
echo "  $(ls src/amelie/*.py | wc -l) moduli"

# L'interfaccia: la pagina, la schermata d'avvio, il carattere. Il server nuovo
# con la pagina vecchia non da' errori, da' solo un'interfaccia che non cambia.
# I test della pagina girano sulla board, quindi si copia PRIMA dei test.
echo "### $(ora) interfaccia"
ssh "$HOST" "mkdir -p $REMOTO/src/amelie/ui/static/fonts"
scp -q src/amelie/ui/static/*.html "$HOST:$REMOTO/src/amelie/ui/static/"
scp -q src/amelie/ui/static/fonts/* "$HOST:$REMOTO/src/amelie/ui/static/fonts/"
verifica src/amelie/ui/static/*.html src/amelie/ui/static/fonts/*
echo "  pagina, avvio, $(ls src/amelie/ui/static/fonts | wc -l) file del carattere"

# Il lessico e' dati, non codice, ma va insieme al codice: `frasi.json` porta le
# varianti con cui si compone il racconto, e il codice nuovo col lessico vecchio
# racconta in un modo che nessun test ha mai visto.
echo "### $(ora) lessico e vitigni"
scp -q data/lessico/*.json data/lessico/*.txt "$HOST:$REMOTO/data/lessico/"
scp -q data/vitigni.json "$HOST:$REMOTO/data/"
verifica data/lessico/*.json data/lessico/*.txt data/vitigni.json
echo "  lessico, vocabolari, vitigni"

# Il database non sta in git: la copia di sicurezza sulla board e' l'unico modo
# di tornare indietro. `cp -n` non la sovrascrive, quindi resta il database che
# la board aveva prima del primo rilascio.
echo "### $(ora) database (copia di sicurezza, poi sostituzione)"
ssh "$HOST" "cd $REMOTO && cp -n data/amelie.db data/amelie.db.prima-del-rilascio 2>/dev/null; true"
scp -q data/amelie.db "$HOST:$REMOTO/data/amelie.db"
verifica data/amelie.db
echo "  $(du -h data/amelie.db | cut -f1)"

echo "### $(ora) test"
scp -q tests/*.py "$HOST:$REMOTO/tests/"
verifica tests/*.py

# La suite gira sull'hardware vero. Se fallisce lo si dice, ma si riavvia lo
# stesso: e' il codice appena copiato, e il log dice che cosa guardare.
echo "### $(ora) suite sulla board (circa due minuti)"
# pytest non fa parte del dispositivo: lo si installa la prima volta.
ssh "$HOST" "cd $REMOTO && (venv/bin/python -c 'import pytest' 2>/dev/null \
        || venv/bin/pip install -q -r requirements-dev.txt)"
ssh "$HOST" "cd $REMOTO && venv/bin/python -m pytest -q -p no:cacheprovider tests/ \
        > /tmp/amelie-test.log 2>&1; esito=\$?; tail -3 /tmp/amelie-test.log; exit \$esito" \
    || echo "  ATTENZIONE: la suite non e' passata (log completo in /tmp/amelie-test.log sulla board)" >&2

# Il chiosco carica la pagina una volta sola: riavviato il server si riaggancia
# agli eventi, ma la pagina resta quella caricata all'avvio. Ripartendo mostra
# la schermata d'avvio finche' il server non risponde.
echo "### $(ora) riavvio"
# -t: se sudo chiede la password dell'utente arduino, serve un terminale.
ssh -t "$HOST" 'sudo systemctl restart amelie.service
sudo systemctl try-restart amelie-kiosk.service 2>/dev/null || true
sleep 35
echo "  servizio: $(systemctl is-active amelie.service)"
echo "  modo:     $(cat ~/amelie/var/modo 2>/dev/null)"
curl -s --max-time 6 localhost:8080/stato | python3 -c "
import json,sys
d = json.load(sys.stdin)
print(\"  stato:   \", {k: d.get(k) for k in (\"stato\", \"bottiglia\", \"moduli\")})" 2>/dev/null || echo "  la pagina di stato non risponde"
journalctl -u amelie.service --since "-40s" --no-pager 2>/dev/null \
    | grep -aiE "error|traceback" | grep -v graceful | tail -3'

echo "### $(ora) fatto"
