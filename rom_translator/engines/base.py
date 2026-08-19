"""Contrato de motor de traducao.

Dois cuidados moldam esta interface, e os dois vem da ROM, nao do LLM:

1. **Codigos de controle nao sao texto.** `[END]`, `[LINE]`, `[$1F]` viram
   marcadores opacos antes de chegar ao modelo e sao restaurados depois. O
   modelo nunca ve -- nem inventa -- um byte de controle.
2. **O limite de tamanho e restricao dura.** Cada unidade carrega quantos
   caracteres cabem. Estourar significa nao reinserir; entao o limite vai no
   pedido, e a traducao longa demais e repedida com o limite explicito.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"\[[^\[\]]+\]")
PLACEHOLDER = "⸤{}⸥"  # delimitadores que nao aparecem em texto de jogo
PLACEHOLDER_RE = re.compile("⸤(\\d+)⸥")


@dataclass
class TranslationRequest:
    id: str
    text: str  # ja com os codigos de controle mascarados
    max_chars: int
    context: str = ""


@dataclass
class TranslationResult:
    id: str
    text: str | None  # None quando o motor nao conseguiu traduzir
    note: str = ""


def mask_controls(text: str) -> tuple[str, list[str]]:
    """Troca codigos de controle por marcadores opacos numerados."""
    tokens: list[str] = []

    def take(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return PLACEHOLDER.format(len(tokens) - 1)

    return TOKEN_RE.sub(take, text), tokens


def unmask_controls(text: str, tokens: list[str]) -> str:
    """Restaura os codigos de controle. Marcador invalido e deixado como veio."""

    def put(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return tokens[index] if index < len(tokens) else match.group(0)

    return PLACEHOLDER_RE.sub(put, text)


@dataclass
class EngineConfig:
    source_lang: str = "auto"
    target_lang: str = "pt-BR"
    game: str = ""
    glossary: dict[str, str] = field(default_factory=dict)
    batch_size: int = 40
    #: largura da linha, quando o jogo cola as linhas sem espaco na quebra
    line_width: int | None = None
    #: caracteres que a fonte do jogo tem. Vazio = sem restricao conhecida
    alphabet: str = ""


class TranslationEngine(ABC):
    name: str = "abstract"

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

    @abstractmethod
    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        """Traduz um lote. A saida tem que ter um resultado por pedido, na ordem."""

    def close(self) -> None:
        """Libera recursos, se houver."""
