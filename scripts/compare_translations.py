"""Compara a nossa traducao com a de um humano, na mesma ROM.

Uma traducao de fa nao serve so para medir o scanner (`validate_patch.py`):
serve para medir a *traducao*. Este script alinha as duas pelas marcas de
controle que as duas preservam e mostra, unidade a unidade, onde a nossa
ficou para tras.

    python scripts/compare_translations.py original.nes humana.nes nossa.nes tabela.tbl
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

# bytes que separam mensagens no Dragon Warrior; um tradutor humano preserva
# quase todos, porque mexer neles quebra o jogo -- por isso servem de ancora
SEPARADORES = {0xFB, 0xFC, 0xFD}

PALAVRAS_EN = {
    "the", "and", "you", "thou", "thy", "thee", "hath", "not", "with", "have",
    "are", "that", "this", "king", "castle", "welcome", "princess", "what",
    "your", "will", "from", "they", "been", "who", "but", "when", "shall",
    "must", "money", "enough",
}


def ler_tabela(caminho: Path) -> dict[int, str]:
    tabela = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if "=" in linha:
            byte, char = linha.split("=", 1)
            tabela[int(byte, 16)] = char
    return tabela


def unidades(rom: bytes, tabela: dict[int, str], lo: int, hi: int):
    """Fatia o script nos separadores e devolve (texto, byte que fechou)."""
    saida, atual = [], []
    for i in range(lo, hi):
        b = rom[i]
        if b in SEPARADORES:
            texto = "".join(atual).strip()
            if texto:
                saida.append((texto, b))
            atual = []
        else:
            atual.append(tabela.get(b, "{%02X}" % b))
    return saida


def ingles(texto: str) -> int:
    return len(set(re.findall(r"[a-z]{3,}", texto.lower())) & PALAVRAS_EN)


def alinhar(orig, outra):
    """Alinha pela sequencia de separadores, nao pelo conteudo.

    O conteudo esta em linguas diferentes, entao comparar texto nao alinha
    nada. A *estrutura* de controle, sim: ela sobrevive a traducao.
    """
    casamento = difflib.SequenceMatcher(
        None, [s for _, s in orig], [s for _, s in outra], autojunk=False
    )
    mapa = {}
    for a, b, n in casamento.get_matching_blocks():
        for k in range(n):
            mapa[a + k] = b + k
    return mapa


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    orig_p, hum_p, nos_p, tbl_p = (Path(a) for a in sys.argv[1:5])
    lo = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x8000
    hi = int(sys.argv[6], 0) if len(sys.argv) > 6 else 0xBD00

    orig, hum, nos = (p.read_bytes() for p in (orig_p, hum_p, nos_p))
    tabela = ler_tabela(tbl_p)

    uo = unidades(orig, tabela, lo, hi)
    uh = unidades(hum, tabela, lo, hi)
    un = unidades(nos, tabela, lo, hi)
    print(f"unidades: original {len(uo)}  humana {len(uh)}  nossa {len(un)}")

    mapa_h, mapa_n = alinhar(uo, uh), alinhar(uo, un)
    trios = [
        (uo[i][0], uh[mapa_h[i]][0], un[mapa_n[i]][0])
        for i in range(len(uo))
        if i in mapa_h and i in mapa_n
    ]
    print(f"alinhadas nas tres: {len(trios)}")

    com_ingles = [t for t in trios if ingles(t[0]) >= 2]
    ficou_hum = [t for t in com_ingles if ingles(t[1]) >= 2]
    ficou_nos = [t for t in com_ingles if ingles(t[2]) >= 2]
    print(f"\nunidades com ingles de verdade no original: {len(com_ingles)}")
    print(f"  ainda em ingles na humana: {len(ficou_hum)}")
    print(f"  ainda em ingles na nossa : {len(ficou_nos)}")

    for antes, depois, nossa in ficou_nos[:20]:
        print(f"\n  EN : {antes[:76]}")
        print(f"  hum: {depois[:76]}")
        print(f"  nos: {nossa[:76]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
