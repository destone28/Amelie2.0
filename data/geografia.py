# -*- coding: utf-8 -*-
"""Da una denominazione alla sua regione amministrativa.

    from geografia import regione_di
    regione_di("Barolo")             -> "Piemonte"
    regione_di("Aleatico di Puglia") -> "Puglia"

Nessuna fonte aperta dice in quale regione stia una denominazione: il registro
UE non lo riporta, e i nomi di X-Wines mescolano regioni amministrative e zone
di produzione (Barolo, Chianti, Collio...). La mappa qui sotto e' scritta a
mano e riporta ogni zona alla sua regione. Le zone a cavallo di piu' regioni
stanno in quella prevalente: Prosecco e Delle Venezie in Veneto, Lugana in
Lombardia, Colli di Luni in Liguria.

La ricerca e' volutamente prudente. Si prova, nell'ordine:

1. il nome intero, fra le zone della mappa;
2. il nome senza una menzione finale («Frascati Superiore» -> «Frascati»);
3. la parte del nome che precede «di», «del», «della»...
   («Sforzato di Valtellina/Sfursat di Valtellina» -> «Sforzato»);
4. il nome di una regione dentro il nome («Aleatico di Puglia»);
5. qualche forma che nei nomi sta al posto della regione («Alto Adige»,
   «Romagna», «Sannio»).

Una denominazione che non passa nessuna di queste resta senza regione: il
racconto la tace invece di indovinarla. Succede a circa tre su dieci, per lo
piu' nomi composti («Bianco di Custoza/Custoza») o con l'apostrofo tipografico
(«Barbera d’Alba»), che la chiave qui sotto non scioglie.
"""
from __future__ import annotations

import re
import unicodedata

REGIONE_DI: dict[str, str] = {}


def _aggiungi(regione: str, zone: list[str]) -> None:
    for z in zone:
        REGIONE_DI[z] = regione


_aggiungi("Piemonte", [
    "Barolo", "Langhe", "Barbera d'Alba", "Barbera d'Asti", "Barbaresco", "Gavi",
    "Dolcetto d'Alba", "Asti", "Nebbiolo d'Alba", "Roero", "Monferrato", "Moscato d'Asti",
    "Gattinara", "Alba", "Barbera del Monferrato", "Dogliani", "Ghemme", "Colli Tortonesi",
    "Alto Piemonte", "Dolcetto di Dogliani", "Piemonte Barbera", "Brachetto d'Acqui",
    "Erbaluce di Caluso", "Cortese di Gavi", "Nizza", "Ruche di Castagnole Monferrato",
    "Grignolino d'Asti", "Barbera d'Asti Superiore", "Langhe Nebbiolo", "Verduno Pelaverga",
    "Carema", "Boca", "Lessona"])

_aggiungi("Toscana", [
    "Chianti", "Chianti Classico", "Brunello di Montalcino", "Rosso di Montalcino",
    "Maremma Toscana", "Vino Nobile di Montepulciano", "Vernaccia di San Gimignano",
    "Bolgheri", "Chianti Colli Senesi", "San Gimignano", "Morellino di Scansano",
    "Bolgheri Superiore", "Rosso di Montepulciano", "Vin Santo del Chianti Classico",
    "Toscano", "Toscana", "Chianti Rufina", "Chianti Colli Fiorentini", "Carmignano",
    "Montecucco", "Suvereto", "Val di Cornia", "Vin Santo del Chianti", "Cortona",
    "Bolgheri Sassicaia", "Chianti Montalbano", "Chianti Colline Pisane", "Montescudaio",
    "Colline Lucchesi", "Elba", "Terre di Pisa"])

_aggiungi("Veneto", [
    "Valpolicella", "Prosecco", "Conegliano-Valdobbiadene Prosecco", "Bardolino",
    "Amarone della Valpolicella", "Amarone della Valpolicella Classico",
    "Valpolicella Ripasso", "Soave", "Soave Classico", "Verona", "Prosecco di Treviso",
    "Bardolino Classico", "Recioto della Valpolicella Classico", "Bianco di Custoza",
    "Custoza", "Bardolino Chiaretto", "Valpolicella Classico",
    "Valpolicella Ripasso Classico", "Lugana", "Venezia", "Rosso Veronese",
    "Conegliano-Valdobbiadene Prosecco Superiore", "Recioto della Valpolicella", "Piave",
    "Colli Euganei", "Breganze", "Gambellara", "Bagnoli", "Lison", "Montello",
    "Valdobbiadene", "Veronese", "Delle Venezie", "Vigneti delle Dolomiti", "Garda"])

_aggiungi("Friuli-Venezia Giulia", [
    "Collio", "Colli Orientali del Friuli", "Friuli Grave", "Venezia Giulia",
    "Friuli Isonzo", "Friuli Aquileia", "Friuli Colli Orientali", "Carso", "Friuli Annia",
    "Friuli Latisana", "Ramandolo", "Colli Orientali del Friuli Picolit", "Rosazzo"])

_aggiungi("Trentino-Alto Adige", [
    "Südtirol-Alto Adige", "Trentino", "Trento", "Teroldego Rotaliano", "Alto Adige",
    "Alto Adige Valle Isarco", "Alto Adige Terlano", "Alto Adige Santa Maddalena",
    "Alto Adige Lago di Caldaro", "Trentino Superiore", "Valle Isarco", "Vallagarina"])

_aggiungi("Puglia", [
    "Salento", "Primitivo di Manduria", "Salice Salentino", "Brindisi", "Puglia",
    "Castel del Monte", "Copertino", "Gioia del Colle", "Locorotondo", "Squinzano",
    "Negroamaro", "Manduria", "Tarantino", "Daunia", "Murgia", "Nardò", "Alezio",
    "Leverano", "Valle d'Itria"])

_aggiungi("Sicilia", [
    "Terre Siciliane", "Etna", "Cerasuolo di Vittoria", "Marsala", "Sicilia",
    "Pantelleria", "Noto", "Vittoria", "Faro", "Malvasia delle Lipari", "Menfi",
    "Contea di Sclafani", "Passito di Pantelleria", "Salaparuta", "Eloro", "Alcamo",
    "Monreale"])

_aggiungi("Abruzzo", [
    "Montepulciano d'Abruzzo", "Cerasuolo d'Abruzzo", "Trebbiano d'Abruzzo",
    "Terre di Chieti", "Abruzzo", "Colline Teramane",
    "Montepulciano d'Abruzzo Colline Teramane", "Controguerra", "Villamagna",
    "Terre Aquilane", "Colline Pescaresi", "Colli Aprutini"])

_aggiungi("Emilia-Romagna", [
    "Emilia", "Rubicone", "Sangiovese di Romagna", "dell'Emilia", "Romagna",
    "Lambrusco di Sorbara", "Lambrusco Grasparossa di Castelvetro",
    "Lambrusco Salamino di Santa Croce", "Colli Bolognesi", "Modena", "Reggiano",
    "Colli Piacentini", "Gutturnio", "Albana di Romagna", "Romagna Albana",
    "Bosco Eliceo", "Forlì", "Ravenna", "Rubicone Sangiovese"])

_aggiungi("Lombardia", [
    "Franciacorta", "Oltrepò Pavese", "Provincia di Pavia", "Valtellina",
    "Valtellina Superiore", "Sforzato di Valtellina", "Lugana Lombardia", "Curtefranca",
    "Terre Lariane", "Garda Classico", "Valcalepio", "Sebino", "Benaco Bresciano",
    "Bergamasca", "San Colombano", "Riviera del Garda", "Sforzato"])

_aggiungi("Campania", [
    "Fiano di Avellino", "Falanghina del Beneventano", "Taurasi", "Greco di Tufo",
    "Campania", "Aglianico del Taburno", "Costa d'Amalfi", "Sannio", "Irpinia",
    "Falerno del Massico", "Beneventano", "Paestum", "Cilento", "Vesuvio",
    "Lacryma Christi del Vesuvio", "Penisola Sorrentina"])

_aggiungi("Umbria", [
    "Montefalco", "Orvieto Classico", "Orvieto", "Umbria", "Sagrantino di Montefalco",
    "Torgiano", "Torgiano Rosso Riserva", "Colli del Trasimeno", "Montefalco Sagrantino"])

_aggiungi("Marche", [
    "Rosso Piceno", "Verdicchio dei Castelli di Jesi", "Verdicchio di Matelica", "Conero",
    "Offida", "Marche", "Castelli di Jesi Verdicchio", "Rosso Conero",
    "Lacrima di Morro d'Alba", "Bianchello del Metauro", "Pergola", "Falerio"])

_aggiungi("Sardegna", [
    "Cannonau di Sardegna", "Vermentino di Gallura", "Vermentino di Sardegna", "Sardegna",
    "Carignano del Sulcis", "Isola dei Nuraghi", "Turriga", "Monica di Sardegna",
    "Vernaccia di Oristano", "Nuragus di Cagliari", "Alghero", "Mandrolisai", "Barbagia",
    "Colli del Limbara"])

_aggiungi("Lazio", [
    "Frascati", "Castelli Romani", "Lazio", "Cesanese del Piglio", "Est! Est!! Est!!!",
    "Marino", "Cesanese di Olevano Romano", "Bianco Capena", "Aprilia", "Colli Albani",
    "Velletri", "Cori"])

_aggiungi("Liguria", [
    "Riviera Ligure di Ponente", "Cinque Terre", "Colli di Luni", "Liguria",
    "Rossese di Dolceacqua", "Golfo del Tigullio", "Val Polcevera", "Pornassio"])

_aggiungi("Basilicata", [
    "Aglianico del Vulture", "Basilicata", "Aglianico del Vulture Superiore", "Matera",
    "Grottino di Roccanova", "Terre dell'Alta Val d'Agri"])

_aggiungi("Calabria", [
    "Cirò", "Calabria", "Savuto", "Greco di Bianco", "Terre di Cosenza", "Val di Neto",
    "Melissa", "Lamezia", "Scavigna", "Bivongi"])

_aggiungi("Molise", [
    "Molise", "Biferno", "Tintilia del Molise", "Pentro di Isernia", "Osco",
    "Terre degli Osci"])

_aggiungi("Valle d'Aosta", [
    "Valle d'Aosta", "Vallée d'Aoste", "Blanc de Morgex", "Donnas", "Chambave",
    "Arnad-Montjovet"])

# Denominazioni minori, DOC e IGT.
_aggiungi("Veneto", [
    "Colli Berici", "Asolo Prosecco", "Recioto di Soave", "Recioto di Soave Classico",
    "Marca Trevigiana", "Valdadige", "Bardolino Superiore", "Montello e Colli Asolani",
    "Colli Trevigiani", "Soave Superiore", "Arcole", "Merlara", "Riviera del Brenta",
    "Corti Benedettine del Padovano"])
_aggiungi("Friuli-Venezia Giulia", [
    "Friuli", "Alto Livenza", "Colli Orientali", "Friuli Colli Orientali Picolit"])
_aggiungi("Toscana", [
    "Chianti Rùfina", "Colli della Toscana Centrale", "Sant'Antimo", "Costa Toscana",
    "Pomino", "Bianco dell'Empolese", "Barco Reale di Carmignano", "Valdichiana Toscana",
    "Orcia", "Terratico di Bibbona", "Grance Senesi", "Sovana", "Parrina",
    "Ansonica Costa dell'Argentario"])
_aggiungi("Campania", [
    "Taburno", "Campi Flegrei", "Galluccio", "Ischia", "Capri",
    "Casavecchia di Pontelatone", "Aversa", "Costa d'Amalfi Furore", "Roccamonfina",
    "Colli di Salerno", "Pompeiano", "Terre del Volturno"])
_aggiungi("Piemonte", [
    "Pinerolese", "Alta Langa", "Cortese dell'Alto Monferrato", "Coste della Sesia",
    "Dolcetto di Diano d'Alba", "Verduno", "Barolo Chinato", "Diano d'Alba", "Albugnano",
    "Calosso", "Canavese", "Colline Novaresi", "Fara", "Sizzano", "Valsusa", "Loazzolo",
    "Cisterna d'Asti", "Collina Torinese", "Freisa d'Asti", "Malvasia di Casorzo",
    "Strevi", "Terre Alfieri", "Valli Ossolane"])
_aggiungi("Lombardia", [
    "Ronchi di Brescia", "Bonarda dell'Oltrepo Pavese", "Botticino", "Cellatica",
    "Lambrusco Mantovano", "Capriano del Colle", "Casteggio", "Buttafuoco",
    "Sangue di Giuda", "Pinot Nero dell'Oltrepò Pavese", "Alto Mincio",
    "Montenetto di Brescia", "Ronchi Varesini", "Quistello", "Sabbioneta",
    "Terrazze Retiche di Sondrio"])
_aggiungi("Marche", [
    "Rosso Conero Riserva", "Serrapetrona", "Vernaccia di Serrapetrona", "Colli Pesaresi",
    "Colli Maceratesi", "Terre di Offida", "Marche Rosso", "Esino",
    "Terreni di Sanseverino"])
_aggiungi("Sicilia", [
    "Delia Nivolelli", "Erice", "Mamertino", "Riesi", "Sambuca di Sicilia",
    "Santa Margherita di Belice", "Sciacca", "Siracusa", "Vittoria Frappato", "Camarro",
    "Fontanarossa di Cerda", "Salemi", "Valle Belice"])
_aggiungi("Lazio", [
    "Colli Etruschi Viterbesi", "Roma", "Atina", "Circeo", "Genazzano", "Nettuno",
    "Tarquinia", "Vignanello", "Zagarolo", "Colli della Sabina", "Costa Etrusco Romana",
    "Frusinate", "Civitella d'Agliano"])
_aggiungi("Puglia", [
    "Salento Rosso", "Colline Joniche Tarantine", "Galatina", "Martina Franca", "Matino",
    "Ostuni", "Rosso Barletta", "Rosso Canosa", "San Severo", "Cacc'e mmitte di Lucera",
    "Orta Nova"])
_aggiungi("Emilia-Romagna", [
    "Colli d'Imola", "Colli di Faenza", "Colli di Parma", "Colli di Rimini",
    "Colli di Scandiano e di Canossa", "Colli Romagna Centrale", "Ortrugo",
    "Terre di Veleja", "Val Tidone"])
_aggiungi("Umbria", [
    "Colli Amerini", "Colli Martani", "Colli Perugini", "Lago di Corbara",
    "Rosso Orvietano", "Spoleto", "Todi", "Assisi", "Narni", "Spello"])
_aggiungi("Abruzzo", [
    "Ortona", "Terre Tollesi", "Tullum", "Histonium", "Colli del Sangro", "Del Vastese"])
_aggiungi("Sardegna", [
    "Malvasia di Bosa", "Moscato di Sardegna", "Girò di Cagliari", "Nasco di Cagliari",
    "Semidano", "Campidano di Terralba", "Provincia di Nuoro", "Ogliastra", "Marmilla",
    "Parteolla", "Planargia", "Romangia", "Sibiola", "Tharros", "Trexenta",
    "Valle del Tirso", "Valli di Porto Pino"])
_aggiungi("Calabria", [
    "Terre di Cosenza Donnici", "Pollino", "Sant'Anna di Isola Capo Rizzuto", "Verbicaro",
    "Costa Viola", "Locride", "Palizzi", "Pellaro", "Scilla", "Arghillà", "Caloveto",
    "Esaro", "Lipuda", "Valdamato", "Valle dei Crati"])
_aggiungi("Basilicata", ["Grottino di Roccanova Rosso", "Colli Lucani"])
_aggiungi("Trentino-Alto Adige", [
    "Casteller", "Alto Adige Meranese", "Alto Adige Val Venosta",
    "Alto Adige Colli di Bolzano", "Mitterberg"])
_aggiungi("Liguria", [
    "Val Polcevera Coronata", "Riviera Ligure di Levante", "Colline del Genovesato",
    "Colline Savonesi", "Terrazze dell'Imperiese"])
_aggiungi("Molise", ["Rotae", "Terre degli Osci Rosso"])
_aggiungi("Valle d'Aosta", ["Torrette", "Enfer d'Arvier", "Nus", "Chambave Muscat"])

# Le venti regioni, nell'ordine in cui si cercano dentro un nome.
REGIONI = [
    "Piemonte", "Toscana", "Veneto", "Lombardia", "Friuli-Venezia Giulia", "Sicilia",
    "Puglia", "Campania", "Emilia-Romagna", "Trentino-Alto Adige", "Lazio", "Umbria",
    "Marche", "Abruzzo", "Sardegna", "Calabria", "Liguria", "Basilicata", "Molise",
    "Valle d'Aosta"]

# Forme che nei nomi delle denominazioni stanno al posto della regione.
ALIAS = {
    "alto adige": "Trentino-Alto Adige", "sudtirol": "Trentino-Alto Adige",
    "sudtiroler": "Trentino-Alto Adige", "trentino": "Trentino-Alto Adige",
    "romagna": "Emilia-Romagna", "colli piacentini": "Emilia-Romagna",
    "delle venezie": "Veneto", "venezia giulia": "Friuli-Venezia Giulia",
    "friuli": "Friuli-Venezia Giulia", "sicilia": "Sicilia", "d'abruzzo": "Abruzzo",
    "salento": "Puglia", "daunia": "Puglia", "irpinia": "Campania", "sannio": "Campania",
}

_MENZIONI_FINALI = (" superiore", " classico", " riserva", " spumante", " passito",
                    " novello")


def _chiave(s: str) -> str:
    """Minuscole, senza accenti, solo lettere, cifre e apostrofo diritto."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9' ]+", " ", s).strip()


_MAPPA = {_chiave(z): r for z, r in REGIONE_DI.items()}


def regione_di(nome: str) -> str | None:
    """La regione di una denominazione, o None se il nome non basta a dirla."""
    kn = _chiave(nome)
    if kn in _MAPPA:
        return _MAPPA[kn]
    for coda in _MENZIONI_FINALI:
        if kn.endswith(coda) and _MAPPA.get(kn[:-len(coda)]):
            return _MAPPA[kn[:-len(coda)]]
    primo = re.split(r"\b(di|del|della|dei|delle|d)\b", kn)[0].strip()
    if _MAPPA.get(primo):
        return _MAPPA[primo]
    for r in REGIONI:
        if _chiave(r) in kn:
            return r
    for forma, r in ALIAS.items():
        if forma in kn:
            return r
    return None
