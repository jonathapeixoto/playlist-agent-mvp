import json

import httpx
import pytest
import respx

from contracts.errors import AuthRequired
from services.spotify.client import SpotifyClient, SpotifyError

HOST = "api.spotify.com"


class FakeAuth:
    def __init__(self):
        self.token = "t1"
        self.refreshes = 0

    def access_token(self):
        return self.token

    def refresh(self):
        self.refreshes += 1
        self.token = "t2"


def _track(tid, name="Song", type_="track"):
    return {"id": tid, "uri": f"spotify:track:{tid}", "name": name, "type": type_,
            "artists": [{"id": "ar", "name": "Artist"}], "album": {"name": "Alb"}, "duration_ms": 1000}


@pytest.fixture
def client():
    sleeps = []
    c = SpotifyClient(FakeAuth(), httpx.Client(), sleep=sleeps.append)
    c.sleeps = sleeps
    return c


@respx.mock
def test_my_playlists_paginates_and_keeps_only_owned_or_collaborative(client):
    respx.get(host=HOST, path="/v1/me").mock(return_value=httpx.Response(200, json={"id": "me"}))
    respx.get(host=HOST, path="/v1/me/playlists").mock(side_effect=[
        httpx.Response(200, json={"items": [
            {"id": "p1", "name": "Minha", "owner": {"id": "me"}, "items": {"total": 3}},
            {"id": "p2", "name": "Alheia", "owner": {"id": "x"}, "collaborative": False, "items": {"total": 1}},
        ], "next": f"https://{HOST}/v1/me/playlists?offset=50&limit=50"}),
        httpx.Response(200, json={"items": [
            {"id": "p3", "name": "Colab", "owner": {"id": "x"}, "collaborative": True, "tracks": {"total": 2}},
            None,
        ], "next": None}),
    ])
    playlists = client.my_playlists()
    assert [(p.id, p.total) for p in playlists] == [("p1", 3), ("p3", 2)]


@respx.mock
def test_playlist_tracks_reads_item_key_and_skips_local_and_episodes(client):
    respx.get(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"items": [
        {"item": _track("a", "Primeiro Andar")},
        {"track": _track("b")},
        {"item": _track("c"), "is_local": True},
        {"item": _track("d", type_="episode")},
        {"item": None},
    ], "next": None}))
    tracks = client.playlist_tracks("p1")
    assert [t.id for t in tracks] == ["a", "b"]
    assert tracks[0].name == "Primeiro Andar"
    assert tracks[0].artists[0].name == "Artist"
    assert tracks[0].album == "Alb"


@respx.mock
def test_search_uses_limit_10_and_offset_pages(client):
    route = respx.get(host=HOST, path="/v1/search").mock(side_effect=[
        httpx.Response(200, json={"tracks": {"items": [_track("a")]}}),
        httpx.Response(200, json={"tracks": {"items": [_track("b")]}}),
    ])
    tracks = client.search_tracks('track:"Andar"', pages=2)
    assert [t.id for t in tracks] == ["a", "b"]
    params = [dict(c.request.url.params) for c in route.calls]
    assert params[0]["limit"] == "10" and params[0]["offset"] == "0"
    assert params[1]["offset"] == "10"


@respx.mock
def test_search_stops_when_page_is_empty(client):
    route = respx.get(host=HOST, path="/v1/search").mock(return_value=httpx.Response(200, json={"tracks": {"items": []}}))
    assert client.search_tracks("x", pages=3) == []
    assert route.call_count == 1


@respx.mock
def test_retries_429_with_retry_after(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"genres": ["rock"]}),
    ])
    assert client.artist_genres("ar") == ["rock"]
    assert client.sleeps == [2.0]


@respx.mock
def test_401_refreshes_token_once(client):
    route = respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(401), httpx.Response(200, json={"genres": []}),
    ])
    client.artist_genres("ar")
    assert client.auth.refreshes == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer t2"


@respx.mock
def test_second_401_after_refresh_raises_auth_required(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(401), httpx.Response(401),
    ])
    with pytest.raises(AuthRequired):
        client.artist_genres("ar")
    assert client.auth.refreshes == 1


@respx.mock
def test_error_after_retries_raises_spotify_error(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(return_value=httpx.Response(503))
    with pytest.raises(SpotifyError):
        client.artist_genres("ar")
    assert len(client.sleeps) == 3


@respx.mock
def test_retry_after_http_date_falls_back_to_exponential_default(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "Mon, 01 Jan 2030 00:00:00 GMT"}),
        httpx.Response(200, json={"genres": ["rock"]}),
    ])
    assert client.artist_genres("ar") == ["rock"]
    assert client.sleeps == [1.0]


@respx.mock
def test_429_retry_after_over_30s_raises_without_sleeping(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(SpotifyError):
        client.artist_genres("ar")
    assert client.sleeps == []


@respx.mock
def test_post_5xx_is_not_retried_and_raises_immediately(client):
    route = respx.post(host=HOST, path="/v1/me/playlists").mock(return_value=httpx.Response(503))
    with pytest.raises(SpotifyError):
        client.create_playlist("x", "y")
    assert route.call_count == 1
    assert client.sleeps == []


@respx.mock
def test_post_429_is_still_retried(client):
    route = respx.post(host=HOST, path="/v1/me/playlists").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(201, json={"id": "new", "external_urls": {"spotify": "https://open.spotify.com/playlist/new"}}),
    ])
    pid, _ = client.create_playlist("x", "y")
    assert pid == "new"
    assert route.call_count == 2
    assert client.sleeps == [1.0]


@respx.mock
def test_create_playlist_truncates_and_strips_newlines(client):
    route = respx.post(host=HOST, path="/v1/me/playlists").mock(return_value=httpx.Response(
        201, json={"id": "new", "external_urls": {"spotify": "https://open.spotify.com/playlist/new"}}
    ))
    pid, url = client.create_playlist("x" * 150, "linha1\nlinha2" + "y" * 400)
    body = json.loads(route.calls.last.request.content)
    assert (pid, url) == ("new", "https://open.spotify.com/playlist/new")
    assert len(body["name"]) == 100
    assert "\n" not in body["description"] and len(body["description"]) == 300
    assert body["public"] is False


@respx.mock
def test_replace_items_puts_first_100_then_posts_rest(client):
    put = respx.put(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"snapshot_id": "s"}))
    post = respx.post(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(201, json={"snapshot_id": "s"}))
    uris = [f"spotify:track:{i}" for i in range(250)]
    client.replace_items("p1", uris)
    assert json.loads(put.calls.last.request.content)["uris"] == uris[:100]
    assert [len(json.loads(c.request.content)["uris"]) for c in post.calls] == [100, 50]


@respx.mock
def test_replace_items_with_empty_list_clears_playlist(client):
    put = respx.put(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"snapshot_id": "s"}))
    client.replace_items("p1", [])
    assert json.loads(put.calls.last.request.content)["uris"] == []
