"""Adaptador para qualquer API no formato da OpenAI: Gemini, Groq, OpenRouter, Mistral, Ollama, LM Studio."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx

from services.llm.runner import LLMError, RunResult


class OpenAICompatibleRunner:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or None
        self.http = http or httpx.Client()
        self.timeout = timeout
        self.clock = clock

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": schema},
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        start = self.clock()
        try:
            response = self.http.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as err:
            raise LLMError(f"Não consegui falar com {self.base_url}: {err}") from err
        latency = self.clock() - start
        if response.status_code in (401, 403):
            raise LLMError("O provedor recusou a chave. Confira a chave na configuração do motor de IA.")
        if response.status_code == 429:
            raise LLMError("O provedor atingiu o limite de uso. Tente de novo mais tarde ou escolha outro motor.")
        if response.status_code >= 400:
            raise LLMError(f"O provedor respondeu {response.status_code}: {response.text[:200]}")
        return RunResult(data=self._parse(response), latency_s=latency, cost_usd=0.0)

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as err:
            raise LLMError("Resposta do provedor fora do formato esperado.") from err
        if isinstance(content, list):
            # Alguns provedores devolvem o texto em pedaços.
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError) as err:
            raise LLMError(f"O modelo {self.model} não devolveu JSON. Escolha um modelo que aceite schema JSON.") from err
        if not isinstance(parsed, dict):
            raise LLMError(f"O modelo {self.model} devolveu JSON que não é um objeto.")
        return parsed
