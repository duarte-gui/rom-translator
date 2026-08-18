"""Motores de traducao: mascaramento de codigos de controle e contrato."""

import pytest

from rom_translator.engines import EngineConfig, build, mask_controls, unmask_controls
from rom_translator.engines.base import TranslationRequest


@pytest.mark.parametrize(
    "text",
    [
        "Bem-vindo ao castelo[END]",
        "Ola[LINE]tudo bem?[END]",
        "[NOME] encontrou [$1F] moedas[END]",
        "sem nenhum codigo",
        "[END]",
    ],
)
def test_control_codes_survive_the_round_trip(text):
    """A invariante que impede o LLM de inventar bytes de controle."""
    masked, tokens = mask_controls(text)
    assert "[" not in masked, "sobrou codigo de controle visivel para o modelo"
    assert unmask_controls(masked, tokens) == text


def test_masking_numbers_placeholders_in_order():
    masked, tokens = mask_controls("a[X]b[Y]c")
    assert masked == "a⸤0⸥b⸤1⸥c"
    assert tokens == ["[X]", "[Y]"]


def test_unmask_leaves_unknown_placeholder_alone():
    """Se o modelo inventar um marcador, ele fica visivel em vez de virar lixo."""
    assert unmask_controls("a⸤9⸥b", ["[X]"]) == "a⸤9⸥b"


def test_dummy_engine_respects_the_length_budget():
    engine = build("dummy", EngineConfig())
    results = engine.translate_batch(
        [TranslationRequest(id="u1", text="uma frase bem longa", max_chars=5)]
    )
    assert len(results[0].text) <= 5


def test_dummy_engine_returns_one_result_per_request():
    engine = build("dummy", EngineConfig())
    requests = [TranslationRequest(id=f"u{i}", text=f"linha {i}", max_chars=20) for i in range(5)]
    results = engine.translate_batch(requests)
    assert [r.id for r in results] == [r.id for r in requests]


def test_dummy_engine_handles_empty_batch():
    assert build("dummy", EngineConfig()).translate_batch([]) == []


def test_unknown_engine_is_rejected():
    with pytest.raises(KeyError, match="motor desconhecido"):
        build("inexistente", EngineConfig())


def test_claude_engine_is_lazy():
    """Registrar o motor Claude nao pode exigir o SDK nem uma chave de API."""
    from rom_translator.engines import ENGINES

    assert "claude" in ENGINES and "ollama" in ENGINES


def test_claude_schema_is_strict():
    """Saida estruturada exige additionalProperties=false em todo objeto."""
    from rom_translator.engines.claude import SCHEMA

    assert SCHEMA["additionalProperties"] is False
    assert SCHEMA["properties"]["translations"]["items"]["additionalProperties"] is False
    assert SCHEMA["properties"]["translations"]["items"]["required"] == ["id", "text"]
