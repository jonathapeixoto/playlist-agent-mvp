"""OAuth Authorization Code com PKCE. Token salvo em arquivo local (data/token.json, fora do git)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from contracts.errors import AuthRequired

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
]


class Token(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float

    def expired(self, now: float, margin: float = 60) -> bool:
        return now >= self.expires_at - margin


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        return Token.model_validate(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(token.model_dump_json(), encoding="utf-8")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def make_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": " ".join(SCOPES),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


class SpotifyAuth:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        store: TokenStore,
        http: httpx.Client,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.store = store
        self.http = http
        self.clock = clock

    def _post(self, form: dict[str, str], previous_refresh: str | None) -> Token:
        response = self.http.post(TOKEN_URL, data=form)
        if response.status_code != 200:
            self.store.clear()
            raise AuthRequired(f"Spotify recusou o token ({response.status_code}). Faça login de novo.")
        data = response.json()
        token = Token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or previous_refresh or "",
            expires_at=self.clock() + float(data["expires_in"]),
        )
        self.store.save(token)
        return token

    def exchange_code(self, code: str, verifier: str) -> Token:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        return self._post(form, previous_refresh=None)

    def refresh(self) -> Token:
        current = self.store.load()
        if current is None or not current.refresh_token:
            raise AuthRequired("Faça login no Spotify.")
        form = {"grant_type": "refresh_token", "refresh_token": current.refresh_token, "client_id": self.client_id}
        return self._post(form, previous_refresh=current.refresh_token)

    def access_token(self) -> str:
        token = self.store.load()
        if token is None:
            raise AuthRequired("Faça login no Spotify.")
        if token.expired(self.clock()):
            token = self.refresh()
        return token.access_token

    def has_token(self) -> bool:
        return self.store.load() is not None
