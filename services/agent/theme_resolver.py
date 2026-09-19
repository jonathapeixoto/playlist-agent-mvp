"""Transforma o ThemePlan do LLM em faixas reais: biblioteca do usuário, depois busca validada no Spotify."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.models import ThemePlan, Track
from contracts.ports import SpotifyPort
from services.organizer.theme import pick_match


@dataclass
class ResolveResult:
    found: list[Track | None]
    candidates_tried: int
    candidates_valid: int


def _clean(text: str) -> str:
    return " ".join(text.replace('"', "").split())


class ThemeResolver:
    def __init__(
        self, spotify: SpotifyPort, max_playlists: int = 20, max_library_tracks: int = 2000, fallback_pages: int = 2
    ) -> None:
        self.spotify = spotify
        self.max_playlists = max_playlists
        self.max_library_tracks = max_library_tracks
        self.fallback_pages = fallback_pages
        self._library: list[Track] | None = None

    def library_tracks(self) -> list[Track]:
        if self._library is None:
            tracks: list[Track] = []
            for playlist in self.spotify.my_playlists()[: self.max_playlists]:
                tracks.extend(self.spotify.playlist_tracks(playlist.id))
                if len(tracks) >= self.max_library_tracks:
                    break
            self._library = tracks[: self.max_library_tracks]
        return self._library

    def invalidate(self) -> None:
        self._library = None

    def resolve(self, plan: ThemePlan) -> ResolveResult:
        library = self.library_tracks()
        used: set[str] = set()
        found: list[Track | None] = []
        tried = valid = 0
        for slot in plan.slots:
            match = pick_match(library, slot.keywords, used)
            if match is None:
                for candidate in slot.candidates:
                    tried += 1
                    query = f'track:"{_clean(candidate.title)}" artist:"{_clean(candidate.artist)}"'
                    match = pick_match(self.spotify.search_tracks(query), slot.keywords, used)
                    if match is not None:
                        valid += 1
                        break
            if match is None:
                for keyword in slot.keywords[:2]:
                    results = self.spotify.search_tracks(f'track:"{_clean(keyword)}"', pages=self.fallback_pages)
                    match = pick_match(results, slot.keywords, used)
                    if match is not None:
                        break
            found.append(match)
            if match is not None:
                used.add(match.id)
        return ResolveResult(found=found, candidates_tried=tried, candidates_valid=valid)
