"""Boota a ROM num emulador sem janela e verifica que ela roda.

Todas as outras checagens do projeto sao de bytes: round-trip, checksum interno,
patch reaplicando. Nenhuma delas percebe uma ROM que passa em tudo e trava na
primeira tela -- e traducao mal reinserida faz exatamente isso.

Roda com `nes-py`, que traz um emulador de NES em C++ com o framebuffer exposto
em numpy. E dependencia opcional: sem ela o comando avisa e sai.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: mascara dos botoes do controle, como o nes-py espera
BOTOES = {
    "right": 0x80, "left": 0x40, "down": 0x20, "up": 0x10,
    "start": 0x08, "select": 0x04, "B": 0x02, "A": 0x01,
}


@dataclass
class Fumaca:
    quadros: int = 0
    telas_distintas: int = 0
    amostras: dict = field(default_factory=dict)  # quadro -> tela
    fracao_preta: float = 1.0
    congelou_em: int | None = None
    divergencia: float | None = None  # contra a ROM original, se dada
    erro: str = ""
    capturas: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.erro
            and self.congelou_em is None
            and self.fracao_preta < 0.99
            and self.telas_distintas >= 3
        )

    @property
    def veredito(self) -> str:
        if self.erro:
            return f"nao rodou: {self.erro}"
        if self.fracao_preta >= 0.99:
            return "tela preta o tempo todo"
        if self.congelou_em is not None:
            return f"congelou no quadro {self.congelou_em}"
        if self.telas_distintas < 3:
            return "roda, mas a tela quase nao muda"
        return "boota e roda"


def _passo(env, acao: int):
    resultado = env.step(acao)
    return resultado[0]


def fumaca(
    rom_path: Path,
    quadros: int = 900,
    roteiro: list[tuple[str, int]] | None = None,
    amostrar: int = 30,
    capturas_em: list[int] | None = None,
    pasta_capturas: Path | None = None,
) -> Fumaca:
    """Roda a ROM e resume o que aconteceu na tela.

    `roteiro` e uma lista de (botao, por quantos quadros). O padrao aperta start
    algumas vezes, que e o bastante para atravessar tela de titulo.
    """
    try:
        from nes_py import NESEnv
    except ImportError:
        return Fumaca(erro="nes-py nao instalado (pip install nes-py)")

    relatorio = Fumaca()
    # o padrao precisa chegar a uma tela COM texto: so atravessar o titulo leva
    # a um cenario onde nada foi traduzido, e a comparacao daria zero a toa
    roteiro = roteiro or [
        ("", 240), ("start", 4), ("", 150), ("start", 4), ("", 180),
        ("A", 4), ("", 150),
    ]
    capturas_em = capturas_em or []
    try:
        env = NESEnv(str(rom_path))
    except Exception as exc:  # ROM que o emulador recusa
        return Fumaca(erro=str(exc))

    try:
        inicial = env.reset()
        tela = inicial[0] if isinstance(inicial, tuple) else inicial
        vistas: list[np.ndarray] = []
        pretos = 0
        ultima = tela.copy()
        parado = 0
        total = 0

        sequencia = [
            (BOTOES.get(botao, 0), n) for botao, n in roteiro
        ]
        sequencia.append((0, max(0, quadros - sum(n for _, n in roteiro))))

        for acao, n in sequencia:
            for _ in range(n):
                tela = _passo(env, acao)
                total += 1
                if tela.max() < 16:
                    pretos += 1
                if np.array_equal(tela, ultima):
                    parado += 1
                    if parado > 600 and relatorio.congelou_em is None:
                        relatorio.congelou_em = total
                else:
                    parado = 0
                    ultima = tela.copy()
                if all(
                    np.abs(tela.astype(np.int16) - v.astype(np.int16)).mean() > 4
                    for v in vistas
                ):
                    vistas.append(tela.copy())
                if total % amostrar == 0:
                    relatorio.amostras[total] = tela.copy()
                if total in capturas_em and pasta_capturas is not None:
                    relatorio.capturas.append(
                        _salvar(tela, pasta_capturas / f"{rom_path.stem}-{total:05d}.png")
                    )

        relatorio.quadros = total
        relatorio.telas_distintas = len(vistas)
        relatorio.fracao_preta = pretos / total if total else 1.0
        relatorio.ultima_tela = ultima  # type: ignore[attr-defined]
    finally:
        env.close()
    return relatorio


def _salvar(tela: np.ndarray, caminho: Path) -> Path:
    from PIL import Image

    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tela).resize((512, 480), Image.NEAREST).save(caminho)
    return caminho


def comparar(original: Path, traduzida: Path, **kwargs) -> tuple[Fumaca, Fumaca, float]:
    """Roda as duas com o mesmo roteiro e mede a maior diferenca de tela.

    Comparar so a tela final nao serve: ela pode ser justamente uma onde nao ha
    texto traduzido, e o resultado da zero mesmo com a traducao funcionando.
    A comparacao e feita em varios pontos da execucao, e vale o maior.

    Divergencia zero em todos os pontos significa que a traducao nao aparece --
    ou nao foi escrita. Divergencia enorme costuma ser corrupcao.
    """
    a = fumaca(original, **kwargs)
    b = fumaca(traduzida, **kwargs)
    div = 0.0
    if a.ok and b.ok:
        for quadro, tela_a in a.amostras.items():
            tela_b = b.amostras.get(quadro)
            if tela_b is not None:
                div = max(div, float((tela_a != tela_b).any(axis=2).mean()))
    b.divergencia = div
    return a, b, div
