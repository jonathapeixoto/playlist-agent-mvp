import pytest

from contracts.models import Artist, Track
from services.enrichment.alternates import AlternateFinder, same_recording


def _t(tid, name="Voices In My Head", artist_id="fir", duration=200_000):
    return Track(id=tid, uri=f"spotify:track:{tid}", name=name, artists=[Artist(id=artist_id, name="Falling In Reverse")],
                 duration_ms=duration)


ORIGINAL = _t("single")


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (_t("album"), True),
        (_t("album", name="voices in my head"), True),
        (_t("album", duration=201_900), True),
        (_t("single"), False),
        (_t("live", duration=215_000), False),
        (_t("other", name="Voices In My Head (Acoustic)"), False),
        (_t("cover", artist_id="someone-else"), False),
        (_t("no-id", artist_id=""), False),
    ],
)
def test_same_recording(candidate, expected):
    assert same_recording(ORIGINAL, candidate) is expected


def test_track_without_artists_never_matches():
    lonely = Track(id="x", uri="spotify:track:x", name="Voices In My Head", artists=[], duration_ms=200_000)
    assert not same_recording(lonely, _t("album"))
    assert AlternateFinder(lambda q: [_t("album")]).find(lonely) == []


def test_finder_builds_quoted_query_and_filters_results():
    queries = []

    def search(query):
        queries.append(query)
        return [_t("single"), _t("album"), _t("live", duration=260_000)]

    original = _t("single", name='Say "Hi"')
    finder = AlternateFinder(search)
    assert finder.find(original) == []
    assert queries == ['track:"Say Hi" artist:"Falling In Reverse"']
    assert AlternateFinder(lambda q: [_t("single"), _t("album")]).find(ORIGINAL) == ["album"]


def test_two_tracks_with_empty_artist_ids_are_not_the_same_artist():
    assert not same_recording(_t("a", artist_id=""), _t("b", artist_id=""))
