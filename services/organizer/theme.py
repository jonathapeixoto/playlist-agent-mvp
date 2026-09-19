"""Escolha determinística de faixa para um slot de tema."""

from __future__ import annotations

from contracts.models import Track
from services.organizer.text import matches_any


def pick_match(tracks: list[Track], keywords: list[str], exclude_ids: set[str]) -> Track | None:
    for track in tracks:
        if track.id not in exclude_ids and matches_any(track.name, keywords):
            return track
    return None
