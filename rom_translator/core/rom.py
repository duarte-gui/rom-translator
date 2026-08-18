"""ROM container: carga, hashes e remocao do header de copiadora.

O resto do projeto trabalha SEMPRE com offsets de arquivo sobre `Rom.data`,
que ja vem sem header de copiadora. A conversao para enderecos de CPU e
responsabilidade exclusiva do plugin de plataforma.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Rom:
    data: bytearray
    path: Path | None = None
    #: header de 512 bytes das copiadoras antigas (SMC/FIG). Vazio se nao houver.
    copier_header: bytes = b""
    meta: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path, strip_copier_header: bool = True) -> "Rom":
        path = Path(path)
        raw = path.read_bytes()
        header = b""
        if strip_copier_header and len(raw) % 1024 == 512:
            header, raw = raw[:512], raw[512:]
        return cls(data=bytearray(raw), path=path, copier_header=header)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Rom":
        return cls(data=bytearray(raw))

    def save(self, path: str | Path, keep_copier_header: bool = True) -> Path:
        path = Path(path)
        out = (self.copier_header if keep_copier_header else b"") + bytes(self.data)
        path.write_bytes(out)
        return path

    # -- identidade -------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self.data)

    def crc32(self) -> int:
        return zlib.crc32(self.data) & 0xFFFFFFFF

    def md5(self) -> str:
        return hashlib.md5(self.data).hexdigest()

    def sha1(self) -> str:
        return hashlib.sha1(self.data).hexdigest()

    def hashes(self) -> dict[str, str]:
        return {"crc32": f"{self.crc32():08x}", "md5": self.md5(), "sha1": self.sha1()}

    # -- acesso -----------------------------------------------------------
    def read(self, offset: int, length: int) -> bytes:
        return bytes(self.data[offset : offset + length])

    def write(self, offset: int, payload: bytes) -> None:
        end = offset + len(payload)
        if end > len(self.data):
            self.data.extend(b"\x00" * (end - len(self.data)))
        self.data[offset:end] = payload

    def expand(self, size: int | None = None, filler: int = 0x00) -> tuple[int, int]:
        """Aumenta a ROM ate `size` (padrao: proxima potencia de 2). Devolve (inicio, fim).

        A faixa nova e espaco livre de verdade -- ninguem aponta para la. Mas so
        serve para texto enderecavel por ponteiro *largo*: um ponteiro de 16 bits
        nao alcanca um banco que nao existia antes. Quem chama precisa saber
        disso; a expansao em si nao tem como impedir o mau uso.

        Vale avisar tambem que nem todo emulador e nem todo cartucho aceitam uma
        ROM expandida.
        """
        current = len(self.data)
        target = size if size is not None else 1 << (current - 1).bit_length()
        if target <= current:
            raise ValueError(f"expansao precisa passar de {current} bytes, pediram {target}")
        self.data.extend(bytes([filler]) * (target - current))
        return current, target

    def copy(self) -> "Rom":
        return Rom(
            data=bytearray(self.data),
            path=self.path,
            copier_header=self.copier_header,
            meta=dict(self.meta),
        )
