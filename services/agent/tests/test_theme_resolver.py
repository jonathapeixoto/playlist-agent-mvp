from contracts.models import Artist, PlaylistSummary, SongCandidate, ThemePlan, ThemeSlot, Track
from services.agent.theme_resolver import ThemeResolver


def _t(tid, name):
    return Track(id=tid, uri=f"spotify:track:{tid}", name=name, artists=[Artist(id="a", name="A")])


class FakeSpotify:
    def __init__(self, library=None, search=None):
        self.library = library or []
        self.search = search or {}
        self.queries = []
        self.playlist_calls = 0

    def my_playlists(self):
        self.playlist_calls += 1
        return [PlaylistSummary(id="lib", name="Minha", total=len(self.library), owner_id="me")]

    def playlist_tracks(self, pid):
        return list(self.library)

    def search_tracks(self, query, pages=1):
        self.queries.append((query, pages))
        return list(self.search.get(query, []))


def _plan(*slots):
    return ThemePlan(playlist_name="Prédio", description="d", slots=list(slots))


def _slot(label, keywords, candidates=()):
    return ThemeSlot(label=label, keywords=keywords, candidates=[SongCandidate(title=t, artist=a) for t, a in candidates])


def test_library_match_wins_without_search():
    spotify = FakeSpotify(library=[_t("lib1", "Primeiro Andar")])
    result = ThemeResolver(spotify).resolve(_plan(_slot("1º", ["Primeiro Andar"], [("Primeiro Andar", "X")])))
    assert [t.id for t in result.found] == ["lib1"]
    assert spotify.queries == []
    assert (result.candidates_tried, result.candidates_valid) == (0, 0)


def test_candidate_must_really_contain_keyword():
    spotify = FakeSpotify(search={
        'track:"Andar Errado" artist:"X"': [_t("bad", "Andar Errado")],
        'track:"1º Andar" artist:"Y"': [_t("good", "1º Andar (Ao Vivo)")],
    })
    slot = _slot("1º", ["Primeiro Andar"], [("Andar Errado", "X"), ("1º Andar", "Y")])
    result = ThemeResolver(spotify).resolve(_plan(slot))
    assert result.found[0].id == "good"
    assert (result.candidates_tried, result.candidates_valid) == (2, 1)


def test_falls_back_to_keyword_search_then_gives_up():
    spotify = FakeSpotify(search={'track:"Térreo"': [_t("t", "Térreo")]})
    plan = _plan(_slot("Térreo", ["Térreo"]), _slot("Cobertura", ["Cobertura", "Penthouse"]))
    result = ThemeResolver(spotify).resolve(plan)
    assert result.found[0].id == "t"
    assert result.found[1] is None
    assert ('track:"Térreo"', 2) in spotify.queries
    assert ('track:"Penthouse"', 2) in spotify.queries


def test_same_track_is_not_reused_across_slots():
    spotify = FakeSpotify(library=[_t("x", "Segunda-Feira")])
    plan = _plan(_slot("Seg A", ["Segunda"]), _slot("Seg B", ["Segunda"]))
    result = ThemeResolver(spotify).resolve(plan)
    assert result.found[0].id == "x" and result.found[1] is None


def test_quotes_are_stripped_from_queries():
    spotify = FakeSpotify()
    ThemeResolver(spotify).resolve(_plan(_slot("x", ["Andar"], [('Say "Andar"', 'The "Band"')])))
    assert spotify.queries[0][0] == 'track:"Say Andar" artist:"The Band"'


def test_library_is_cached_until_invalidated():
    spotify = FakeSpotify()
    resolver = ThemeResolver(spotify)
    resolver.library_tracks()
    resolver.library_tracks()
    assert spotify.playlist_calls == 1
    resolver.invalidate()
    resolver.library_tracks()
    assert spotify.playlist_calls == 2
