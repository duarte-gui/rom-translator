"""Leitura e escrita dos tiles de fonte, e composicao de letras acentuadas.

Traduzir para portugues esbarra numa parede que nao e de software: a fonte da ROM
nao tem `a`, `c` nem `o`. Nenhum ajuste de tabela resolve -- o desenho da letra
precisa existir nos graficos.

Da para desenhar. Uma minuscula de 8x8 quase sempre ocupa as linhas de baixo e
deixa as duas de cima vazias, que e onde o til e o acento cabem. Quando nao
sobra espaco, isto avisa em vez de estragar o glifo.
"""

from __future__ import annotations

import numpy as np

#: bytes por tile em cada formato
TILE_BYTES = {"nes2bpp": 16, "snes2bpp": 16, "snes4bpp": 32}


def decode_tile(data: bytes, offset: int, fmt: str = "nes2bpp") -> np.ndarray:
    """Um tile 8x8 como matriz de indices de cor."""
    tile = np.zeros((8, 8), dtype=np.uint8)
    if fmt == "nes2bpp":
        # dois planos separados: 8 bytes do bit 0, depois 8 bytes do bit 1
        for row in range(8):
            low, high = data[offset + row], data[offset + 8 + row]
            for column in range(8):
                bit = 7 - column
                tile[row, column] = ((low >> bit) & 1) | (((high >> bit) & 1) << 1)
    elif fmt in ("snes2bpp", "snes4bpp"):
        # planos intercalados por linha
        planes = 2 if fmt == "snes2bpp" else 4
        for row in range(8):
            for pair in range(planes // 2):
                low = data[offset + pair * 16 + row * 2]
                high = data[offset + pair * 16 + row * 2 + 1]
                for column in range(8):
                    bit = 7 - column
                    tile[row, column] |= ((low >> bit) & 1) << (pair * 2)
                    tile[row, column] |= ((high >> bit) & 1) << (pair * 2 + 1)
    else:
        raise ValueError(f"formato de tile desconhecido: {fmt!r}")
    return tile


def encode_tile(tile: np.ndarray, fmt: str = "nes2bpp") -> bytes:
    """Inverso de decode_tile."""
    if fmt == "nes2bpp":
        out = bytearray(16)
        for row in range(8):
            for column in range(8):
                bit = 7 - column
                value = int(tile[row, column])
                out[row] |= (value & 1) << bit
                out[8 + row] |= ((value >> 1) & 1) << bit
        return bytes(out)
    if fmt in ("snes2bpp", "snes4bpp"):
        planes = 2 if fmt == "snes2bpp" else 4
        out = bytearray(TILE_BYTES[fmt])
        for row in range(8):
            for pair in range(planes // 2):
                for column in range(8):
                    bit = 7 - column
                    value = int(tile[row, column])
                    out[pair * 16 + row * 2] |= ((value >> (pair * 2)) & 1) << bit
                    out[pair * 16 + row * 2 + 1] |= ((value >> (pair * 2 + 1)) & 1) << bit
        return bytes(out)
    raise ValueError(f"formato de tile desconhecido: {fmt!r}")


def render(tile: np.ndarray, ramp: str = " .+#") -> str:
    """Desenha o tile em texto, para inspecionar a fonte no terminal."""
    return "\n".join(
        "".join(ramp[min(int(value), len(ramp) - 1)] for value in row) for row in tile
    )


#: marcas de 3 pixels de largura, desenhadas na linha de cima do glifo
DIACRITICS: dict[str, tuple[tuple[int, int], ...]] = {
    "tilde": ((0, 1), (0, 2), (1, 3), (0, 4), (0, 5)),
    "acute": ((1, 3), (0, 4), (0, 5)),
    "grave": ((0, 2), (0, 3), (1, 4)),
    "circumflex": ((1, 2), (0, 3), (1, 4)),
    "diaeresis": ((0, 2), (0, 5)),
}

#: acentos de cada letra que o portugues precisa
ACCENTS: dict[str, tuple[str, str]] = {
    "á": ("a", "acute"), "à": ("a", "grave"), "â": ("a", "circumflex"),
    "ã": ("a", "tilde"), "é": ("e", "acute"), "ê": ("e", "circumflex"),
    "í": ("i", "acute"), "ó": ("o", "acute"), "ô": ("o", "circumflex"),
    "õ": ("o", "tilde"), "ú": ("u", "acute"), "ç": ("c", "cedilla"),
}


class NoRoomForDiacritic(ValueError):
    pass


def background_of(tile: np.ndarray) -> int:
    """Cor de fundo do tile: a mais frequente.

    Nao da para assumir zero. A fonte do Dragon Warrior desenha em cima da cor 2,
    e uma funcao que trate "linha vazia" como "linha de zeros" conclui que nao ha
    espaco nenhum e recusa todos os acentos.
    """
    values, counts = np.unique(tile, return_counts=True)
    return int(values[int(counts.argmax())])


def ink_of(tile: np.ndarray, background: int | None = None) -> int:
    """Cor do traco do glifo: o maior indice presente.

    A tentacao e usar "a cor mais frequente que nao e fundo", mas numa fonte com
    contorno essa cor e a do *contorno*, nao a do traco -- e ai toda linha com
    borda parece ocupada e os acentos sao recusados sem motivo. O traco e sempre
    o indice mais alto da paleta nas fontes de 2bpp e 4bpp examinadas.
    """
    background = background_of(tile) if background is None else background
    values = np.unique(tile[tile != background])
    if values.size == 0:
        raise NoRoomForDiacritic("o tile e de uma cor so")
    return int(values.max())


def add_diacritic(
    tile: np.ndarray,
    mark: str,
    ink: int | None = None,
    background: int | None = None,
) -> np.ndarray:
    """Devolve o glifo com a marca somada, deslocando para baixo se precisar.

    Levanta NoRoomForDiacritic quando nao ha linha livre -- e o caso das letras
    com haste alta. Recusar e o certo: um glifo ilegivel e pior que uma palavra
    escolhida para evitar o acento.
    """
    out = tile.copy()
    background = background_of(out) if background is None else background
    ink = ink_of(out, background) if ink is None else ink

    def free(row: int) -> bool:
        """Livre = sem traco. Nao exige a linha inteira na cor de fundo.

        Fontes com contorno e sombra deixam pixels de meio-tom nas bordas do
        glifo; exigir uniformidade recusava acentos que cabiam folgadamente.
        """
        return not bool((out[row] == ink).any())

    if mark == "cedilla":
        if not free(7):
            raise NoRoomForDiacritic("nao ha linha livre embaixo para a cedilha")
        out[7, 3] = out[7, 4] = ink
        return out

    if mark not in DIACRITICS:
        raise ValueError(f"marca desconhecida: {mark!r}")

    if not free(0):
        if not free(7):
            raise NoRoomForDiacritic("sem linha livre em cima nem embaixo")
        out = np.roll(out, 1, axis=0)  # desce o glifo para abrir a linha de cima
        out[0] = background
    for row, column in DIACRITICS[mark]:
        out[row, column] = ink
    return out


def find_free_tiles(
    data: bytes, offset: int, count: int, fmt: str, used: set[int]
) -> list[int]:
    """Indices de tiles em branco que a tabela nao usa -- candidatos a doador.

    "Em branco" e o tile de uma cor so. Nem todo tile em branco esta livre (pode
    ser um espaco que o jogo desenha), mas os que a tabela ja usa ficam de fora, e
    o resto e conferido a olho com `font show` antes de sobrescrever.
    """
    size = TILE_BYTES[fmt]
    free = []
    for index in range(count):
        if index in used:
            continue
        start = offset + index * size
        if start + size > len(data):
            break
        if len(np.unique(decode_tile(data, start, fmt))) == 1:
            free.append(index)
    return free
