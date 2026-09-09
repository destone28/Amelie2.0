# Amelie 2.0

Un supporto da tavolo che riconosce un vino dall'etichetta e ne racconta la
storia. Si appoggia la bottiglia, un anello di luce si accende, una telecamera
legge l'etichetta e il dispositivo racconta — a schermo e a voce.

**Tutto avviene a bordo.** Nessuna connessione, nessun servizio esterno, nessun
dato che esce dal tavolo.

<!-- TODO: fotografia del dispositivo finito -->

---

## Come funziona

```
   bottiglia appoggiata
        │
        ▼
   sensore di distanza ──► l'MCU sveglia Linux
        │
        ▼
   anello di luce + telecamera ──► OCR dell'etichetta        ~3,8 s
        │
        ▼
   ricerca nel database locale (24.686 voci)                 ~5 ms
        │
        ▼
   racconto: dai fatti del database, con la prosa del modello
        │
        ├──► testo a schermo, frase per frase
        └──► voce sintetizzata a bordo
```

Il riconoscimento è una **cascata**, e non risponde mai «non lo so»:

| se riconosce | dice |
|---|---|
| il vino esatto | «Questo è il Cannubi Barolo di Marchesi di Barolo, annata 2016.» |
| solo la tipologia | «Non riesco a leggere l'etichetta con certezza, ma questo è un Amarone della Valpolicella Classico.» |
| solo la denominazione | «L'etichetta non è nitida, ma riconosco la denominazione: Barolo, DOCG.» |
| solo il vitigno | «Del produttore non sono sicuro, ma il vitigno sì: Nebbiolo.» |
| niente | «Non riesco a leggere questa etichetta. Provi a girarla verso di me.» |

---

## Le misure, non le stime

Tutto ciò che segue è stato misurato sull'hardware reale, non stimato.

| | |
|---|---|
| Riconoscimento OCR | **97,8 %** delle etichette dà cantina o nome del vino |
| Coerenza del riconoscimento | **96,4 %** su 139 etichette italiane reali |
| Tempo OCR sulla board | **3,75 s** per etichetta (Cortex-A53, quattro thread) |
| Ricerca nel database | ~5 ms |
| Racconto pre-generato | istantaneo |
| Racconto generato dal vivo | 65-90 s — **per questo si pre-genera** |
| Modello linguistico | 8 token/s in lettura, 4,2 in scrittura |

---

## Cosa serve

### Hardware

| | |
|---|---|
| **Arduino UNO Q 4 GB** | il cervello: Linux + microcontrollore sulla stessa scheda |
| **Telecamera USB** InnoMaker U20CAM-1080P | UVC, MJPEG 1920×1080 |
| **Schermo 5"** LAFVIN MPI5001 | 800×480 IPS, HDMI + touch |
| **Hub USB-C** UGREEN Revodok 105 | HDMI + 3 USB-A + ingresso di alimentazione |
| **1× Modulino Pixels** | l'anello di luce sotto la bottiglia |
| **1× Modulino Distance** | rileva la bottiglia |
| **Amplificatore** PAM8403 + 2 altoparlanti 3 W | la voce |
| **Alimentatore** ≥ 30 W USB-C | oppure un power bank con PD |

### Come si collega

La UNO Q ha **una sola porta USB-C**, ed è OTG: fa da *host* oppure da
*device*, mai le due cose insieme. Quella porta è anche l'unica uscita video.
Perciò le configurazioni sono due, alternative:

```
   Configurazione A · banco          Configurazione B · prodotto

   PC ──USB-C──► UNO Q                                ┌── HDMI ──► schermo
                                     UNO Q ──USB-C──► hub ── USB-A ──► telecamera
   Per ADB, primo setup, flash.            (host)     ├── USB-A ──► touch
   La board è device.                                 └── PD ◄── alimentazione

                                     Il PC non c'è: si lavora via SSH.
```

Guida completa: [`docs/01-PRIMO-AVVIO.md`](docs/01-PRIMO-AVVIO.md).

---

## Installazione

Su una UNO Q già avviata e collegata in rete:

```bash
git clone https://github.com/destone28/Amelie2.0.git ~/amelie
cd ~/amelie
bash scripts/install.sh
sudo reboot
```

Lo script installa i pacchetti, crea l'ambiente Python, compila `llama.cpp`,
scarica i modelli, costruisce il database e abilita i servizi. Circa **40
minuti**, quasi tutti di compilazione.

> **Non serve rifare il flash della board.** La partizione `/home/arduino` ha
> 18 GiB liberi e tutto vive lì. Vedi il § 1.2 di `docs/01-PRIMO-AVVIO.md` per
> il perché.

### Il firmware del microcontrollore

Va caricato a parte, sullo STM32U585: istruzioni in
[`firmware/amelie_mcu/README.md`](firmware/amelie_mcu/README.md). Entrambi i
Modulino usano l'indirizzo di fabbrica, quindi non c'è niente da riprogrammare
prima di montare.

Per provare il giro completo con i pezzi ancora sul tavolo, prima di chiuderli
nella scocca: [`docs/06-ASSEMBLAGGIO-BANCO.md`](docs/06-ASSEMBLAGGIO-BANCO.md).

---

## Come si collauda

```bash
bash scripts/00_diagnostica.sh    # sistema, video, camera, audio, CPU, spazio
bash scripts/01_audio.sh          # la catena della voce, fino al jack
bash scripts/suona.sh             # fa suonare qualcosa, subito
```

Guida completa alle prove: [`docs/03-COLLAUDO.md`](docs/03-COLLAUDO.md).

---

## I servizi

| unità | cosa fa |
|---|---|
| `amelie.service` | l'applicazione |
| `amelie-kiosk.service` | il browser a schermo intero |
| `amelie-llm.service` | il modello linguistico, residente |
| `amelie-display.service` | modalità video e schermo sempre sveglio |
| `amelie-audio-guard.service` | garantisce la scheda audio all'avvio |
| `amelie-pregenera.service` | il lotto notturno dei racconti |

```bash
systemctl status 'amelie*'
journalctl -u amelie -f
```

---

## Struttura

```
src/amelie/
  app.py        l'orchestratore: sensore → camera → OCR → ricerca → racconto
  state.py      la macchina a stati dell'interazione (nessun I/O: tutta testabile)
  capture.py    raffica, scelta del fotogramma più nitido, ritaglio
  ocr.py        RapidOCR
  text.py       normalizzazione del testo letto, estrazione dell'annata
  matcher.py    dal testo al record, con la cascata
  narrator.py   dai fatti alla prosa, senza inventare
  llm.py        client del modello locale
  speech.py     voce, in streaming frase per frase
  bridge.py     dialogo con il microcontrollore
  lessico.py    vocabolari italiano/inglese
  ui/           l'interfaccia
data/
  build_db.py   costruisce il database dagli snapshot versionati
  vitigni.json  48 vitigni italiani, scritti a mano
firmware/       lo sketch del microcontrollore
scripts/        installazione, diagnostica, banchi di prova
docs/           primo avvio, riconoscimento, collaudo, attribuzioni
```

---

## Licenze

Il **codice** è distribuito sotto **GNU GPL v3** — vedi [`LICENSE`](LICENSE).

Documentazione, guide, schemi e file di stampa 3D sono sotto **CC BY 4.0** —
vedi [`LICENSE-DOCS.md`](LICENSE-DOCS.md).

> Amelie 2.0 — progetto realizzato da **Emilio Destratis**
> ([destratis.it](https://destratis.it)) in collaborazione con Arduino.

Dati e modelli di terze parti, ciascuno con la propria licenza e attribuzione:
[`docs/ATTRIBUZIONI.md`](docs/ATTRIBUZIONI.md).
