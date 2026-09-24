"""La pagina e il server si parlano per indirizzi: quelli della pagina devono esistere.

E qualche regola della pagina che una svista romperebbe senza far fallire
nient'altro: il pulsante della correzione nell'intestazione, le accentate
sulla tastiera, le misure della sfumatura che `segui()` deve conoscere.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[1]
PAGINA = (RADICE / "src/amelie/ui/static/index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rotte():
    from amelie.app import Amelie, Configurazione, crea_app
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    try:
        return [r.path for r in crea_app(a).routes]
    finally:
        a.matcher.chiudi()
        a.narratore.chiudi()


def test_ogni_indirizzo_della_pagina_ha_una_rotta(rotte):
    """Un `fetch` verso un indirizzo che non c'e' non da' errore a nessuno: il
    pulsante semplicemente non fa niente. Per quelli composti - «/lingua/» piu'
    il codice - basta che esista una rotta con quel prefisso."""
    chiamate = re.findall(r'fetch\("([^"]+)"(\s*\+)?', PAGINA)
    assert len(chiamate) >= 10, "la ricerca dei fetch non trova piu' niente"
    for indirizzo, composto in chiamate:
        if "?" in indirizzo:
            # «/correzione/cerca?q=» + il testo: la parte variabile e' la query.
            assert indirizzo.split("?")[0] in rotte, indirizzo
        elif composto:
            assert any(r.startswith(indirizzo) and "{" in r for r in rotte), indirizzo
        else:
            assert indirizzo in rotte, indirizzo


def test_il_pulsante_della_correzione_sta_nell_intestazione():
    """In coda al racconto finiva sotto la sfumatura, o fuori vista finche' il
    testo non scorreva fino in fondo."""
    intestazione = re.search(r'<header class="intestazione">(.*?)</header>', PAGINA, re.S)
    assert intestazione and 'id="r-correggi"' in intestazione.group(1)


def test_la_tastiera_ha_tutte_le_accentate():
    lettere = re.search(r"const LETTERE = \[(.*?)\];", PAGINA, re.S).group(1)
    for a in "àèéìòù":
        assert f'"{a}"' in lettere, a


def test_segui_conosce_la_sfumatura_vera():
    """`segui()` tiene la frase detta fra le due sfumature: se la maschera
    cambia e le sue costanti no, la frase torna a finire dietro ai comandi."""
    su, giu = map(int, re.search(r"const SFUMA_SU = (\d+), SFUMA_GIU = (\d+);",
                                 PAGINA).groups())
    maschera = re.search(r"\.testo\.scorso \{\s*mask-image: linear-gradient\((.*?)\);",
                         PAGINA, re.S).group(1)
    assert f"#000 {su}px" in maschera
    assert f"#000 calc(100% - {giu}px)" in maschera
    # E l'ultima riga del racconto deve poter salire sopra la sfumatura.
    fondo = int(re.search(r"#racconto \.testo \{ padding-bottom: (\d+)px; \}",
                          PAGINA).group(1))
    assert fondo >= giu


def test_la_maiuscola_non_ricostruisce_la_tastiera():
    """Ricostruire i tasti a ogni cambio di maiuscola faceva sparire il ⌫ da
    sotto il dito: un tocco che svuotava il campo riaccendeva la maiuscola, il
    ripetitore del tasto vecchio partiva dopo 450 ms e non lo fermava piu'
    nessuno. Sul dispositivo: «il cancella sembra sempre premuto, non riesco a
    scrivere». Le maiuscole cambiano le scritte; i tasti si ricostruiscono solo
    cambiando strato, lettere o simboli."""
    maiuscola = re.search(r"function aggiornaMaiuscola\(\) \{(.*?)\n\}", PAGINA, re.S).group(1)
    assert "disegnaTastiera" not in maiuscola
    batti = re.search(r"function batti\(t\) \{(.*?)\n\}", PAGINA, re.S).group(1)
    assert batti.count("disegnaTastiera") == 2, "solo ?123 e ABC ricostruiscono i tasti"
    # e il ripetitore del cancella e' uno solo, fermato da qualunque dito che si alzi
    assert 'window.addEventListener(ev, fermaRipetizione, true)' in PAGINA


def test_la_home_riceve_motto_e_tre_passi():
    """Le scritte dell'attesa vengono dal lessico, in ogni lingua: la pagina
    deve avere un posto per ciascuna, e il server deve mandarle tutte."""
    for ident in ("motto", "invito", "p1-s", "p2-t", "p2-s", "p3-t", "p3-s"):
        assert f'id="{ident}"' in PAGINA, ident
    from amelie.app import Amelie, Configurazione
    a = Amelie(Configurazione(simula_mcu=True, senza_camera=True, senza_voce=True,
                              senza_modello=True))
    try:
        for lingua in a.lex.lingue:
            a.lingua = lingua
            detti = []
            a._pubblica = detti.append
            a._manda_lingua()
            m = detti[-1]
            assert m["motto"].strip(), lingua
            assert len(m["passi"]) == 3
            assert all(p["titolo"].strip() and p["spiega"].strip() for p in m["passi"]), lingua
    finally:
        a.matcher.chiudi()
        a.narratore.chiudi()


def test_nessuna_goccia_rimasta():
    """La goccia rossa si leggeva come sangue: il motivo e' il calice. Il
    colore della goccia non deve sopravvivere in nessuna delle due pagine."""
    avvio = (RADICE / "src/amelie/ui/static/avvio.html").read_text(encoding="utf-8")
    for testo in (PAGINA, avvio):
        assert "--goccia" not in testo and 'class="goccia"' not in testo


def test_le_proposte_stanno_al_posto_della_descrizione():
    """Mentre si scrive il titolo le bottiglie si scelgono dove c'e' la
    descrizione, cinque per volta, e l'ultima casella e' «Nessuna di queste»."""
    colonna = re.search(r'<div id="k-colonna">(.*?)</div>\s*</div>', PAGINA, re.S).group(1)
    assert 'id="k-descrizione"' in colonna and 'id="k-proposte"' in colonna
    assert "const PER_PAGINA = 5;" in PAGINA
    pagina = re.search(r"function disegnaPagina\(\) \{(.*?)\n\}", PAGINA, re.S).group(1)
    assert "nessuna_di_queste" in pagina and "paginaProposte++" in pagina
