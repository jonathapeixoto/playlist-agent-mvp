"""Padrão mínimo: 3 chamadas reais que provam que o motor escolhido serve para o app."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from contracts.models import ThemePlan
from services.llm.api import AgentLLM
from services.llm.runner import LLMError
from services.llm.scoring import score_intent

PLAYLISTS = ["Treino", "Churrasco"]
SIMPLE_CASE = {
    "message": "organiza minha playlist Treino por BPM",
    "action": "reorganize", "playlist": "Treino", "kinds": ["bpm"], "question": False,
}
OPEN_CASE = {
    "message": "arruma a Treino do jeito que você achar melhor",
    "action": "reorganize", "playlist": "Treino",
}
THEME = "músicas cujo título tem uma cor"
THEME_SLOTS = 3


@dataclass
class CompatCheck:
    name: str
    ok: bool
    detail: str
    latency_s: float


@dataclass
class CompatReport:
    checks: list[CompatCheck]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [asdict(c) for c in self.checks]}


def _theme_ok(plan: ThemePlan) -> tuple[bool, str]:
    if not plan.playlist_name.strip():
        return False, "veio sem nome de playlist"
    if len(plan.slots) < 2:
        return False, f"devolveu {len(plan.slots)} posições, esperava ao menos 2"
    if any(not slot.candidates for slot in plan.slots):
        return False, "alguma posição veio sem sugestões de música"
    return True, "ok"


def check(runner: Any) -> CompatReport:
    llm = AgentLLM(runner)
    checks: list[CompatCheck] = []
    for name, case in (
        ("Entender um pedido simples", SIMPLE_CASE),
        ("Propor opções para um pedido aberto", OPEN_CASE),
    ):
        start = time.monotonic()
        try:
            intent = llm.interpret(case["message"], [], PLAYLISTS)
            ok, detail = score_intent(case, intent)
            if ok and not intent.options:
                ok, detail = False, "não propôs nenhuma opção de organização"
        except LLMError as err:
            ok, detail = False, str(err)
        checks.append(CompatCheck(name, ok, detail, round(time.monotonic() - start, 2)))
    start = time.monotonic()
    try:
        ok, detail = _theme_ok(llm.plan_theme(THEME, THEME_SLOTS))
    except LLMError as err:
        ok, detail = False, str(err)
    checks.append(CompatCheck("Montar um tema pequeno", ok, detail, round(time.monotonic() - start, 2)))
    return CompatReport(checks)
