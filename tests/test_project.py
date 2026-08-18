"""Projeto, blocos e extracao de unidades."""

import pytest

from romtrans.core.rom import Rom
from romtrans.core.script import Script, Unit
from romtrans.core.table import ascii_table
from romtrans.project import Block, Project


def test_fixed_block_splits_into_equal_entries():
    data = b"Slash      Flea       Dalton     "
    units = Block(id="inimigos", start=0, end=33, kind="fixed", entry_size=11).extract(
        data, ascii_table()
    )
    assert [u.text.strip() for u in units] == ["Slash", "Flea", "Dalton"]
    assert all(u.max_len == 11 for u in units)


def test_fixed_block_requires_entry_size():
    with pytest.raises(ValueError, match="entry_size"):
        Block(id="x", start=0, end=10, kind="fixed").extract(b"abc", ascii_table())


def test_terminated_block_splits_on_end_token():
    data = b"Crono\x00Marle\x00Lucca\x00"
    units = Block(id="nomes", start=0, end=len(data), kind="terminated").extract(
        data, ascii_table()
    )
    assert [u.text for u in units] == ["Crono[END]", "Marle[END]", "Lucca[END]"]
    assert units[1].offset == 6


def test_greedy_block_ignores_unmapped_bytes():
    data = b"\x01\x02Chrono Trigger\xff\xfeMarle\x03"
    units = Block(id="b", start=0, end=len(data), kind="greedy", min_run=4).extract(
        data, ascii_table()
    )
    assert [u.text for u in units] == ["Chrono Trigger", "Marle"]
    assert units[0].offset == 2


def test_greedy_block_respects_min_run():
    data = b"\x00abc\x00Chrono\x00"
    units = Block(id="b", start=0, end=len(data), kind="greedy", min_run=5).extract(
        data, ascii_table()
    )
    assert [u.text for u in units] == ["Chrono"]


def test_unit_offsets_point_back_at_the_original_bytes():
    """O que sustenta o round-trip do M2: cada unidade sabe de onde veio."""
    data = b"\x00Guardia\x00\x00Zeal Kingdom\x00"
    table = ascii_table(end_byte=None)
    units = Block(id="b", start=0, end=len(data), kind="greedy").extract(data, table)
    for unit in units:
        assert table.encode(unit.text) == data[unit.offset : unit.offset + unit.length]


def test_project_roundtrips_through_yaml(tmp_path):
    project = Project(
        rom_path="jogo.smc", rom_sha1="abc", platform="snes", mapper="hirom",
        table_path="jogo.tbl",
        blocks=[
            Block(id="b000", start=0x1000, end=0x2000, kind="greedy", min_run=5, score=0.87),
            Block(id="itens", start=0xC000, end=0xC100, kind="fixed", entry_size=11),
        ],
    )
    path = project.save(tmp_path / "p.yaml")
    again = Project.load(path)
    assert again.rom_sha1 == "abc"
    assert again.blocks[0].start == 0x1000
    assert again.blocks[0].min_run == 5
    assert again.blocks[1].entry_size == 11
    assert "0x001000" in path.read_text()  # offsets legiveis em hex


def test_project_dump_collects_all_blocks(tmp_path):
    rom = Rom.from_bytes(b"\x00Crono\x00\x00\x00Marle Queen\x00")
    project = Project(
        blocks=[Block(id="a", start=0, end=8, kind="greedy"),
                Block(id="b", start=8, end=22, kind="greedy")]
    )
    script = project.dump(rom, ascii_table(end_byte=None))
    assert [u.text for u in script.units] == ["Crono", "Marle Queen"]
    assert script.rom_sha1 == rom.sha1()


def test_script_roundtrips_through_json(tmp_path):
    script = Script(
        rom_sha1="deadbeef", table="x.tbl",
        units=[Unit(id="a/0", offset=16, length=5, text="Crono", max_len=5, block="a")],
    )
    path = script.save(tmp_path / "s.json")
    again = Script.load(path)
    assert again.units[0].text == "Crono"
    assert again.units[0].offset == 16
    assert again.rom_sha1 == "deadbeef"
    assert again.stats() == {"unidades": 1, "traduzidas": 0, "caracteres": 5}


def test_script_rejects_unknown_version(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"version": 99, "units": []}')
    with pytest.raises(ValueError, match="versao"):
        Script.load(path)
