"""Transforma estratégia + faixas enriquecidas em um PlaylistPlan pronto para prévia."""

from __future__ import annotations

from contracts.models import (
    BpmMode, EnrichedTrack, GenreLevel, PlannedPlaylist, PlaylistPlan, PlaylistSummary, StrategyChoice, StrategyKind, ThemePlan,
)
from services.organizer.bpm import order_by_bpm
from services.organizer.diff import diff_positions
from services.organizer.genre import group_by_genre, merge_small_groups


def coverage(tracks: list[EnrichedTrack]) -> tuple[float, float]:
    if not tracks:
        return 0.0, 0.0
    bpm = sum(1 for t in tracks if t.tempo) / len(tracks)
    genre = sum(1 for t in tracks if t.genres) / len(tracks)
    return bpm, genre


def _ids(tracks: list[EnrichedTrack]) -> list[str]:
    return [t.track.id for t in tracks]


def plan_reorganize(strategy: StrategyChoice, source: PlaylistSummary, tracks: list[EnrichedTrack]) -> PlaylistPlan:
    original = _ids(tracks)
    replaceable = True
    if strategy.kind is StrategyKind.BPM:
        ordered = order_by_bpm(tracks, strategy.bpm_mode or BpmMode.ASC, strategy.normalize_tempo)
        playlists = [
            PlannedPlaylist(
                name=f"{source.name} · {strategy.label}",
                description=strategy.description,
                tracks=ordered,
                diff=diff_positions(original, _ids(ordered)),
            )
        ]
    elif strategy.kind is StrategyKind.GENRE:
        groups = group_by_genre(tracks, strategy.genre_level or GenreLevel.FAMILY)
        if strategy.genre_split:
            # Dividir sempre cria playlists novas, mesmo que tudo caia num grupo só.
            replaceable = False
            playlists = [
                PlannedPlaylist(name=f"{source.name} · {label}", description=strategy.description, tracks=group)
                for label, group in merge_small_groups(groups)
            ]
        else:
            ordered = [t for _, group in groups for t in group]
            playlists = [
                PlannedPlaylist(
                    name=f"{source.name} · {strategy.label}",
                    description=strategy.description,
                    tracks=ordered,
                    diff=diff_positions(original, _ids(ordered)),
                )
            ]
    else:
        raise ValueError("estratégias de tema usam plan_theme")
    bpm, genre = coverage(tracks)
    return PlaylistPlan(
        strategy=strategy,
        source_playlist_id=source.id if replaceable and len(playlists) == 1 else None,
        playlists=playlists,
        bpm_coverage=bpm,
        genre_coverage=genre,
    )


def plan_theme(strategy: StrategyChoice, theme: ThemePlan, slots: list[EnrichedTrack | None]) -> PlaylistPlan:
    found = [t for t in slots if t is not None]
    missing = [slot.label for slot, t in zip(theme.slots, slots) if t is None]
    bpm, genre = coverage(found)
    playlist = PlannedPlaylist(name=theme.playlist_name, description=theme.description, tracks=found, missing_slots=missing)
    return PlaylistPlan(strategy=strategy, playlists=[playlist], bpm_coverage=bpm, genre_coverage=genre)
