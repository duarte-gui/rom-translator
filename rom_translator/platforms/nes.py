"""NES / Famicom (arquivos iNES e NES 2.0)."""

from __future__ import annotations

from .base import Detection, PlatformPlugin, PointerSpec


class NesPlugin(PlatformPlugin):
    name = "nes"
    extensions = (".nes",)

    def detect(self, data: bytes) -> Detection | None:
        if data[:4] != b"NES\x1a":
            return None
        prg_banks = data[4]
        chr_banks = data[5]
        flags6 = data[6]
        trainer = 512 if flags6 & 0x04 else 0
        mapper_id = (flags6 >> 4) | (data[7] & 0xF0)
        nes20 = (data[7] & 0x0C) == 0x08
        return Detection(
            platform=self.name,
            confidence=1.0,
            mapper=f"ines-{mapper_id}",
            details={
                "prg_offset": 16 + trainer,
                "prg_size": prg_banks * 16384,
                "chr_offset": 16 + trainer + prg_banks * 16384,
                "chr_size": chr_banks * 8192,
                "bank_size": 16384,
                "format": "NES 2.0" if nes20 else "iNES",
            },
        )

    def cpu_to_file(self, cpu_addr: int, det: Detection) -> int | None:
        """Sem estado de banco corrente, so o ultimo banco (fixo em $C000) e resolvivel."""
        if cpu_addr < 0x8000:
            return None
        prg_off = det.details["prg_offset"]
        prg_size = det.details["prg_size"]
        if cpu_addr >= 0xC000:
            return prg_off + prg_size - 0x4000 + (cpu_addr - 0xC000)
        return None

    def file_to_cpu(self, offset: int, det: Detection) -> int | None:
        prg_off = det.details["prg_offset"]
        if offset < prg_off:
            return None
        return 0x8000 + ((offset - prg_off) % det.details["bank_size"])

    def bank_size(self, det: Detection) -> int | None:
        return det.details["bank_size"]

    def pointer_specs(self, det: Detection) -> list[PointerSpec]:
        return [PointerSpec("ptr16", width=2, endian="little")]

    def text_regions(self, data: bytes, det: Detection) -> list[tuple[int, int]]:
        # CHR e tile grafico: procurar texto la so gera falso positivo
        start = det.details["prg_offset"]
        return [(start, start + det.details["prg_size"])]
