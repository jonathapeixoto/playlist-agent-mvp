"""Monta o runner a partir da configuração escolhida pelo usuário."""

from __future__ import annotations

import httpx

from contracts.models import LLMConfig, ProviderKind
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.llm.registry import find
from services.llm.runner import LLMError


def build_runner(config: LLMConfig, http: httpx.Client | None = None):
    if config.provider is ProviderKind.CLAUDE_CODE:
        return ClaudeRunner(model=config.model or "opus")
    if not config.base_url:
        raise LLMError("Informe o endereço da API do provedor.")
    if not config.model:
        raise LLMError("Informe o modelo que o provedor deve usar.")
    return OpenAICompatibleRunner(config.base_url, config.model, config.api_key or None, http)


def describe(config: LLMConfig) -> str:
    preset = find(config.preset)
    label = preset.label if preset else config.base_url or config.provider.value
    return f"{label} · {config.model}"
