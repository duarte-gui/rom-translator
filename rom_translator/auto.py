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

import re
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
    realocadas: int = 0
    terminador: int | None = None
    largura_linha: int | None = None
    tabelas_de_ponteiro: int = 0
    motivo_sem_realocar: str = ""
    nomes_proprios: list[str] = field(default_factory=list)
    acentos: list[tuple[str, int]] = field(default_factory=list)
    transliteradas: int = 0
    espremidas: int = 0
    encurtadas: int = 0
    repetidas: int = 0
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


#: fracao minima das frases que precisam terminar no mesmo byte para que ele
#: seja aceito como terminador sem o usuario dizer. Medido em tres ROMs, o
#: melhor candidato ficou em 44% (Faxanadu), 22% (Dragon Warrior) e 19%
#: (Castlevania) -- ou seja, na pratica nenhuma passa, e e esse o ponto: mover
#: uma string cujo fim eu adivinhei errado corrompe o jogo em silencio
CONFIANCA_TERMINADOR = 0.60


def inferir_terminador(
    data: bytes, regions, tabela: Table
) -> tuple[int, float] | None:
    """Byte que fecha as frases, se houver um dominante o bastante.

    Devolve None quando a evidencia e fraca -- e quase sempre e. Sem terminador
    o realocador se recusa a mover a string, o que e o comportamento certo: o
    jogo leria alem dela ate topar com um byte de fim por acaso.
    """
    import numpy as np

    letras = tabela.letter_bytes
    if not letras:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    e_letra = np.zeros(256, dtype=bool)
    for b in letras:
        e_letra[b] = True

    depois: Counter[int] = Counter()
    for region in regions:
        trecho = arr[region.start : region.end]
        marca = e_letra[trecho]
        i = 0
        while i < len(trecho):
            if not marca[i]:
                i += 1
                continue
            inicio = i
            while i < len(trecho) and marca[i]:
                i += 1
            if i - inicio >= 4 and i < len(trecho):
                depois[int(trecho[i])] += 1
    total = sum(depois.values())
    if not total:
        return None
    byte, quantas = depois.most_common(1)[0]
    return byte, quantas / total


def nomes_proprios(script: Script, lexico: set[str]) -> dict[str, str]:
    """Nomes que o jogo inventou, pescados pela maiuscula fora do inicio da frase.

    Maiuscula no meio de uma frase quase sempre e nome proprio, e nome proprio
    ausente de qualquer dicionario e quase sempre invencao do jogo. No Dragon
    Warrior isso devolve o elenco e a geografia inteiros -- Dragonlord, Erdrick,
    Gwaelin, Lorik, Tantegel, Garinham -- sem um falso positivo.

    Vao para o glossario como `nome -> nome`, que e a instrucao de nao traduzir.
    """
    contagem: Counter[str] = Counter()
    for unidade in script.units:
        tokens = unidade.text.split()
        for indice, token in enumerate(tokens):
            limpo = token.strip(".,!?'\"[]")
            if indice == 0 or len(limpo) < 3 or not limpo.isalpha():
                continue
            if limpo[0].isupper() and limpo.lower() not in lexico:
                contagem[limpo] += 1
    return {nome: nome for nome, _ in contagem.most_common()}


def tem_palavra_real(texto: str, lexico: set[str], minimo: int = 3) -> bool:
    """Ao menos uma palavra do idioma de origem aparece inteira aqui.

    Sem isso, bloco de grafico que o scanner marcou como texto chega ao modelo --
    e modelo de linguagem nunca responde "isso nao e texto". Ele traduziu
    `ihiyyA` para `Ola` e `wiyyyAwwy` para `Ei voce`, invencoes que seriam
    gravadas por cima dos graficos do jogo.
    """
    for token in texto.split():
        limpo = token.lower().strip(".,!?'\"[]")
        if len(limpo) >= minimo and limpo.isalpha() and limpo in lexico:
            return True
    return False


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
    table_path: Path | None = None,
    engine_kwargs: dict | None = None,
    accents: bool = True,
    relocate: bool = True,
    terminator: int | None = None,
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
    if table_path is not None:
        # tabela fornecida ganha da deduzida: ela sabe pontuacao e codigos de
        # controle, que a deducao nao tem como descobrir sozinha
        tabela = Table.load(table_path)
        log(f"tabela fornecida: {table_path.name} ({len(tabela)} entradas)")
    elif guess is None:
        report.explicacao = "nao consegui deduzir o alfabeto"
        return report
    else:
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

    # 5. largura de linha: o jogo pode guardar o texto em linhas coladas
    from .core.lexicon import load_lexicon
    from .core.wrap import detectar_largura

    largura = None
    lexico = load_lexicon("/usr/share/dict/words") or load_lexicon()
    if lexico:
        achado = detectar_largura([u.text for u in script.units], lexico)
        if achado:
            largura = achado.valor
            report.largura_linha = largura
            log(f"linhas de {largura} caracteres coladas "
                f"({achado.juncoes}/{achado.total} juncoes na mesma coluna) -- "
                "avisado ao tradutor, e a traducao volta re-quebrada nessa largura")

    # 6. traducao
    # nomes que o jogo inventou entram no glossario para nao serem traduzidos;
    # o glossario que o usuario passou tem precedencia sobre o deduzido
    achados = nomes_proprios(script, lexico) if lexico else {}
    report.nomes_proprios = list(achados)
    if achados:
        log(f"nomes proprios: {' '.join(list(achados)[:8])}"
            + (f" e mais {len(achados) - 8}" if len(achados) > 8 else ""))
    combinado = {**achados, **(glossary or {})}

    config = engine_registry.EngineConfig(
        target_lang=target_lang, game=game or nome, glossary=combinado,
        line_width=largura,
        alphabet="".join(sorted(
            valor for raw, valor in tabela.entries.items()
            if len(raw) == 1 and len(valor) == 1 and valor.strip()
        )),
    )
    engine = engine_registry.build(engine_name, config, **(engine_kwargs or {}))
    candidatas = script.units
    if lexico:
        antes = len(candidatas)
        candidatas = [u for u in candidatas if tem_palavra_real(u.text, lexico)]
        if antes != len(candidatas):
            log(f"{antes - len(candidatas):,} unidades sem nenhuma palavra real "
                "ficaram de fora -- sao ruido do scanner")
    # com limite, escolhe as mais longas: sao as com mais texto de verdade,
    # nao as que por acaso estao no comeco da ROM
    if limit:
        candidatas = sorted(candidatas, key=lambda u: -len(u.text))[:limit]
    alvos = candidatas
    _traduzir(engine, alvos, largura, log)

    # o modelo as vezes engole um lote inteiro e devolve menos linhas do que
    # recebeu. Medido no Hermes Agent: uma rodada devolveu 30 de 30 e a seguinte
    # 12. Repetir as que faltam, em lotes menores, recupera boa parte
    for tentativa in range(2):
        faltando = [u for u in alvos if not u.translated]
        if not faltando:
            break
        log(f"{len(faltando):,} linhas nao voltaram do modelo -- repetindo "
            f"(tentativa {tentativa + 1})")
        anterior = engine.config.batch_size
        engine.config.batch_size = max(1, anterior // 3)
        _traduzir(engine, faltando, largura, log)
        engine.config.batch_size = anterior
        report.repetidas += len(faltando) - sum(1 for u in faltando if not u.translated)
    traduzidas = [u for u in script.units if u.translated]
    report.traduzidas = len(traduzidas)
    log(f"traduzidas {len(traduzidas):,} unidades")
    if not traduzidas:
        return report

    # 6. acentos: desenhar os glifos que faltam
    if accents:
        _acentuar(rom, tabela, script, traduzidas, plugin, det, caminho_tabela, report, log)

    # 7. o que ainda nao codifica perde o acento, e depois a pontuacao, em vez
    #    de perder a linha inteira. O modelo escreve '.', '!' e ',' mesmo quando
    #    a tabela deduzida nao tem nenhum deles
    for u in traduzidas:
        if not u.translation or tabela.can_encode(u.translation):
            continue
        tentativa = sem_acento(u.translation)
        if not tabela.can_encode(tentativa):
            tentativa = "".join(c for c in tentativa if tabela.can_encode(c)).strip()
            tentativa = " ".join(tentativa.split())
        if tentativa and tabela.can_encode(tentativa):
            u.translation = tentativa
            report.transliteradas += 1
        else:
            u.translation = None
    if report.transliteradas:
        log(f"{report.transliteradas:,} traducoes perderam o acento por falta de tile")

    # 7b. so agora da para medir o estouro de verdade: a tabela ja tem os acentos
    #     desenhados e as transliteracoes ja mudaram o tamanho das linhas
    _reapertar(engine, script, tabela, largura, report, log)
    engine.close()

    script.save(out_dir / f"{nome}.script.json")

    # 8. reinsercao. Primeiro no lugar, numa copia, so para saber se sobra algo
    ensaio = insert(rom.copy(), script, tabela)
    relocador = None
    if ensaio.overflow and relocate:
        relocador = _preparar_realocacao(
            rom, data, script, tabela, plugin, det, regions, terminator, report, log
        )
    elif ensaio.overflow:
        report.motivo_sem_realocar = "realocacao desligada"

    # a tabela pode ter ganhado acentos e o terminador pelo caminho; sem regravar,
    # o .tbl entregue decodificaria a ROM traduzida de forma errada
    caminho_tabela.write_text(tabela.dumps(), encoding="utf-8")

    relatorio = insert(rom, script, tabela, relocator=relocador)
    report.escritas = relatorio.written
    report.realocadas = relatorio.relocated
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
        + (f", {relatorio.relocated:,} realocadas" if relatorio.relocated else "")
        + (f", {len(relatorio.overflow):,} nao couberam" if relatorio.overflow else ""))
    if relatorio.overflow and report.motivo_sem_realocar:
        log(f"  nao deu para mover as que sobraram: {report.motivo_sem_realocar}")
    return report


def _preparar_realocacao(
    rom, data, script, tabela, plugin, det, regions, terminator, report, log
):
    """Monta o realocador, ou explica por que nao deu.

    Custa uma varredura de ponteiros pela ROM inteira, entao so roda quando
    alguma traducao de fato nao coube -- nao ha por que pagar isso a toa.
    """
    from .core.insert import Relocator
    from .core.pointers import find_pointers
    from .core.space import SpaceAllocator, find_free_space

    # o terminador e obrigatorio: sem ele o jogo le alem da string movida
    if terminator is None:
        achado = inferir_terminador(data, regions, tabela)
        if achado and achado[1] >= CONFIANCA_TERMINADOR:
            terminator, confianca = achado
            log(f"terminador deduzido: 0x{terminator:02X} ({confianca:.0%} das frases)")
        else:
            visto = f" (melhor palpite 0x{achado[0]:02X}, so {achado[1]:.0%})" if achado else ""
            report.motivo_sem_realocar = (
                f"nao sei qual byte fecha as frases{visto}; passe --terminator 0xNN"
            )
            return None
    report.terminador = terminator

    # as unidades precisam incluir o terminador para poderem ser movidas
    tabela.entries[bytes([terminator])] = "[END]"
    tabela.end_tokens.add(bytes([terminator]))
    tabela.reindex()
    estendidas = 0
    for u in script.units:
        fim = u.offset + u.length
        if fim < len(data) and data[fim] == terminator:
            u.length += 1
            u.max_len += 1
            u.text += "[END]"
            if u.translation is not None:
                u.translation += "[END]"
            estendidas += 1
    log(f"{estendidas:,} unidades passam a incluir o terminador")

    alvos = {u.offset: u.id for u in script.units}
    especificacoes: dict[int, object] = {}
    tabelas = 0
    for spec in plugin.pointer_specs(det):
        for tabela_ptr in find_pointers(data, alvos, plugin, det, spec, min_run=8):
            tabelas += 1
            for offset in tabela_ptr.entries:
                especificacoes[offset] = spec
    report.tabelas_de_ponteiro = tabelas
    por_alvo: dict[int, list[int]] = {}
    for spec in plugin.pointer_specs(det):
        for tabela_ptr in find_pointers(data, alvos, plugin, det, spec, min_run=8):
            for offset, alvo in tabela_ptr.entries.items():
                por_alvo.setdefault(alvo, []).append(offset)
    for u in script.units:
        u.pointers = sorted(por_alvo.get(u.offset, []))
    com_ponteiro = sum(1 for u in script.units if u.pointers)
    log(f"ponteiros: {tabelas} tabelas, {com_ponteiro:,} unidades enderecadas")
    if not especificacoes:
        report.motivo_sem_realocar = "nenhuma tabela de ponteiros encontrada"
        return None

    cabecalho = det.details.get("header_offset")
    excluir = [(cabecalho, cabecalho + 64)] if cabecalho is not None else []
    regioes = find_free_space(data, min_run=64, exclude=excluir)
    alocador = SpaceAllocator(regioes, bank_size=plugin.bank_size(det))
    log(f"espaco livre: {alocador.total_free:,} bytes em {len(alocador.regions)} trechos")
    if not alocador.total_free:
        report.motivo_sem_realocar = "nao ha espaco livre na ROM"
        return None
    return Relocator(rom=rom, table=tabela, plugin=plugin, det=det,
                     allocator=alocador, specs=especificacoes)


def _traduzir(engine, unidades, largura, log) -> None:
    """Traduz, e re-quebra a traducao na largura do jogo.

    Na ida o texto vai como esta na ROM, com as palavras coladas -- um modelo de
    linguagem le `goingto` sem dificuldade, e a alternativa que testei aqui era
    pior: separar por dicionario acerta `goingto` e destroi `Dragonlord`, que
    vira `Dragon lord`. O modelo sabe a diferenca porque le a frase; o
    dicionario nao.

    O que o modelo *nao* tem como saber e que a linha mede 16 caracteres. Isso
    nao esta na lingua, esta na tela -- e por isso a largura continua sendo
    medida, e serve para re-quebrar a traducao na volta.
    """
    from .core.wrap import redobrar
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
            if r.text is None:
                continue
            traduzido = unmask_controls(r.text, tokens[u.id])
            u.translation = redobrar(traduzido, largura) if largura else traduzido


def _espremer(texto: str, origem: str, tabela, max_len: int) -> str | None:
    """Tira a folga mecanica da traducao, sem trocar uma palavra sequer.

    Espaco duplicado, espaco antes de pontuacao, espaco sobrando na ponta e
    ponto final que o modelo acrescentou por conta propria -- o original nao
    tinha. Devolve None quando nao sobra folga: ai so trocando palavra, e isso
    e trabalho do modelo.
    """
    apertado = " ".join(texto.split())
    apertado = re.sub(r"\s+([.,!?;:])", r"\1", apertado)
    if apertado.endswith(".") and not origem.rstrip().endswith("."):
        apertado = apertado[:-1].rstrip()
    if not apertado or apertado == texto or not tabela.can_encode(apertado):
        return None
    return apertado if len(tabela.encode(apertado)) <= max_len else None


def _reapertar(engine, script, tabela, largura, report, log) -> None:
    """Ultima passada nas traducoes que nao cabem.

    Precisa rodar *depois* dos acentos e da transliteracao, que sao justamente
    as etapas que mudam o tamanho da linha: medir antes delas media o texto
    errado, e uma traducao com acento nem era codificavel ainda, entao escapava
    do filtro inteira.

    Medido contra a traducao humana do Dragon Warrior: das 106 que estouravam,
    41 passavam por 1 ou 2 caracteres -- `CONTINUE` virando `CONTINUAR`.
    """
    def estouro(u) -> int:
        if not u.translated or not tabela.can_encode(u.translation):
            return 0
        return len(tabela.encode(u.translation)) - u.max_len

    estouradas = [u for u in script.units if estouro(u) > 0]
    if not estouradas:
        return
    apertadas = sum(1 for u in estouradas if estouro(u) <= 2)
    log(f"{len(estouradas):,} traducoes passaram do limite "
        f"({apertadas:,} por 1 ou 2 caracteres)")

    # o que da para resolver sem gastar token vem primeiro
    for u in estouradas:
        apertado = _espremer(u.translation, u.text, tabela, u.max_len)
        if apertado is not None:
            u.translation = apertado
            report.espremidas += 1
    if report.espremidas:
        log(f"  {report.espremidas:,} couberam so tirando espaco e pontuacao sobrando")

    faltam = [u for u in estouradas if estouro(u) > 0]
    if not faltam:
        return
    antes = {u.id: u.translation for u in faltam}
    # duas rodadas: um estouro de 1 caractere quase sempre sai na segunda, e
    # cada rodada ve por quanto a anterior passou
    for rodada in range(2):
        alvo = [u for u in faltam if estouro(u) > 0]
        if not alvo:
            break
        log(f"  pedindo {len(alvo):,} mais curtas (rodada {rodada + 1})")
        _encurtar(engine, alvo, tabela, largura, log)
    report.encurtadas = sum(
        1 for u in faltam if u.translation != antes[u.id] and estouro(u) <= 0
    )
    if report.encurtadas:
        log(f"  {report.encurtadas:,} passaram a caber")


def _encurtar(engine, unidades, tabela, largura, log) -> None:
    """Repede as traducoes que nao couberam, dizendo por quanto passaram."""
    from .core.wrap import redobrar
    from .engines.base import TranslationRequest, mask_controls, unmask_controls

    tamanho = max(1, engine.config.batch_size // 2)
    for inicio in range(0, len(unidades), tamanho):
        lote = unidades[inicio : inicio + tamanho]
        pedidos, tokens = [], {}
        for u in lote:
            excesso = len(tabela.encode(u.translation)) - u.max_len
            texto, marcas = mask_controls(u.text)
            tokens[u.id] = marcas
            pedidos.append(TranslationRequest(
                id=u.id, text=texto, max_chars=u.max_len,
                context=f"'{u.translation}' passou {excesso} de {u.max_len} "
                        f"caracteres. Cabem {u.max_len}, contando espaco e "
                        f"pontuacao. Reescreva com no maximo {u.max_len}: troque "
                        f"palavra por sinonimo mais curto, nunca corte no meio "
                        f"nem abrevie com ponto",
            ))
        try:
            resultados = engine.translate_batch(pedidos)
        except Exception as exc:
            log(f"  lote falhou: {exc}")
            continue
        for u, r in zip(lote, resultados):
            if r.text is None:
                continue
            novo = unmask_controls(r.text, tokens[u.id])
            novo = redobrar(novo, largura) if largura else novo
            # o modelo devolve a linha ainda com folga mecanica e as vezes com
            # um acento que esta tabela nao tem: as duas coisas tem conserto
            # antes de desistir da resposta
            for tentativa in (novo, _espremer(novo, u.text, tabela, u.max_len),
                              sem_acento(novo)):
                if (tentativa and tabela.can_encode(tentativa)
                        and len(tabela.encode(tentativa)) <= u.max_len):
                    u.translation = tentativa
                    break


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
