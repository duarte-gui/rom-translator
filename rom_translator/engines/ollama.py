"""Motor local via Ollama.

Modelo local nao segue schema de forma confiavel num lote grande, entao aqui a
traducao e uma linha por vez com prompt curto. E mais lento, mas roda offline e
de graca -- util para varrer um script inteiro antes de gastar API nas linhas
que importam.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import EngineConfig, TranslationEngine, TranslationRequest, TranslationResult

PROMPT = """Traduza para {lang} o texto de um jogo retro.
Preserve exatamente os marcadores no formato ⸤0⸥ (codigos de controle do jogo).
Maximo de {max_chars} caracteres. Responda SO com a traducao, sem aspas nem comentario.

{text}"""


class OllamaEngine(TranslationEngine):
    name = "ollama"

    def __init__(
        self,
        config: EngineConfig | None = None,
        model: str = "llama3.1",
        host: str = "http://localhost:11434",
        timeout: int = 120,
    ) -> None:
        super().__init__(config)
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _generate(self, prompt: str) -> str | None:
        body = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())["response"].strip()
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
            return None

    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        results = []
        for request in requests:
            answer = self._generate(
                PROMPT.format(
                    lang=self.config.target_lang,
                    max_chars=request.max_chars,
                    text=request.text,
                )
            )
            results.append(
                TranslationResult(
                    request.id,
                    answer,
                    "" if answer else "Ollama nao respondeu",
                )
            )
        return results
