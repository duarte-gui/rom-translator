"""Motor de teste: nao traduz nada, so transforma o texto de forma previsivel.

Existe para exercitar o pipeline inteiro -- dump, traducao, reinsercao, patch --
sem gastar um token sequer e sem depender de rede. E o motor que os testes usam.
"""

from __future__ import annotations

from .base import TranslationEngine, TranslationRequest, TranslationResult


class DummyEngine(TranslationEngine):
    name = "dummy"

    def __init__(self, config=None, mode: str = "upper") -> None:
        super().__init__(config)
        self.mode = mode

    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        results = []
        for request in requests:
            if self.mode == "upper":
                text = request.text.upper()
            elif self.mode == "reverse":
                text = request.text[::-1]
            else:  # "identity"
                text = request.text
            results.append(TranslationResult(id=request.id, text=text[: request.max_chars]))
        return results
