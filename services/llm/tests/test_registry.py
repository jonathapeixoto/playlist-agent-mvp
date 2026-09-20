import pytest

from services.llm.registry import PRESETS, find


def test_every_preset_has_label_and_model_except_custom():
    for preset in PRESETS:
        assert preset.key and preset.label
        if preset.key != "custom":
            assert preset.model
            assert preset.base_url or preset.key == "claude_code"


@pytest.mark.parametrize("key", ["gemini", "groq", "openrouter", "mistral"])
def test_remote_presets_need_a_key_and_point_to_where_to_get_it(key):
    preset = find(key)
    assert preset.needs_key and preset.help_url.startswith("https://")
    assert preset.base_url.startswith("https://")


@pytest.mark.parametrize("key", ["ollama", "lmstudio"])
def test_local_presets_need_no_key(key):
    preset = find(key)
    assert not preset.needs_key
    assert preset.base_url.startswith("http://127.0.0.1")


def test_claude_code_preset_has_no_base_url_and_no_key():
    preset = find("claude_code")
    assert preset.base_url == "" and not preset.needs_key


def test_find_unknown_key():
    assert find("inventado") is None
