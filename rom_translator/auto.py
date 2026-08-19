"""Modo automatico: da ROM ao patch num comando so.

Duas travas moldam este fluxo, e as duas existem porque falhar depois sai caro:

* **A triagem decide se comeca.** Jogo que comprime dialogo nao tem como ser
  traduzido sem a tabela de compressao, e insistir produz lixo com cara de
  progresso. O `auto` recusa e diz o porque.
* **O round-trip vem antes da traducao.** Se reinserir o texto *original* nao
  devolve a ROM byte a byte, o dump esta errado -- e qualquer traducao
  construida em cima corrompe o jogo num ponto que so aparece horas depois. E
  a checagem mais barata do pipeline e a unica que autoriza o resto.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import engines as engine_registry
from . import platforms
from .core.insert import insert
from .core.patch import create_bps, create_ips
from .core.rom import Rom
from .core.scanner import find_text_regions, guess_alphabet, looks_like_language
from .core.script import Script
from .core.table import Table
from .core.triage import triar
from .project import Block, Project


@dataclass
class AutoReport:
    veredito: str = ""
    explicacao: str = ""
    blocos: int = 0
    unidades: int = 0
    round_trip_ok: bool = False
    round_trip_quebradas: int = 0
    traduzidas: int = 0
    escritas: int = 0
    nao_couberam: int = 0
    acentos: list[tuple[str, int]] = field(default_factory=list)
    transliteradas: int = 0
    saidas: dict[str, Path] = field(default_factory=dict)


def sem_acento(texto: str) -> str:
    """Tira acentos preservando a letra: 'ação' -> 'acao'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def escolher_doadores(
    traducoes: list[str], script: Script, tabela: Table, precisa: list[str]
) -> list[str]:
    """Letras cujo tile pode virar acento, das que menos custam.

    O criterio nao e "o que o portugues nao usa" -- e "o que *este jogo* nao usa".
    Uma letra ausente do script inteiro custa zero; uma que aparece em falas ainda
    nao traduzidas custa aquelas ocorrencias virarem um caractere errado na tela.
    """
    usadas_na_traducao = {c for t in traducoes for c in t}
    frequencia_no_jogo = Counter(c for u in script.units for c in u.text)
    candidatas = [
        letra
        for letra in (tabela.entries[raw] for raw in tabela.entries if len(raw) == 1)
        if len(letra) == 1 and letra.isalpha() and letra not in usadas_na_traducao
    ]
    candidatas.sort(key=lambda c: frequencia_no_jogo.get(c, 0))
    return candidatas[: len(precisa)]


def acentos_necessarios(traducoes: list[str], tabela: Table) -> list[str]:
    """Letras acentuadas que aparecem nas traducoes e a tabela ainda nao tem."""
    from .core.tiles import ACCENTS

    contagem = Counter(
        c for t in traducoes for c in t if c in ACCENTS and not tabela.can_encode(c)
    )
    return [letra for letra, _ in contagem.most_common()]


def run_auto(
    rom_path: Path,
    out_dir: Path,
    engine_name: str = "claude",
    target_lang: str = "pt-BR",
    game: str = "",
    glossary: dict[str, str] | None = None,
    engine_kwargs: dict | None = None,
    accents: bool = True,
    force: bool = False,
    limit: int | None = None,
    min_chars: int = 6,
    window: int = 64,
    log=print,
) -> AutoReport:
    """Roda a cadeia inteira: triagem, extracao, traducao, fonte, patch."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nome = rom_path.stem
    report = AutoReport()

    rom = Rom.load(rom_path)
    plugin, det = platforms.identify(rom.data)
    data = bytes(rom.data)
    log(f"{det.platform}/{det.mapper}" + (f"  {det.title}" if det.title else ""))

    # 1. triagem -- decide se vale comecar
    regions = find_text_regions(
        data, window=window, stride=window // 2, threshold=0.35,
        min_length=window, limits=plugin.text_regions(data, det),
    )
    t = triar(data, plugin, det, regions)
    report.veredito, report.explicacao = t.veredito, t.explicacao
    report.blocos = t.blocos
    log(f"triagem: {t.veredito} -- {t.explicacao}")
    if t.veredito in ("texto comprimido", "sem texto legivel") and not force:
        return report

    # 2. alfabeto e projeto
    guess = guess_alphabet(data, regions)
    if guess is None:
        report.explicacao = "nao consegui deduzir o alfabeto"
        return report
    tabela = Table.parse(guess.as_table_source())
    caminho_tabela = out_dir / f"{nome}.tbl"
    caminho_tabela.write_text(tabela.dumps(), encoding="utf-8")

    projeto = Project(
        rom_path=str(rom_path), rom_sha1=rom.sha1(), platform=det.platform,
        mapper=det.mapper, table_path=caminho_tabela.name,
        blocks=[Block(id=f"b{i:03d}", start=r.start, end=r.end, kind="greedy",
                      score=r.score) for i, r in enumerate(regions)],
        notes="gerado por 'rom-translator auto'",
    )
    caminho_projeto = projeto.save(out_dir / f"{nome}.yaml")

    # 3. extracao
    script = projeto.dump(rom, tabela)
    script.units = [
        u for u in script.units
        if len(u.text.strip()) >= min_chars and looks_like_language(u.text)
    ]
    report.unidades = len(script.units)
    log(f"extraidas {len(script.units):,} unidades")

    # 4. round-trip antes de qualquer traducao
    from .core.insert import verify_roundtrip


    quebradas = verify_roundtrip(rom, script, tabela)
    report.round_trip_quebradas = len(quebradas)
    report.round_trip_ok = not quebradas
    if quebradas:
        log(f"round-trip falhou em {len(quebradas)} unidades -- abortando antes de traduzir")
        return report
    log(f"round-trip: {len(script.units):,} unidades voltam identicas")

    # 5. traducao
    config = engine_registry.EngineConfig(
        target_lang=target_lang, game=game or nome, glossary=glossary or {}
    )
    engine = engine_registry.build(engine_name, config, **(engine_kwargs or {}))
    alvos = script.units[:limit] if limit else script.units
    _traduzir(engine, alvos, log)
    engine.close()
    traduzidas = [u for u in script.units if u.translated]
    report.traduzidas = len(traduzidas)
    log(f"traduzidas {len(traduzidas):,} unidades")
    if not traduzidas:
        return report

    # 6. acentos: desenhar os glifos que faltam
    if accents:
        _acentuar(rom, tabela, script, traduzidas, plugin, det, caminho_tabela, report, log)

    # 7. o que ainda nao codifica perde o acento em vez de perder a linha
    for u in traduzidas:
        if u.translation and not tabela.can_encode(u.translation):
            simples = sem_acento(u.translation)
            if tabela.can_encode(simples):
                u.translation = simples
                report.transliteradas += 1
    if report.transliteradas:
        log(f"{report.transliteradas:,} traducoes perderam o acento por falta de tile")

    script.save(out_dir / f"{nome}.script.json")

    # 8. reinsercao e patch
    relatorio = insert(rom, script, tabela)
    report.escritas = relatorio.written
    report.nao_couberam = len(relatorio.overflow)
    if det.platform == "snes":
        from .platforms.snes import fix_checksum

        fix_checksum(rom.data, det.details["header_offset"])

    rom_saida = out_dir / f"{nome} [{target_lang}]{rom_path.suffix}"
    rom.save(rom_saida)
    bps = out_dir / f"{nome} [{target_lang}].bps"
    bps.write_bytes(create_bps(data, bytes(rom.data)))
    ips = out_dir / f"{nome} [{target_lang}].ips"
    try:
        ips.write_bytes(create_ips(data, bytes(rom.data)))
    except ValueError:
        ips = None  # passou dos 16 MiB do IPS

    report.saidas = {"projeto": caminho_projeto, "tabela": caminho_tabela,
                     "rom": rom_saida, "bps": bps}
    if ips:
        report.saidas["ips"] = ips
    log(f"escritas {relatorio.written:,} unidades"
        + (f", {len(relatorio.overflow):,} nao couberam" if relatorio.overflow else ""))
    return report


def _traduzir(engine, unidades, log) -> None:
    from .engines.base import TranslationRequest, mask_controls, unmask_controls

    tamanho = engine.config.batch_size
    for inicio in range(0, len(unidades), tamanho):
        lote = unidades[inicio : inicio + tamanho]
        pedidos, tokens = [], {}
        for u in lote:
            texto, marcas = mask_controls(u.text)
            tokens[u.id] = marcas
            pedidos.append(TranslationRequest(id=u.id, text=texto, max_chars=u.max_len))
        try:
            resultados = engine.translate_batch(pedidos)
        except Exception as exc:
            log(f"  lote falhou: {exc}")
            continue
        for u, r in zip(lote, resultados):
            if r.text is not None:
                u.translation = unmask_controls(r.text, tokens[u.id])


def _acentuar(rom, tabela, script, traduzidas, plugin, det, caminho_tabela, report, log) -> None:
    """Gera os glifos acentuados que as traducoes pedirem, se houver como."""
    from .core.tiles import (
        ACCENTS, TILE_BYTES, NoRoomForDiacritic, add_diacritic, decode_tile,
        encode_tile, find_free_tiles,
    )

    textos = [u.translation for u in traduzidas if u.translation]
    precisa = acentos_necessarios(textos, tabela)
    if not precisa:
        return
    if det.platform != "nes" or not det.details.get("chr_size"):
        log(f"{len(precisa)} acentos necessarios, mas nao sei onde fica a fonte "
            "desta ROM -- o texto sai sem acento")
        return

    offset, fmt = det.details["chr_offset"], "nes2bpp"
    tamanho = TILE_BYTES[fmt]
    usados = {raw[0] for raw in tabela.entries if len(raw) == 1}
    total = (rom.size - offset) // tamanho
    pool = [i for i in find_free_tiles(bytes(rom.data), offset, min(total, 256), fmt, usados)
            if i < 256]
    doadores = escolher_doadores(textos, script, tabela, precisa[len(pool):])
    for letra in doadores:
        raw = tabela.bytes_for(letra)
        if raw and len(raw) == 1:
            del tabela.entries[raw]
            tabela.reindex()
            pool.append(raw[0])
    log(f"acentos: {len(precisa)} necessarios, {len(pool)} tiles disponiveis"
        + (f" (sacrificando {' '.join(doadores)})" if doadores else ""))

    for letra in precisa:
        if not pool:
            break
        base, marca = ACCENTS[letra]
        origem = tabela.bytes_for(base)
        if not origem or len(origem) != 1:
            continue
        tile = decode_tile(bytes(rom.data), offset + origem[0] * tamanho, fmt)
        try:
            novo = add_diacritic(tile, marca)
        except NoRoomForDiacritic:
            continue
        alvo = pool.pop(0)
        rom.write(offset + alvo * tamanho, encode_tile(novo, fmt))
        tabela.entries[bytes([alvo])] = letra
        report.acentos.append((letra, alvo))
    tabela.reindex()
    caminho_tabela.write_text(tabela.dumps(), encoding="utf-8")
    if report.acentos:
        log("  desenhados: " + " ".join(f"{l}=0x{b:02X}" for l, b in report.acentos))
