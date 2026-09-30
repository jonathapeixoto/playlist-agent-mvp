"""Tipos compartilhados pelos adaptadores de motor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.errors import ExternalServiceError


class LLMError(ExternalServiceError):
    pass


@dataclass(frozen=True)
class RunResult:
    data: dict[str, Any]
    latency_s: float
    cost_usd: float
