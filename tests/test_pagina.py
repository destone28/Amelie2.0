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
        if composto:
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
