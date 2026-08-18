"""Arquivo de projeto: o que o `scan` descobriu e o usuario pode corrigir a mao.

Deliberadamente em YAML e nao em JSON: blocos e limites sao exatamente o tipo de
coisa que se ajusta manualmente depois que a deteccao automatica erra a mao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .core.rom import Rom
from .core.script import Script, Unit
from .core.table import Table


def _hex(value: int) -> str:
    return f"0x{value:06X}"


@dataclass
class Block:
    """Uma faixa da ROM com texto, e como as unidades sao delimitadas dentro dela."""

    id: str
    start: int
    end: int
    #: "fixed"      -> registros de tamanho constante (nomes de item, menus)
    #: "terminated" -> strings encerradas por um token de fim (dialogo)
    #: "greedy"     -> trechos maximos de bytes imprimiveis; nao exige conhecer
    #:                 o terminador, entao e o que o `scan` automatico usa
    kind: str = "greedy"
    entry_size: int = 0
    min_run: int = 4
    score: float = 0.0

    def extract(self, data: bytes, table: Table) -> list[Unit]:
        if self.kind == "fixed":
            return self._extract_fixed(data, table)
        if self.kind == "greedy":
            return self._extract_greedy(data, table)
        return self._extract_terminated(data, table)

    def _extract_greedy(self, data: bytes, table: Table) -> list[Unit]:
        """Trechos maximos de bytes que a tabela sabe imprimir.

        Nao depende de conhecer o token de fim -- o que torna este o unico modo
        que funciona logo depois de um `scan` automatico, antes de qualquer
        engenharia reversa manual do formato do jogo.
        """
        printable = table.letter_bytes
        units: list[Unit] = []
        index = 0
        offset = self.start
        end = min(self.end, len(data))
        while offset < end:
            if data[offset] not in printable:
                offset += 1
                continue
            start = offset
            while offset < end and data[offset] in printable:
                offset += 1
            if offset - start < self.min_run:
                continue
            decoded = table.decode(data, start, offset - start, stop_at_end=False)
            units.append(
                Unit(
                    id=f"{self.id}/{index:04d}",
                    offset=start,
                    length=offset - start,
                    text=decoded.text,
                    max_len=offset - start,
                    block=self.id,
                )
            )
            index += 1
        return units

    def _extract_fixed(self, data: bytes, table: Table) -> list[Unit]:
        if self.entry_size <= 0:
            raise ValueError(f"bloco {self.id!r}: kind 'fixed' exige entry_size")
        units = []
        for index, offset in enumerate(range(self.start, self.end, self.entry_size)):
            if offset + self.entry_size > len(data):
                break
            decoded = table.decode(data, offset, self.entry_size, stop_at_end=False)
            units.append(
                Unit(
                    id=f"{self.id}/{index:04d}",
                    offset=offset,
                    length=self.entry_size,
                    text=decoded.text,
                    max_len=self.entry_size,
                    block=self.id,
                )
            )
        return units

    def _extract_terminated(self, data: bytes, table: Table) -> list[Unit]:
        units = []
        offset = self.start
        index = 0
        while offset < self.end:
            decoded = table.decode(data, offset, self.end - offset, stop_at_end=True)
            if decoded.consumed == 0:
                break
            if decoded.terminated:
                units.append(
                    Unit(
                        id=f"{self.id}/{index:04d}",
                        offset=offset,
                        length=decoded.consumed,
                        text=decoded.text,
                        # sem repointing (M4), a traducao tem que caber no original
                        max_len=decoded.consumed,
                        block=self.id,
                    )
                )
                index += 1
            offset += decoded.consumed
        return units


@dataclass
class Project:
    rom_path: str = ""
    rom_sha1: str = ""
    platform: str = ""
    mapper: str = ""
    table_path: str = "table.tbl"
    blocks: list[Block] = field(default_factory=list)
    notes: str = ""

    # -- persistencia -----------------------------------------------------
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        payload = {
            "rom": {
                "path": self.rom_path,
                "sha1": self.rom_sha1,
                "platform": self.platform,
                "mapper": self.mapper,
            },
            "table": self.table_path,
            "blocks": [
                {
                    "id": b.id,
                    "kind": b.kind,
                    "start": _hex(b.start),
                    "end": _hex(b.end),
                    **({"entry_size": b.entry_size} if b.entry_size else {}),
                    **({"min_run": b.min_run} if b.kind == "greedy" else {}),
                    **({"score": round(b.score, 2)} if b.score else {}),
                }
                for b in self.blocks
            ],
        }
        if self.notes:
            payload["notes"] = self.notes
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        rom = payload.get("rom", {})
        blocks = [
            Block(
                id=item["id"],
                start=int(str(item["start"]), 0),
                end=int(str(item["end"]), 0),
                kind=item.get("kind", "greedy"),
                entry_size=int(item.get("entry_size", 0)),
                min_run=int(item.get("min_run", 4)),
                score=float(item.get("score", 0.0)),
            )
            for item in payload.get("blocks", [])
        ]
        return cls(
            rom_path=rom.get("path", ""),
            rom_sha1=rom.get("sha1", ""),
            platform=rom.get("platform", ""),
            mapper=rom.get("mapper", ""),
            table_path=payload.get("table", "table.tbl"),
            blocks=blocks,
            notes=payload.get("notes", ""),
        )

    # -- uso --------------------------------------------------------------
    def load_table(self, base_dir: Path) -> Table:
        return Table.load(base_dir / self.table_path)

    def dump(self, rom: Rom, table: Table) -> Script:
        script = Script(rom_sha1=rom.sha1(), table=self.table_path)
        for block in self.blocks:
            script.units.extend(block.extract(bytes(rom.data), table))
        return script
