"""Gênero por artista: Spotify primeiro, tags do Last.fm quando o Spotify vem vazio ou falha."""

from __future__ import annotations

import re
from typing import Callable

import httpx

from contracts.errors import ExternalServiceError
from contracts.models import Artist
from services.enrichment.cache import EnrichmentCache

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
MIN_TAG_COUNT = 10
_JUNK = {
    "seen live", "favorites", "favourites", "favorite", "albums i own", "love", "awesome", "beautiful",
    "male vocalists", "female vocalists", "spotify", "all", "brazilian", "brazil", "brasil", "american",
    "british", "usa", "uk", "under 2000 listeners",
}
_DECADE = re.compile(r"^(\d0s|\d{4}s)$")


def is_junk_tag(tag: str) -> bool:
    normalized = tag.lower().strip()
    return normalized in _JUNK or bool(_DECADE.match(normalized))


class LastFmClient:
    def __init__(self, api_key: str, http: httpx.Client) -> None:
        self.api_key = api_key
        self.http = http

    def artist_tags(self, artist_name: str) -> list[str]:
        params = {
            "method": "artist.gettoptags", "artist": artist_name, "api_key": self.api_key,
            "format": "json", "autocorrect": 1,
        }
        try:
            response = self.http.get(LASTFM_API, params=params, timeout=15)
        except httpx.HTTPError as err:
            raise ExternalServiceError(f"Last.fm indisponível: {err}") from err
        if response.status_code != 200:
            raise ExternalServiceError(f"Last.fm respondeu {response.status_code}")
        tags = response.json().get("toptags", {}).get("tag", [])
        names = [
            t["name"].lower().strip()
            for t in tags
            if int(t.get("count", 0)) >= MIN_TAG_COUNT and not is_junk_tag(t["name"])
        ]
        return names[:3]


class GenreResolver:
    """Circuito por lote: uma fonte que falha uma vez fica marcada 'down' até o próximo start_batch(),
    para não fazer o lote inteiro esperar timeout de novo em cada artista."""

    def __init__(
        self, spotify_genres: Callable[[str], list[str]], lastfm: LastFmClient | None, cache: EnrichmentCache
    ) -> None:
        self.spotify_genres = spotify_genres
        self.lastfm = lastfm
        self.cache = cache
        self._spotify_down = False
        self._lastfm_down = False

    def start_batch(self) -> None:
        self._spotify_down = False
        self._lastfm_down = False

    def genres_for(self, artist: Artist) -> list[str]:
        cached = self.cache.get_genres(artist.id)
        if cached is not None:
            return cached
        genres: list[str] = []
        source = "spotify"
        blocked = False
        if artist.id:
            if self._spotify_down:
                blocked = True
            else:
                try:
                    genres = self.spotify_genres(artist.id)
                except ExternalServiceError:
                    self._spotify_down = True
                    blocked = True
        if not genres and self.lastfm is not None:
            source = "lastfm"
            if self._lastfm_down:
                blocked = True
            else:
                try:
                    genres = self.lastfm.artist_tags(artist.name)
                except ExternalServiceError:
                    self._lastfm_down = True
                    blocked = True
        if not genres and blocked:
            # Vazio por causa de falha/circuito aberto, não por resposta genuína: não cacheia,
            # para o próximo lote poder tentar de novo em vez de ficar preso a um "sem gênero" falso.
            return genres
        self.cache.put_genres(artist.id, genres, source)
        return genres
