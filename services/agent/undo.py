"""Snapshot da ordem original antes de reordenar uma playlist no lugar, para o botão Desfazer."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class UndoStore:
    def __init__(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id TEXT, uris TEXT, created_at REAL)"
            )

    def save(self, playlist_id: str, uris: list[str]) -> int:
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT INTO snapshots (playlist_id, uris, created_at) VALUES (?, ?, ?)",
                (playlist_id, json.dumps(uris), time.time()),
            )
            return int(cursor.lastrowid)

    def get(self, undo_id: int) -> tuple[str, list[str]] | None:
        with self.lock:
            row = self.db.execute("SELECT playlist_id, uris FROM snapshots WHERE id = ?", (undo_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def delete(self, undo_id: int) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM snapshots WHERE id = ?", (undo_id,))
