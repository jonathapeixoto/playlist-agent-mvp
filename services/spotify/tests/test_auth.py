from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from contracts.errors import AuthRequired
from services.spotify.auth import (
    TOKEN_URL, SpotifyAuth, Token, TokenStore, authorize_url, code_challenge, make_verifier,
)


def test_code_challenge_matches_rfc7636_vector():
    assert code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifier_length_is_valid():
    assert 43 <= len(make_verifier()) <= 128


def test_authorize_url_has_pkce_params():
    query = parse_qs(urlparse(authorize_url("cid", "http://127.0.0.1:8000/callback", "st", "ch")).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["ch"]
    assert query["state"] == ["st"]
    assert "playlist-modify-private" in query["scope"][0]


def test_token_store_round_trip(tmp_path):
    store = TokenStore(tmp_path / "token.json")
    assert store.load() is None
    store.save(Token(access_token="a", refresh_token="r", expires_at=10))
    assert store.load().access_token == "a"
    store.clear()
    assert store.load() is None


def _auth(tmp_path, now=1000.0):
    clock = {"now": now}
    auth = SpotifyAuth(
        "cid", "http://127.0.0.1:8000/callback", TokenStore(tmp_path / "t.json"), httpx.Client(), clock=lambda: clock["now"]
    )
    return auth, clock


@respx.mock
def test_exchange_code_sends_verifier_and_saves(tmp_path):
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600})
    )
    auth, _ = _auth(tmp_path)
    token = auth.exchange_code("code123", "verif")
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["code_verifier"] == ["verif"]
    assert body["grant_type"] == ["authorization_code"]
    assert token.expires_at == 1000 + 3600
    assert auth.has_token()


@respx.mock
def test_access_token_refreshes_when_expired_and_keeps_old_refresh(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "a2", "expires_in": 3600}))
    auth, _ = _auth(tmp_path)
    auth.store.save(Token(access_token="a1", refresh_token="r1", expires_at=1010))
    assert auth.access_token() == "a2"
    assert auth.store.load().refresh_token == "r1"


@respx.mock
def test_refresh_failure_clears_store_and_requires_login(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    auth, _ = _auth(tmp_path)
    auth.store.save(Token(access_token="a1", refresh_token="r1", expires_at=0))
    with pytest.raises(AuthRequired):
        auth.access_token()
    assert not auth.has_token()


def test_access_token_without_login_requires_auth(tmp_path):
    auth, _ = _auth(tmp_path)
    with pytest.raises(AuthRequired):
        auth.access_token()
