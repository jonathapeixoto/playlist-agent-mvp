import json

import pytest
from fastapi.testclient import TestClient

from contracts.models import LLMConfig, ProviderKind
from services.llm.compat import CompatCheck, CompatReport
from services.llm.config_store import LLMConfigStore
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class FakeLLM:
    def __init__(self):
        self.description = "Claude Code (nesta máquina) · opus"
        self.runner = object()

    def set_runner(self, runner, description):
        self.runner = runner
        self.description = description


def _report(ok: bool) -> CompatReport:
    detail = "ok" if ok else "o modelo não devolveu JSON"
    return CompatReport([CompatCheck("Entender um pedido simples", ok, detail, 0.4)])


@pytest.fixture
def ctx(tmp_path):
    calls = {"checked": []}

    def compat_check(runner):
        calls["checked"].append(runner)
        return _report(calls.get("ok", True))

    deps = AppDeps(
        agent=None, auth=None, settings=Settings(spotify_client_id="cid", data_dir=tmp_path),
        trace_path=tmp_path / "t.jsonl", claude_ok=True, llm=FakeLLM(),
        llm_store=LLMConfigStore(tmp_path / "llm.json"), http=None, compat_check=compat_check,
    )
    return TestClient(create_app(deps)), deps, calls


def test_get_llm_lists_presets_and_current_engine(ctx):
    client, deps, _ = ctx
    data = client.get("/api/llm").json()
    assert data["description"] == "Claude Code (nesta máquina) · opus"
    assert data["current"]["provider"] == "claude_code"
    assert data["current"]["has_key"] is False
    keys = [p["key"] for p in data["presets"]]
    assert {"claude_code", "gemini", "groq", "ollama", "custom"} <= set(keys)


def test_test_route_does_not_save(ctx):
    client, deps, calls = ctx
    body = {"preset": "gemini", "model": "gemini-2.5-flash", "api_key": "k-1"}
    data = client.post("/api/llm/test", json=body).json()
    assert data["ok"] is True
    assert deps.llm_store.load() is None
    assert deps.llm.description == "Claude Code (nesta máquina) · opus"


def test_save_runs_the_check_stores_and_swaps(ctx):
    client, deps, _ = ctx
    body = {"preset": "groq", "model": "llama-3.3-70b-versatile", "api_key": "k-2"}
    data = client.post("/api/llm", json=body).json()
    assert data["ok"] is True
    assert data["description"] == "Groq · llama-3.3-70b-versatile"
    saved = deps.llm_store.load()
    assert saved.api_key == "k-2" and saved.base_url == "https://api.groq.com/openai/v1"
    assert deps.llm.description == "Groq · llama-3.3-70b-versatile"


def test_save_is_refused_when_the_check_fails(ctx):
    client, deps, calls = ctx
    calls["ok"] = False
    response = client.post("/api/llm", json={"preset": "gemini", "model": "modelo-fraco", "api_key": "k"})
    assert response.status_code == 400
    assert response.json()["report"]["checks"][0]["detail"] == "o modelo não devolveu JSON"
    assert deps.llm_store.load() is None
    assert deps.llm.description == "Claude Code (nesta máquina) · opus"


def test_key_is_kept_when_the_user_does_not_retype_it(ctx):
    client, deps, _ = ctx
    client.post("/api/llm", json={"preset": "groq", "model": "m1", "api_key": "k-3"})
    client.post("/api/llm", json={"preset": "groq", "model": "m2", "api_key": ""})
    saved = deps.llm_store.load()
    assert saved.model == "m2" and saved.api_key == "k-3"


def test_switching_preset_without_a_key_starts_empty(ctx):
    client, deps, _ = ctx
    client.post("/api/llm", json={"preset": "groq", "model": "m1", "api_key": "k-3"})
    client.post("/api/llm", json={"preset": "gemini", "model": "m2", "api_key": ""})
    assert deps.llm_store.load().api_key == ""


def test_custom_preset_requires_a_base_url(ctx):
    client, _, _ = ctx
    response = client.post("/api/llm", json={"preset": "custom", "model": "m", "base_url": ""})
    assert response.status_code == 502
    assert "endereço" in response.json()["detail"]


def test_claude_code_preset_saves_without_key_or_url(ctx):
    client, deps, _ = ctx
    assert client.post("/api/llm", json={"preset": "claude_code", "model": "haiku"}).json()["ok"] is True
    assert deps.llm_store.load().provider == ProviderKind.CLAUDE_CODE


def test_key_is_not_reused_when_the_custom_endpoint_changes(ctx):
    client, deps, _ = ctx
    client.post("/api/llm", json={"preset": "custom", "model": "m", "base_url": "https://a.exemplo/v1", "api_key": "k-a"})
    client.post("/api/llm", json={"preset": "custom", "model": "m", "base_url": "https://b.exemplo/v1", "api_key": ""})
    saved = deps.llm_store.load()
    assert saved.base_url == "https://b.exemplo/v1"
    assert saved.api_key == ""
