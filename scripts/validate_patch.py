#!/usr/bin/env python3
"""Transforma qualquer par ROM + patch de traducao humana num gabarito.

Uma traducao de fa e um dataset rotulado de graca. Os tradutores marcaram, byte
a byte, onde o texto do jogo esta -- e as vezes tambem onde ficam os ponteiros e
os glifos da fonte. Este script le tudo isso de volta e mede as partes da
ferramenta que so dava para conferir a olho:

  1. aplicacao de patch e round-trip dos dois formatos;
  2. **recall do scanner** -- quanto do que o humano mexeu a deteccao encontra;
  3. **alfabeto** deduzido, contra o que o diff sugere;
  4. **ponteiros** -- se o humano reescreveu ponteiros, quantos deles o
     `pointers` acha (unica medida real de realocacao que existe);
  5. **fonte** -- se o humano editou tiles, onde, e quantos glifos criou.

Uso:
    python scripts/validate_patch.py ROM_ORIGINAL PATCH [--json saida.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rom_translator.core.patch import (  # noqa: E402
    apply_bps, apply_ips, create_bps, create_ips, detect_format,
)
from rom_translator.core.pointers import find_pointers  # noqa: E402
from rom_translator.core.rom import Rom  # noqa: E402
from rom_translator.core.scanner import find_text_regions, guess_alphabet  # noqa: E402
from rom_translator.core.table import Table  # noqa: E402
from rom_translator.platforms import identify  # noqa: E402


def diff_runs(a: bytes, b: bytes) -> list[tuple[int, int]]:
    runs, i, n = [], 0, min(len(a), len(b))
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom")
    parser.add_argument("patch")
    parser.add_argument("--json", dest="json_out", help="grava as metricas em JSON")
    args = parser.parse_args()

    rom = Rom.load(args.rom)
    plugin, det = identify(rom.data)
    original = bytes(rom.data)
    blob = Path(args.patch).read_bytes()
    fmt = detect_format(blob)

    print(f"ROM      : {det.title or Path(args.rom).stem!r}")
    print(f"           {det.platform}/{det.mapper}, {rom.size:,} bytes, md5 {rom.md5()}")
    print(f"patch    : {fmt.upper()}, {len(blob):,} bytes\n")

    results, metrics = [], {"platform": det.platform, "mapper": det.mapper}

    print("1. aplicacao e round-trip")
    if fmt == "ips":
        patched = apply_ips(original, blob)
    elif fmt == "bps":
        patched = apply_bps(original, blob)
    else:
        print(f"  formato {fmt} nao suportado")
        return 2
    results.append(check("patch aplicado", len(patched) >= len(original),
                         f"crc32 {Rom.from_bytes(patched).crc32():08x}"))
    results.append(check("IPS: create + apply devolve o mesmo",
                         apply_ips(original, create_ips(original, patched)) == patched))
    results.append(check("BPS: create + apply devolve o mesmo",
                         apply_bps(original, create_bps(original, patched)) == patched))

    if det.platform == "snes":
        from rom_translator.platforms.snes import checksum_valid

        header = det.details["header_offset"]
        results.append(check(
            "checksum interno da ROM traduzida continua valido",
            checksum_valid(patched, header),
            "-- prova independente de que a aplicacao ficou correta",
        ))

    print("\n2. dataset extraido do diff")
    runs = diff_runs(original, patched)
    changed = sum(end - start for start, end in runs)
    metrics |= {"diff_runs": len(runs), "diff_bytes": changed,
                "diff_fraction": changed / len(original)}
    print(f"  {len(runs):,} regioes alteradas, {changed:,} bytes "
          f"({changed / len(original):.1%} da ROM)")
    if len(patched) > len(original):
        print(f"  ROM expandida pelo tradutor: +{len(patched) - len(original):,} bytes")

    print("\n3. recall do scanner")
    limits = plugin.text_regions(original, det)
    regions = find_text_regions(original, limits=limits)
    marked = bytearray(len(original))
    for region in regions:
        marked[region.start : region.end] = b"\x01" * region.length
    total = hit = 0
    for start, end in runs:
        for offset in range(start, min(end, len(marked))):
            total += 1
            hit += marked[offset]
    recall = hit / total if total else 0.0
    flagged = sum(r.length for r in regions) / len(original)
    metrics |= {"scanner_recall": recall, "scanner_flagged": flagged,
                "scanner_blocks": len(regions)}
    print(f"  {len(regions):,} blocos, {flagged:.1%} da ROM sinalizada")
    results.append(check(f"recall de {recall:.1%}", recall >= 0.80, "-- meta: 80%"))

    print("\n4. alfabeto deduzido")
    guess = guess_alphabet(original, regions)
    if guess is None:
        results.append(check("alfabeto deduzido", False))
    else:
        upper = f"0x{guess.upper_base:02X}" if guess.upper_base is not None else "-"
        print(f"  espaco=0x{guess.space:02X}  a-z=0x{guess.lower_base:02X}  A-Z={upper}")
        print(f"  {guess.word_hits} palavras reais contra {guess.runner_up_hits} do 2o")
        metrics |= {"space": guess.space, "lower": guess.lower_base, "upper": guess.upper_base}
        table = Table.parse(guess.as_table_source())
        maior = max(runs, key=lambda r: r[1] - r[0])
        amostra = table.decode(original, maior[0], min(70, maior[1] - maior[0]),
                               stop_at_end=False).text
        print(f"  amostra do maior bloco alterado: {amostra!r}")
        results.append(check("alfabeto encontrado", True))

    print("\n5. ponteiros reescritos pelo tradutor")
    # trechos alterados curtos e alinhados sao candidatos a ponteiro
    curtos = [r for r in runs if r[1] - r[0] <= 4]
    print(f"  {len(curtos):,} alteracoes de ate 4 bytes (candidatas a ponteiro)")
    alvos = {start: f"d{i}" for i, (start, _) in enumerate(runs) if _ - start >= 8}
    achadas = 0
    for spec in plugin.pointer_specs(det):
        tabelas = find_pointers(original, alvos, plugin, det, spec, min_run=8)
        achadas += len(tabelas)
    metrics |= {"short_diffs": len(curtos), "pointer_tables": achadas}
    print(f"  o `pointers` acha {achadas} tabelas apontando para o texto alterado")

    print("\n6. edicao de fonte")
    graficos = None
    if det.platform == "nes":
        graficos = (det.details["chr_offset"],
                    det.details["chr_offset"] + det.details["chr_size"])
    if graficos:
        lo, hi = graficos
        tocados = sum(1 for start, end in runs if start >= lo and end <= hi)
        bytes_fonte = sum(end - start for start, end in runs if start >= lo and end <= hi)
        metrics |= {"chr_runs": tocados, "chr_bytes": bytes_fonte}
        print(f"  {tocados} alteracoes dentro do CHR ({bytes_fonte:,} bytes) "
              f"-- ~{bytes_fonte // 16} tiles")
        if tocados:
            print("  o tradutor editou a fonte: da para comparar com `font accents`")
    else:
        print("  (so da para separar graficos automaticamente em NES)")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"\nmetricas gravadas em {args.json_out}")

    print()
    if all(results):
        print("todos os checks passaram.")
        return 0
    print("HOUVE FALHA.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
