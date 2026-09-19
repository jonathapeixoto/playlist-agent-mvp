import pytest

from services.organizer.text import contains_phrase, matches_any, normalize_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Primeiro Andar", ["1", "andar"]),
        ("1º Andar", ["1", "andar"]),
        ("1o andar", ["1", "andar"]),
        ("Terceira Via", ["3", "via"]),
        ("Três Corações", ["3", "coracoes"]),
        ("First Floor", ["1", "floor"]),
        ("2nd Floor", ["2", "floor"]),
        ("Andar 07", ["andar", "7"]),
        ("Sétimo Céu", ["7", "ceu"]),
        ("  Rock'n'Roll!!  ", ["rock", "n", "roll"]),
    ],
)
def test_normalize_tokens(text, expected):
    assert normalize_tokens(text) == expected


def test_contains_phrase_matches_across_number_forms():
    assert contains_phrase("O 1º Andar (Ao Vivo)", "Primeiro Andar")


def test_contains_phrase_requires_contiguous_tokens():
    assert not contains_phrase("Andar no Primeiro Dia", "Primeiro Andar")


def test_contains_phrase_blank_keyword_never_matches():
    assert not contains_phrase("qualquer coisa", "!!!")


def test_matches_any_accepts_any_keyword():
    assert matches_any("First Floor Blues", ["Primeiro Andar", "First Floor"])
    assert not matches_any("Segundo Andar", ["Primeiro Andar"])


def test_weekday_that_is_also_ordinal_still_matches():
    assert contains_phrase("Sexta-Feira Sua Linda", "Sexta")
