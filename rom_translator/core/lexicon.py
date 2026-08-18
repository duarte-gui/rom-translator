"""Listas de palavras usadas para deduzir a tabela de compressao de um jogo.

Um compressor e deterministico: se ele troca "th" por um byte, ele troca em toda
ocorrencia. Entao a palavra comprimida nunca aparece inteira em outro ponto da
ROM para servir de gabarito -- foi o que derrubou a primeira versao da inferencia
de DTE, que tentava se virar so com o texto do proprio jogo.

Com um lexico do idioma, `s?rd` casa com `sword` mesmo que "sword" so exista
comprimido dentro da ROM. E por isso que a inferencia depende de uma lista de
palavras do idioma *de origem* do texto.
"""

from __future__ import annotations

import re
from pathlib import Path

#: caminhos comuns em Linux, do mais util para o menos
SEARCH_PATHS = (
    "/usr/share/hunspell/en_US.dic",
    "/usr/share/dict/american-english",
    "/usr/share/dict/words",
)

WORD_RE = re.compile(r"^[a-z]+$")


def load_lexicon(
    path: str | Path | None = None,
    min_length: int = 3,
    max_length: int = 14,
) -> set[str]:
    """Carrega uma lista de palavras. Sem caminho, procura nos lugares usuais.

    Aceita o formato do hunspell (`palavra/FLAGS`) e listas simples. Palavras
    muito curtas sao ruido -- casam com qualquer coisa -- e as muito longas nao
    ajudam a resolver um par de duas letras.
    """
    candidates = [Path(path)] if path else [Path(p) for p in SEARCH_PATHS]
    for candidate in candidates:
        if not candidate.exists():
            continue
        words = set()
        for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = line.split("/")[0].strip().lower()
            if min_length <= len(word) <= max_length and WORD_RE.match(word):
                words.add(word)
        if words:
            return words
    if path:
        raise FileNotFoundError(f"lista de palavras nao encontrada: {path}")
    return set()
