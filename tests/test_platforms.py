"""Deteccao de plataforma e conversao de enderecos."""

import pytest

from romtrans import platforms
from romtrans.platforms.snes import checksum_valid, compute_checksum, fix_checksum


def _fake_snes(mapper: str = "hirom", size: int = 0x100000) -> bytes:
    base = {"lorom": 0x7FC0, "hirom": 0xFFC0}[mapper]
    data = bytearray(size)
    data[base : base + 21] = b"FAKE GAME".ljust(21, b" ")
    data[base + 0x15] = {"lorom": 0x20, "hirom": 0x21}[mapper]
    data[base + 0x17] = (size // 1024).bit_length() - 1
    data[base + 0x3C : base + 0x3E] = (0x8000).to_bytes(2, "little")
    fix_checksum(data, base)
    return bytes(data)


@pytest.mark.parametrize("mapper", ["lorom", "hirom"])
def test_detects_snes_mapper(mapper):
    plugin, det = platforms.identify(_fake_snes(mapper))
    assert plugin.name == "snes"
    assert det.mapper == mapper
    assert det.title == "FAKE GAME"


def test_snes_lorom_address_roundtrip():
    plugin, det = platforms.identify(_fake_snes("lorom"))
    for offset in (0, 0x7FFF, 0x8000, 0x1234, 0xFFFFF):
        cpu = plugin.file_to_cpu(offset, det)
        assert plugin.cpu_to_file(cpu, det) == offset


def test_snes_hirom_address_roundtrip():
    plugin, det = platforms.identify(_fake_snes("hirom"))
    for offset in (0, 0xFFFF, 0x10000, 0xABCDE):
        cpu = plugin.file_to_cpu(offset, det)
        assert plugin.cpu_to_file(cpu, det) == offset


def test_snes_lorom_rejects_ram_addresses():
    plugin, det = platforms.identify(_fake_snes("lorom"))
    assert plugin.cpu_to_file(0x7E0000, det) is None  # WRAM


def test_snes_checksum_helpers():
    data = bytearray(_fake_snes("hirom"))
    assert checksum_valid(bytes(data), 0xFFC0)
    data[0x1000] ^= 0xFF
    assert not checksum_valid(bytes(data), 0xFFC0)
    fix_checksum(data, 0xFFC0)
    assert checksum_valid(bytes(data), 0xFFC0)


def test_detects_nes():
    data = bytearray(b"NES\x1a\x02\x01\x00\x00" + bytes(8) + bytes(0x8000))
    plugin, det = platforms.identify(bytes(data))
    assert plugin.name == "nes"
    assert det.details["prg_size"] == 32768
    assert det.details["prg_offset"] == 16


def test_detects_gba():
    data = bytearray(0x200)
    data[0x04:0x08] = b"\x24\xff\xae\x51"
    data[0xA0:0xAC] = b"FAKE GBA   \x00"
    data[0xB2] = 0x96
    plugin, det = platforms.identify(bytes(data))
    assert plugin.name == "gba"
    assert plugin.cpu_to_file(0x08001234, det) == 0x1234
    assert plugin.cpu_to_file(0x02000000, det) is None  # EWRAM, nao e ROM


def test_falls_back_to_generic():
    plugin, det = platforms.identify(b"\x00" * 1024)
    assert plugin.name == "generic"
    assert det.confidence < 0.1


def test_compute_checksum_mirrors_non_power_of_two():
    # 6 Mbit: 4 MiB + 2 MiB espelhado -- so precisa nao explodir e ser estavel
    data = bytes(range(256)) * (0x600000 // 256)
    assert 0 <= compute_checksum(data) <= 0xFFFF
