from contracts.models import LLMConfig, ProviderKind
from services.agent.agent import Agent
from services.llm.config_store import LLMConfigStore
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.web.settings import Settings
from services.web.wiring import build_deps


def test_build_deps_wires_everything_without_network(tmp_path):
    deps = build_deps(Settings(spotify_client_id="cid", data_dir=tmp_path), claude_ok=False)
    assert isinstance(deps.agent, Agent)
    assert deps.trace_path == tmp_path / "traces.jsonl"
    assert (tmp_path / "cache.sqlite").exists()
    assert not deps.auth.has_token()


def test_enricher_looks_up_alternate_versions_through_spotify_search(tmp_path):
    deps = build_deps(Settings(spotify_client_id="cid", data_dir=tmp_path), claude_ok=False)
    finder = deps.agent.enricher.alternates
    assert finder is not None
    assert finder.search.__self__ is deps.agent.spotify


def test_without_saved_config_the_engine_is_claude_code(tmp_path):
    deps = build_deps(Settings(spotify_client_id="cid", data_dir=tmp_path), claude_ok=False)
    assert isinstance(deps.llm.runner, ClaudeRunner)
    assert deps.llm.description.startswith("Claude Code")
    assert deps.llm_store.load() is None


def test_saved_config_is_used_on_startup(tmp_path):
    LLMConfigStore(tmp_path / "llm.json").save(
        LLMConfig(provider=ProviderKind.OPENAI, model="gemini-2.5-flash",
                  base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                  api_key="k-1", preset="gemini")
    )
    deps = build_deps(Settings(spotify_client_id="cid", data_dir=tmp_path), claude_ok=False)
    assert isinstance(deps.llm.runner, OpenAICompatibleRunner)
    assert deps.llm.runner.api_key == "k-1"
    assert deps.llm.description == "Google Gemini · gemini-2.5-flash"
