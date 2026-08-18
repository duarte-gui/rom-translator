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

from ..platforms.base import Detection, PlatformPlugin, PointerSpec
from .rom import Rom
from .script import Script, Unit
from .space import SpaceAllocator
from .table import Table, TableError


@dataclass
class InsertReport:
    written: int = 0
    skipped_untranslated: int = 0
    relocated: int = 0
    bytes_relocated: int = 0
    overflow: list[tuple[Unit, int]] = field(default_factory=list)
    failed: list[tuple[Unit, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.overflow and not self.failed


@dataclass
class Relocator:
    """Move uma string para espaco livre e conserta quem apontava para ela.

    Tres condicoes precisam valer, e qualquer uma que falte cancela a mudanca:

    * a unidade tem que terminar num token de fim -- sem terminador, o jogo le
      alem da string nova e continua lendo ate achar um byte de fim por acaso;
    * todos os ponteiros que a enderecam precisam ser conhecidos e reescreviveis;
    * com ponteiro estreito, o destino tem que cair no mesmo banco da origem.
    """

    rom: Rom
    table: Table
    plugin: PlatformPlugin
    det: Detection
    allocator: SpaceAllocator
    #: offset do ponteiro -> como ele e codificado
    specs: dict[int, PointerSpec] = field(default_factory=dict)
    moved: dict[int, int] = field(default_factory=dict)

    def can_relocate(self, unit: Unit, encoded: bytes) -> str:
        """Devolve o motivo do impedimento, ou string vazia se pode mover."""
        if not unit.pointers:
            return "nenhum ponteiro conhecido aponta para esta unidade"
        if not any(encoded.endswith(token) for token in self.table.end_tokens):
            return "a unidade nao termina num token de fim"
        missing = [p for p in unit.pointers if p not in self.specs]
        if missing:
            return f"ponteiro em 0x{missing[0]:06X} sem formato conhecido"
        return ""

    def relocate(self, unit: Unit, encoded: bytes) -> int | None:
        """Escreve `encoded` em espaco livre e reaponta. None se nao deu."""
        narrow = any(self.specs[p].width < 3 for p in unit.pointers)
        bank = self.allocator.bank_of(unit.offset) if narrow else None
        target = self.allocator.allocate(len(encoded), bank=bank)
        if target is None:
            return None
        cpu = self.plugin.file_to_cpu(target, self.det)
        if cpu is None:
            return None
        self.rom.write(target, encoded)
        for pointer in unit.pointers:
            spec = self.specs[pointer]
            self.rom.write(pointer, spec.encode(cpu))
        self.moved[unit.offset] = target
        return target


def insert(
    rom: Rom,
    script: Script,
    table: Table,
    padding: bytes | None = None,
    relocator: "Relocator | None" = None,
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
            if relocator is None:
                report.overflow.append((unit, len(encoded)))
                continue
            reason = relocator.can_relocate(unit, encoded)
            if reason:
                report.overflow.append((unit, len(encoded)))
                unit.note = reason
                continue
            if relocator.relocate(unit, encoded) is None:
                report.overflow.append((unit, len(encoded)))
                unit.note = "sem espaco livre no banco de origem"
                continue
            report.relocated += 1
            report.bytes_relocated += len(encoded)
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
