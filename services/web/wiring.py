"""Monta os serviços reais. Único lugar que conhece todas as implementações concretas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from services.agent.agent import Agent
from services.agent.theme_resolver import ThemeResolver
from services.agent.trace import Tracer
from services.agent.undo import UndoStore
from services.enrichment.cache import EnrichmentCache
from services.enrichment.enricher import Enricher
from services.enrichment.genres import GenreResolver, LastFmClient
from services.enrichment.reccobeats import ReccoBeatsClient
from services.llm.api import ClaudeLLM
from services.llm.runner import ClaudeRunner
from services.spotify.auth import SpotifyAuth, TokenStore
from services.spotify.client import SpotifyClient
from services.web.settings import Settings


@dataclass
class AppDeps:
    agent: Any
    auth: Any
    settings: Settings
    trace_path: Path
    claude_ok: bool


def build_deps(settings: Settings, claude_ok: bool) -> AppDeps:
    data = Path(settings.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(timeout=20)
    auth = SpotifyAuth(settings.spotify_client_id, settings.redirect_uri, TokenStore(data / "token.json"), http)
    spotify = SpotifyClient(auth, http)
    cache = EnrichmentCache(data / "cache.sqlite")
    lastfm = LastFmClient(settings.lastfm_api_key, http) if settings.lastfm_api_key else None
    enricher = Enricher(ReccoBeatsClient(http), GenreResolver(spotify.artist_genres, lastfm, cache), cache)
    trace_path = data / "traces.jsonl"
    tracer = Tracer(trace_path)
    # Sem cwd: o runner usa uma pasta temporária fora do projeto (ver services/llm/runner.py).
    llm = ClaudeLLM(ClaudeRunner(model=settings.model), tracer)
    agent = Agent(llm, spotify, enricher, ThemeResolver(spotify), UndoStore(data / "undo.sqlite"), tracer)
    return AppDeps(agent=agent, auth=auth, settings=settings, trace_path=trace_path, claude_ok=claude_ok)
