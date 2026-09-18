"""Quello che vale per tutti i test.

Per ora una cosa sola, e viene da un errore vero: la suite girata sulla board
ha lasciato le proprie scansioni nel giornale di bordo del dispositivo. Aprendolo
per capire perché una bottiglia non era stata riconosciuta, dentro c'erano
racconti di prova — «x.» — insieme a quelli veri.

Un test non deve scrivere nel `var` del progetto, e nemmeno trovarci quello di
ieri. Qui si sposta la cartella del giornale in una tutta sua, diversa a ogni
test, **prima** che qualcuno costruisca un `Amelie`: la costanti la legge il
costruttore, e spostarla dopo non sposterebbe niente.
"""

import pytest


@pytest.fixture(autouse=True)
def giornale_in_disparte(tmp_path, monkeypatch):
    try:
        from amelie import app
    except ImportError:          # pragma: no cover - dipende dall'ambiente
        # Senza le dipendenze del dispositivo (cv2, fastapi) `amelie.app` non
        # si importa, e i test che non lo usano devono girare lo stesso.
        return
    monkeypatch.setattr(app, "CARTELLA_GIORNALE", tmp_path / "scansioni")
