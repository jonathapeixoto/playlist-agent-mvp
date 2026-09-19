from contracts.models import Artist, BpmMode, EnrichedTrack, Track
from services.organizer.bpm import effective_tempo, order_by_bpm


def _e(tid: str, tempo: float | None) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, tempo=tempo)


def _ids(tracks):
    return [t.track.id for t in tracks]


def test_asc_and_desc():
    tracks = [_e("b", 120), _e("a", 100), _e("c", 140)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["a", "b", "c"]
    assert _ids(order_by_bpm(tracks, BpmMode.DESC)) == ["c", "b", "a"]


def test_arc_rises_to_peak_then_falls():
    tracks = [_e(str(t), t) for t in (140, 100, 130, 110, 120)]
    assert _ids(order_by_bpm(tracks, BpmMode.ARC)) == ["100", "120", "140", "130", "110"]


def test_unknown_tempo_goes_last_in_original_order():
    tracks = [_e("x", None), _e("a", 100), _e("y", 0), _e("b", 90)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["b", "a", "x", "y"]


def test_normalize_doubles_slow_tempos():
    assert effective_tempo(70, normalize=True) == 140
    assert effective_tempo(70, normalize=False) == 70
    tracks = [_e("slow", 70), _e("mid", 120)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC, normalize=True)) == ["mid", "slow"]


def test_ties_keep_original_order():
    tracks = [_e("first", 100), _e("second", 100)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["first", "second"]
    assert _ids(order_by_bpm(tracks, BpmMode.DESC)) == ["first", "second"]
