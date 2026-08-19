"""Teste de fumaca: bootar a ROM e ver se ela roda.

Todas as outras checagens do projeto sao de bytes. Esta e a unica que percebe
uma ROM que passa em tudo e trava na primeira tela.
"""

import numpy as np
import pytest

from rom_translator.core.smoke import BOTOES, Fumaca


def test_rom_que_roda_passa():
    r = Fumaca(quadros=900, telas_distintas=6, fracao_preta=0.1)
    assert r.ok and r.veredito == "boota e roda"


def test_tela_preta_reprova():
    r = Fumaca(quadros=900, telas_distintas=6, fracao_preta=1.0)
    assert not r.ok and "preta" in r.veredito


def test_congelamento_reprova():
    r = Fumaca(quadros=900, telas_distintas=6, fracao_preta=0.1, congelou_em=412)
    assert not r.ok and "412" in r.veredito


def test_tela_quase_parada_reprova():
    """Uma ROM que boota mas nao sai do lugar tambem esta quebrada."""
    r = Fumaca(quadros=900, telas_distintas=1, fracao_preta=0.1)
    assert not r.ok and "quase nao muda" in r.veredito


def test_erro_de_emulador_reprova():
    r = Fumaca(erro="mapper nao suportado")
    assert not r.ok and "mapper" in r.veredito


def test_sem_a_dependencia_o_comando_avisa_em_vez_de_explodir(monkeypatch, tmp_path):
    import builtins

    from rom_translator.core import smoke

    real = builtins.__import__

    def sem_nes_py(nome, *args, **kwargs):
        if nome == "nes_py":
            raise ImportError("nao instalado")
        return real(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sem_nes_py)
    r = smoke.fumaca(tmp_path / "x.nes")
    assert not r.ok and "nes-py" in r.erro


def test_rom_invalida_vira_erro_nao_excecao(tmp_path):
    from rom_translator.core.smoke import fumaca

    ruim = tmp_path / "ruim.nes"
    ruim.write_bytes(b"nao sou uma ROM" * 40)
    r = fumaca(ruim, quadros=10)
    assert not r.ok and r.erro


def test_os_botoes_seguem_a_mascara_do_controle():
    assert BOTOES["A"] == 1 and BOTOES["start"] == 8
    assert len(set(BOTOES.values())) == 8
    assert sum(BOTOES.values()) == 0xFF
