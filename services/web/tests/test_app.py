from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import AgentReply, ConversationState
from services.agent.agent import AgentError, Session
from services.spotify.auth import AUTHORIZE_URL, code_challenge
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class FakeAgent:
    def handle_message(self, s, text):
        if text == "erro":
            raise AgentError("Escolha uma das opções propostas.")
        if text == "login":
            raise AuthRequired("Faça login no Spotify.")
        if text == "fora":
            raise ExternalServiceError("Spotify fora do ar")
        return AgentReply(message=f"eco {text}", state=ConversationState.UNDERSTAND)

    def choose(self, s, index):
        return AgentReply(message=f"opção {index}", state=ConversationState.PREVIEW)

    def apply(self, s, mode):
        return AgentReply(message=f"aplicado {mode.value}", state=ConversationState.APPLIED)

    def undo(self, s, undo_id):
        return AgentReply(message=f"desfeito {undo_id}", state=ConversationState.APPLIED)


class FakeAuth:
    def __init__(self):
        self.exchanged = []

    def has_token(self):
        return bool(self.exchanged)

    def exchange_code(self, code, verifier):
        self.exchanged.append((code, verifier))


@pytest.fixture
def ctx(tmp_path):
    deps = AppDeps(
        agent=FakeAgent(), auth=FakeAuth(), settings=Settings(spotify_client_id="cid", data_dir=tmp_path),
        trace_path=tmp_path / "t.jsonl", claude_ok=True,
    )
    return TestClient(create_app(deps)), deps


def test_status(ctx):
    client, _ = ctx
    assert client.get("/api/status").json() == {"logged_in": False, "claude_ok": True}


def test_chat_choose_apply_undo(ctx):
    client, _ = ctx
    assert client.post("/api/chat", json={"text": "oi"}).json()["message"] == "eco oi"
    assert client.post("/api/choose", json={"index": 1}).json()["state"] == "preview"
    assert client.post("/api/apply", json={"mode": "replace"}).json()["message"] == "aplicado replace"
    assert client.post("/api/undo", json={"undo_id": 7}).json()["message"] == "desfeito 7"


def test_invalid_apply_mode_is_422(ctx):
    client, _ = ctx
    assert client.post("/api/apply", json={"mode": "apagar"}).status_code == 422


@pytest.mark.parametrize(("text", "status"), [("erro", 400), ("login", 401), ("fora", 502)])
def test_errors_map_to_status_and_portuguese_detail(ctx, text, status):
    client, _ = ctx
    response = client.post("/api/chat", json={"text": text})
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]


def test_login_then_callback_exchanges_matching_verifier(ctx):
    client, deps = ctx
    response = client.get("/login", follow_redirects=False)
    location = response.headers["location"]
    assert location.startswith(AUTHORIZE_URL)
    query = parse_qs(urlparse(location).query)
    callback = client.get("/callback", params={"code": "c1", "state": query["state"][0]}, follow_redirects=False)
    assert callback.status_code in (302, 307) and callback.headers["location"] == "/"
    code, verifier = deps.auth.exchanged[0]
    assert code == "c1" and code_challenge(verifier) == query["code_challenge"][0]
    # state é de uso único
    again = client.get("/callback", params={"code": "c1", "state": query["state"][0]}, follow_redirects=False)
    assert again.status_code == 400


def test_callback_with_error_or_unknown_state_is_400(ctx):
    client, _ = ctx
    assert client.get("/callback", params={"error": "access_denied"}).status_code == 400
    assert client.get("/callback", params={"code": "c", "state": "inventado"}).status_code == 400


def test_stats_and_reset(ctx):
    client, _ = ctx
    assert client.get("/api/stats").json()["events"] == 0
    assert client.post("/api/reset").json() == {"ok": True}
