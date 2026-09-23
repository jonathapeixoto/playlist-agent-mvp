from contracts.models import IntentAction
from services.llm.api import AgentLLM, load_prompt, render_interpret_prompt
from services.llm.runner import RunResult


class FakeRunner:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def run(self, system, prompt, schema):
        self.calls.append((system, prompt, schema))
        return RunResult(data=self.data, latency_s=2.5, cost_usd=0.03)


def test_prompts_exist_and_cover_contract_fields():
    assert "reorganize" in load_prompt("interpret") and "normalize_tempo" in load_prompt("interpret")
    assert "keywords" in load_prompt("theme") and "candidates" in load_prompt("theme")


def test_render_interpret_prompt_keeps_last_10_turns_and_lists_playlists():
    history = [("usuário", f"m{i}") for i in range(15)]
    prompt = render_interpret_prompt("nova", history, ["Treino", "Relax"])
    assert "- Treino\n- Relax" in prompt
    assert "m4" not in prompt and "m5" in prompt and "m14" in prompt
    assert prompt.endswith("nova")


def test_interpret_parses_intent_and_traces():
    events = []
    runner = FakeRunner({"action": "chat", "reply": "Oi!", "options": []})
    llm = AgentLLM(runner, tracer=lambda event, **f: events.append((event, f)))
    intent = llm.interpret("oi", [], [])
    assert intent.action is IntentAction.CHAT
    assert runner.calls[0][0] == load_prompt("interpret")
    assert events == [("llm", {"kind": "interpret", "latency_s": 2.5, "cost_usd": 0.03, "motor": ""})]


def test_plan_theme_caps_slots():
    slots = [{"label": f"S{i}", "keywords": [f"k{i}"], "candidates": []} for i in range(8)]
    llm = AgentLLM(FakeRunner({"playlist_name": "P", "description": "d", "slots": slots}))
    plan = llm.plan_theme("prédio", max_slots=5)
    assert len(plan.slots) == 5


def test_trace_records_provider_and_model():
    events = []
    runner = FakeRunner({"action": "chat", "reply": "Oi!", "options": []})
    llm = AgentLLM(runner, tracer=lambda event, **f: events.append((event, f)), description="Google Gemini · flash")
    llm.interpret("oi", [], [])
    assert events[0][1]["motor"] == "Google Gemini · flash"


def test_set_runner_takes_effect_on_the_next_call():
    first = FakeRunner({"action": "chat", "reply": "um", "options": []})
    second = FakeRunner({"action": "chat", "reply": "dois", "options": []})
    llm = AgentLLM(first, description="A")
    assert llm.interpret("oi", [], []).reply == "um"
    llm.set_runner(second, "B")
    assert llm.interpret("oi", [], []).reply == "dois"
    assert llm.description == "B"
