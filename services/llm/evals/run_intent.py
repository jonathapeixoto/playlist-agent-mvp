"""Eval de interpretação contra o Claude Code real. Custa tokens (~US$ 0,03 por caso).

Uso: uv run python -m services.llm.evals.run_intent
Sai com código 1 se o acerto ficar abaixo de THRESHOLD.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.llm.api import ClaudeLLM
from services.llm.evals.scoring import score_intent
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.runner import LLMError

THRESHOLD = 0.9
CASES = Path(__file__).parent / "intent_cases.jsonl"
PLAYLISTS = ["Treino", "Churrasco", "Estudo", "Rock Nacional", "Festa 2025", "Relax"]


def _run_case(llm: ClaudeLLM, case: dict) -> dict:
    try:
        intent = llm.interpret(case["message"], [], PLAYLISTS)
        ok, why = score_intent(case, intent)
        got = intent.model_dump(mode="json")
    except LLMError as err:
        ok, why, got = False, f"erro: {err}", None
    return {"id": case["id"], "message": case["message"], "ok": ok, "why": why, "got": got}


def main() -> int:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    llm = ClaudeLLM(ClaudeRunner())
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda c: _run_case(llm, c), cases))
    score = sum(r["ok"] for r in rows) / len(rows)
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'} #{r['id']:>2} {r['message'][:60]:<60} {r['why']}")
    print(f"\nAcerto: {score:.0%} (limiar {THRESHOLD:.0%})")
    out = Path("data/evals") / f"intent-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"score": score, "threshold": THRESHOLD, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    return 0 if score >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
