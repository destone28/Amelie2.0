#!/usr/bin/env bash
# Amelie 2.0 - porta sul dispositivo quello che c'e' nel repository.
#
#   bash scripts/rilascio.sh                 codice, interfaccia, dati, database, test
#   bash scripts/rilascio.sh --con-modello   e anche il modello linguistico
#   bash scripts/rilascio.sh --host amelie2  su un'altra unita'
#
# Va eseguito sul PC di sviluppo. L'unita' si raggiunge per ssh col nome
# configurato in ~/.ssh/config (vedi docs/01-PRIMO-AVVIO.md).
#
# Non usa `rsync`: sulla UNO Q non c'e', e una riga di rsync in mezzo a uno
# script che si crede riuscito e' peggio di un errore. Tutto passa da `scp`, e
# ogni file che conta si riconfronta con md5 dopo essere arrivato.
#
# Prima di sostituire database e modello se ne tiene una copia sulla board:
# il database non sta in git, quindi quella copia e' l'unico modo di tornare
# indietro. Vedi docs/STATO-LAVORI.md.
set -euo pipefail

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST=amelie
CON_MODELLO=0
MODELLO="$HOME/modello/studente_v8/studente-f16.gguf"

while [ $# -gt 0 ]; do
    case "$1" in
        --con-modello) CON_MODELLO=1 ;;
        --modello) MODELLO="$2"; CON_MODELLO=1; shift ;;
        --host) HOST="$2"; shift ;;
        *) echo "argomento sconosciuto: $1" >&2; exit 2 ;;
    esac
    shift
done

cd "$RADICE"
REMOTO=/home/arduino/amelie
ora() { date +%H:%M:%S; }

# Un file e' arrivato davvero solo se il suo md5 coincide. `scp` che fallisce a
# meta' lascia un file troncato e un codice d'uscita che non sempre lo dice.
verifica() {
    local locale="$1" remoto="$2"
    local a b
    a=$(md5sum "$locale" | cut -d' ' -f1)
    b=$(ssh "$HOST" "md5sum $remoto 2>/dev/null | cut -d' ' -f1")
    if [ "$a" != "$b" ]; then
        echo "  DIVERSO dopo la copia: $remoto" >&2
        return 1
    fi
}

echo "### $(ora) unita': $HOST"
ssh -o ConnectTimeout=8 "$HOST" "test -d $REMOTO" || {
    echo "non trovo $REMOTO su $HOST: l'unita' e' installata? (scripts/install.sh)" >&2
    exit 3
}

echo "### $(ora) codice"
scp -q src/amelie/*.py "$HOST:$REMOTO/src/amelie/"
for f in app.py narrator.py matcher.py ocr.py speech.py; do
    verifica "src/amelie/$f" "$REMOTO/src/amelie/$f"
done
echo "  $(ls src/amelie/*.py | wc -l) moduli"

# L'interfaccia: la pagina, la schermata d'avvio, il carattere. Mancava, e per
# due rilasci la board ha girato col server nuovo e la pagina vecchia: nessun
# errore, solo un'interfaccia che non cambiava. I test della pagina girano
# sulla board, quindi si copia PRIMA dei test.
echo "### $(ora) interfaccia"
ssh "$HOST" "mkdir -p $REMOTO/src/amelie/ui/static/fonts"
scp -q src/amelie/ui/static/*.html "$HOST:$REMOTO/src/amelie/ui/static/"
scp -q src/amelie/ui/static/fonts/* "$HOST:$REMOTO/src/amelie/ui/static/fonts/"
for f in index.html avvio.html fonts/EBGaramond.woff2 fonts/EBGaramond-Italic.woff2; do
    verifica "src/amelie/ui/static/$f" "$REMOTO/src/amelie/ui/static/$f"
done
echo "  pagina, avvio, $(ls src/amelie/ui/static/fonts | wc -l) file del carattere"

# Il lessico e' dati, non codice, e si dimentica: `frasi.json` porta le varianti
# con cui si compone il racconto, e una board che ha il codice nuovo col lessico
# vecchio racconta in un modo che nessuna misura ha mai visto.
echo "### $(ora) lessico e vitigni"
scp -q data/lessico/*.json data/lessico/*.txt "$HOST:$REMOTO/data/lessico/"
scp -q data/vitigni.json "$HOST:$REMOTO/data/"
verifica data/lessico/frasi.json "$REMOTO/data/lessico/frasi.json"
echo "  lessico, vocabolari, vitigni"

echo "### $(ora) database (copia di sicurezza, poi sostituzione)"
ssh "$HOST" "cd $REMOTO && cp -n data/amelie.db data/amelie.db.prima-del-rilascio 2>/dev/null; true"
scp -q data/amelie.db "$HOST:$REMOTO/data/amelie.db"
verifica data/amelie.db "$REMOTO/data/amelie.db"
echo "  $(du -h data/amelie.db | cut -f1)"

echo "### $(ora) test"
scp -q tests/*.py "$HOST:$REMOTO/tests/"
scp -q scripts/valuta_generativa.py scripts/prova_finale.py "$HOST:$REMOTO/scripts/" 2>/dev/null || true

echo "### $(ora) suite sulla board (circa due minuti)"
ssh "$HOST" "cd $REMOTO && venv/bin/python -m pytest -q -p no:cacheprovider tests/ 2>&1 | tail -3"

if [ "$CON_MODELLO" = 1 ]; then
    [ -f "$MODELLO" ] || { echo "non trovo il modello: $MODELLO" >&2; exit 4; }
    NOME=$(basename "$(dirname "$MODELLO")")          # es. studente_v8
    echo "### $(ora) modello $NOME: trasferimento di $(du -h "$MODELLO" | cut -f1)"
    echo "     (a circa 1,5 MB/s sono una decina di minuti)"
    scp "$MODELLO" "$HOST:$REMOTO/models/$NOME-f16.gguf"
    verifica "$MODELLO" "$REMOTO/models/$NOME-f16.gguf"

    # Si quantizza SULLA BOARD, non qui: il binario che legge il modello e
    # quello che lo scrive devono venire dallo stesso llama.cpp, e quello che
    # conta e' il suo. Vedi la memoria del fine-tuning.
    echo "### $(ora) quantizzazione Q4_K_M sulla board"
    ssh "$HOST" "cd $REMOTO/models && \
        ~/amelie/llama.cpp/build/bin/llama-quantize $NOME-f16.gguf $NOME-q4_k_m.gguf Q4_K_M \
            > /tmp/quant.log 2>&1 && tail -2 /tmp/quant.log && \
        cp -n studente-q4_k_m.gguf studente-prima-del-rilascio.gguf 2>/dev/null; \
        cp $NOME-q4_k_m.gguf studente-q4_k_m.gguf && rm -f $NOME-f16.gguf && \
        ls -la studente-q4_k_m.gguf"
fi

echo "### $(ora) riavvio"
ssh "$HOST" 'sudo systemctl restart amelie.service
sudo systemctl try-restart amelie-llm.service 2>/dev/null || true
# Il chiosco carica la pagina una volta sola e ci resta per giorni: riavviato
# il server si riaggancia agli eventi, ma la pagina resta quella di prima.
# Ripartendo mostra la schermata d avvio finche il server non risponde.
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
