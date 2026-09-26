# Riconoscimento dell'etichetta

Come Amelie passa da una bottiglia appoggiata sul piatto a un insieme di fatti da raccontare: chi
decide che la bottiglia c'è, come si scatta, come si legge l'etichetta, come si cerca nel database
e, soprattutto, quando il dispositivo **non** dice un nome. Serve a chi vuole capire il
comportamento, tararlo sulla propria installazione o estenderlo. Tutto gira sulla board, senza
rete; i percorsi sono relativi alla radice del repository.

## La catena in un colpo d'occhio

```
sensore di distanza ──► «c'è una bottiglia»                    bridge.Presenza
          │
camera in moto ──► sagoma contro il piatto vuoto ──► riquadro   capture.PresenzaOttica
          │
fotogramma nitido ──► ritaglio ──► OCR                         capture.Camera, ocr.Lettore
          │                          └─ riga sul bordo? ──► rilettura allargata
          ▼
righe di testo ──► correzione a mano? ── sì ──► si racconta quella   correzioni.Correzioni
          │ no
          ├── modo carta ──► Carta.cerca ──► voce, oppure «non in carta»
          └── archivio ──► Matcher.cerca ──► cascata ──► Fatti ──► narratore
                                                          └─ se dubbio: il_piu_generico
```

Il flusso segue la macchina a stati di `src/amelie/state.py`:
`ATTESA → ASSESTAMENTO → SCANSIONE → RICONOSCIMENTO → RACCONTO`, con `RIPOSIZIONA` quando non si
legge niente. Il lavoro lo fanno due metodi di `Amelie` in `src/amelie/app.py`: `_scatta_e_leggi`
(camera e OCR) e `_riconosci` (correzioni, carta o archivio).

| modulo | compito |
|---|---|
| `src/amelie/bridge.py` | `Presenza`: l'innesco dal sensore di distanza |
| `src/amelie/capture.py` | camera, posa, nitidezza, ritaglio, sagoma della bottiglia |
| `src/amelie/ocr.py` | lettura con RapidOCR, versi di ripiego, rilettura allargata |
| `src/amelie/text.py` | normalizzazione, parole utili, annata |
| `src/amelie/matcher.py` | ricerca nel database, cascata, sicurezza, regole sui nomi |
| `src/amelie/carta.py` | riconoscimento su una carta dei vini in CSV |
| `src/amelie/correzioni.py` | bottiglie insegnate a mano: parole e punti d'immagine |

## Presenza: il sensore decide, la camera guarda

**Il sensore di distanza è l'unico innesco.** `Amelie._chi_c_e` legge la distanza a ogni battito
e la passa a `bridge.Presenza`, che applica un'isteresi asimmetrica: sotto `vicino_mm` (100 mm)
per 3 letture di fila la bottiglia è arrivata; sopra `lontano_mm` (140 mm), o senza misura, per 5
letture di fila è andata via; in mezzo non si cambia idea. Una scansione di troppo costa poco, un
racconto interrotto a metà si nota molto.

**La camera dice dove sta la bottiglia, non se c'è.** `Amelie._guarda_il_piatto` prende a
intervalli una «sbirciata» (il fotogramma intero, in grigio e rimpicciolito) e la passa a
`capture.PresenzaOttica`:

- quando il sensore dice che il piatto è vuoto, quello che si vede **è** lo sfondo:
  `non_e_una_bottiglia` lo impara, e l'app lo conserva in `var/sfondo.npy`;
- quando la bottiglia c'è, `PresenzaOttica.riquadro` ne ricava la **sagoma** contro lo sfondo:
  le colonne cambiate per almeno `FRAZIONE_SAGOMA` (0,25), poi le righe cambiate dentro quelle.

La sagoma si scarta, e si torna al ritaglio fisso, quando non è credibile: più stretta di
`LARGHEZZA_MINIMA` (0,12 del fotogramma), più bassa di `ALTEZZA_MINIMA` (0,30), più larga che
alta, o con oltre `SAGOMA_MASSIMA` (0,70) del fotogramma cambiato, segno di un cambio di scena o
di luce.

## La camera

`capture.Camera` trova la camera USB per nome fra i collegamenti stabili di `/dev/v4l/by-id`
(`trova_camera`), perché l'ordine di `/dev/videoN` cambia da un avvio all'altro, e lavora in MJPEG
a 1920×1080.

- **È montata di lato**: una bottiglia è alta e stretta, e un sensore 16:9 girato la inquadra per
  il lungo. Ogni fotogramma si raddrizza con `ImpostazioniCamera.rotazione` (90°) *a monte* di
  qualunque ritaglio o misura.
- **Posa e bilanciamento del bianco sono manuali** (`blocca_esposizione`), con guadagno a zero:
  l'automatico non è ripetibile.
- **Lo stream resta acceso** mentre si guarda il piatto (`Camera.sorveglia`, il «guardiano»),
  perché aprire la camera costa molto più che leggere da uno stream attivo. Si spegne mentre parla
  la voce (`Camera.chiudi`), perché camera e audio condividono il bus USB, e va in pausa durante
  l'OCR (`Camera.in_pausa`) per lasciare i core alla lettura.

Lo scatto ha due strade. `Camera.al_volo`, con lo stream in moto, prende il primo fotogramma
arrivato **dopo** l'istante in cui la bottiglia è comparsa e abbastanza nitido (varianza del
laplaciano sul ritaglio ≥ `SOGLIA_NITIDEZZA`, 40), altrimenti il più nitido visto entro l'attesa
massima: l'assestamento si guarda invece di aspettarlo. A stream fermo, `_scatta_e_leggi` porta
l'anello a bianco e chiama `Camera.scatta`, che butta i fotogrammi vecchi del buffer USB
(`fotogrammi_da_scartare`), cerca la posa e tiene il più nitido di una raffica
(`fotogrammi_raffica`). Lo `Scatto` porta con sé anche il
fotogramma intero raddrizzato e la posizione del ritaglio (`intero`, `posto`).

## Esposizione e luce

La luce che conta è la media del grigio **sul ritaglio raddrizzato**, cioè dove guarderà l'OCR
(`Camera._luce`). Il bersaglio è `luce_cercata` (90 su 255) con tolleranza `luce_tollerata` (8);
fuori banda si corregge la posa:

```
posa_nuova = posa × (luce_cercata / luce) ^ esponente_posa      limitata a [posa_minima, posa_massima]
```

L'esponente (1,5) tiene conto che la luce non cresce in proporzione alla posa: il sensore satura
sui punti chiari. Il guardiano corregge di un passo alla volta mentre lo stream scorre
(`_ritocca_la_posa`), così all'arrivo della bottiglia la posa è di solito già giusta; lo scatto a camera ferma fa fino a
`ritocchi_posa` correzioni, ognuna verificata da `_aspetta_la_posa` (due fotogrammi di fila con la
stessa luce, diversa da quella di partenza). `posa_massima` (4500, in unità da 100 µs) sta sotto il
massimo dichiarato dalla camera, perché oltre una certa posa la camera smette di dare fotogrammi;
se lo stream resta muto con una posa lunga, `_a_vuoto` riparte da `posa_sicura`.

L'anello di LED sposta la luce media di pochi livelli, la posa la moltiplica: per questo l'anello
va a bianco solo per la raffica di `scatta`. In apertura della lettura, `ocr._contrasto_normalizzato`
applica un CLAHE alla sola luminanza (spazio LAB), che aiuta nei casi estremi senza toccare i
colori.

> Ogni collaudo che riguarda la luce va fatto anche **a luce della sala spenta**: è la condizione
> di un ristorante a cena, e lì la posa di partenza da sola non basta.

## Il ritaglio

`Camera.posto` sceglie il rettangolo che va all'OCR. Se la sagoma è nota (`Camera.riquadro`) si
prende quella, allargata ai lati di `allarga_riquadro` (0,08 della sua larghezza): con una mano che
regge il collo la sagoma può essere spostata. Altrimenti si usa un ritaglio centrale fisso di
`ritaglio_largo` (0,70) per `ritaglio_alto` (0,95).

Due frazioni e non una, perché i due compiti stanno su assi diversi: in larghezza si stringe per
lasciare fuori la parete, che il rilevatore legge come testo (un calendario produce decine di
righe, e ognuna costa tempo); in altezza si tiene quasi tutto, perché lì sta l'etichetta.
Stringere troppo non aiuta: il riconoscimento lavora su parole intere, e una parola senza la lettera
iniziale o finale spesso non si ritrova.

### La rilettura allargata

Con le bottiglie tenute in mano il titolo finisce spesso contro il bordo del ritaglio.
`Lettore.allarga`, chiamato da `Amelie._leggi_scatto`, cerca righe con almeno 2 lettere
(`LETTERE_DI_UNA_RIGA`) che arrivano entro `BORDO_CHE_TAGLIA` (3 % della larghezza) dal bordo
sinistro o destro; le righe di sole cifre non si inseguono. Se ce ne sono, rilegge il ritaglio
**esteso fino al bordo del fotogramma** dal lato dove toccano, alla stessa altezza e alla stessa
scala della lettura iniziale, e aggiunge le righe di quella che la rilettura non ritrova.
L'immagine allargata diventa lo scatto di riferimento (è quella che conserva una correzione), e il
giornale annota `"allargata": true`.

## L'OCR

`ocr.Lettore` usa **RapidOCR** con i modelli **PP-OCRv6 tiny** su ONNX Runtime
(`ImpostazioniOCR.reti_piccole`). Il rilevatore dà un quadrilatero per riga, che si rettifica
prospetticamente e poi si legge: così curvatura e scorcio si compensano riga per riga.

**L'immagine va all'OCR a colori, nativa.** I modelli sono addestrati su tre canali, e su
un'etichetta oro su rosso scuro il canale blu da solo non rileva niente. Il grigio serve solo per
misurare (nitidezza, luce, sagoma, confronti delle correzioni).

La lettura è **in due fasi** (`_trova_e_leggi`):

1. **si trova** il testo su una copia rimpicciolita con il lato corto a `lato_rilevatore` (480 px):
   il costo del rilevatore cresce con i pixel, e oltre una certa scala il rilevatore peggiora;
2. **si legge** ogni riga ritagliata dall'immagine a piena risoluzione. Si tengono le
   `righe_massime` (10) più alte, perché la denominazione è scritta grande e i solfiti piccoli, e
   ogni riga si porta a `altezza_riga` (48 px) con un tetto di `larghezza_riga` (320 px).

Restano le righe con confidenza ≥ `confidenza_minima` (0,55) e lunghe almeno 2 caratteri. I
parametri di RapidOCR si danno **alla costruzione** del motore (`Lettore._carica`): passati alla
chiamata ricostruiscono il motore a ogni fotogramma, senza avvisi.

**Il verso.** Il classificatore di orientamento è spento (`usa_classificatore = False`) perché il
fotogramma arriva raddrizzato. Se il montaggio non corrisponde a `rotazione`, l'OCR non degrada:
legge spazzatura. `Lettore.leggi_comunque` prova allora gli altri tre versi, ma solo quando la
lettura iniziale ha meno di 2 parole utili (`parole_che_sono_una_lettura`), meno di 8 righe
(`righe_che_bastano`: di più è una parete) e almeno una lettera; si ferma appena un verso dà 3
parole utili (`parole_che_bastano`).

Una **parola utile** è una riga di almeno tre caratteri non tutti cifre. Una lettura senza parole
utili (`Lettura.utile` falso) è un tentativo fallito: dopo `TENTATIVI_MAX` (3) il dispositivo
smette di riprovare e reimpara lo sfondo, perché quello che vede non è un'etichetta.

## Dal testo letto alle parole confrontabili

In `src/amelie/text.py` il lavoro lo fanno tre funzioni.

- **`normalizza`** prepara il testo per il confronto: toglie accenti e maiuscole, scioglie i punti
  delle sigle (`_sciogli_punti`: «D.O.C.G.» → `docg`, «F.lli» → `flli`, «13.5» → `135`) e riporta
  a lettera le confusioni dell'OCR (`0→o`, `1→l`, `5→s`, `8→b`, `6→g`, `2→z`), lasciando intatti i
  token di sole cifre.
- **`parole_utili`** tiene le parole di almeno tre lettere e toglie `PAROLE_VUOTE`, quelle che
  stanno su quasi ogni etichetta («vino», «doc», «cantina», «tenuta», «riserva», «classico»…). Il
  riconoscitore ha un secondo elenco, `matcher.PAROLE_GENERICHE`: le parole che dicono **che
  tipo** di vino è («spumante», «brut», «rosso», «metodo») e non **quale**.
- **`estrai_annata`** cerca un anno fra 1900 e l'anno massimo, riparando le lettere travestite da
  cifre («2Ol7» → 2017) ma pretendendo, sul testo riparato, confini non alfanumerici. Fra più anni
  vince il più recente: il più vecchio è di solito la fondazione della cantina.

`data/build_db.py` contiene una copia di `normalizza`, tenuta allineata da
`tests/test_build_db.py`. Se cambi la normalizzazione, rigenera colonne `*_norm` e indice con
`python3 scripts/reindicizza.py`.

## Il database

L'archivio è `data/amelie.db`, un SQLite costruito da fonti aperte con `python3 data/build_db.py`.
`Matcher` lo apre **in sola lettura** e ricorda ciò che ha già chiesto; se manca, solleva
`DatabaseAssente`. Le tabelle lette dal riconoscimento:

| tabella | contenuto |
|---|---|
| `ricerca` | indice FTS5: `testo` normalizzato, `ambito`, `ambito_id`, `peso` |
| `vino` | vini commerciali: nome, cantina, forme `*_norm`, regione, tipo, gradazione, `denominazione_id` |
| `denominazione` | DOP e IGP: nome, tipo, regione |
| `tipologia` | le tipologie di ogni denominazione, con colore e categoria UE |
| `tipologia_vitigno` | vitigni per tipologia con `ruolo`: `principale` (imposto) o `ammesso` (tollerato) |
| `tipologia_ue` | descrizioni ufficiali del disciplinare (colore, odore, sapore), con `menzione` e `nome_incerto` |
| `vitigno` | colore della bacca e schede scritte a mano, in italiano e inglese |
| `vino_vitigno`, `vino_abbinamento` | vitigni e abbinamenti dei vini commerciali |

`ricerca` ha una riga per record e quattro **ambiti**: `vino` (cantina più nome), `tipologia`,
`denominazione`, `vitigno`. Il `peso` misura la specificità, dal vino (il più alto) al vitigno;
lo assegna chi costruisce l'indice (`scripts/reindicizza.py`). Le righe di un ambito che il codice
non conosce non entrano in gara (`Matcher.AMBITI`): il database può essere più ricco del codice.

## La ricerca

`Matcher.cerca(righe)` è il punto d'ingresso; senza parole utili restituisce `Fatti()` vuoti.

1. **FTS5 con BM25** trova fino a `CANDIDATI` (200) record cercando le parole utili in OR. BM25
   pesa le parole per rarità: una parola presente in centinaia di nomi conta poco.
2. **RapidFuzz** dà a ciascuno una somiglianza (`token_set_ratio`, indifferente all'ordine e alle
   parole in più). Si ordina per `somiglianza + peso/100`, con un bonus per la coincidenza esatta.
3. **La sicurezza verificata** (`_sicurezza_verificata`) si ricalcola su *tutti* i candidati: la
   verifica abbassa i punteggi, e chi restasse fuori terrebbe quello gonfiato.

La sicurezza misura l'**affermazione**, non la stringa. Per un vino commerciale `_copertura`
cerca ogni parola del nome fra quelle lette (`fuzz.ratio`; sotto `RISCONTRO_PAROLA`, 70, vale
zero; ogni parola letta ne conferma una sola). La cantina si prova solo con le parole **sue**
(`_prova_del_produttore`: le parole della cantina meno quelle della denominazione): se non si
leggono il candidato è `produttore_letto = False` e vale l'80 % della copertura del nome; se si
leggono vale `min(0,6·cantina + 0,4·nome, 1,15·cantina, 1,6·nome)`, scalato sul numero di parole
del record. Per gli altri ambiti la sicurezza è `token_set_ratio` scalato sulla lunghezza del
record (`min(1, 0,55 + 0,15·parole)`).

Infine un **tetto** dipende da quante parole utili ha dato l'OCR (`TETTO_PER_PAROLE`): 60 con una,
78 con due, 87 con tre, nessuno da quattro in su. Una parola sola può combaciare al 100 % per
aritmetica degli insiemi: **per essere certi servono almeno quattro parole utili**.

## La cascata e le soglie

La risposta non è mai «non lo so»: si scende finché si trova qualcosa di vero da dire.

| livello (`Livello`) | che cosa si dice |
|---|---|
| `vino` | il vino di un produttore, con nome e cantina |
| `tipologia` | «è un Barolo Riserva» |
| `denominazione` | «è un Barolo» |
| `vitigno` | «è un Nebbiolo» |
| `generico` | solo ciò che è scritto: «uno spumante rosato metodo classico, brut» |
| `nulla` | niente: si chiede di girare l'etichetta |

`catena_di_ripiego` dà i gradini di ogni record: un vino scende alla sua tipologia
(`_tipologia_del_vino`, che rispetta il colore scritto nel nome e preferisce le tipologie con le
bolle quando il nome le dichiara), poi alla denominazione, poi al suo vitigno, se ha una scheda.

| sicurezza | in `Fatti` | cosa fa `Amelie._riconosci` |
|---|---|---|
| ≥ `SOGLIA_CERTA` (88) | `certo` | racconta, con apertura affermativa |
| da `SOGLIA_DUBBIA` (75) a 88 | `dubbio` | sceglie il candidato più generico, poi racconta |
| sotto 75, livello non `nulla` | — | racconta; per vino, tipologia e vitigno l'apertura lo dice una supposizione |
| livello `nulla` | `vuoto` | chiede di girare l'etichetta; dopo `TENTATIVI_MAX` tace |

**Il dubbio non si chiede all'ospite.** `Matcher.il_piu_generico` prende, fra il primo e le
alternative, quello di livello più generale (`GENERALITA`); a parità resta il primo. Se le
alternative sono vini di produttori diversi, il dubbio è la cantina, e si scende allo stesso vino
senza produttore. Le alternative (al massimo tre, diverse, del colore giusto e tutte lette) restano
nei `Fatti` e nel giornale.

## Non si nomina ciò che non si è letto

È la regola che regge tutto il riconoscimento: un nome detto a voce a un tavolo è
un'affermazione su un'azienda o un luogo veri, e sbagliarlo è peggio che dire una cosa vaga.

- **Il produttore.** Un vino si attribuisce a un produttore solo se le sue parole proprie sono
  sull'etichetta; quelle della denominazione stanno sulla bottiglia di chiunque. Senza prova
  `_senza_produttore` scende al gradino generico: un'etichetta che dice solo «Primitivo di
  Manduria» si racconta come Primitivo di Manduria, non come il vino di uno dei tanti produttori.
- **Tutti i nomi.** `_non_oltre_cio_che_si_e_letto` scende finché le parole **identificanti** del
  record (parole utili meno `PAROLE_GENERICHE`) sono tutte sull'etichetta, ciascuna con un
  riscontro ≥ 70 su una parola letta diversa (`_tutto_letto`). Una soglia di somiglianza non può
  fare questo lavoro: le somiglianze dei riconoscimenti giusti e delle invenzioni si
  sovrappongono, le parole lette no.
- **Il livello generico.** Se nessun gradino regge, `_solo_l_etichetta` dice il colore dichiarato,
  la categoria dedotta dalle parole lette (`CATEGORIA_DETTA`) e i qualificatori nell'ordine in cui
  si pronunciano (`ORDINE_QUALIFICATORI`). A questo livello il modello linguistico non scrive mai.
- **Il colore dichiarato.** Se l'etichetta dichiara un solo colore (`COLORE_DETTO`), nessun record
  di colore diverso può essere quella bottiglia: `_del_colore_giusto` scende fra i primi
  `CANDIDATI_PER_COLORE` (16) fino a uno di quel colore, e `_del_colore_dichiarato` corregge il
  gradino fra le tipologie sorelle della stessa denominazione. «Nero» e «rosa» non contano come
  colori (sono parti di nomi di vitigno); due colori diversi letti insieme valgono come nessuno.
- **Il produttore senza il vino.** Quando la cascata scende sotto il vino,
  `_il_produttore_scritto` rimette la cantina nei fatti solo se le sue parole proprie (almeno
  quattro lettere, non generiche, non nel nome di un vino candidato, non nomi di luogo) si leggono
  con copertura ≥ `PRODUTTORE_SCRITTO` (90), appartengono solo a lei nell'archivio, e un solo
  produttore supera la prova.
- **Due produttori a pari evidenza.** Se fra i primi `RIVALI` (6) c'è un vino di un'altra cantina
  entro `MARGINE_PRODUTTORE` (3 punti), la sicurezza scende appena sotto la certezza e il dubbio
  si risolve senza cantina.
- **Le cooperative omonime.** Un produttore che si chiama come la propria denominazione non ha
  parole sue: non si può provare, e le sue bottiglie si raccontano come generiche.
- **Le citazioni del disciplinare.** `_disciplinare` assegna le descrizioni di `tipologia_ue`
  restringendo, non somigliando: colore uguale, stesso tipo di prodotto (`PRODOTTO_DIVERSO`:
  passito, liquoroso, recioto, vendemmia tardiva…), poi nome identico se affidabile, poi vitigni e
  qualificatori. Se quel che resta dice la stessa cosa la si riporta, altrimenti si tace.

## Il modo carta

Con `--carta vini.csv` e il modo «carta» scelto dalle impostazioni, il dispositivo riconosce i
titoli di un file scritto dal locale (`src/amelie/carta.py`). Colonne `titolo` e `descrizione`,
più `titolo_xx` e `descrizione_xx` per ogni altra lingua:

```csv
titolo,descrizione,titolo_en,descrizione_en
Barolo DOCG,"Il testo che il dispositivo legge.",Barolo DOCG,"The text it reads."
```

`Carta.cerca` non ha cascata: la carta ha la voce o non ce l'ha. Un titolo è ammesso se:

- la somiglianza (`_somiglianza`) è almeno `SOMIGLIANZA_MINIMA` (55). Per le letture a pezzi c'è una
  misura parola per parola, valida solo se il titolo ha almeno due parole, le ritrova tutte con
  riscontro ≥ `RISCONTRO_PEZZO` (75) e almeno una è letta esatta, non generica e lunga almeno
  `ESATTA_CHE_PROVA` (4) lettere;
- ogni sua parola è sull'etichetta (riscontro ≥ 70), tranne le `TACITE` (DOC, DOCG, IGT… e «annata») e quelle
  **implicate** (`Carta._implicate`: presenti in tutte le voci che contengono le parole
  identificanti lette). «Riserva» o «Extra Brut» nel titolo vanno lette;
- le parole implicate non lette non sono più di quelle identificanti lette.

Fra i titoli ammessi vince quello con più parole lette, poi con meno parole non lette, poi la
somiglianza. Se nessuno passa, il giornale annota le voci più vicine (`Carta.vicine`). Anche in
modo carta si interroga l'archivio, per le lingue che la carta non ha.

## Le correzioni a mano

Con «Aggiungi correzioni» acceso, chi sta in sala può insegnare una bottiglia: titolo,
descrizione, e facoltativamente un collegamento a un record dell'archivio o a una voce della
carta. `Correzioni` conserva in `var/correzioni/<id>/` il file `correzione.json` e una foto per
**vista**, con le righe lette e la zona dell'etichetta. Le correzioni si cercano **per prime**, in
ogni modo di racconto (`Amelie._cerca_correzione`), con due segnali:

- **le parole**: `parole_identificanti` (almeno quattro lettere, non generiche) ricordate e
  rilette, con `fuzz.ratio` ≥ 80 e una parola letta per ciascuna;
- **l'immagine**: punti ORB ritrovati in posizione coerente (filtro sul rapporto fra i due
  riscontri migliori, omografia RANSAC), cercati **solo nella zona dell'etichetta**
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

1. scatta e confronta la zona dell'etichetta della foto precedente con la foto nuova
   (`Correzioni.punti_in_comune`): con almeno `STESSA_A_OCCHIO` (25) punti è la stessa bottiglia;
2. altrimenti legge, e `_e_un_altra` decide: stesse parole identificanti (con la `Regola` delle
   correzioni) vuol dire la stessa; un'altra cosa da raccontare (correzione, voce della carta,
   record) vuol dire un'altra; senza parole identificanti non decide, e la bottiglia si rilegge a
   racconto finito;
3. se è un'altra, la voce si ferma (`Evento.CAMBIO_BOTTIGLIA`) e `_scatta_e_leggi` riusa la
   lettura già fatta, finché è entro `ANTICIPO_VALIDO_S`.

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

Il lato predefinito dello script è quello del dispositivo (`lato_rilevatore = 480`); con
`--lato` se ne prova un altro. Il banco stampa quante volte cantina e nome del
vino si ritrovano nel testo letto (`partial_ratio` ≥ 80), le annate plausibili, le etichette mute,
le righe medie, il tempo per etichetta e le cinque peggiori. Sul PC misura la qualità; sulla board,
con il venv del servizio, anche il tempo. Usa `Lettore.leggi` su foto **piane e frontali**, senza
versi di ripiego né rilettura allargata: è un limite superiore.

**Il banco del riconoscimento.** `scripts/bench_matcher.py` passa quel testo a `Matcher.cerca` e lo
confronta con la scheda nota: **coerente** (ciò che si dice torna, anche se si è scesi di
livello), **incoerente**, e **di cui dichiarate certe**, cioè incoerenti sopra `SOGLIA_CERTA`.
Quest'ultima riga **deve restare a zero**: quelle si raccontano come fatti. Seguono la distribuzione
per livello e per fascia di sicurezza. Il banco misura `Matcher.cerca` senza il passaggio di
`il_piu_generico`, e il conteggio per livello non stampa la riga `generico` (si ricava per
differenza).

**Sul dispositivo.**

- **Il giornale** (`src/amelie/giornale.py`) annota ogni scansione in `var/scansioni/giornale.jsonl`
  con il fotogramma accanto: righe lette, tempi di scatto e OCR, nitidezza, posa, `allargata`,
  `anticipata`, livello, sicurezza, nomi, colore, candidati, `scelto_il_piu_generico`,
  `perche_correzione`, e in modo carta le `vicine`. Si legge anche da `GET /giornale?quante=N` e
  `GET /giornale/<nome>`.
- **Il mirino** mostra dal vivo fotogramma, ritaglio, nitidezza, lettura e riconoscimento; si
  accende dalle impostazioni. `scripts/mirino.py`, a servizio fermo, fa lo stesso in un browser e
  accetta `--esposizione`, `--ritaglio`, `--ritaglio-alto`, `--luce`, `--ocr`.
- **`POST /prova/bottiglia`** simula una bottiglia sul piatto (`/prova/via` la toglie,
  `/prova/camera` torna al sensore), per provare lettura e riconoscimento senza il sensore.
- **I test** (`tests/test_matcher.py`, `test_ocr.py`, `test_carta.py`, `test_cambio_bottiglia.py`…)
  si saltano, per la parte di riconoscimento, se mancano il database o `rapidfuzz`.

I numeri aggregati non bastano: ogni modifica a una soglia va rigiocata su **tutte** le etichette
di prova e sulle letture vere del giornale, e ogni differenza va riletta a mano. Una tolleranza che
sistema un caso ne rompe spesso altri, e si vede solo così.

## Come si regola

Cambia un parametro alla volta, rimisura con i banchi e con il giornale, e controlla che le
«dichiarate certe» restino a zero.

| dove | parametro (default) | quando toccarlo |
|---|---|---|
| `ImpostazioniCamera` | `rotazione` (90) | la camera è montata in un altro verso |
| `ImpostazioniCamera` | `esposizione` (900), `posa_massima` (4500) | sala molto buia o camera diversa |
| `ImpostazioniCamera` | `luce_cercata` (90), `luce_tollerata` (8) | etichette bruciate o troppo scure |
| `ImpostazioniCamera` | `ritaglio_largo` (0,70), `ritaglio_alto` (0,95), `allarga_riquadro` (0,08) | entra la parete, o si tagliano le parole |
| `capture.py` | `SOGLIA_NITIDEZZA` (40), `FRAZIONE_SAGOMA` (0,25), `SAGOMA_MASSIMA` (0,70) | fotogrammi mossi, sagome sbagliate |
| `bridge.Presenza` | `vicino_mm` (100), `lontano_mm` (140) | geometria diversa fra piatto e sensore |
| `ImpostazioniOCR` | `lato_rilevatore` (480), `righe_massime` (10) | compromesso fra lettere lette e tempo |
| `ImpostazioniOCR` | `confidenza_minima` (0,55), `usa_classificatore` (falso) | rumore; fotogramma non raddrizzato |
| `ocr.py` | `BORDO_CHE_TAGLIA` (0,03) | quando scatta la rilettura allargata |
| `matcher.py` | `SOGLIA_CERTA` (88), `SOGLIA_DUBBIA` (75), `TETTO_PER_PAROLE` | quanto si afferma |
| `matcher.py` | `RISCONTRO_PAROLA` (70), `PRODUTTORE_SCRITTO` (90), `MARGINE_PRODUTTORE` (3) | prove sui nomi |
| `matcher.py`, `text.py` | `PAROLE_GENERICHE`, `COLORE_DETTO`, `PRODOTTO_DIVERSO`, `PAROLE_VUOTE` | vocabolario delle regole |
| `carta.py` | `SOMIGLIANZA_MINIMA` (55), `RISCONTRO_PEZZO` (75), `TACITE` | severità della carta |
| `correzioni.py` | `Regola` | severità delle correzioni |
| `app.py` | `TENTATIVI_MAX` (3), `STESSA_A_OCCHIO` (25) | tentativi; «è la stessa bottiglia» |

Per estendere il riconoscimento a un nuovo tipo di record servono le righe nell'indice `ricerca`,
l'ambito in `Matcher.AMBITI`, `LIVELLO_DELL_AMBITO` e `GENERALITA`, e un costruttore in
`Matcher._componi`: finché il codice non lo conosce, le sue righe restano fuori gara.

## Limiti noti

- **Vetro chiaro.** Il sensore di distanza lavora all'infrarosso, che attraversa il fondo di una
  bottiglia chiara e non torna: la bottiglia non viene vista e la scansione non parte. Il rimedio
  passa dalla soglia del segnale nel firmware del sensore.
- **Etichette curve.** Sui fianchi del cilindro le lettere si stringono e si perdono: la
  rettifica per riga compensa lo scorcio, non ciò che il vetro nasconde, e la rilettura allargata
  recupera solo ciò che il ritaglio ha tagliato.
- **Riflessi e buio.** Un riflesso speculare brucia le lettere che copre (la posa guarda la luce
  media, il CLAHE non ricostruisce un punto saturo); al buio servono pose lunghe, e una bottiglia
  tenuta in mano si muove, per cui il fotogramma più nitido può non esserlo abbastanza.
- **Caratteri decorativi e trame fitte.** Corsivi ornati e fondi a pattern confondono il
  rilevatore anche quando l'etichetta si legge a occhio; se il nome del vino è decorativo si scende
  alla tipologia o alla denominazione.
- **Annata.** Spesso sta sul collarino, fuori inquadratura o troppo piccola: allora non si dice.
- **Scritte dietro il piatto.** Una parete con testo aggiunge righe e tempo; ritaglio stretto e
  sfondo imparato lo limitano.
- **Copertura dell'archivio.** Si riconosce ciò che è nel database; il resto arriva alla
  denominazione, al livello generico, o si insegna con una correzione. Le cooperative omonime della
  propria denominazione si raccontano sempre come generiche.
- **Verso di montaggio.** Se `rotazione` non corrisponde al montaggio si legge lo stesso, provando
  gli altri versi, ma con più letture per scansione.
