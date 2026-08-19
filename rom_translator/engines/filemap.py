"""Motor que le traducoes prontas de um arquivo.

Existe por dois motivos. O primeiro e permitir que uma pessoa traduza -- o
pipeline inteiro passa a servir a quem quer controle sobre cada linha, nao so a
quem quer automacao. O segundo e testar: com traducoes fixas da para exercitar a
cadeia toda de ponta a ponta e comparar o resultado byte a byte, coisa que
nenhum motor de LLM permite.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import EngineConfig, TranslationEngine, TranslationRequest, TranslationResult


class FileEngine(TranslationEngine):
    name = "file"

    def __init__(self, config: EngineConfig | None = None, path: str | Path | None = None) -> None:
        super().__init__(config)
        if path is None:
            raise ValueError("o motor 'file' precisa de --translations")
        caminho = Path(path)
        texto = caminho.read_text(encoding="utf-8")
        if caminho.suffix.lower() in (".yaml", ".yml"):
            import yaml

            dados = yaml.safe_load(texto) or {}
        else:
            dados = json.loads(texto)
        self.mapa = {str(k): str(v) for k, v in dados.items()}

    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        resultados = []
        for pedido in requests:
            texto = self.mapa.get(pedido.text)
            resultados.append(
                TranslationResult(
                    pedido.id, texto, "" if texto else "sem traducao no arquivo"
                )
            )
        return resultados
