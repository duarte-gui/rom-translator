"""Container de ROM: header de copiadora e hashes."""

from rom_translator.core.rom import Rom


def test_strips_512_byte_copier_header(tmp_path):
    payload = bytes(range(256)) * 1024  # 256 KiB
    path = tmp_path / "game.smc"
    path.write_bytes(b"\xaa" * 512 + payload)

    rom = Rom.load(path)
    assert rom.size == len(payload)
    assert rom.copier_header == b"\xaa" * 512
    assert bytes(rom.data) == payload


def test_keeps_file_without_copier_header(tmp_path):
    payload = bytes(range(256)) * 1024
    path = tmp_path / "game.sfc"
    path.write_bytes(payload)

    rom = Rom.load(path)
    assert rom.copier_header == b""
    assert rom.size == len(payload)


def test_save_restores_copier_header(tmp_path):
    original = tmp_path / "in.smc"
    original.write_bytes(b"\xaa" * 512 + bytes(1024))
    out = tmp_path / "out.smc"

    Rom.load(original).save(out)
    assert out.read_bytes() == original.read_bytes()


def test_write_extends_rom():
    rom = Rom.from_bytes(bytes(16))
    rom.write(20, b"abc")
    assert rom.size == 23
    assert rom.read(20, 3) == b"abc"


def test_hashes_are_stable():
    rom = Rom.from_bytes(b"chrono")
    assert rom.hashes()["crc32"] == f"{rom.crc32():08x}"
    assert len(rom.hashes()["sha1"]) == 40


def test_expand_doubles_to_the_next_power_of_two():
    rom = Rom.from_bytes(bytes(0x180000))
    start, end = rom.expand()
    assert (start, end) == (0x180000, 0x200000)
    assert rom.size == 0x200000
    assert bytes(rom.data[0x180000:]) == bytes(0x80000)


def test_expand_accepts_an_explicit_size():
    rom = Rom.from_bytes(bytes(100))
    assert rom.expand(size=256, filler=0xFF) == (100, 256)
    assert bytes(rom.data[100:]) == b"\xff" * 156


def test_expand_refuses_to_shrink():
    import pytest

    rom = Rom.from_bytes(bytes(256))
    with pytest.raises(ValueError, match="precisa passar de"):
        rom.expand(size=128)


def test_expanded_area_is_seen_as_free_space():
    from rom_translator.core.space import find_free_space

    rom = Rom.from_bytes(b"\xaa" * 0x1000)
    rom.expand(size=0x2000)
    regions = find_free_space(bytes(rom.data), min_run=0x100)
    assert any(r.start == 0x1000 and r.end == 0x2000 for r in regions)
