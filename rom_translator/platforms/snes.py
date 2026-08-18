"""SNES / Super Famicom: LoROM, HiROM e ExHiROM."""

from __future__ import annotations

from .base import Detection, PlatformPlugin, PointerSpec

#: offset do header interno de 64 bytes para cada mapeamento
HEADER_OFFSETS = {"lorom": 0x7FC0, "hirom": 0xFFC0, "exhirom": 0x40FFC0}

#: posicoes no header interno (relativas ao inicio dele)
COMPLEMENT_OFF = 0x1C
CHECKSUM_OFF = 0x1E


def compute_checksum(data: bytes) -> int:
    """Soma de 16 bits de toda a ROM, com os campos de checksum zerados.

    Em ROMs cujo tamanho nao e potencia de 2, o hardware espelha o trecho final
    ate completar a proxima potencia -- e a soma tem que espelhar junto.
    """
    total = sum(data) & 0xFFFFFFFF
    size = len(data)
    power = 1 << (size.bit_length() - 1)
    if power != size:  # trecho excedente e espelhado ate fechar a potencia
        rest = data[power:]
        mirror = power - len(rest)
        repeats = max(1, mirror // max(len(rest), 1))
        total = (sum(data[:power]) + sum(rest) * repeats) & 0xFFFFFFFF
    return total & 0xFFFF


def checksum_valid(data: bytes, header_offset: int) -> bool:
    stored = int.from_bytes(
        data[header_offset + CHECKSUM_OFF : header_offset + CHECKSUM_OFF + 2], "little"
    )
    comp = int.from_bytes(
        data[header_offset + COMPLEMENT_OFF : header_offset + COMPLEMENT_OFF + 2], "little"
    )
    if stored ^ comp != 0xFFFF:
        return False
    # zera os campos antes de somar, como faz o calculo canonico
    patched = bytearray(data)
    patched[header_offset + COMPLEMENT_OFF : header_offset + COMPLEMENT_OFF + 2] = b"\xff\xff"
    patched[header_offset + CHECKSUM_OFF : header_offset + CHECKSUM_OFF + 2] = b"\x00\x00"
    return compute_checksum(bytes(patched)) == stored


def fix_checksum(data: bytearray, header_offset: int) -> int:
    """Recalcula e grava o checksum interno. Obrigatorio apos alterar a ROM."""
    data[header_offset + COMPLEMENT_OFF : header_offset + COMPLEMENT_OFF + 2] = b"\xff\xff"
    data[header_offset + CHECKSUM_OFF : header_offset + CHECKSUM_OFF + 2] = b"\x00\x00"
    checksum = compute_checksum(bytes(data))
    data[header_offset + CHECKSUM_OFF : header_offset + CHECKSUM_OFF + 2] = checksum.to_bytes(2, "little")
    data[header_offset + COMPLEMENT_OFF : header_offset + COMPLEMENT_OFF + 2] = (checksum ^ 0xFFFF).to_bytes(2, "little")
    return checksum


def _score_header(data: bytes, base: int, mapper: str) -> float:
    """Pontua um candidato a header interno. 0.0 = nao e header."""
    if base + 64 > len(data):
        return 0.0
    title = data[base : base + 21]
    printable = sum(1 for b in title if 0x20 <= b <= 0x7E)
    if printable < 15:  # titulos reais sao ASCII com padding de espaco
        return 0.0
    score = printable / 21 * 0.3

    map_mode = data[base + 0x15]
    expected = {"lorom": 0x0, "hirom": 0x1, "exhirom": 0x5}[mapper]
    if (map_mode & 0x0F) == expected:
        score += 0.25

    complement = int.from_bytes(data[base + 0x1C : base + 0x1E], "little")
    checksum = int.from_bytes(data[base + 0x1E : base + 0x20], "little")
    if checksum ^ complement == 0xFFFF and checksum not in (0x0000, 0xFFFF):
        score += 0.3

    # vetor de reset (NMI/RESET em modo emulacao) tem que apontar para ROM
    reset = int.from_bytes(data[base + 0x3C : base + 0x3E], "little")
    if reset >= 0x8000:
        score += 0.1

    declared = 1 << data[base + 0x17]  # em KiB
    if declared and abs(declared * 1024 - len(data)) <= declared * 1024:
        score += 0.05

    return min(score, 1.0)


class SnesPlugin(PlatformPlugin):
    name = "snes"
    extensions = (".smc", ".sfc", ".fig", ".swc")

    def detect(self, data: bytes) -> Detection | None:
        best: Detection | None = None
        for mapper, base in HEADER_OFFSETS.items():
            score = _score_header(data, base, mapper)
            if score > 0.4 and (best is None or score > best.confidence):
                title = data[base : base + 21].decode("ascii", "replace").strip()
                best = Detection(
                    platform=self.name,
                    confidence=score,
                    mapper=mapper,
                    title=title,
                    details={
                        "header_offset": base,
                        "rom_speed": "fast" if data[base + 0x15] & 0x10 else "slow",
                        "checksum": f"{int.from_bytes(data[base + 0x1E:base + 0x20], 'little'):04X}",
                        "checksum_ok": checksum_valid(data, base),
                        "country": data[base + 0x19],
                        "version": data[base + 0x1B],
                    },
                )
        return best

    def cpu_to_file(self, cpu_addr: int, det: Detection) -> int | None:
        bank = (cpu_addr >> 16) & 0xFF
        addr = cpu_addr & 0xFFFF
        if det.mapper == "lorom":
            if addr < 0x8000:
                return None  # RAM/registradores, nao ROM
            return ((bank & 0x7F) * 0x8000) + (addr & 0x7FFF)
        # hirom / exhirom
        if (bank & 0x7F) < 0x40 and addr < 0x8000:
            return None
        return ((bank & 0x3F) * 0x10000) + addr

    def file_to_cpu(self, offset: int, det: Detection) -> int | None:
        if offset < 0:
            return None
        if det.mapper == "lorom":
            bank = 0x80 + (offset // 0x8000)
            return (bank << 16) | (0x8000 + (offset % 0x8000))
        bank = 0xC0 + (offset // 0x10000)
        return (bank << 16) | (offset % 0x10000)

    def pointer_specs(self, det: Detection) -> list[PointerSpec]:
        return [
            PointerSpec("ptr16", width=2, endian="little"),
            PointerSpec("ptr24", width=3, endian="little"),
        ]
