"""Formato IPS (International Patching System).

Layout:
    "PATCH"
    registros:
        offset  : 3 bytes big-endian
        tamanho : 2 bytes big-endian
        se tamanho == 0  -> registro RLE: contagem (2 BE) + byte repetido (1)
        senao            -> `tamanho` bytes literais
    "EOF"
    [truncate: 3 bytes BE opcionais]

Limites do formato: offset < 16 MiB, tamanho de registro < 65536.
"""

from __future__ import annotations

MAGIC = b"PATCH"
EOF_MARK = b"EOF"
MAX_OFFSET = 0xFFFFFF
MAX_CHUNK = 0xFFFF
#: offset que colide com o marcador "EOF" ao ser escrito como 3 bytes BE
EOF_OFFSET = 0x454F46


class IpsError(ValueError):
    pass


def apply_ips(source: bytes, patch: bytes) -> bytes:
    if patch[:5] != MAGIC:
        raise IpsError("nao e um patch IPS (magic 'PATCH' ausente)")
    out = bytearray(source)
    pos = 5
    while True:
        if pos + 3 > len(patch):
            raise IpsError("patch truncado: faltou o marcador EOF")
        if patch[pos : pos + 3] == EOF_MARK:
            pos += 3
            break
        offset = int.from_bytes(patch[pos : pos + 3], "big")
        pos += 3
        if pos + 2 > len(patch):
            raise IpsError("patch truncado no campo de tamanho")
        size = int.from_bytes(patch[pos : pos + 2], "big")
        pos += 2
        if size == 0:  # registro RLE
            count = int.from_bytes(patch[pos : pos + 2], "big")
            value = patch[pos + 2]
            pos += 3
            payload = bytes([value]) * count
        else:
            payload = patch[pos : pos + size]
            if len(payload) != size:
                raise IpsError("patch truncado no payload de um registro")
            pos += size
        end = offset + len(payload)
        if end > len(out):
            out.extend(b"\x00" * (end - len(out)))
        out[offset:end] = payload
    # campo opcional de truncamento
    if pos + 3 <= len(patch):
        truncate = int.from_bytes(patch[pos : pos + 3], "big")
        del out[truncate:]
    return bytes(out)


def _runs(source: bytes, target: bytes):
    """Gera (inicio, fim) de cada trecho divergente entre source e target.

    Trechos iguais com menos de 6 bytes sao absorvidos no registro: quebrar um
    registro custa 5 bytes de cabecalho, entao nao compensa.
    """
    n = len(target)
    src_len = len(source)
    i = 0
    while i < n:
        if i < src_len and source[i] == target[i]:
            i += 1
            continue
        start = i
        gap = 0
        while i < n:
            same = i < src_len and source[i] == target[i]
            i += 1
            if same:
                gap += 1
                if gap >= 6:
                    break
            else:
                gap = 0
        end = i - gap
        yield start, end
        i = end + gap


def _emit(out: bytearray, target: bytes, offset: int, end: int) -> None:
    """Escreve um trecho como registros IPS, respeitando os limites do formato."""
    while offset < end:
        if offset == EOF_OFFSET:
            # um registro nunca pode comecar em 0x454F46: os 3 bytes de offset
            # seriam lidos como o marcador "EOF". Recua um byte -- reescrever um
            # byte identico e inofensivo.
            offset -= 1
        stop = min(offset + MAX_CHUNK, end)
        piece = target[offset:stop]
        if len(piece) >= 4 and len(set(piece)) == 1:
            # RLE: 3 bytes de payload em vez de len(piece)
            out += offset.to_bytes(3, "big") + b"\x00\x00"
            out += len(piece).to_bytes(2, "big") + piece[:1]
        else:
            out += offset.to_bytes(3, "big") + len(piece).to_bytes(2, "big") + piece
        offset = stop


def create_ips(source: bytes, target: bytes) -> bytes:
    """Gera um patch IPS que transforma `source` em `target`."""
    if len(target) > MAX_OFFSET + 1:
        raise IpsError(
            f"IPS endereca no maximo 16 MiB; alvo tem {len(target)} bytes. Use BPS."
        )
    out = bytearray(MAGIC)
    for start, end in _runs(source, target):
        if start > MAX_OFFSET:
            raise IpsError("diferenca alem do limite de 16 MiB do IPS. Use BPS.")
        _emit(out, target, start, end)
    out += EOF_MARK
    if len(target) < len(source):
        out += len(target).to_bytes(3, "big")
    return bytes(out)
