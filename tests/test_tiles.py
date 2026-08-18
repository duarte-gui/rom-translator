"""Tiles de fonte e composicao de letras acentuadas."""

import numpy as np
import pytest

from rom_translator.core.tiles import (
    ACCENTS,
    NoRoomForDiacritic,
    add_diacritic,
    background_of,
    decode_tile,
    encode_tile,
    find_free_tiles,
    ink_of,
    render,
)


def _glyph(rows: list[str], ink: int = 3, background: int = 0) -> np.ndarray:
    tile = np.full((8, 8), background, dtype=np.uint8)
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                tile[y, x] = ink
    return tile


LETRA_BAIXA = _glyph(["", "", "  ####  ", " #    # ", " ###### ", " #    # ", " #    # ", ""])
LETRA_ALTA = _glyph([" #      ", " #      ", " #####  ", " #    # ", " #    # ", " #    # ",
                     " #####  ", " #      "])


@pytest.mark.parametrize("fmt", ["nes2bpp", "snes2bpp", "snes4bpp"])
def test_tile_encoding_roundtrips(fmt):
    tile = _glyph(["#  #  # ", " #  #  #", "###  ###", "  ####  ",
                   "# #  # #", " ## ##  ", "#      #", "  #  #  "], ink=1)
    raw = encode_tile(tile, fmt)
    assert np.array_equal(decode_tile(raw, 0, fmt), tile)


def test_snes4bpp_carries_four_bits_per_pixel():
    tile = np.zeros((8, 8), dtype=np.uint8)
    tile[0, 0] = 15
    assert np.array_equal(decode_tile(encode_tile(tile, "snes4bpp"), 0, "snes4bpp"), tile)


def test_background_and_ink_do_not_assume_zero():
    """A fonte do Dragon Warrior desenha sobre a cor 2, nao sobre a 0."""
    tile = _glyph(["", "  ####  ", " #    # ", " ###### ", " #    # ", " #    # ", "", ""],
                  ink=3, background=2)
    assert background_of(tile) == 2
    assert ink_of(tile) == 3


def test_ink_is_the_stroke_not_the_outline():
    """Numa fonte com contorno, a cor mais frequente que nao e fundo e o contorno."""
    tile = _glyph(["", " ###### ", " #    # ", " ###### ", "", "", "", ""], ink=3, background=0)
    tile[tile == 0] = 0
    tile[2, 1] = tile[2, 6] = 1  # contorno espalhado
    for row in range(8):
        for column in range(8):
            if tile[row, column] == 0 and row < 6:
                tile[row, column] = 1
    assert ink_of(tile) == 3


def test_adds_a_tilde_above_a_low_glyph():
    resultado = add_diacritic(LETRA_BAIXA, "tilde")
    assert (resultado[0] != 0).any(), "a marca deveria estar na linha de cima"
    assert np.array_equal(resultado[2:], LETRA_BAIXA[2:]), "o glifo nao devia mudar"


def test_shifts_the_glyph_down_when_the_top_row_is_taken():
    glifo = _glyph(["  ####  ", " #    # ", " ###### ", " #    # ", " #    # ", "", "", ""])
    resultado = add_diacritic(glifo, "acute")
    assert (resultado[0] != 0).any()
    assert np.array_equal(resultado[2:6], glifo[1:5]), "o corpo devia ter descido uma linha"


def test_refuses_when_there_is_no_room():
    with pytest.raises(NoRoomForDiacritic, match="sem linha livre"):
        add_diacritic(LETRA_ALTA, "tilde")


def test_cedilla_goes_below_and_needs_the_bottom_row():
    resultado = add_diacritic(LETRA_BAIXA, "cedilla")
    assert (resultado[7] != 0).any()
    cheio = _glyph(["", "  ####  ", " #    # ", " ###### ", " #    # ", " #    # ",
                    " ###### ", " #    # "])
    with pytest.raises(NoRoomForDiacritic, match="cedilha"):
        add_diacritic(cheio, "cedilla")


def test_refuses_an_empty_tile():
    with pytest.raises(NoRoomForDiacritic):
        add_diacritic(np.zeros((8, 8), dtype=np.uint8), "tilde")


def test_every_portuguese_accent_maps_to_a_base_letter():
    for acentuada, (base, mark) in ACCENTS.items():
        assert len(base) == 1 and base.isalpha()
        assert mark == "cedilla" or mark in {
            "tilde", "acute", "grave", "circumflex", "diaeresis"
        }


def test_find_free_tiles_skips_used_indexes():
    data = encode_tile(LETRA_BAIXA, "nes2bpp") + bytes(16) + bytes(16)
    assert find_free_tiles(data, 0, 3, "nes2bpp", used=set()) == [1, 2]
    assert find_free_tiles(data, 0, 3, "nes2bpp", used={1}) == [2]


def test_render_draws_something_readable():
    saida = render(LETRA_BAIXA)
    assert len(saida.split("\n")) == 8
    assert "#" in saida and " " in saida
