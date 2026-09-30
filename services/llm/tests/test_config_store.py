from contracts.models import LLMConfig, ProviderKind
from services.llm.config_store import LLMConfigStore


def _config():
    return LLMConfig(provider=ProviderKind.OPENAI, model="llama-3.3-70b-versatile",
                     base_url="https://api.groq.com/openai/v1", api_key="k-123", preset="groq")


def test_round_trip(tmp_path):
    store = LLMConfigStore(tmp_path / "llm.json")
    assert store.load() is None
    store.save(_config())
    loaded = store.load()
    assert loaded == _config()
    assert loaded.api_key == "k-123"


def test_corrupted_file_means_no_configuration(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text("isso não é json", encoding="utf-8")
    assert LLMConfigStore(path).load() is None


def test_file_with_unknown_provider_means_no_configuration(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text('{"provider": "telepatia", "model": "x"}', encoding="utf-8")
    assert LLMConfigStore(path).load() is None


def test_save_creates_the_directory(tmp_path):
    store = LLMConfigStore(tmp_path / "sub" / "llm.json")
    store.save(_config())
    assert store.load().preset == "groq"
