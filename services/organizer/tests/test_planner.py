import pytest

from contracts.models import (
    Artist, BpmMode, EnrichedTrack, GenreLevel, PlaylistSummary, StrategyChoice, StrategyKind, ThemePlan, ThemeSlot, Track,
)
from services.organizer.planner import coverage, plan_reorganize, plan_theme

SOURCE = PlaylistSummary(id="src", name="Treino", total=4, owner_id="me")


def _e(tid: str, tempo: float | None = None, genres: list[str] | None = None) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, tempo=tempo, genres=genres or [])


def test_bpm_plan_single_playlist_with_diff():
    strategy = StrategyChoice(kind=StrategyKind.BPM, label="BPM crescente", description="d", bpm_mode=BpmMode.ASC)
    plan = plan_reorganize(strategy, SOURCE, [_e("b", 120), _e("a", 100)])
    assert plan.source_playlist_id == "src"
    assert plan.can_replace_in_place
    [playlist] = plan.playlists
    assert playlist.name == "Treino · BPM crescente"
    assert [t.track.id for t in playlist.tracks] == ["a", "b"]
    assert playlist.diff.previous_positions == [1, 0]


def test_genre_split_creates_one_playlist_per_group_and_cannot_replace():
    strategy = StrategyChoice(
        kind=StrategyKind.GENRE, label="Por gênero", description="d", genre_level=GenreLevel.FAMILY, genre_split=True
    )
    tracks = [_e(str(i), genres=["rock"]) for i in range(3)] + [_e(str(i + 3), genres=["pagode"]) for i in range(3)]
    plan = plan_reorganize(strategy, SOURCE, tracks)
    assert [p.name for p in plan.playlists] == ["Treino · Pagode e samba", "Treino · Rock"]
    assert plan.source_playlist_id is None
    assert not plan.can_replace_in_place


def test_genre_split_with_single_group_still_cannot_replace():
    strategy = StrategyChoice(
        kind=StrategyKind.GENRE, label="Por gênero", description="d", genre_level=GenreLevel.FAMILY, genre_split=True
    )
    plan = plan_reorganize(strategy, SOURCE, [_e("a", genres=["rock"]), _e("b", genres=["pagode"])])
    assert len(plan.playlists) == 1
    assert not plan.can_replace_in_place


def test_genre_group_keeps_single_playlist_in_blocks():
    strategy = StrategyChoice(kind=StrategyKind.GENRE, label="Blocos", description="d", genre_level=GenreLevel.FAMILY)
    plan = plan_reorganize(strategy, SOURCE, [_e("r1", genres=["rock"]), _e("p1", genres=["pop"]), _e("r2", genres=["rock"])])
    assert [t.track.id for t in plan.playlists[0].tracks] == ["r1", "r2", "p1"]


def test_theme_strategy_is_rejected_by_plan_reorganize():
    with pytest.raises(ValueError):
        plan_reorganize(StrategyChoice(kind=StrategyKind.THEME, label="t", description="d"), SOURCE, [])


def test_plan_theme_reports_missing_slots():
    theme = ThemePlan(
        playlist_name="Prédio",
        description="Sobe!",
        slots=[ThemeSlot(label="Térreo", keywords=["Térreo"]), ThemeSlot(label="1º", keywords=["Primeiro Andar"])],
    )
    strategy = StrategyChoice(kind=StrategyKind.THEME, label="Prédio", description="d", theme="prédio")
    plan = plan_theme(strategy, theme, [None, _e("x", 100)])
    [playlist] = plan.playlists
    assert playlist.name == "Prédio"
    assert playlist.missing_slots == ["Térreo"]
    assert [t.track.id for t in playlist.tracks] == ["x"]
    assert plan.source_playlist_id is None


def test_coverage():
    assert coverage([_e("a", 100, ["rock"]), _e("b")]) == (0.5, 0.5)
    assert coverage([]) == (0.0, 0.0)
