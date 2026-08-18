"""Reinsercao: escrever o texto traduzido de volta na ROM.

Politica conservadora, nesta ordem:
  1. cabe no espaco original -> escreve no lugar;
  2. sobra espaco            -> escreve e completa com o byte de preenchimento,
                                para nao deslocar nada depois;
  3. nao cabe                -> **nao escreve**, e reporta.

O passo 3 e deliberado. Escrever alem do limite corromperia a string seguinte
de forma silenciosa, e uma ROM que trava depois de duas horas de jogo e um
problema muito pior do que uma linha que ficou em ingles. Mover a string para
outro lugar e reapontar e trabalho do M4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rom import Rom
from .script import Script, Unit
from .table import Table, TableError


@dataclass
class InsertReport:
    written: int = 0
    skipped_untranslated: int = 0
    overflow: list[tuple[Unit, int]] = field(default_factory=list)
    failed: list[tuple[Unit, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.overflow and not self.failed


def insert(
    rom: Rom,
    script: Script,
    table: Table,
    padding: bytes | None = None,
) -> InsertReport:
    """Aplica as traducoes de `script` sobre `rom`, no lugar."""
    report = InsertReport()
    for unit in script.units:
        if unit.translation is None:
            report.skipped_untranslated += 1
            continue
        try:
            encoded = table.encode(unit.translation)
        except TableError as exc:
            report.failed.append((unit, str(exc)))
            continue
        if len(encoded) > unit.max_len:
            report.overflow.append((unit, len(encoded)))
            continue
        filler = padding if padding is not None else _guess_padding(rom, unit, table)
        block = encoded + filler * (unit.max_len - len(encoded))
        rom.write(unit.offset, block[: unit.max_len])
        report.written += 1
    return report


def _guess_padding(rom: Rom, unit: Unit, table: Table) -> bytes:
    """Byte usado para completar uma traducao mais curta que o original.

    O espaco e quase sempre a escolha certa: e o que o proprio jogo usa para
    alinhar nomes de item e menus de largura fixa. Sem espaco na tabela, repete
    o ultimo byte do original -- que ao menos preserva o tipo de dado.
    """
    space = table.bytes_for(" ")
    if space and len(space) == 1:
        return space
    if unit.length:
        return bytes(rom.data[unit.offset + unit.length - 1 : unit.offset + unit.length])
    return b"\x00"


def verify_roundtrip(rom: Rom, script: Script, table: Table) -> list[Unit]:
    """Confere que reinserir o texto *original* nao muda um byte sequer.

    Este e o teste que sustenta o M2. Se `encode(decode(bytes))` nao devolve os
    mesmos bytes para alguma unidade, a tabela e ambigua ou o dump esta errado --
    e qualquer traducao construida em cima disso vai corromper a ROM em algum
    ponto que so aparece horas depois de jogo.
    """
    broken: list[Unit] = []
    for unit in script.units:
        original = bytes(rom.data[unit.offset : unit.offset + unit.length])
        try:
            if table.encode(unit.text) != original:
                broken.append(unit)
        except TableError:
            broken.append(unit)
    return broken
