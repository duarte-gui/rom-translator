"""Descoberta de tabelas de ponteiros."""

from rom_translator.core.pointers import find_pointers, rewrite
from rom_translator.platforms import identify
from rom_translator.platforms.base import PointerSpec
from tests.test_platforms import _fake_snes


def _rom_with_pointer_table(count: int = 12):
    """ROM sintetica: strings em offsets conhecidos e uma tabela apontando pra elas."""
    data = bytearray(_fake_snes("hirom", 0x100000))
    plugin, det = identify(bytes(data))
    spec = PointerSpec("ptr16", width=2, endian="little")

    # deslocados de 0x100 de proposito: um alvo cujo ponteiro fosse 0x0000
    # casaria com todo o preenchimento zerado da ROM
    targets = [0x20100 + i * 0x40 for i in range(count)]
    table_at = 0x30000
    for index, target in enumerate(targets):
        data[target : target + 5] = b"TEXT\x00"
        cpu = plugin.file_to_cpu(target, det)
        data[table_at + index * 2 : table_at + index * 2 + 2] = spec.encode(cpu)
    return bytes(data), plugin, det, spec, targets, table_at


def test_finds_a_real_pointer_table():
    data, plugin, det, spec, targets, table_at = _rom_with_pointer_table()
    tables = find_pointers(data, {t: f"u{i}" for i, t in enumerate(targets)},
                           plugin, det, spec, min_run=8)
    assert tables, "nao achou a tabela"
    found = max(tables, key=lambda t: t.count)
    assert found.offset == table_at
    assert found.count == len(targets)


def test_rejects_a_run_shorter_than_min_run():
    data, plugin, det, spec, targets, _ = _rom_with_pointer_table(count=12)
    tables = find_pointers(data, {t: "u" for t in targets}, plugin, det, spec, min_run=20)
    assert tables == [], "uma tabela de 12 nao pode passar por min_run=20"


def test_rewrite_updates_only_moved_targets():
    data, plugin, det, spec, targets, table_at = _rom_with_pointer_table()
    tables = find_pointers(data, {t: "u" for t in targets}, plugin, det, spec, min_run=8)
    buffer = bytearray(data)
    moved = {targets[0]: targets[0] + 0x10}
    assert rewrite(buffer, tables, moved, plugin, det) == 1
    new_cpu = plugin.file_to_cpu(targets[0] + 0x10, det)
    assert bytes(buffer[table_at : table_at + 2]) == spec.encode(new_cpu)
    # os demais ponteiros ficaram intactos
    assert bytes(buffer[table_at + 2 :]) == data[table_at + 2 :]
