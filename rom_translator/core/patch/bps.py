"""Formato BPS (beat patch system).

Estrutura:
    "BPS1"
    source-size (varint), target-size (varint), metadata-size (varint), metadata
    acoes ate (len(patch) - 12):
        varint: acao = valor & 3, tamanho = (valor >> 2) + 1
            0 SourceRead : copia do source no mesmo offset de saida
            1 TargetRead : `tamanho` bytes literais vindos do patch
            2 SourceCopy : varint com sinal ajusta o cursor do source, depois copia
            3 TargetCopy : idem, mas lendo da propria saida (permite RLE)
    footer: crc32 do source, do target e do proprio patch (4 bytes LE cada)

Ao contrario do IPS, o BPS carrega checksums -- aplicar um patch na ROM errada
falha em vez de gerar silenciosamente uma ROM corrompida.
"""

from __future__ import annotations

import zlib

MAGIC = b"BPS1"

SOURCE_READ = 0
TARGET_READ = 1
SOURCE_COPY = 2
TARGET_COPY = 3


class BpsError(ValueError):
    pass


class ChecksumMismatch(BpsError):
    pass


# -- varint ---------------------------------------------------------------
def encode_varint(number: int) -> bytes:
    out = bytearray()
    while True:
        x = number & 0x7F
        number >>= 7
        if number == 0:
            out.append(0x80 | x)
            break
        out.append(x)
        number -= 1
    return bytes(out)


def decode_varint(blob: bytes, pos: int) -> tuple[int, int]:
    data = 0
    shift = 1
    while True:
        if pos >= len(blob):
            raise BpsError("patch truncado ao ler um varint")
        x = blob[pos]
        pos += 1
        data += (x & 0x7F) * shift
        if x & 0x80:
            return data, pos
        shift <<= 7
        data += shift


def apply_bps(source: bytes, patch: bytes, verify: bool = True) -> bytes:
    if patch[:4] != MAGIC:
        raise BpsError("nao e um patch BPS (magic 'BPS1' ausente)")
    if len(patch) < 4 + 12:
        raise BpsError("patch BPS curto demais")

    if verify:
        want = int.from_bytes(patch[-12:-8], "little")
        got = zlib.crc32(source) & 0xFFFFFFFF
        if want != got:
            raise ChecksumMismatch(
                f"ROM de origem errada: patch espera crc32 {want:08x}, recebeu {got:08x}"
            )
        want_patch = int.from_bytes(patch[-4:], "little")
        got_patch = zlib.crc32(patch[:-4]) & 0xFFFFFFFF
        if want_patch != got_patch:
            raise ChecksumMismatch("o proprio arquivo .bps esta corrompido")

    pos = 4
    source_size, pos = decode_varint(patch, pos)
    target_size, pos = decode_varint(patch, pos)
    metadata_size, pos = decode_varint(patch, pos)
    pos += metadata_size

    if verify and source_size != len(source):
        raise ChecksumMismatch(
            f"tamanho da ROM de origem nao bate: patch espera {source_size}, recebeu {len(source)}"
        )

    target = bytearray(target_size)
    out_off = src_rel = tgt_rel = 0
    end = len(patch) - 12

    while pos < end:
        value, pos = decode_varint(patch, pos)
        action = value & 3
        length = (value >> 2) + 1

        if action == SOURCE_READ:
            target[out_off : out_off + length] = source[out_off : out_off + length]
            out_off += length
        elif action == TARGET_READ:
            target[out_off : out_off + length] = patch[pos : pos + length]
            pos += length
            out_off += length
        elif action == SOURCE_COPY:
            value, pos = decode_varint(patch, pos)
            src_rel += -(value >> 1) if value & 1 else (value >> 1)
            target[out_off : out_off + length] = source[src_rel : src_rel + length]
            src_rel += length
            out_off += length
        else:  # TARGET_COPY -- pode se sobrepor, precisa ser byte a byte
            value, pos = decode_varint(patch, pos)
            tgt_rel += -(value >> 1) if value & 1 else (value >> 1)
            for _ in range(length):
                target[out_off] = target[tgt_rel]
                tgt_rel += 1
                out_off += 1

    if out_off != target_size:
        raise BpsError(f"saida com {out_off} bytes, patch declara {target_size}")

    if verify:
        want = int.from_bytes(patch[-8:-4], "little")
        got = zlib.crc32(target) & 0xFFFFFFFF
        if want != got:
            raise ChecksumMismatch("a ROM gerada nao bate com o checksum do patch")

    return bytes(target)


def create_bps(source: bytes, target: bytes, metadata: bytes = b"") -> bytes:
    """Gera um patch BPS.

    Codificador linear: emite SourceRead nos trechos identicos e TargetRead nos
    divergentes. Nao usa SourceCopy/TargetCopy (que capturariam blocos movidos),
    mas para patch de traducao -- onde a ROM muda pouco e no lugar -- o ganho
    seria marginal e o custo em complexidade, alto.
    """
    out = bytearray(MAGIC)
    out += encode_varint(len(source))
    out += encode_varint(len(target))
    out += encode_varint(len(metadata))
    out += metadata

    def emit(action: int, length: int, payload: bytes = b"") -> None:
        out.extend(encode_varint(((length - 1) << 2) | action))
        out.extend(payload)

    n = len(target)
    common = min(len(source), n)
    pos = 0
    while pos < n:
        if pos < common and source[pos] == target[pos]:
            start = pos
            while pos < common and source[pos] == target[pos]:
                pos += 1
            emit(SOURCE_READ, pos - start)
        else:
            start = pos
            # so encerra o literal apos 4 bytes iguais seguidos: quebrar antes
            # custa mais em cabecalho do que economiza em payload
            while pos < n:
                if pos < common and source[pos] == target[pos]:
                    run = 0
                    while pos + run < common and source[pos + run] == target[pos + run]:
                        run += 1
                        if run >= 4:
                            break
                    if run >= 4:
                        break
                pos += 1
            emit(TARGET_READ, pos - start, target[start:pos])

    out += (zlib.crc32(source) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(target) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(bytes(out)) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)
