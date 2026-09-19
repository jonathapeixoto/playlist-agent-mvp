"""Agrupamento por gênero. Famílias são casadas por substring, na ordem da tabela: o mais específico vem primeiro."""

from __future__ import annotations

import unicodedata

from contracts.models import EnrichedTrack, GenreLevel

UNKNOWN = "Sem gênero"
OTHERS = "Outros"

_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("Funk brasileiro", ("funk carioca", "brazilian funk", "funk brasileiro", "baile funk", "funk ostentacao", "funk mtg", "funk paulista")),
    ("Sertanejo", ("sertanejo",)),
    ("Pagode e samba", ("pagode", "samba")),
    ("Forró e piseiro", ("forro", "piseiro", "arrocha", "brega")),
    ("MPB", ("mpb", "musica popular brasileira", "bossa nova", "tropicalia")),
    ("Trap e hip hop", ("trap", "hip hop", "rap", "drill", "grime")),
    ("Metal", ("metal", "deathcore")),
    ("Punk e hardcore", ("punk", "hardcore", "emo")),
    ("Rock", ("rock", "grunge", "shoegaze")),
    ("Eletrônica", ("house", "techno", "trance", "edm", "electro", "dubstep", "drum and bass", "dnb", "eletronica")),
    ("R&B e soul", ("r&b", "rnb", "soul")),
    ("Funk e disco", ("funk", "disco", "boogie")),
    ("Latina", ("reggaeton", "latin", "salsa", "bachata", "cumbia")),
    ("Reggae", ("reggae", "dancehall", "ska")),
    ("Jazz e blues", ("jazz", "blues")),
    ("Clássica", ("classical", "classica", "orchestra", "opera")),
    ("Indie", ("indie",)),
    ("Pop", ("pop",)),
    ("Country e folk", ("country", "folk", "americana")),
]


def normalize_genre(genre: str) -> str:
    decomposed = unicodedata.normalize("NFKD", genre.lower().replace("-", " "))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def genre_family(genre: str) -> str | None:
    normalized = normalize_genre(genre)
    for family, needles in _FAMILIES:
        if any(n in normalized for n in needles):
            return family
    return None


def primary_label(track: EnrichedTrack, level: GenreLevel) -> str:
    if not track.genres:
        return UNKNOWN
    if level is GenreLevel.SUBGENRE:
        return track.genres[0]
    for genre in track.genres:
        family = genre_family(genre)
        if family:
            return family
    return OTHERS


def _order_groups(groups: dict[str, list[EnrichedTrack]]) -> list[tuple[str, list[EnrichedTrack]]]:
    tail = (OTHERS, UNKNOWN)
    labels = sorted((k for k in groups if k not in tail), key=lambda k: (-len(groups[k]), k))
    labels += [k for k in tail if k in groups]
    return [(k, groups[k]) for k in labels]


def group_by_genre(tracks: list[EnrichedTrack], level: GenreLevel) -> list[tuple[str, list[EnrichedTrack]]]:
    groups: dict[str, list[EnrichedTrack]] = {}
    for track in tracks:
        groups.setdefault(primary_label(track, level), []).append(track)
    return _order_groups(groups)


def merge_small_groups(
    groups: list[tuple[str, list[EnrichedTrack]]], min_size: int = 3
) -> list[tuple[str, list[EnrichedTrack]]]:
    merged: dict[str, list[EnrichedTrack]] = {}
    for label, tracks in groups:
        target = label if label == UNKNOWN or len(tracks) >= min_size else OTHERS
        merged.setdefault(target, []).extend(tracks)
    return _order_groups(merged)
