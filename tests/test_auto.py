"""Modo automatico: as travas antes de tudo, e a cadeia inteira depois."""

import pytest

from rom_translator.auto import (
    AutoReport, _espremer, _reapertar, acentos_necessarios, escolher_doadores,
    run_auto, sem_acento,
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


def _rom_com_ponteiros(tmp_path):
    """ROM sintetica com frases terminadas, uma tabela de ponteiros e espaco livre.

    Nenhuma das ROMs reais testadas ate agora exercita a realocacao: ou nao da
    para saber o terminador, ou a busca de ponteiros nao acha tabela. Este caso
    existe para provar que a ligacao no `auto` esta certa mesmo assim.
    """
    frases = [
        "the king waits for thee in the castle beyond the river",
        "travel not to the south for the monsters are fierce there",
        "many brave warriors have perished upon this dangerous quest",
        "thou must find the sword before facing the ancient dragon",
        "the princess is held within the cave to the far east",
        "return the water to the fountain and the town shall live",
        "a magic cane lies buried at the foot of the old tree",
        "speak with the elder and he shall tell thee of the globe",
        "the golden harp beckons to the creatures of the darkness",
        "rest here and thy wounds shall heal before the long road",
    ]
    corpo = bytearray()
    offsets = []
    for frase in frases * 14:  # precisa passar de 4 KiB para a deducao de alfabeto opinar
        offsets.append(0x400 + len(corpo))
        corpo += frase.encode("ascii") + b"\x00"

    dados = bytearray(b"\x00" * 0x400) + corpo
    dados += b"\x00" * ((0x100 - len(dados) % 0x100) % 0x100)
    tabela_ptr = len(dados)
    for offset in offsets:
        dados += offset.to_bytes(3, "little")
    dados += b"\xff" * 0x800  # espaco livre para receber o texto movido

    caminho = tmp_path / "componteiros.bin"
    caminho.write_bytes(bytes(dados))
    return caminho, tabela_ptr, len(offsets)


def test_realoca_quando_a_traducao_nao_cabe(tmp_path):
    import json

    from rom_translator.core.rom import Rom
    from rom_translator.core.table import Table

    rom, _, _ = _rom_com_ponteiros(tmp_path)
    saida = tmp_path / "s"
    primeiro = run_auto(rom, saida, engine_name="dummy", accents=False,
                        terminator=0x00, log=lambda m: None)
    assert primeiro.round_trip_ok

    script = Script.load(next(saida.glob("*.script.json")))
    alvo = max(script.units, key=lambda u: len(u.text))
    # sem [END]: a tabela so ganha o terminador depois, quando a realocacao e preparada
    longa = alvo.text + " e mais texto que nao cabe no lugar"
    arquivo = tmp_path / "t.json"
    arquivo.write_text(json.dumps({alvo.text: longa}), encoding="utf-8")

    report = run_auto(rom, tmp_path / "s2", engine_name="file",
                      engine_kwargs={"path": arquivo}, accents=False,
                      terminator=0x00, log=lambda m: None)
    # a mesma frase se repete na ROM, entao todas as copias sao movidas
    repeticoes = sum(1 for u in script.units if u.text == alvo.text)
    assert report.tabelas_de_ponteiro > 0, "devia ter achado a tabela de ponteiros"
    assert report.realocadas == repeticoes, report.motivo_sem_realocar
    assert report.nao_couberam == 0

    # o original nao pode ter sido tocado onde a string cabia
    traduzida = bytes(Rom.load(report.saidas["rom"]).data)
    assert len(traduzida) == len(rom.read_bytes()), "realocar nao expande a ROM"


def test_o_ponteiro_passa_a_apontar_para_o_texto_movido(tmp_path):
    import json

    from rom_translator.core.rom import Rom
    from rom_translator.core.table import Table

    rom, tabela_ptr, quantos_ponteiros = _rom_com_ponteiros(tmp_path)
    saida = tmp_path / "s"
    run_auto(rom, saida, engine_name="dummy", accents=False, terminator=0x00,
             log=lambda m: None)
    script = Script.load(next(saida.glob("*.script.json")))
    alvo = max(script.units, key=lambda u: len(u.text))
    longa = alvo.text + " com bastante texto sobrando aqui"
    arquivo = tmp_path / "t.json"
    arquivo.write_text(json.dumps({alvo.text: longa}), encoding="utf-8")

    report = run_auto(rom, tmp_path / "s2", engine_name="file",
                      engine_kwargs={"path": arquivo}, accents=False,
                      terminator=0x00, log=lambda m: None)
    assert report.realocadas > 0

    traduzida = bytes(Rom.load(report.saidas["rom"]).data)
    tabela = Table.load(report.saidas["tabela"])
    # acha o ponteiro que mudou e le o que ha no destino
    original = rom.read_bytes()
    mudou = [
        i for i in range(tabela_ptr, tabela_ptr + quantos_ponteiros * 3, 3)
        if traduzida[i : i + 3] != original[i : i + 3]
    ]
    assert len(mudou) == report.realocadas, "um ponteiro reescrito por string movida"
    for posicao in mudou:
        destino = int.from_bytes(traduzida[posicao : posicao + 3], "little")
        lido = tabela.decode(traduzida, destino, 200, stop_at_end=True).text
        assert lido.replace("[END]", "") == longa, "o ponteiro tem que achar o texto novo"


def test_pesca_os_nomes_proprios_do_jogo():
    """Maiuscula fora do inicio da frase, e ausente do lexico: nome do jogo."""
    from rom_translator.auto import nomes_proprios

    script = Script(units=[
        Unit(id="u1", offset=0, length=1, text="the Dragonlord waits in the castle", max_len=1),
        Unit(id="u2", offset=1, length=1, text="Erdrick fought here long ago", max_len=1),
        Unit(id="u3", offset=2, length=1, text="go to Tantegel and speak with Lorik", max_len=1),
    ])
    lexico = {"the", "waits", "castle", "fought", "here", "long", "ago", "and",
              "speak", "with", "erdrick"}
    achados = nomes_proprios(script, lexico)
    assert "Dragonlord" in achados and "Tantegel" in achados and "Lorik" in achados
    # 'Erdrick' abre a frase, entao nao conta -- e esta no lexico de qualquer forma
    assert achados["Dragonlord"] == "Dragonlord", "o glossario manda copiar, nao traduzir"


def test_nome_proprio_no_inicio_da_frase_nao_conta():
    from rom_translator.auto import nomes_proprios

    script = Script(units=[
        Unit(id="u", offset=0, length=1, text="Castle guards stand here", max_len=1),
    ])
    assert "Castle" not in nomes_proprios(script, {"guards", "stand", "here"})


# --- reaperto: o estouro de 1 ou 2 caracteres ---------------------------------


def _tabela_simples() -> Table:
    return ascii_table()


def test_espremer_tira_espaco_duplicado():
    t = _tabela_simples()
    assert _espremer("Bem  vindo   a Kol", "Welcome to Kol", t, 16) == "Bem vindo a Kol"


def test_espremer_tira_ponto_que_o_modelo_inventou():
    t = _tabela_simples()
    # o original nao termina em ponto, entao o ponto e folga
    assert _espremer("Boa noite.", "Good night", t, 9) == "Boa noite"


def test_espremer_preserva_ponto_que_o_original_tinha():
    t = _tabela_simples()
    # aqui o ponto e do texto, nao e folga: nao ha o que espremer
    assert _espremer("Boa noite.", "Good night.", t, 9) is None


def test_espremer_desiste_quando_nao_ha_folga():
    t = _tabela_simples()
    assert _espremer("CONTINUAR", "CONTINUE", t, 8) is None


def test_espremer_nao_devolve_o_que_continua_estourando():
    t = _tabela_simples()
    # da para tirar um espaco, mas ainda assim nao cabe em 5
    assert _espremer("um  dois", "one two", t, 5) is None


def test_reapertar_conserta_sozinho_o_que_e_so_espaco():
    t = _tabela_simples()
    script = Script(units=[
        Unit(id="u0", offset=0, length=15, text="Welcome to Kol",
             max_len=15, translation="Bem  vindo a Kol"),
    ])
    report = AutoReport()
    chamou = []
    _reapertar(_engine_que_falha(chamou), script, t, None, report, lambda *_: None)
    assert script.units[0].translation == "Bem vindo a Kol"
    assert report.espremidas == 1
    assert not chamou, "nao devia gastar o modelo no que espaco resolve"


def test_reapertar_ignora_o_que_ja_cabe():
    t = _tabela_simples()
    script = Script(units=[
        Unit(id="u0", offset=0, length=20, text="Welcome",
             max_len=20, translation="Bem vindo"),
    ])
    report = AutoReport()
    chamou = []
    _reapertar(_engine_que_falha(chamou), script, t, None, report, lambda *_: None)
    assert report.espremidas == 0 and report.encurtadas == 0
    assert not chamou


def _engine_que_falha(registro):
    """Motor que grita se for chamado -- serve para provar que nao foi."""
    class _Motor:
        class config:
            batch_size = 8

        def translate_batch(self, pedidos):
            registro.append(pedidos)
            raise AssertionError("nao devia chamar o modelo")

    return _Motor()
