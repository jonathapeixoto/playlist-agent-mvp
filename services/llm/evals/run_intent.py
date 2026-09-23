"""Eval de interpretação contra o Claude Code real. Custa tokens (~US$ 0,03 por caso).

Uso: uv run python -m services.llm.evals.run_intent
Sai com código 1 se o acerto ficar abaixo de THRESHOLD.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contracts.models import LLMConfig, ProviderKind
from services.llm.api import AgentLLM
from services.llm.config_store import LLMConfigStore
from services.llm.factory import build_runner, describe
from services.llm.registry import find
from services.llm.scoring import score_intent
from services.llm.runner import LLMError

THRESHOLD = 0.9
CASES = Path(__file__).parent / "intent_cases.jsonl"
PLAYLISTS = ["Treino", "Churrasco", "Estudo", "Rock Nacional", "Festa 2025", "Relax"]


def _config_from_env_or_file() -> LLMConfig:
    """Override por ambiente: PLAYLIST_AGENT_PRESET, PLAYLIST_AGENT_MODEL, PLAYLIST_AGENT_API_KEY."""
    preset_key = os.environ.get("PLAYLIST_AGENT_PRESET")
    if preset_key:
        preset = find(preset_key)
        if preset is None:
            raise SystemExit(f"Preset desconhecido: {preset_key}")
        provider = ProviderKind.CLAUDE_CODE if preset.key == "claude_code" else ProviderKind.OPENAI
        return LLMConfig(
            provider=provider,
            model=os.environ.get("PLAYLIST_AGENT_MODEL") or preset.model,
            base_url=preset.base_url,
            api_key=os.environ.get("PLAYLIST_AGENT_API_KEY", ""),
            preset=preset.key,
        )
    saved = LLMConfigStore(Path("data/llm.json")).load()
    return saved or LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus")


def _run_case(llm: AgentLLM, case: dict) -> dict:
    try:
        intent = llm.interpret(case["message"], [], PLAYLISTS)
        ok, why = score_intent(case, intent)
        got = intent.model_dump(mode="json")
    except LLMError as err:
        ok, why, got = False, f"erro: {err}", None
    return {"id": case["id"], "message": case["message"], "ok": ok, "why": why, "got": got}


def main() -> int:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    config = _config_from_env_or_file()
    motor = describe(config)
    llm = AgentLLM(build_runner(config))
    print(f"Motor: {motor}\n")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda c: _run_case(llm, c), cases))
    score = sum(r["ok"] for r in rows) / len(rows)
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'} #{r['id']:>2} {r['message'][:60]:<60} {r['why']}")
    print(f"\nAcerto: {score:.0%} (limiar {THRESHOLD:.0%}) no motor {motor}")
    out = Path("data/evals") / f"intent-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"score": score, "threshold": THRESHOLD, "motor": motor, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    return 0 if score >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
