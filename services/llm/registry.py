"""Atalhos de provedores. Só dados: quem fala o formato da OpenAI cabe no mesmo adaptador."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    base_url: str
    model: str
    needs_key: bool
    help_url: str


PRESETS: tuple[Preset, ...] = (
    Preset("claude_code", "Claude Code (nesta máquina)", "", "opus", False, "https://claude.com/claude-code"),
    Preset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
           "gemini-2.5-flash", True, "https://aistudio.google.com/apikey"),
    Preset("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", True,
           "https://console.groq.com/keys"),
    Preset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "google/gemini-2.5-flash", True,
           "https://openrouter.ai/keys"),
    Preset("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", True,
           "https://console.mistral.ai/api-keys"),
    Preset("ollama", "Ollama (nesta máquina)", "http://127.0.0.1:11434/v1", "llama3.1:8b", False,
           "https://ollama.com/download"),
    Preset("lmstudio", "LM Studio (nesta máquina)", "http://127.0.0.1:1234/v1", "local-model", False,
           "https://lmstudio.ai"),
    Preset("custom", "Personalizado", "", "", True, ""),
)


def find(key: str) -> Preset | None:
    return next((p for p in PRESETS if p.key == key), None)
