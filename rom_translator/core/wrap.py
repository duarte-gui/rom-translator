"""Texto quebrado em linhas de largura fixa, sem espaco na quebra.

Muitos jogos guardam dialogo como linhas de N caracteres coladas umas nas
outras. A quebra visual e feita pelo renderizador, entao o espaco que separaria
as palavras nao existe nos bytes: `Could I help you` + `with anything` fica
`Could I help youwith anything` na ROM.

Isso importa duas vezes. Na leitura, o modelo recebe `youwith` e traduz pior. Na
escrita, importa mais: se a traducao nao for re-quebrada na mesma largura, o jogo
parte palavras no meio da tela.

Achar a largura pede duas evidencias juntas, e nenhuma serve sozinha:

* um **dicionario**, para saber que `youwith` se parte em duas palavras. Mas so
  ele acusa `Wolflord` e `Starwyvern` -- nomes de inimigo que o jogo inventou --
  e "consertar" esses corromperia o texto;
* a **posicao**. Quebra de linha cai sempre na mesma coluna. No Faxanadu, 11 de
  13 juncoes caem na coluna 16; no Dragon Warrior elas se espalham por 4, 34, 15
  e 17, porque la nao ha quebra nenhuma -- so nomes compostos.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

#: uma peca de duas ou tres letras so vale como palavra se for uma destas. Sem
#: essa trava, `shoot` vira `sh oot` -- listas grandes de palavras contem siglas
#: e abreviacoes que casam com qualquer coisa
CURTAS = frozenset(
    """a an the and or but if of to in on at by for from with as is are was were
    be am no not so up out off he she it we you they his her its my me him them
    do did go got has had have can will would should may might must who how why
    all any one two new old now then here than too very own same such only""".split()
)


@dataclass
class Largura:
    valor: int
    juncoes: int  # juncoes que caem nesta coluna
    total: int  # juncoes encontradas ao todo

    @property
    def confianca(self) -> float:
        return self.juncoes / self.total if self.total else 0.0


def _palavra(pedaco: str, lexico: set[str]) -> bool:
    """Peca curta so passa se for palavra funcional comum; longa, se estiver no lexico."""
    if len(pedaco) < 2:
        return False
    if len(pedaco) <= 3:
        return pedaco in CURTAS
    return pedaco in lexico


def cortar(token: str, lexico: set[str]) -> int | None:
    """Onde este token se parte em duas palavras, se e que se parte."""
    limpo = token.lower().strip(".,!?'\"")
    if not limpo.isalpha() or len(limpo) < 4 or limpo in lexico:
        return None
    return next(
        (i for i in range(2, len(limpo) - 1)
         if _palavra(limpo[:i], lexico) and _palavra(limpo[i:], lexico)),
        None,
    )


def parece_nome_proprio(token: str, primeiro: bool) -> bool:
    """Maiuscula fora do inicio da frase denuncia nome proprio.

    E o que separa `Dragonlord` de `goingto`. Sem isso, o dicionario acha que
    `Wolflord` e `wolf lord` e `Starwyvern` e `star wyvern` -- nomes que o jogo
    inventou e que nenhuma lista de palavras contem inteiros.
    """
    return bool(token) and token[0].isupper() and not primeiro


def _juncoes(texto: str, lexico: set[str]) -> list[int]:
    """Colunas onde uma palavra desconhecida se parte em duas conhecidas."""
    achadas = []
    coluna = 0
    tokens = texto.split(" ")
    for indice, token in enumerate(tokens):
        # a primeira palavra da unidade pode legitimamente vir em maiuscula
        if not parece_nome_proprio(token, indice == 0):
            corte = cortar(token, lexico)
            if corte is not None:
                achadas.append(coluna + corte)
        coluna += len(token) + 1
    return achadas


def detectar_largura(
    textos: list[str],
    lexico: set[str],
    min_juncoes: int = 5,
    min_confianca: float = 0.5,
) -> Largura | None:
    """Largura da linha, se as juncoes se concentrarem numa coluna so.

    Sem concentracao devolve None -- e o caso do Dragon Warrior, onde as
    "juncoes" sao nomes proprios e re-quebrar nao faria sentido nenhum.
    """
    colunas: Counter[int] = Counter()
    for texto in textos:
        colunas.update(_juncoes(texto, lexico))
    total = sum(colunas.values())
    if total < min_juncoes:
        return None
    coluna, quantas = colunas.most_common(1)[0]
    if coluna < 8:
        return None  # largura absurda: e ruido, nao layout
    largura = Largura(coluna, quantas, total)
    return largura if largura.confianca >= min_confianca else None


def desdobrar(texto: str, largura: int, lexico: set[str] | None = None) -> str:
    """Separa as palavras que a quebra de linha colou, para leitura humana.

    Fatiar de `largura` em `largura` parece o caminho obvio e erra a fase: uma
    unidade extraida pode comecar no meio de uma linha, e ai todo corte sai
    deslocado. Quem sabe onde a juncao esta e o dicionario.

    A largura detectada e o que *autoriza* usar o dicionario aqui -- sem ela, o
    mesmo corte transformaria `Wolflord` em `wolf lord`. Uma ROM onde as juncoes
    nao se concentram numa coluna nao cola linhas, e entao nada deve ser cortado.
    """
    if not lexico:
        linhas = [texto[i : i + largura] for i in range(0, len(texto), largura)]
        return " ".join(linha.rstrip() for linha in linhas if linha.strip())

    saida = []
    for token in texto.split(" "):
        corte = cortar(token, lexico)
        saida.append(f"{token[:corte]} {token[corte:]}" if corte else token)
    return " ".join(saida)


def redobrar(texto: str, largura: int) -> str:
    """Quebra o texto em linhas de `largura`, do jeito que o jogo espera.

    Cada linha que nao e a ultima e completada com espacos ate a largura exata:
    o renderizador conta caracteres, entao uma linha curta faria a proxima
    comecar no meio dela.
    """
    palavras = texto.split()
    if not palavras:
        return texto
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        if not atual:
            atual = palavra
        elif len(atual) + 1 + len(palavra) <= largura:
            atual += " " + palavra
        else:
            linhas.append(atual)
            atual = palavra
        while len(atual) > largura:  # palavra maior que a linha inteira
            linhas.append(atual[:largura])
            atual = atual[largura:]
    linhas.append(atual)
    return "".join(
        linha.ljust(largura) if i < len(linhas) - 1 else linha
        for i, linha in enumerate(linhas)
    )
