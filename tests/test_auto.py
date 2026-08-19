"""Modo automatico: as travas antes de tudo, e a cadeia inteira depois."""

import pytest

from rom_translator.auto import (
    acentos_necessarios, escolher_doadores, run_auto, sem_acento,
)
from rom_translator.core.script import Script, Unit
from rom_translator.core.table import Table, ascii_table

PROSA = (
    "the king said travel not to the south for there the monsters are fierce "
    "and terrible and thou must first battle many foes to become strong enough "
    "to face the dragon that stole the precious globe and hid it in the darkness "
)


def test_sem_acento_preserva_a_letra():
    assert sem_acento("ação não é fácil") == "acao nao e facil"
    assert sem_acento("sem acento") == "sem acento"


def test_acentos_necessarios_ignora_o_que_a_tabela_ja_tem():
    tabela = Table.parse("41=a\n42=ã\n")
    assert acentos_necessarios(["ãa"], tabela) == []
    assert "ç" in acentos_necessarios(["ação"], tabela)


def test_doadores_preferem_letras_ausentes_do_jogo():
    """O criterio nao e o que o idioma nao usa, e o que ESTE jogo nao usa."""
    tabela = Table.parse("\n".join(f"{0x41 + i:02X}={chr(0x61 + i)}" for i in range(26)))
    script = Script(units=[
        Unit(id="u1", offset=0, length=9, text="kwy zebra", max_len=9),
        Unit(id="u2", offset=9, length=3, text="kkk", max_len=3),
    ])
    doadores = escolher_doadores(["texto sem essas letras"], script, tabela, ["ã", "ç"])
    assert len(doadores) == 2
    # 'q' nao aparece no script; 'k' aparece quatro vezes -- 'q' deve vir antes
    assert "k" not in doadores or doadores.index("q") < doadores.index("k")


def test_doadores_nunca_sacrificam_letra_usada_na_traducao():
    tabela = Table.parse("\n".join(f"{0x41 + i:02X}={chr(0x61 + i)}" for i in range(26)))
    script = Script(units=[Unit(id="u", offset=0, length=4, text="abcd", max_len=4)])
    doadores = escolher_doadores(["kwyz"], script, tabela, ["ã", "ç", "é", "õ"])
    assert not ({"k", "w", "y", "z"} & set(doadores))


def _rom_sintetica(tmp_path, texto: str, nome: str = "jogo.bin"):
    """ROM de teste. Precisa passar de 4 KiB: abaixo disso a deducao de
    alfabeto se recusa a opinar, e o teste falharia pelo motivo errado."""
    corpo = texto.encode("ascii")
    dados = bytearray(b"\x00" * 0x200) + bytearray(corpo) + bytearray(b"\x00" * 0x200)
    caminho = tmp_path / nome
    caminho.write_bytes(bytes(dados))
    return caminho


def test_recusa_rom_que_a_triagem_reprova(tmp_path):
    """Texto comprimido nao tem como ser traduzido: melhor recusar que fingir."""
    # cacos de duas letras: o perfil de um jogo que comprime o dialogo
    rom = _rom_sintetica(tmp_path, "ab cd ef gh ij kl mn op qr st " * 400)
    report = run_auto(rom, tmp_path / "saida", engine_name="dummy", log=lambda m: None)
    assert report.veredito in ("texto comprimido", "sem texto legivel")
    assert not report.saidas, "nao devia ter escrito nada"


def test_cadeia_completa_com_traducoes_de_arquivo(tmp_path):
    import json

    rom = _rom_sintetica(tmp_path, PROSA * 40)
    traducoes = tmp_path / "t.json"
    saida = tmp_path / "saida"

    # descobre o que o dump extrai, para traduzir exatamente aquilo
    primeiro = run_auto(rom, saida, engine_name="dummy", accents=False,
                        log=lambda m: None)
    assert primeiro.round_trip_ok
    assert primeiro.unidades > 0

    script = Script.load(next(saida.glob("*.script.json")))
    mapa = {u.text: u.text.replace("the", "foo")[: u.max_len] for u in script.units[:3]}
    traducoes.write_text(json.dumps(mapa), encoding="utf-8")

    report = run_auto(rom, tmp_path / "saida2", engine_name="file",
                      engine_kwargs={"path": traducoes}, accents=False,
                      log=lambda m: None)
    assert report.round_trip_ok
    assert report.traduzidas == len(mapa)
    assert report.escritas == len(mapa), "traducao codificavel deveria ter sido escrita"
    assert {"projeto", "tabela", "rom", "bps"} <= set(report.saidas)


def test_o_patch_gerado_reproduz_a_rom(tmp_path):
    import json

    from rom_translator.core.patch import apply_bps
    from rom_translator.core.rom import Rom

    rom = _rom_sintetica(tmp_path, PROSA * 40)
    saida = tmp_path / "s"
    primeiro = run_auto(rom, saida, engine_name="dummy", accents=False, log=lambda m: None)
    script = Script.load(next(saida.glob("*.script.json")))
    mapa = {u.text: u.text.replace("the", "foo")[: u.max_len] for u in script.units[:3]}
    t = tmp_path / "t.json"
    t.write_text(json.dumps(mapa), encoding="utf-8")

    report = run_auto(rom, tmp_path / "s2", engine_name="file",
                      engine_kwargs={"path": t}, accents=False, log=lambda m: None)
    original = rom.read_bytes()
    traduzida = bytes(Rom.load(report.saidas["rom"]).data)
    assert apply_bps(original, report.saidas["bps"].read_bytes()) == traduzida


def test_motor_file_exige_arquivo():
    from rom_translator.engines import EngineConfig, build

    with pytest.raises(ValueError, match="translations"):
        build("file", EngineConfig())


def test_motor_file_le_yaml(tmp_path):
    from rom_translator.engines import EngineConfig, build
    from rom_translator.engines.base import TranslationRequest

    arquivo = tmp_path / "t.yaml"
    arquivo.write_text("Sword: Espada\n", encoding="utf-8")
    motor = build("file", EngineConfig(), path=arquivo)
    resultado = motor.translate_batch([
        TranslationRequest(id="a", text="Sword", max_chars=10),
        TranslationRequest(id="b", text="Shield", max_chars=10),
    ])
    assert resultado[0].text == "Espada"
    assert resultado[1].text is None and "sem traducao" in resultado[1].note


def test_traducao_com_caractere_fora_da_tabela_nao_e_escrita(tmp_path):
    """Melhor deixar a linha no original do que gravar byte que o jogo nao conhece."""
    import json

    rom = _rom_sintetica(tmp_path, PROSA * 40)
    saida = tmp_path / "s"
    run_auto(rom, saida, engine_name="dummy", accents=False, log=lambda m: None)
    script = Script.load(next(saida.glob("*.script.json")))
    # o texto sintetico e todo minusculo: a tabela deduzida nao tem maiusculas
    mapa = {u.text: u.text.upper()[: u.max_len] for u in script.units[:1]}
    arquivo = tmp_path / "t.json"
    arquivo.write_text(json.dumps(mapa), encoding="utf-8")

    report = run_auto(rom, tmp_path / "s2", engine_name="file",
                      engine_kwargs={"path": arquivo}, accents=False,
                      log=lambda m: None)
    assert report.traduzidas == 1
    assert report.escritas == 0
