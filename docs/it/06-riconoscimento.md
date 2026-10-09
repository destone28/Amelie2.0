# Riconoscimento dell'etichetta

Come Amelie passa da una bottiglia appoggiata sul piatto a un insieme di fatti da raccontare: chi
decide che la bottiglia c'è, come si scatta, come si legge l'etichetta, come si cerca nell'archivio
e, soprattutto, quando il dispositivo **non** dice un nome. Serve a chi vuole capire il
comportamento, tararlo sulla propria installazione o estenderlo. Tutto gira sulla board, senza
rete; i percorsi sono relativi alla radice del repository. Che cosa si racconta a partire dai fatti
è descritto in [07-racconto.md](07-racconto.md).

## Le parole che servono

| termine | che cosa vuol dire qui |
|---|---|
| OCR | *optical character recognition*: il programma che trasforma l'immagine di un testo in caratteri |
| denominazione | il nome protetto di una zona di produzione e dei suoi vini, per esempio Barolo o Chianti Classico |
| DOP, IGP | le due categorie europee dei vini legati a un territorio: denominazione di origine protetta, indicazione geografica protetta |
| DOCG, DOC, IGT | le menzioni italiane: DOCG (denominazione di origine controllata e garantita) e DOC (controllata) si usano per le DOP, IGT (indicazione geografica tipica) per le IGP |
| tipologia | uno dei vini che una denominazione prevede, con nome, colore e categoria: «Barolo Riserva» è una tipologia della denominazione Barolo |
| disciplinare | il regolamento di produzione di una denominazione: uve imposte e ammesse, rese, e una descrizione ufficiale di colore, odore e sapore |
| documento unico | la sintesi ufficiale del disciplinare depositata nel registro dell'Unione europea; da lì vengono le descrizioni che il racconto cita |
| vitigno | la varietà d'uva: Nebbiolo, Sangiovese, Garganega… |
| archivio | il database SQLite `data/amelie.db`, costruito da fonti aperte (vedi «L'archivio») |
| sicurezza | un punteggio da 0 a 100: quanto il dispositivo può sostenere ciò che sta per affermare (vedi «La ricerca») |

## La catena in un colpo d'occhio

```
sensore di distanza ──► «c'è una bottiglia»                      bridge.Presenza
          │
camera in moto ──► sagoma contro il piatto vuoto ──► riquadro    capture.PresenzaOttica
          │
fotogramma nitido ──► ritaglio ──► OCR                          capture.Camera, ocr.Lettore
          │                          └─ riga sul bordo? ──► rilettura allargata
          ▼
righe di testo ──► correzione a mano? ── sì ──► si racconta quella   correzioni.Correzioni
          │ no
          ├── modo «carta» ──► Carta.cerca ──► voce della carta, oppure «non in carta»
          └── modi «archivio» e «generativa» ──► Matcher.cerca ──► cascata ──► Fatti ──► narratore
                                                                               └─ se dubbio: il_piu_generico
```

Il flusso segue la macchina a stati di `src/amelie/state.py`:
`ATTESA → ASSESTAMENTO → SCANSIONE → RICONOSCIMENTO → RACCONTO → CONCLUSO`. `ASSESTAMENTO` dura
0,15 s, il tempo perché la mano che ha posato la bottiglia esca dall'inquadratura; `SCANSIONE` è
scatto e OCR; `RICONOSCIMENTO` è la ricerca nell'archivio. Quando non si legge niente, o quello che
si legge non porta a niente, si passa da `RIPOSIZIONA`, che chiede di girare l'etichetta e riprova;
un errore tecnico porta in `GUASTO`, che torna da solo all'attesa. Il lavoro lo fanno due metodi di
`Amelie` in `src/amelie/app.py`: `_scatta_e_leggi` (camera e OCR) e `_riconosci` (correzioni, carta
o archivio).

| modulo | compito |
|---|---|
| `src/amelie/bridge.py` | `Presenza`: l'innesco dal sensore di distanza |
| `src/amelie/capture.py` | camera, posa, nitidezza, ritaglio, sagoma della bottiglia |
| `src/amelie/ocr.py` | lettura con RapidOCR, versi di ripiego, rilettura allargata |
| `src/amelie/text.py` | normalizzazione, parole utili, annata |
| `src/amelie/matcher.py` | ricerca nell'archivio, cascata, sicurezza, regole sui nomi |
| `src/amelie/carta.py` | riconoscimento su una carta dei vini in CSV |
| `src/amelie/correzioni.py` | bottiglie insegnate a mano: parole e punti d'immagine |

## Presenza: il sensore decide, la camera guarda

**Il sensore di distanza è l'unico innesco.** È un modulo Modulino con il VL53L4CD, un sensore a
tempo di volo che misura la distanza con un impulso infrarosso; sta sul connettore Qwiic del
microcontrollore della UNO Q, e Linux lo legge attraverso il router di Arduino, il servizio che
sulla board collega i programmi Linux al microcontrollore (`Ponte.distanza_mm`). `Amelie._chi_c_e`
legge la distanza a ogni battito, cioè ogni 0,05 s (`Configurazione.periodo_sensore_s`), e la passa
a `bridge.Presenza`, che applica un'isteresi asimmetrica: sotto `vicino_mm` (100 mm) per 3 letture
di fila (`letture_per_arrivare`) la bottiglia è arrivata; sopra `lontano_mm` (140 mm), o senza una
misura valida, per 5 letture di fila (`letture_per_andarsene`) è andata via; in mezzo non si cambia
idea. L'innesco costa quindi tre battiti, 0,15 s. Una scansione di troppo costa poco, un racconto
interrotto a metà si nota molto.

**La camera dice dove sta la bottiglia, non se c'è.** `Amelie._guarda_il_piatto` prende ogni 0,25 s
(`Configurazione.periodo_sbirciata_s`) una «sbirciata»: il fotogramma intero, raddrizzato, in grigio
e rimpicciolito a 96 × 170 pixel (`ImpostazioniCamera.sbirciata`). La passa a
`capture.PresenzaOttica`:

- in attesa, quando il sensore dice che il piatto è vuoto, quello che si vede **è** lo sfondo:
  `non_e_una_bottiglia` lo impara, e l'app lo conserva in `var/sfondo.npy` per ritrovarlo al
  riavvio (al massimo ogni 10 minuti, `RIPOSO_SFONDO_S`, e solo se almeno il 20 % dei pixel è
  cambiato, `SFONDO_DA_RISCRIVERE`);
- quando la bottiglia c'è, `PresenzaOttica.riquadro` ne ricava la **sagoma** contro lo sfondo: sono
  cambiati i pixel che differiscono dallo sfondo di più di 20 livelli di grigio; si tengono le
  colonne in cui è cambiata almeno la frazione `FRAZIONE_SAGOMA` (0,25) dei pixel, poi, dentro
  quelle colonne, le righe con la stessa proporzione. Il rettangolo che le contiene è il riquadro
  della bottiglia.

La sagoma si scarta, e si torna al ritaglio fisso, quando non è credibile: colonne meno della
frazione `LARGHEZZA_MINIMA` (0,12) della larghezza, righe meno di `ALTEZZA_MINIMA` (0,30)
dell'altezza, un riquadro non più alto che largo (misurato in frazioni del fotogramma), oppure
più di `SAGOMA_MASSIMA` (0,70) del fotogramma cambiato, segno di un cambio di scena o di luce.

## La camera

`capture.Camera` cerca la camera USB per nome (`ImpostazioniCamera.nome_camera`, `"U20CAM"`, cioè
la InnoMaker U20CAM-1080P) fra i collegamenti stabili che Linux crea per le videocamere in
`/dev/v4l/by-id` (`trova_camera`), perché l'ordine dei dispositivi `/dev/videoN` cambia da un avvio
all'altro; se quei collegamenti mancano interroga ogni `/dev/video*` con `v4l2-ctl --info`, e
`ImpostazioniCamera.device` impone un percorso preciso. Lavora in MJPEG (ogni fotogramma compresso
come un JPEG) a 1920 × 1080.

- **È montata di lato**: una bottiglia è alta e stretta, e un sensore 16:9 girato la inquadra per
  il lungo. Ogni fotogramma si raddrizza di `ImpostazioniCamera.rotazione` (90°, in senso orario)
  *a monte* di qualunque ritaglio o misura.
- **Posa e bilanciamento del bianco sono manuali** (`blocca_esposizione`, all'avvio: posa 900,
  bianco a 4600 K, guadagno a zero): l'automatico non è ripetibile.
- **Lo stream resta acceso** mentre si guarda il piatto (`Camera.sorveglia`: un thread, il
  «guardiano», legge i fotogrammi di continuo), perché aprire la camera costa molto più che leggere
  da uno stream attivo. Si spegne mentre parla la voce (`Camera.chiudi`), perché camera e audio
  condividono il bus USB, e va in pausa durante l'OCR (`Camera.in_pausa`) per lasciare i core alla
  lettura.

Lo scatto ha due strade.

- **Con lo stream in moto**, `Camera.al_volo` prende il primo fotogramma abbastanza nitido **e con
  la luce giusta** fra quelli arrivati **dopo** l'istante in cui la bottiglia è comparsa,
  altrimenti il più nitido visto entro un secondo: l'assestamento si guarda invece di aspettarlo.
  La nitidezza è la varianza del laplaciano sul ritaglio, una misura di contrasto locale che sale
  quando l'immagine è a fuoco; la soglia è `SOGLIA_NITIDEZZA` (40). La luce è giusta entro il
  doppio della tolleranza del guardiano, o quando la posa è già a un estremo e non può migliorare;
  all'arrivo della bottiglia il guardiano misura subito (`Camera.guarda_subito`), senza aspettare
  il mezzo secondo.
- **A stream fermo**, `_scatta_e_leggi` chiama `Camera.scatta`, che aspetta 0,15 s
  (`assestamento_luce_s`), butta i fotogrammi vecchi rimasti nel buffer USB
  (`fotogrammi_da_scartare`, 3), cerca la posa e tiene il più nitido di una raffica
  (`fotogrammi_raffica`, 3).

In tutti e due i casi la luce dell'anello resta quella di sempre: lo scatto non la cambia, così la
posa trovata a riposo vale anche per la raffica.

Lo `Scatto` porta con sé anche il fotogramma intero raddrizzato e la posizione del ritaglio
(`intero`, `posto`).

## Esposizione e luce

La luce che conta è la media del grigio **sul ritaglio raddrizzato**, cioè dove guarderà l'OCR
(`Camera._luce`). Il bersaglio è `luce_cercata` (90 su 255) con tolleranza `luce_tollerata` (8);
fuori banda si corregge la posa con `posa_verso`:

```
k         = come risponde la scena: luce ∝ posa^k, stimato dagli ultimi due punti
            (fra 0,3 e 1,6; senza due punti utili vale 1 / esponente_posa)
posa_nuova = posa × (luce_cercata / luce) ^ (0,8 / k)      limitata a [posa_minima, posa_massima]
```

La luce non cresce in proporzione alla posa, e non sempre allo stesso modo: dipende dalla scena.
Sul banco `luce ∝ posa^0,54`; con un'etichetta chiara vicino all'anello, sul dispositivo, il 20%
di posa in più ha dato il 30% di luce in più. Un esponente fisso, tarato sul primo caso, nel
secondo salterebbe oltre la banda buona a ogni passo: per questo la risposta si stima sulla scena, e
il passo fa l'80% della strada (`SMORZAMENTO_POSA`), il resto al passo dopo.

È la regolazione **in background**: il guardiano, mentre lo stream scorre in attesa e durante la
lettura, guarda la luce ogni mezzo secondo (`INTERVALLO_MISURA_S`, in secondi e non in fotogrammi:
con le pose lunghe di una sala buia i fotogrammi rallentano) e corregge di un passo
(`_ritocca_la_posa`). Così la posa segue la sala, e la bottiglia la trova già quasi giusta. Lo
scatto a stream fermo fa fino a `ritocchi_posa` (3) correzioni, ognuna verificata da
`_aspetta_la_posa` (due fotogrammi di fila con la stessa luce, diversa da quella di partenza). La
posa si misura in unità da 100 µs: `posa_minima` è 100 (10 ms: sotto, le lampade a 50 Hz
darebbero bande, sopra un'etichetta chiara sotto l'anello al massimo si brucia), `posa_massima`
4500. Il massimo sta sotto quello dichiarato dalla camera (5000) perché oltre una certa posa la
camera smette di dare fotogrammi; se lo stream resta muto con una posa lunga, `_a_vuoto` riparte da
`posa_sicura` (900).

L'anello di LED, bianco e giallo al massimo, resta acceso uguale in attesa e durante la lettura:
la posa che il guardiano trova a riposo è quella dello scatto. In apertura della lettura,
`ocr._contrasto_normalizzato`
applica un CLAHE (*contrast limited adaptive histogram equalization*: uno stiramento del contrasto
fatto zona per zona, con un limite che evita di amplificare il rumore) alla sola luminanza, nello
spazio di colore LAB: aiuta nei casi estremi senza toccare i colori.

> Ogni collaudo che riguarda la luce va fatto anche **a luce della sala spenta**: è la condizione
> di un ristorante a cena, e lì la posa di partenza da sola non basta.

## Il ritaglio

`Camera.posto` sceglie il rettangolo che va all'OCR. Se la sagoma è nota (`Camera.riquadro`) si
prende quella, allargata ai lati di `allarga_riquadro` (0,08 della sua larghezza): con una mano che
regge il collo la sagoma può essere spostata. Altrimenti si usa un ritaglio centrale fisso di
`ritaglio_largo` (0,70 della larghezza) per `ritaglio_alto` (0,95 dell'altezza).

Due frazioni e non una, perché i due compiti stanno su assi diversi: in larghezza si stringe per
lasciare fuori la parete, che il rilevatore legge come testo (un calendario produce decine di
righe, e ognuna costa tempo); in altezza si tiene quasi tutto, perché lì sta l'etichetta.
Stringere troppo non aiuta: il riconoscimento lavora su parole intere, e una parola senza la lettera
iniziale o finale spesso non si ritrova.

### La rilettura allargata

Con le bottiglie tenute in mano il titolo finisce spesso contro il bordo del ritaglio.
`Lettore.allarga`, chiamato da `Amelie._leggi_scatto`, cerca le righe con almeno 2 lettere
(`LETTERE_DI_UNA_RIGA`) che arrivano entro `BORDO_CHE_TAGLIA` (3 % della larghezza del ritaglio, e
almeno 4 pixel) dal bordo sinistro o destro, da un lato dove il ritaglio non coincide già con il
bordo del fotogramma; le righe di sole cifre non si inseguono. Se ce ne sono, rilegge il ritaglio
**esteso fino al bordo del fotogramma** dal lato dove toccano, alla stessa altezza e alla stessa
scala della lettura iniziale, e aggiunge le righe della lettura iniziale che la rilettura non
ritrova. L'immagine allargata diventa lo scatto di riferimento (è quella che conserva una
correzione), e il giornale annota `"allargata": true`.

## L'OCR

`ocr.Lettore` usa **RapidOCR**, una libreria libera che esegue le reti neurali **PP-OCR** (quelle
del progetto PaddleOCR) con ONNX Runtime, un motore per far girare reti neurali sulla CPU. Le reti
sono quelle della serie v6 nella taglia «tiny», **PP-OCRv6 tiny** (`ImpostazioniOCR.reti_piccole`),
e sono due: il **rilevatore**, che trova dove sta il testo e restituisce un quadrilatero per riga,
e il **riconoscitore**, che legge una riga alla volta. Ogni quadrilatero si rettifica prospetticamente
prima di leggerlo: così curvatura e scorcio si compensano riga per riga.

**L'immagine va all'OCR a colori, nativa.** Le reti sono addestrate su tre canali, e su
un'etichetta oro su rosso scuro il canale blu da solo non rileva niente. Il grigio serve solo per
misurare (nitidezza, luce, sagoma, confronti delle correzioni).

La lettura è **in due fasi** (`_trova_e_leggi`):

1. **si trova** il testo su una copia rimpicciolita con il lato corto a `lato_rilevatore` (480 px):
   il costo del rilevatore cresce con i pixel, e 480 è il valore misurato migliore, perché più in
   basso si perdono lettere e più in alto il rilevatore costa di più e torna a peggiorare;
2. **si legge** ogni riga ritagliata dall'immagine a piena risoluzione. Si tengono le
   `righe_massime` (10) più alte, perché la denominazione è scritta grande e i solfiti piccoli, e
   ogni riga si porta a `altezza_riga` (48 px) con un tetto di `larghezza_riga` (320 px).

Restano le righe con confidenza ≥ `confidenza_minima` (0,55) e lunghe almeno `lunghezza_minima`
(2) caratteri. I parametri di RapidOCR si danno **alla costruzione** del motore
(`Lettore._carica`): passati alla chiamata ricostruiscono il motore a ogni fotogramma, senza avvisi.

**Il verso.** Il classificatore di orientamento di PP-OCR è spento (`usa_classificatore = False`)
perché il fotogramma arriva raddrizzato. Se il montaggio non corrisponde a `rotazione`, l'OCR non
degrada: legge spazzatura. `Lettore.leggi_comunque` prova allora gli altri tre versi, ma solo
quando la lettura iniziale ha meno di 2 parole utili (`parole_che_sono_una_lettura`), meno di 8
righe (`righe_che_bastano`: di più è una parete) e almeno una lettera; si ferma appena un verso dà
3 parole utili (`parole_che_bastano`).

Qui una **parola utile** è una riga di almeno tre caratteri non fatta di sole cifre (`_parole_utili`
in `ocr.py`); non va confusa con le parole utili di `text.parole_utili`, descritte sotto. Una
lettura senza nessuna di queste righe (`Lettura.utile` falso) è un tentativo fallito: dopo
`TENTATIVI_MAX` (3) il dispositivo smette di riprovare e reimpara lo sfondo, perché quello che vede
non è un'etichetta.

## Dal testo letto alle parole confrontabili

In `src/amelie/text.py` il lavoro lo fanno tre funzioni.

- **`normalizza`** prepara il testo per il confronto: toglie accenti e maiuscole, scioglie i punti
  delle sigle (`_sciogli_punti`: «D.O.C.G.» → `docg`, «F.lli» → `flli`, «13.5» → `135`), separa le
  parole su tutto ciò che non è lettera o cifra e riporta a lettera le confusioni dell'OCR (`0→o`,
  `1→l`, `5→s`, `8→b`, `6→g`, `2→z`), lasciando intatte le parole di sole cifre.
- **`parole_utili`** tiene le parole normalizzate di almeno tre caratteri e toglie `PAROLE_VUOTE`,
  quelle che stanno su quasi ogni etichetta («vino», «doc», «cantina», «tenuta», «riserva»,
  «classico»…). Il riconoscitore ha un secondo elenco, `matcher.PAROLE_GENERICHE`: le parole che
  dicono **che tipo** di vino è («spumante», «brut», «rosso», «metodo») e non **quale**.
- **`estrai_annata`** cerca un anno fra 1900 (`ANNO_MINIMO`) e 2100, o un anno massimo dato da chi
  chiama, riparando le lettere travestite da cifre («2Ol7» → 2017) ma pretendendo, sul testo
  riparato, che l'anno non sia attaccato a lettere o cifre. Fra più anni vince il più recente: il
  più vecchio è di solito la fondazione della cantina.

`data/build_db.py` contiene una copia di `normalizza`, perché deve girare senza il pacchetto
installato; `tests/test_build_db.py` controlla che le due copie diano lo stesso risultato. Se cambi
la normalizzazione, cambiala in tutti e due i posti e rigenera le colonne `*_norm` e l'indice con
`python3 scripts/reindicizza.py`, che non tocca gli identificativi dei record.

## L'archivio

L'archivio è `data/amelie.db`, un database SQLite costruito da fonti aperte con
`python3 data/build_db.py`; sulla board lo lancia `scripts/install.sh`, che lo ricostruisce anche
quando le sorgenti o il codice cambiano. Il file non sta nel repository: si ricostruisce identico
dalle sorgenti versionate in `data/sources/`. `Matcher` lo apre **in sola lettura** e ricorda ciò
che ha già chiesto; se il file manca, solleva `DatabaseAssente`.

### Da dove vengono i dati

| fonte | file | che cosa dà | licenza |
|---|---|---|---|
| figshare, Candiago et al. (2024) | `data/sources/PDO_wine_data_IT_FR.csv` | 408 DOP italiane con le loro tipologie: colore, categoria UE, vitigni imposti e ammessi | CC BY 4.0 |
| X-Wines, de Azambuja et al. (2023) | `data/sources/xwines_italia.csv` | 19.358 vini commerciali italiani: cantina, regione, vitigni, abbinamenti, corpo, acidità | ODbL 1.0 (la più restrittiva fra quelle dichiarate) |
| registro UE eAmbrosia | `data/sources/eambrosia_it_wine.tsv` | le 532 indicazioni geografiche italiane del vino: le 124 che figshare non ha (119 IGP e 5 DOP) e la menzione DOCG, DOC o IGT di tutte | © Unione europea, CC BY 4.0 |
| documenti unici UE | `data/sources/documenti_unici.jsonl` | colore, odore e sapore ufficiali delle tipologie | © Unione europea, CC BY 4.0 |
| elenco delle DOCG | `data/sources/docg.txt` | quali DOP sono DOCG, che il registro UE non distingue dalle DOC | dati di fatto |
| il progetto | `data/vitigni.json`, `data/geografia.py` | le schede dei vitigni scritte a mano, con gli alias; la regione di ogni denominazione | CC BY 4.0 (schede), GPL-3.0-or-later (codice) |

Il database costruito si distribuisce sotto ODbL 1.0, per via di X-Wines; attribuzioni e citazioni
obbligatorie sono in [08-attribuzioni.md](08-attribuzioni.md), la provenienza di ogni file in
`data/sources/LEGGIMI.md`.

`build_db.py` procede in quest'ordine, e l'ordine fissa gli identificativi: con le stesse sorgenti
escono gli stessi numeri.

1. Denominazioni e tipologie DOP da figshare.
2. Vini commerciali da X-Wines. Ogni vino si aggancia alla denominazione del passo 1 il cui nome
   normalizzato, il più lungo possibile, sta dentro il nome del vino o della sua regione:
   «Chianti Classico» batte «Chianti».
3. Le schede di `data/vitigni.json`, applicate al nome di ogni vitigno e ai suoi alias, e i nomi
   italiani dei vitigni di X-Wines che mancano.
4. Le denominazioni del registro UE che figshare non ha, e la menzione di tutte.
5. La regione di ogni denominazione, dalla mappa scritta a mano in `data/geografia.py`; quella che
   la mappa non sa dire resta vuota.
6. Colore, odore e sapore di ogni tipologia, estratti dai documenti unici.
7. Le forme normalizzate e l'indice di ricerca (`scripts/reindicizza.py`).
8. I racconti pronti (`scripts/genera_corpus.py`, vedi [07-racconto.md](07-racconto.md));
   `--senza-racconti` salta questo passo.

Il risultato, misurato sul database costruito: 532 denominazioni (413 DOP, di cui 74 DOCG e 339
DOC, e 119 IGP, tutte IGT), 4.301 tipologie, 19.358 vini commerciali (13.829 agganciati a una
denominazione), 618 vitigni (223 con una scheda scritta a mano), 2.223 descrizioni ufficiali per 515
denominazioni.

### Le tabelle

| tabella | contenuto |
|---|---|
| `ricerca` | l'indice di ricerca a testo pieno: `testo` normalizzato, `ambito`, `ambito_id`, `peso` |
| `vino` | vini commerciali: nome, cantina, forme `*_norm`, regione, tipo, gradazione, corpo, acidità, `denominazione_id` |
| `denominazione` | DOP e IGP: nome, numero di fascicolo UE, tipo (DOP o IGP), menzione (DOCG, DOC o IGT), regione |
| `tipologia` | le tipologie di ogni denominazione, con colore e categoria UE (fermo, spumante, frizzante, passito, liquoroso…) |
| `tipologia_vitigno` | vitigni per tipologia con `ruolo`: `principale` (imposto dal disciplinare) o `ammesso` (tollerato) |
| `tipologia_ue` | le descrizioni ufficiali dei documenti unici (colore, odore, sapore), con `menzione` e `nome_incerto` (vero quando il nome della tipologia è ricostruito e non va preso per buono) |
| `vitigno` | colore della bacca e schede scritte a mano, in italiano e inglese |
| `vino_vitigno`, `vino_abbinamento` | vitigni e abbinamenti dei vini commerciali |
| `racconto` | i racconti pronti per tipologie, denominazioni e vitigni, nelle due lingue (li usa solo il modo «generativa») |
| `fonte` | le fonti, con licenza e attribuzione |

`ricerca` è una tabella FTS5, l'estensione di SQLite per la ricerca a testo pieno: ha una riga per
record (24.809 in tutto) e quattro **ambiti**: `vino` (cantina più nome), `tipologia`,
`denominazione`, `vitigno`. Il `peso` misura quanto il record è specifico: 100 per un vino, 70 per
una denominazione, 50 per una tipologia, 30 per un vitigno. La denominazione pesa più delle sue
tipologie perché «Barolo» letto su un'etichetta è la denominazione, non la prima delle sue
tipologie. Lo assegna chi costruisce l'indice (`scripts/reindicizza.py`, `PESO`). Le righe di un
ambito che il codice non conosce non entrano in gara (`Matcher.AMBITI`): il database può essere più
ricco del codice.

## La ricerca

`Matcher.cerca(righe)` è il punto d'ingresso. Ricava l'annata (`estrai_annata`) e le parole utili
dell'intera lettura (`text.parole_utili`); senza parole utili, o senza candidati, restituisce
`Fatti()` vuoti, al livello `nulla`. I candidati si trovano in tre passi (`_candidati`):

1. **FTS5 con BM25** trova fino a `CANDIDATI` (200) record che contengono almeno una delle parole
   utili. BM25 è la funzione di ordinamento di FTS5: pesa le parole per rarità, e una parola
   presente in centinaia di nomi conta poco.
2. **RapidFuzz**, una libreria di confronto approssimato fra stringhe che dà punteggi da 0 a 100,
   assegna a ciascuno una **somiglianza** con `token_set_ratio`, un confronto fra insiemi di parole
   indifferente all'ordine e alle parole in più. I candidati si ordinano per
   `somiglianza + peso/100`; un record identico all'intera lettura normalizzata vale 100 e prende
   15 punti in più (`Candidato.punteggio`).
3. **La sicurezza verificata** (`_sicurezza_verificata`) sostituisce la somiglianza di *tutti* i
   candidati non identici, e si riordina: la verifica abbassa i punteggi, e un candidato rimasto
   fuori terrebbe quello gonfiato.

La sicurezza misura l'**affermazione**, non la stringa. Il mattone è la copertura (`_copertura`):
ogni parola del record cerca la parola letta più simile con `fuzz.ratio` (il confronto carattere per
carattere di RapidFuzz); sotto `RISCONTRO_PAROLA` (70) vale zero, ogni parola letta ne conferma una
sola, e il risultato è la media sulle parole del record.

- **Un vino commerciale** chiede due conferme, il nome e la cantina; senza cantina vale l'80 %
  della copertura del nome. La cantina si prova solo con le parole **sue**
  (`_prova_del_produttore`: le parole utili della cantina meno quelle della sua denominazione). Se
  queste non si leggono, cioè la loro copertura sulle parole utili dell'etichetta resta sotto 70,
  il candidato ha `produttore_letto = False` e vale anche lui l'80 % della copertura del nome. Se
  si leggono vale `min(0,6·cantina + 0,4·nome, 1,15·cantina, 1,6·nome)`, moltiplicato per
  `min(1, 0,55 + 0,15·n)`, dove `n` è il numero di parole distinte di nome e cantina.
- **Gli altri ambiti** valgono `token_set_ratio` moltiplicato per lo stesso fattore, con `n` le
  parole del record: un record di una parola sola arriva al massimo a 70, uno di tre parole a 100.

Infine un **tetto** dipende da quante parole utili ha dato la lettura (`TETTO_PER_PAROLE`): 60 con
una, 78 con due, 87 con tre, nessuno da quattro in su. Una parola sola può combaciare al 100 % per
aritmetica degli insiemi: **per essere certi servono almeno quattro parole utili**.

L'ordine completo di `Matcher.cerca`, dopo i candidati:

1. il tetto per numero di parole, applicato a tutti i candidati;
2. se l'etichetta dichiara un colore e il primo candidato lo contraddice, `_del_colore_giusto`
   scende al primo candidato di quel colore;
3. `_componi` costruisce i `Fatti` del candidato scelto, con la sua sicurezza;
4. se il produttore non si è letto, `_senza_produttore` scende al vino senza cantina;
5. `_non_oltre_cio_che_si_e_letto` scende finché il nome da dire è tutto sull'etichetta, fino al
   livello generico (`_solo_l_etichetta`);
6. `_del_colore_dichiarato` corregge il gradino fra le tipologie della stessa denominazione;
7. `_il_produttore_scritto` rimette la cantina, se si è letta;
8. `_c_e_un_altro_produttore` abbassa la sicurezza se due cantine sono a pari evidenza;
9. si aggiungono l'annata, la catena di ripiego e fino a tre alternative.

Le regole dei passi 2 e 4-8 sono in «Non si nomina ciò che non si è letto».

## La cascata e le soglie

La risposta non è mai «non lo so»: si scende finché si trova qualcosa di vero da dire. Gli esempi
sono le frasi d'apertura del racconto nella loro forma di riferimento (il narratore sceglie fra
forme equivalenti, vedi [07-racconto.md](07-racconto.md)); per `nulla`, la scritta a schermo.

| livello (`Livello`) | che cosa si dice | esempio |
|---|---|---|
| `vino` | il vino di un produttore, con nome e cantina | `Questo è il «Cannubi Barolo» di Marchesi di Barolo annata 2016.` |
| `tipologia` | una tipologia di una denominazione | `Questo è un Barolo Riserva.` |
| `denominazione` | la denominazione | `Questo è un Barolo, a denominazione di origine protetta.` |
| `vitigno` | il vitigno | `Questo è un vino di Nebbiolo.` |
| `generico` | solo ciò che è scritto sull'etichetta | `Questo è uno spumante rosato metodo classico, brut.` |
| `nulla` | niente: lo schermo chiede di girare l'etichetta e si riprova | `Provi a girare l'etichetta verso di me?` |

`catena_di_ripiego` dà i gradini di ogni record: un vino scende alla sua tipologia
(`_tipologia_del_vino`, che rispetta il colore scritto nel nome e preferisce le tipologie con le
bolle quando il nome le dichiara), poi alla denominazione, poi al primo dei suoi vitigni, se ha una
scheda; una tipologia scende alla denominazione e al vitigno; una denominazione al vitigno.

Le due soglie stanno in `src/amelie/matcher.py`.

| sicurezza | in `Fatti` | cosa fa `Amelie._riconosci` |
|---|---|---|
| ≥ `SOGLIA_CERTA` (88) | `certo` | racconta, con apertura affermativa |
| da `SOGLIA_DUBBIA` (75) a 88 | `dubbio` | passa da `il_piu_generico`, poi racconta |
| sotto 75, livello non `nulla` | — | racconta; per vino, tipologia e vitigno l'apertura lo dice una supposizione |
| livello `nulla` | `vuoto` | chiede di girare l'etichetta e riprova; dopo `TENTATIVI_MAX` (3) tentativi smette |

**Il dubbio non si chiede all'ospite.** `Matcher.il_piu_generico` prende, fra il primo e le
alternative, quello di livello più generale secondo `GENERALITA` (vino, tipologia, denominazione,
vitigno, generico); a parità resta il primo. Se invece il primo è un vino con la cantina e fra le
alternative c'è un vino di un'altra cantina, il dubbio è la cantina, e si scende allo stesso vino
senza produttore. Le alternative (al massimo tre, diverse fra loro, del colore giusto e con le
parole identificanti tutte lette) restano nei `Fatti` e nel giornale.

Dopo `TENTATIVI_MAX` tentativi senza esito il dispositivo smette di riprovare: se «Aggiungi
correzioni» è acceso e si è letta almeno una parola identificante, lo schermo dice «Non ho
riconosciuto questa bottiglia.» e offre «Mi aiuti a riconoscerla»; altrimenti torna all'invito.
Riprova quando la bottiglia viene tolta e rimessa.

## Non si nomina ciò che non si è letto

È la regola che regge tutto il riconoscimento: un nome detto a voce a un tavolo è
un'affermazione su un'azienda o un luogo veri, e sbagliarlo è peggio che dire una cosa vaga.

- **Il produttore.** Un vino si attribuisce a un produttore solo se le sue parole proprie sono
  sull'etichetta; quelle della denominazione stanno sulla bottiglia di chiunque. Senza prova
  `_senza_produttore` scende al gradino successivo della catena: un'etichetta che dice solo
  «Primitivo di Manduria» si racconta come Primitivo di Manduria, non come il vino di uno dei tanti
  produttori.
- **Tutti i nomi.** `_non_oltre_cio_che_si_e_letto` scende lungo la catena finché le parole
  **identificanti** del record (parole utili meno `PAROLE_GENERICHE`) sono tutte sull'etichetta,
  ciascuna con un riscontro ≥ 70 su una parola letta diversa (`_tutto_letto`). Una soglia di
  somiglianza non può fare questo lavoro: le somiglianze dei riconoscimenti giusti e delle
  invenzioni si sovrappongono, le parole lette no.
- **Il livello generico.** Se nessun gradino regge, `_solo_l_etichetta` dice il colore dichiarato,
  la categoria dedotta dalle parole lette (`CATEGORIA_DETTA`: «spumante», «metodo», «frizzante»,
  «passito»…) e i qualificatori nell'ordine in cui si pronunciano (`ORDINE_QUALIFICATORI`). La
  sicurezza resta sotto la certezza e sotto il tetto per parole. A questo livello il modello
  linguistico non scrive mai.
- **Il colore dichiarato.** Se l'etichetta dichiara un solo colore (`COLORE_DETTO`: «rosato»,
  «rosé», «rosso», «bianco» e le loro forme straniere), nessun record di colore diverso può essere
  quella bottiglia: `_del_colore_giusto` scende fra i primi `CANDIDATI_PER_COLORE` (16) fino a uno
  di quel colore, salvo quando la denominazione del primo ha una tipologia sorella di quel colore
  con il nome tutto letto; `_del_colore_dichiarato` corregge poi il gradino fra le tipologie
  sorelle della stessa denominazione. «Nero» e «rosa» non contano come colori (sono parti di nomi
  di vitigno); due colori diversi letti insieme valgono come nessuno.
- **Il produttore senza il vino.** Quando nei fatti non c'è una cantina, di solito perché la
  cascata è scesa sotto il vino, `_il_produttore_scritto` la rimette solo se le sue parole proprie
  (almeno quattro lettere, non generiche, non nel nome di un vino candidato, non nomi di luogo) si
  leggono con copertura ≥ `PRODUTTORE_SCRITTO` (90), appartengono solo a lei nell'archivio, e un
  solo produttore supera la prova.
- **Due produttori a pari evidenza.** Se il primo candidato è il vino di una cantina e fra i primi
  `RIVALI` (6) c'è il vino di un'altra cantina entro `MARGINE_PRODUTTORE` (3 punti), la sicurezza
  scende appena sotto la certezza (87,5): il riconoscimento diventa dubbio e passa da
  `il_piu_generico`.
- **Le cooperative omonime.** Un produttore che si chiama come la propria denominazione non ha
  parole sue: non si può provare, e le sue bottiglie si raccontano senza produttore, al livello
  della tipologia o della denominazione.
- **Le citazioni del disciplinare.** `_disciplinare` assegna le descrizioni di `tipologia_ue`
  restringendo, non somigliando: stesso colore, stesso tipo di prodotto (`PRODOTTO_DIVERSO`:
  passito, liquoroso, recioto, vendemmia tardiva…), poi nome identico se affidabile, poi vitigni e
  qualificatori. Se quel che resta dice la stessa cosa la si riporta, altrimenti si tace.

## Il modo carta

Con `--carta vini.csv` e il modo «Carta dei vini» scelto dalle impostazioni, il dispositivo
riconosce i titoli di un file scritto dal locale (`src/amelie/carta.py`); il servizio di sistema
carica `/home/arduino/amelie/vini.csv`. Colonne `titolo` e `descrizione`, più `titolo_xx` e
`descrizione_xx` per ogni altra lingua (`xx` è il codice di due lettere):

```csv
titolo,descrizione,titolo_en,descrizione_en
Barolo DOCG,"Il testo che il dispositivo legge.",Barolo DOCG,"The text it reads."
```

`Carta.cerca` non ha cascata: la carta ha la voce o non ce l'ha. Un titolo è ammesso se:

- la somiglianza (`_somiglianza`) è almeno `SOMIGLIANZA_MINIMA` (55). Per le letture a pezzi c'è una
  misura parola per parola, valida solo se il titolo ha almeno due parole, le ritrova tutte con
  riscontro ≥ `RISCONTRO_PEZZO` (75) e almeno una è letta esatta, non generica e lunga almeno
  `ESATTA_CHE_PROVA` (4) lettere;
- ogni sua parola di almeno tre caratteri è sull'etichetta (riscontro ≥ 70), tranne le `TACITE`
  (DOC, DOCG, IGT, le altre sigle di denominazione e «annata») e quelle **implicate**
  (`Carta._implicate`: presenti in tutte le voci che contengono le parole identificanti lette).
  «Riserva» o «Extra Brut» nel titolo vanno lette;
- le parole implicate non lette non sono più di quelle identificanti lette.

Fra i titoli ammessi vince quello con più parole lette, poi con meno parole non lette, poi la
somiglianza. Se nessuno passa, la lettura conta come un tentativo fallito, si chiede di girare
l'etichetta e il giornale annota le voci più vicine (`Carta.vicine`). Quando un titolo passa si
interroga anche l'archivio, per raccontare nelle lingue che la carta non ha.

## Le correzioni a mano

Con «Aggiungi correzioni» acceso, chi sta in sala può insegnare una bottiglia: un titolo e una
descrizione, che diventa facoltativa se la bottiglia si collega a un record dell'archivio o a una
voce della carta. `Correzioni` conserva in `var/correzioni/<id>/` il file
`correzione.json` e una foto per **vista**, con le righe lette e la zona dell'etichetta. Le
correzioni si cercano **per prime**, in ogni modo di racconto (`Amelie._cerca_correzione`), con due
segnali:

- **le parole**: `parole_identificanti` (almeno quattro lettere, solo lettere, non generiche)
  ricordate e rilette, con `fuzz.ratio` ≥ 80 e una parola letta per ciascuna;
- **l'immagine**: punti ORB ritrovati in posizione coerente. ORB è un algoritmo che trova nella
  foto punti caratteristici e li descrive in modo da poterli ritrovare in un'altra foto; un
  riscontro vale solo se è nettamente migliore del secondo (il «test del rapporto»), e restano i
  punti coerenti con un'unica trasformazione prospettica fra le due foto (un'omografia stimata con
  RANSAC, che scarta i riscontri sparsi). I punti si cercano **solo nella zona dell'etichetta**
  (`zona_etichetta`), perché lo sfondo della sala è uguale in tutte le foto e farebbe somigliare
  bottiglie diverse.

Le soglie, in `Regola`, sono tarate perché due bottiglie diverse non si scambino mai, a costo di
qualche riconoscimento mancato: quota di parole `parole` (0,6) con almeno `parole_minime` (2) e
`immagine_con_parole` (16) punti, oppure `immagine_da_sola` (30) punti; si confrontano al massimo
`viste_confrontate` (6) viste, fra quelle con almeno una parola in comune. Correggere di nuovo la
stessa bottiglia aggiunge una vista, e la fa riconoscere meglio con luci e angoli diversi.

## La bottiglia cambiata durante il racconto

Se il sensore vede arrivare una bottiglia mentre si racconta, `Amelie._anticipa` la legge in un
thread a parte **senza fermare la voce** (`_decidi_in_anticipo`):

1. aspetta l'assestamento (0,15 s), scatta (fino a 1,5 s per un fotogramma nitido) e confronta la
   zona dell'etichetta della foto precedente con la foto nuova (`Correzioni.punti_in_comune`): con
   almeno `STESSA_A_OCCHIO` (25) punti è la stessa bottiglia;
2. altrimenti legge, e `_e_un_altra` decide: le stesse parole identificanti (con la `Regola` delle
   correzioni) vogliono dire la stessa bottiglia; altrimenti si confronta che cosa si
   racconterebbe (correzione, voce della carta, record dell'archivio) con quello che si sta
   raccontando, e se è diverso è un'altra; senza parole identificanti non decide, e la bottiglia
   si rilegge a racconto finito;
3. se è un'altra, la voce si ferma (`Evento.CAMBIO_BOTTIGLIA`) e `_scatta_e_leggi` riusa la
   lettura già fatta, purché non sia più vecchia di `ANTICIPO_VALIDO_S` (30 s).

La foto sa dire «è la stessa» ma non «è un'altra»: una bottiglia rimessa girata ritrova pochi
punti, e serve il testo. Una bottiglia tolta durante il racconto non lo interrompe.

## Come si misura

**Il banco OCR.** `scripts/bench_ocr.py` legge le 139 etichette italiane fotografate del dataset
X-Wines, con cantina, nome e annate note in `tests/etichette/manifesto.csv`. Le foto non sono nel
repository (sono opere grafiche di terzi): scarica X-Wines in
`data/sources/X-Wines_Official_Repository/` e rigenera il set.

```bash
python3 data/estrai_xwines.py --estrai-immagini
python3 scripts/bench_ocr.py --lato 480 --salva /tmp/ocr.json     # -n N per le prime N
python3 scripts/bench_matcher.py /tmp/ocr.json
```

Il lato predefinito dello script è quello del dispositivo (`lato_rilevatore = 480`); con `--lato`
se ne prova un altro, con `--thread` si cambia il numero di thread. Il banco stampa quante volte
cantina e nome del vino si ritrovano nel testo letto (`partial_ratio` ≥ 80, cioè la miglior
corrispondenza fra una parte del testo e il nome atteso), quante volte almeno uno dei due, le annate
plausibili, le etichette mute, le righe medie, il tempo per etichetta e le cinque peggiori. Sul PC
misura la qualità; sulla board, con l'ambiente Python del servizio (`venv/bin/python`), anche il
tempo. Usa `Lettore.leggi` su foto **piane e frontali**, senza versi di ripiego né rilettura
allargata: è un limite superiore.

**Il banco del riconoscimento.** `scripts/bench_matcher.py` passa quel testo a `Matcher.cerca`,
applica `il_piu_generico` ai riconoscimenti dubbi come fa il dispositivo, e confronta ciò che si
direbbe con la scheda nota: **coerente** (ciò che si dice torna, anche se si è scesi di livello),
**incoerente**, e **di cui dichiarate certe**, cioè incoerenti sopra `SOGLIA_CERTA`. Quest'ultima
riga **deve restare a zero**: quelle si raccontano come fatti. Seguono la distribuzione per livello
(da `vino` a `nulla`, più le etichette senza testo), la distribuzione per fascia di sicurezza,
contata prima di `il_piu_generico`, e alcuni esempi di riconoscimenti incoerenti.

**Sul dispositivo.**

- **Il giornale** (`src/amelie/giornale.py`) annota ogni scansione in `var/scansioni/giornale.jsonl`
  con il fotogramma accanto: righe lette, tempi di scatto e OCR, nitidezza, posa, `allargata`,
  `anticipata`, livello, sicurezza, nomi, colore, candidati, `scelto_il_piu_generico`,
  `perche_correzione`, nel modo carta le `vicine`, e il racconto detto con la sua origine
  (`racconto_da`). Si legge anche da `GET /giornale?quante=N` e `GET /giornale/<nome>`.
- **Il mirino** mostra dal vivo fotogramma, ritaglio, nitidezza, lettura e riconoscimento; si
  accende con l'interruttore «Debug camera» nelle impostazioni, che si aprono tenendo premuto per
  tre secondi l'angolo in basso a destra dello schermo. `scripts/mirino.py`, a servizio fermo, fa
  lo stesso in un browser (porta 8090) e accetta `--esposizione`, `--ritaglio`, `--ritaglio-alto`,
  `--luce`, `--ocr`.
- **`POST /prova/bottiglia`** simula una bottiglia sul piatto (`/prova/via` la toglie,
  `/prova/camera` torna al sensore), per provare lettura e riconoscimento senza il sensore.
- **I test** (`tests/test_matcher.py`, `test_ocr.py`, `test_carta.py`, `test_cambio_bottiglia.py`…)
  si saltano invece di fallire quando manca ciò che serve: il database o `rapidfuzz` per il
  riconoscimento, OpenCV e NumPy per il cambio di bottiglia.

I numeri aggregati non bastano: ogni modifica a una soglia va rigiocata su **tutte** le etichette
di prova e sulle letture vere del giornale, e ogni differenza va riletta a mano. Una tolleranza che
sistema un caso ne rompe spesso altri, e si vede solo così.

## Come si regola

Cambia un parametro alla volta, rimisura con i banchi e con il giornale, e controlla che le
«dichiarate certe» restino a zero.

| dove | parametro (predefinito) | quando toccarlo |
|---|---|---|
| `ImpostazioniCamera` | `nome_camera` (`"U20CAM"`), `device` (nessuno) | camera di un altro modello |
| `ImpostazioniCamera` | `rotazione` (90) | la camera è montata in un altro verso |
| `ImpostazioniCamera` | `esposizione` (900), `posa_massima` (4500) | sala molto buia o camera diversa |
| `ImpostazioniCamera` | `luce_cercata` (90), `luce_tollerata` (8) | etichette bruciate o troppo scure |
| `ImpostazioniCamera` | `ritaglio_largo` (0,70), `ritaglio_alto` (0,95), `allarga_riquadro` (0,08) | entra la parete, o si tagliano le parole |
| `capture.py` | `SOGLIA_NITIDEZZA` (40), `FRAZIONE_SAGOMA` (0,25), `SAGOMA_MASSIMA` (0,70) | fotogrammi mossi, sagome sbagliate |
| `bridge.Presenza` | `vicino_mm` (100), `lontano_mm` (140) | geometria diversa fra piatto e sensore |
| `ImpostazioniOCR` | `lato_rilevatore` (480), `righe_massime` (10) | compromesso fra lettere lette e tempo |
| `ImpostazioniOCR` | `confidenza_minima` (0,55), `usa_classificatore` (falso) | rumore; fotogramma non raddrizzato |
| `ocr.py` | `BORDO_CHE_TAGLIA` (0,03) | quando scatta la rilettura allargata |
| `matcher.py` | `SOGLIA_CERTA` (88), `SOGLIA_DUBBIA` (75), `TETTO_PER_PAROLE` (60, 78, 87) | quanto si afferma |
| `matcher.py` | `RISCONTRO_PAROLA` (70), `PRODUTTORE_SCRITTO` (90), `MARGINE_PRODUTTORE` (3) | prove sui nomi |
| `matcher.py`, `text.py` | `PAROLE_GENERICHE`, `COLORE_DETTO`, `PRODOTTO_DIVERSO`, `PAROLE_VUOTE` | vocabolario delle regole |
| `carta.py` | `SOMIGLIANZA_MINIMA` (55), `RISCONTRO_PEZZO` (75), `TACITE` | severità della carta |
| `correzioni.py` | `Regola` | severità delle correzioni |
| `app.py` | `TENTATIVI_MAX` (3), `STESSA_A_OCCHIO` (25) | tentativi; «è la stessa bottiglia» |

Per estendere il riconoscimento a un nuovo tipo di record servono le righe nell'indice `ricerca`,
l'ambito in `Matcher.AMBITI`, un `Livello` con il suo posto in `LIVELLO_DELL_AMBITO` e
`GENERALITA`, e un costruttore in `Matcher._componi`: finché il codice non lo conosce, le sue righe
restano fuori gara.

## Limiti noti

- **Vetro chiaro.** Il sensore di distanza lavora all'infrarosso, che attraversa il fondo di una
  bottiglia chiara e non torna: la bottiglia non viene vista e la scansione non parte. Il rimedio
  passa dalla soglia del segnale del VL53L4CD, nel firmware del microcontrollore.
- **Etichette curve.** Sui fianchi del cilindro le lettere si stringono e si perdono: la
  rettifica per riga compensa lo scorcio, non ciò che il vetro nasconde, e la rilettura allargata
  recupera solo ciò che il ritaglio ha tagliato.
- **Riflessi e buio.** Un riflesso speculare brucia le lettere che copre (la posa guarda la luce
  media, il CLAHE non ricostruisce un punto saturo); al buio servono pose lunghe, e una bottiglia
  tenuta in mano si muove, per cui il fotogramma più nitido può non esserlo abbastanza.
- **Caratteri decorativi e trame fitte.** Corsivi ornati e fondi a motivi confondono il
  rilevatore anche quando l'etichetta si legge a occhio; se il nome del vino è decorativo si scende
  alla tipologia o alla denominazione.
- **Annata.** Spesso sta sul collarino, fuori inquadratura o troppo piccola: allora non si dice.
- **Scritte dietro il piatto.** Una parete con testo aggiunge righe e tempo; ritaglio stretto e
  sfondo imparato lo limitano.
- **Copertura dell'archivio.** Si riconosce ciò che è nell'archivio; il resto arriva alla
  denominazione, al livello generico, o si insegna con una correzione. Le cooperative che si
  chiamano come la propria denominazione si raccontano sempre senza produttore.
- **Verso di montaggio.** Se `rotazione` non corrisponde al montaggio si legge lo stesso, provando
  gli altri versi, ma con più letture per scansione.
