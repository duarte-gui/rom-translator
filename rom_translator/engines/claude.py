"""Motor de traducao usando a API da Anthropic.

Tres decisoes que valem explicar:

* **Saida estruturada.** O modelo devolve um JSON com um item por unidade, contra
  um schema. Sem isso sobraria parsing fragil de texto solto -- e uma linha
  perdida no meio de um lote de 40 desalinha tudo.
* **Cache de prompt.** As instrucoes e o glossario sao identicos em todos os
  lotes e ficam num bloco de sistema marcado para cache: a partir do segundo
  lote esse prefixo custa ~10% do preco.
* **Esforco baixo.** Traduzir linha de dialogo com limite de caracteres e
  trabalho mecanico. `effort: low` no Opus 5 entrega qualidade equivalente por
  uma fracao dos tokens; o dificil aqui e o limite de espaco, nao o raciocinio.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .base import EngineConfig, TranslationEngine, TranslationRequest, TranslationResult

DEFAULT_MODEL = "claude-opus-5"

SYSTEM = """Voce traduz texto extraido de ROMs de videogame retro.

Regras invioláveis:
1. Marcadores como ⸤0⸥ ⸤1⸥ sao codigos de controle do jogo (fim de fala, quebra
   de linha, nome do personagem). Preserve TODOS, na mesma ordem, sem alterar o
   numero. Nunca invente um marcador novo.
2. Respeite o limite de caracteres de cada linha. E espaco fisico na ROM: o que
   passar do limite nao entra no jogo. Prefira uma traducao mais curta e natural
   a uma literal que estoure.
3. Preserve espacos no inicio e no fim -- muitos jogos centralizam texto com eles.
4. Nomes proprios de personagens e lugares seguem o glossario quando houver.
   Entrada em que original e traducao sao iguais quer dizer: nao traduza, copie.
5. Mantenha o registro do original: fala informal continua informal.

Responda apenas com o JSON pedido."""

SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def _load_api_key() -> str | None:
    """Chave da API: variavel de ambiente ou ~/.config/secrets/anthropic.env."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    secrets = Path.home() / ".config" / "secrets" / "anthropic.env"
    if secrets.exists():
        for line in secrets.read_text(encoding="utf-8").splitlines():
            line = line.strip().removeprefix("export ").strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


class ClaudeEngine(TranslationEngine):
    name = "claude"

    def __init__(
        self,
        config: EngineConfig | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = "low",
        max_tokens: int = 16000,
    ) -> None:
        super().__init__(config)
        import anthropic  # importado aqui para nao pesar quem usa outro motor

        key = _load_api_key()
        # sem chave explicita o SDK ainda resolve credenciais do ambiente
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def _system_blocks(self) -> list[dict]:
        parts = [SYSTEM]
        if self.config.game:
            parts.append(f"\nJogo: {self.config.game}")
        parts.append(f"\nIdioma de destino: {self.config.target_lang}")
        if self.config.alphabet:
            alfabeto = self.config.alphabet
            texto = (
                f"\n\nA fonte do jogo tem estes caracteres: {alfabeto}\n"
                "Letras acentuadas do idioma de destino sao permitidas -- os "
                "glifos que faltarem sao desenhados depois. Sinais de pontuacao "
                "NAO sao: nada de hifen, apostrofo, virgula, ponto, dois-pontos "
                "ou reticencias. Reescreva a frase para nao precisar deles -- "
                "'Ofereco-te' vira 'Ofereco a ti', nao 'Oferecote'."
            )
            parts.append(texto)
        if self.config.line_width:
            parts.append(
                f"\n\nO jogo quebra as falas em linhas de {self.config.line_width} "
                "caracteres e nao guarda espaco na quebra, entao palavras chegam "
                "coladas: 'goingto' e 'going to', 'youwith' e 'you with'. Leia "
                "assim e traduza a frase inteira. Cuidado para nao separar nome "
                "proprio que so parece colado -- 'Dragonlord' e um nome, nao "
                "'Dragon lord'."
            )
        if self.config.glossary:
            entries = "\n".join(f"  {k} -> {v}" for k, v in sorted(self.config.glossary.items()))
            parts.append(f"\nGlossario (obrigatorio):\n{entries}")
        # bloco estavel entre lotes -> cacheavel
        return [
            {
                "type": "text",
                "text": "".join(parts),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        if not requests:
            return []
        payload = [
            {"id": r.id, "text": r.text, "max_chars": r.max_chars,
             **({"observacao": r.context} if r.context else {})}
            for r in requests
        ]
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self._system_blocks(),
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": "Traduza cada linha:\n"
                    + json.dumps(payload, ensure_ascii=False, indent=1),
                }
            ],
        )
        if message.stop_reason == "refusal":
            return [TranslationResult(r.id, None, "recusado pelo modelo") for r in requests]

        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [TranslationResult(r.id, None, "resposta nao era JSON") for r in requests]

        by_id = {item["id"]: item["text"] for item in data.get("translations", [])}
        return [
            TranslationResult(
                r.id,
                by_id.get(r.id),
                "" if r.id in by_id else "o modelo nao devolveu esta linha",
            )
            for r in requests
        ]
