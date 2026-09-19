"""Cache SQLite de BPM e gêneros. Resultado negativo também é cacheado, mas expira em 7 dias."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel


class AudioFeatures(BaseModel):
    tempo: float | None = None
    energy: float | None = None


class EnrichmentCache:
    NEGATIVE_TTL = 7 * 24 * 3600

    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.clock = clock
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS audio "
                "(track_id TEXT PRIMARY KEY, tempo REAL, energy REAL, found INTEGER, fetched_at REAL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS genres (artist_id TEXT PRIMARY KEY, genres TEXT, source TEXT, fetched_at REAL)"
            )

    def _fresh(self, found: bool, fetched_at: float) -> bool:
        return found or self.clock() - fetched_at <= self.NEGATIVE_TTL

    def get_audio(self, ids: list[str]) -> dict[str, AudioFeatures | None]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self.lock:
            rows = self.db.execute(
                f"SELECT track_id, tempo, energy, found, fetched_at FROM audio WHERE track_id IN ({marks})", ids
            ).fetchall()
        out: dict[str, AudioFeatures | None] = {}
        for track_id, tempo, energy, found, fetched_at in rows:
            if self._fresh(bool(found), fetched_at):
                out[track_id] = AudioFeatures(tempo=tempo, energy=energy) if found else None
        return out

    def put_audio(self, found: dict[str, AudioFeatures], missing: list[str]) -> None:
        now = self.clock()
        rows = [(tid, f.tempo, f.energy, 1, now) for tid, f in found.items()]
        rows += [(tid, None, None, 0, now) for tid in missing]
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO audio VALUES (?, ?, ?, ?, ?)", rows)

    def get_genres(self, artist_id: str) -> list[str] | None:
        with self.lock:
            row = self.db.execute("SELECT genres, fetched_at FROM genres WHERE artist_id = ?", (artist_id,)).fetchone()
        if row is None:
            return None
        genres = json.loads(row[0])
        return genres if self._fresh(bool(genres), row[1]) else None

    def put_genres(self, artist_id: str, genres: list[str], source: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO genres VALUES (?, ?, ?, ?)", (artist_id, json.dumps(genres), source, self.clock())
            )
