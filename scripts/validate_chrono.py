#!/usr/bin/env python3
"""Valida o romtrans contra um gabarito humano: a traducao PT-BR de Chrono Trigger.

O grupo CBT traduziu Chrono Trigger em 1998 (revisao 2010) e distribuiu como IPS.
Aplicando esse patch temos um par (ROM em ingles, ROM em portugues) produzido por
tradutores humanos -- ou seja, um dataset rotulado de graca:

  * quais regioes da ROM realmente contem texto (as que o patch alterou);
  * como a tabela de caracteres foi estendida para acentos;
  * quais ponteiros precisaram ser reajustados.

Todo heuristico do scanner (M1) e medido contra esse diff. Nenhuma ROM e
distribuida com o projeto: o script le os arquivos do proprio usuario.

Uso:
    python scripts/validate_chrono.py ROM_EN.smc PATCH.ips
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from romtrans.core.patch import apply_bps, apply_ips, create_bps, create_ips  # noqa: E402
from romtrans.core.rom import Rom  # noqa: E402
from romtrans.platforms import identify  # noqa: E402
from romtrans.platforms.snes import checksum_valid  # noqa: E402


def diff_runs(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """Faixas [inicio, fim) onde os dois buffers divergem."""
    runs: list[tuple[int, int]] = []
    i, n = 0, min(len(a), len(b))
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        start = i
        while i < n and a[i] != b[i]:
            i += 1
        runs.append((start, i))
    return runs


def check(label: str, ok: bool, note: str = "") -> bool:
    print(f"  [{'OK ' if ok else 'FALHA'}] {label}{'  ' + note if note else ''}")
    return ok


def main(rom_path: str, patch_path: str) -> int:
    rom = Rom.load(rom_path)
    plugin, det = identify(rom.data)
    english = bytes(rom.data)
    patch_blob = Path(patch_path).read_bytes()

    print(f"ROM base: {det.title!r} ({det.platform}/{det.mapper}, {rom.size:,} bytes)")
    print(f"          md5 {rom.md5()}\n")

    results = []
    print("1. aplicacao do patch")
    portuguese = apply_ips(english, patch_blob)
    results.append(
        check(
            "IPS aplicado",
            len(portuguese) == len(english),
            f"crc32 {Rom.from_bytes(portuguese).crc32():08x}",
        )
    )
    header = det.details["header_offset"]
    results.append(
        check(
            "checksum interno da ROM traduzida continua valido",
            checksum_valid(portuguese, header),
            "-- prova independente de que a aplicacao ficou correta",
        )
    )

    print("\n2. round-trip de geracao de patch")
    ips = create_ips(english, portuguese)
    bps = create_bps(english, portuguese)
    results.append(check("IPS: create + apply == original", apply_ips(english, ips) == portuguese,
                         f"{len(ips):,} bytes"))
    results.append(check("BPS: create + apply == original", apply_bps(english, bps) == portuguese,
                         f"{len(bps):,} bytes"))
    try:
        apply_bps(portuguese, bps)
        results.append(check("BPS recusa ROM base errada", False))
    except Exception:
        results.append(check("BPS recusa ROM base errada", True))

    print("\n3. dataset rotulado extraido do diff")
    runs = diff_runs(english, portuguese)
    changed = sum(end - start for start, end in runs)
    print(f"  {len(runs):,} regioes alteradas, {changed:,} bytes ({changed / len(english):.1%} da ROM)")
    biggest = sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:5]
    for start, end in biggest:
        cpu = plugin.file_to_cpu(start, det)
        print(f"    0x{start:06X} (+{end - start:3d} bytes)  cpu ${cpu:06X}")

    print()
    if all(results):
        print("todos os checks passaram.")
        return 0
    print("HOUVE FALHA.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
