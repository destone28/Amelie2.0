#!/usr/bin/env python3
"""Misura l'OCR su etichette di vino vere.

Le 139 immagini italiane di X-Wines hanno la scheda nota accanto — cantina,
nome del vino, regione, annate — quindi si può misurare invece di stimare:
quante volte l'OCR restituisce abbastanza testo da riconoscere il produttore,
la denominazione e l'annata.

Cosa questo misura e cosa NON misura. Sono fotografie di etichette piane,
inquadrate frontalmente: misurano la qualità del RICONOSCIMENTO su tipografia
reale — corsivi, maiuscoletti, testo ruotato sul fianco, oro su fondo scuro.
Non misurano l'ottica di Amelie, che riprende l'etichetta curva a 53° da 100 mm.
Il numero che ne esce è quindi un limite superiore: sul dispositivo si può solo
fare peggio, mai meglio.

Sul PC di sviluppo dà la qualità; sulla board dà il TEMPO, che è il numero da
cui dipende tutta l'esperienza utente.

    python3 scripts/bench_ocr.py                  tutte le etichette
    python3 scripts/bench_ocr.py -n 20            solo le prime 20
    python3 scripts/bench_ocr.py --salva out.json il dettaglio riga per riga
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import statistics
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.ocr import ImpostazioniOCR, Lettore          # noqa: E402
from amelie.text import estrai_annata, normalizza        # noqa: E402

CARTELLA = RADICE / "tests" / "etichette"
MANIFESTO = CARTELLA / "manifesto.csv"

# Sotto questa somiglianza il nome non si considera ritrovato. 80 su 100 con
# `partial_ratio` è severo abbastanza da non premiare le coincidenze e
# tollerante abbastanza da accettare un accento perso o una lettera sbagliata.
SOGLIA = 80


def carica_manifesto(limite: int | None) -> list[dict]:
    if not MANIFESTO.exists():
        sys.exit(
            f"manca {MANIFESTO}\nEsegui prima: python3 data/estrai_xwines.py --estrai-immagini"
        )
    with MANIFESTO.open(encoding="utf-8", newline="") as f:
        righe = [r for r in csv.DictReader(f) if (CARTELLA / f"{r['WineID']}.jpeg").exists()]
    if not righe:
        sys.exit(
            "nessuna immagine in tests/etichette/\n"
            "Esegui: python3 data/estrai_xwines.py --estrai-immagini"
        )
    return righe[:limite] if limite else righe


def annate_attese(grezzo: str) -> set[int]:
    try:
        return {int(v) for v in ast.literal_eval(grezzo) if str(v).isdigit()}
    except (ValueError, SyntaxError):
        return set()


def somiglianza(atteso: str, letto: str) -> float:
    from rapidfuzz import fuzz

    a, b = normalizza(atteso), normalizza(letto)
    if not a or not b:
        return 0.0
    return fuzz.partial_ratio(a, b)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--numero", type=int, default=None)
    ap.add_argument("--salva", type=Path, default=None)
    ap.add_argument("--lato", type=int, default=320, help="lato corto dato al rilevatore")
    ap.add_argument("--thread", type=int, default=4)
    args = ap.parse_args()

    import cv2

    righe = carica_manifesto(args.numero)
    lettore = Lettore(ImpostazioniOCR(lato_rilevatore=args.lato, numero_thread=args.thread))

    print(f"Etichette: {len(righe)}   lato_ril={args.lato}   thread={args.thread}")
    print("Caricamento del motore...", end=" ", flush=True)
    t0 = time.perf_counter()
    lettore._carica()
    print(f"{time.perf_counter() - t0:.1f} s\n")

    esiti, tempi = [], []
    for i, r in enumerate(righe, 1):
        immagine = cv2.imread(str(CARTELLA / f"{r['WineID']}.jpeg"))
        if immagine is None:
            continue
        t = time.perf_counter()
        lettura = lettore.leggi(immagine)          # BGR nativo, non grigio
        tempi.append(time.perf_counter() - t)

        testo = lettura.testo
        anno = estrai_annata(lettura.righe and [x.testo for x in lettura.righe] or [])
        attese = annate_attese(r["Vintages"])

        e = {
            "WineID": r["WineID"],
            "cantina": r["WineryName"],
            "vino": r["WineName"],
            "righe_lette": len(lettura.righe),
            "sim_cantina": somiglianza(r["WineryName"], testo),
            "sim_vino": somiglianza(r["WineName"], testo),
            "annata_letta": anno,
            "annata_plausibile": bool(anno and (not attese or anno in attese)),
            "secondi": round(tempi[-1], 3),
            "testo": testo,
        }
        esiti.append(e)
        if i % 20 == 0 or i == len(righe):
            print(f"  {i}/{len(righe)}...", flush=True)

    n = len(esiti)
    cant = sum(e["sim_cantina"] >= SOGLIA for e in esiti)
    vino = sum(e["sim_vino"] >= SOGLIA for e in esiti)
    uno = sum(e["sim_cantina"] >= SOGLIA or e["sim_vino"] >= SOGLIA for e in esiti)
    ann = sum(e["annata_plausibile"] for e in esiti)
    vuote = sum(e["righe_lette"] == 0 for e in esiti)

    print(f"\n{'='*62}\nRISULTATI su {n} etichette italiane vere\n{'='*62}")
    print(f"  cantina riconosciuta        {cant:4}/{n}  {100*cant/n:5.1f}%")
    print(f"  nome del vino riconosciuto  {vino:4}/{n}  {100*vino/n:5.1f}%")
    print(f"  almeno uno dei due          {uno:4}/{n}  {100*uno/n:5.1f}%")
    print(f"  annata plausibile           {ann:4}/{n}  {100*ann/n:5.1f}%")
    print(f"  nessun testo letto          {vuote:4}/{n}  {100*vuote/n:5.1f}%")
    print(f"\n  righe per etichetta         {statistics.mean(e['righe_lette'] for e in esiti):5.1f} in media")
    print(f"  tempo per etichetta         {statistics.mean(tempi):5.2f} s  "
          f"(mediana {statistics.median(tempi):.2f}, max {max(tempi):.2f})")

    peggiori = sorted(esiti, key=lambda e: max(e["sim_cantina"], e["sim_vino"]))[:5]
    print("\n  le cinque peggiori:")
    for e in peggiori:
        print(f"    {e['WineID']}  {e['cantina'][:24]:26} {e['vino'][:26]:28} "
              f"cant={e['sim_cantina']:3.0f} vino={e['sim_vino']:3.0f} righe={e['righe_lette']}")

    if args.salva:
        args.salva.write_text(json.dumps(esiti, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  dettaglio in {args.salva}")


if __name__ == "__main__":
    main()
