"""Diz, antes de investir tempo, se uma ROM da para traduzir automaticamente.

A pergunta que decide um projeto de traducao nao e "quanto texto tem" -- e "da
para *ler* esse texto sem engenharia reversa". Jogo que comprime dialogo (DTE,
MTE, Huffman) esconde o texto atras de uma tabela que mora no codigo, e nenhuma
estatistica recupera isso de forma confiavel: a inferencia deste projeto acerta
7 de 16 numa tabela sintetica e nao acerta nada nas ROMs comprimidas reais.

O sinal que separa os dois casos e o **comprimento** do que sai. Texto sem
compressao sai em frases; comprimido sai picado, porque cada byte que a tabela
nao conhece corta a sequencia. Medido em sete ROMs de tres consoles:

    Dragon Warrior (NES, sem compressao)     mediana 17, p90 44
    Castlevania AoS (GBA, ASCII puro)        mediana 11, p90 23
    Faxanadu (NES, sem compressao)           mediana 12, p90 15
    Final Fantasy III (SNES, DTE)            mediana  8, p90 22
    Chrono Trigger (SNES, DTE)               mediana  5, p90  8
    Illusion of Gaia (SNES)                  mediana  5, p90  8
    Golden Sun (GBA, comprimido)             mediana  5, p90  7
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..platforms.base import Detection, PlatformPlugin
from .scanner import TextRegion, find_text_regions, guess_alphabet, looks_like_language
from .table import Table

#: limiares medidos nas sete ROMs acima. Nao sao finos: a separacao entre
#: "frases" e "cacos" e larga, e o meio-termo e sinalizado como parcial
MEDIANA_BOA = 10
P90_BOM = 15
FRACAO_LINGUAGEM_BOA = 0.85


@dataclass
class Triagem:
    plataforma: str
    blocos: int
    fracao_sinalizada: float
    espaco: int | None
    minusculas: int | None
    maiusculas: int | None
    palavras_reais: int
    segundo_lugar: int
    unidades: int
    fracao_linguagem: float
    mediana: float
    p90: int
    palavras_por_unidade: float
    caracteres: int

    @property
    def veredito(self) -> str:
        # a guarda conta caracteres, nao unidades: uma ROM que guarde o texto
        # num unico bloco continuo produz uma unidade so, e exigir vinte
        # rejeitaria justamente o caso mais facil de todos
        if self.espaco is None or self.caracteres < 200:
            return "sem texto legivel"
        if (self.mediana >= MEDIANA_BOA and self.p90 >= P90_BOM
                and self.fracao_linguagem >= FRACAO_LINGUAGEM_BOA):
            return "automatica viavel"
        if self.mediana >= 7 or self.p90 >= P90_BOM:
            return "parcial"
        return "texto comprimido"

    @property
    def explicacao(self) -> str:
        return {
            "automatica viavel":
                "o texto sai em frases inteiras -- dump, traducao e reinsercao "
                "devem funcionar sem tabela fornecida",
            "parcial":
                "parte do texto sai legivel e parte vem picada; da para traduzir "
                "menus e nomes, mas o dialogo provavelmente esta comprimido",
            "texto comprimido":
                "o que sai sao cacos de 5 caracteres: o jogo comprime o dialogo e "
                "so um .tbl com a tabela de compressao resolve",
            "sem texto legivel":
                "nao foi possivel deduzir o alfabeto -- ou o texto esta comprimido "
                "de ponta a ponta, ou nao e um formato que o scan reconhece",
        }[self.veredito]


def triar(
    data: bytes,
    plugin: PlatformPlugin,
    det: Detection,
    regions: list[TextRegion] | None = None,
    amostra_blocos: int = 120,
) -> Triagem:
    """Roda o pipeline de leitura e resume o que da para esperar dele."""
    from ..project import Block

    if regions is None:
        regions = find_text_regions(data, limits=plugin.text_regions(data, det))
    sinalizado = sum(r.length for r in regions) / len(data) if data else 0.0
    guess = guess_alphabet(data, regions)
    if guess is None:
        return Triagem(det.platform, len(regions), sinalizado, None, None, None,
                       0, 0, 0, 0.0, 0.0, 0, 0.0, 0)

    table = Table.parse(guess.as_table_source())
    unidades = []
    for region in sorted(regions, key=lambda r: -r.length)[:amostra_blocos]:
        unidades += Block(
            id="t", start=region.start, end=region.end, kind="greedy", min_run=4
        ).extract(data, table)
    textos = [u.text for u in unidades if looks_like_language(u.text)]
    if not textos:
        return Triagem(det.platform, len(regions), sinalizado, guess.space,
                       guess.lower_base, guess.upper_base, guess.word_hits,
                       guess.runner_up_hits, len(unidades), 0.0, 0.0, 0, 0.0, 0)

    tamanhos = sorted(len(t) for t in textos)
    return Triagem(
        plataforma=det.platform,
        blocos=len(regions),
        fracao_sinalizada=sinalizado,
        espaco=guess.space,
        minusculas=guess.lower_base,
        maiusculas=guess.upper_base,
        palavras_reais=guess.word_hits,
        segundo_lugar=guess.runner_up_hits,
        unidades=len(unidades),
        fracao_linguagem=len(textos) / len(unidades),
        mediana=statistics.median(tamanhos),
        p90=tamanhos[int(len(tamanhos) * 0.9)],
        palavras_por_unidade=statistics.mean(t.count(" ") + 1 for t in textos),
        caracteres=sum(tamanhos),
    )
