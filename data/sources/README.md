# The database sources

*[Versione italiana](LEGGIMI.md)*

This folder holds the third-party data from which `data/build_db.py` builds the
wine database, `data/amelie.db`. The files are in the repository because the
device works without a network: the database is rebuilt from these files, with
the same contents, even if an original address stops responding. The grape
variety sheets (`data/vitigni.json`) and the lexicon (`data/lessico/`) are the
project's own content and live outside this folder. The licences are
summarised here and explained in
[Attributions and licences](../../docs/en/08-attributions.md).

A few terms. **DOP** (*denominazione di origine protetta*, PDO, protected
designation of origin) and **IGP** (*indicazione geografica protetta*, PGI,
protected geographical indication) are the European appellations for wine; in
Italy DOPs are called DOCG or DOC, and IGPs carry the term IGT. A **tipologia**
is one of the wines that an appellation's production specification
(*disciplinare di produzione*) defines, for example the Riserva. The **single
document** is the summary of the production specification that the European
Union's register publishes for each appellation.

| File | What it contains | Origin | Licence |
|---|---|---|---|
| `PDO_wine_data_IT_FR.csv` | the Italian and French DOPs and their tipologie: colour, category, main and permitted grape varieties, maximum yields. The builder uses the rows of the 408 Italian DOPs | Candiago et al. (2024), figshare, <https://doi.org/10.6084/m9.figshare.25393261> | CC BY 4.0 |
| `EU_PDO_id_varieties.csv` | the main and the other grape varieties of the European PDOs; the builder does not read it | Tscholl, Candiago (2022), Zenodo, <https://doi.org/10.5281/zenodo.7257126> | CC BY 4.0 |
| `xwines_italia.csv` | 19,358 Italian commercial wines, extracted with `data/estrai_xwines.py` | X-Wines, <https://github.com/rogerioxavier/X-Wines> | treated as ODbL 1.0, with a required citation: see [Attributions and licences](../../docs/en/08-attributions.md) |
| `eambrosia_it_wine.tsv` | the 532 Italian geographical indications for wine: 413 DOPs and 119 IGPs | EU register eAmbrosia | © European Union, CC BY 4.0 |
| `documenti_unici.jsonl` | the text of the single documents of 523 appellations | EU register eAmbrosia | © European Union, CC BY 4.0 |
| `docg.txt` | the DOCGs, one name per line | written by hand from the public list of DOCGs | facts, not protected by copyright |

The full X-Wines dataset is not in the repository. To rebuild
`xwines_italia.csv`, download it from the official repository into
`data/sources/X-Wines_Official_Repository/` and run, from the root of the
repository:

```bash
python3 data/estrai_xwines.py
```

The script reads `X-Wines_Official_Repository/last/XWines_Full_100K_wines.csv`.

## The EU register

**Where from.** The European Union's register of geographical indications,
eAmbrosia, <https://ec.europa.eu/geographical-indications-register/>, and its
public programming interface, <https://webgate.ec.europa.eu/eambrosia-api/>:
the Italian geographical indications of the wine sector, and for each one the
PDF of its single document.

**Licence.** The content of the European Commission's websites is reused under
Decision 2011/833/EU, with the CC BY 4.0 licence: attribution "© European
Union" and an indication of the changes (here: text extracted from the PDFs,
personal contact details left out, as described below). The single document
summarises the production specification, which is an official act of the
State: in Italy the texts of official acts are not covered by copyright
(art. 5, law 633/1941).

**`eambrosia_it_wine.tsv`**: one line per indication, fields separated by
tabs, no header:

```
GI identifier | names (separated by "|") | file number | PDO or PGI |
number of categories | protection date | record | protection consortium
```

The file number (for example `PDO-IT-A0435`) identifies the registration
application in the EU register, and it is the same key that figshare uses: it
links the two sources without comparing names. The consortium is the name of an
organisation, and the builder does not read it.

**`documenti_unici.jsonl`**: one JSON object per line:

```
{"fn": file number, "nome": names, "tipo": "PDO" | "PGI", "d": text}
```

`d` is the text extracted from the PDF of the single document, exactly as the
extraction produces it: without lines or columns, with the page headers in the
middle. The builder links each document to the register by name, the
document's first name against all the names in the register;
`data/fonti_ue.py` explains how the colour, aroma and taste of each tipologia
are derived from it.

The text does not include the **contact details** that the EU form gives for
the applicant and for the national authority: email addresses, including
personal ones, and telephone and fax numbers. The organisations, the postal
addresses of their offices where the document gives them, and all the rest of
the document remain. The builder uses none of those parts, so leaving them out
does not change the database.

## `docg.txt`

The EU register tells DOPs from IGPs, but not DOCGs from DOCs: the DOCGs are an
Italian list. The file has one name per line; an appellation is a DOCG if any
of its names in the register is in the list, with the comparison made ignoring
case, accents and punctuation. Some DOCGs appear both with their common name
and with the register's name ("Sagrantino di Montefalco", "Montefalco
Sagrantino"): what matters is that the second one is there.

In the register, 74 appellations come out as DOCG. They are counted like this,
from the root of the repository:

```bash
python3 -c "import sys; sys.path.insert(0, 'data'); import fonti_ue as f; print(sum(v.menzione == 'DOCG' for v in f.leggi_registro()))"
```
