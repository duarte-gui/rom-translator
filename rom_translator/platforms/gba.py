"""Game Boy Advance: mapeamento direto, ponteiros de 32 bits em 0x08xxxxxx."""

from __future__ import annotations

from .base import Detection, PlatformPlugin, PointerSpec

ROM_BASE = 0x08000000


class GbaPlugin(PlatformPlugin):
    name = "gba"
    extensions = (".gba", ".agb")

    def detect(self, data: bytes) -> Detection | None:
        if len(data) < 0xC0 or data[0xB2] != 0x96:
            return None
        # o logo da Nintendo em 0x04..0xA0 e verificado pela BIOS; usamos so
        # o primeiro word como confirmacao barata
        logo_ok = data[0x04:0x08] == b"\x24\xff\xae\x51"
        title = data[0xA0:0xAC].decode("ascii", "replace").strip("\x00 ")
        return Detection(
            platform=self.name,
            confidence=1.0 if logo_ok else 0.6,
            mapper="flat",
            title=title,
            details={"game_code": data[0xAC:0xB0].decode("ascii", "replace")},
        )

    def cpu_to_file(self, cpu_addr: int, det: Detection) -> int | None:
        if cpu_addr < ROM_BASE or cpu_addr >= ROM_BASE + 0x02000000:
            return None
        return cpu_addr - ROM_BASE

    def file_to_cpu(self, offset: int, det: Detection) -> int | None:
        return ROM_BASE + offset

    def pointer_specs(self, det: Detection) -> list[PointerSpec]:
        return [PointerSpec("ptr32", width=4, endian="little")]
