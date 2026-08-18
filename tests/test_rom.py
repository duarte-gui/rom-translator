"""Container de ROM: header de copiadora e hashes."""

from romtrans.core.rom import Rom


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
