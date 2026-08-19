"""Linhas de largura fixa: detectar, e re-quebrar a traducao na mesma largura."""

import pytest

from rom_translator.core.wrap import (
    cortar, desdobrar, detectar_largura, parece_nome_proprio, redobrar,
)

LEXICO = {
    "you", "with", "the", "tower", "going", "see", "king", "water", "fountain",
    "down", "from", "town", "help", "anything", "almost", "well", "flowing",
    "shoot", "shopping", "coming", "therefore", "together", "wolf", "lord",
    "star", "dragon", "magic", "hall",
}


def test_detecta_a_largura_quando_as_juncoes_se_concentram():
    textos = [
        "Could I help youwith anything",
        "If you are goingto see the king",
        "return the waterto the fountain",
        "When you go downfrom the town",
        "Water is flowingin our fountain",
        "The last well isalmost dry",
    ]
    largura = detectar_largura(textos, LEXICO | {"is", "our", "and", "in", "to"})
    assert largura is not None
    assert largura.valor == 16
    assert largura.confianca > 0.5


def test_nao_inventa_largura_quando_as_juncoes_se_espalham():
    """Dragon Warrior: as 'juncoes' sao nomes de inimigo, nao quebras de linha."""
    textos = [
        "the Wolflord guards the gate of the ancient keep",
        "beware the Starwyvern that circles above the tower",
        "a Dragonlord waits beyond the final door of stone",
        "the Magichall lies hidden under the frozen lake",
    ] * 3
    assert detectar_largura(textos, LEXICO) is None


def test_maiuscula_no_meio_da_frase_denuncia_nome_proprio():
    assert parece_nome_proprio("Dragonlord", primeiro=False)
    assert not parece_nome_proprio("Dragonlord", primeiro=True)
    assert not parece_nome_proprio("goingto", primeiro=False)


@pytest.mark.parametrize("palavra", ["shoot", "shopping", "coming", "therefore", "together"])
def test_nao_corta_palavra_que_existe(palavra):
    assert cortar(palavra, LEXICO) is None


def test_peca_curta_so_vale_se_for_palavra_funcional():
    """Sem essa trava, listas grandes de palavras cortam qualquer coisa."""
    assert cortar("goingto", LEXICO) == 5  # going + to
    assert cortar("aardvarkxy", LEXICO) is None


def test_desdobrar_separa_o_que_a_quebra_colou():
    assert desdobrar("If you are goingto see the king", 16, LEXICO) == (
        "If you are going to see the king"
    )


def test_desdobrar_sem_lexico_fatia_pela_largura():
    assert desdobrar("Could I help youwith anything", 16) == "Could I help you with anything"


def test_redobrar_completa_cada_linha_ate_a_largura():
    """O renderizador conta caracteres: linha curta faria a proxima comecar nela."""
    resultado = redobrar("se voce for ver o rei da cidade", 16)
    assert len(resultado[:16]) == 16
    assert resultado[:16] == "se voce for ver ".ljust(16)
    assert resultado.split() == "se voce for ver o rei da cidade".split()


def test_redobrar_parte_palavra_maior_que_a_linha():
    resultado = redobrar("antidisestablishmentarianism sim", 10)
    assert len(resultado) >= len("antidisestablishmentarianism sim")


def test_redobrar_nao_mexe_em_texto_vazio():
    assert redobrar("", 16) == ""
    assert redobrar("   ", 16) == "   "
