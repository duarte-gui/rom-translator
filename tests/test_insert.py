"""Reinsercao: cabe, sobra, ou nao entra."""

from rom_translator.core.insert import insert, verify_roundtrip
from rom_translator.core.rom import Rom
from rom_translator.core.script import Script, Unit
from rom_translator.core.table import ascii_table


def _script(*units):
    return Script(units=list(units))


def test_translation_that_fits_is_written():
    rom = Rom.from_bytes(b"Sword      ")
    unit = Unit(id="u", offset=0, length=11, text="Sword      ", max_len=11)
    unit.translation = "Espada"
    report = insert(rom, _script(unit), ascii_table(end_byte=None))
    assert report.written == 1
    assert bytes(rom.data) == b"Espada     ", "sobra deveria virar espaco"


def test_translation_that_overflows_is_refused_not_truncated():
    """Escrever alem do limite corromperia a string seguinte, em silencio."""
    rom = Rom.from_bytes(b"Sword ")
    unit = Unit(id="u", offset=0, length=6, text="Sword ", max_len=6)
    unit.translation = "Espada Longa"
    report = insert(rom, _script(unit), ascii_table(end_byte=None))
    assert report.written == 0
    assert report.overflow and report.overflow[0][1] == 12
    assert bytes(rom.data) == b"Sword ", "a ROM nao pode ter sido tocada"


def test_untranslated_units_are_left_alone():
    rom = Rom.from_bytes(b"Sword ")
    unit = Unit(id="u", offset=0, length=6, text="Sword ", max_len=6)
    report = insert(rom, _script(unit), ascii_table(end_byte=None))
    assert report.skipped_untranslated == 1
    assert bytes(rom.data) == b"Sword "


def test_untranslatable_character_is_reported():
    rom = Rom.from_bytes(b"Sword ")
    unit = Unit(id="u", offset=0, length=6, text="Sword ", max_len=6)
    unit.translation = "Espadão"  # 'ã' nao existe na tabela ASCII
    report = insert(rom, _script(unit), ascii_table(end_byte=None))
    assert report.written == 0 and report.failed
    assert "nao existe na tabela" in report.failed[0][1]


def test_verify_roundtrip_accepts_a_faithful_dump():
    rom = Rom.from_bytes(b"Chrono Trigger")
    unit = Unit(id="u", offset=0, length=14, text="Chrono Trigger", max_len=14)
    assert verify_roundtrip(rom, _script(unit), ascii_table(end_byte=None)) == []


def test_verify_roundtrip_catches_a_lossy_dump():
    rom = Rom.from_bytes(b"Chrono Trigger")
    unit = Unit(id="u", offset=0, length=14, text="Chrono Triggr", max_len=14)
    assert len(verify_roundtrip(rom, _script(unit), ascii_table(end_byte=None))) == 1
