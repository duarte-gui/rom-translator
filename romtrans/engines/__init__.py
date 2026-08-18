"""Registro de motores de traducao."""

from __future__ import annotations

from .base import (
    EngineConfig,
    TranslationEngine,
    TranslationRequest,
    TranslationResult,
    mask_controls,
    unmask_controls,
)

__all__ = [
    "EngineConfig", "TranslationEngine", "TranslationRequest", "TranslationResult",
    "mask_controls", "unmask_controls", "build", "ENGINES",
]

#: nome -> caminho de importacao preguicosa (nao carrega SDK de quem nao usa)
ENGINES = {
    "dummy": ("romtrans.engines.dummy", "DummyEngine"),
    "claude": ("romtrans.engines.claude", "ClaudeEngine"),
    "ollama": ("romtrans.engines.ollama", "OllamaEngine"),
}


def build(name: str, config: EngineConfig, **kwargs) -> TranslationEngine:
    import importlib

    if name not in ENGINES:
        raise KeyError(f"motor desconhecido: {name!r} (disponiveis: {', '.join(ENGINES)})")
    module_name, class_name = ENGINES[name]
    engine_class = getattr(importlib.import_module(module_name), class_name)
    return engine_class(config=config, **kwargs)
