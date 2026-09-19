"""Configuração lida do .env. Só o client ID do Spotify é obrigatório."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    lastfm_api_key: str | None = None
    redirect_uri: str = "http://127.0.0.1:8000/callback"
    data_dir: Path = Path("data")
    model: str = "opus"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_dotenv()
            env = os.environ
        client_id = (env.get("SPOTIFY_CLIENT_ID") or "").strip()
        if not client_id:
            raise SystemExit("Defina SPOTIFY_CLIENT_ID no arquivo .env (veja .env.example e o README).")
        lastfm = (env.get("LASTFM_API_KEY") or "").strip() or None
        return cls(spotify_client_id=client_id, lastfm_api_key=lastfm)
