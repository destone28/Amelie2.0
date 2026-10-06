# Le sorgenti del database

*[English version](README.md)*

Questa cartella contiene i dati di terzi da cui `data/build_db.py` costruisce il
database dei vini, `data/amelie.db`. Stanno nel repository perché il
dispositivo lavora senza rete: il database si ricostruisce da questi file, con
gli stessi contenuti, anche se un indirizzo di origine smette di rispondere. Le
schede dei vitigni (`data/vitigni.json`) e il lessico (`data/lessico/`) sono
contenuti del progetto e stanno fuori da questa cartella. Le licenze sono
riassunte qui e spiegate in
[Attribuzioni e licenze](../../docs/it/08-attribuzioni.md).

Qualche termine. Le **DOP** (denominazioni di origine protetta) e le **IGP**
(indicazioni geografiche protette) sono le denominazioni europee dei vini; in
Italia le DOP si chiamano DOCG o DOC, e le IGP portano la menzione IGT. Una
**tipologia** è uno dei vini che il disciplinare di produzione di una
denominazione definisce, per esempio il Riserva. Il **documento unico** è la
sintesi del disciplinare che il registro dell'Unione europea pubblica per ogni
denominazione.

| File | Che cosa contiene | Provenienza | Licenza |
|---|---|---|---|
| `PDO_wine_data_IT_FR.csv` | le DOP italiane e francesi e le loro tipologie: colore, categoria, vitigni principali e ammessi, rese massime. Il costruttore usa le righe delle 408 DOP italiane | Candiago et al. (2024), figshare, <https://doi.org/10.6084/m9.figshare.25393261> | CC BY 4.0 |
| `EU_PDO_id_varieties.csv` | i vitigni principali e gli altri vitigni delle DOP europee; il costruttore non lo legge | Tscholl, Candiago (2022), Zenodo, <https://doi.org/10.5281/zenodo.7257126> | CC BY 4.0 |
| `xwines_italia.csv` | 19.358 vini commerciali italiani, estratti con `data/estrai_xwines.py` | X-Wines, <https://github.com/rogerioxavier/X-Wines> | trattato come ODbL 1.0, con citazione obbligatoria: vedi [Attribuzioni e licenze](../../docs/it/08-attribuzioni.md) |
| `eambrosia_it_wine.tsv` | le 532 indicazioni geografiche italiane del vino: 413 DOP e 119 IGP | registro UE eAmbrosia | © Unione europea, CC BY 4.0 |
| `documenti_unici.jsonl` | il testo dei documenti unici di 523 denominazioni | registro UE eAmbrosia | © Unione europea, CC BY 4.0 |
| `docg.txt` | le DOCG, un nome per riga | scritto a mano dall'elenco pubblico delle DOCG | fatti, non tutelati dal diritto d'autore |

Il dataset X-Wines completo non è nel repository. Per rifare
`xwines_italia.csv` lo si scarica dal repository ufficiale in
`data/sources/X-Wines_Official_Repository/` e si lancia, dalla radice del
repository:

```bash
python3 data/estrai_xwines.py
```

Lo script legge `X-Wines_Official_Repository/last/XWines_Full_100K_wines.csv`.

## Il registro UE

**Da dove.** Il registro delle indicazioni geografiche dell'Unione europea,
eAmbrosia, <https://ec.europa.eu/geographical-indications-register/>, e la sua
interfaccia pubblica per i programmi, <https://webgate.ec.europa.eu/eambrosia-api/>:
le indicazioni geografiche italiane del settore vino, e per ciascuna il PDF
del documento unico.

**Licenza.** I contenuti dei siti della Commissione europea si riutilizzano ai
sensi della Decisione 2011/833/UE, con licenza CC BY 4.0: attribuzione
«© Unione europea» e indicazione delle modifiche (qui: testo estratto dai PDF,
recapiti personali omessi, come descritto più sotto). Il documento unico
riassume il disciplinare di produzione, che è un atto ufficiale dello Stato: in
Italia i testi degli atti ufficiali non sono coperti dal diritto d'autore
(art. 5, legge 633/1941).

**`eambrosia_it_wine.tsv`**: una riga per indicazione, campi separati da
tabulazioni, senza intestazione:

```
identificativo GI | nomi (separati da «|») | numero di fascicolo | PDO o PGI |
numero di categorie | data di protezione | scheda | consorzio di tutela
```

Il numero di fascicolo (per esempio `PDO-IT-A0435`) identifica la domanda di
registrazione nel registro UE, ed è la stessa chiave che usa figshare: aggancia
le due fonti senza confrontare i nomi. Il consorzio è il nome di un ente, e il
costruttore non lo legge.

**`documenti_unici.jsonl`**: un oggetto JSON per riga:

```
{"fn": numero di fascicolo, "nome": nomi, "tipo": "PDO" | "PGI", "d": testo}
```

`d` è il testo estratto dal PDF del documento unico, così come esce
dall'estrazione: senza righe né colonne, con le intestazioni di pagina in
mezzo. Il costruttore aggancia ogni documento al registro per nome, il primo
nome del documento contro tutti i nomi del registro; `data/fonti_ue.py` spiega
come se ne ricavano colore, odore e sapore di ogni tipologia.

Il testo non riporta i **recapiti** che il modulo UE indica per il richiedente
e per l'autorità nazionale: indirizzi di posta elettronica, anche nominativi, e
numeri di telefono e di fax. Restano gli enti, gli indirizzi postali delle sedi
dove il documento li riporta e tutto il resto del documento. Il costruttore non
usa nessuna di quelle parti, quindi ometterle non cambia il database.

## `docg.txt`

Il registro UE distingue le DOP dalle IGP, ma non le DOCG dalle DOC: le DOCG
sono un elenco italiano. Il file ha un nome per riga; una denominazione è DOCG
se uno qualunque dei suoi nomi nel registro è nell'elenco, con il confronto
fatto senza maiuscole, accenti e punteggiatura. Alcune DOCG compaiono sia con il
nome d'uso sia con quello del registro («Sagrantino di Montefalco», «Montefalco
Sagrantino»): conta che ci sia il secondo.

Le denominazioni del registro che risultano DOCG sono 74. Si contano così,
dalla radice del repository:

```bash
python3 -c "import sys; sys.path.insert(0, 'data'); import fonti_ue as f; print(sum(v.menzione == 'DOCG' for v in f.leggi_registro()))"
```
