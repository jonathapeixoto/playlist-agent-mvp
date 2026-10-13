import httpx
import pytest

from contracts.models import LLMConfig, ProviderKind
from services.llm.factory import build_runner, describe
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.llm.runner import LLMError


def test_builds_the_claude_code_runner():
    runner = build_runner(LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="haiku"))
    assert isinstance(runner, ClaudeRunner) and runner.model == "haiku"


def test_builds_the_openai_compatible_runner_with_key_and_shared_client():
    http = httpx.Client()
    config = LLMConfig(provider=ProviderKind.OPENAI, model="m", base_url="https://x/v1", api_key="k", preset="groq")
    runner = build_runner(config, http)
    assert isinstance(runner, OpenAICompatibleRunner)
    assert (runner.base_url, runner.model, runner.api_key) == ("https://x/v1", "m", "k")
    assert runner.http is http


def test_openai_compatible_without_base_url_is_refused():
    with pytest.raises(LLMError, match="endereço"):
        build_runner(LLMConfig(provider=ProviderKind.OPENAI, model="m", preset="custom"))


def test_openai_compatible_without_model_is_refused():
    with pytest.raises(LLMError, match="modelo"):
        build_runner(LLMConfig(provider=ProviderKind.OPENAI, model="", base_url="https://x/v1", preset="custom"))


def test_describe_uses_the_preset_label():
    assert describe(LLMConfig(provider=ProviderKind.OPENAI, model="gemini-2.5-flash",
                              base_url="https://x/v1", preset="gemini")) == "Google Gemini · gemini-2.5-flash"
    assert describe(LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus")) == "Claude Code (nesta máquina) · opus"
    assert describe(LLMConfig(provider=ProviderKind.OPENAI, model="m", base_url="https://x/v1",
                              preset="custom")) == "Personalizado · m"
