from contracts.models import Artist, Track
from services.organizer.theme import pick_match


def _t(tid: str, name: str) -> Track:
    return Track(id=tid, uri=f"spotify:track:{tid}", name=name, artists=[Artist(id="a", name="A")])


def test_pick_match_skips_used_and_non_matching():
    a, b, c = _t("a", "Primeiro Andar"), _t("b", "1º Andar"), _t("c", "Outra")
    assert pick_match([c, a, b], ["Primeiro Andar"], exclude_ids={"a"}).id == "b"


def test_pick_match_returns_none_without_match():
    assert pick_match([_t("c", "Outra")], ["Primeiro Andar"], set()) is None
