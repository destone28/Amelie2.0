#!/usr/bin/env python3
"""Estrae dal repository X-Wines il sottoinsieme che serve ad Amelie.

Il repository ufficiale pesa 1,9 GB, di cui 1,1 GB sono 21 milioni di
valutazioni utente destinate ai sistemi di raccomandazione: per riconoscere un
vino da un'etichetta non servono. Questo script tiene i 19.358 vini italiani e
il manifesto delle etichette fotografate, e scarta il resto.

Il repository non e' versionato (vedi .gitignore): va scaricato una volta dal
repository ufficiale X-Wines - vedi docs/it/08-attribuzioni.md per licenza e
citazione obbligatoria - e messo in `data/sources/X-Wines_Official_Repository/`.

    python3 data/estrai_xwines.py

Produce:
    data/sources/xwines_italia.csv        i vini italiani, versionato
    tests/etichette/manifesto.csv         le etichette italiane fotografate

Le fotografie delle etichette NON vengono copiate nel repository: sono opere
grafiche di produttori terzi. Il manifesto permette a chiunque abbia scaricato
X-Wines di ricostruire lo stesso set di prova con `--estrai-immagini`.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SORGENTI = RADICE / "data" / "sources"
XWINES = SORGENTI / "X-Wines_Official_Repository" / "last"
USCITA_VINI = SORGENTI / "xwines_italia.csv"
CARTELLA_PROVA = RADICE / "tests" / "etichette"

ARCHIVI_ETICHETTE = ("XWines_Slim_1K_labels.zip", "XWines_Test_100_labels.zip")

# Campi che teniamo. Si scartano gli identificativi interni delle regioni e
# delle cantine, che non servono a nulla fuori dal dataset originale.
CAMPI = [
    "WineID", "WineName", "Type", "Elaborate", "Grapes", "Harmonize",
    "ABV", "Body", "Acidity", "Country", "RegionName", "WineryName",
    "Website", "Vintages",
]


def leggi_vini() -> list[dict]:
    sorgente = XWINES / "XWines_Full_100K_wines.csv"
    if not sorgente.exists():
        sys.exit(
            f"manca {sorgente}\n"
            "Scarica il repository X-Wines (licenza e citazione in docs/it/08-attribuzioni.md) "
            "in data/sources/X-Wines_Official_Repository/"
        )
    csv.field_size_limit(10 ** 7)
    with sorgente.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def scrivi_italiani(vini: list[dict]) -> list[dict]:
    italiani = [v for v in vini if v.get("Code") == "IT"]
    USCITA_VINI.parent.mkdir(parents=True, exist_ok=True)
    with USCITA_VINI.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, extrasaction="ignore")
        w.writeheader()
        w.writerows(italiani)
    peso = USCITA_VINI.stat().st_size / 1e6
    print(f"  {len(italiani):>6} vini italiani  ->  {USCITA_VINI.name} ({peso:.1f} MB)")
    return italiani


def id_con_etichetta() -> dict[str, str]:
    """Mappa WineID -> nome dell'archivio che contiene la sua fotografia."""
    trovati: dict[str, str] = {}
    for nome in ARCHIVI_ETICHETTE:
        archivio = XWINES / nome
        if not archivio.exists():
            print(f"  (archivio assente, salto: {nome})")
            continue
        with zipfile.ZipFile(archivio) as z:
            for voce in z.namelist():
                if voce.endswith(".jpeg"):
                    trovati.setdefault(Path(voce).stem, nome)
    return trovati


def scrivi_manifesto(italiani: list[dict], etichette: dict[str, str]) -> list[dict]:
    per_id = {v["WineID"]: v for v in italiani}
    righe = [
        {
            "WineID": wid,
            "archivio": archivio,
            "WineName": per_id[wid]["WineName"],
            "WineryName": per_id[wid]["WineryName"],
            "RegionName": per_id[wid]["RegionName"],
            "Type": per_id[wid]["Type"],
            "Vintages": per_id[wid]["Vintages"],
        }
        for wid, archivio in sorted(etichette.items())
        if wid in per_id
    ]
    CARTELLA_PROVA.mkdir(parents=True, exist_ok=True)
    manifesto = CARTELLA_PROVA / "manifesto.csv"
    with manifesto.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(righe[0].keys()) if righe else ["WineID"])
        w.writeheader()
        w.writerows(righe)
    print(f"  {len(righe):>6} etichette italiane fotografate  ->  {manifesto.name}")
    return righe


def estrai_immagini(righe: list[dict]) -> None:
    """Ricostruisce il set di prova in locale, senza ridistribuire nulla."""
    per_archivio: dict[str, list[str]] = {}
    for r in righe:
        per_archivio.setdefault(r["archivio"], []).append(r["WineID"])
    n = 0
    for nome, ids in per_archivio.items():
        with zipfile.ZipFile(XWINES / nome) as z:
            dentro = {Path(v).stem: v for v in z.namelist() if v.endswith(".jpeg")}
            for wid in ids:
                voce = dentro.get(wid)
                if not voce:
                    continue
                destinazione = CARTELLA_PROVA / f"{wid}.jpeg"
                if destinazione.exists():
                    continue
                with z.open(voce) as src, destinazione.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
    print(f"  {n:>6} immagini estratte in {CARTELLA_PROVA}/")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--estrai-immagini",
        action="store_true",
        help="copia anche le fotografie in tests/etichette/ (restano fuori da git)",
    )
    args = ap.parse_args()

    print("Estrazione da X-Wines:")
    vini = leggi_vini()
    print(f"  {len(vini):>6} vini nel dataset completo")
    italiani = scrivi_italiani(vini)
    righe = scrivi_manifesto(italiani, id_con_etichetta())
    if args.estrai_immagini:
        estrai_immagini(righe)
    else:
        print("\n  (per il set di prova OCR:  python3 data/estrai_xwines.py --estrai-immagini)")


if __name__ == "__main__":
    main()
