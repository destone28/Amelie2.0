#!/usr/bin/env python3
"""Esegue il ciclo completo una volta sola, e racconta cosa è successo.

    python3 scripts/prova_ciclo.py                 scatta e riconosce
    python3 scripts/prova_ciclo.py --foto x.jpg    parte da un'immagine
    python3 scripts/prova_ciclo.py --con-voce      dice anche il racconto

È il collaudo che si fa con una bottiglia vera davanti al dispositivo: mostra
ogni passaggio con il suo tempo, così si vede subito dove si perde.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foto", type=Path)
    ap.add_argument("--con-voce", action="store_true")
    ap.add_argument("--salva", type=Path, help="dove salvare lo scatto")
    ap.add_argument("--audio", default="plughw:0,3")
    args = ap.parse_args()

    import cv2

    from amelie.matcher import Matcher
    from amelie.narrator import Narratore
    from amelie.ocr import Lettore

    tempi: list[tuple[str, float]] = []

    def passo(nome: str, f):
        t = time.monotonic()
        r = f()
        dt = time.monotonic() - t
        tempi.append((nome, dt))
        print(f"  {nome:22} {dt:6.2f} s")
        return r

    print("CICLO COMPLETO\n")

    if args.foto:
        immagine = cv2.imread(str(args.foto))
        if immagine is None:
            sys.exit(f"non riesco a leggere {args.foto}")
        print(f"  immagine da {args.foto.name}  {immagine.shape[1]}x{immagine.shape[0]}")
    else:
        from amelie.capture import Camera, blocca_esposizione
        cam = Camera()
        print(f"  camera: {cam.percorso}")
        blocca_esposizione(cam.imp, cam.percorso)
        scatto = passo("scatto", cam.scatta)
        immagine = scatto.immagine
        print(f"  {'':22} nitidezza {scatto.nitidezza:.0f}"
              f"{'  (SOSPETTO MOSSO)' if scatto.sospetto_mosso else ''}")
        if args.salva:
            from amelie.capture import salva
            salva(scatto, args.salva)
            print(f"  {'':22} salvato in {args.salva}")

    lettore = Lettore()
    lettura = passo("OCR", lambda: lettore.leggi(immagine))
    righe = [r.testo for r in lettura.righe]
    print(f"  {'':22} {len(righe)} righe")
    for r in righe[:8]:
        print(f"  {'':24} {r[:60]}")

    m = Matcher()
    fatti = passo("riconoscimento", lambda: m.cerca(righe))
    print(f"  {'':22} livello {fatti.livello.value}, sicurezza {fatti.sicurezza:.0f}"
          f" ({'certo' if fatti.certo else 'dubbio' if fatti.dubbio else 'sotto soglia'})")
    if fatti.candidati:
        print(f"  {'':22} alternative: {', '.join(fatti.candidati[:2])}")

    n = Narratore()
    racconto = passo("racconto", lambda: n.racconta(fatti, consenti_modello=False))
    print(f"  {'':22} da {racconto.origine}")

    print(f"\n  TOTALE {sum(d for _, d in tempi):.2f} s\n")
    print("  " + "─" * 66)
    for riga in _a_capo(racconto.testo, 66):
        print(f"  {riga}")
    print("  " + "─" * 66)

    if args.con_voce:
        from amelie.speech import ImpostazioniVoce, Voce, VoceNonDisponibile
        try:
            v = Voce(ImpostazioniVoce(device_alsa=args.audio))
            print("\n  parlo…")
            t = time.monotonic()
            v.parla(racconto.frasi)
            print(f"  voce: {time.monotonic() - t:.1f} s")
        except VoceNonDisponibile as e:
            print(f"  voce non disponibile: {e}")

    m.chiudi()
    n.chiudi()


def _a_capo(testo: str, larghezza: int) -> list[str]:
    import textwrap
    return textwrap.wrap(testo, larghezza) or [""]


if __name__ == "__main__":
    main()
