"""Tabela de caracteres: parsing, DTE/MTE e a invariante de round-trip."""

import pytest

from rom_translator.core.table import Table, TableError, ascii_table

SAMPLE = """
# tabela de exemplo
20= 
41=A
42=B
43=C
2A=th
2B=the
1234=q
/00=[END]
*01=[LINE]
"""


def test_parses_all_entry_kinds():
    table = Table.parse(SAMPLE)
    assert table.entries[b"\x41"] == "A"
    assert table.entries[b"\x20"] == " "
    assert table.entries[b"\x2a"] == "th"  # DTE
    assert table.entries[b"\x12\x34"] == "q"  # chave multibyte
    assert b"\x00" in table.end_tokens
    assert b"\x01" in table.line_tokens


def test_decode_stops_at_end_token():
    table = Table.parse(SAMPLE)
    result = table.decode(b"\x41\x42\x00\x43")
    assert result.text == "AB[END]"
    assert result.consumed == 3
    assert result.terminated is True


def test_decode_prefers_longest_byte_match():
    table = Table.parse(SAMPLE)
    assert table.decode(b"\x12\x34\x00").text == "q[END]"


def test_encode_prefers_longest_text_match_using_mte():
    table = Table.parse(SAMPLE)
    # "the" existe como MTE de 1 byte; nao deve virar "th"+"e"
    assert table.encode("the") == b"\x2b"


def test_unmapped_byte_survives_roundtrip():
    """A invariante que sustenta o round-trip byte-identico do M2."""
    table = Table.parse(SAMPLE)
    raw = b"\x41\xf7\x42\xee\x00"
    decoded = table.decode(raw)
    assert "[$F7]" in decoded.text
    assert table.encode(decoded.text) == raw


@pytest.mark.parametrize(
    "raw",
    [b"\x41\x42\x43", b"\x2a\x2b\x20\x41", b"\x12\x34\x41", b"\xff\xfe\xfd", b""],
)
def test_decode_encode_is_lossless(raw):
    table = Table.parse(SAMPLE)
    decoded = table.decode(raw, stop_at_end=False)
    assert table.encode(decoded.text) == raw


def test_decode_respects_max_bytes():
    table = Table.parse(SAMPLE)
    result = table.decode(b"\x41\x42\x43\x00", max_bytes=2)
    assert result.text == "AB"
    assert result.terminated is False


def test_encode_rejects_unknown_character():
    table = Table.parse(SAMPLE)
    with pytest.raises(TableError, match="nao existe na tabela"):
        table.encode("Z")


def test_dumps_roundtrips_through_parse():
    table = Table.parse(SAMPLE)
    again = Table.parse(table.dumps())
    assert again.entries == table.entries
    assert again.end_tokens == table.end_tokens
    assert again.line_tokens == table.line_tokens


def test_rejects_odd_length_hex():
    with pytest.raises(TableError, match="hexadecimal par"):
        Table.parse("4=A")


def test_shortest_sequence_wins_on_duplicate_values():
    table = Table.parse("41=A\n0041=A\n")
    assert table.encode("A") == b"\x41"


def test_ascii_table_roundtrip():
    table = ascii_table()
    raw = b"Chrono Trigger\x00"
    assert table.decode(raw).text == "Chrono Trigger[END]"
    assert table.encode("Chrono Trigger[END]") == raw


def test_letter_bytes_excludes_control_tokens():
    table = Table.parse(SAMPLE)
    assert 0x41 in table.letter_bytes
    assert 0x00 not in table.letter_bytes
