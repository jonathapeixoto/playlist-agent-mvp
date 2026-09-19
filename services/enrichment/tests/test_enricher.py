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
