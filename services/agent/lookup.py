"""Acha a playlist citada pelo usuário: igualdade normalizada primeiro, depois trecho único."""

from __future__ import annotations

from contracts.models import PlaylistSummary
from services.organizer.text import normalize_tokens


def _key(text: str) -> str:
    return " ".join(normalize_tokens(text))


def find_playlist(name: str, playlists: list[PlaylistSummary]) -> PlaylistSummary | None:
    wanted = _key(name)
    if not wanted:
        return None
    keyed = [(p, _key(p.name)) for p in playlists]
    keyed = [(p, k) for p, k in keyed if k]
    exact = [p for p, k in keyed if k == wanted]
    if exact:
        return exact[0]
    partial = [p for p, k in keyed if wanted in k or k in wanted]
    return partial[0] if len(partial) == 1 else None
