"""Descoberta de tabelas de ponteiros.

Sem isso, traduzir so funciona quando o texto cabe exatamente no espaco do
original. Com isso, da para mover uma string para outro lugar da ROM e corrigir
quem apontava para ela.

Achar ponteiros por forca bruta gera muito falso positivo -- qualquer par de
bytes pode coincidir com um endereco valido. O filtro que resolve e estrutural:
ponteiros de verdade vivem em *tabelas*, lado a lado, com passo constante e
alvos em ordem crescente. Um acerto isolado e ruido; vinte em sequencia, nao.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..platforms.base import Detection, PlatformPlugin, PointerSpec


@dataclass
class PointerTable:
    offset: int  # onde a tabela comeca no arquivo
    count: int  # quantos ponteiros ela tem
    spec: PointerSpec
    #: offset do ponteiro -> offset do alvo no arquivo
    entries: dict[int, int] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.offset + self.count * self.spec.width


def _read_all(data: bytes, width: int) -> np.ndarray:
    """Le a ROM inteira como ponteiros little-endian em cada posicao possivel."""
    arr = np.frombuffer(data, dtype=np.uint8)
    out = np.zeros(len(arr) - width + 1, dtype=np.uint32)
    for shift in range(width):
        out |= arr[shift : len(arr) - width + 1 + shift].astype(np.uint32) << (8 * shift)
    return out


def find_pointers(
    data: bytes,
    targets: dict[int, str],
    plugin: PlatformPlugin,
    det: Detection,
    spec: PointerSpec,
    min_run: int = 8,
) -> list[PointerTable]:
    """Acha tabelas de ponteiros que apontam para os offsets em `targets`.

    `min_run` e o que separa sinal de ruido: quantos ponteiros consecutivos e
    validos uma tabela precisa ter para ser aceita.
    """
    wanted: dict[int, int] = {}
    for offset in targets:
        cpu = plugin.file_to_cpu(offset, det)
        if cpu is None:
            continue
        raw = spec.encode(cpu)
        if len(raw) != spec.width:
            continue
        wanted[int.from_bytes(raw, spec.endian)] = offset
    if not wanted:
        return []

    values = _read_all(data, spec.width)
    keys = np.array(sorted(wanted), dtype=np.uint32)
    positions = np.flatnonzero(np.isin(values, keys))
    if positions.size == 0:
        return []

    tables: list[PointerTable] = []
    run: list[int] = []

    def flush() -> None:
        """Aceita o maior trecho do run cujos alvos crescem monotonicamente.

        Uma tabela de ponteiros segue a ordem do texto que indexa; coincidencias
        nao. Mas descartar o run inteiro por causa de um falso positivo colado no
        fim perderia tabelas boas -- entao apara em vez de rejeitar.
        """
        if len(run) < min_run:
            return
        targets_in_run = [wanted[int(values[p])] for p in run]
        best = (0, 0)
        start = 0
        for index in range(1, len(run) + 1):
            if index == len(run) or targets_in_run[index] <= targets_in_run[index - 1]:
                if index - start > best[1] - best[0]:
                    best = (start, index)
                start = index
        lo, hi = best
        if hi - lo < min_run:
            return
        chosen = run[lo:hi]
        tables.append(
            PointerTable(
                offset=chosen[0],
                count=len(chosen),
                spec=spec,
                entries={p: wanted[int(values[p])] for p in chosen},
            )
        )

    for position in positions:
        if run and position - run[-1] == spec.width:
            run.append(int(position))
            continue
        flush()
        run = [int(position)]
    flush()
    return tables


def rewrite(
    data: bytearray,
    tables: list[PointerTable],
    moved: dict[int, int],
    plugin: PlatformPlugin,
    det: Detection,
) -> int:
    """Reescreve os ponteiros cujos alvos mudaram de lugar. Devolve quantos."""
    changed = 0
    for table in tables:
        for pointer_offset, target in table.entries.items():
            new_target = moved.get(target)
            if new_target is None or new_target == target:
                continue
            cpu = plugin.file_to_cpu(new_target, det)
            if cpu is None:
                raise ValueError(
                    f"alvo 0x{new_target:06X} nao e enderecavel em {det.mapper}"
                )
            raw = table.spec.encode(cpu)
            data[pointer_offset : pointer_offset + len(raw)] = raw
            changed += 1
    return changed
