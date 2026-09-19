from contracts.models import PlaylistSummary
from services.agent.lookup import find_playlist


def _p(pid, name):
    return PlaylistSummary(id=pid, name=name, total=1, owner_id="me")


PLAYLISTS = [_p("1", "Treino Pesado"), _p("2", "Churrasco"), _p("3", "Estudo"), _p("4", "Estudo Noturno"), _p("5", "🔥🔥")]


def test_exact_match_ignores_case_and_accents():
    assert find_playlist("churrasco", PLAYLISTS).id == "2"
    assert find_playlist("ESTUDO", PLAYLISTS).id == "3"


def test_unique_partial_match():
    assert find_playlist("treino", PLAYLISTS).id == "1"


def test_ambiguous_partial_returns_none():
    assert find_playlist("estud", PLAYLISTS) is None


def test_blank_name_and_emoji_only_playlist_never_match():
    assert find_playlist("", PLAYLISTS) is None
    assert find_playlist("festa", PLAYLISTS) is None
