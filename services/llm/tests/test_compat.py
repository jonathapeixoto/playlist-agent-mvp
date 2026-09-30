import pytest

from services.llm.compat import check
from services.llm.runner import LLMError, RunResult

INTENT_OK = {
    "action": "reorganize", "reply": "Posso fazer assim:", "playlist_name": "Treino",
    "options": [{"kind": "bpm", "label": "BPM crescente", "description": "d", "bpm_mode": "asc"}],
}
THEME_OK = {
    "playlist_name": "Playlist colorida", "description": "cores nos títulos",
    "slots": [
        {"label": "Azul", "keywords": ["Azul"], "candidates": [{"title": "Azul", "artist": "X"}]},
        {"label": "Verde", "keywords": ["Verde"], "candidates": [{"title": "Verde", "artist": "Y"}]},
    ],
}


class FakeRunner:
    """Responde conforme o schema pedido: Intent ou ThemePlan."""

    def __init__(self, intent=INTENT_OK, theme=THEME_OK, raises=None):
        self.intent = intent
        self.theme = theme
        self.raises = raises
        self.calls = 0

    def run(self, system, prompt, schema):
        self.calls += 1
        if self.raises:
            raise self.raises
        data = self.theme if "slots" in schema["properties"] else self.intent
        return RunResult(data=data, latency_s=0.5, cost_usd=0.0)


def test_good_engine_passes_all_three_checks():
    runner = FakeRunner()
    report = check(runner)
    assert report.ok
    assert [c.name for c in report.checks] == [
        "Entender um pedido simples", "Propor opções para um pedido aberto", "Montar um tema pequeno"
    ]
    assert runner.calls == 3
    assert all(c.latency_s >= 0 for c in report.checks)


def test_engine_that_misreads_the_request_fails_the_first_check():
    intent = {**INTENT_OK, "action": "chat", "playlist_name": None, "options": []}
    report = check(FakeRunner(intent=intent))
    assert not report.ok
    assert not report.checks[0].ok and "action" in report.checks[0].detail


def test_engine_that_proposes_nothing_fails():
    report = check(FakeRunner(intent={**INTENT_OK, "options": []}))
    assert not report.ok
    assert "opção" in report.checks[1].detail


def test_engine_with_a_weak_theme_fails_the_third_check():
    theme = {**THEME_OK, "slots": THEME_OK["slots"][:1]}
    report = check(FakeRunner(theme=theme))
    assert report.checks[0].ok and report.checks[1].ok
    assert not report.checks[2].ok and "posições" in report.checks[2].detail


def test_theme_without_candidates_fails():
    theme = {**THEME_OK, "slots": [{"label": "Azul", "keywords": ["Azul"], "candidates": []},
                                   {"label": "Verde", "keywords": ["Verde"], "candidates": []}]}
    assert "sugestões" in check(FakeRunner(theme=theme)).checks[2].detail


def test_engine_error_becomes_the_failure_reason():
    report = check(FakeRunner(raises=LLMError("O provedor recusou a chave.")))
    assert not report.ok
    assert all("recusou a chave" in c.detail for c in report.checks)


def test_report_to_dict_is_serializable():
    data = check(FakeRunner()).to_dict()
    assert data["ok"] is True
    assert data["checks"][0]["name"] == "Entender um pedido simples"
    assert set(data["checks"][0]) == {"name", "ok", "detail", "latency_s"}
