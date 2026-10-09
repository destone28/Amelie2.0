"""La cache della voce: una frase rovinata si rifa', non si salta.

Il dispositivo si spegne togliendo corrente. Una frase scritta in cache pochi
secondi prima puo' restare, al riavvio, un file vuoto; letta come buona, `parla`
la saltava in silenzio, per sempre. E' successo all'annuncio della lingua:
«Lingua italiana.» non si sentiva piu', e restava solo la frase dopo.
"""
from __future__ import annotations

import os

import pytest

from amelie import speech
from amelie.speech import ImpostazioniVoce, Voce

PCM = b"\x11\x22" * 100


class _Pezzo:
    def __init__(self, dati: bytes) -> None:
        self.audio_int16_bytes = dati


class _MotoreFinto:
    """Il motore di sintesi, ridotto a quello che conta qui: quante volte lavora."""

    def __init__(self) -> None:
        self.sintesi: list[str] = []

    def synthesize(self, frase: str):
        self.sintesi.append(frase)
        return [_Pezzo(PCM)]


@pytest.fixture
def voce(monkeypatch):
    v = Voce(ImpostazioniVoce())
    motore = _MotoreFinto()
    monkeypatch.setattr(v, "_carica", lambda modello=None: motore)
    return v, motore


def _unico_file(v: Voce):
    file = list(v.cache.glob("*.raw"))
    assert len(file) == 1, file
    return file[0]


class TestUnaFraseRovinataSiRifa:
    def test_una_frase_sana_si_legge_dalla_cache(self, voce):
        v, motore = voce
        assert v.sintetizza("Lingua italiana.") == PCM
        assert v.sintetizza("Lingua italiana.") == PCM
        assert len(motore.sintesi) == 1

    def test_un_file_vuoto_non_e_una_frase(self, voce):
        """Il caso trovato sul dispositivo: il file c'e' ed e' lungo zero."""
        v, motore = voce
        v.sintetizza("Lingua italiana.")
        _unico_file(v).write_bytes(b"")
        assert v.sintetizza("Lingua italiana.") == PCM, "la frase si e' persa"
        assert len(motore.sintesi) == 2
        assert _unico_file(v).read_bytes() == PCM, "il file rovinato e' rimasto"

    def test_un_file_di_lunghezza_dispari_neppure(self, voce):
        """Campioni da 16 bit: un byte dispari e' un file troncato a meta'."""
        v, motore = voce
        v.sintetizza("Lingua italiana.")
        _unico_file(v).write_bytes(b"\x11\x22\x33")
        assert v.sintetizza("Lingua italiana.") == PCM
        assert len(motore.sintesi) == 2

    def test_la_scrittura_arriva_sul_disco(self, voce, monkeypatch):
        """Un fsync per il contenuto e uno per la cartella: e' cio' che rende
        durevole il nome nuovo, se la corrente salta subito dopo."""
        v, _ = voce
        sincronizzati = []
        vero = os.fsync
        monkeypatch.setattr(os, "fsync", lambda fd: (sincronizzati.append(fd), vero(fd)))
        v.sintetizza("Lingua italiana.")
        assert len(sincronizzati) >= 2
        assert not list(v.cache.glob("*.parziale")), "e' rimasto il file temporaneo"

    def test_una_cache_che_non_si_scrive_non_ferma_la_voce(self, voce, monkeypatch):
        v, _ = voce

        def disco_pieno(percorso, dati):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(speech, "scrivi_durevole", disco_pieno)
        assert v.sintetizza("Lingua italiana.") == PCM


class TestAllAvvioLaCacheSiRipara:
    def test_si_tolgono_i_file_rovinati_e_restano_quelli_sani(self):
        cartella = speech.CARTELLA_CACHE
        cartella.mkdir(parents=True)
        (cartella / "sana.raw").write_bytes(PCM)
        (cartella / "vuota.raw").write_bytes(b"")
        (cartella / "dispari.raw").write_bytes(b"\x01\x02\x03")
        (cartella / "a-meta.parziale").write_bytes(PCM)

        v = Voce(ImpostazioniVoce())

        assert sorted(p.name for p in v.cache.iterdir()) == ["sana.raw"]
        assert v.ripara_cache() == 0, "la seconda volta non c'e' piu' niente"
