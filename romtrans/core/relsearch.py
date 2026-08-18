"""Relative search: descobrir o encoding de uma ROM sem ter a tabela.

A tecnica classica do romhacking. Quase toda ROM guarda o alfabeto como uma
faixa contigua de bytes -- so nao se sabe onde ela comeca. Mas as *distancias*
entre letras sobrevivem: em "Crono", de 'r' para 'o' ha -3 posicoes, seja o
alfabeto ASCII ou qualquer outro. Procurar essas distancias no lugar dos bytes
literais acha a palavra sem conhecer a tabela.
"""

from __future__ import annotations

import string
from collections import Counter
from dataclasses import dataclass

DEFAULT_WORDS = (
    # ingles e portugues: palavras curtas e frequentes em dialogo de RPG
    "the", "you", "and", "that", "with", "have", "this", "what",
    "para", "voce", "com", "uma", "nao", "que", "mas", "por",
)


@dataclass
class Hit:
    offset: int
    raw: bytes
    #: byte correspondente a 'a' minusculo implicado por este hit
    base_lower: int | None = None
    base_upper: int | None = None


def _deltas(text: str) -> list[int]:
    return [(ord(b) - ord(a)) % 256 for a, b in zip(text, text[1:])]


def relative_search(
    data: bytes,
    crib: str,
    regions: list[tuple[int, int]] | None = None,
) -> list[Hit]:
    """Acha ocorrencias de `crib` por distancia entre caracteres.

    `crib` deve ficar dentro de uma unica faixa contigua do alfabeto -- use
    "rono" e nao "Crono", ja que maiusculas e minusculas costumam viver em
    faixas separadas.
    """
    if len(crib) < 3:
        raise ValueError("crib curto demais: com menos de 3 letras tudo casa")
    deltas = _deltas(crib)
    span = len(crib)
    hits: list[Hit] = []
    for start, end in regions or [(0, len(data))]:
        for i in range(start, min(end, len(data)) - span + 1):
            if all(
                (data[i + k + 1] - data[i + k]) % 256 == deltas[k]
                for k in range(span - 1)
            ):
                raw = bytes(data[i : i + span])
                hit = Hit(offset=i, raw=raw)
                first = crib[0]
                if first in string.ascii_lowercase:
                    hit.base_lower = (raw[0] - (ord(first) - ord("a"))) % 256
                elif first in string.ascii_uppercase:
                    hit.base_upper = (raw[0] - (ord(first) - ord("A"))) % 256
                hits.append(hit)
    return hits


def guess_alphabet(
    data: bytes,
    words: tuple[str, ...] = DEFAULT_WORDS,
    regions: list[tuple[int, int]] | None = None,
    top: int = 5,
) -> list[tuple[int, int]]:
    """Ranqueia candidatos a byte da letra 'a'.

    Ao contrario do relative_search, nao pede uma palavra conhecida: testa todos
    os 256 deslocamentos possiveis do alfabeto e conta quantas palavras comuns
    aparecem em cada um. O deslocamento certo se destaca por ordens de grandeza.

    Retorna [(base, ocorrencias)] em ordem decrescente.
    """
    scores: Counter[int] = Counter()
    for word in words:
        for hit in relative_search(data, word, regions):
            if hit.base_lower is not None:
                scores[hit.base_lower] += 1
    return scores.most_common(top)


def build_table_source(
    base_lower: int,
    base_upper: int | None = None,
    base_digit: int | None = None,
    space: int | None = None,
) -> str:
    """Monta um .tbl inicial a partir dos deslocamentos descobertos.

    E um ponto de partida para revisao humana, nao um resultado final:
    acentos, pontuacao e codigos de controle ainda precisam ser mapeados a mao
    (ou deduzidos comparando com uma traducao existente).
    """
    lines = [f"# gerado por relative search -- revisar antes de usar"]
    for index, char in enumerate(string.ascii_lowercase):
        lines.append(f"{(base_lower + index) % 256:02X}={char}")
    if base_upper is not None:
        for index, char in enumerate(string.ascii_uppercase):
            lines.append(f"{(base_upper + index) % 256:02X}={char}")
    if base_digit is not None:
        for index in range(10):
            lines.append(f"{(base_digit + index) % 256:02X}={index}")
    if space is not None:
        lines.append(f"{space:02X}= ")
    return "\n".join(lines) + "\n"
