"""CLI do rom-translator."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table as RichTable

from . import platforms
from .core.patch import apply_bps, apply_ips, create_bps, create_ips, detect_format
from . import engines as engine_registry
from .core.insert import Relocator, insert, verify_roundtrip
from .core.pointers import find_pointers
from .core.rom import Rom
from .core.scanner import find_text_regions, guess_alphabet, looks_like_language
from .core.space import SpaceAllocator, find_free_space
from .core.script import Script
from .core.table import Table
from .project import Block, PointerTableRef, Project

console = Console()
err = Console(stderr=True, style="bold red")


def _fail(message: str) -> None:
    err.print(f"erro: {message}")
    sys.exit(1)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option("0.1.0", prog_name="rom-translator")
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
        notes="gerado por 'rom-translator scan' -- revise os blocos antes de traduzir",
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


def _load_all(project_path: Path, script_path: Path, rom_override: Path | None):
    project = Project.load(project_path)
    rom = Rom.load(rom_override or project.rom_path)
    if rom.sha1() != project.rom_sha1:
        console.print("[yellow]aviso[/yellow] a ROM nao e a mesma registrada no projeto")
    table = project.load_table(project_path.parent)
    script = Script.load(script_path)
    return project, rom, table, script


@main.command()
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--rom", "rom_override", type=click.Path(exists=True, path_type=Path))
def verify(project_path: Path, script_path: Path, rom_override: Path | None) -> None:
    """Confere que reinserir o texto original nao altera um byte da ROM.

    E o teste que autoriza tudo o que vem depois: se a tabela for ambigua, uma
    traducao construida sobre ela corrompe a ROM sem avisar.
    """
    _, rom, table, script = _load_all(project_path, script_path, rom_override)
    broken = verify_roundtrip(rom, script, table)
    total = len(script.units)
    if not broken:
        console.print(f"[green]ok[/green] {total:,} unidades sobrevivem ao round-trip intactas")
        return
    console.print(
        f"[red]{len(broken):,} de {total:,} unidades nao voltam iguais[/red] "
        f"({len(broken) / total:.1%})"
    )
    for unit in broken[:10]:
        console.print(f"  [dim]0x{unit.offset:06X}[/dim] {unit.text!r}")
    sys.exit(1)


@main.command()
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@click.option("--rom", "rom_override", type=click.Path(exists=True, path_type=Path))
@click.option("--allow-overflow", is_flag=True,
              help="segue mesmo com traducoes que nao cabem (elas ficam no original)")
@click.option("--relocate", is_flag=True,
              help="move para espaco livre o que nao couber, reapontando os ponteiros")
@click.option("--min-free-run", default=64, show_default=True,
              help="tamanho minimo de um trecho para valer como espaco livre")
@click.option("--expand", is_flag=True,
              help="dobra a ROM e usa a area nova como espaco livre (exige ponteiro largo)")
def build(project_path: Path, script_path: Path, output: Path,
          rom_override: Path | None, allow_overflow: bool,
          relocate: bool, min_free_run: int, expand: bool) -> None:
    """Reinsere as traducoes e grava a ROM traduzida."""
    project, rom, table, script = _load_all(project_path, script_path, rom_override)
    plugin, det = platforms.identify(rom.data)

    relocator = None
    if relocate:
        specs = project.pointer_specs()
        if not specs:
            _fail("nenhuma tabela de ponteiros no projeto; rode 'pointers' antes de --relocate")
        header = det.details.get("header_offset")
        exclude = [(header, header + 64)] if header is not None else []
        expanded: tuple[int, int] | None = None
        if expand:
            expanded = rom.expand()
            console.print(
                f"[yellow]ROM expandida[/yellow] de {expanded[0]:,} para {expanded[1]:,} bytes "
                "-- so alcancavel por ponteiro largo, e nem todo emulador aceita"
            )
        regions = find_free_space(bytes(rom.data), min_run=min_free_run, exclude=exclude)
        allocator = SpaceAllocator(regions, bank_size=plugin.bank_size(det))
        relocator = Relocator(
            rom=rom, table=table, plugin=plugin, det=det,
            allocator=allocator, specs=specs,
        )
        console.print(
            f"espaco livre: {allocator.total_free:,} bytes em {len(allocator.regions)} trechos"
        )

    before = bytes(rom.data)
    report = insert(rom, script, table, relocator=relocator)

    if det.platform == "snes" and bytes(rom.data) != before:
        from .platforms.snes import fix_checksum

        fix_checksum(rom.data, det.details["header_offset"])

    console.print(
        f"escritas {report.written:,} unidades"
        + (f", {report.relocated:,} realocadas ({report.bytes_relocated:,} bytes)"
           if report.relocated else "")
        + (f", {report.skipped_untranslated:,} ainda sem traducao"
           if report.skipped_untranslated else "")
    )
    if report.overflow:
        console.print(f"[yellow]{len(report.overflow):,} traducoes nao couberam:[/yellow]")
        for unit, size in report.overflow[:8]:
            console.print(
                f"  [dim]0x{unit.offset:06X}[/dim] precisa de {size} bytes, cabe {unit.max_len}"
                f"  {unit.translation!r}"
            )
        if not allow_overflow:
            _fail("use --allow-overflow para gerar assim mesmo, ou encurte as traducoes")
    for unit, message in report.failed[:8]:
        console.print(f"  [red]0x{unit.offset:06X}[/red] {message}")

    rom.save(output)
    console.print(f"[green]ok[/green] ROM gravada em {output} (crc32 {rom.crc32():08x})")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="grava o script anotado com os ponteiros encontrados")
@click.option("--min-run", default=8, show_default=True,
              help="quantos ponteiros seguidos uma tabela precisa ter para valer")
@click.option("--rom", "rom_override", type=click.Path(exists=True, path_type=Path))
def pointers(project_path: Path, script_path: Path, output: Path | None,
             min_run: int, rom_override: Path | None) -> None:
    """Procura as tabelas de ponteiros que endereçam o texto extraido."""
    project, rom, _table, script = _load_all(project_path, script_path, rom_override)
    plugin, det = platforms.identify(rom.data)
    targets = {unit.offset: unit.id for unit in script.units}

    found = []
    for spec in plugin.pointer_specs(det):
        tables = find_pointers(bytes(rom.data), targets, plugin, det, spec, min_run=min_run)
        for table in tables:
            found.append((spec, table))
        console.print(f"{spec.name}: {len(tables)} tabelas")

    by_target: dict[int, list[int]] = {}
    for _spec, table in found:
        for pointer_offset, target in table.entries.items():
            by_target.setdefault(target, []).append(pointer_offset)
    for unit in script.units:
        unit.pointers = sorted(by_target.get(unit.offset, []))

    project.pointer_tables = [
        PointerTableRef(
            offset=table.offset, count=table.count,
            width=spec.width, endian=spec.endian, base=spec.base,
        )
        for spec, table in found
    ]
    project.save(project_path)

    covered = sum(1 for unit in script.units if unit.pointers)
    console.print(
        f"[green]ok[/green] {len(found)} tabelas, {covered:,} de {len(script.units):,} "
        f"unidades com ponteiro conhecido ({covered / max(len(script.units), 1):.1%})"
    )
    console.print(f"tabelas gravadas em {project_path}")
    for _spec, table in sorted(found, key=lambda item: -item[1].count)[:8]:
        console.print(
            f"  [dim]0x{table.offset:06X}[/dim] {table.count:4d} ponteiros de "
            f"{table.spec.width} bytes"
        )
    if output:
        script.save(output)
        console.print(f"script anotado gravado em {output}")


def _notify_telegram(message: str) -> None:
    """Avisa no Telegram ao fim de uma rodada longa, se as credenciais existirem."""
    env = Path.home() / ".config" / "secrets" / "telegram.env"
    if not env.exists():
        return
    values = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    token, chat = values.get("TELEGRAM_BOT_TOKEN"), values.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15
        )
    except Exception:  # notificacao nunca deve derrubar a traducao
        console.print("[dim]nao consegui avisar no Telegram[/dim]")


@main.command()
@click.argument("script_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="onde gravar (padrao: sobrescreve o proprio script)")
@click.option("-e", "--engine", "engine_name", default="dummy", show_default=True,
              type=click.Choice(sorted(engine_registry.ENGINES)))
@click.option("--to", "target_lang", default="pt-BR", show_default=True)
@click.option("--game", default="", help="nome do jogo, dado como contexto ao motor")
@click.option("--glossary", type=click.Path(exists=True, path_type=Path),
              help="YAML com 'original: traducao' -- nomes proprios, itens, lugares")
@click.option("--batch-size", default=40, show_default=True)
@click.option("--limit", type=int, help="traduz so as N primeiras unidades (teste barato)")
@click.option("--retranslate", is_flag=True, help="refaz o que ja estava traduzido")
@click.option("--notify", is_flag=True, help="avisa no Telegram ao terminar")
def translate(script_path: Path, output: Path | None, engine_name: str, target_lang: str,
              game: str, glossary: Path | None, batch_size: int, limit: int | None,
              retranslate: bool, notify: bool) -> None:
    """Traduz as unidades de um script com o motor escolhido."""
    import time

    from .engines.base import TranslationRequest, mask_controls, unmask_controls

    script = Script.load(script_path)
    output = output or script_path

    words: dict[str, str] = {}
    if glossary:
        import yaml

        words = {str(k): str(v) for k, v in (yaml.safe_load(glossary.read_text()) or {}).items()}

    config = engine_registry.EngineConfig(
        target_lang=target_lang, game=game, glossary=words, batch_size=batch_size
    )
    try:
        engine = engine_registry.build(engine_name, config)
    except Exception as exc:
        _fail(f"nao consegui iniciar o motor {engine_name!r}: {exc}")

    pending = [u for u in script.units if retranslate or not u.translated]
    if limit:
        pending = pending[:limit]
    if not pending:
        console.print("nada a traduzir")
        return

    # memoria de traducao: texto identico so vai uma vez ao motor
    memory = {u.text: u.translation for u in script.units if u.translated}
    reused = 0
    to_send = []
    for unit in pending:
        cached = memory.get(unit.text)
        if cached is not None and not retranslate:
            unit.translation = cached
            reused += 1
        else:
            to_send.append(unit)

    console.print(
        f"motor [cyan]{engine_name}[/cyan] -> {target_lang}: {len(to_send):,} unidades "
        f"em lotes de {batch_size}" + (f", {reused:,} reaproveitadas da memoria" if reused else "")
    )

    started = time.time()
    done = failed = 0
    with console.status("traduzindo...") as status:
        for start in range(0, len(to_send), batch_size):
            chunk = to_send[start : start + batch_size]
            masked = []
            tokens_by_id = {}
            for unit in chunk:
                masked_text, tokens = mask_controls(unit.text)
                tokens_by_id[unit.id] = tokens
                masked.append(
                    TranslationRequest(id=unit.id, text=masked_text, max_chars=unit.max_len)
                )
            try:
                results = engine.translate_batch(masked)
            except Exception as exc:  # rede, cota, timeout
                console.print(f"[yellow]lote falhou:[/yellow] {exc}")
                failed += len(chunk)
                continue
            for unit, result in zip(chunk, results):
                if result.text is None:
                    failed += 1
                    unit.note = result.note
                    continue
                unit.translation = unmask_controls(result.text, tokens_by_id[unit.id])
                memory[unit.text] = unit.translation
                done += 1
            status.update(f"traduzindo... {done + failed:,}/{len(to_send):,}")

    engine.close()
    script.save(output)
    elapsed = time.time() - started
    summary = (
        f"traducao concluida: {done:,} unidades em {elapsed / 60:.1f} min"
        + (f", {reused:,} da memoria" if reused else "")
        + (f", {failed:,} falharam" if failed else "")
    )
    console.print(f"[green]ok[/green] {summary} -> {output}")
    if notify:
        _notify_telegram(f"rom-translator: {summary}\narquivo: {output}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--rom", "rom_override", type=click.Path(exists=True, path_type=Path))
@click.option("--lexicon", "lexicon_path", type=click.Path(exists=True, path_type=Path),
              help="lista de palavras do idioma de ORIGEM (padrao: a do sistema)")
@click.option("--apply", "apply_to_table", is_flag=True,
              help="grava as propostas na tabela do projeto")
@click.option("--min-confidence", default=0.6, show_default=True)
@click.option("-n", "--count", default=30, show_default=True)
def dte(project_path: Path, rom_override: Path | None, lexicon_path: Path | None,
        apply_to_table: bool, min_confidence: float, count: int) -> None:
    """Propoe o que cada byte comprimido (DTE/MTE) representa.

    Sao propostas, nao certezas: confira antes de aceitar. O algoritmo so opina
    quando o lexico fixa a resposta, entao ele erra pouco -- mas cala em muitos
    bytes, e nenhum deles e necessariamente DTE.
    """
    from .core.dte import infer_dte
    from .core.lexicon import load_lexicon

    project = Project.load(project_path)
    rom = Rom.load(rom_override or project.rom_path)
    table = project.load_table(project_path.parent)
    plugin, det = platforms.identify(rom.data)

    words = load_lexicon(lexicon_path)
    if not words:
        _fail("nenhuma lista de palavras encontrada; passe --lexicon")
    console.print(f"lexico: {len(words):,} palavras")

    space_bytes = table.bytes_for(" ")
    if not space_bytes or len(space_bytes) != 1:
        _fail("a tabela do projeto nao define o byte de espaco")
    regions = [(b.start, b.end) for b in project.blocks]

    with console.status("deduzindo..."):
        guesses = infer_dte(
            bytes(rom.data), regions, table, space_bytes[0], lexicon=words,
            min_confidence=min_confidence,
        )
    if not guesses:
        console.print("nenhuma proposta passou nos criterios")
        return

    view = RichTable(show_header=True, box=None, pad_edge=False)
    view.add_column("byte", style="dim")
    view.add_column("expansao")
    view.add_column("ocorrencias", justify="right", style="dim")
    view.add_column("apoio", justify="right", style="dim")
    view.add_column("confianca", justify="right")
    for guess in guesses[:count]:
        view.add_row(f"0x{guess.byte:02X}", repr(guess.text), f"{guess.occurrences:,}",
                     f"{guess.hits} vs {guess.runner_up}", f"{guess.confidence:.2f}")
    console.print(view)
    console.print(f"[dim]{len(guesses)} propostas no total[/dim]")

    if apply_to_table:
        path = project_path.parent / project.table_path
        for guess in guesses:
            table.entries[bytes([guess.byte])] = guess.text
        table.reindex()
        path.write_text(table.dumps(), encoding="utf-8")
        console.print(f"[green]ok[/green] {len(guesses)} entradas somadas a {path}")


@main.group()
def font() -> None:
    """Inspeciona e edita os tiles da fonte da ROM."""


def _font_layout(rom: Rom, det, font_offset: int | None, fmt: str | None):
    """Descobre onde ficam os tiles e em que formato, ou usa o que foi passado."""
    if font_offset is None:
        if det.platform != "nes":
            _fail("passe --font-offset: so em NES da para deduzir (os graficos vem no CHR)")
        font_offset = det.details["chr_offset"]
    if fmt is None:
        fmt = "nes2bpp" if det.platform == "nes" else "snes2bpp"
    return font_offset, fmt


@font.command("show")
@click.argument("rom_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--font-offset", type=lambda v: int(v, 0), help="onde comecam os tiles")
@click.option("--format", "fmt", type=click.Choice(["nes2bpp", "snes2bpp", "snes4bpp"]))
@click.option("--first", default=0, type=lambda v: int(v, 0), show_default=True)
@click.option("-n", "--count", default=8, show_default=True)
def font_show(rom_path: Path, font_offset: int | None, fmt: str | None,
              first: int, count: int) -> None:
    """Desenha tiles no terminal, para localizar a fonte e conferir os glifos."""
    from .core.tiles import TILE_BYTES, decode_tile, render

    rom = Rom.load(rom_path)
    _plugin, det = platforms.identify(rom.data)
    font_offset, fmt = _font_layout(rom, det, font_offset, fmt)
    console.print(f"tiles em 0x{font_offset:06X}, formato {fmt}")
    for index in range(first, first + count):
        start = font_offset + index * TILE_BYTES[fmt]
        if start + TILE_BYTES[fmt] > rom.size:
            break
        console.print(f"\n[cyan]tile 0x{index:02X}[/cyan]")
        console.print(render(decode_tile(bytes(rom.data), start, fmt)))


@font.command("accents")
@click.argument("project_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path),
              help="ROM de saida, com os glifos acentuados gravados")
@click.option("--font-offset", type=lambda v: int(v, 0))
@click.option("--format", "fmt", type=click.Choice(["nes2bpp", "snes2bpp", "snes4bpp"]))
@click.option("--letters", default="áàâãéêíóôõúç", show_default=True,
              help="quais letras acentuadas gerar")
@click.option("--donors", help="bytes doadores separados por virgula (padrao: tiles em branco)")
@click.option("--sacrifice", help="letras cujos tiles podem ser reaproveitados, ex: k,w,y,K,W,Y")
def font_accents(project_path: Path, output: Path, font_offset: int | None,
                 fmt: str | None, letters: str, donors: str | None,
                 sacrifice: str | None) -> None:
    """Desenha letras acentuadas a partir das existentes e registra na tabela.

    Assume que o byte da tabela e o indice do tile -- convencao comum, e o caso
    do Dragon Warrior. Confira com `font show` antes de gravar.

    Fonte de jogo raramente tem slot sobrando: o Dragon Warrior tem dois. A saida
    classica e `--sacrifice`, que reaproveita o tile de letras que o idioma de
    destino nao usa (`k`, `w` e `y` em portugues). Elas saem da tabela, entao
    qualquer texto que ainda dependa delas passa a nao codificar -- e o `build`
    reclama em vez de escrever errado.
    """
    from .core.tiles import (
        ACCENTS, TILE_BYTES, NoRoomForDiacritic, add_diacritic, decode_tile,
        encode_tile, find_free_tiles,
    )

    project = Project.load(project_path)
    rom = Rom.load(project.rom_path)
    table = project.load_table(project_path.parent)
    _plugin, det = platforms.identify(rom.data)
    font_offset, fmt = _font_layout(rom, det, font_offset, fmt)
    size = TILE_BYTES[fmt]

    used = {raw[0] for raw in table.entries if len(raw) == 1}
    if donors:
        pool = [int(v, 0) for v in donors.split(",")]
    else:
        total = (rom.size - font_offset) // size
        pool = find_free_tiles(bytes(rom.data), font_offset, total, fmt, used)
        # so tiles enderecaveis por um byte de texto servem como doadores
        pool = [index for index in pool if index < 256]
        console.print(f"{len(pool)} tiles em branco e enderecaveis por um byte")
        if not pool:
            _fail(
                "nenhum tile em branco abaixo de 0x100; use --donors com bytes que "
                "o jogo nao usa (confira antes com 'font show')"
            )

    if sacrifice:
        for letra in [c.strip() for c in sacrifice.split(",") if c.strip()]:
            raw = table.bytes_for(letra)
            if not raw or len(raw) != 1:
                console.print(f"  [yellow]nao da para sacrificar {letra!r}[/yellow]: nao esta na tabela")
                continue
            del table.entries[raw]
            table.reindex()
            pool.append(raw[0])
        console.print(f"doadores apos os sacrificios: {len(pool)}")

    escritos, recusados = [], []
    for letra in letters:
        if letra not in ACCENTS:
            recusados.append(f"{letra} (acento nao suportado)")
            continue
        base, mark = ACCENTS[letra]
        origem = table.bytes_for(base)
        if not origem or len(origem) != 1:
            recusados.append(f"{letra} (a tabela nao tem {base!r})")
            continue
        if not pool:
            recusados.append(f"{letra} (acabaram os tiles doadores)")
            continue
        tile = decode_tile(bytes(rom.data), font_offset + origem[0] * size, fmt)
        try:
            novo = add_diacritic(tile, mark)
        except NoRoomForDiacritic as exc:
            recusados.append(f"{letra} ({exc})")
            continue
        alvo = pool.pop(0)
        rom.write(font_offset + alvo * size, encode_tile(novo, fmt))
        table.entries[bytes([alvo])] = letra
        escritos.append((letra, alvo))

    table.reindex()
    (project_path.parent / project.table_path).write_text(table.dumps(), encoding="utf-8")
    rom.save(output)

    console.print(
        "[green]ok[/green] "
        + " ".join(f"{letra}=0x{alvo:02X}" for letra, alvo in escritos)
        + f"  -> {output}"
    )
    for motivo in recusados:
        console.print(f"  [yellow]recusado[/yellow] {motivo}")
    console.print(f"tabela atualizada: {project_path.parent / project.table_path}")
    console.print(f"[dim]agora use --rom {output} nos proximos comandos[/dim]")


if __name__ == "__main__":
    main()
