"""Ordenação por andamento (BPM)."""

from __future__ import annotations

from contracts.models import BpmMode, EnrichedTrack

# Abaixo disso, muita música é detectada em "meio tempo" (70 em vez de 140).
HALF_TIME_THRESHOLD = 90.0


def effective_tempo(tempo: float | None, normalize: bool) -> float | None:
    if tempo is None or tempo <= 0:
        return None
    if normalize and tempo < HALF_TIME_THRESHOLD:
        return tempo * 2
    return tempo


def order_by_bpm(tracks: list[EnrichedTrack], mode: BpmMode, normalize: bool = False) -> list[EnrichedTrack]:
    known = [t for t in tracks if effective_tempo(t.tempo, normalize) is not None]
    unknown = [t for t in tracks if effective_tempo(t.tempo, normalize) is None]

    def key(t: EnrichedTrack) -> float:
        return effective_tempo(t.tempo, normalize)  # type: ignore[return-value]

    ascending = sorted(known, key=key)
    if mode is BpmMode.ASC:
        ordered = ascending
    elif mode is BpmMode.DESC:
        ordered = sorted(known, key=key, reverse=True)
    else:
        # Arco: posições pares sobem até o pico, ímpares descem de volta.
        ordered = ascending[0::2] + ascending[1::2][::-1]
    return ordered + unknown
