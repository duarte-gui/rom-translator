"""CLI do romtrans."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import platforms
from .core.patch import apply_bps, apply_ips, create_bps, create_ips, detect_format
from .core.rom import Rom

console = Console()
err = Console(stderr=True, style="bold red")


def _fail(message: str) -> None:
    err.print(f"erro: {message}")
    sys.exit(1)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option("0.1.0", prog_name="romtrans")
def main() -> None:
    """Pipeline de traducao de ROMs: identificar, extrair, traduzir, reinserir, gerar patch."""


@main.command()
@click.argument("rom_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def identify(rom_path: Path) -> None:
    """Identifica plataforma, mapeamento e hashes de uma ROM."""
    rom = Rom.load(rom_path)
    plugin, det = platforms.identify(rom.data)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("arquivo", str(rom_path))
    table.add_row("tamanho", f"{rom.size:,} bytes ({rom.size / 1024:.0f} KiB)")
    if rom.copier_header:
        table.add_row("header copiadora", "512 bytes (removido para analise)")
    table.add_row("plataforma", f"{det.platform}  (confianca {det.confidence:.0%})")
    if det.mapper:
        table.add_row("mapeamento", det.mapper)
    if det.title:
        table.add_row("titulo interno", det.title)
    for key, value in det.details.items():
        table.add_row(key, str(value))
    for key, value in rom.hashes().items():
        table.add_row(key, value)
    console.print(table)


@main.command()
@click.argument("rom_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("patch_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@click.option("--no-verify", is_flag=True, help="ignora os checksums de um patch BPS")
def apply(rom_path: Path, patch_path: Path, output: Path, no_verify: bool) -> None:
    """Aplica um patch (IPS ou BPS) a uma ROM."""
    rom = Rom.load(rom_path)
    blob = patch_path.read_bytes()
    fmt = detect_format(blob)

    if fmt == "ips":
        result = apply_ips(bytes(rom.data), blob)
    elif fmt == "bps":
        try:
            result = apply_bps(bytes(rom.data), blob, verify=not no_verify)
        except Exception as exc:  # checksum ou formato
            _fail(str(exc))
    else:
        _fail(f"formato de patch nao suportado: {fmt}")

    patched = Rom(data=bytearray(result), copier_header=rom.copier_header)
    patched.save(output)
    console.print(
        f"[green]ok[/green] {fmt.upper()} aplicado -> {output} "
        f"({patched.size:,} bytes, crc32 {patched.crc32():08x})"
    )


@main.command()
@click.argument("original", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("modified", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@click.option(
    "-f",
    "--format",
    "fmt",
    type=click.Choice(["bps", "ips"]),
    default="bps",
    show_default=True,
    help="BPS carrega checksum e nao tem limite de 16 MiB; IPS e o formato legado.",
)
def patch(original: Path, modified: Path, output: Path, fmt: str) -> None:
    """Gera um patch a partir de duas ROMs (a original e a traduzida)."""
    src = bytes(Rom.load(original).data)
    tgt = bytes(Rom.load(modified).data)
    if src == tgt:
        _fail("as duas ROMs sao identicas; nao ha o que empacotar")
    try:
        blob = create_bps(src, tgt) if fmt == "bps" else create_ips(src, tgt)
    except ValueError as exc:
        _fail(str(exc))
    output.write_bytes(blob)
    console.print(
        f"[green]ok[/green] {fmt.upper()} gerado -> {output} ({len(blob):,} bytes)"
    )


@main.command()
@click.argument("patch_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def inspect(patch_path: Path) -> None:
    """Mostra o que um patch altera, sem aplicar."""
    blob = patch_path.read_bytes()
    fmt = detect_format(blob)
    console.print(f"formato: [cyan]{fmt}[/cyan]   tamanho: {len(blob):,} bytes")
    if fmt != "ips":
        if fmt == "bps":
            from .core.patch.bps import decode_varint

            pos = 4
            src_size, pos = decode_varint(blob, pos)
            tgt_size, pos = decode_varint(blob, pos)
            console.print(f"source: {src_size:,} bytes -> target: {tgt_size:,} bytes")
            console.print(
                f"crc32 esperado da ROM base: "
                f"[yellow]{int.from_bytes(blob[-12:-8], 'little'):08x}[/yellow]"
            )
        return

    pos, records, total, lo, hi = 5, 0, 0, None, 0
    while blob[pos : pos + 3] != b"EOF":
        offset = int.from_bytes(blob[pos : pos + 3], "big")
        pos += 3
        size = int.from_bytes(blob[pos : pos + 2], "big")
        pos += 2
        if size == 0:
            count = int.from_bytes(blob[pos : pos + 2], "big")
            pos += 3
            length = count
        else:
            pos += size
            length = size
        records += 1
        total += length
        lo = offset if lo is None else min(lo, offset)
        hi = max(hi, offset + length)
    console.print(
        f"registros: {records}   bytes alterados: {total:,}\n"
        f"faixa tocada: 0x{lo:06X} - 0x{hi:06X}"
    )


if __name__ == "__main__":
    main()
