"""Triagem: dizer, antes de trabalhar, se a ROM da para traduzir sozinha."""

import pytest

from rom_translator.core.triage import Triagem, triar
from rom_translator.platforms import identify

PROSA = (
    "the king said travel not to the south for there the monsters are fierce "
    "and terrible and thou must first battle many foes to become strong enough "
    "to face the dragon that stole the precious globe and hid it in the darkness "
)


def _triagem(**kwargs) -> Triagem:
    base = dict(
        plataforma="nes", blocos=10, fracao_sinalizada=0.2, espaco=0x20,
        minusculas=0x61, maiusculas=0x41, palavras_reais=500, segundo_lugar=0,
        unidades=100, fracao_linguagem=0.95, mediana=17, p90=44,
        palavras_por_unidade=4.5, caracteres=2000,
    )
    return Triagem(**{**base, **kwargs})


def test_frases_longas_sao_consideradas_viaveis():
    assert _triagem().veredito == "automatica viavel"


def test_cacos_curtos_denunciam_compressao():
    """O perfil medido em Chrono Trigger, Golden Sun e Illusion of Gaia."""
    assert _triagem(mediana=5, p90=8, palavras_por_unidade=2.1).veredito == "texto comprimido"


def test_meio_termo_e_parcial():
    """Final Fantasy III: nomes de item legiveis, dialogo comprimido."""
    assert _triagem(mediana=8, p90=22, fracao_linguagem=0.80).veredito == "parcial"


def test_sem_alfabeto_nao_finge_veredito():
    assert _triagem(espaco=None, minusculas=None).veredito == "sem texto legivel"


def test_pouco_texto_nao_sustenta_veredito():
    assert _triagem(caracteres=50).veredito == "sem texto legivel"


def test_um_bloco_continuo_e_o_caso_mais_facil_nao_o_pior():
    """Contar unidades rejeitava a ROM que guarda o texto num bloco so."""
    assert _triagem(unidades=1, caracteres=13000).veredito == "automatica viavel"


def test_todo_veredito_tem_explicacao():
    for kwargs in ({}, {"mediana": 5, "p90": 8}, {"mediana": 8, "p90": 22},
                   {"espaco": None}):
        assert _triagem(**kwargs).explicacao


def test_triagem_sobre_texto_sintetico_sem_compressao():
    dados = bytes(
        0x20 if c == " " else (0x41 + ord(c) - ord("A")) if c.isupper()
        else (0x61 + ord(c) - ord("a"))
        for c in PROSA * 60 if c.isalpha() or c == " "
    )
    plugin, det = identify(dados)
    resultado = triar(dados, plugin, det)
    assert resultado.espaco == 0x20
    assert resultado.veredito == "automatica viavel"
    assert resultado.mediana >= 10
