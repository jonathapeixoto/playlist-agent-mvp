"""Cliente fino da Web API do Spotify, já no formato de fev/2026 (/items, POST /me/playlists, busca limit 10)."""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol

import httpx

from contracts.errors import ExternalServiceError
from contracts.models import Artist, PlaylistSummary, Track

API = "https://api.spotify.com/v1"
SEARCH_PAGE = 10
WRITE_BATCH = 100


class SpotifyError(ExternalServiceError):
    pass


class _Auth(Protocol):
    def access_token(self) -> str: ...
    def refresh(self) -> Any: ...


def parse_track(obj: dict[str, Any]) -> Track:
    return Track(
        id=obj["id"],
        uri=obj["uri"],
        name=obj["name"],
        artists=[Artist(id=a.get("id") or "", name=a["name"]) for a in obj.get("artists", [])],
        album=(obj.get("album") or {}).get("name", ""),
        duration_ms=obj.get("duration_ms", 0),
    )


def _clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


class SpotifyClient:
    def __init__(
        self, auth: _Auth, http: httpx.Client, sleep: Callable[[float], None] = time.sleep, max_retries: int = 3
    ) -> None:
        self.auth = auth
        self.http = http
        self.sleep = sleep
        self.max_retries = max_retries
        self._me: str | None = None

    def _request(self, method: str, path_or_url: str, **kwargs: Any) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
        refreshed = False
        attempt = 0
        while True:
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            try:
                response = self.http.request(method, url, headers=headers, timeout=20, **kwargs)
            except httpx.HTTPError as err:
                raise SpotifyError(f"Sem conexão com o Spotify: {err}") from err
            if response.status_code == 401 and not refreshed:
                self.auth.refresh()
                refreshed = True
                continue
            retryable = response.status_code == 429 or (
                response.status_code >= 500 and method in ("GET", "PUT")
            )
            if retryable and attempt < self.max_retries:
                wait = float(response.headers.get("Retry-After", 2**attempt))
                self.sleep(min(wait, 30.0))
                attempt += 1
                continue
            break
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify {method} {url} falhou com {response.status_code}: {response.text[:200]}")
        return response

    def _pages(self, first: str) -> list[dict[str, Any]]:
        url: str | None = first
        items: list[dict[str, Any]] = []
        while url:
            data = self._request("GET", url).json()
            items.extend(data.get("items", []))
            url = data.get("next")
        return items

    def me_id(self) -> str:
        if self._me is None:
            self._me = self._request("GET", "/me").json()["id"]
        return self._me

    def my_playlists(self) -> list[PlaylistSummary]:
        me = self.me_id()
        out: list[PlaylistSummary] = []
        for p in self._pages("/me/playlists?limit=50"):
            if not p:
                continue
            owner = p["owner"]["id"]
            if owner != me and not p.get("collaborative"):
                continue
            total = (p.get("items") or p.get("tracks") or {}).get("total", 0)
            out.append(PlaylistSummary(id=p["id"], name=p["name"], total=total, owner_id=owner))
        return out

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        tracks: list[Track] = []
        for entry in self._pages(f"/playlists/{playlist_id}/items?limit=50&additional_types=track"):
            obj = entry.get("item") or entry.get("track")
            if not obj or entry.get("is_local") or obj.get("type", "track") != "track" or not obj.get("id"):
                continue
            tracks.append(parse_track(obj))
        return tracks

    def search_tracks(self, query: str, pages: int = 1) -> list[Track]:
        tracks: list[Track] = []
        for page in range(pages):
            params = {"q": query, "type": "track", "limit": SEARCH_PAGE, "offset": page * SEARCH_PAGE}
            items = self._request("GET", "/search", params=params).json().get("tracks", {}).get("items", [])
            if not items:
                break
            tracks.extend(parse_track(obj) for obj in items if obj and obj.get("id"))
        return tracks

    def artist_genres(self, artist_id: str) -> list[str]:
        return list(self._request("GET", f"/artists/{artist_id}").json().get("genres", []))

    def create_playlist(self, name: str, description: str) -> tuple[str, str]:
        body = {"name": _clean(name, 100), "description": _clean(description, 300), "public": False}
        data = self._request("POST", "/me/playlists", json=body).json()
        url = data.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/playlist/{data['id']}"
        return data["id"], url

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        self._request("PUT", f"/playlists/{playlist_id}/items", json={"uris": uris[:WRITE_BATCH]})
        rest = uris[WRITE_BATCH:]
        for start in range(0, len(rest), WRITE_BATCH):
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": rest[start : start + WRITE_BATCH]})
