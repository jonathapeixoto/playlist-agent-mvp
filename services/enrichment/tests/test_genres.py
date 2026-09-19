import httpx
import pytest
import respx

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import Artist
from services.enrichment.cache import EnrichmentCache
from services.enrichment.genres import GenreResolver, LastFmClient, is_junk_tag


@pytest.mark.parametrize("tag", ["seen live", "90s", "1980s", "brazilian", "favorites"])
def test_junk_tags(tag):
    assert is_junk_tag(tag)


def test_real_genre_is_not_junk():
    assert not is_junk_tag("indie rock")


@respx.mock
def test_lastfm_filters_junk_low_count_and_keeps_top_3():
    respx.get(host="ws.audioscrobbler.com").mock(return_value=httpx.Response(200, json={"toptags": {"tag": [
        {"name": "Seen Live", "count": 100}, {"name": "MPB", "count": 90}, {"name": "Bossa Nova", "count": 60},
        {"name": "samba", "count": 40}, {"name": "jazz", "count": 30}, {"name": "rare", "count": 5},
    ]}}))
    assert LastFmClient("k", httpx.Client()).artist_tags("Caetano") == ["mpb", "bossa nova", "samba"]


@respx.mock
def test_lastfm_error_payload_returns_empty():
    respx.get(host="ws.audioscrobbler.com").mock(return_value=httpx.Response(200, json={"error": 6, "message": "not found"}))
    assert LastFmClient("k", httpx.Client()).artist_tags("???") == []


class FakeLastFm:
    def __init__(self, tags):
        self.tags = tags

    def artist_tags(self, name):
        return self.tags


def test_resolver_uses_spotify_first_and_caches(tmp_path):
    calls = []
    resolver = GenreResolver(lambda aid: calls.append(aid) or ["rock"], FakeLastFm(["x"]), EnrichmentCache(tmp_path / "c.sqlite"))
    artist = Artist(id="ar", name="Banda")
    assert resolver.genres_for(artist) == ["rock"]
    assert resolver.genres_for(artist) == ["rock"]
    assert calls == ["ar"]


def test_resolver_falls_back_to_lastfm_when_spotify_empty_or_fails(tmp_path):
    def failing(aid):
        raise ExternalServiceError("503")

    lastfm = FakeLastFm(["mpb"])
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    assert GenreResolver(lambda aid: [], lastfm, cache).genres_for(Artist(id="a1", name="A")) == ["mpb"]
    assert GenreResolver(failing, lastfm, cache).genres_for(Artist(id="a2", name="B")) == ["mpb"]


def test_resolver_propagates_auth_required(tmp_path):
    def needs_login(aid):
        raise AuthRequired("login")

    with pytest.raises(AuthRequired):
        GenreResolver(needs_login, None, EnrichmentCache(tmp_path / "c.sqlite")).genres_for(Artist(id="a", name="A"))


# F5: circuito por lote não pode travar o resto do lote nem poluir o cache com falha.

def test_circuit_breaker_skips_spotify_for_rest_of_batch_after_one_failure(tmp_path):
    calls = []

    def failing(aid):
        calls.append(aid)
        raise ExternalServiceError("503")

    resolver = GenreResolver(failing, FakeLastFm(["mpb"]), EnrichmentCache(tmp_path / "c.sqlite"))
    resolver.start_batch()
    assert resolver.genres_for(Artist(id="a1", name="A")) == ["mpb"]
    assert resolver.genres_for(Artist(id="a2", name="B")) == ["mpb"]
    assert calls == ["a1"]


def test_errored_lookup_is_not_cached_and_retries_in_next_batch(tmp_path):
    calls = []

    def failing(aid):
        calls.append(aid)
        raise ExternalServiceError("503")

    cache = EnrichmentCache(tmp_path / "c.sqlite")
    resolver = GenreResolver(failing, None, cache)
    resolver.start_batch()
    assert resolver.genres_for(Artist(id="a1", name="A")) == []
    assert cache.get_genres("a1") is None
    resolver.start_batch()
    assert resolver.genres_for(Artist(id="a1", name="A")) == []
    assert calls == ["a1", "a1"]


def test_genuine_empty_answer_is_still_cached(tmp_path):
    calls = []

    def empty(aid):
        calls.append(aid)
        return []

    cache = EnrichmentCache(tmp_path / "c.sqlite")
    resolver = GenreResolver(empty, FakeLastFm([]), cache)
    resolver.start_batch()
    assert resolver.genres_for(Artist(id="a1", name="A")) == []
    assert cache.get_genres("a1") == []
    resolver.start_batch()
    assert resolver.genres_for(Artist(id="a1", name="A")) == []
    assert calls == ["a1"]
