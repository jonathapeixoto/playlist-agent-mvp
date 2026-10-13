"""Configuração do motor em data/llm.json. Arquivo ilegível vale como 'sem configuração'."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from contracts.models import LLMConfig


class LLMConfigStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> LLMConfig | None:
        if not self.path.exists():
            return None
        try:
            return LLMConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError, OSError):
            return None

    def save(self, config: LLMConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(config.model_dump_json(), encoding="utf-8")
