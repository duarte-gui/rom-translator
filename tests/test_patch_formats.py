"""Round-trip dos formatos de patch.

A propriedade que importa: create(A, B) seguido de apply(A, ...) tem que
devolver B byte a byte, para qualquer par de arquivos.
"""

import random

import pytest

from rom_translator.core.patch import apply_bps, apply_ips, create_bps, create_ips, detect_format
from rom_translator.core.patch.bps import ChecksumMismatch, decode_varint, encode_varint
from rom_translator.core.patch.ips import EOF_OFFSET


def _random_pair(rng: random.Random) -> tuple[bytes, bytes]:
    source = bytes(rng.randrange(256) for _ in range(rng.randint(0, 4000)))
    target = bytearray(source)
    for _ in range(rng.randint(0, 8)):
        if not target:
            break
        pos = rng.randrange(len(target))
        length = rng.randint(1, 50)
        target[pos : pos + length] = bytes(
            rng.randrange(4) for _ in range(min(length, len(target) - pos))
        )
    if rng.random() < 0.3:  # ROM expandida
        target.extend(b"\xff" * rng.randint(1, 300))
    if rng.random() < 0.2 and target:  # ROM truncada
        del target[rng.randrange(len(target)) :]
    return source, bytes(target)


@pytest.mark.parametrize("seed", range(60))
def test_ips_roundtrip(seed):
    source, target = _random_pair(random.Random(seed))
    assert apply_ips(source, create_ips(source, target)) == target


@pytest.mark.parametrize("seed", range(60))
def test_bps_roundtrip(seed):
    source, target = _random_pair(random.Random(seed))
    assert apply_bps(source, create_bps(source, target)) == target


def test_ips_offset_that_collides_with_eof_marker():
    """Um registro em 0x454F46 seria lido como o marcador 'EOF'."""
    source = bytes(0x460000)
    target = bytearray(source)
    target[EOF_OFFSET - 6 : EOF_OFFSET + 10] = b"X" * 16
    target = bytes(target)
    assert apply_ips(source, create_ips(source, target)) == target


def test_ips_rle_compresses_long_runs():
    source = bytes(70000)
    target = b"\xaa" * 70000
    patch = create_ips(source, target)
    assert len(patch) < 200, "trecho constante deveria virar registros RLE"
    assert apply_ips(source, patch) == target


def test_ips_truncation():
    source = bytes(range(256)) * 4
    target = source[:500]
    assert apply_ips(source, create_ips(source, target)) == target


def test_bps_rejects_wrong_source_rom():
    source, target = _random_pair(random.Random(7))
    patch = create_bps(source, target)
    with pytest.raises(ChecksumMismatch):
        apply_bps(source + b"\x00", patch)


def test_bps_rejects_corrupted_patch():
    source, target = _random_pair(random.Random(9))
    patch = bytearray(create_bps(source, target))
    patch[20] ^= 0xFF
    with pytest.raises(ChecksumMismatch):
        apply_bps(source, bytes(patch))


@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 16383, 16384, 1 << 30])
def test_varint_roundtrip(value):
    decoded, pos = decode_varint(encode_varint(value), 0)
    assert decoded == value
    assert pos == len(encode_varint(value))


def test_detect_format():
    assert detect_format(b"PATCHfoo") == "ips"
    assert detect_format(b"BPS1foo") == "bps"
    assert detect_format(b"UPS1foo") == "ups"
    assert detect_format(b"nada") == "unknown"
