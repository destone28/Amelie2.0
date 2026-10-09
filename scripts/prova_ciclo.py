#!/usr/bin/env python3
"""Esegue il ciclo completo una volta sola, e mostra ogni passaggio.

    python3 scripts/prova_ciclo.py                 scatta e riconosce
    python3 scripts/prova_ciclo.py --foto x.jpg    parte da un'immagine
    python3 scripts/prova_ciclo.py --con-voce      dice anche il racconto
    python3 scripts/prova_ciclo.py --esposizione 600
    python3 scripts/prova_ciclo.py --scala-pose    prova sei pose e le confronta

È il collaudo che si fa con una bottiglia vera davanti al dispositivo: mostra
ogni passaggio con il suo tempo, così si vede subito dove si perde.

**La posa.** L'unica luce che il dispositivo controlla è l'anello: il Modulino
Pixels nella torre, che illumina l'etichetta attraverso la finestra traslucida.
Se l'etichetta viene scura, la prima cosa da provare non è
aggiungere luce: è allungare il tempo di posa. Bottiglia e camera sono ferme
entrambe, quindi si può salire parecchio senza mosso, ed è la posa a dare il
grosso del segnale in questa geometria. `--scala-pose` fa la sweep e dice, per
ogni posa, quanto è nitida l'immagine e quante righe ne tira fuori l'OCR: è
quella tabella che decide, non un'occhiata allo scatto.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))


class LuceDelloScatto:
    """Accende l'anello con la luce con cui legge il dispositivo vero.

    **Non è un abbellimento: senza, questo strumento misura la scena sbagliata.**
    La luce dello scatto è l'anello stesso, bianco e giallo al massimo (`LUCE`
    in `amelie.bridge`). Questa prova si lancia a servizio FERMO — è la
    condizione per non contendere la camera — quindi qui non c'è nessun altro a
    pilotarlo, e l'anello resterebbe come l'ha lasciato la prova precedente.

    Tarare la posa su una scena illuminata da un'altra luce porta a scrivere in
    `capture.py` un valore che nel dispositivo finito brucia l'immagine, o la
    lascia al buio.

    Se l'MCU non risponde lo **dice**, invece di misurare in silenzio una cosa
    diversa da quella che si crede di misurare — e lo dice una volta sola, anche
    se la si riusa per sei pose di seguito. Finita la prova l'anello si spegne:
    a servizio fermo non c'è niente da illuminare.
    """

    def __init__(self) -> None:
        from amelie.bridge import Ponte

        self.ponte = Ponte()
        self.acceso = False
        self._gia_lamentato = False

    def __enter__(self) -> bool:
        from amelie.bridge import LUCE

        try:
            self.ponte.luce(LUCE)
            self.acceso = True
        except Exception as e:                              # noqa: BLE001
            self.acceso = False
            if not self._gia_lamentato:
                self._gia_lamentato = True
                print(f"  ATTENZIONE: anello non acceso ({e.__class__.__name__}).")
                print("  La misura vale MENO di quella vera: nel giro reale")
                print("  l'anello illumina l'etichetta. Collega il Modulino")
                print("  Pixels e verifica il firmware prima di tarare.")
        return self.acceso

    def __exit__(self, *_) -> None:
        from amelie.bridge import LUCE_SPENTA

        if not self.acceso:
            return
        try:
            self.ponte.luce(LUCE_SPENTA)
        except Exception:                                   # noqa: BLE001
            # Simmetrico all'accensione: se l'MCU muore a meta' prova, il
            # ripristino non deve mascherare l'errore vero con il suo.
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--foto", type=Path)
    ap.add_argument("--con-voce", action="store_true")
    ap.add_argument("--salva", type=Path, help="dove salvare lo scatto")
    ap.add_argument("--audio", default="plughw:0,3")
    ap.add_argument("--esposizione", type=int,
                    help="tempo di posa in unità da 100 µs (300 = 30 ms)")
    ap.add_argument("--scala-pose", action="store_true",
                    help="prova una scala di pose e confronta nitidezza e righe lette")
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

    if args.scala_pose:
        scala_pose(args)
        return

    print("CICLO COMPLETO\n")

    if args.foto:
        immagine = cv2.imread(str(args.foto))
        if immagine is None:
            sys.exit(f"non riesco a leggere {args.foto}")
        print(f"  immagine da {args.foto.name}  {immagine.shape[1]}x{immagine.shape[0]}")
    else:
        from amelie.capture import Camera, ImpostazioniCamera, blocca_esposizione
        imp = ImpostazioniCamera()
        if args.esposizione:
            from dataclasses import replace
            imp = replace(imp, esposizione=args.esposizione)
            print(f"  posa: {args.esposizione} (= {args.esposizione / 10:.0f} ms)")
        cam = Camera(imp)
        print(f"  camera: {cam.percorso}")
        blocca_esposizione(cam.imp, cam.percorso)
        with LuceDelloScatto():
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


def scala_pose(args) -> None:
    """Prova una scala di pose sulla stessa scena, e le mette a confronto.

    Serve a rispondere a una domanda sola: con questa luce, quale posa legge
    l'etichetta? Si guardano due numeri insieme, perché uno solo inganna: la
    NITIDEZZA cala quando la posa è così lunga da prendere il micromosso, e le
    RIGHE LETTE calano quando l'immagine è troppo scura o troppo bruciata. La
    posa buona è dove le righe sono tante e la nitidezza non è ancora crollata.

    Fra una posa e l'altra non si muove niente: la scena dev'essere la stessa,
    altrimenti si confrontano due cose diverse.
    """
    from dataclasses import replace

    from amelie.capture import Camera, ImpostazioniCamera, blocca_esposizione
    from amelie.ocr import Lettore

    pose = [150, 300, 600, 1000, 1600, 2500]
    if args.esposizione and args.esposizione not in pose:
        pose = sorted(pose + [args.esposizione])

    base = ImpostazioniCamera()
    lettore = Lettore()

    print("SCALA DELLE POSE\n")
    print("  Non muovere niente fra una posa e l'altra.")

    migliore, migliori_righe = None, -1
    misurate: list[float] = []
    # La luce del dispositivo, accesa per ogni scatto e spenta durante l'OCR:
    # la scena dev'essere identica fra una riga e l'altra della tabella, ma
    # non ha senso tenere otto LED al massimo per i cinque secondi di lettura
    # che stanno in mezzo.
    luce = LuceDelloScatto()
    print("  La luce si accende per ogni scatto, la stessa del dispositivo.")
    print()
    print(f"  {'posa':>8}  {'ms':>6}  {'nitidezza':>10}  {'righe':>6}  primo testo")
    print("  " + "─" * 68)
    for posa in pose:
        imp = replace(base, esposizione=posa)
        cam = Camera(imp)
        blocca_esposizione(imp, cam.percorso)
        try:
            with luce:
                scatto = cam.scatta()
        except Exception as e:                              # noqa: BLE001
            print(f"  {posa:>8}  {posa / 10:>6.0f}  scatto fallito: {e}")
            continue
        righe = [r.testo for r in lettore.leggi(scatto.immagine).righe]
        primo = righe[0][:28] if righe else "—"
        segno = " ←" if len(righe) > migliori_righe else ""
        if len(righe) > migliori_righe:
            migliore, migliori_righe = posa, len(righe)
        misurate.append(scatto.nitidezza)
        print(f"  {posa:>8}  {posa / 10:>6.0f}  {scatto.nitidezza:>10.0f}"
              f"  {len(righe):>6}  {primo}{segno}")
        if args.salva:
            from amelie.capture import salva
            salva(scatto, args.salva.with_name(
                f"{args.salva.stem}-{posa}{args.salva.suffix}"))

    print()
    if migliore is None:
        print("  nessuno scatto riuscito: la camera non risponde")
        return

    # Se il controllo non fa presa, tutte le pose danno la stessa immagine e la
    # tabella sembra dire "la posa non conta". Non e' cosi': vuol dire che il
    # driver ha rimesso i suoi valori riaprendo il device, ed e' documentato che
    # alcuni UVC lo facciano. Meglio dirlo che lasciar concludere il falso.
    if len(misurate) > 2 and max(misurate) - min(misurate) < 0.02 * max(misurate):
        print("  ATTENZIONE: la nitidezza non cambia fra una posa e l'altra.")
        print("  Il controllo V4L2 probabilmente non fa presa: alcuni driver UVC")
        print("  rimettono i propri valori a ogni riapertura del device. Verifica:")
        print("    v4l2-ctl -d $(ls /dev/v4l/by-id/*U20CAM*index0) \\")
        print("        --get-ctrl auto_exposure,exposure_time_absolute")
        print()
    print(f"  La posa che legge di più è {migliore} ({migliore / 10:.0f} ms), "
          f"con {migliori_righe} righe.")
    print(f"  Se è molto lontana da {base.esposizione}, cambia `esposizione` in")
    print("  ImpostazioniCamera (src/amelie/capture.py) e rifai il giro completo.")


def _a_capo(testo: str, larghezza: int) -> list[str]:
    import textwrap
    return textwrap.wrap(testo, larghezza) or [""]


if __name__ == "__main__":
    main()
