# Le sorgenti del database

Tutto ciò che `data/build_db.py` legge sta in questa cartella, versionato: il
dispositivo è offline, e il database si deve poter rifare identico anche quando
un indirizzo non risponde più. Le licenze sono riassunte qui e spiegate in
[`docs/ATTRIBUZIONI.md`](../../docs/ATTRIBUZIONI.md).

| File | Cosa contiene | Provenienza | Licenza |
|---|---|---|---|
| `PDO_wine_data_IT_FR.csv` | 408 DOP italiane e le loro tipologie: colore, categoria, vitigni imposti e ammessi, rese | Candiago et al. (2024), figshare, <https://doi.org/10.6084/m9.figshare.25393261> | CC BY 4.0 |
| `EU_PDO_id_varieties.csv` | vitigni principali delle DOP europee (non letto dal costruttore) | Candiago et al. (2022), <https://doi.org/10.5281/zenodo.7257126> | CC BY 4.0 |
| `xwines_italia.csv` | 19.358 vini commerciali italiani, estratti con `data/estrai_xwines.py` | X-Wines, <https://github.com/rogerioxavier/X-Wines> | vedi ATTRIBUZIONI: trattato come ODbL 1.0 |
| `eambrosia_it_wine.tsv` | le 532 indicazioni geografiche italiane del vino, DOP e IGP | registro UE eAmbrosia | © Unione europea, CC BY 4.0 |
| `documenti_unici.jsonl` | il testo dei documenti unici di 523 denominazioni | registro UE eAmbrosia | © Unione europea, CC BY 4.0 |
| `docg.txt` | le DOCG, un nome per riga | scritto a mano dall'elenco pubblico delle DOCG | fatti, non tutelabili |

## Il registro UE

**Da dove.** Il registro delle indicazioni geografiche dell'Unione europea,
<https://ec.europa.eu/geographical-indications-register/>, e la sua
interfaccia pubblica, <https://webgate.ec.europa.eu/eambrosia-api/>: le
indicazioni geografiche italiane del settore vino, e per ciascuna il PDF del
documento unico.

**Licenza.** I contenuti dei siti della Commissione si riutilizzano ai sensi
della Decisione 2011/833/UE, con licenza CC BY 4.0: attribuzione
«© Unione europea», con l'indicazione delle modifiche. Il documento unico
riproduce il disciplinare di produzione, che è un atto ufficiale dello Stato
(art. 5 L. 633/1941).

**`eambrosia_it_wine.tsv`** — una riga per indicazione, separata da tabulazioni,
senza intestazione:

    identificativo GI | nomi (separati da «|») | numero di fascicolo | PDO o PGI |
    numero di categorie | data di protezione | scheda | consorzio di tutela

Il numero di fascicolo (`PDO-IT-A0435`) è la stessa chiave che usa figshare, e
aggancia le due fonti senza confrontare i nomi. Il consorzio è il nome di un
ente, e il costruttore non lo legge.

**`documenti_unici.jsonl`** — un oggetto per riga:

    {"fn": numero di fascicolo, "nome": nomi, "tipo": "PDO" | "PGI", "d": testo}

`d` è il testo estratto dal PDF del documento unico, così come esce
dall'estrazione: senza righe né colonne, con le intestazioni di pagina in mezzo.
`data/fonti_ue.py` spiega come se ne ricavano colore, odore e sapore di ogni
tipologia.

Dal testo sono stati **tolti i recapiti** che il modulo UE riporta per il
richiedente e per l'autorità nazionale: indirizzi di posta elettronica, anche
nominativi, e numeri di telefono e di fax. Restano gli enti, gli indirizzi
postali delle sedi e tutto il resto del documento. Il costruttore non legge
nessuna di quelle parti, e i risultati sono identici con e senza i recapiti.

## `docg.txt`

Il registro UE distingue DOP da IGP ma non DOCG da DOC: le DOCG sono un
elenco italiano. Un nome per riga; una denominazione è DOCG se uno qualunque
dei suoi nomi nel registro è in elenco, confrontati senza accenti né
punteggiatura. Alcune DOCG compaiono sia col nome d'uso sia con quello del
registro («Sagrantino di Montefalco», «Montefalco Sagrantino»): conta che ci
sia il secondo. Le 74 DOCG riconosciute si controllano con

    python3 -c "import sys; sys.path.insert(0, 'data'); import fonti_ue as f; \
    print(sum(v.menzione == 'DOCG' for v in f.leggi_registro()))"
