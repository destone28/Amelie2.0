#!/usr/bin/env python3
"""Misura il riconoscimento end-to-end: testo OCR reale -> record del database.

Usa l'uscita di `bench_ocr.py --salva`, che contiene per ogni etichetta il testo
letto davvero E la scheda nota (cantina, nome del vino). Si verifica quanto
spesso la cascata arriva al vino giusto, e quando non ci arriva, dove si ferma.

    python3 scripts/bench_matcher.py /percorso/ocr.json
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from amelie.matcher import Livello, Matcher, SOGLIA_CERTA, SOGLIA_DUBBIA  # noqa: E402
from amelie.text import normalizza                                        # noqa: E402


def main() -> None:
    sorgente = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not sorgente or not sorgente.exists():
        sys.exit("uso: bench_matcher.py <uscita di bench_ocr.py --salva>")
    esiti = json.loads(sorgente.read_text(encoding="utf-8"))
    m = Matcher()

    livelli = collections.Counter()
    fasce = collections.Counter()
    giusti = sbagliati = 0
    esempi_sbagliati = []

    for e in esiti:
        righe = [r for r in (e.get("testo") or "").split("\n") if r.strip()]
        if not righe:
            livelli["nessun testo"] += 1
            continue
        f = m.cerca(righe)
        livelli[f.livello.value] += 1
        fasce["certo" if f.certo else "dubbio" if f.dubbio else "sotto soglia"] += 1

        # Il metro deve rispettare la cascata: scendere al livello giusto e' un
        # SUCCESSO, non un errore. "Tenuta Il Poggione / Brunello di Montalcino"
        # che si ferma sulla tipologia "Brunello di Montalcino" ha detto una cosa
        # vera; conta come sbagliato solo se afferma qualcosa che non torna.
        atteso_cant = normalizza(e.get("cantina", ""))
        atteso_vino = normalizza(e.get("vino", ""))
        trovato = normalizza(" ".join(filter(
            None, [f.cantina, f.nome, f.denominazione, f.tipologia,
                   " ".join(f.vitigni)])))
        coerente = (
            (atteso_cant and atteso_cant in trovato)
            or (trovato and trovato in f"{atteso_cant} {atteso_vino}")
            or any(p in atteso_vino.split() for p in trovato.split() if len(p) > 4)
        )
        if coerente:
            giusti += 1
        elif f.livello is not Livello.NULLA:
            sbagliati += 1
            if len(esempi_sbagliati) < 6:
                esempi_sbagliati.append(
                    (e.get("cantina"), e.get("vino"), f.livello.value,
                     f.cantina or f.denominazione or (f.vitigni[0] if f.vitigni else "?"),
                     round(f.sicurezza)))

    n = len(esiti)
    print(f"{'='*66}\nRICONOSCIMENTO su {n} etichette (testo OCR reale)\n{'='*66}")
    print(f"  coerente con l'etichetta    {giusti:4}/{n}  {100*giusti/n:5.1f}%")
    print(f"  INCOERENTE (figuraccia)     {sbagliati:4}/{n}  {100*sbagliati/n:5.1f}%")
    print("\n  dove si ferma la cascata:")
    for liv in ("vino", "tipologia", "denominazione", "vitigno", "nulla", "nessun testo"):
        if livelli[liv]:
            print(f"    {liv:14} {livelli[liv]:4}  {100*livelli[liv]/n:5.1f}%")
    print(f"\n  sicurezza (>={SOGLIA_CERTA} certo, >={SOGLIA_DUBBIA} dubbio):")
    for fascia in ("certo", "dubbio", "sotto soglia"):
        if fasce[fascia]:
            print(f"    {fascia:14} {fasce[fascia]:4}  {100*fasce[fascia]/n:5.1f}%")
    if esempi_sbagliati:
        print("\n  esempi di match su altro:")
        for cant, vino, liv, trov, sic in esempi_sbagliati:
            print(f"    atteso {str(cant)[:22]:24} / {str(vino)[:24]:26}")
            print(f"      -> {liv} '{str(trov)[:40]}' ({sic})")
    m.chiudi()


if __name__ == "__main__":
    main()
