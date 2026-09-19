"""Opções usadas quando o LLM entende o pedido de reorganização mas não propõe estratégias."""

from contracts.models import BpmMode, GenreLevel, StrategyChoice, StrategyKind

DEFAULT_REORGANIZE_OPTIONS: tuple[StrategyChoice, ...] = (
    StrategyChoice(
        kind=StrategyKind.BPM, label="BPM crescente", bpm_mode=BpmMode.ASC,
        description="Começa devagar e vai acelerando até as mais rápidas.",
    ),
    StrategyChoice(
        kind=StrategyKind.BPM, label="Arco de energia", bpm_mode=BpmMode.ARC, normalize_tempo=True,
        description="Sobe até um pico no meio e desacelera no final.",
    ),
    StrategyChoice(
        kind=StrategyKind.GENRE, label="Blocos por gênero", genre_level=GenreLevel.FAMILY,
        description="Mantém uma playlist só, com as músicas agrupadas por gênero.",
    ),
)
