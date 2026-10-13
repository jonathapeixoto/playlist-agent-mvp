"""Modelos de dados compartilhados. Todo serviço importa daqui; nenhum lê o interior de outro."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field, field_validator

SCHEMA_VERSION = 1


class Artist(BaseModel):
    id: str
    name: str


class Track(BaseModel):
    id: str
    uri: str
    name: str
    artists: list[Artist]
    album: str = ""
    duration_ms: int = 0


class PlaylistSummary(BaseModel):
    id: str
    name: str
    total: int
    owner_id: str


class EnrichedTrack(BaseModel):
    track: Track
    tempo: float | None = None
    energy: float | None = None
    genres: list[str] = Field(default_factory=list)


class StrategyKind(StrEnum):
    BPM = "bpm"
    GENRE = "genre"
    THEME = "theme"


class BpmMode(StrEnum):
    ASC = "asc"
    DESC = "desc"
    ARC = "arc"


class GenreLevel(StrEnum):
    FAMILY = "family"
    SUBGENRE = "subgenre"


class StrategyChoice(BaseModel):
    kind: StrategyKind
    label: str
    description: str
    bpm_mode: BpmMode | None = None
    normalize_tempo: bool = False
    genre_level: GenreLevel | None = None
    genre_split: bool = False
    theme: str | None = None


class IntentAction(StrEnum):
    REORGANIZE = "reorganize"
    DISCOVER = "discover"
    CHAT = "chat"


class Intent(BaseModel):
    action: IntentAction
    reply: str
    playlist_name: str | None = None
    question: str | None = None
    options: list[StrategyChoice] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def _cap_options(cls, value: list[StrategyChoice]) -> list[StrategyChoice]:
        return value[:3]


class SongCandidate(BaseModel):
    title: str
    artist: str


class ThemeSlot(BaseModel):
    label: str
    keywords: list[str]
    candidates: list[SongCandidate] = Field(default_factory=list)

    @field_validator("keywords")
    @classmethod
    def _need_keyword(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k.strip()]
        if not cleaned:
            raise ValueError("cada slot precisa de pelo menos uma keyword")
        return cleaned


class ThemePlan(BaseModel):
    playlist_name: str
    description: str
    slots: list[ThemeSlot]

    @field_validator("slots")
    @classmethod
    def _need_slots(cls, value: list[ThemeSlot]) -> list[ThemeSlot]:
        if not value:
            raise ValueError("o tema precisa de pelo menos um slot")
        return value


class PlaylistDiff(BaseModel):
    previous_positions: list[int | None]
    moved: int


class PlannedPlaylist(BaseModel):
    name: str
    description: str
    tracks: list[EnrichedTrack]
    diff: PlaylistDiff | None = None
    missing_slots: list[str] = Field(default_factory=list)


class PlaylistPlan(BaseModel):
    strategy: StrategyChoice
    source_playlist_id: str | None = None
    playlists: list[PlannedPlaylist]
    bpm_coverage: float = 0.0
    genre_coverage: float = 0.0

    @computed_field
    @property
    def can_replace_in_place(self) -> bool:
        return self.source_playlist_id is not None and len(self.playlists) == 1


class ApplyMode(StrEnum):
    NEW = "new"
    REPLACE = "replace"


class ApplyResult(BaseModel):
    mode: ApplyMode
    playlist_ids: list[str]
    urls: list[str]
    undo_id: int | None = None


class ConversationState(StrEnum):
    UNDERSTAND = "understand"
    PROPOSE = "propose"
    PREVIEW = "preview"
    APPLIED = "applied"


class AgentReply(BaseModel):
    message: str
    state: ConversationState
    options: list[StrategyChoice] = Field(default_factory=list)
    plan: PlaylistPlan | None = None
    result: ApplyResult | None = None


class ProviderKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    OPENAI = "openai_compatible"


class LLMConfig(BaseModel):
    """Motor de IA escolhido pelo usuário. A chave fica só no servidor."""

    provider: ProviderKind
    model: str
    base_url: str = ""
    api_key: str = ""
    preset: str = "claude_code"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider.value,
            "model": self.model,
            "base_url": self.base_url,
            "preset": self.preset,
            "has_key": bool(self.api_key),
        }
