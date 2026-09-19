"""API do agente para o resto do app: interpretar mensagens e planejar temas."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from contracts.models import Intent, ThemePlan
from services.llm.structured import call_structured

PROMPTS_DIR = Path(__file__).parent / "prompts"
HISTORY_TURNS = 10


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_interpret_prompt(message: str, history: list[tuple[str, str]], playlist_names: list[str]) -> str:
    names = "\n".join(f"- {n}" for n in playlist_names) or "(nenhuma)"
    turns = "\n".join(f"{role}: {text}" for role, text in history[-HISTORY_TURNS:]) or "(início da conversa)"
    return f"Playlists do usuário:\n{names}\n\nConversa até agora:\n{turns}\n\nNova mensagem do usuário:\n{message}"


def render_theme_prompt(theme: str, max_slots: int) -> str:
    return f"Tema: {theme}\nNúmero máximo de slots: {max_slots}"


def _no_trace(event: str, **fields: Any) -> None:
    return None


class ClaudeLLM:
    def __init__(self, runner: Any, tracer: Callable[..., None] | None = None) -> None:
        self.runner = runner
        self.tracer = tracer or _no_trace

    def _call(self, kind: str, prompt_name: str, prompt: str, model_cls: type) -> Any:
        model, run = call_structured(self.runner, load_prompt(prompt_name), prompt, model_cls)
        self.tracer("llm", kind=kind, latency_s=round(run.latency_s, 2), cost_usd=run.cost_usd)
        return model

    def interpret(self, message: str, history: list[tuple[str, str]], playlist_names: list[str]) -> Intent:
        return self._call("interpret", "interpret", render_interpret_prompt(message, history, playlist_names), Intent)

    def plan_theme(self, theme: str, max_slots: int) -> ThemePlan:
        plan: ThemePlan = self._call("theme", "theme", render_theme_prompt(theme, max_slots), ThemePlan)
        return plan.model_copy(update={"slots": plan.slots[:max_slots]})
