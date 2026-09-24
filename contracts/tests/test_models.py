import pytest
from pydantic import ValidationError

from contracts.models import (
    AgentReply,
    ConversationState,
    Intent,
    IntentAction,
    PlannedPlaylist,
    PlaylistPlan,
    StrategyChoice,
    StrategyKind,
    ThemePlan,
    ThemeSlot,
)


def _strategy(label: str = "BPM") -> StrategyChoice:
    return StrategyChoice(kind=StrategyKind.BPM, label=label, description="d")


def test_plan_can_replace_only_with_single_playlist_and_source():
    one = PlannedPlaylist(name="x", description="", tracks=[])
    assert PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one]).can_replace_in_place
    assert not PlaylistPlan(strategy=_strategy(), source_playlist_id=None, playlists=[one]).can_replace_in_place
    assert not PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one, one]).can_replace_in_place


def test_can_replace_is_serialized_for_frontend():
    one = PlannedPlaylist(name="x", description="", tracks=[])
    dumped = PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one]).model_dump()
    assert dumped["can_replace_in_place"] is True


def test_intent_keeps_at_most_three_options():
    intent = Intent(action=IntentAction.REORGANIZE, reply="ok", options=[_strategy(str(i)) for i in range(5)])
    assert [o.label for o in intent.options] == ["0", "1", "2"]


def test_theme_plan_requires_slots():
    with pytest.raises(ValidationError):
        ThemePlan(playlist_name="x", description="", slots=[])


def test_theme_slot_requires_non_blank_keyword():
    with pytest.raises(ValidationError):
        ThemeSlot(label="x", keywords=["  "])


def test_agent_reply_round_trips_json():
    reply = AgentReply(message="oi", state=ConversationState.PROPOSE, options=[_strategy()])
    assert AgentReply.model_validate_json(reply.model_dump_json()) == reply


def test_llm_config_public_dict_hides_the_key():
    from contracts.models import LLMConfig, ProviderKind

    config = LLMConfig(provider=ProviderKind.OPENAI, model="gemini-2.5-flash",
                       base_url="https://exemplo/v1", api_key="segredo", preset="gemini")
    public = config.to_public_dict()
    assert public == {
        "provider": "openai_compatible", "model": "gemini-2.5-flash",
        "base_url": "https://exemplo/v1", "preset": "gemini", "has_key": True,
    }
    assert "segredo" not in str(public)


def test_llm_config_without_key_reports_has_key_false():
    from contracts.models import LLMConfig, ProviderKind

    assert LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus").to_public_dict()["has_key"] is False
