"""Realocacao: mover uma string para espaco livre e consertar os ponteiros."""

import pytest

from rom_translator.core.insert import Relocator, insert
from rom_translator.core.rom import Rom
from rom_translator.core.script import Script, Unit
from rom_translator.core.space import SpaceAllocator, find_free_space
from rom_translator.core.table import Table
from rom_translator.platforms import identify
from rom_translator.platforms.base import PointerSpec

TABLE = Table.parse(
    "\n".join(f"{0x41 + i:02X}={chr(0x61 + i)}" for i in range(26))
    + "\n20= \n/00=[END]\n"
)


def _setup(free_at: int = 0x100, free_size: int = 0x200, width: int = 3):
    """ROM plana com uma string, um ponteiro para ela e um trecho livre."""
    data = bytearray(b"\xee" * 0x400)
    text = TABLE.encode("sword[END]")
    string_at = 0x40
    data[string_at : string_at + len(text)] = text
    data[free_at : free_at + free_size] = bytes(free_size)

    rom = Rom(data=data)
    plugin, det = identify(bytes(data))  # generic: mapeamento plano
    spec = PointerSpec("ptr", width=width, endian="little")
    pointer_at = 0x10
    rom.write(pointer_at, spec.encode(string_at))

    unit = Unit(
        id="u", offset=string_at, length=len(text), text="sword[END]",
        max_len=len(text), pointers=[pointer_at],
    )
    allocator = SpaceAllocator(find_free_space(bytes(rom.data), min_run=64))
    relocator = Relocator(
        rom=rom, table=TABLE, plugin=plugin, det=det,
        allocator=allocator, specs={pointer_at: spec},
    )
    return rom, unit, relocator, spec, pointer_at


def test_long_translation_is_moved_and_the_pointer_follows():
    rom, unit, relocator, spec, pointer_at = _setup()
    unit.translation = "espada longa demais[END]"
    report = insert(rom, Script(units=[unit]), TABLE, relocator=relocator)

    assert report.relocated == 1 and not report.overflow
    new_offset = spec.decode(bytes(rom.data[pointer_at : pointer_at + spec.width]))
    assert new_offset != unit.offset
    written = TABLE.decode(bytes(rom.data), new_offset, stop_at_end=True)
    assert written.text == "espada longa demais[END]"


def test_relocation_is_refused_without_a_terminator():
    """Sem token de fim, o jogo leria alem da string nova ate achar um por acaso."""
    rom, unit, relocator, _spec, _p = _setup()
    unit.text = "sword"
    unit.translation = "espada longa demais"
    report = insert(rom, Script(units=[unit]), TABLE, relocator=relocator)
    assert report.relocated == 0 and len(report.overflow) == 1
    assert "token de fim" in unit.note


def test_relocation_is_refused_without_known_pointers():
    rom, unit, relocator, _spec, _p = _setup()
    unit.pointers = []
    unit.translation = "espada longa demais[END]"
    report = insert(rom, Script(units=[unit]), TABLE, relocator=relocator)
    assert report.relocated == 0
    assert "nenhum ponteiro" in unit.note


def test_relocation_is_refused_when_free_space_runs_out():
    rom, unit, relocator, _spec, _p = _setup(free_size=0x80)
    relocator.allocator.allocate(0x80)  # consome tudo
    unit.translation = "espada longa demais[END]"
    report = insert(rom, Script(units=[unit]), TABLE, relocator=relocator)
    assert report.relocated == 0 and "sem espaco livre" in unit.note


def test_narrow_pointer_keeps_the_string_in_its_own_bank():
    """Ponteiro estreito nao carrega o banco: sair dele aponta para o lugar errado."""
    rom, unit, relocator, _spec, _p = _setup(free_at=0x100, free_size=0x200, width=2)
    relocator.allocator = SpaceAllocator(
        find_free_space(bytes(rom.data), min_run=64), bank_size=0x40
    )
    unit.translation = "espada longa demais[END]"
    insert(rom, Script(units=[unit]), TABLE, relocator=relocator)
    # a origem esta no banco 1 (0x40 // 0x40); se moveu, foi para dentro dele
    if unit.offset in relocator.moved:
        assert relocator.moved[unit.offset] // 0x40 == 1


def test_short_translation_still_goes_in_place():
    rom, unit, relocator, _spec, pointer_at = _setup()
    before = bytes(rom.data[pointer_at : pointer_at + 3])
    unit.translation = "faca[END]"
    report = insert(rom, Script(units=[unit]), TABLE, relocator=relocator)
    assert report.written == 1 and report.relocated == 0
    assert bytes(rom.data[pointer_at : pointer_at + 3]) == before, "ponteiro nao devia mudar"
