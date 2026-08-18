"""Unidades de texto extraidas da ROM e sua serializacao.

Uma Unit e o menor pedaco que se traduz de forma independente: um nome de item,
uma fala, uma opcao de menu. Ela carrega o texto e -- igualmente importante --
o *orcamento* de bytes que a traducao tem para caber de volta.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class Unit:
    id: str
    offset: int  # offset no arquivo onde a unidade comeca
    length: int  # bytes que ela ocupa hoje
    text: str  # texto original decodificado pela tabela
    max_len: int  # orcamento em bytes para a reinsercao no lugar
    block: str = ""
    translation: str | None = None
    #: offsets de arquivo dos ponteiros que apontam para esta unidade (M2)
    pointers: list[int] = field(default_factory=list)
    note: str = ""

    @property
    def translated(self) -> bool:
        return self.translation is not None


@dataclass
class Script:
    units: list[Unit] = field(default_factory=list)
    rom_sha1: str = ""
    table: str = ""
    version: int = SCHEMA_VERSION

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        payload = {
            "version": self.version,
            "rom_sha1": self.rom_sha1,
            "table": self.table,
            "units": [asdict(unit) for unit in self.units],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Script":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != SCHEMA_VERSION:
            raise ValueError(
                f"script versao {payload.get('version')}, esperado {SCHEMA_VERSION}"
            )
        return cls(
            units=[Unit(**item) for item in payload["units"]],
            rom_sha1=payload.get("rom_sha1", ""),
            table=payload.get("table", ""),
        )

    def stats(self) -> dict[str, int]:
        return {
            "unidades": len(self.units),
            "traduzidas": sum(1 for u in self.units if u.translated),
            "caracteres": sum(len(u.text) for u in self.units),
        }
