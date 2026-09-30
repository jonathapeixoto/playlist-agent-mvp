from contracts.models import Intent, StrategyChoice
from services.llm.scoring import score_intent


def _intent(**kw):
    base = {"action": "reorganize", "reply": "ok", "playlist_name": "Treino", "options": []}
    base.update(kw)
    return Intent.model_validate(base)


def _opt(kind):
    return StrategyChoice(kind=kind, label="x", description="y")


def test_passes_when_action_playlist_and_kind_match():
    case = {"action": "reorganize", "playlist": "treino", "kinds": ["bpm"], "question": False}
    assert score_intent(case, _intent(options=[_opt("genre"), _opt("bpm")]))[0]


def test_fails_on_wrong_action():
    ok, why = score_intent({"action": "chat"}, _intent())
    assert not ok and "action" in why


def test_fails_on_missing_kind():
    assert not score_intent({"action": "reorganize", "kinds": ["bpm"]}, _intent(options=[_opt("genre")]))[0]


def test_question_expectations():
    assert not score_intent({"action": "reorganize", "question": True}, _intent())[0]
    assert score_intent({"action": "reorganize", "question": True}, _intent(question="Qual playlist?"))[0]
    assert not score_intent({"action": "reorganize", "question": False}, _intent(question="?"))[0]


def test_playlist_mismatch_fails():
    assert not score_intent({"action": "reorganize", "playlist": "Relax"}, _intent())[0]
