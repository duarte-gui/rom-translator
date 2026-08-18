"""Tabela de caracteres (.tbl) -- o dicionario entre bytes da ROM e texto.

Formato .tbl padrao do romhacking:

    41=A                # um byte -> um caractere
    1234=<char>         # sequencia de bytes -> caractere (encoding multibyte)
    2A=th               # DTE/MTE: um byte -> varios caracteres
    /00=[END]           # token de fim de string
    *01=[LINE]          # token de quebra de linha
    # comentario

**Invariante do projeto**: decode() e encode() sao inversas exatas. Byte sem
mapeamento vira `[$XX]` no texto e volta a ser o mesmo byte. Sem isso, a
garantia de round-trip byte-identico do M2 nao existe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: `[END]`, `[$1F]`, `[NOME]` -- tudo que nao e caractere imprimivel
TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")
RAW_TOKEN_RE = re.compile(r"^\$([0-9A-Fa-f]{2}(?:[0-9A-Fa-f]{2})*)$")


class TableError(ValueError):
    pass


@dataclass
class Decoded:
    text: str
    consumed: int  # bytes lidos a partir do offset
    terminated: bool  # encerrou num token de fim (e nao por limite/EOF)


@dataclass
class Table:
    entries: dict[bytes, str] = field(default_factory=dict)
    end_tokens: set[bytes] = field(default_factory=set)
    line_tokens: set[bytes] = field(default_factory=set)
    name: str = ""

    _reverse: dict[str, bytes] = field(default_factory=dict, repr=False)
    _max_key: int = field(default=1, repr=False)
    _max_value: int = field(default=1, repr=False)

    # -- construcao -------------------------------------------------------
    def __post_init__(self) -> None:
        self.reindex()

    def reindex(self) -> None:
        self._max_key = max((len(k) for k in self.entries), default=1)
        self._max_value = max((len(v) for v in self.entries.values()), default=1)
        self._reverse = {}
        for raw, text in self.entries.items():
            # com valores duplicados, vence a sequencia mais curta (menos bytes
            # gastos na reinsercao); empatou, vence a primeira declarada
            current = self._reverse.get(text)
            if current is None or len(raw) < len(current):
                self._reverse[text] = raw

    @classmethod
    def parse(cls, source: str, name: str = "") -> "Table":
        table = cls(name=name)
        for lineno, line in enumerate(source.splitlines(), 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith(("#", ";")):
                continue
            kind = ""
            if line[0] in "/*":
                kind, line = line[0], line[1:]
            if "=" not in line:
                raise TableError(f"linha {lineno}: falta '=' em {line!r}")
            hexpart, value = line.split("=", 1)
            hexpart = hexpart.strip()
            if len(hexpart) % 2 or not re.fullmatch(r"[0-9A-Fa-f]+", hexpart):
                raise TableError(f"linha {lineno}: {hexpart!r} nao e hexadecimal par")
            raw = bytes.fromhex(hexpart)
            if kind == "/":
                table.end_tokens.add(raw)
                value = value or "[END]"
            elif kind == "*":
                table.line_tokens.add(raw)
                value = value or "[LINE]"
            table.entries[raw] = value
        table.reindex()
        return table

    @classmethod
    def load(cls, path: str | Path) -> "Table":
        path = Path(path)
        return cls.parse(path.read_text(encoding="utf-8"), name=path.stem)

    def dumps(self) -> str:
        lines = []
        for raw in sorted(self.entries):
            prefix = "/" if raw in self.end_tokens else "*" if raw in self.line_tokens else ""
            lines.append(f"{prefix}{raw.hex().upper()}={self.entries[raw]}")
        return "\n".join(lines) + "\n"

    # -- decodificacao ----------------------------------------------------
    def decode(
        self,
        data: bytes,
        offset: int = 0,
        max_bytes: int | None = None,
        stop_at_end: bool = True,
    ) -> Decoded:
        """Le bytes ate um token de fim, o limite ou o fim do buffer."""
        limit = len(data) if max_bytes is None else min(len(data), offset + max_bytes)
        out: list[str] = []
        pos = offset
        while pos < limit:
            for size in range(min(self._max_key, limit - pos), 0, -1):
                chunk = bytes(data[pos : pos + size])
                if chunk in self.entries:
                    out.append(self.entries[chunk])
                    pos += size
                    if stop_at_end and chunk in self.end_tokens:
                        return Decoded("".join(out), pos - offset, True)
                    break
            else:  # byte sem mapeamento -- preservado literalmente
                out.append(f"[${data[pos]:02X}]")
                pos += 1
        return Decoded("".join(out), pos - offset, False)

    # -- codificacao ------------------------------------------------------
    def encode(self, text: str) -> bytes:
        """Texto -> bytes, preferindo sempre a sequencia mais curta (usa DTE/MTE)."""
        out = bytearray()
        pos = 0
        n = len(text)
        while pos < n:
            if text[pos] == "[":
                match = TOKEN_RE.match(text, pos)
                if match:
                    token = match.group(0)
                    raw = self._reverse.get(token)
                    if raw is None:
                        inner = RAW_TOKEN_RE.match(match.group(1))
                        if inner is None:
                            raise TableError(f"token {token!r} nao existe na tabela")
                        raw = bytes.fromhex(inner.group(1))
                    out += raw
                    pos = match.end()
                    continue
            for size in range(min(self._max_value, n - pos), 0, -1):
                piece = text[pos : pos + size]
                raw = self._reverse.get(piece)
                if raw is not None:
                    out += raw
                    pos += size
                    break
            else:
                raise TableError(
                    f"caractere {text[pos]!r} (pos {pos}) nao existe na tabela {self.name!r}"
                )
        return bytes(out)

    # -- consultas --------------------------------------------------------
    def can_encode(self, text: str) -> bool:
        try:
            self.encode(text)
        except TableError:
            return False
        return True

    @property
    def letter_bytes(self) -> set[int]:
        """Bytes de 1 byte que mapeiam para texto imprimivel -- usado pelo scanner."""
        return {
            raw[0]
            for raw, value in self.entries.items()
            if len(raw) == 1 and value and not value.startswith("[")
        }

    def __len__(self) -> int:
        return len(self.entries)


def ascii_table(end_byte: int | None = 0x00) -> Table:
    """Tabela ASCII -- util para testes e para ROMs de GBA sem encoding proprio."""
    entries = {bytes([b]): chr(b) for b in range(0x20, 0x7F)}
    table = Table(entries=entries, name="ascii")
    if end_byte is not None:
        table.entries[bytes([end_byte])] = "[END]"
        table.end_tokens.add(bytes([end_byte]))
    table.reindex()
    return table
