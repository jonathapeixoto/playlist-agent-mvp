"""Eval de temas: o LLM sugere músicas e medimos quantas existem de verdade no Spotify.

Precisa do login feito pelo app (data/token.json). Custa tokens do Claude Code e chamadas ao Spotify.
Uso: uv run python -m services.agent.evals.run_theme
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from contracts.errors import AuthRequired, ExternalServiceError
from services.web.settings import Settings
from services.web.wiring import build_deps

THRESHOLD = 0.7
MAX_SLOTS = 8
THEMES = [
    "andares de um prédio, do térreo à cobertura",
    "dias da semana, de segunda a domingo",
    "cores",
    "números de um a dez",
    "estações do ano",
]


def main() -> int:
    agent = build_deps(Settings.from_env(), claude_ok=True).agent
    rows = []
    for theme in THEMES:
        try:
            plan = agent.llm.plan_theme(theme, MAX_SLOTS)
            resolved = agent.resolver.resolve(plan)
            rows.append({
                "theme": theme, "slots": len(plan.slots),
                "slots_found": sum(t is not None for t in resolved.found),
                "tried": resolved.candidates_tried, "valid": resolved.candidates_valid,
            })
        except AuthRequired:
            print("Faça login pelo app (`uv run playlist-agent`) antes de rodar este eval.")
            return 2
        except ExternalServiceError as err:
            rows.append({"theme": theme, "error": str(err), "slots": 0, "slots_found": 0, "tried": 0, "valid": 0})
    tried = sum(r["tried"] for r in rows)
    valid = sum(r["valid"] for r in rows)
    rate = valid / tried if tried else 0.0
    for r in rows:
        print(f"{r['theme'][:40]:<40} slots {r['slots_found']}/{r['slots']}  candidatas válidas {r['valid']}/{r['tried']}"
              + (f"  ERRO {r['error']}" if "error" in r else ""))
    print(f"\nTaxa de validação das sugestões: {rate:.0%} (limiar {THRESHOLD:.0%})")
    out = Path("data/evals") / f"theme-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rate": rate, "threshold": THRESHOLD, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    return 0 if rate >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
