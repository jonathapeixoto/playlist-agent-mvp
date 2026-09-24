import json

from services.agent.trace import Tracer, summarize


def test_tracer_appends_json_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path, clock=lambda: 5.0)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.03)
    tracer("plan", bpm_coverage=0.8, genre_coverage=0.5)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"ts": 5.0, "event": "llm", "kind": "interpret", "latency_s": 2.0, "cost_usd": 0.03}


def test_summarize_computes_metrics(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.03)
    tracer("llm", kind="theme", latency_s=4.0, cost_usd=0.05)
    tracer("plan", bpm_coverage=1.0, genre_coverage=0.5)
    tracer("plan", bpm_coverage=0.5, genre_coverage=0.5)
    tracer("theme", candidates_tried=10, candidates_valid=7)
    tracer("apply", mode="new", playlists=1)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("linha quebrada\n")
    stats = summarize(path)
    assert stats["llm_calls"] == 2
    assert stats["llm_avg_latency_s"] == 3.0
    assert stats["llm_total_cost_usd"] == 0.08
    assert stats["avg_bpm_coverage"] == 0.75
    assert stats["theme_validation_rate"] == 0.7
    assert stats["applies"] == 1


def test_summarize_missing_file(tmp_path):
    stats = summarize(tmp_path / "nada.jsonl")
    assert stats["events"] == 0 and stats["avg_bpm_coverage"] is None


def test_summarize_groups_by_engine(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.10, motor="Claude Code (nesta máquina) · opus")
    tracer("llm", kind="theme", latency_s=4.0, cost_usd=0.20, motor="Claude Code (nesta máquina) · opus")
    tracer("llm", kind="interpret", latency_s=1.0, cost_usd=0.0, motor="Google Gemini · gemini-2.5-flash")
    tracer("llm", kind="interpret", latency_s=1.0, cost_usd=0.0)
    by_motor = summarize(path)["llm_by_motor"]
    assert by_motor["Claude Code (nesta máquina) · opus"] == {"calls": 2, "cost_usd": 0.3, "avg_latency_s": 3.0}
    assert by_motor["Google Gemini · gemini-2.5-flash"]["calls"] == 1
    assert by_motor["desconhecido"]["calls"] == 1
