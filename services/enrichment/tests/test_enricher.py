from contracts.models import Artist, Track
from services.enrichment.cache import AudioFeatures, EnrichmentCache
from services.enrichment.enricher import Enricher
from services.enrichment.reccobeats import FeaturesResult


def _t(tid, artist="ar"):
    return Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id=artist, name=artist)])


class FakeRecco:
    def __init__(self):
        self.asked = []

    def audio_features(self, ids):
        self.asked.append(list(ids))
        return FeaturesResult(found={"a": AudioFeatures(tempo=120, energy=0.7)}, failed=["c"])


class FakeGenres:
    def start_batch(self):
        pass

    def genres_for(self, artist):
        return ["rock"] if artist.id == "ar" else []


def test_enrich_merges_features_and_genres_and_caches_misses(tmp_path):
    recco = FakeRecco()
    enricher = Enricher(recco, FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite"))
    out = enricher.enrich([_t("a"), _t("b", "other"), _t("c"), _t("a")])
    assert [(e.track.id, e.tempo, e.genres) for e in out] == [
        ("a", 120, ["rock"]), ("b", None, []), ("c", None, ["rock"]), ("a", 120, ["rock"]),
    ]
    assert recco.asked == [["a", "b", "c"]]
    # "b" virou negativo no cache; "c" falhou e NÃO foi cacheado, então é pedido de novo.
    enricher.enrich([_t("a"), _t("b"), _t("c")])
    assert recco.asked[-1] == ["c"]


def test_track_without_artists_gets_no_genres(tmp_path):
    track = Track(id="z", uri="spotify:track:z", name="z", artists=[])
    out = Enricher(FakeRecco(), FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite")).enrich([track])
    assert out[0].genres == []


class ScriptedRecco:
    """Responde BPM só para os IDs em `known`; registra cada chamada."""

    def __init__(self, known, failing=()):
        self.known = known
        self.failing = set(failing)
        self.asked = []

    def audio_features(self, ids):
        self.asked.append(list(ids))
        found = {i: AudioFeatures(tempo=self.known[i]) for i in ids if i in self.known}
        return FeaturesResult(found=found, failed=[i for i in ids if i in self.failing])


class FakeAlternates:
    def __init__(self, mapping, raise_on=()):
        self.mapping = mapping
        self.raise_on = set(raise_on)
        self.looked_up = []

    def find(self, track):
        self.looked_up.append(track.id)
        if track.id in self.raise_on:
            from contracts.errors import ExternalServiceError

            raise ExternalServiceError("busca fora do ar")
        return self.mapping.get(track.id, [])


def test_bpm_recovered_from_alternate_version_and_cached_under_original_id(tmp_path):
    recco = ScriptedRecco({"album-version": 173.0})
    alternates = FakeAlternates({"single": ["album-version"]})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    enricher = Enricher(recco, FakeGenres(), cache, alternates)
    [out] = enricher.enrich([_t("single")])
    assert out.tempo == 173.0
    assert recco.asked == [["single"], ["album-version"]]
    assert cache.get_audio(["single"])["single"].tempo == 173.0
    # Segunda vez vem do cache: nem ReccoBeats nem busca.
    enricher.enrich([_t("single")])
    assert len(recco.asked) == 2 and alternates.looked_up == ["single"]


def test_first_alternate_in_search_order_wins(tmp_path):
    recco = ScriptedRecco({"alt1": 100.0, "alt2": 150.0})
    enricher = Enricher(recco, FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite"), FakeAlternates({"s": ["alt1", "alt2"]}))
    assert enricher.enrich([_t("s")])[0].tempo == 100.0


def test_no_alternate_found_is_cached_as_missing(tmp_path):
    recco = ScriptedRecco({})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    enricher = Enricher(recco, FakeGenres(), cache, FakeAlternates({}))
    assert enricher.enrich([_t("ghost")])[0].tempo is None
    assert cache.get_audio(["ghost"]) == {"ghost": None}
    assert recco.asked == [["ghost"]]


def test_search_failure_stops_lookups_and_does_not_cache(tmp_path, monkeypatch):
    # Um worker torna a ordem determinística: depois da falha em "x", "y" nem é buscado.
    monkeypatch.setattr("services.enrichment.enricher.ALTERNATE_WORKERS", 1)
    recco = ScriptedRecco({})
    alternates = FakeAlternates({}, raise_on={"x"})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    enricher = Enricher(recco, FakeGenres(), cache, alternates)
    enricher.enrich([_t("x"), _t("y")])
    assert alternates.looked_up == ["x"]
    assert cache.get_audio(["x", "y"]) == {}


def test_alternate_failing_at_reccobeats_is_not_cached(tmp_path):
    recco = ScriptedRecco({}, failing={"alt"})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    Enricher(recco, FakeGenres(), cache, FakeAlternates({"s": ["alt"]})).enrich([_t("s")])
    assert cache.get_audio(["s"]) == {}


def test_alternate_lookups_are_capped_per_batch(tmp_path, monkeypatch):
    monkeypatch.setattr("services.enrichment.enricher.MAX_ALTERNATE_LOOKUPS", 2)
    alternates = FakeAlternates({})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    Enricher(ScriptedRecco({}), FakeGenres(), cache, alternates).enrich([_t("a"), _t("b"), _t("c")])
    assert alternates.looked_up == ["a", "b"]
    assert set(cache.get_audio(["a", "b", "c"])) == {"a", "b"}


def test_without_alternates_behaves_as_before(tmp_path):
    recco = ScriptedRecco({})
    assert Enricher(recco, FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite")).enrich([_t("s")])[0].tempo is None
    assert recco.asked == [["s"]]


def test_found_alternate_wins_even_if_a_sibling_alternate_failed(tmp_path):
    recco = ScriptedRecco({"good": 128.0}, failing={"broken"})
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    out = Enricher(recco, FakeGenres(), cache, FakeAlternates({"s": ["broken", "good"]})).enrich([_t("s")])
    assert out[0].tempo == 128.0
    assert cache.get_audio(["s"])["s"].tempo == 128.0


def test_direct_hits_are_cached_before_alternate_lookup_can_fail(tmp_path):
    from contracts.errors import AuthRequired

    class ExpiringAlternates:
        def find(self, track):
            raise AuthRequired("login expirou")

    cache = EnrichmentCache(tmp_path / "c.sqlite")
    enricher = Enricher(ScriptedRecco({"hit": 100.0}), FakeGenres(), cache, ExpiringAlternates())
    try:
        enricher.enrich([_t("hit"), _t("miss")])
    except AuthRequired:
        pass
    else:
        raise AssertionError("AuthRequired deveria subir para o app pedir login")
    assert cache.get_audio(["hit", "miss"]) == {"hit": AudioFeatures(tempo=100.0)}


def test_alternate_lookups_run_in_parallel(tmp_path):
    import threading

    barrier = threading.Barrier(2, timeout=2)

    class MeetingAlternates:
        def find(self, track):
            barrier.wait()  # só passa se duas buscas estiverem rodando ao mesmo tempo
            return []

    out = Enricher(ScriptedRecco({}), FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite"), MeetingAlternates()).enrich(
        [_t("a"), _t("b")]
    )
    assert [e.tempo for e in out] == [None, None]


def test_expired_login_trips_the_breaker_and_reaches_the_app(tmp_path):
    import threading

    from contracts.errors import AuthRequired

    first_call = threading.Event()
    calls = []

    class ExpiredOnce:
        def find(self, track):
            calls.append(track.id)
            if not first_call.is_set():
                first_call.set()
                raise AuthRequired("login expirou")
            return []

    enricher = Enricher(ScriptedRecco({}), FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite"), ExpiredOnce())
    tracks = [_t(f"t{i}") for i in range(20)]
    try:
        enricher.enrich(tracks)
    except AuthRequired:
        pass
    else:
        raise AssertionError("AuthRequired deveria subir para o app pedir login")
    # Só as buscas que já estavam em andamento terminam; nenhuma nova começa depois da falha.
    assert len(calls) <= 4
