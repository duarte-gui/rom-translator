"""Espaco livre na ROM e alocacao para strings que nao cabem no lugar.

Achar espaco livre e a parte facil: jogos deixam trechos longos de um mesmo byte
de preenchimento no fim dos bancos. A parte que da errado e o *banco*.

Um ponteiro de 16 bits so guarda o deslocamento dentro do banco -- o banco vem
de outro lugar (um registrador, uma tabela paralela, uma constante no codigo).
Mover uma string para um banco diferente e reescrever esse ponteiro produz um
endereco que aponta para o lugar certo no banco errado: a ROM nao trava na hora,
ela mostra lixo horas depois. Por isso o alocador aceita um banco obrigatorio e
devolve None em vez de "quase serve".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FreeRegion:
    start: int
    end: int
    filler: int
    used: int = 0

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def free(self) -> int:
        return self.size - self.used

    @property
    def cursor(self) -> int:
        return self.start + self.used


def find_free_space(
    data: bytes,
    min_run: int = 32,
    fillers: tuple[int, ...] = (0x00, 0xFF),
    exclude: list[tuple[int, int]] | None = None,
) -> list[FreeRegion]:
    """Trechos longos de um unico byte de preenchimento.

    E uma heuristica, nao uma certeza: um trecho de zeros pode ser uma tabela
    ainda nao preenchida, ou dados que o jogo escreve em tempo de execucao.
    Por isso `exclude` existe -- o header interno e as faixas que o usuario
    marcar ficam de fora.
    """
    arr = np.frombuffer(data, dtype=np.uint8)
    regions: list[FreeRegion] = []
    for filler in fillers:
        mask = arr == filler
        padded = np.concatenate(([False], mask, [False]))
        edges = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        for start, end in zip(starts, ends):
            if end - start >= min_run:
                regions.append(FreeRegion(int(start), int(end), filler))

    for lo, hi in exclude or []:
        regions = [r for region in regions for r in _carve(region, lo, hi)]
    regions.sort(key=lambda r: r.start)
    return [r for r in regions if r.size >= min_run]


def _carve(region: FreeRegion, lo: int, hi: int) -> list[FreeRegion]:
    """Remove [lo, hi) de uma regiao, possivelmente partindo-a em duas."""
    if hi <= region.start or lo >= region.end:
        return [region]
    out = []
    if region.start < lo:
        out.append(FreeRegion(region.start, lo, region.filler))
    if hi < region.end:
        out.append(FreeRegion(hi, region.end, region.filler))
    return out


class SpaceAllocator:
    """Aloca bytes nas regioes livres, respeitando a restricao de banco.

    Regioes que atravessam uma fronteira de banco sao divididas na construcao.
    Sem isso, uma regiao que comeca no banco 1 e termina no 2 nao conseguiria
    servir um pedido do banco 2, mesmo tendo espaco de sobra la dentro.
    """

    def __init__(self, regions: list[FreeRegion], bank_size: int | None = None) -> None:
        self.bank_size = bank_size
        self.regions = self._split_by_bank(regions) if bank_size else list(regions)
        self.regions.sort(key=lambda r: r.start)

    def _split_by_bank(self, regions: list[FreeRegion]) -> list[FreeRegion]:
        assert self.bank_size
        out: list[FreeRegion] = []
        for region in regions:
            start = region.start
            while start < region.end:
                boundary = (start // self.bank_size + 1) * self.bank_size
                end = min(boundary, region.end)
                out.append(FreeRegion(start, end, region.filler))
                start = end
        return out

    def bank_of(self, offset: int) -> int | None:
        return None if self.bank_size is None else offset // self.bank_size

    def allocate(self, size: int, bank: int | None = None) -> int | None:
        """Reserva `size` bytes, opcionalmente dentro de um banco especifico."""
        for region in self.regions:
            if region.free < size:
                continue
            if bank is not None and self.bank_of(region.start) != bank:
                continue
            offset = region.cursor
            region.used += size
            return offset
        return None

    @property
    def total_free(self) -> int:
        return sum(r.free for r in self.regions)

    @property
    def total_used(self) -> int:
        return sum(r.used for r in self.regions)

    def free_by_bank(self) -> dict[int | None, int]:
        totals: dict[int | None, int] = {}
        for region in self.regions:
            key = self.bank_of(region.start)
            totals[key] = totals.get(key, 0) + region.free
        return totals
