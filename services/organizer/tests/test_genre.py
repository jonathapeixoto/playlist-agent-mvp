import pytest

from contracts.models import Artist, EnrichedTrack, GenreLevel, Track
from services.organizer.genre import OTHERS, UNKNOWN, genre_family, group_by_genre, merge_small_groups, primary_label


def _e(tid: str, genres: list[str]) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, genres=genres)


@pytest.mark.parametrize(
    ("genre", "family"),
    [
        ("funk carioca", "Funk brasileiro"),
        ("brazilian funk", "Funk brasileiro"),
        ("sertanejo universitario", "Sertanejo"),
        ("pagode", "Pagode e samba"),
        ("forró", "Forró e piseiro"),
        ("MPB", "MPB"),
        ("musica popular brasileira", "MPB"),
        ("trap brasileiro", "Trap e hip hop"),
        ("hip-hop", "Trap e hip hop"),
        ("heavy metal", "Metal"),
        ("pop punk", "Punk e hardcore"),
        ("indie rock", "Rock"),
        ("deep house", "Eletrônica"),
        ("funk", "Funk e disco"),
        ("reggaeton", "Latina"),
        ("indie pop", "Indie"),
        ("dance pop", "Pop"),
        ("xyzcore", None),
    ],
)
def test_genre_family(genre, family):
    assert genre_family(genre) == family


def test_primary_label_levels():
    t = _e("a", ["indie rock", "rock"])
    assert primary_label(t, GenreLevel.FAMILY) == "Rock"
    assert primary_label(t, GenreLevel.SUBGENRE) == "indie rock"
    assert primary_label(_e("b", []), GenreLevel.FAMILY) == UNKNOWN
    assert primary_label(_e("c", ["xyzcore"]), GenreLevel.FAMILY) == OTHERS


def test_group_by_genre_orders_by_size_and_puts_tail_last():
    tracks = [
        _e("1", ["pagode"]), _e("2", []), _e("3", ["sertanejo"]),
        _e("4", ["sertanejo"]), _e("5", ["xyz"]), _e("6", ["pagode"]), _e("7", ["sertanejo"]),
    ]
    groups = group_by_genre(tracks, GenreLevel.FAMILY)
    assert [label for label, _ in groups] == ["Sertanejo", "Pagode e samba", OTHERS, UNKNOWN]
    assert [t.track.id for t in groups[0][1]] == ["3", "4", "7"]


def test_merge_small_groups_folds_into_others():
    groups = [
        ("Rock", [_e("1", []), _e("2", []), _e("3", [])]),
        ("Jazz e blues", [_e("4", [])]),
        (UNKNOWN, [_e("5", [])]),
    ]
    merged = merge_small_groups(groups, min_size=3)
    assert [label for label, _ in merged] == ["Rock", OTHERS, UNKNOWN]
    assert [t.track.id for t in merged[1][1]] == ["4"]
