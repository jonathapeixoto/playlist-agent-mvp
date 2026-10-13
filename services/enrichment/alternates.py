"""Acha outras versões da mesma gravação no Spotify (single x álbum x coletânea).

A ReccoBeats guarda BPM por ID do Spotify, e a mesma música costuma ter vários IDs.
Quando o ID da playlist não tem BPM, uma versão equivalente muitas vezes tem.
"""

from __future__ import annotations

from typing import Callable

from contracts.models import Track
from services.organizer.text import normalize_tokens

# Remasters e relançamentos mudam a duração em milissegundos; ao vivo e edits mudam em segundos.
DURATION_TOLERANCE_MS = 2000


def same_recording(original: Track, candidate: Track, tolerance_ms: int = DURATION_TOLERANCE_MS) -> bool:
    if candidate.id == original.id or not original.artists or not candidate.artists:
        return False
    # ID vazio (arquivo local, coletânea sem artista) não prova que é o mesmo artista.
    artist_id = original.artists[0].id
    if not artist_id or candidate.artists[0].id != artist_id:
        return False
    if normalize_tokens(candidate.name) != normalize_tokens(original.name):
        return False
    return abs(candidate.duration_ms - original.duration_ms) <= tolerance_ms


def _clean(text: str) -> str:
    return " ".join(text.replace('"', "").split())


class AlternateFinder:
    def __init__(self, search: Callable[[str], list[Track]]) -> None:
        self.search = search

    def find(self, track: Track) -> list[str]:
        """IDs de outras versões da mesma gravação, na ordem da busca do Spotify."""
        if not track.artists:
            return []
        query = f'track:"{_clean(track.name)}" artist:"{_clean(track.artists[0].name)}"'
        return [c.id for c in self.search(query) if same_recording(track, c)]
