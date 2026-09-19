"""API HTTP local. Uma sessão de conversa por processo (app pessoal, um usuário)."""

from __future__ import annotations

import html
import secrets
import threading
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import AgentReply, ApplyMode
from services.agent.agent import AgentError, Session
from services.agent.trace import summarize
from services.spotify.auth import authorize_url, code_challenge, make_verifier
from services.web.wiring import AppDeps

STATIC = Path(__file__).parent / "static"


class ChatIn(BaseModel):
    text: str


class ChooseIn(BaseModel):
    index: int


class ApplyIn(BaseModel):
    mode: ApplyMode


class UndoIn(BaseModel):
    undo_id: int


def create_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title="Playlist Agent")
    app.state.session = Session()
    pending_logins: dict[str, str] = {}
    lock = threading.Lock()

    def _error(status: int):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc) or "Erro inesperado."})
        return handler

    app.add_exception_handler(AgentError, _error(400))
    app.add_exception_handler(AuthRequired, _error(401))
    app.add_exception_handler(ExternalServiceError, _error(502))
    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    def login() -> RedirectResponse:
        verifier = make_verifier()
        state = secrets.token_urlsafe(16)
        pending_logins[state] = verifier
        url = authorize_url(deps.settings.spotify_client_id, deps.settings.redirect_uri, state, code_challenge(verifier))
        return RedirectResponse(url)

    @app.get("/callback")
    def callback(code: str | None = None, state: str | None = Query(None), error: str | None = None):
        verifier = pending_logins.pop(state or "", None)
        if error or not code or verifier is None:
            reason = html.escape(error or "estado inválido")
            return HTMLResponse(f"<p>Login não concluído ({reason}). <a href='/login'>Tentar de novo</a></p>", status_code=400)
        deps.auth.exchange_code(code, verifier)
        return RedirectResponse("/")

    @app.get("/api/status")
    def status() -> dict:
        return {"logged_in": deps.auth.has_token(), "claude_ok": deps.claude_ok}

    @app.post("/api/chat")
    def chat(body: ChatIn) -> AgentReply:
        with lock:
            return deps.agent.handle_message(app.state.session, body.text)

    @app.post("/api/choose")
    def choose(body: ChooseIn) -> AgentReply:
        with lock:
            return deps.agent.choose(app.state.session, body.index)

    @app.post("/api/apply")
    def apply(body: ApplyIn) -> AgentReply:
        with lock:
            return deps.agent.apply(app.state.session, body.mode)

    @app.post("/api/undo")
    def undo(body: UndoIn) -> AgentReply:
        with lock:
            return deps.agent.undo(app.state.session, body.undo_id)

    @app.post("/api/reset")
    def reset() -> dict:
        with lock:
            app.state.session = Session()
        return {"ok": True}

    @app.get("/api/stats")
    def stats() -> dict:
        return summarize(deps.trace_path)

    return app
