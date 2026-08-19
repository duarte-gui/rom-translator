"""Motor para servidores no formato OpenAI (Hermes Agent, LM Studio, vLLM...)."""

import json

import pytest

from rom_translator.engines import EngineConfig, build
from rom_translator.engines.base import TranslationRequest
from rom_translator.engines.openai_compat import OpenAICompatEngine, _extrair_json


def test_exige_endereco_do_servidor():
    with pytest.raises(ValueError, match="base-url"):
        build("openai", EngineConfig())


def test_lote_encolhe_para_modelo_local():
    """Modelo pequeno se perde em lote de 40 linhas."""
    motor = OpenAICompatEngine(EngineConfig(batch_size=40), base_url="http://x")
    assert motor.config.batch_size <= 12


@pytest.mark.parametrize(
    "resposta",
    [
        '[{"id": "a", "text": "oi"}]',
        'Claro!\n```json\n[{"id": "a", "text": "oi"}]\n```',
        '{"translations": [{"id": "a", "text": "oi"}]}',
        'Aqui esta: [{"id": "a", "text": "oi"}] espero ter ajudado',
    ],
)
def test_le_o_json_em_qualquer_embrulho(resposta):
    """Modelo local devolve JSON em cerca de codigo mesmo quando se pede puro."""
    assert _extrair_json(resposta) == [{"id": "a", "text": "oi"}]


def test_desiste_quando_nao_ha_json():
    assert _extrair_json("desculpe, nao consegui traduzir") is None


def test_o_prompt_carrega_glossario_e_largura():
    config = EngineConfig(
        target_lang="pt-BR", game="Dragon Warrior", line_width=16,
        glossary={"Erdrick": "Erdrick"},
    )
    motor = OpenAICompatEngine(config, base_url="http://x")
    prompt = motor._prompt([])
    assert "pt-BR" in prompt and "Dragon Warrior" in prompt
    assert "16" in prompt and "Erdrick -> Erdrick" in prompt


def test_falha_de_rede_vira_resultado_vazio_e_nao_excecao(monkeypatch):
    """Um lote perdido nao pode derrubar a traducao inteira."""
    motor = OpenAICompatEngine(EngineConfig(), base_url="http://x")

    def explode(*_args, **_kwargs):
        raise TimeoutError("sem resposta")

    monkeypatch.setattr(motor, "_chamar", explode)
    saida = motor.translate_batch([TranslationRequest(id="a", text="Sword", max_chars=8)])
    assert saida[0].text is None and "servidor" in saida[0].note


def test_linha_que_o_modelo_esqueceu_e_reportada(monkeypatch):
    motor = OpenAICompatEngine(EngineConfig(), base_url="http://x")
    monkeypatch.setattr(
        motor, "_chamar",
        lambda *a, **k: {"choices": [{"message": {"content": json.dumps(
            [{"id": "a", "text": "Espada"}]
        )}}]},
    )
    saida = motor.translate_batch([
        TranslationRequest(id="a", text="Sword", max_chars=8),
        TranslationRequest(id="b", text="Shield", max_chars=8),
    ])
    assert saida[0].text == "Espada"
    assert saida[1].text is None and "nao devolveu" in saida[1].note


def test_lote_vazio_nao_chama_o_servidor(monkeypatch):
    motor = OpenAICompatEngine(EngineConfig(), base_url="http://x")
    monkeypatch.setattr(motor, "_chamar", lambda *a, **k: pytest.fail("nao devia chamar"))
    assert motor.translate_batch([]) == []


def test_base_url_com_v1_nao_vira_v1_v1():
    """Colar o endereco com /v1 da 404 em toda linha, e em silencio."""
    motor = OpenAICompatEngine(base_url="http://host:8642/v1", model="m")
    assert motor.base_url == "http://host:8642"


def test_base_url_sem_v1_fica_como_esta():
    motor = OpenAICompatEngine(base_url="http://host:8642/", model="m")
    assert motor.base_url == "http://host:8642"
