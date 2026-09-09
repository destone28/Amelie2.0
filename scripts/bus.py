#!/usr/bin/env python3
"""Che cosa c'è attaccato al Qwiic, adesso.

    ssh arduino@amelie.local 'cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/bus.py'
    ... --guarda        resta in ascolto e stampa quando qualcosa cambia

Serve con i cavetti in mano. `moduli()` dice se ci sono i due moduli attesi, e
quando dice di no non dice perché: un modulo scambiato, uno a un indirizzo
inatteso e nessun modulo sono tre guasti diversi che da fuori si somigliano
tutti. Questo li distingue.

Due schede Modulino sono quasi identiche a occhio — stesso blu, stessa forma,
stessi due connettori — e si distinguono solo dal componente al centro e da una
piccola icona. Farlo decidere al dispositivo è più veloce e non sbaglia.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))


def racconta(p) -> str:
    if not p.disponibile:
        return ("l'MCU non risponde: o non ha il firmware di Amelie, o è "
                "bloccato.\n  Carica firmware/amelie_mcu e togli corrente una "
                "volta.")
    v = p.versione()
    if v is None:
        return ("firmware anteriore al protocollo 2: non sa scandire il bus.\n"
                "  Carica firmware/amelie_mcu.")

    trovati = p.scansiona()
    if trovati is None:
        return f"protocollo {v}: questo firmware non sa scandire il bus."
    if not trovati:
        return ("nessun dispositivo sul bus Qwiic.\n"
                "  Il cavetto è inserito a fondo da tutte e due le parti?")

    nomi = p.nomi_noti(trovati)
    righe = [f"  {a:#04x}  {nomi[a]}" for a in trovati]

    # Un sensore che risponde all'indirizzo ma non e' partito e' il caso che
    # confonde di piu': c'e' sul bus e non misura. Qui si dice a che punto si e'
    # fermato, invece di lasciarlo dedurre.
    if 0x29 in trovati:
        passi = {0: None,
                 -1: "l'avvio non e' mai stato tentato",
                 2: "il chip non ha finito di avviarsi in tempo",
                 3: "la scrittura della configurazione di fabbrica",
                 4: "la calibrazione VHV",
                 5: "il calcolo dei tempi di misura",
                 6: "l'avvio della misura continua"}
        stato = p.stato_sensore()
        if stato is not None and stato != 0:
            righe.append("        sensore NON avviato: "
                         + passi.get(stato, f"passo {stato}"))
    atteso = {0x36, 0x29}
    manca = atteso - set(trovati)
    coda = []
    if manca:
        quali = {0x36: "l'anello (Modulino Pixels)",
                 0x29: "il sensore (Modulino Distance)"}
        coda.append("  manca: " + ", ".join(quali[a] for a in sorted(manca)))
    if set(trovati) - atteso:
        coda.append("  c'è qualcosa che il dispositivo non si aspetta")
    return "\n".join(righe + coda)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--guarda", action="store_true",
                    help="resta in ascolto e stampa quando cambia")
    args = ap.parse_args()

    from amelie.bridge import Ponte

    p = Ponte(timeout=3.0)
    if not args.guarda:
        print(racconta(p))
        return

    print("in ascolto: collega un pezzo per volta.\n")
    prima = None
    while True:
        ora = racconta(p)
        if ora != prima:
            print(time.strftime("%H:%M:%S"))
            print(ora, flush=True)
            prima = ora
        time.sleep(1)


if __name__ == "__main__":
    main()
