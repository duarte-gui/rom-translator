"""CLI do romtrans."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table as RichTable

from . import platforms
from .core.patch import apply_bps, apply_ips, create_bps, create_ips, detect_format
from .core.rom import Rom
from .core.scanner import find_text_regions, guess_alphabet, looks_like_language
from .core.script import Script
from .core.table import Table
from .project import Block, Project

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

    table = RichTable(show_header=False, box=None, pad_edge=False)
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


@main.command()
@click.argument("rom_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", default="projeto.yaml", type=click.Path(path_type=Path),
              show_default=True, help="arquivo de projeto a gerar")
@click.option("-t", "--table", "table_path", type=click.Path(exists=True, path_type=Path),
              help="usa uma tabela .tbl pronta em vez de deduzir o alfabeto")
@click.option("--threshold", default=0.45, show_default=True,
              help="quao parecido com texto um bloco precisa ser (0 a 1)")
@click.option("--min-length", default=256, show_default=True,
              help="tamanho minimo de um bloco, em bytes")
def scan(rom_path: Path, output: Path, table_path: Path | None,
         threshold: float, min_length: int) -> None:
    """Procura os blocos de texto de uma ROM e deduz o alfabeto."""
    rom = Rom.load(rom_path)
    plugin, det = platforms.identify(rom.data)
    data = bytes(rom.data)

    limits = plugin.text_regions(data, det)
    regions = find_text_regions(data, threshold=threshold, min_length=min_length, limits=limits)
    if not regions:
        _fail("nenhum bloco com cara de texto encontrado; tente --threshold menor")
    covered = sum(r.length for r in regions)
    console.print(
        f"{det.platform}/{det.mapper}: {len(regions)} blocos, {covered:,} bytes "
        f"({covered / len(data):.1%} da ROM)"
    )

    project_dir = output.parent
    if table_path is not None:
        table = Table.load(table_path)
        table_name = str(table_path.relative_to(project_dir) if table_path.is_relative_to(project_dir) else table_path)
        console.print(f"tabela fornecida: {table_path} ({len(table)} entradas)")
    else:
        guess = guess_alphabet(data, regions)
        if guess is None:
            _fail("nao consegui deduzir o alfabeto; passe uma tabela com --table")
        table = Table.parse(guess.as_table_source())
        table_name = output.with_suffix(".tbl").name
        (project_dir / table_name).write_text(table.dumps(), encoding="utf-8")
        console.print(
            f"alfabeto deduzido: espaco=0x{guess.space:02X}  a-z=0x{guess.lower_base:02X}  "
            f"A-Z={('0x%02X' % guess.upper_base) if guess.upper_base is not None else '-'}  "
            f"({guess.word_hits} palavras reais contra {guess.runner_up_hits} do 2o lugar)"
        )
        console.print(f"tabela inicial gravada em {project_dir / table_name} "
                      f"[dim]-- acentos, pontuacao e codigos de controle ainda faltam[/dim]")

    project = Project(
        rom_path=str(rom_path), rom_sha1=rom.sha1(), platform=det.platform,
        mapper=det.mapper, table_path=table_name,
        blocks=[Block(id=f"b{i:03d}", start=r.start, end=r.end, kind="greedy", score=r.score)
                for i, r in enumerate(regions)],
        notes="gerado por 'romtrans scan' -- revise os blocos antes de traduzir",
    )
    project.save(output)
    console.print(f"[green]ok[/green] projeto gravado em {output}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", default="script.json", type=click.Path(path_type=Path),
              show_default=True)
@click.option("--rom", "rom_override", type=click.Path(exists=True, path_type=Path),
              help="usa outra ROM em vez da registrada no projeto")
@click.option("--min-chars", default=3, show_default=True,
              help="descarta unidades com menos caracteres que isso")
@click.option("--keep-noise", is_flag=True,
              help="nao aplica o filtro linguistico (mantem tudo que o scan achou)")
def dump(project_path: Path, output: Path, rom_override: Path | None,
         min_chars: int, keep_noise: bool) -> None:
    """Extrai as unidades de texto de um projeto para um script .json."""
    project = Project.load(project_path)
    base = project_path.parent
    rom = Rom.load(rom_override or project.rom_path)
    if rom.sha1() != project.rom_sha1:
        console.print("[yellow]aviso[/yellow] a ROM nao e a mesma registrada no projeto")
    table = project.load_table(base)

    script = project.dump(rom, table)
    found = len(script.units)
    script.units = [u for u in script.units if len(u.text.strip()) >= min_chars]
    if not keep_noise:
        script.units = [u for u in script.units if looks_like_language(u.text)]
    script.save(output)

    stats = script.stats()
    console.print(
        f"[green]ok[/green] {stats['unidades']:,} unidades, {stats['caracteres']:,} "
        f"caracteres -> {output}"
        + (f"  [dim]({found - stats['unidades']:,} descartadas pelos filtros)[/dim]"
           if found > stats["unidades"] else "")
    )
    for unit in script.units[:5]:
        console.print(f"  [dim]0x{unit.offset:06X}[/dim] {unit.text!r}")


@main.command()
@click.argument("script_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-n", "--count", default=25, show_default=True)
@click.option("--longest", is_flag=True, help="mostra as unidades mais longas")
def preview(script_path: Path, count: int, longest: bool) -> None:
    """Mostra uma amostra do texto extraido."""
    script = Script.load(script_path)
    units = sorted(script.units, key=lambda u: -len(u.text)) if longest else script.units
    view = RichTable(show_header=True, box=None, pad_edge=False)
    view.add_column("offset", style="dim")
    view.add_column("max", justify="right", style="dim")
    view.add_column("texto")
    for unit in units[:count]:
        view.add_row(f"0x{unit.offset:06X}", str(unit.max_len), unit.text)
    console.print(view)
    console.print(f"[dim]{script.stats()['unidades']:,} unidades no total[/dim]")


if __name__ == "__main__":
    main()
