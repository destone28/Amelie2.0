"""Quello che vale per tutti i test.

Una cosa sola: la suite non tocca il giornale di bordo del dispositivo. Girata
sulla board, lascerebbe le proprie scansioni accanto a quelle vere, e chi apre
il giornale per capire perché una bottiglia non è stata riconosciuta ci
troverebbe racconti di prova — «x.» — mescolati a quelli dell'ospite.

Un test non deve scrivere nel `var` del progetto, e nemmeno trovarci quello di
un'esecuzione precedente. Qui si sposta la cartella del giornale in una tutta
sua, diversa a ogni test, **prima** che qualcuno costruisca un `Amelie`: la
costante la legge il costruttore, e spostarla dopo non sposterebbe niente.
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
