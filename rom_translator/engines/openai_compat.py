"""Motor para qualquer servidor com API no formato OpenAI.

Cobre Hermes Agent, LM Studio, vLLM, llama.cpp em modo servidor e o proprio
`/v1` do Ollama -- todos falam `POST /v1/chat/completions` com o mesmo corpo.
Como o modelo pode ser pequeno, o lote e menor que o do motor Claude e a leitura
da resposta tolera JSON embrulhado em cerca de codigo, que modelos locais
costumam produzir mesmo quando se pede JSON puro.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from .base import EngineConfig, TranslationEngine, TranslationRequest, TranslationResult

SISTEMA = """Voce traduz texto extraido de ROMs de videogame retro.

Regras invioláveis:
1. Marcadores como ⸤0⸥ ⸤1⸥ sao codigos de controle do jogo. Preserve TODOS, na
   mesma ordem, sem mudar o numero. Nunca invente um marcador novo.
2. Respeite o limite de caracteres de cada linha: e espaco fisico na ROM.
3. Preserve espacos no inicio e no fim do texto.
4. Nomes do glossario sao copiados, nunca traduzidos.

Responda SO com um array JSON: [{"id": "...", "text": "..."}]"""

CERCA = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


class OpenAICompatEngine(TranslationEngine):
    name = "openai"

    def __init__(
        self,
        config: EngineConfig | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "",
        timeout: int = 180,
        max_tokens: int = 4096,
    ) -> None:
        super().__init__(config)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
        if not self.base_url:
            raise ValueError("o motor 'openai' precisa de --base-url")
        self.api_key = api_key or _chave_do_ambiente()
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        if config and config.batch_size > 12:
            self.config.batch_size = 12  # modelo local se perde em lote grande

    def _chamar(self, caminho: str, corpo: dict | None = None) -> dict:
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        pedido = urllib.request.Request(
            f"{self.base_url}{caminho}",
            data=dados,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        with urllib.request.urlopen(pedido, timeout=self.timeout) as resposta:
            return json.loads(resposta.read())

    def modelos(self) -> list[str]:
        """Lista os modelos que o servidor expoe."""
        return [m["id"] for m in self._chamar("/v1/models").get("data", [])]

    def _prompt(self, pedidos: list[TranslationRequest]) -> str:
        partes = [SISTEMA, f"\nIdioma de destino: {self.config.target_lang}"]
        if self.config.game:
            partes.append(f"Jogo: {self.config.game}")
        if self.config.line_width:
            partes.append(
                f"As falas vem quebradas em linhas de {self.config.line_width} "
                "caracteres, sem espaco na quebra, entao palavras chegam coladas "
                "('goingto' e 'going to'). Leia a frase inteira. Nao separe nome "
                "proprio que so parece colado."
            )
        if self.config.glossary:
            entradas = "\n".join(
                f"  {k} -> {v}" for k, v in sorted(self.config.glossary.items())
            )
            partes.append(f"Glossario (obrigatorio):\n{entradas}")
        return "\n".join(partes)

    def translate_batch(
        self, requests: list[TranslationRequest]
    ) -> list[TranslationResult]:
        if not requests:
            return []
        carga = [
            {"id": r.id, "text": r.text, "max_chars": r.max_chars} for r in requests
        ]
        corpo = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": self._prompt(requests)},
                {
                    "role": "user",
                    "content": "Traduza cada linha:\n"
                    + json.dumps(carga, ensure_ascii=False, indent=1),
                },
            ],
        }
        try:
            resposta = self._chamar("/v1/chat/completions", corpo)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return [TranslationResult(r.id, None, f"servidor: {exc}") for r in requests]

        try:
            conteudo = resposta["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return [TranslationResult(r.id, None, "resposta sem conteudo") for r in requests]

        itens = _extrair_json(conteudo)
        if itens is None:
            return [TranslationResult(r.id, None, "resposta nao era JSON") for r in requests]
        por_id = {str(i.get("id")): str(i.get("text", "")) for i in itens if isinstance(i, dict)}
        return [
            TranslationResult(
                r.id,
                por_id.get(r.id),
                "" if r.id in por_id else "o modelo nao devolveu esta linha",
            )
            for r in requests
        ]


def _extrair_json(texto: str) -> list | None:
    """Le o array de traducoes mesmo embrulhado em cerca de codigo ou prosa."""
    for candidato in (texto, *(m.group(1) for m in CERCA.finditer(texto))):
        try:
            dados = json.loads(candidato)
        except json.JSONDecodeError:
            continue
        if isinstance(dados, list):
            return dados
        if isinstance(dados, dict):
            for chave in ("translations", "traducoes", "items", "data"):
                if isinstance(dados.get(chave), list):
                    return dados[chave]
    # ultimo recurso: o primeiro array que apareca no meio do texto
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio >= 0 < fim > inicio:
        try:
            dados = json.loads(texto[inicio : fim + 1])
            return dados if isinstance(dados, list) else None
        except json.JSONDecodeError:
            return None
    return None


def _chave_do_ambiente() -> str | None:
    for variavel in ("HERMES_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(variavel):
            return os.environ[variavel]
    for arquivo in ("hermes.env", "openai.env"):
        caminho = Path.home() / ".config" / "secrets" / arquivo
        if caminho.exists():
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                linha = linha.strip().removeprefix("export ").strip()
                if "=" in linha and not linha.startswith("#"):
                    return linha.split("=", 1)[1].strip().strip("'\"")
    return None
