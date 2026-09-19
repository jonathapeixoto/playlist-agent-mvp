"""Trace JSONL de cada interação e o resumo mostrado em /api/stats."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


class Tracer:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()

    def __call__(self, event: str, **fields: Any) -> None:
        line = json.dumps({"ts": self.clock(), "event": event, **fields}, ensure_ascii=False)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summarize(path: Path) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def of(kind: str) -> list[dict[str, Any]]:
        return [e for e in events if e.get("event") == kind]

    llm, plans, themes = of("llm"), of("plan"), of("theme")
    tried = sum(e.get("candidates_tried", 0) for e in themes)
    valid = sum(e.get("candidates_valid", 0) for e in themes)
    return {
        "events": len(events),
        "llm_calls": len(llm),
        "llm_avg_latency_s": _avg([e["latency_s"] for e in llm if "latency_s" in e]),
        "llm_total_cost_usd": round(sum(e.get("cost_usd", 0.0) for e in llm), 4),
        "plans": len(plans),
        "avg_bpm_coverage": _avg([e["bpm_coverage"] for e in plans if "bpm_coverage" in e]),
        "avg_genre_coverage": _avg([e["genre_coverage"] for e in plans if "genre_coverage" in e]),
        "theme_candidates_tried": tried,
        "theme_candidates_valid": valid,
        "theme_validation_rate": round(valid / tried, 3) if tried else None,
        "applies": len(of("apply")),
    }
