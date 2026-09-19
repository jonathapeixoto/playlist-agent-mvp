"""Ponto de entrada: `uv run playlist-agent`."""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from services.llm.runner import ClaudeRunner
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import build_deps

URL = "http://127.0.0.1:8000"


def main() -> None:
    settings = Settings.from_env()
    claude_ok = ClaudeRunner(model=settings.model).available()
    if not claude_ok:
        print("Aviso: Claude Code não encontrado ou sem login. Rode `claude`, faça login e reinicie.")
    app = create_app(build_deps(settings, claude_ok=claude_ok))
    print(f"Playlist Agent rodando em {URL} (Ctrl+C para parar)")
    threading.Timer(1.5, webbrowser.open, args=[URL]).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
