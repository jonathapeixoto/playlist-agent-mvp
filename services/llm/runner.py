"""Executa `claude -p` com saída estruturada e devolve o JSON validado pelo próprio Claude Code."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from contracts.errors import ExternalServiceError


class LLMError(ExternalServiceError):
    pass


@dataclass(frozen=True)
class RunResult:
    data: dict[str, Any]
    latency_s: float
    cost_usd: float


class ClaudeRunner:
    def __init__(
        self,
        model: str = "opus",
        binary: str | None = None,
        cwd: Path | str | None = None,
        timeout: float = 180.0,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.binary = binary
        self.cwd = Path(cwd) if cwd else Path(tempfile.gettempdir()) / "playlist-agent-llm"
        self.timeout = timeout
        self._run = run
        self.clock = clock

    def _exe(self) -> str:
        exe = self.binary or shutil.which("claude")
        if not exe:
            raise LLMError("Comando `claude` não encontrado no PATH. Instale o Claude Code e faça login (`claude`).")
        return exe

    def available(self) -> bool:
        try:
            proc = self._run([self._exe(), "--version"], capture_output=True, text=True, timeout=30)
        except (LLMError, OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult:
        cmd = [
            self._exe(), "-p",
            "--model", self.model,
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--system-prompt", system,
            "--tools", "",
        ]
        self.cwd.mkdir(parents=True, exist_ok=True)
        start = self.clock()
        try:
            proc = self._run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout, cwd=str(self.cwd),
            )
        except subprocess.TimeoutExpired as err:
            raise LLMError(f"O Claude Code não respondeu em {self.timeout:.0f}s.") from err
        except OSError as err:
            raise LLMError(f"Não foi possível executar o Claude Code: {err}") from err
        latency = self.clock() - start
        if proc.returncode != 0:
            raise LLMError(f"Claude Code saiu com código {proc.returncode}: {(proc.stderr or '')[:300]}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as err:
            raise LLMError("Saída do Claude Code não é JSON.") from err
        if payload.get("is_error") or "structured_output" not in payload:
            raise LLMError(f"Claude Code não devolveu resposta estruturada: {str(payload.get('result', ''))[:300]}")
        return RunResult(
            data=payload["structured_output"], latency_s=latency, cost_usd=float(payload.get("total_cost_usd") or 0.0)
        )
