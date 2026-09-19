"""Cliente da ReccoBeats: audio features (BPM, energia) a partir de IDs do Spotify. Sem autenticação."""

from __future__ import annotations

import time
from typing import Callable

import httpx
from pydantic import BaseModel

from services.enrichment.cache import AudioFeatures

RECCO_API = "https://api.reccobeats.com/v1"
BATCH = 40


class FeaturesResult(BaseModel):
    found: dict[str, AudioFeatures]
    failed: list[str]


class ReccoBeatsClient:
    def __init__(self, http: httpx.Client, sleep: Callable[[float], None] = time.sleep, max_retries: int = 3) -> None:
        self.http = http
        self.sleep = sleep
        self.max_retries = max_retries

    def _fetch(self, chunk: list[str]) -> list[dict] | None:
        for attempt in range(self.max_retries + 1):
            try:
                response = self.http.get(f"{RECCO_API}/audio-features", params={"ids": ",".join(chunk)}, timeout=20)
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code == 200:
                return response.json().get("content", [])
            if attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After") if response is not None else None
                self.sleep(min(float(retry_after or 2**attempt), 30.0))
        return None

    def audio_features(self, spotify_ids: list[str]) -> FeaturesResult:
        found: dict[str, AudioFeatures] = {}
        failed: list[str] = []
        for start in range(0, len(spotify_ids), BATCH):
            chunk = spotify_ids[start : start + BATCH]
            content = self._fetch(chunk)
            if content is None:
                failed.extend(chunk)
                continue
            for item in content:
                spotify_id = str(item.get("href", "")).rstrip("/").rsplit("/", 1)[-1]
                if spotify_id in chunk:
                    found[spotify_id] = AudioFeatures(tempo=item.get("tempo"), energy=item.get("energy"))
        return FeaturesResult(found=found, failed=failed)
