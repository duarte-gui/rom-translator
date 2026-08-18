"""Contrato de plugin de plataforma.

Regra de ouro do projeto: o core so conhece offsets de arquivo. Tudo que
depende de mapeamento de memoria, bancos ou formato de ponteiro mora aqui.
Adicionar um console novo = adicionar um PlatformPlugin, sem tocar no core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PointerSpec:
    """Como um ponteiro e representado nesta plataforma."""

    name: str
    width: int  # bytes ocupados no arquivo
    endian: str = "little"
    #: valor somado ao ponteiro bruto para virar endereco de CPU
    base: int = 0

    @property
    def mask(self) -> int:
        return (1 << (8 * self.width)) - 1

    def decode(self, raw: bytes) -> int:
        return int.from_bytes(raw, self.endian) + self.base

    def encode(self, cpu_addr: int) -> bytes:
        """Enderecos que nao cabem na largura sao truncados.

        Um ponteiro de 2 bytes num console de 24 bits guarda so o deslocamento
        dentro do banco -- o banco vem de outro lugar (registrador, tabela
        paralela ou constante no codigo). Truncar aqui e o comportamento certo;
        quem monta a tabela e que precisa saber de qual banco ela fala.
        """
        return ((cpu_addr - self.base) & self.mask).to_bytes(self.width, self.endian)


@dataclass
class Detection:
    """Resultado de uma tentativa de identificacao."""

    platform: str
    confidence: float  # 0.0 a 1.0
    mapper: str = ""
    title: str = ""
    details: dict = field(default_factory=dict)


class PlatformPlugin(ABC):
    name: str = "abstract"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def detect(self, data: bytes) -> Detection | None:
        """Retorna uma Detection se `data` parece ser desta plataforma."""

    @abstractmethod
    def cpu_to_file(self, cpu_addr: int, det: Detection) -> int | None:
        """Endereco de CPU -> offset no arquivo. None se nao mapeavel."""

    @abstractmethod
    def file_to_cpu(self, offset: int, det: Detection) -> int | None:
        """Offset no arquivo -> endereco de CPU. None se nao mapeavel."""

    def pointer_specs(self, det: Detection) -> list[PointerSpec]:
        return []

    def bank_size(self, det: Detection) -> int | None:
        """Bytes por banco, ou None se ponteiros enderecam a ROM inteira.

        Importa para realocar texto: com ponteiro estreito, a string tem que
        ficar no mesmo banco, senao o endereco reescrito aponta para o lugar
        certo do banco errado.
        """
        return None

    def text_regions(self, data: bytes, det: Detection) -> list[tuple[int, int]]:
        """Faixas do arquivo onde faz sentido procurar texto. Padrao: tudo."""
        return [(0, len(data))]
