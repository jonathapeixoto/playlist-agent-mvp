from services.enrichment.cache import AudioFeatures, EnrichmentCache


def test_audio_hits_misses_and_uncached(tmp_path):
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: 1000.0)
    cache.put_audio({"a": AudioFeatures(tempo=120.0, energy=0.5)}, missing=["b"])
    got = cache.get_audio(["a", "b", "c"])
    assert got["a"].tempo == 120.0
    assert got["b"] is None
    assert "c" not in got


def test_negative_audio_entries_expire(tmp_path):
    clock = {"now": 0.0}
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: clock["now"])
    cache.put_audio({}, missing=["b"])
    clock["now"] = EnrichmentCache.NEGATIVE_TTL + 1
    assert "b" not in cache.get_audio(["b"])


def test_genres_round_trip_and_empty_expires(tmp_path):
    clock = {"now": 0.0}
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: clock["now"])
    assert cache.get_genres("ar") is None
    cache.put_genres("ar", ["rock"], "spotify")
    cache.put_genres("empty", [], "lastfm")
    assert cache.get_genres("ar") == ["rock"]
    assert cache.get_genres("empty") == []
    clock["now"] = EnrichmentCache.NEGATIVE_TTL + 1
    assert cache.get_genres("ar") == ["rock"]
    assert cache.get_genres("empty") is None


def test_old_negative_audio_entries_are_purged_once_on_upgrade(tmp_path):
    path = tmp_path / "c.sqlite"
    cache = EnrichmentCache(path)
    cache.put_audio({"hit": AudioFeatures(tempo=100.0)}, missing=["miss"])
    # Simula um cache criado antes da busca por versões alternativas.
    cache.db.execute("DELETE FROM meta")
    cache.db.commit()
    reopened = EnrichmentCache(path)
    assert reopened.get_audio(["hit", "miss"]) == {"hit": AudioFeatures(tempo=100.0)}
    # Negativos gravados depois da migração continuam valendo.
    reopened.put_audio({}, missing=["miss"])
    assert EnrichmentCache(path).get_audio(["miss"]) == {"miss": None}
