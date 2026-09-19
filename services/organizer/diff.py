"""Posição anterior de cada faixa na nova ordem (para a prévia)."""

from __future__ import annotations

from contracts.models import PlaylistDiff


def diff_positions(original_ids: list[str], new_ids: list[str]) -> PlaylistDiff:
    slots: dict[str, list[int]] = {}
    for index, tid in enumerate(original_ids):
        slots.setdefault(tid, []).append(index)
    previous: list[int | None] = []
    for tid in new_ids:
        queue = slots.get(tid)
        previous.append(queue.pop(0) if queue else None)
    moved = sum(1 for index, prev in enumerate(previous) if prev != index)
    return PlaylistDiff(previous_positions=previous, moved=moved)
