from services.agent.agent import Agent
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
