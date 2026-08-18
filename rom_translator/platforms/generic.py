"""Fallback: arquivo cru, sem mapeamento de memoria.

Sempre casa, com confianca minima, para que `identify` nunca falhe e o
pipeline possa rodar com ponteiros informados manualmente pelo usuario.
"""

from __future__ import annotations

from .base import Detection, PlatformPlugin, PointerSpec


class GenericPlugin(PlatformPlugin):
    name = "generic"
    extensions = ()

    def detect(self, data: bytes) -> Detection | None:
        return Detection(platform=self.name, confidence=0.01, mapper="flat")

    def cpu_to_file(self, cpu_addr: int, det: Detection) -> int | None:
        return cpu_addr

    def file_to_cpu(self, offset: int, det: Detection) -> int | None:
        return offset

    def pointer_specs(self, det: Detection) -> list[PointerSpec]:
        return [
            PointerSpec("ptr16", width=2, endian="little"),
            PointerSpec("ptr24", width=3, endian="little"),
            PointerSpec("ptr32", width=4, endian="little"),
        ]
