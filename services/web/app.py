"""API HTTP local. Uma sessão de conversa por processo (app pessoal, um usuário)."""

from __future__ import annotations

import html
import secrets
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import AgentReply, ApplyMode, LLMConfig, ProviderKind
from services.agent.agent import AgentError, Session
from services.agent.trace import summarize
from services.llm.compat import check as default_compat_check
from services.llm.factory import build_runner, describe
from services.llm.registry import PRESETS, find
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


class LLMConfigIn(BaseModel):
    preset: str = "custom"
    model: str
    base_url: str = ""
    api_key: str = ""


def create_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title="Playlist Agent")
    # Protege contra DNS rebinding: só aceita Host apontando para este processo local.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
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
        try:
            deps.auth.exchange_code(code, verifier)
        except (AuthRequired, ExternalServiceError) as err:
            reason = html.escape(str(err) or "erro desconhecido")
            return HTMLResponse(f"<p>Login não concluído ({reason}). <a href='/login'>Tentar de novo</a></p>", status_code=400)
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

    def _current_config() -> LLMConfig:
        saved = deps.llm_store.load() if deps.llm_store else None
        return saved or LLMConfig(provider=ProviderKind.CLAUDE_CODE, model=deps.settings.model)

    def _config_from(body: LLMConfigIn) -> LLMConfig:
        preset = find(body.preset)
        provider = ProviderKind.CLAUDE_CODE if body.preset == "claude_code" else ProviderKind.OPENAI
        base_url = body.base_url or (preset.base_url if preset else "")
        current = _current_config()
        keeps_key = current.preset == body.preset and current.base_url == base_url
        # Campo vazio mantém a chave salva, mas só quando o destino é o mesmo.
        api_key = body.api_key or (current.api_key if keeps_key else "")
        return LLMConfig(provider=provider, model=body.model, base_url=base_url, api_key=api_key, preset=body.preset)

    @app.get("/api/llm")
    def llm_config() -> dict:
        return {
            "current": _current_config().to_public_dict(),
            "description": getattr(deps.llm, "description", ""),
            "presets": [asdict(p) for p in PRESETS],
        }

    @app.post("/api/llm/test")
    def llm_test(body: LLMConfigIn) -> dict:
        runner = build_runner(_config_from(body), deps.http)
        return (deps.compat_check or default_compat_check)(runner).to_dict()

    @app.post("/api/llm")
    def llm_save(body: LLMConfigIn):
        config = _config_from(body)
        runner = build_runner(config, deps.http)
        report = (deps.compat_check or default_compat_check)(runner)
        if not report.ok:
            return JSONResponse(
                status_code=400,
                content={"detail": "O motor não passou no teste. Nada foi salvo.", "report": report.to_dict()},
            )
        deps.llm_store.save(config)
        deps.llm.set_runner(runner, describe(config))
        return {"ok": True, "description": describe(config), "report": report.to_dict()}

    return app
