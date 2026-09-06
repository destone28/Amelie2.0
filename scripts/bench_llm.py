#!/usr/bin/env python3
"""Misura il modello linguistico sulla board: tempi e qualità.

    python3 scripts/bench_llm.py            un'etichetta, due giri
    python3 scripts/bench_llm.py --tutti    un campione di casi diversi

Il secondo giro serve a misurare l'effetto della cache del prefisso: le
istruzioni sono identiche, quindi llama-server non dovrebbe rileggerle.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.llm import Modello, ModelloNonDisponibile   # noqa: E402
from amelie.matcher import Matcher                       # noqa: E402
from amelie.narrator import _ripulisci, prompt, verifica # noqa: E402

CASI = [
    ["AMARONE DELLA VALPOLICELLA", "Classico", "Tommasi"],
    ["MARCHESI DI BAROLO", "Barolo", "Cannubi", "2016"],
    ["Chianti Classico", "Riserva"],
    ["Vermentino di Sardegna"],
]


def prova(m: Matcher, mod: Modello, righe: list[str], giri: int = 2) -> None:
    f = m.cerca(righe)
    p = prompt(f)
    print(f"\n{'='*70}")
    print(f"{' '.join(righe)[:60]}")
    print(f"  livello {f.livello.value}, sicurezza {f.sicurezza:.0f}, "
          f"prompt {len(p)} caratteri")
    for giro in range(1, giri + 1):
        t0 = time.monotonic()
        try:
            grezzo = mod.genera(p)
        except ModelloNonDisponibile as e:
            print(f"  modello non disponibile: {e}")
            return
        dt = time.monotonic() - t0
        testo = _ripulisci(grezzo)
        ok, inv = verifica(testo, f)
        esito = "OK" if ok else f"SCARTATO {inv}"
        print(f"\n  giro {giro}: {dt:5.1f} s   verifica: {esito}")
        print(f"    {testo[:280]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tutti", action="store_true")
    ap.add_argument("--giri", type=int, default=2)
    args = ap.parse_args()

    mod = Modello()
    if not mod.attendi(30):
        sys.exit("llama-server non risponde: systemctl status amelie-llm")
    m = Matcher()
    for righe in (CASI if args.tutti else CASI[:1]):
        prova(m, mod, righe, args.giri)
    m.chiudi()


if __name__ == "__main__":
    main()
