# Playlist Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App local em que o Jone conversa com um agente (Claude Code local) que entende o pedido, propõe modelos de organização (BPM, gênero, tema) e, após confirmação, cria ou reordena playlists no Spotify.

**Architecture:** Servidor FastAPI em `127.0.0.1:8000` com interface web em HTML/JS puro. Seis serviços em `services/` (spotify, enrichment, organizer, llm, agent, web) conversam só por contratos pydantic em `contracts/`. O LLM faz o trabalho latente (entender, propor, sugerir músicas); o código faz o determinístico (ordenar, agrupar, casar títulos, chamar APIs).

**Tech Stack:** Python 3.12+ (máquina tem 3.13), uv, FastAPI, uvicorn, httpx, pydantic v2, python-dotenv, sqlite3 (stdlib), pytest, respx. LLM via `claude -p` (Claude Code 2.1.x local).

**Spec:** `docs/superpowers/specs/2026-09-18-playlist-agent-design.md`

## Global Constraints

- Python `>=3.12`; gerenciador `uv`; rodar tudo com `uv run ...`.
- Servidor sempre em `http://127.0.0.1:8000`; redirect do Spotify `http://127.0.0.1:8000/callback` (nunca `localhost`).
- LLM: somente `claude -p --model opus --output-format json --json-schema <schema> --system-prompt <prompt> --tools ""`, lendo `structured_output` da saída. Nunca API paga de LLM.
- Nada é escrito no Spotify sem o usuário clicar em confirmar na interface. Padrão: criar playlist nova.
- Spotify (fev/2026): busca `limit` máx. 10 (paginar com `offset`); itens de playlist em `/playlists/{id}/items`, faixa em `entry["item"]` (fallback `entry["track"]`); criar playlist `POST /me/playlists`; `PUT /playlists/{id}/items` troca até 100 URIs, o resto vai em `POST` de 100 em 100; nada de endpoints em lote.
- ReccoBeats: `GET https://api.reccobeats.com/v1/audio-features?ids=<até 40 IDs do Spotify>`, sem auth; resposta `{"content":[{"href":"https://open.spotify.com/track/<id>","tempo":..,"energy":..}]}`; faixas desconhecidas simplesmente não aparecem.
- Gate tests: sem rede, sem subprocess real, suíte inteira < 2s. Evals (pagos/rede) são scripts separados, nunca coletados pelo pytest.
- Textos de interface e mensagens ao usuário em português do Brasil. Sem travessão (em dash) em textos de UI e docs. Separador em nomes de playlist: ` · `.
- Faixa sem BPM nunca some: vai para o fim. Faixa sem gênero vai para o grupo `Sem gênero`.
- Nome de playlist truncado em 100 caracteres, descrição em 300 e sem quebras de linha.
- Imports entre serviços só pelos módulos públicos listados em "Interfaces" de cada tarefa. Erros compartilhados vivem em `contracts/errors.py`.

## Mapa de arquivos

```
pyproject.toml, .gitignore, .env.example, README.md, .githooks/pre-commit
contracts/  __init__.py, models.py, ports.py, errors.py, tests/test_models.py
services/__init__.py
services/organizer/  text.py, theme.py, bpm.py, genre.py, diff.py, planner.py, README.md, tests/
services/spotify/    auth.py, client.py, README.md, tests/
services/enrichment/ cache.py, reccobeats.py, genres.py, enricher.py, README.md, tests/
services/llm/        runner.py, structured.py, api.py, prompts/{interpret,theme}.md, evals/{scoring.py,intent_cases.jsonl,run_intent.py}, README.md, tests/
services/agent/      lookup.py, trace.py, undo.py, defaults.py, theme_resolver.py, agent.py, evals/run_theme.py, README.md, tests/
services/web/        settings.py, wiring.py, app.py, main.py, static/{index.html,app.js,style.css}, README.md, tests/
```

Todo diretório de pacote (`contracts/`, `services/`, `services/<nome>/`, `services/llm/evals/`, `services/agent/evals/`) tem `__init__.py` vazio com uma docstring de uma linha. Diretórios `tests/` não têm `__init__.py` (pytest em `--import-mode=importlib`).

## Ordem e paralelismo

Task 1 primeiro (contratos). Depois quatro trilhas independentes que podem rodar em paralelo, cada uma num diretório próprio: **organizer** (Tasks 2-4), **spotify** (5-6), **enrichment** (7-8), **llm** (9-10). Depois **agent** (11-13), **web** (14-15), e por fim Task 16 (README, verificação real).

---

### Task 1: Scaffold do projeto e contratos

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `.githooks/pre-commit`
- Create: `contracts/__init__.py`, `contracts/models.py`, `contracts/ports.py`, `contracts/errors.py`
- Create: `services/__init__.py`
- Test: `contracts/tests/test_models.py`

**Interfaces:**
- Produces: todos os modelos de `contracts/models.py` abaixo; protocolos `SpotifyPort`, `EnricherPort`, `LLMPort` em `contracts/ports.py`; exceções `AuthRequired`, `ExternalServiceError` em `contracts/errors.py`.

- [ ] **Step 1: Criar `pyproject.toml`**

```toml
[project]
name = "playlist-agent"
version = "0.1.0"
description = "Agente de IA local que organiza playlists do Spotify"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "httpx>=0.27",
  "pydantic>=2.8",
  "python-dotenv>=1.0",
]

[project.scripts]
playlist-agent = "services.web.main:main"

[dependency-groups]
dev = ["pytest>=8", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["contracts", "services"]

[tool.pytest.ini_options]
addopts = "-q --import-mode=importlib"
testpaths = ["contracts", "services"]
pythonpath = ["."]
```

- [ ] **Step 2: Criar `.gitignore`, `.env.example`, `services/__init__.py`, `contracts/__init__.py`**

`.gitignore`:
```
.env
data/
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

`.env.example`:
```
# Client ID do app criado em https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID=
# Chave grátis em https://www.last.fm/api/account/create (opcional, melhora gêneros)
LASTFM_API_KEY=
```

`services/__init__.py`: `"""Serviços independentes do Playlist Agent."""`
`contracts/__init__.py`: `"""Contratos compartilhados entre serviços."""`

- [ ] **Step 3: Escrever o teste que falha, `contracts/tests/test_models.py`**

```python
import pytest
from pydantic import ValidationError

from contracts.models import (
    AgentReply,
    ConversationState,
    Intent,
    IntentAction,
    PlannedPlaylist,
    PlaylistPlan,
    StrategyChoice,
    StrategyKind,
    ThemePlan,
    ThemeSlot,
)


def _strategy(label: str = "BPM") -> StrategyChoice:
    return StrategyChoice(kind=StrategyKind.BPM, label=label, description="d")


def test_plan_can_replace_only_with_single_playlist_and_source():
    one = PlannedPlaylist(name="x", description="", tracks=[])
    assert PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one]).can_replace_in_place
    assert not PlaylistPlan(strategy=_strategy(), source_playlist_id=None, playlists=[one]).can_replace_in_place
    assert not PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one, one]).can_replace_in_place


def test_can_replace_is_serialized_for_frontend():
    one = PlannedPlaylist(name="x", description="", tracks=[])
    dumped = PlaylistPlan(strategy=_strategy(), source_playlist_id="p", playlists=[one]).model_dump()
    assert dumped["can_replace_in_place"] is True


def test_intent_keeps_at_most_three_options():
    intent = Intent(action=IntentAction.REORGANIZE, reply="ok", options=[_strategy(str(i)) for i in range(5)])
    assert [o.label for o in intent.options] == ["0", "1", "2"]


def test_theme_plan_requires_slots():
    with pytest.raises(ValidationError):
        ThemePlan(playlist_name="x", description="", slots=[])


def test_theme_slot_requires_non_blank_keyword():
    with pytest.raises(ValidationError):
        ThemeSlot(label="x", keywords=["  "])


def test_agent_reply_round_trips_json():
    reply = AgentReply(message="oi", state=ConversationState.PROPOSE, options=[_strategy()])
    assert AgentReply.model_validate_json(reply.model_dump_json()) == reply
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv sync && uv run pytest contracts -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'contracts.models'`

- [ ] **Step 5: Implementar `contracts/errors.py`**

```python
"""Exceções que atravessam fronteiras de serviço."""


class AuthRequired(Exception):
    """O usuário precisa (re)fazer login no Spotify."""


class ExternalServiceError(Exception):
    """Falha em serviço externo (Spotify, ReccoBeats, Last.fm, Claude Code). A mensagem é mostrável ao usuário."""
```

- [ ] **Step 6: Implementar `contracts/models.py`**

```python
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
```

- [ ] **Step 7: Implementar `contracts/ports.py`**

```python
"""Interfaces que o agente consome. Implementações reais e fakes de teste seguem estas assinaturas."""

from __future__ import annotations

from typing import Protocol

from contracts.models import EnrichedTrack, Intent, PlaylistSummary, ThemePlan, Track


class SpotifyPort(Protocol):
    def me_id(self) -> str: ...
    def my_playlists(self) -> list[PlaylistSummary]: ...
    def playlist_tracks(self, playlist_id: str) -> list[Track]: ...
    def search_tracks(self, query: str, pages: int = 1) -> list[Track]: ...
    def artist_genres(self, artist_id: str) -> list[str]: ...
    def create_playlist(self, name: str, description: str) -> tuple[str, str]: ...
    def replace_items(self, playlist_id: str, uris: list[str]) -> None: ...


class EnricherPort(Protocol):
    def enrich(self, tracks: list[Track]) -> list[EnrichedTrack]: ...


class LLMPort(Protocol):
    def interpret(self, message: str, history: list[tuple[str, str]], playlist_names: list[str]) -> Intent: ...
    def plan_theme(self, theme: str, max_slots: int) -> ThemePlan: ...
```

- [ ] **Step 8: Rodar e ver passar**

Run: `uv run pytest contracts -v`
Expected: 6 passed

- [ ] **Step 9: Pre-commit hook**

`.githooks/pre-commit`:
```sh
#!/bin/sh
uv run pytest -q || { echo "Gate tests falharam. Commit bloqueado."; exit 1; }
```

Run: `git config core.hooksPath .githooks`

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock .gitignore .env.example .githooks contracts services/__init__.py
git commit -m "feat: scaffold do projeto e contratos compartilhados"
```

---

### Task 2: organizer, normalização de texto e casamento de títulos

**Files:**
- Create: `services/organizer/__init__.py`, `services/organizer/text.py`, `services/organizer/theme.py`
- Test: `services/organizer/tests/test_text.py`, `services/organizer/tests/test_theme_match.py`

**Interfaces:**
- Consumes: `contracts.models.Track`
- Produces: `services.organizer.text.normalize_tokens(text: str) -> list[str]`, `contains_phrase(title: str, keyword: str) -> bool`, `matches_any(title: str, keywords: list[str]) -> bool`; `services.organizer.theme.pick_match(tracks: list[Track], keywords: list[str], exclude_ids: set[str]) -> Track | None`

- [ ] **Step 1: Teste que falha, `services/organizer/tests/test_text.py`**

```python
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
```

- [ ] **Step 2: Teste que falha, `services/organizer/tests/test_theme_match.py`**

```python
from contracts.models import Artist, Track
from services.organizer.theme import pick_match


def _t(tid: str, name: str) -> Track:
    return Track(id=tid, uri=f"spotify:track:{tid}", name=name, artists=[Artist(id="a", name="A")])


def test_pick_match_skips_used_and_non_matching():
    a, b, c = _t("a", "Primeiro Andar"), _t("b", "1º Andar"), _t("c", "Outra")
    assert pick_match([c, a, b], ["Primeiro Andar"], exclude_ids={"a"}).id == "b"


def test_pick_match_returns_none_without_match():
    assert pick_match([_t("c", "Outra")], ["Primeiro Andar"], set()) is None
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest services/organizer -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.organizer'`

- [ ] **Step 4: Implementar**

`services/organizer/__init__.py`: `"""Estratégias determinísticas de organização de playlists (sem rede, sem LLM)."""`

`services/organizer/text.py`:
```python
"""Normalização de títulos para casar temas: acentos, caixa, números por extenso e ordinais viram a mesma forma."""

from __future__ import annotations

import re
import unicodedata

_ORDINALS = {
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3,
    "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7, "oitavo": 8, "oitava": 8, "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_CARDINALS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# "1o", "2a", "3rd", "4th": NFKD já transformou "º"/"ª" em "o"/"a".
_NUMBER_SUFFIX = re.compile(r"^(\d+)(o|a|st|nd|rd|th)$")


def normalize_tokens(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", ascii_text):
        if token.isdigit():
            tokens.append(str(int(token)))
            continue
        suffixed = _NUMBER_SUFFIX.match(token)
        if suffixed:
            tokens.append(str(int(suffixed.group(1))))
            continue
        number = _ORDINALS.get(token) or _CARDINALS.get(token)
        tokens.append(str(number) if number else token)
    return tokens


def contains_phrase(title: str, keyword: str) -> bool:
    haystack, needle = normalize_tokens(title), normalize_tokens(keyword)
    if not needle:
        return False
    size = len(needle)
    return any(haystack[i : i + size] == needle for i in range(len(haystack) - size + 1))


def matches_any(title: str, keywords: list[str]) -> bool:
    return any(contains_phrase(title, k) for k in keywords)
```

`services/organizer/theme.py`:
```python
"""Escolha determinística de faixa para um slot de tema."""

from __future__ import annotations

from contracts.models import Track
from services.organizer.text import matches_any


def pick_match(tracks: list[Track], keywords: list[str], exclude_ids: set[str]) -> Track | None:
    for track in tracks:
        if track.id not in exclude_ids and matches_any(track.name, keywords):
            return track
    return None
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest services/organizer -v`
Expected: 17 passed

- [ ] **Step 6: Commit**

```bash
git add services/organizer
git commit -m "feat(organizer): normalização de títulos e casamento de temas"
```

---

### Task 3: organizer, BPM, gênero e diff

**Files:**
- Create: `services/organizer/bpm.py`, `services/organizer/genre.py`, `services/organizer/diff.py`
- Test: `services/organizer/tests/test_bpm.py`, `services/organizer/tests/test_genre.py`, `services/organizer/tests/test_diff.py`

**Interfaces:**
- Consumes: `contracts.models.EnrichedTrack, BpmMode, GenreLevel, PlaylistDiff`
- Produces:
  - `services.organizer.bpm.effective_tempo(tempo: float | None, normalize: bool) -> float | None`, `order_by_bpm(tracks: list[EnrichedTrack], mode: BpmMode, normalize: bool = False) -> list[EnrichedTrack]`
  - `services.organizer.genre.UNKNOWN = "Sem gênero"`, `OTHERS = "Outros"`, `normalize_genre(genre: str) -> str`, `genre_family(genre: str) -> str | None`, `primary_label(track: EnrichedTrack, level: GenreLevel) -> str`, `group_by_genre(tracks: list[EnrichedTrack], level: GenreLevel) -> list[tuple[str, list[EnrichedTrack]]]`, `merge_small_groups(groups, min_size: int = 3) -> list[tuple[str, list[EnrichedTrack]]]`
  - `services.organizer.diff.diff_positions(original_ids: list[str], new_ids: list[str]) -> PlaylistDiff`

- [ ] **Step 1: Testes que falham**

`services/organizer/tests/test_bpm.py`:
```python
from contracts.models import Artist, BpmMode, EnrichedTrack, Track
from services.organizer.bpm import effective_tempo, order_by_bpm


def _e(tid: str, tempo: float | None) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, tempo=tempo)


def _ids(tracks):
    return [t.track.id for t in tracks]


def test_asc_and_desc():
    tracks = [_e("b", 120), _e("a", 100), _e("c", 140)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["a", "b", "c"]
    assert _ids(order_by_bpm(tracks, BpmMode.DESC)) == ["c", "b", "a"]


def test_arc_rises_to_peak_then_falls():
    tracks = [_e(str(t), t) for t in (140, 100, 130, 110, 120)]
    assert _ids(order_by_bpm(tracks, BpmMode.ARC)) == ["100", "120", "140", "130", "110"]


def test_unknown_tempo_goes_last_in_original_order():
    tracks = [_e("x", None), _e("a", 100), _e("y", 0), _e("b", 90)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["b", "a", "x", "y"]


def test_normalize_doubles_slow_tempos():
    assert effective_tempo(70, normalize=True) == 140
    assert effective_tempo(70, normalize=False) == 70
    tracks = [_e("slow", 70), _e("mid", 120)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC, normalize=True)) == ["mid", "slow"]


def test_ties_keep_original_order():
    tracks = [_e("first", 100), _e("second", 100)]
    assert _ids(order_by_bpm(tracks, BpmMode.ASC)) == ["first", "second"]
    assert _ids(order_by_bpm(tracks, BpmMode.DESC)) == ["first", "second"]
```

`services/organizer/tests/test_genre.py`:
```python
import pytest

from contracts.models import Artist, EnrichedTrack, GenreLevel, Track
from services.organizer.genre import OTHERS, UNKNOWN, genre_family, group_by_genre, merge_small_groups, primary_label


def _e(tid: str, genres: list[str]) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, genres=genres)


@pytest.mark.parametrize(
    ("genre", "family"),
    [
        ("funk carioca", "Funk brasileiro"),
        ("brazilian funk", "Funk brasileiro"),
        ("sertanejo universitario", "Sertanejo"),
        ("pagode", "Pagode e samba"),
        ("forró", "Forró e piseiro"),
        ("MPB", "MPB"),
        ("musica popular brasileira", "MPB"),
        ("trap brasileiro", "Trap e hip hop"),
        ("hip-hop", "Trap e hip hop"),
        ("heavy metal", "Metal"),
        ("pop punk", "Punk e hardcore"),
        ("indie rock", "Rock"),
        ("deep house", "Eletrônica"),
        ("funk", "Funk e disco"),
        ("reggaeton", "Latina"),
        ("indie pop", "Indie"),
        ("dance pop", "Pop"),
        ("xyzcore", None),
    ],
)
def test_genre_family(genre, family):
    assert genre_family(genre) == family


def test_primary_label_levels():
    t = _e("a", ["indie rock", "rock"])
    assert primary_label(t, GenreLevel.FAMILY) == "Rock"
    assert primary_label(t, GenreLevel.SUBGENRE) == "indie rock"
    assert primary_label(_e("b", []), GenreLevel.FAMILY) == UNKNOWN
    assert primary_label(_e("c", ["xyzcore"]), GenreLevel.FAMILY) == OTHERS


def test_group_by_genre_orders_by_size_and_puts_tail_last():
    tracks = [
        _e("1", ["pagode"]), _e("2", []), _e("3", ["sertanejo"]),
        _e("4", ["sertanejo"]), _e("5", ["xyz"]), _e("6", ["pagode"]), _e("7", ["sertanejo"]),
    ]
    groups = group_by_genre(tracks, GenreLevel.FAMILY)
    assert [label for label, _ in groups] == ["Sertanejo", "Pagode e samba", OTHERS, UNKNOWN]
    assert [t.track.id for t in groups[0][1]] == ["3", "4", "7"]


def test_merge_small_groups_folds_into_others():
    groups = [
        ("Rock", [_e("1", []), _e("2", []), _e("3", [])]),
        ("Jazz e blues", [_e("4", [])]),
        (UNKNOWN, [_e("5", [])]),
    ]
    merged = merge_small_groups(groups, min_size=3)
    assert [label for label, _ in merged] == ["Rock", OTHERS, UNKNOWN]
    assert [t.track.id for t in merged[1][1]] == ["4"]
```

`services/organizer/tests/test_diff.py`:
```python
from services.organizer.diff import diff_positions


def test_diff_positions_and_moved_count():
    diff = diff_positions(["a", "b", "c"], ["c", "b", "a"])
    assert diff.previous_positions == [2, 1, 0]
    assert diff.moved == 2


def test_diff_handles_duplicates_and_new_tracks():
    diff = diff_positions(["a", "a", "b"], ["a", "b", "a", "z"])
    assert diff.previous_positions == [0, 2, 1, None]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/organizer -v`
Expected: FAIL com `ModuleNotFoundError` para `services.organizer.bpm`, `genre`, `diff`

- [ ] **Step 3: Implementar**

`services/organizer/bpm.py`:
```python
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
```

`services/organizer/genre.py`:
```python
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
```

`services/organizer/diff.py`:
```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/organizer -v`
Expected: all passed (17 anteriores + 5 bpm + 21 genre + 2 diff)

- [ ] **Step 5: Commit**

```bash
git add services/organizer
git commit -m "feat(organizer): ordenação por BPM, agrupamento por gênero e diff"
```

---

### Task 4: organizer, planner (monta o PlaylistPlan)

**Files:**
- Create: `services/organizer/planner.py`, `services/organizer/README.md`
- Test: `services/organizer/tests/test_planner.py`

**Interfaces:**
- Consumes: Tasks 2-3; `contracts.models.*`
- Produces: `services.organizer.planner.coverage(tracks: list[EnrichedTrack]) -> tuple[float, float]` (bpm, gênero); `plan_reorganize(strategy: StrategyChoice, source: PlaylistSummary, tracks: list[EnrichedTrack]) -> PlaylistPlan`; `plan_theme(strategy: StrategyChoice, theme: ThemePlan, slots: list[EnrichedTrack | None]) -> PlaylistPlan`

- [ ] **Step 1: Teste que falha, `services/organizer/tests/test_planner.py`**

```python
import pytest

from contracts.models import (
    Artist, BpmMode, EnrichedTrack, GenreLevel, PlaylistSummary, StrategyChoice, StrategyKind, ThemePlan, ThemeSlot, Track,
)
from services.organizer.planner import coverage, plan_reorganize, plan_theme

SOURCE = PlaylistSummary(id="src", name="Treino", total=4, owner_id="me")


def _e(tid: str, tempo: float | None = None, genres: list[str] | None = None) -> EnrichedTrack:
    track = Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id="a", name="A")])
    return EnrichedTrack(track=track, tempo=tempo, genres=genres or [])


def test_bpm_plan_single_playlist_with_diff():
    strategy = StrategyChoice(kind=StrategyKind.BPM, label="BPM crescente", description="d", bpm_mode=BpmMode.ASC)
    plan = plan_reorganize(strategy, SOURCE, [_e("b", 120), _e("a", 100)])
    assert plan.source_playlist_id == "src"
    assert plan.can_replace_in_place
    [playlist] = plan.playlists
    assert playlist.name == "Treino · BPM crescente"
    assert [t.track.id for t in playlist.tracks] == ["a", "b"]
    assert playlist.diff.previous_positions == [1, 0]


def test_genre_split_creates_one_playlist_per_group_and_cannot_replace():
    strategy = StrategyChoice(
        kind=StrategyKind.GENRE, label="Por gênero", description="d", genre_level=GenreLevel.FAMILY, genre_split=True
    )
    tracks = [_e(str(i), genres=["rock"]) for i in range(3)] + [_e(str(i + 3), genres=["pagode"]) for i in range(3)]
    plan = plan_reorganize(strategy, SOURCE, tracks)
    assert [p.name for p in plan.playlists] == ["Treino · Pagode e samba", "Treino · Rock"]
    assert plan.source_playlist_id is None
    assert not plan.can_replace_in_place


def test_genre_split_with_single_group_still_cannot_replace():
    strategy = StrategyChoice(
        kind=StrategyKind.GENRE, label="Por gênero", description="d", genre_level=GenreLevel.FAMILY, genre_split=True
    )
    plan = plan_reorganize(strategy, SOURCE, [_e("a", genres=["rock"]), _e("b", genres=["pagode"])])
    assert len(plan.playlists) == 1
    assert not plan.can_replace_in_place


def test_genre_group_keeps_single_playlist_in_blocks():
    strategy = StrategyChoice(kind=StrategyKind.GENRE, label="Blocos", description="d", genre_level=GenreLevel.FAMILY)
    plan = plan_reorganize(strategy, SOURCE, [_e("r1", genres=["rock"]), _e("p1", genres=["pop"]), _e("r2", genres=["rock"])])
    assert [t.track.id for t in plan.playlists[0].tracks] == ["r1", "r2", "p1"]


def test_theme_strategy_is_rejected_by_plan_reorganize():
    with pytest.raises(ValueError):
        plan_reorganize(StrategyChoice(kind=StrategyKind.THEME, label="t", description="d"), SOURCE, [])


def test_plan_theme_reports_missing_slots():
    theme = ThemePlan(
        playlist_name="Prédio",
        description="Sobe!",
        slots=[ThemeSlot(label="Térreo", keywords=["Térreo"]), ThemeSlot(label="1º", keywords=["Primeiro Andar"])],
    )
    strategy = StrategyChoice(kind=StrategyKind.THEME, label="Prédio", description="d", theme="prédio")
    plan = plan_theme(strategy, theme, [None, _e("x", 100)])
    [playlist] = plan.playlists
    assert playlist.name == "Prédio"
    assert playlist.missing_slots == ["Térreo"]
    assert [t.track.id for t in playlist.tracks] == ["x"]
    assert plan.source_playlist_id is None


def test_coverage():
    assert coverage([_e("a", 100, ["rock"]), _e("b")]) == (0.5, 0.5)
    assert coverage([]) == (0.0, 0.0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/organizer/tests/test_planner.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.organizer.planner'`

- [ ] **Step 3: Implementar `services/organizer/planner.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/organizer -v`
Expected: all passed

- [ ] **Step 5: `services/organizer/README.md`**

```markdown
# organizer

Lógica pura de organização. Sem rede, sem LLM, sem estado: mesma entrada, mesma saída.

- `text.py`: normaliza títulos (acentos, caixa, "1º" = "Primeiro" = "First") e casa keywords de tema.
- `theme.py`: `pick_match` escolhe a primeira faixa cujo título contém uma keyword.
- `bpm.py`: ordena por BPM (crescente, decrescente, arco). Sem BPM vai para o fim.
- `genre.py`: agrupa por família de gênero (tabela ordenada por especificidade) ou subgênero.
- `diff.py`: posição anterior de cada faixa, para a prévia.
- `planner.py`: junta tudo em `PlaylistPlan`.

Testes: `uv run pytest services/organizer`
```

- [ ] **Step 6: Commit**

```bash
git add services/organizer
git commit -m "feat(organizer): planner de reorganização e de tema"
```

---

### Task 5: spotify, OAuth PKCE e armazenamento de token

**Files:**
- Create: `services/spotify/__init__.py`, `services/spotify/auth.py`
- Test: `services/spotify/tests/test_auth.py`

**Interfaces:**
- Consumes: `contracts.errors.AuthRequired`
- Produces: `services.spotify.auth.SCOPES`, `AUTHORIZE_URL`, `TOKEN_URL`, `Token(access_token: str, refresh_token: str, expires_at: float)` com `expired(now: float, margin: float = 60) -> bool`, `TokenStore(path: Path)` com `load() -> Token | None`, `save(token)`, `clear()`; `make_verifier() -> str`, `code_challenge(verifier: str) -> str`, `authorize_url(client_id, redirect_uri, state, challenge) -> str`; `SpotifyAuth(client_id, redirect_uri, store, http: httpx.Client, clock=time.time)` com `exchange_code(code, verifier) -> Token`, `refresh() -> Token`, `access_token() -> str`, `has_token() -> bool`.

**Conceito:** PKCE ("pixy") é o fluxo OAuth para apps que não conseguem guardar segredo. O app gera um `verifier` aleatório, manda só o hash dele (`challenge`) para o Spotify no login e, na troca do código por token, prova que é o mesmo app mostrando o `verifier` original. Não precisa de client secret.

- [ ] **Step 1: Teste que falha, `services/spotify/tests/test_auth.py`**

```python
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from contracts.errors import AuthRequired
from services.spotify.auth import (
    TOKEN_URL, SpotifyAuth, Token, TokenStore, authorize_url, code_challenge, make_verifier,
)


def test_code_challenge_matches_rfc7636_vector():
    assert code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifier_length_is_valid():
    assert 43 <= len(make_verifier()) <= 128


def test_authorize_url_has_pkce_params():
    query = parse_qs(urlparse(authorize_url("cid", "http://127.0.0.1:8000/callback", "st", "ch")).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["ch"]
    assert query["state"] == ["st"]
    assert "playlist-modify-private" in query["scope"][0]


def test_token_store_round_trip(tmp_path):
    store = TokenStore(tmp_path / "token.json")
    assert store.load() is None
    store.save(Token(access_token="a", refresh_token="r", expires_at=10))
    assert store.load().access_token == "a"
    store.clear()
    assert store.load() is None


def _auth(tmp_path, now=1000.0):
    clock = {"now": now}
    auth = SpotifyAuth(
        "cid", "http://127.0.0.1:8000/callback", TokenStore(tmp_path / "t.json"), httpx.Client(), clock=lambda: clock["now"]
    )
    return auth, clock


@respx.mock
def test_exchange_code_sends_verifier_and_saves(tmp_path):
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600})
    )
    auth, _ = _auth(tmp_path)
    token = auth.exchange_code("code123", "verif")
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["code_verifier"] == ["verif"]
    assert body["grant_type"] == ["authorization_code"]
    assert token.expires_at == 1000 + 3600
    assert auth.has_token()


@respx.mock
def test_access_token_refreshes_when_expired_and_keeps_old_refresh(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "a2", "expires_in": 3600}))
    auth, _ = _auth(tmp_path)
    auth.store.save(Token(access_token="a1", refresh_token="r1", expires_at=1010))
    assert auth.access_token() == "a2"
    assert auth.store.load().refresh_token == "r1"


@respx.mock
def test_refresh_failure_clears_store_and_requires_login(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    auth, _ = _auth(tmp_path)
    auth.store.save(Token(access_token="a1", refresh_token="r1", expires_at=0))
    with pytest.raises(AuthRequired):
        auth.access_token()
    assert not auth.has_token()


def test_access_token_without_login_requires_auth(tmp_path):
    auth, _ = _auth(tmp_path)
    with pytest.raises(AuthRequired):
        auth.access_token()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/spotify -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.spotify'`

- [ ] **Step 3: Implementar**

`services/spotify/__init__.py`: `"""Integração com a Web API do Spotify (regras de fev/2026)."""`

`services/spotify/auth.py`:
```python
"""OAuth Authorization Code com PKCE. Token salvo em arquivo local (data/token.json, fora do git)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from contracts.errors import AuthRequired

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
]


class Token(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float

    def expired(self, now: float, margin: float = 60) -> bool:
        return now >= self.expires_at - margin


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        return Token.model_validate(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(token.model_dump_json(), encoding="utf-8")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def make_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": " ".join(SCOPES),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


class SpotifyAuth:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        store: TokenStore,
        http: httpx.Client,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.store = store
        self.http = http
        self.clock = clock

    def _post(self, form: dict[str, str], previous_refresh: str | None) -> Token:
        response = self.http.post(TOKEN_URL, data=form)
        if response.status_code != 200:
            self.store.clear()
            raise AuthRequired(f"Spotify recusou o token ({response.status_code}). Faça login de novo.")
        data = response.json()
        token = Token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or previous_refresh or "",
            expires_at=self.clock() + float(data["expires_in"]),
        )
        self.store.save(token)
        return token

    def exchange_code(self, code: str, verifier: str) -> Token:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        return self._post(form, previous_refresh=None)

    def refresh(self) -> Token:
        current = self.store.load()
        if current is None or not current.refresh_token:
            raise AuthRequired("Faça login no Spotify.")
        form = {"grant_type": "refresh_token", "refresh_token": current.refresh_token, "client_id": self.client_id}
        return self._post(form, previous_refresh=current.refresh_token)

    def access_token(self) -> str:
        token = self.store.load()
        if token is None:
            raise AuthRequired("Faça login no Spotify.")
        if token.expired(self.clock()):
            token = self.refresh()
        return token.access_token

    def has_token(self) -> bool:
        return self.store.load() is not None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/spotify -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add services/spotify
git commit -m "feat(spotify): OAuth PKCE com refresh e token local"
```

---

### Task 6: spotify, cliente da Web API

**Files:**
- Create: `services/spotify/client.py`, `services/spotify/README.md`
- Test: `services/spotify/tests/test_client.py`

**Interfaces:**
- Consumes: `SpotifyAuth` (Task 5; só usa `access_token()` e `refresh()`), `contracts.models.Track, Artist, PlaylistSummary`, `contracts.errors.ExternalServiceError`
- Produces: `services.spotify.client.API = "https://api.spotify.com/v1"`, `SpotifyError(ExternalServiceError)`, `parse_track(obj: dict) -> Track`, `SpotifyClient(auth, http: httpx.Client, sleep=time.sleep, max_retries: int = 3)` que satisfaz `contracts.ports.SpotifyPort`.

- [ ] **Step 1: Teste que falha, `services/spotify/tests/test_client.py`**

```python
import json

import httpx
import pytest
import respx

from services.spotify.client import SpotifyClient, SpotifyError

HOST = "api.spotify.com"


class FakeAuth:
    def __init__(self):
        self.token = "t1"
        self.refreshes = 0

    def access_token(self):
        return self.token

    def refresh(self):
        self.refreshes += 1
        self.token = "t2"


def _track(tid, name="Song", type_="track"):
    return {"id": tid, "uri": f"spotify:track:{tid}", "name": name, "type": type_,
            "artists": [{"id": "ar", "name": "Artist"}], "album": {"name": "Alb"}, "duration_ms": 1000}


@pytest.fixture
def client():
    sleeps = []
    c = SpotifyClient(FakeAuth(), httpx.Client(), sleep=sleeps.append)
    c.sleeps = sleeps
    return c


@respx.mock
def test_my_playlists_paginates_and_keeps_only_owned_or_collaborative(client):
    respx.get(host=HOST, path="/v1/me").mock(return_value=httpx.Response(200, json={"id": "me"}))
    respx.get(host=HOST, path="/v1/me/playlists").mock(side_effect=[
        httpx.Response(200, json={"items": [
            {"id": "p1", "name": "Minha", "owner": {"id": "me"}, "items": {"total": 3}},
            {"id": "p2", "name": "Alheia", "owner": {"id": "x"}, "collaborative": False, "items": {"total": 1}},
        ], "next": f"https://{HOST}/v1/me/playlists?offset=50&limit=50"}),
        httpx.Response(200, json={"items": [
            {"id": "p3", "name": "Colab", "owner": {"id": "x"}, "collaborative": True, "tracks": {"total": 2}},
            None,
        ], "next": None}),
    ])
    playlists = client.my_playlists()
    assert [(p.id, p.total) for p in playlists] == [("p1", 3), ("p3", 2)]


@respx.mock
def test_playlist_tracks_reads_item_key_and_skips_local_and_episodes(client):
    respx.get(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"items": [
        {"item": _track("a", "Primeiro Andar")},
        {"track": _track("b")},
        {"item": _track("c"), "is_local": True},
        {"item": _track("d", type_="episode")},
        {"item": None},
    ], "next": None}))
    tracks = client.playlist_tracks("p1")
    assert [t.id for t in tracks] == ["a", "b"]
    assert tracks[0].name == "Primeiro Andar"
    assert tracks[0].artists[0].name == "Artist"
    assert tracks[0].album == "Alb"


@respx.mock
def test_search_uses_limit_10_and_offset_pages(client):
    route = respx.get(host=HOST, path="/v1/search").mock(side_effect=[
        httpx.Response(200, json={"tracks": {"items": [_track("a")]}}),
        httpx.Response(200, json={"tracks": {"items": [_track("b")]}}),
    ])
    tracks = client.search_tracks('track:"Andar"', pages=2)
    assert [t.id for t in tracks] == ["a", "b"]
    params = [dict(c.request.url.params) for c in route.calls]
    assert params[0]["limit"] == "10" and params[0]["offset"] == "0"
    assert params[1]["offset"] == "10"


@respx.mock
def test_search_stops_when_page_is_empty(client):
    route = respx.get(host=HOST, path="/v1/search").mock(return_value=httpx.Response(200, json={"tracks": {"items": []}}))
    assert client.search_tracks("x", pages=3) == []
    assert route.call_count == 1


@respx.mock
def test_retries_429_with_retry_after(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"genres": ["rock"]}),
    ])
    assert client.artist_genres("ar") == ["rock"]
    assert client.sleeps == [2.0]


@respx.mock
def test_401_refreshes_token_once(client):
    route = respx.get(host=HOST, path="/v1/artists/ar").mock(side_effect=[
        httpx.Response(401), httpx.Response(200, json={"genres": []}),
    ])
    client.artist_genres("ar")
    assert client.auth.refreshes == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer t2"


@respx.mock
def test_error_after_retries_raises_spotify_error(client):
    respx.get(host=HOST, path="/v1/artists/ar").mock(return_value=httpx.Response(503))
    with pytest.raises(SpotifyError):
        client.artist_genres("ar")
    assert len(client.sleeps) == 3


@respx.mock
def test_create_playlist_truncates_and_strips_newlines(client):
    route = respx.post(host=HOST, path="/v1/me/playlists").mock(return_value=httpx.Response(
        201, json={"id": "new", "external_urls": {"spotify": "https://open.spotify.com/playlist/new"}}
    ))
    pid, url = client.create_playlist("x" * 150, "linha1\nlinha2" + "y" * 400)
    body = json.loads(route.calls.last.request.content)
    assert (pid, url) == ("new", "https://open.spotify.com/playlist/new")
    assert len(body["name"]) == 100
    assert "\n" not in body["description"] and len(body["description"]) == 300
    assert body["public"] is False


@respx.mock
def test_replace_items_puts_first_100_then_posts_rest(client):
    put = respx.put(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"snapshot_id": "s"}))
    post = respx.post(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(201, json={"snapshot_id": "s"}))
    uris = [f"spotify:track:{i}" for i in range(250)]
    client.replace_items("p1", uris)
    assert json.loads(put.calls.last.request.content)["uris"] == uris[:100]
    assert [len(json.loads(c.request.content)["uris"]) for c in post.calls] == [100, 50]


@respx.mock
def test_replace_items_with_empty_list_clears_playlist(client):
    put = respx.put(host=HOST, path="/v1/playlists/p1/items").mock(return_value=httpx.Response(200, json={"snapshot_id": "s"}))
    client.replace_items("p1", [])
    assert json.loads(put.calls.last.request.content)["uris"] == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/spotify/tests/test_client.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.spotify.client'`

- [ ] **Step 3: Implementar `services/spotify/client.py`**

```python
"""Cliente fino da Web API do Spotify, já no formato de fev/2026 (/items, POST /me/playlists, busca limit 10)."""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol

import httpx

from contracts.errors import ExternalServiceError
from contracts.models import Artist, PlaylistSummary, Track

API = "https://api.spotify.com/v1"
SEARCH_PAGE = 10
WRITE_BATCH = 100


class SpotifyError(ExternalServiceError):
    pass


class _Auth(Protocol):
    def access_token(self) -> str: ...
    def refresh(self) -> Any: ...


def parse_track(obj: dict[str, Any]) -> Track:
    return Track(
        id=obj["id"],
        uri=obj["uri"],
        name=obj["name"],
        artists=[Artist(id=a.get("id") or "", name=a["name"]) for a in obj.get("artists", [])],
        album=(obj.get("album") or {}).get("name", ""),
        duration_ms=obj.get("duration_ms", 0),
    )


def _clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


class SpotifyClient:
    def __init__(
        self, auth: _Auth, http: httpx.Client, sleep: Callable[[float], None] = time.sleep, max_retries: int = 3
    ) -> None:
        self.auth = auth
        self.http = http
        self.sleep = sleep
        self.max_retries = max_retries
        self._me: str | None = None

    def _request(self, method: str, path_or_url: str, **kwargs: Any) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
        refreshed = False
        attempt = 0
        while True:
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            try:
                response = self.http.request(method, url, headers=headers, timeout=20, **kwargs)
            except httpx.HTTPError as err:
                raise SpotifyError(f"Sem conexão com o Spotify: {err}") from err
            if response.status_code == 401 and not refreshed:
                self.auth.refresh()
                refreshed = True
                continue
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.max_retries:
                wait = float(response.headers.get("Retry-After", 2**attempt))
                self.sleep(min(wait, 30.0))
                attempt += 1
                continue
            break
        if response.status_code >= 400:
            raise SpotifyError(f"Spotify {method} {url} falhou com {response.status_code}: {response.text[:200]}")
        return response

    def _pages(self, first: str) -> list[dict[str, Any]]:
        url: str | None = first
        items: list[dict[str, Any]] = []
        while url:
            data = self._request("GET", url).json()
            items.extend(data.get("items", []))
            url = data.get("next")
        return items

    def me_id(self) -> str:
        if self._me is None:
            self._me = self._request("GET", "/me").json()["id"]
        return self._me

    def my_playlists(self) -> list[PlaylistSummary]:
        me = self.me_id()
        out: list[PlaylistSummary] = []
        for p in self._pages("/me/playlists?limit=50"):
            if not p:
                continue
            owner = p["owner"]["id"]
            if owner != me and not p.get("collaborative"):
                continue
            total = (p.get("items") or p.get("tracks") or {}).get("total", 0)
            out.append(PlaylistSummary(id=p["id"], name=p["name"], total=total, owner_id=owner))
        return out

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        tracks: list[Track] = []
        for entry in self._pages(f"/playlists/{playlist_id}/items?limit=50&additional_types=track"):
            obj = entry.get("item") or entry.get("track")
            if not obj or entry.get("is_local") or obj.get("type", "track") != "track" or not obj.get("id"):
                continue
            tracks.append(parse_track(obj))
        return tracks

    def search_tracks(self, query: str, pages: int = 1) -> list[Track]:
        tracks: list[Track] = []
        for page in range(pages):
            params = {"q": query, "type": "track", "limit": SEARCH_PAGE, "offset": page * SEARCH_PAGE}
            items = self._request("GET", "/search", params=params).json().get("tracks", {}).get("items", [])
            if not items:
                break
            tracks.extend(parse_track(obj) for obj in items if obj and obj.get("id"))
        return tracks

    def artist_genres(self, artist_id: str) -> list[str]:
        return list(self._request("GET", f"/artists/{artist_id}").json().get("genres", []))

    def create_playlist(self, name: str, description: str) -> tuple[str, str]:
        body = {"name": _clean(name, 100), "description": _clean(description, 300), "public": False}
        data = self._request("POST", "/me/playlists", json=body).json()
        url = data.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/playlist/{data['id']}"
        return data["id"], url

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        self._request("PUT", f"/playlists/{playlist_id}/items", json={"uris": uris[:WRITE_BATCH]})
        rest = uris[WRITE_BATCH:]
        for start in range(0, len(rest), WRITE_BATCH):
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": rest[start : start + WRITE_BATCH]})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/spotify -v`
Expected: 18 passed

- [ ] **Step 5: `services/spotify/README.md`**

```markdown
# spotify

Login OAuth PKCE (`auth.py`) e cliente da Web API (`client.py`) já nas regras de fevereiro de 2026:

- itens de playlist em `/playlists/{id}/items`, faixa em `item`;
- criar playlist com `POST /me/playlists` (privada por padrão);
- busca com no máximo 10 resultados por página;
- só lê playlists próprias ou colaborativas;
- sem endpoints em lote: gênero é buscado artista por artista (e cacheado pelo `enrichment`).

Retry: 429 e 5xx respeitam `Retry-After` até 3 vezes; 401 renova o token uma vez.

Testes: `uv run pytest services/spotify` (HTTP simulado com respx, sem rede).
```

- [ ] **Step 6: Commit**

```bash
git add services/spotify
git commit -m "feat(spotify): cliente da Web API com paginação, retry e escrita em lotes"
```

---

### Task 7: enrichment, cache SQLite e ReccoBeats

**Files:**
- Create: `services/enrichment/__init__.py`, `services/enrichment/cache.py`, `services/enrichment/reccobeats.py`
- Test: `services/enrichment/tests/test_cache.py`, `services/enrichment/tests/test_reccobeats.py`

**Interfaces:**
- Consumes: nada além de pydantic/httpx
- Produces: `services.enrichment.cache.AudioFeatures(tempo: float | None, energy: float | None)` (pydantic), `EnrichmentCache(path: Path | str, clock=time.time)` com `NEGATIVE_TTL`, `get_audio(ids: list[str]) -> dict[str, AudioFeatures | None]` (chave ausente = não cacheado; valor `None` = sabidamente sem dado), `put_audio(found: dict[str, AudioFeatures], missing: list[str])`, `get_genres(artist_id: str) -> list[str] | None`, `put_genres(artist_id: str, genres: list[str], source: str)`; `services.enrichment.reccobeats.RECCO_API`, `BATCH = 40`, `FeaturesResult(found: dict[str, AudioFeatures], failed: list[str])`, `ReccoBeatsClient(http, sleep=time.sleep, max_retries=3)` com `audio_features(spotify_ids: list[str]) -> FeaturesResult`.

- [ ] **Step 1: Testes que falham**

`services/enrichment/tests/test_cache.py`:
```python
from services.enrichment.cache import AudioFeatures, EnrichmentCache


def test_audio_hits_misses_and_uncached(tmp_path):
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: 1000.0)
    cache.put_audio({"a": AudioFeatures(tempo=120.0, energy=0.5)}, missing=["b"])
    got = cache.get_audio(["a", "b", "c"])
    assert got["a"].tempo == 120.0
    assert got["b"] is None
    assert "c" not in got


def test_negative_audio_entries_expire(tmp_path):
    clock = {"now": 0.0}
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: clock["now"])
    cache.put_audio({}, missing=["b"])
    clock["now"] = EnrichmentCache.NEGATIVE_TTL + 1
    assert "b" not in cache.get_audio(["b"])


def test_genres_round_trip_and_empty_expires(tmp_path):
    clock = {"now": 0.0}
    cache = EnrichmentCache(tmp_path / "c.sqlite", clock=lambda: clock["now"])
    assert cache.get_genres("ar") is None
    cache.put_genres("ar", ["rock"], "spotify")
    cache.put_genres("empty", [], "lastfm")
    assert cache.get_genres("ar") == ["rock"]
    assert cache.get_genres("empty") == []
    clock["now"] = EnrichmentCache.NEGATIVE_TTL + 1
    assert cache.get_genres("ar") == ["rock"]
    assert cache.get_genres("empty") is None
```

`services/enrichment/tests/test_reccobeats.py`:
```python
import httpx
import respx

from services.enrichment.reccobeats import ReccoBeatsClient

HOST = "api.reccobeats.com"


def _item(sid, tempo):
    return {"id": "uuid", "href": f"https://open.spotify.com/track/{sid}", "tempo": tempo, "energy": 0.8}


@respx.mock
def test_parses_spotify_id_from_href_and_skips_unknown():
    respx.get(host=HOST, path="/v1/audio-features").mock(
        return_value=httpx.Response(200, json={"content": [_item("a", 128.4)]})
    )
    result = ReccoBeatsClient(httpx.Client()).audio_features(["a", "b"])
    assert result.found["a"].tempo == 128.4
    assert "b" not in result.found
    assert result.failed == []


@respx.mock
def test_chunks_ids_by_40():
    route = respx.get(host=HOST, path="/v1/audio-features").mock(return_value=httpx.Response(200, json={"content": []}))
    ReccoBeatsClient(httpx.Client()).audio_features([f"id{i}" for i in range(41)])
    sizes = [len(c.request.url.params["ids"].split(",")) for c in route.calls]
    assert sizes == [40, 1]


@respx.mock
def test_retries_429_then_marks_chunk_failed_on_persistent_error():
    sleeps = []
    respx.get(host=HOST, path="/v1/audio-features").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"content": [_item("a", 100)]}),
        httpx.Response(500), httpx.Response(500), httpx.Response(500), httpx.Response(500),
    ])
    client = ReccoBeatsClient(httpx.Client(), sleep=sleeps.append)
    ids = [f"x{i}" for i in range(39)] + ["a", "late"]
    result = client.audio_features(ids)
    assert result.found["a"].tempo == 100
    assert result.failed == ["late"]
    assert sleeps[0] == 1.0


@respx.mock
def test_network_error_marks_chunk_failed():
    respx.get(host=HOST, path="/v1/audio-features").mock(side_effect=httpx.ConnectError("offline"))
    result = ReccoBeatsClient(httpx.Client(), sleep=lambda s: None).audio_features(["a"])
    assert result.failed == ["a"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/enrichment -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.enrichment'`

- [ ] **Step 3: Implementar**

`services/enrichment/__init__.py`: `"""Enriquecimento de faixas: BPM (ReccoBeats) e gênero (Spotify + Last.fm), com cache SQLite."""`

`services/enrichment/cache.py`:
```python
"""Cache SQLite de BPM e gêneros. Resultado negativo também é cacheado, mas expira em 7 dias."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel


class AudioFeatures(BaseModel):
    tempo: float | None = None
    energy: float | None = None


class EnrichmentCache:
    NEGATIVE_TTL = 7 * 24 * 3600

    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.clock = clock
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS audio "
                "(track_id TEXT PRIMARY KEY, tempo REAL, energy REAL, found INTEGER, fetched_at REAL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS genres (artist_id TEXT PRIMARY KEY, genres TEXT, source TEXT, fetched_at REAL)"
            )

    def _fresh(self, found: bool, fetched_at: float) -> bool:
        return found or self.clock() - fetched_at <= self.NEGATIVE_TTL

    def get_audio(self, ids: list[str]) -> dict[str, AudioFeatures | None]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self.lock:
            rows = self.db.execute(
                f"SELECT track_id, tempo, energy, found, fetched_at FROM audio WHERE track_id IN ({marks})", ids
            ).fetchall()
        out: dict[str, AudioFeatures | None] = {}
        for track_id, tempo, energy, found, fetched_at in rows:
            if self._fresh(bool(found), fetched_at):
                out[track_id] = AudioFeatures(tempo=tempo, energy=energy) if found else None
        return out

    def put_audio(self, found: dict[str, AudioFeatures], missing: list[str]) -> None:
        now = self.clock()
        rows = [(tid, f.tempo, f.energy, 1, now) for tid, f in found.items()]
        rows += [(tid, None, None, 0, now) for tid in missing]
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO audio VALUES (?, ?, ?, ?, ?)", rows)

    def get_genres(self, artist_id: str) -> list[str] | None:
        with self.lock:
            row = self.db.execute("SELECT genres, fetched_at FROM genres WHERE artist_id = ?", (artist_id,)).fetchone()
        if row is None:
            return None
        genres = json.loads(row[0])
        return genres if self._fresh(bool(genres), row[1]) else None

    def put_genres(self, artist_id: str, genres: list[str], source: str) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO genres VALUES (?, ?, ?, ?)", (artist_id, json.dumps(genres), source, self.clock())
            )
```

Nota: SQLite limita parâmetros por query (32766 nas versões atuais); playlists de até alguns milhares de faixas cabem. Se a Task 16 revelar playlists maiores, fatiar `get_audio` em blocos de 500.

`services/enrichment/reccobeats.py`:
```python
"""Cliente da ReccoBeats: audio features (BPM, energia) a partir de IDs do Spotify. Sem autenticação."""

from __future__ import annotations

import time
from typing import Callable

import httpx
from pydantic import BaseModel

from services.enrichment.cache import AudioFeatures

RECCO_API = "https://api.reccobeats.com/v1"
BATCH = 40


class FeaturesResult(BaseModel):
    found: dict[str, AudioFeatures]
    failed: list[str]


class ReccoBeatsClient:
    def __init__(self, http: httpx.Client, sleep: Callable[[float], None] = time.sleep, max_retries: int = 3) -> None:
        self.http = http
        self.sleep = sleep
        self.max_retries = max_retries

    def _fetch(self, chunk: list[str]) -> list[dict] | None:
        for attempt in range(self.max_retries + 1):
            try:
                response = self.http.get(f"{RECCO_API}/audio-features", params={"ids": ",".join(chunk)}, timeout=20)
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code == 200:
                return response.json().get("content", [])
            if attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After") if response is not None else None
                self.sleep(min(float(retry_after or 2**attempt), 30.0))
        return None

    def audio_features(self, spotify_ids: list[str]) -> FeaturesResult:
        found: dict[str, AudioFeatures] = {}
        failed: list[str] = []
        for start in range(0, len(spotify_ids), BATCH):
            chunk = spotify_ids[start : start + BATCH]
            content = self._fetch(chunk)
            if content is None:
                failed.extend(chunk)
                continue
            for item in content:
                spotify_id = str(item.get("href", "")).rstrip("/").rsplit("/", 1)[-1]
                if spotify_id in chunk:
                    found[spotify_id] = AudioFeatures(tempo=item.get("tempo"), energy=item.get("energy"))
        return FeaturesResult(found=found, failed=failed)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/enrichment -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add services/enrichment
git commit -m "feat(enrichment): cache SQLite e cliente ReccoBeats para BPM"
```

---

### Task 8: enrichment, gêneros (Spotify + Last.fm) e Enricher

**Files:**
- Create: `services/enrichment/genres.py`, `services/enrichment/enricher.py`, `services/enrichment/README.md`
- Test: `services/enrichment/tests/test_genres.py`, `services/enrichment/tests/test_enricher.py`

**Interfaces:**
- Consumes: Task 7; `contracts.models.Artist, Track, EnrichedTrack`; `contracts.errors.ExternalServiceError`
- Produces: `services.enrichment.genres.LASTFM_API`, `is_junk_tag(tag: str) -> bool`, `LastFmClient(api_key: str, http)` com `artist_tags(artist_name: str) -> list[str]` (até 3), `GenreResolver(spotify_genres: Callable[[str], list[str]], lastfm: LastFmClient | None, cache: EnrichmentCache)` com `genres_for(artist: Artist) -> list[str]`; `services.enrichment.enricher.Enricher(recco: ReccoBeatsClient, genres: GenreResolver, cache: EnrichmentCache)` com `enrich(tracks: list[Track]) -> list[EnrichedTrack]` (satisfaz `EnricherPort`).

- [ ] **Step 1: Testes que falham**

`services/enrichment/tests/test_genres.py`:
```python
import httpx
import pytest
import respx

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import Artist
from services.enrichment.cache import EnrichmentCache
from services.enrichment.genres import GenreResolver, LastFmClient, is_junk_tag


@pytest.mark.parametrize("tag", ["seen live", "90s", "1980s", "brazilian", "favorites"])
def test_junk_tags(tag):
    assert is_junk_tag(tag)


def test_real_genre_is_not_junk():
    assert not is_junk_tag("indie rock")


@respx.mock
def test_lastfm_filters_junk_low_count_and_keeps_top_3():
    respx.get(host="ws.audioscrobbler.com").mock(return_value=httpx.Response(200, json={"toptags": {"tag": [
        {"name": "Seen Live", "count": 100}, {"name": "MPB", "count": 90}, {"name": "Bossa Nova", "count": 60},
        {"name": "samba", "count": 40}, {"name": "jazz", "count": 30}, {"name": "rare", "count": 5},
    ]}}))
    assert LastFmClient("k", httpx.Client()).artist_tags("Caetano") == ["mpb", "bossa nova", "samba"]


@respx.mock
def test_lastfm_error_payload_returns_empty():
    respx.get(host="ws.audioscrobbler.com").mock(return_value=httpx.Response(200, json={"error": 6, "message": "not found"}))
    assert LastFmClient("k", httpx.Client()).artist_tags("???") == []


class FakeLastFm:
    def __init__(self, tags):
        self.tags = tags

    def artist_tags(self, name):
        return self.tags


def test_resolver_uses_spotify_first_and_caches(tmp_path):
    calls = []
    resolver = GenreResolver(lambda aid: calls.append(aid) or ["rock"], FakeLastFm(["x"]), EnrichmentCache(tmp_path / "c.sqlite"))
    artist = Artist(id="ar", name="Banda")
    assert resolver.genres_for(artist) == ["rock"]
    assert resolver.genres_for(artist) == ["rock"]
    assert calls == ["ar"]


def test_resolver_falls_back_to_lastfm_when_spotify_empty_or_fails(tmp_path):
    def failing(aid):
        raise ExternalServiceError("503")

    lastfm = FakeLastFm(["mpb"])
    cache = EnrichmentCache(tmp_path / "c.sqlite")
    assert GenreResolver(lambda aid: [], lastfm, cache).genres_for(Artist(id="a1", name="A")) == ["mpb"]
    assert GenreResolver(failing, lastfm, cache).genres_for(Artist(id="a2", name="B")) == ["mpb"]


def test_resolver_propagates_auth_required(tmp_path):
    def needs_login(aid):
        raise AuthRequired("login")

    with pytest.raises(AuthRequired):
        GenreResolver(needs_login, None, EnrichmentCache(tmp_path / "c.sqlite")).genres_for(Artist(id="a", name="A"))
```

`services/enrichment/tests/test_enricher.py`:
```python
from contracts.models import Artist, Track
from services.enrichment.cache import AudioFeatures, EnrichmentCache
from services.enrichment.enricher import Enricher
from services.enrichment.reccobeats import FeaturesResult


def _t(tid, artist="ar"):
    return Track(id=tid, uri=f"spotify:track:{tid}", name=tid, artists=[Artist(id=artist, name=artist)])


class FakeRecco:
    def __init__(self):
        self.asked = []

    def audio_features(self, ids):
        self.asked.append(list(ids))
        return FeaturesResult(found={"a": AudioFeatures(tempo=120, energy=0.7)}, failed=["c"])


class FakeGenres:
    def genres_for(self, artist):
        return ["rock"] if artist.id == "ar" else []


def test_enrich_merges_features_and_genres_and_caches_misses(tmp_path):
    recco = FakeRecco()
    enricher = Enricher(recco, FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite"))
    out = enricher.enrich([_t("a"), _t("b", "other"), _t("c"), _t("a")])
    assert [(e.track.id, e.tempo, e.genres) for e in out] == [
        ("a", 120, ["rock"]), ("b", None, []), ("c", None, ["rock"]), ("a", 120, ["rock"]),
    ]
    assert recco.asked == [["a", "b", "c"]]
    # "b" virou negativo no cache; "c" falhou e NÃO foi cacheado, então é pedido de novo.
    enricher.enrich([_t("a"), _t("b"), _t("c")])
    assert recco.asked[-1] == ["c"]


def test_track_without_artists_gets_no_genres(tmp_path):
    track = Track(id="z", uri="spotify:track:z", name="z", artists=[])
    out = Enricher(FakeRecco(), FakeGenres(), EnrichmentCache(tmp_path / "c.sqlite")).enrich([track])
    assert out[0].genres == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/enrichment -v`
Expected: FAIL com `ModuleNotFoundError` para `genres` e `enricher`

- [ ] **Step 3: Implementar**

`services/enrichment/genres.py`:
```python
"""Gênero por artista: Spotify primeiro, tags do Last.fm quando o Spotify vem vazio ou falha."""

from __future__ import annotations

import re
from typing import Callable

import httpx

from contracts.errors import ExternalServiceError
from contracts.models import Artist
from services.enrichment.cache import EnrichmentCache

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
MIN_TAG_COUNT = 10
_JUNK = {
    "seen live", "favorites", "favourites", "favorite", "albums i own", "love", "awesome", "beautiful",
    "male vocalists", "female vocalists", "spotify", "all", "brazilian", "brazil", "brasil", "american",
    "british", "usa", "uk", "under 2000 listeners",
}
_DECADE = re.compile(r"^(\d0s|\d{4}s)$")


def is_junk_tag(tag: str) -> bool:
    normalized = tag.lower().strip()
    return normalized in _JUNK or bool(_DECADE.match(normalized))


class LastFmClient:
    def __init__(self, api_key: str, http: httpx.Client) -> None:
        self.api_key = api_key
        self.http = http

    def artist_tags(self, artist_name: str) -> list[str]:
        params = {
            "method": "artist.gettoptags", "artist": artist_name, "api_key": self.api_key,
            "format": "json", "autocorrect": 1,
        }
        try:
            response = self.http.get(LASTFM_API, params=params, timeout=15)
        except httpx.HTTPError as err:
            raise ExternalServiceError(f"Last.fm indisponível: {err}") from err
        if response.status_code != 200:
            raise ExternalServiceError(f"Last.fm respondeu {response.status_code}")
        tags = response.json().get("toptags", {}).get("tag", [])
        names = [
            t["name"].lower().strip()
            for t in tags
            if int(t.get("count", 0)) >= MIN_TAG_COUNT and not is_junk_tag(t["name"])
        ]
        return names[:3]


class GenreResolver:
    def __init__(
        self, spotify_genres: Callable[[str], list[str]], lastfm: LastFmClient | None, cache: EnrichmentCache
    ) -> None:
        self.spotify_genres = spotify_genres
        self.lastfm = lastfm
        self.cache = cache

    def genres_for(self, artist: Artist) -> list[str]:
        cached = self.cache.get_genres(artist.id)
        if cached is not None:
            return cached
        source = "spotify"
        try:
            genres = self.spotify_genres(artist.id) if artist.id else []
        except ExternalServiceError:
            genres = []
        if not genres and self.lastfm is not None:
            source = "lastfm"
            try:
                genres = self.lastfm.artist_tags(artist.name)
            except ExternalServiceError:
                genres = []
        self.cache.put_genres(artist.id, genres, source)
        return genres
```

`services/enrichment/enricher.py`:
```python
"""Junta BPM e gênero em EnrichedTrack. Falha de fonte externa vira 'sem dado', nunca derruba o fluxo."""

from __future__ import annotations

from contracts.models import EnrichedTrack, Track
from services.enrichment.cache import EnrichmentCache
from services.enrichment.genres import GenreResolver
from services.enrichment.reccobeats import ReccoBeatsClient


class Enricher:
    def __init__(self, recco: ReccoBeatsClient, genres: GenreResolver, cache: EnrichmentCache) -> None:
        self.recco = recco
        self.genres = genres
        self.cache = cache

    def enrich(self, tracks: list[Track]) -> list[EnrichedTrack]:
        ids = list(dict.fromkeys(t.id for t in tracks))
        features = self.cache.get_audio(ids)
        to_fetch = [i for i in ids if i not in features]
        if to_fetch:
            result = self.recco.audio_features(to_fetch)
            failed = set(result.failed)
            missing = [i for i in to_fetch if i not in result.found and i not in failed]
            self.cache.put_audio(result.found, missing)
            features.update(result.found)
        out: list[EnrichedTrack] = []
        for track in tracks:
            audio = features.get(track.id)
            genres = self.genres.genres_for(track.artists[0]) if track.artists else []
            out.append(
                EnrichedTrack(
                    track=track,
                    tempo=audio.tempo if audio else None,
                    energy=audio.energy if audio else None,
                    genres=genres,
                )
            )
        return out
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/enrichment -v`
Expected: 20 passed (7 da Task 7 + 11 genres + 2 enricher)

- [ ] **Step 5: `services/enrichment/README.md`**

```markdown
# enrichment

Completa cada faixa com BPM, energia e gêneros.

- BPM e energia: ReccoBeats (`GET /v1/audio-features?ids=`, até 40 IDs do Spotify, sem login). O Spotify removeu esse dado da API em nov/2024.
- Gênero: `GET /artists/{id}` do Spotify (artista principal). Se vier vazio ou falhar, tags do Last.fm (`LASTFM_API_KEY`), filtrando tags que não são gênero ("seen live", "90s").
- Cache SQLite em `data/cache.sqlite`. Acertos não expiram; "sem dado" expira em 7 dias; falha de rede não é cacheada.

Testes: `uv run pytest services/enrichment`
```

- [ ] **Step 6: Commit**

```bash
git add services/enrichment
git commit -m "feat(enrichment): gêneros via Spotify com fallback Last.fm e Enricher"
```

---

### Task 9: llm, runner do Claude Code e saída estruturada

**Files:**
- Create: `services/llm/__init__.py`, `services/llm/runner.py`, `services/llm/structured.py`
- Test: `services/llm/tests/test_runner.py`, `services/llm/tests/test_structured.py`

**Interfaces:**
- Consumes: `contracts.errors.ExternalServiceError`
- Produces: `services.llm.runner.LLMError(ExternalServiceError)`, `RunResult(data: dict, latency_s: float, cost_usd: float)`, `ClaudeRunner(model="opus", binary: str | None = None, cwd: Path | str | None = None, timeout: float = 180, run=subprocess.run, clock=time.monotonic)` com `available() -> bool` e `run(system: str, prompt: str, schema: dict) -> RunResult`; `services.llm.structured.inline_schema(model_cls) -> dict`, `call_structured(runner, system: str, prompt: str, model_cls: type[T]) -> tuple[T, RunResult]`.

**Conceito:** o app chama o Claude Code em modo headless (`claude -p`), como se fosse um comando de terminal. `--json-schema` obriga a resposta a seguir um formato, que chega pronta em `structured_output`. `--system-prompt` troca o prompt padrão do Claude Code (que é enorme e voltado a programação) pelo nosso, o que corta custo: medido em 18/09/2026, US$ 0,03 por chamada contra US$ 0,10 com o prompt padrão. `--tools ""` desliga ferramentas: o agente só pensa e responde, não mexe em arquivos. O runner roda numa pasta temporária FORA do projeto: o Claude Code procura `CLAUDE.md` subindo as pastas a partir do `cwd`, e o `CLAUDE.md` deste repositório (40 KB) iria para toda chamada.

- [ ] **Step 1: Testes que falham**

`services/llm/tests/test_runner.py`:
```python
import json
import subprocess

import pytest

from services.llm.runner import ClaudeRunner, LLMError


def _completed(payload, returncode=0, stderr=""):
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class Recorder:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _runner(result, tmp_path):
    recorder = Recorder(result)
    return ClaudeRunner(binary="claude", cwd=tmp_path, run=recorder), recorder


def test_run_builds_headless_command_and_returns_structured_output(tmp_path):
    ok = _completed({"is_error": False, "structured_output": {"x": 1}, "total_cost_usd": 0.1})
    runner, recorder = _runner(ok, tmp_path)
    result = runner.run("SYS", "PROMPT", {"type": "object"})
    cmd, kwargs = recorder.calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert kwargs["input"] == "PROMPT"
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["cwd"] == str(tmp_path)
    assert result.data == {"x": 1}
    assert result.cost_usd == 0.1


@pytest.mark.parametrize(
    "result",
    [
        _completed({}, returncode=1, stderr="boom"),
        _completed("not json"),
        _completed({"is_error": True, "result": "limite atingido"}),
        _completed({"is_error": False, "result": "texto sem schema"}),
        subprocess.TimeoutExpired(cmd="claude", timeout=1),
    ],
)
def test_failures_raise_llm_error(result, tmp_path):
    runner, _ = _runner(result, tmp_path)
    with pytest.raises(LLMError):
        runner.run("s", "p", {})


def test_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("services.llm.runner.shutil.which", lambda name: None)
    with pytest.raises(LLMError, match="claude"):
        ClaudeRunner(cwd=tmp_path).run("s", "p", {})


def test_available_runs_version(tmp_path):
    recorder = Recorder(subprocess.CompletedProcess([], 0, "2.1.0", ""))
    assert ClaudeRunner(binary="claude", cwd=tmp_path, run=recorder).available()
    assert recorder.calls[0][0] == ["claude", "--version"]


def test_available_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("services.llm.runner.shutil.which", lambda name: None)
    assert not ClaudeRunner(cwd=tmp_path).available()
```

`services/llm/tests/test_structured.py`:
```python
import json

import pytest
from pydantic import BaseModel

from services.llm.runner import LLMError, RunResult
from services.llm.structured import call_structured, inline_schema


class Inner(BaseModel):
    title: str


class Outer(BaseModel):
    items: list[Inner]
    note: str | None = None


def test_inline_schema_removes_refs_and_closes_objects():
    schema = inline_schema(Outer)
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    inner = schema["properties"]["items"]["items"]
    assert inner["additionalProperties"] is False
    # Campo chamado "title" é propriedade de verdade e precisa sobreviver; só o metadado "title" some.
    assert "title" in inner["properties"]
    assert "title" not in schema


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def run(self, system, prompt, schema):
        self.prompts.append(prompt)
        return RunResult(data=self.outputs.pop(0), latency_s=1.0, cost_usd=0.01)


def test_call_structured_validates_output():
    model, run = call_structured(FakeRunner([{"items": [{"title": "a"}]}]), "s", "p", Outer)
    assert model.items[0].title == "a"
    assert run.cost_usd == 0.01


def test_retries_once_with_validation_error_in_prompt():
    runner = FakeRunner([{"items": "ruim"}, {"items": []}])
    model, _ = call_structured(runner, "s", "p", Outer)
    assert model.items == []
    assert len(runner.prompts) == 2
    assert "inválida" in runner.prompts[1]


def test_gives_up_after_second_invalid_output():
    with pytest.raises(LLMError):
        call_structured(FakeRunner([{"items": "ruim"}, {"items": "ruim"}]), "s", "p", Outer)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/llm -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.llm'`

- [ ] **Step 3: Implementar**

`services/llm/__init__.py`: `"""Serviço de LLM: chama o Claude Code local em modo headless. Nunca uma API paga."""`

`services/llm/runner.py`:
```python
"""Executa `claude -p` com saída estruturada e devolve o JSON validado pelo próprio Claude Code."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from contracts.errors import ExternalServiceError


class LLMError(ExternalServiceError):
    pass


@dataclass(frozen=True)
class RunResult:
    data: dict[str, Any]
    latency_s: float
    cost_usd: float


class ClaudeRunner:
    def __init__(
        self,
        model: str = "opus",
        binary: str | None = None,
        cwd: Path | str | None = None,
        timeout: float = 180.0,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.binary = binary
        self.cwd = Path(cwd) if cwd else Path(tempfile.gettempdir()) / "playlist-agent-llm"
        self.timeout = timeout
        self._run = run
        self.clock = clock

    def _exe(self) -> str:
        exe = self.binary or shutil.which("claude")
        if not exe:
            raise LLMError("Comando `claude` não encontrado no PATH. Instale o Claude Code e faça login (`claude`).")
        return exe

    def available(self) -> bool:
        try:
            proc = self._run([self._exe(), "--version"], capture_output=True, text=True, timeout=30)
        except (LLMError, OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult:
        cmd = [
            self._exe(), "-p",
            "--model", self.model,
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--system-prompt", system,
            "--tools", "",
        ]
        self.cwd.mkdir(parents=True, exist_ok=True)
        start = self.clock()
        try:
            proc = self._run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout, cwd=str(self.cwd),
            )
        except subprocess.TimeoutExpired as err:
            raise LLMError(f"O Claude Code não respondeu em {self.timeout:.0f}s.") from err
        latency = self.clock() - start
        if proc.returncode != 0:
            raise LLMError(f"Claude Code saiu com código {proc.returncode}: {(proc.stderr or '')[:300]}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as err:
            raise LLMError("Saída do Claude Code não é JSON.") from err
        if payload.get("is_error") or "structured_output" not in payload:
            raise LLMError(f"Claude Code não devolveu resposta estruturada: {str(payload.get('result', ''))[:300]}")
        return RunResult(
            data=payload["structured_output"], latency_s=latency, cost_usd=float(payload.get("total_cost_usd") or 0.0)
        )
```

`services/llm/structured.py`:
```python
"""Converte modelos pydantic em JSON Schema autocontido e valida a resposta, com uma nova tentativa."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from services.llm.runner import LLMError, RunResult

T = TypeVar("T", bound=BaseModel)


class _Runner(Protocol):
    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult: ...


def inline_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("title", "default"):
                continue
            if key == "properties":
                out[key] = {name: resolve(sub) for name, sub in value.items()}
            else:
                out[key] = resolve(value)
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out

    return resolve(schema)


def call_structured(runner: _Runner, system: str, prompt: str, model_cls: type[T]) -> tuple[T, RunResult]:
    schema = inline_schema(model_cls)
    result = runner.run(system, prompt, schema)
    try:
        return model_cls.model_validate(result.data), result
    except ValidationError as first:
        retry = f"{prompt}\n\nSua resposta anterior foi inválida:\n{first}\nResponda de novo seguindo o schema e as regras."
        result = runner.run(system, retry, schema)
        try:
            return model_cls.model_validate(result.data), result
        except ValidationError as second:
            raise LLMError(f"Resposta do agente inválida mesmo após nova tentativa: {second}") from second
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/llm -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add services/llm
git commit -m "feat(llm): runner headless do Claude Code com saída estruturada e retry"
```

---

### Task 10: llm, prompts, API do agente e eval de intenção

**Files:**
- Create: `services/llm/prompts/interpret.md`, `services/llm/prompts/theme.md`, `services/llm/api.py`, `services/llm/README.md`
- Create: `services/llm/evals/__init__.py`, `services/llm/evals/scoring.py`, `services/llm/evals/intent_cases.jsonl`, `services/llm/evals/run_intent.py`
- Test: `services/llm/tests/test_api.py`, `services/llm/tests/test_scoring.py`

**Interfaces:**
- Consumes: Task 9; `contracts.models.Intent, ThemePlan`
- Produces: `services.llm.api.load_prompt(name: str) -> str`, `render_interpret_prompt(message, history, playlist_names) -> str`, `render_theme_prompt(theme, max_slots) -> str`, `ClaudeLLM(runner, tracer: Callable[..., None] | None = None)` com `interpret(...) -> Intent` e `plan_theme(theme, max_slots) -> ThemePlan` (satisfaz `LLMPort`; chama `tracer("llm", kind=..., latency_s=..., cost_usd=...)`); `services.llm.evals.scoring.score_intent(case: dict, intent: Intent) -> tuple[bool, str]`.

- [ ] **Step 1: Escrever os prompts**

`services/llm/prompts/interpret.md`:
```markdown
Você é o agente do Playlist Agent, um app pessoal que organiza as playlists do Spotify do usuário. Responda sempre em português do Brasil, com tom direto e amigável.

Tarefa: ler a nova mensagem do usuário, junto com o histórico da conversa e a lista de playlists dele, e devolver um objeto JSON no schema pedido.

Campos:
- action:
  - "reorganize": o usuário quer reordenar ou dividir uma playlist que ele JÁ TEM.
  - "discover": o usuário quer uma playlist NOVA montada com músicas escolhidas por um tema.
  - "chat": saudação, agradecimento, dúvida sobre o app ou qualquer coisa que não seja um pedido de playlist.
- reply: mensagem curta (1 a 3 frases) para o usuário. Em "reorganize" e "discover", apresente as opções. Em "chat", responda e, se fizer sentido, diga o que você sabe fazer.
- playlist_name: em "reorganize", o nome da playlist exatamente como aparece na lista do usuário. Se ele citar uma playlist que não está na lista, copie o nome que ele usou. Nos outros casos, null.
- question: preencha só quando faltar informação essencial para agir. Exemplos: "faz uma playlist" sem tema; "organiza minha playlist" sem dizer qual. Caso contrário, null.
- options: de 1 a 3 estratégias concretas. Lista vazia em "chat" ou quando houver question.

Estratégias disponíveis (campo kind):
- "bpm": ordena pelo andamento.
  - bpm_mode: "asc" (devagar para rápido), "desc" (rápido para devagar) ou "arc" (sobe até um pico no meio e desce).
  - normalize_tempo: true quando o estilo costuma ter batida em meio tempo (funk, trap, hip hop, reggaeton) ou quando o usuário fala em energia ou intensidade.
- "genre": agrupa por gênero.
  - genre_level: "family" (famílias amplas como Rock, Sertanejo, Pagode e samba) ou "subgenre" (rótulos finos como "indie rock").
  - genre_split: true para criar uma playlist por gênero; false para manter uma playlist só, com os gêneros em blocos.
- "theme": só em "discover".
  - theme: descreva o tema em uma frase, ex.: "músicas cujo título contém andares de um prédio, do térreo à cobertura".

Regras:
- Não invente estratégias fora da lista. Pedidos de ordem por energia, calma ou agitação viram "bpm".
- label: nome curto da opção (até 30 caracteres), ex.: "BPM crescente", "Arco de energia", "Uma playlist por gênero".
- description: uma frase explicando o resultado para o usuário.
- Se o pedido já define a estratégia, a primeira opção é exatamente ela; as outras são variações úteis.
- Pedidos que combinam critérios ("por gênero e depois por BPM") viram opções separadas; comece pela que o usuário citou primeiro.
```

`services/llm/prompts/theme.md`:
```markdown
Você monta playlists temáticas em que o TÍTULO de cada música contém uma palavra ou expressão de uma sequência. Exemplo: tema "prédio" gera os slots "Térreo", "Primeiro Andar", "Segundo Andar", ..., "Cobertura".

Devolva JSON no schema pedido:
- playlist_name: nome criativo e curto (até 60 caracteres), em português.
- description: uma frase divertida sobre a playlist (até 200 caracteres, sem quebra de linha).
- slots: a sequência em ordem, com no máximo o número de slots pedido. Cada slot tem:
  - label: rótulo mostrado ao usuário.
  - keywords: 1 a 4 formas de escrever o trecho que PRECISA aparecer no título, incluindo variações em inglês e com número. Ex.: ["Primeiro Andar", "1º Andar", "First Floor"]. Cada keyword tem de 1 a 3 palavras: o app só aceita uma música se o título contém a keyword inteira.
  - candidates: 3 a 5 músicas REAIS, disponíveis no Spotify, cujo título contém uma das keywords. Prefira músicas conhecidas. Não invente títulos: sugestão inexistente desperdiça uma busca.

A ordem dos slots é a ordem da playlist.
```

- [ ] **Step 2: Testes que falham**

`services/llm/tests/test_api.py`:
```python
from contracts.models import IntentAction
from services.llm.api import ClaudeLLM, load_prompt, render_interpret_prompt
from services.llm.runner import RunResult


class FakeRunner:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def run(self, system, prompt, schema):
        self.calls.append((system, prompt, schema))
        return RunResult(data=self.data, latency_s=2.5, cost_usd=0.03)


def test_prompts_exist_and_cover_contract_fields():
    assert "reorganize" in load_prompt("interpret") and "normalize_tempo" in load_prompt("interpret")
    assert "keywords" in load_prompt("theme") and "candidates" in load_prompt("theme")


def test_render_interpret_prompt_keeps_last_10_turns_and_lists_playlists():
    history = [("usuário", f"m{i}") for i in range(15)]
    prompt = render_interpret_prompt("nova", history, ["Treino", "Relax"])
    assert "- Treino\n- Relax" in prompt
    assert "m4" not in prompt and "m5" in prompt and "m14" in prompt
    assert prompt.endswith("nova")


def test_interpret_parses_intent_and_traces():
    events = []
    runner = FakeRunner({"action": "chat", "reply": "Oi!", "options": []})
    llm = ClaudeLLM(runner, tracer=lambda event, **f: events.append((event, f)))
    intent = llm.interpret("oi", [], [])
    assert intent.action is IntentAction.CHAT
    assert runner.calls[0][0] == load_prompt("interpret")
    assert events == [("llm", {"kind": "interpret", "latency_s": 2.5, "cost_usd": 0.03})]


def test_plan_theme_caps_slots():
    slots = [{"label": f"S{i}", "keywords": [f"k{i}"], "candidates": []} for i in range(8)]
    llm = ClaudeLLM(FakeRunner({"playlist_name": "P", "description": "d", "slots": slots}))
    plan = llm.plan_theme("prédio", max_slots=5)
    assert len(plan.slots) == 5
```

`services/llm/tests/test_scoring.py`:
```python
from contracts.models import Intent, StrategyChoice
from services.llm.evals.scoring import score_intent


def _intent(**kw):
    base = {"action": "reorganize", "reply": "ok", "playlist_name": "Treino", "options": []}
    base.update(kw)
    return Intent.model_validate(base)


def _opt(kind):
    return StrategyChoice(kind=kind, label="x", description="y")


def test_passes_when_action_playlist_and_kind_match():
    case = {"action": "reorganize", "playlist": "treino", "kinds": ["bpm"], "question": False}
    assert score_intent(case, _intent(options=[_opt("genre"), _opt("bpm")]))[0]


def test_fails_on_wrong_action():
    ok, why = score_intent({"action": "chat"}, _intent())
    assert not ok and "action" in why


def test_fails_on_missing_kind():
    assert not score_intent({"action": "reorganize", "kinds": ["bpm"]}, _intent(options=[_opt("genre")]))[0]


def test_question_expectations():
    assert not score_intent({"action": "reorganize", "question": True}, _intent())[0]
    assert score_intent({"action": "reorganize", "question": True}, _intent(question="Qual playlist?"))[0]
    assert not score_intent({"action": "reorganize", "question": False}, _intent(question="?"))[0]


def test_playlist_mismatch_fails():
    assert not score_intent({"action": "reorganize", "playlist": "Relax"}, _intent())[0]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest services/llm -v`
Expected: FAIL com `ModuleNotFoundError` para `services.llm.api` e `services.llm.evals.scoring`

- [ ] **Step 4: Implementar `services/llm/api.py`**

```python
"""API do agente para o resto do app: interpretar mensagens e planejar temas."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from contracts.models import Intent, ThemePlan
from services.llm.structured import call_structured

PROMPTS_DIR = Path(__file__).parent / "prompts"
HISTORY_TURNS = 10


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_interpret_prompt(message: str, history: list[tuple[str, str]], playlist_names: list[str]) -> str:
    names = "\n".join(f"- {n}" for n in playlist_names) or "(nenhuma)"
    turns = "\n".join(f"{role}: {text}" for role, text in history[-HISTORY_TURNS:]) or "(início da conversa)"
    return f"Playlists do usuário:\n{names}\n\nConversa até agora:\n{turns}\n\nNova mensagem do usuário:\n{message}"


def render_theme_prompt(theme: str, max_slots: int) -> str:
    return f"Tema: {theme}\nNúmero máximo de slots: {max_slots}"


def _no_trace(event: str, **fields: Any) -> None:
    return None


class ClaudeLLM:
    def __init__(self, runner: Any, tracer: Callable[..., None] | None = None) -> None:
        self.runner = runner
        self.tracer = tracer or _no_trace

    def _call(self, kind: str, prompt_name: str, prompt: str, model_cls: type) -> Any:
        model, run = call_structured(self.runner, load_prompt(prompt_name), prompt, model_cls)
        self.tracer("llm", kind=kind, latency_s=round(run.latency_s, 2), cost_usd=run.cost_usd)
        return model

    def interpret(self, message: str, history: list[tuple[str, str]], playlist_names: list[str]) -> Intent:
        return self._call("interpret", "interpret", render_interpret_prompt(message, history, playlist_names), Intent)

    def plan_theme(self, theme: str, max_slots: int) -> ThemePlan:
        plan: ThemePlan = self._call("theme", "theme", render_theme_prompt(theme, max_slots), ThemePlan)
        return plan.model_copy(update={"slots": plan.slots[:max_slots]})
```

- [ ] **Step 5: Implementar `services/llm/evals/scoring.py`** (e `services/llm/evals/__init__.py` com `"""Evals do serviço de LLM."""`)

```python
"""Pontuação determinística de um caso do eval de intenção."""

from __future__ import annotations

from typing import Any

from contracts.models import Intent


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def score_intent(case: dict[str, Any], intent: Intent) -> tuple[bool, str]:
    if intent.action.value != case["action"]:
        return False, f"action {intent.action.value} != {case['action']}"
    expects_question = case.get("question")
    if expects_question is True and not intent.question:
        return False, "esperava uma pergunta de esclarecimento"
    if expects_question is False and intent.question:
        return False, f"pergunta desnecessária: {intent.question}"
    playlist = case.get("playlist")
    if playlist and _norm(intent.playlist_name or "") != _norm(playlist):
        return False, f"playlist {intent.playlist_name!r} != {playlist!r}"
    kinds = case.get("kinds") or []
    if kinds and not any(o.kind.value in kinds for o in intent.options):
        return False, f"nenhuma opção do tipo {kinds}"
    return True, "ok"
```

- [ ] **Step 6: Casos do eval, `services/llm/evals/intent_cases.jsonl`** (playlists padrão do eval: Treino, Churrasco, Estudo, Rock Nacional, Festa 2025, Relax)

```jsonl
{"id": 1, "message": "organiza minha playlist Treino por BPM", "action": "reorganize", "playlist": "Treino", "kinds": ["bpm"], "question": false}
{"id": 2, "message": "quero a Treino começando devagar e acelerando", "action": "reorganize", "playlist": "Treino", "kinds": ["bpm"], "question": false}
{"id": 3, "message": "separa a Festa 2025 por gênero", "action": "reorganize", "playlist": "Festa 2025", "kinds": ["genre"], "question": false}
{"id": 4, "message": "divide a Churrasco em várias playlists por estilo", "action": "reorganize", "playlist": "Churrasco", "kinds": ["genre"], "question": false}
{"id": 5, "message": "faz uma playlist prédio, com músicas tipo primeiro andar, segundo andar", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 6, "message": "cria uma playlist com músicas que tenham os dias da semana no nome", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 7, "message": "quero uma playlist com cores no título das músicas", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 8, "message": "organiza a Estudo", "action": "reorganize", "playlist": "Estudo"}
{"id": 9, "message": "oi, tudo bem?", "action": "chat"}
{"id": 10, "message": "o que você consegue fazer?", "action": "chat"}
{"id": 11, "message": "ordena a Rock Nacional do mais rápido pro mais lento", "action": "reorganize", "playlist": "Rock Nacional", "kinds": ["bpm"], "question": false}
{"id": 12, "message": "coloca a Relax em ordem de bpm decrescente", "action": "reorganize", "playlist": "Relax", "kinds": ["bpm"], "question": false}
{"id": 13, "message": "quero que a playlist de treino tenha um pico de energia no meio", "action": "reorganize", "playlist": "Treino", "kinds": ["bpm"], "question": false}
{"id": 14, "message": "agrupa a Festa 2025 por subgênero", "action": "reorganize", "playlist": "Festa 2025", "kinds": ["genre"], "question": false}
{"id": 15, "message": "organiza minha playlist de academia por batidas por minuto", "action": "reorganize", "kinds": ["bpm"]}
{"id": 16, "message": "monta uma playlist contando de um a dez", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 17, "message": "playlist com músicas que tenham as estações do ano no título", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 18, "message": "cria uma playlist sobre o sistema solar, com um planeta no nome de cada música", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 19, "message": "separa a Churrasco: sertanejo de um lado, pagode do outro", "action": "reorganize", "playlist": "Churrasco", "kinds": ["genre"], "question": false}
{"id": 20, "message": "deixa a Estudo na ordem das mais calmas pras mais agitadas", "action": "reorganize", "playlist": "Estudo", "kinds": ["bpm"], "question": false}
{"id": 21, "message": "faz uma playlist", "action": "discover", "question": true}
{"id": 22, "message": "valeu, ficou ótimo!", "action": "chat"}
{"id": 23, "message": "arruma a Treino do jeito que você achar melhor", "action": "reorganize", "playlist": "Treino", "question": false}
{"id": 24, "message": "quero uma playlist que conte um dia inteiro: manhã, tarde e noite no nome das músicas", "action": "discover", "kinds": ["theme"], "question": false}
{"id": 25, "message": "organiza a Festa 2025 por gênero musical e depois por bpm", "action": "reorganize", "playlist": "Festa 2025", "kinds": ["genre", "bpm"], "question": false}
```

- [ ] **Step 7: Runner do eval, `services/llm/evals/run_intent.py`**

```python
"""Eval de interpretação contra o Claude Code real. Custa tokens (~US$ 0,03 por caso).

Uso: uv run python -m services.llm.evals.run_intent
Sai com código 1 se o acerto ficar abaixo de THRESHOLD.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.llm.api import ClaudeLLM
from services.llm.evals.scoring import score_intent
from services.llm.runner import ClaudeRunner, LLMError

THRESHOLD = 0.9
CASES = Path(__file__).parent / "intent_cases.jsonl"
PLAYLISTS = ["Treino", "Churrasco", "Estudo", "Rock Nacional", "Festa 2025", "Relax"]


def _run_case(llm: ClaudeLLM, case: dict) -> dict:
    try:
        intent = llm.interpret(case["message"], [], PLAYLISTS)
        ok, why = score_intent(case, intent)
        got = intent.model_dump(mode="json")
    except LLMError as err:
        ok, why, got = False, f"erro: {err}", None
    return {"id": case["id"], "message": case["message"], "ok": ok, "why": why, "got": got}


def main() -> int:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    llm = ClaudeLLM(ClaudeRunner())
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda c: _run_case(llm, c), cases))
    score = sum(r["ok"] for r in rows) / len(rows)
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'} #{r['id']:>2} {r['message'][:60]:<60} {r['why']}")
    print(f"\nAcerto: {score:.0%} (limiar {THRESHOLD:.0%})")
    out = Path("data/evals") / f"intent-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"score": score, "threshold": THRESHOLD, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    return 0 if score >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Rodar gate tests e ver passar**

Run: `uv run pytest services/llm -v`
Expected: 22 passed (13 da Task 9 + 4 api + 5 scoring)

- [ ] **Step 9: Smoke real (1 chamada, confirma schema inline + Windows)**

Run:
```bash
uv run python -c "from services.llm.api import ClaudeLLM; from services.llm.runner import ClaudeRunner; print(ClaudeLLM(ClaudeRunner()).interpret('organiza a Treino por bpm', [], ['Treino']).model_dump_json(indent=2))"
```
Expected: JSON com `"action": "reorganize"`, `"playlist_name": "Treino"` e pelo menos uma opção `"kind": "bpm"`. Se o Claude Code recusar o schema, imprima `inline_schema(Intent)` e ajuste `inline_schema` (ex.: remover `maxItems`), com teste novo cobrindo o ajuste.

- [ ] **Step 10: Rodar o eval completo**

Run: `uv run python -m services.llm.evals.run_intent`
Expected: `Acerto: >= 90%`. Se ficar abaixo, ajustar `prompts/interpret.md` olhando os FAIL (nunca editar os casos para passar), rodar de novo, e registrar no commit o acerto antes/depois.

- [ ] **Step 11: `services/llm/README.md`**

```markdown
# llm

Chama o Claude Code local (`claude -p`) com `--json-schema`, `--system-prompt` próprio e `--tools ""`. Nada de API paga.

- `runner.py`: executa o comando, mede latência e custo, transforma falhas em `LLMError`.
- `structured.py`: gera o JSON Schema a partir dos modelos pydantic e valida a resposta (1 nova tentativa com o erro no prompt).
- `api.py`: `interpret` (mensagem vira `Intent`) e `plan_theme` (tema vira `ThemePlan`).
- `prompts/`: prompts versionados em markdown. Mudou prompt, rode o eval.

Gate tests: `uv run pytest services/llm` (sem chamar o Claude).
Eval pago: `uv run python -m services.llm.evals.run_intent` (25 casos, limiar 90%, relatório em `data/evals/`).
```

- [ ] **Step 12: Commit**

```bash
git add services/llm
git commit -m "feat(llm): prompts, API interpret/plan_theme e eval de intenção"
```

---

### Task 11: agent, busca de playlist, trace, undo e opções padrão

**Files:**
- Create: `services/agent/__init__.py`, `services/agent/lookup.py`, `services/agent/trace.py`, `services/agent/undo.py`, `services/agent/defaults.py`
- Test: `services/agent/tests/test_lookup.py`, `services/agent/tests/test_trace.py`, `services/agent/tests/test_undo.py`

**Interfaces:**
- Consumes: `services.organizer.text.normalize_tokens` (Task 2); `contracts.models.PlaylistSummary, StrategyChoice, StrategyKind, BpmMode, GenreLevel`
- Produces: `services.agent.lookup.find_playlist(name: str, playlists: list[PlaylistSummary]) -> PlaylistSummary | None`; `services.agent.trace.Tracer(path: Path, clock=time.time)` chamável como `tracer(event: str, **fields)`, `summarize(path: Path) -> dict`; `services.agent.undo.UndoStore(path)` com `save(playlist_id: str, uris: list[str]) -> int`, `get(undo_id: int) -> tuple[str, list[str]] | None`, `delete(undo_id: int) -> None`; `services.agent.defaults.DEFAULT_REORGANIZE_OPTIONS: tuple[StrategyChoice, ...]`.

- [ ] **Step 1: Testes que falham**

`services/agent/tests/test_lookup.py`:
```python
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
```

`services/agent/tests/test_trace.py`:
```python
import json

from services.agent.trace import Tracer, summarize


def test_tracer_appends_json_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path, clock=lambda: 5.0)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.03)
    tracer("plan", bpm_coverage=0.8, genre_coverage=0.5)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"ts": 5.0, "event": "llm", "kind": "interpret", "latency_s": 2.0, "cost_usd": 0.03}


def test_summarize_computes_metrics(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.03)
    tracer("llm", kind="theme", latency_s=4.0, cost_usd=0.05)
    tracer("plan", bpm_coverage=1.0, genre_coverage=0.5)
    tracer("plan", bpm_coverage=0.5, genre_coverage=0.5)
    tracer("theme", candidates_tried=10, candidates_valid=7)
    tracer("apply", mode="new", playlists=1)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("linha quebrada\n")
    stats = summarize(path)
    assert stats["llm_calls"] == 2
    assert stats["llm_avg_latency_s"] == 3.0
    assert stats["llm_total_cost_usd"] == 0.08
    assert stats["avg_bpm_coverage"] == 0.75
    assert stats["theme_validation_rate"] == 0.7
    assert stats["applies"] == 1


def test_summarize_missing_file(tmp_path):
    stats = summarize(tmp_path / "nada.jsonl")
    assert stats["events"] == 0 and stats["avg_bpm_coverage"] is None
```

`services/agent/tests/test_undo.py`:
```python
from services.agent.undo import UndoStore


def test_save_get_delete(tmp_path):
    store = UndoStore(tmp_path / "u.sqlite")
    undo_id = store.save("p1", ["spotify:track:a", "spotify:track:b"])
    assert store.get(undo_id) == ("p1", ["spotify:track:a", "spotify:track:b"])
    store.delete(undo_id)
    assert store.get(undo_id) is None


def test_ids_are_unique(tmp_path):
    store = UndoStore(tmp_path / "u.sqlite")
    assert store.save("p", []) != store.save("p", [])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/agent -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.agent'`

- [ ] **Step 3: Implementar**

`services/agent/__init__.py`: `"""Orquestrador da conversa: liga LLM, Spotify, enrichment e organizer."""`

`services/agent/lookup.py`:
```python
"""Acha a playlist citada pelo usuário: igualdade normalizada primeiro, depois trecho único."""

from __future__ import annotations

from contracts.models import PlaylistSummary
from services.organizer.text import normalize_tokens


def _key(text: str) -> str:
    return " ".join(normalize_tokens(text))


def find_playlist(name: str, playlists: list[PlaylistSummary]) -> PlaylistSummary | None:
    wanted = _key(name)
    if not wanted:
        return None
    keyed = [(p, _key(p.name)) for p in playlists]
    keyed = [(p, k) for p, k in keyed if k]
    exact = [p for p, k in keyed if k == wanted]
    if exact:
        return exact[0]
    partial = [p for p, k in keyed if wanted in k or k in wanted]
    return partial[0] if len(partial) == 1 else None
```

`services/agent/trace.py`:
```python
"""Trace JSONL de cada interação e o resumo mostrado em /api/stats."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


class Tracer:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()

    def __call__(self, event: str, **fields: Any) -> None:
        line = json.dumps({"ts": self.clock(), "event": event, **fields}, ensure_ascii=False)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summarize(path: Path) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def of(kind: str) -> list[dict[str, Any]]:
        return [e for e in events if e.get("event") == kind]

    llm, plans, themes = of("llm"), of("plan"), of("theme")
    tried = sum(e.get("candidates_tried", 0) for e in themes)
    valid = sum(e.get("candidates_valid", 0) for e in themes)
    return {
        "events": len(events),
        "llm_calls": len(llm),
        "llm_avg_latency_s": _avg([e["latency_s"] for e in llm if "latency_s" in e]),
        "llm_total_cost_usd": round(sum(e.get("cost_usd", 0.0) for e in llm), 4),
        "plans": len(plans),
        "avg_bpm_coverage": _avg([e["bpm_coverage"] for e in plans if "bpm_coverage" in e]),
        "avg_genre_coverage": _avg([e["genre_coverage"] for e in plans if "genre_coverage" in e]),
        "theme_candidates_tried": tried,
        "theme_candidates_valid": valid,
        "theme_validation_rate": round(valid / tried, 3) if tried else None,
        "applies": len(of("apply")),
    }
```

`services/agent/undo.py`:
```python
"""Snapshot da ordem original antes de reordenar uma playlist no lugar, para o botão Desfazer."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class UndoStore:
    def __init__(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id TEXT, uris TEXT, created_at REAL)"
            )

    def save(self, playlist_id: str, uris: list[str]) -> int:
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT INTO snapshots (playlist_id, uris, created_at) VALUES (?, ?, ?)",
                (playlist_id, json.dumps(uris), time.time()),
            )
            return int(cursor.lastrowid)

    def get(self, undo_id: int) -> tuple[str, list[str]] | None:
        with self.lock:
            row = self.db.execute("SELECT playlist_id, uris FROM snapshots WHERE id = ?", (undo_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def delete(self, undo_id: int) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM snapshots WHERE id = ?", (undo_id,))
```

`services/agent/defaults.py`:
```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/agent -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add services/agent
git commit -m "feat(agent): busca de playlist, trace JSONL, undo e opções padrão"
```

---

### Task 12: agent, resolvedor de tema (valida sugestões do LLM no Spotify)

**Files:**
- Create: `services/agent/theme_resolver.py`
- Test: `services/agent/tests/test_theme_resolver.py`

**Interfaces:**
- Consumes: `contracts.ports.SpotifyPort`, `contracts.models.ThemePlan, Track`, `services.organizer.theme.pick_match`
- Produces: `services.agent.theme_resolver.ResolveResult(found: list[Track | None], candidates_tried: int, candidates_valid: int)` (dataclass), `ThemeResolver(spotify, max_playlists=20, max_library_tracks=2000, fallback_pages=2)` com `library_tracks() -> list[Track]`, `invalidate() -> None`, `resolve(plan: ThemePlan) -> ResolveResult`.

**Como funciona, por slot:** 1) procura nas playlists do próprio usuário; 2) busca cada candidata do LLM (`track:"título" artist:"artista"`) e só aceita se o título contém a keyword; 3) busca pela própria keyword (`track:"Primeiro Andar"`, 2 páginas); 4) se nada casar, o slot fica vazio e aparece na prévia. Uma faixa nunca é usada em dois slots.

- [ ] **Step 1: Teste que falha, `services/agent/tests/test_theme_resolver.py`**

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/agent/tests/test_theme_resolver.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.agent.theme_resolver'`

- [ ] **Step 3: Implementar `services/agent/theme_resolver.py`**

```python
"""Transforma o ThemePlan do LLM em faixas reais: biblioteca do usuário, depois busca validada no Spotify."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.models import ThemePlan, Track
from contracts.ports import SpotifyPort
from services.organizer.theme import pick_match


@dataclass
class ResolveResult:
    found: list[Track | None]
    candidates_tried: int
    candidates_valid: int


def _clean(text: str) -> str:
    return " ".join(text.replace('"', "").split())


class ThemeResolver:
    def __init__(
        self, spotify: SpotifyPort, max_playlists: int = 20, max_library_tracks: int = 2000, fallback_pages: int = 2
    ) -> None:
        self.spotify = spotify
        self.max_playlists = max_playlists
        self.max_library_tracks = max_library_tracks
        self.fallback_pages = fallback_pages
        self._library: list[Track] | None = None

    def library_tracks(self) -> list[Track]:
        if self._library is None:
            tracks: list[Track] = []
            for playlist in self.spotify.my_playlists()[: self.max_playlists]:
                tracks.extend(self.spotify.playlist_tracks(playlist.id))
                if len(tracks) >= self.max_library_tracks:
                    break
            self._library = tracks[: self.max_library_tracks]
        return self._library

    def invalidate(self) -> None:
        self._library = None

    def resolve(self, plan: ThemePlan) -> ResolveResult:
        library = self.library_tracks()
        used: set[str] = set()
        found: list[Track | None] = []
        tried = valid = 0
        for slot in plan.slots:
            match = pick_match(library, slot.keywords, used)
            if match is None:
                for candidate in slot.candidates:
                    tried += 1
                    query = f'track:"{_clean(candidate.title)}" artist:"{_clean(candidate.artist)}"'
                    match = pick_match(self.spotify.search_tracks(query), slot.keywords, used)
                    if match is not None:
                        valid += 1
                        break
            if match is None:
                for keyword in slot.keywords[:2]:
                    results = self.spotify.search_tracks(f'track:"{_clean(keyword)}"', pages=self.fallback_pages)
                    match = pick_match(results, slot.keywords, used)
                    if match is not None:
                        break
            found.append(match)
            if match is not None:
                used.add(match.id)
        return ResolveResult(found=found, candidates_tried=tried, candidates_valid=valid)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/agent -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add services/agent
git commit -m "feat(agent): resolvedor de tema com validação de títulos no Spotify"
```

---

### Task 13: agent, máquina de estados da conversa

**Files:**
- Create: `services/agent/agent.py`, `services/agent/README.md`
- Test: `services/agent/tests/test_agent.py`

**Interfaces:**
- Consumes: `contracts.ports.LLMPort, SpotifyPort, EnricherPort`; `contracts.models.*`; `services.organizer.planner.plan_reorganize, plan_theme`; Tasks 11-12.
- Produces: `services.agent.agent.MAX_THEME_SLOTS = 12`, `Session` (dataclass: `state`, `history`, `source`, `options`, `plan`), `AgentError(Exception)`, `describe_plan(plan: PlaylistPlan) -> str`, `Agent(llm, spotify, enricher, resolver, undo_store, tracer)` com `handle_message(s: Session, text: str) -> AgentReply`, `choose(s, index: int) -> AgentReply`, `apply(s, mode: ApplyMode) -> AgentReply`, `undo(s, undo_id: int) -> AgentReply`.

**Estados:** `UNDERSTAND` (entendendo) → `PROPOSE` (opções na tela) → `PREVIEW` (prévia pronta) → `APPLIED` (gravado). Confirmar é a transição `PREVIEW → APPLIED`, e só ela escreve no Spotify.

- [ ] **Step 1: Teste que falha, `services/agent/tests/test_agent.py`**

```python
import pytest

from contracts.models import (
    ApplyMode, Artist, BpmMode, ConversationState, EnrichedTrack, GenreLevel, Intent, PlaylistSummary,
    StrategyChoice, StrategyKind, ThemePlan, ThemeSlot, Track,
)
from services.agent.agent import Agent, AgentError, Session
from services.agent.theme_resolver import ResolveResult
from services.agent.undo import UndoStore


def _t(tid, name=None):
    return Track(id=tid, uri=f"spotify:track:{tid}", name=name or tid, artists=[Artist(id="a", name="A")])


BPM_ASC = StrategyChoice(kind=StrategyKind.BPM, label="BPM crescente", description="d", bpm_mode=BpmMode.ASC)
SPLIT = StrategyChoice(kind=StrategyKind.GENRE, label="Por gênero", description="d", genre_level=GenreLevel.FAMILY, genre_split=True)
THEME = StrategyChoice(kind=StrategyKind.THEME, label="Prédio", description="d", theme="prédio")


class FakeLLM:
    def __init__(self, intents=(), theme=None):
        self.intents = list(intents)
        self.theme = theme
        self.seen = []

    def interpret(self, message, history, playlist_names):
        self.seen.append((message, list(history), playlist_names))
        return self.intents.pop(0)

    def plan_theme(self, theme, max_slots):
        return self.theme


class FakeSpotify:
    def __init__(self):
        self.playlists = [PlaylistSummary(id="src", name="Treino", total=3, owner_id="me")]
        self.tracks = {"src": [_t("b"), _t("a"), _t("c")]}
        self.created = []
        self.replaced = []

    def my_playlists(self):
        return self.playlists

    def playlist_tracks(self, pid):
        return list(self.tracks[pid])

    def create_playlist(self, name, description):
        pid = f"new{len(self.created)}"
        self.created.append((pid, name))
        return pid, f"https://open.spotify.com/playlist/{pid}"

    def replace_items(self, pid, uris):
        self.replaced.append((pid, list(uris)))
        self.tracks[pid] = [_t(u.rsplit(":", 1)[-1]) for u in uris]


class FakeEnricher:
    TEMPO = {"a": 100, "b": 120, "c": 140, "x": 90}
    GENRES = {"a": ["rock"], "b": ["rock"], "c": ["pagode"], "x": []}

    def __init__(self):
        self.calls = []

    def enrich(self, tracks):
        self.calls.append([t.id for t in tracks])
        return [EnrichedTrack(track=t, tempo=self.TEMPO.get(t.id), genres=self.GENRES.get(t.id, [])) for t in tracks]


class FakeResolver:
    def __init__(self, result=None):
        self.result = result
        self.invalidations = 0

    def resolve(self, plan):
        return self.result

    def invalidate(self):
        self.invalidations += 1


@pytest.fixture
def world(tmp_path):
    events = []
    spotify, enricher, resolver = FakeSpotify(), FakeEnricher(), FakeResolver()

    def make(intents=(), theme=None):
        llm = FakeLLM(intents, theme)
        agent = Agent(llm, spotify, enricher, resolver, UndoStore(tmp_path / "u.sqlite"),
                      lambda e, **f: events.append((e, f)))
        return agent, llm

    return {"make": make, "spotify": spotify, "enricher": enricher, "resolver": resolver, "events": events}


def _reorganize(options=(BPM_ASC,), name="Treino"):
    return Intent(action="reorganize", reply="Opções:", playlist_name=name, options=list(options))


def test_question_keeps_understanding(world):
    agent, _ = world["make"]([Intent(action="reorganize", reply="", question="Qual playlist?")])
    reply = agent.handle_message(Session(), "organiza")
    assert reply.state is ConversationState.UNDERSTAND and reply.message == "Qual playlist?"


def test_chat_replies(world):
    agent, _ = world["make"]([Intent(action="chat", reply="Oi!")])
    assert agent.handle_message(Session(), "oi").message == "Oi!"


def test_unknown_playlist_lists_user_playlists(world):
    agent, _ = world["make"]([_reorganize(name="Festa")])
    reply = agent.handle_message(Session(), "organiza a festa")
    assert reply.state is ConversationState.UNDERSTAND and "Treino" in reply.message


def test_reorganize_proposes_options_and_filters_theme(world):
    agent, _ = world["make"]([_reorganize(options=[THEME, BPM_ASC])])
    s = Session()
    reply = agent.handle_message(s, "organiza a treino")
    assert reply.state is ConversationState.PROPOSE
    assert [o.label for o in reply.options] == ["BPM crescente"]
    assert s.source.id == "src"


def test_reorganize_without_options_uses_defaults(world):
    agent, _ = world["make"]([_reorganize(options=[])])
    assert len(agent.handle_message(Session(), "organiza a treino").options) == 3


def test_history_passed_to_llm_excludes_current_message(world):
    agent, llm = world["make"]([Intent(action="chat", reply="Oi!"), Intent(action="chat", reply="Tchau")])
    s = Session()
    agent.handle_message(s, "oi")
    agent.handle_message(s, "tchau")
    assert llm.seen[1][1] == [("usuário", "oi"), ("agente", "Oi!")]


def test_choose_builds_preview_without_writing(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    reply = agent.choose(s, 0)
    assert reply.state is ConversationState.PREVIEW
    assert [t.track.id for t in reply.plan.playlists[0].tracks] == ["a", "b", "c"]
    assert world["spotify"].created == [] and world["spotify"].replaced == []
    assert world["events"][-1][0] == "plan"


def test_choose_rejects_invalid_index_and_wrong_state(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    with pytest.raises(AgentError):
        agent.choose(s, 0)
    agent.handle_message(s, "x")
    with pytest.raises(AgentError):
        agent.choose(s, 5)


def test_apply_new_creates_playlist_with_planned_order(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    reply = agent.apply(s, ApplyMode.NEW)
    assert reply.state is ConversationState.APPLIED
    assert world["spotify"].created == [("new0", "Treino · BPM crescente")]
    assert world["spotify"].replaced == [("new0", ["spotify:track:a", "spotify:track:b", "spotify:track:c"])]
    assert reply.result.urls == ["https://open.spotify.com/playlist/new0"]
    assert world["resolver"].invalidations == 1
    with pytest.raises(AgentError):
        agent.apply(s, ApplyMode.NEW)


def test_apply_replace_then_undo_restores_original(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    reply = agent.apply(s, ApplyMode.REPLACE)
    assert [t.id for t in world["spotify"].tracks["src"]] == ["a", "b", "c"]
    agent.undo(s, reply.result.undo_id)
    assert [t.id for t in world["spotify"].tracks["src"]] == ["b", "a", "c"]
    with pytest.raises(AgentError):
        agent.undo(s, reply.result.undo_id)


def test_replace_is_refused_for_split_plans(world):
    agent, _ = world["make"]([_reorganize(options=[SPLIT])])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    with pytest.raises(AgentError):
        agent.apply(s, ApplyMode.REPLACE)


def test_apply_without_preview_is_refused(world):
    agent, _ = world["make"]()
    with pytest.raises(AgentError):
        agent.apply(Session(), ApplyMode.NEW)


def test_discover_flow_resolves_enriches_found_only_and_reports_missing(world):
    theme = ThemePlan(playlist_name="Prédio", description="Sobe!", slots=[
        ThemeSlot(label="Térreo", keywords=["Térreo"]), ThemeSlot(label="1º", keywords=["Primeiro Andar"]),
    ])
    world["resolver"].result = ResolveResult(found=[None, _t("x", "Primeiro Andar")], candidates_tried=3, candidates_valid=1)
    agent, _ = world["make"]([Intent(action="discover", reply="Bora!", options=[THEME, BPM_ASC])], theme=theme)
    s = Session()
    proposal = agent.handle_message(s, "playlist prédio")
    assert [o.kind for o in proposal.options] == [StrategyKind.THEME]
    reply = agent.choose(s, 0)
    playlist = reply.plan.playlists[0]
    assert playlist.missing_slots == ["Térreo"]
    assert world["enricher"].calls[-1] == ["x"]
    assert "Térreo" in reply.message
    assert ("theme", {"slots": 2, "slots_found": 1, "candidates_tried": 3, "candidates_valid": 1}) in world["events"]


def test_discover_with_nothing_found_stays_in_propose(world):
    theme = ThemePlan(playlist_name="P", description="d", slots=[ThemeSlot(label="a", keywords=["a"])])
    world["resolver"].result = ResolveResult(found=[None], candidates_tried=1, candidates_valid=0)
    agent, _ = world["make"]([Intent(action="discover", reply="ok", options=[THEME])], theme=theme)
    s = Session()
    agent.handle_message(s, "x")
    with pytest.raises(AgentError):
        agent.choose(s, 0)
    assert s.state is ConversationState.PROPOSE


def test_discover_without_theme_option_asks_for_theme(world):
    agent, _ = world["make"]([Intent(action="discover", reply="ok", options=[BPM_ASC])])
    reply = agent.handle_message(Session(), "faz uma playlist")
    assert reply.state is ConversationState.UNDERSTAND and "tema" in reply.message
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/agent/tests/test_agent.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.agent.agent'`

- [ ] **Step 3: Implementar `services/agent/agent.py`**

```python
"""Máquina de estados da conversa. O LLM entende e sugere; o código decide, ordena e só escreve após confirmação."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from contracts.models import (
    AgentReply, ApplyMode, ApplyResult, ConversationState, IntentAction, PlaylistPlan, PlaylistSummary,
    StrategyChoice, StrategyKind,
)
from contracts.ports import EnricherPort, LLMPort, SpotifyPort
from services.agent.defaults import DEFAULT_REORGANIZE_OPTIONS
from services.agent.lookup import find_playlist
from services.agent.theme_resolver import ThemeResolver
from services.agent.undo import UndoStore
from services.organizer.planner import plan_reorganize, plan_theme

MAX_THEME_SLOTS = 12
State = ConversationState


@dataclass
class Session:
    state: ConversationState = ConversationState.UNDERSTAND
    history: list[tuple[str, str]] = field(default_factory=list)
    source: PlaylistSummary | None = None
    options: list[StrategyChoice] = field(default_factory=list)
    plan: PlaylistPlan | None = None


class AgentError(Exception):
    """Erro de uso, com mensagem para mostrar ao usuário."""


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def describe_plan(plan: PlaylistPlan) -> str:
    total = sum(len(p.tracks) for p in plan.playlists)
    parts = [
        f"Prévia pronta: {total} faixas em {len(plan.playlists)} playlist(s).",
        f"BPM encontrado em {_pct(plan.bpm_coverage)} e gênero em {_pct(plan.genre_coverage)} das faixas.",
    ]
    diffs = [p.diff for p in plan.playlists if p.diff]
    if diffs:
        parts.append(f"{sum(d.moved for d in diffs)} faixas mudaram de posição.")
    missing = [slot for p in plan.playlists for slot in p.missing_slots]
    if missing:
        parts.append("Sem música encontrada para: " + ", ".join(missing) + ".")
    parts.append("Confira abaixo e confirme para gravar no Spotify.")
    return " ".join(parts)


class Agent:
    def __init__(
        self,
        llm: LLMPort,
        spotify: SpotifyPort,
        enricher: EnricherPort,
        resolver: ThemeResolver,
        undo_store: UndoStore,
        tracer: Callable[..., None],
    ) -> None:
        self.llm = llm
        self.spotify = spotify
        self.enricher = enricher
        self.resolver = resolver
        self.undo_store = undo_store
        self.tracer = tracer

    def _say(self, s: Session, message: str, state: ConversationState, **extra: Any) -> AgentReply:
        s.state = state
        s.history.append(("agente", message))
        return AgentReply(message=message, state=state, **extra)

    def handle_message(self, s: Session, text: str) -> AgentReply:
        text = text.strip()
        if not text:
            raise AgentError("Escreva uma mensagem.")
        playlists = self.spotify.my_playlists()
        intent = self.llm.interpret(text, s.history, [p.name for p in playlists])
        s.history.append(("usuário", text))
        s.plan, s.options = None, []
        self.tracer("intent", action=intent.action.value, asked=bool(intent.question))
        if intent.question:
            return self._say(s, intent.question, State.UNDERSTAND)
        if intent.action is IntentAction.REORGANIZE:
            source = find_playlist(intent.playlist_name or "", playlists)
            if source is None:
                names = ", ".join(p.name for p in playlists[:15]) or "nenhuma"
                return self._say(
                    s, f'Não achei a playlist "{intent.playlist_name or ""}" entre as suas. Suas playlists: {names}.',
                    State.UNDERSTAND,
                )
            s.source = source
            options = [o for o in intent.options if o.kind is not StrategyKind.THEME] or list(DEFAULT_REORGANIZE_OPTIONS)
        elif intent.action is IntentAction.DISCOVER:
            s.source = None
            options = [o for o in intent.options if o.kind is StrategyKind.THEME]
            if not options:
                return self._say(
                    s, "Qual tema você quer? Ex.: andares de um prédio, dias da semana, cores.", State.UNDERSTAND
                )
        else:
            return self._say(s, intent.reply, State.UNDERSTAND)
        s.options = options[:3]
        return self._say(s, intent.reply, State.PROPOSE, options=s.options)

    def _plan_theme(self, choice: StrategyChoice) -> PlaylistPlan:
        theme_plan = self.llm.plan_theme(choice.theme or choice.label, MAX_THEME_SLOTS)
        resolved = self.resolver.resolve(theme_plan)
        found = [t for t in resolved.found if t is not None]
        self.tracer(
            "theme", slots=len(theme_plan.slots), slots_found=len(found),
            candidates_tried=resolved.candidates_tried, candidates_valid=resolved.candidates_valid,
        )
        if not found:
            raise AgentError("Não achei nenhuma música no Spotify para esse tema. Tente outra opção ou reformule o tema.")
        by_id = {e.track.id: e for e in self.enricher.enrich(found)}
        return plan_theme(choice, theme_plan, [by_id[t.id] if t else None for t in resolved.found])

    def choose(self, s: Session, index: int) -> AgentReply:
        if s.state is not State.PROPOSE or not 0 <= index < len(s.options):
            raise AgentError("Escolha uma das opções propostas.")
        choice = s.options[index]
        if choice.kind is StrategyKind.THEME:
            plan = self._plan_theme(choice)
        else:
            if s.source is None:
                raise AgentError("Diga qual playlist organizar.")
            tracks = self.spotify.playlist_tracks(s.source.id)
            if not tracks:
                raise AgentError(f'A playlist "{s.source.name}" está vazia.')
            plan = plan_reorganize(choice, s.source, self.enricher.enrich(tracks))
        s.history.append(("usuário", f"Escolhi: {choice.label}"))
        s.plan = plan
        self.tracer(
            "plan", kind=choice.kind.value, playlists=len(plan.playlists),
            tracks=sum(len(p.tracks) for p in plan.playlists),
            bpm_coverage=round(plan.bpm_coverage, 3), genre_coverage=round(plan.genre_coverage, 3),
        )
        return self._say(s, describe_plan(plan), State.PREVIEW, plan=plan)

    def apply(self, s: Session, mode: ApplyMode) -> AgentReply:
        if s.state is not State.PREVIEW or s.plan is None:
            raise AgentError("Nada para aplicar. Gere uma prévia primeiro.")
        plan = s.plan
        if mode is ApplyMode.REPLACE:
            if not plan.can_replace_in_place or plan.source_playlist_id is None:
                raise AgentError("Este plano só pode criar playlists novas.")
            pid = plan.source_playlist_id
            undo_id = self.undo_store.save(pid, [t.uri for t in self.spotify.playlist_tracks(pid)])
            self.spotify.replace_items(pid, [t.track.uri for t in plan.playlists[0].tracks])
            result = ApplyResult(
                mode=mode, playlist_ids=[pid], urls=[f"https://open.spotify.com/playlist/{pid}"], undo_id=undo_id
            )
            message = "Pronto: a playlist original foi reordenada. Se não gostar, use Desfazer."
        else:
            ids: list[str] = []
            urls: list[str] = []
            for planned in plan.playlists:
                if not planned.tracks:
                    continue
                pid, url = self.spotify.create_playlist(planned.name, planned.description)
                self.spotify.replace_items(pid, [t.track.uri for t in planned.tracks])
                ids.append(pid)
                urls.append(url)
            if not ids:
                raise AgentError("O plano não tem faixas para gravar.")
            result = ApplyResult(mode=mode, playlist_ids=ids, urls=urls)
            message = f"Pronto: criei {len(ids)} playlist(s) nova(s) no seu Spotify (privadas)."
        self.resolver.invalidate()
        self.tracer("apply", mode=mode.value, playlists=len(result.playlist_ids))
        s.plan = None
        return self._say(s, message, State.APPLIED, result=result)

    def undo(self, s: Session, undo_id: int) -> AgentReply:
        snapshot = self.undo_store.get(undo_id)
        if snapshot is None:
            raise AgentError("Não há o que desfazer: já foi desfeito.")
        playlist_id, uris = snapshot
        self.spotify.replace_items(playlist_id, uris)
        self.undo_store.delete(undo_id)
        self.tracer("undo", playlist_id=playlist_id)
        return self._say(s, "Desfeito: a playlist voltou à ordem original.", s.state)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/agent -v`
Expected: 30 passed (15 anteriores + 15 agent)

- [ ] **Step 5: `services/agent/README.md`**

```markdown
# agent

Orquestra a conversa. Estados: `understand` → `propose` → `preview` → `applied`.

- `handle_message`: o LLM interpreta; o código acha a playlist (`lookup.py`) e filtra as opções válidas.
- `choose`: carrega faixas, enriquece (BPM/gênero) e monta o plano com o `organizer`. Tema: o LLM sugere, o `theme_resolver` valida cada título no Spotify.
- `apply`: única etapa que escreve no Spotify. Padrão cria playlist nova (privada); `replace` salva snapshot para `undo`.
- `trace.py`: cada etapa grava uma linha em `data/traces.jsonl`; `summarize` alimenta `/api/stats`.

Testes: `uv run pytest services/agent` (LLM, Spotify e enrichment falsos).
```

- [ ] **Step 6: Commit**

```bash
git add services/agent
git commit -m "feat(agent): máquina de estados da conversa com prévia, confirmação e desfazer"
```

---

### Task 14: web, configuração, montagem dos serviços e API HTTP

**Files:**
- Create: `services/web/__init__.py`, `services/web/settings.py`, `services/web/wiring.py`, `services/web/app.py`
- Test: `services/web/tests/test_settings.py`, `services/web/tests/test_wiring.py`, `services/web/tests/test_app.py`

**Interfaces:**
- Consumes: todas as tarefas anteriores.
- Produces: `services.web.settings.Settings(spotify_client_id, lastfm_api_key=None, redirect_uri="http://127.0.0.1:8000/callback", data_dir=Path("data"), model="opus")` com `from_env(env: Mapping | None = None)`; `services.web.wiring.AppDeps(agent, auth, settings, trace_path, claude_ok)`, `build_deps(settings, claude_ok: bool) -> AppDeps`; `services.web.app.create_app(deps: AppDeps) -> FastAPI`.

Rotas: `GET /` (index), `/static/*`, `GET /login`, `GET /callback`, `GET /api/status`, `POST /api/chat {text}`, `POST /api/choose {index}`, `POST /api/apply {mode}`, `POST /api/undo {undo_id}`, `POST /api/reset`, `GET /api/stats`. Erros: `AgentError` → 400, `AuthRequired` → 401, `ExternalServiceError` → 502, sempre `{"detail": "<mensagem em português>"}`.

- [ ] **Step 1: Testes que falham**

`services/web/tests/test_settings.py`:
```python
from pathlib import Path

import pytest

from services.web.settings import Settings


def test_missing_client_id_exits_with_instructions():
    with pytest.raises(SystemExit, match="SPOTIFY_CLIENT_ID"):
        Settings.from_env({})


def test_reads_env_and_treats_blank_lastfm_as_none():
    settings = Settings.from_env({"SPOTIFY_CLIENT_ID": " abc ", "LASTFM_API_KEY": ""})
    assert settings.spotify_client_id == "abc"
    assert settings.lastfm_api_key is None
    assert settings.redirect_uri == "http://127.0.0.1:8000/callback"
    assert settings.data_dir == Path("data")
```

`services/web/tests/test_wiring.py`:
```python
from services.agent.agent import Agent
from services.web.settings import Settings
from services.web.wiring import build_deps


def test_build_deps_wires_everything_without_network(tmp_path):
    deps = build_deps(Settings(spotify_client_id="cid", data_dir=tmp_path), claude_ok=False)
    assert isinstance(deps.agent, Agent)
    assert deps.trace_path == tmp_path / "traces.jsonl"
    assert (tmp_path / "cache.sqlite").exists()
    assert not deps.auth.has_token()
```

`services/web/tests/test_app.py`:
```python
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import AgentReply, ConversationState
from services.agent.agent import AgentError
from services.spotify.auth import AUTHORIZE_URL, code_challenge
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class FakeAgent:
    def handle_message(self, s, text):
        if text == "erro":
            raise AgentError("Escolha uma das opções propostas.")
        if text == "login":
            raise AuthRequired("Faça login no Spotify.")
        if text == "fora":
            raise ExternalServiceError("Spotify fora do ar")
        return AgentReply(message=f"eco {text}", state=ConversationState.UNDERSTAND)

    def choose(self, s, index):
        return AgentReply(message=f"opção {index}", state=ConversationState.PREVIEW)

    def apply(self, s, mode):
        return AgentReply(message=f"aplicado {mode.value}", state=ConversationState.APPLIED)

    def undo(self, s, undo_id):
        return AgentReply(message=f"desfeito {undo_id}", state=ConversationState.APPLIED)


class FakeAuth:
    def __init__(self):
        self.exchanged = []

    def has_token(self):
        return bool(self.exchanged)

    def exchange_code(self, code, verifier):
        self.exchanged.append((code, verifier))


@pytest.fixture
def ctx(tmp_path):
    deps = AppDeps(
        agent=FakeAgent(), auth=FakeAuth(), settings=Settings(spotify_client_id="cid", data_dir=tmp_path),
        trace_path=tmp_path / "t.jsonl", claude_ok=True,
    )
    return TestClient(create_app(deps)), deps


def test_status(ctx):
    client, _ = ctx
    assert client.get("/api/status").json() == {"logged_in": False, "claude_ok": True}


def test_chat_choose_apply_undo(ctx):
    client, _ = ctx
    assert client.post("/api/chat", json={"text": "oi"}).json()["message"] == "eco oi"
    assert client.post("/api/choose", json={"index": 1}).json()["state"] == "preview"
    assert client.post("/api/apply", json={"mode": "replace"}).json()["message"] == "aplicado replace"
    assert client.post("/api/undo", json={"undo_id": 7}).json()["message"] == "desfeito 7"


def test_invalid_apply_mode_is_422(ctx):
    client, _ = ctx
    assert client.post("/api/apply", json={"mode": "apagar"}).status_code == 422


@pytest.mark.parametrize(("text", "status"), [("erro", 400), ("login", 401), ("fora", 502)])
def test_errors_map_to_status_and_portuguese_detail(ctx, text, status):
    client, _ = ctx
    response = client.post("/api/chat", json={"text": text})
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]


def test_login_then_callback_exchanges_matching_verifier(ctx):
    client, deps = ctx
    response = client.get("/login", follow_redirects=False)
    location = response.headers["location"]
    assert location.startswith(AUTHORIZE_URL)
    query = parse_qs(urlparse(location).query)
    callback = client.get("/callback", params={"code": "c1", "state": query["state"][0]}, follow_redirects=False)
    assert callback.status_code in (302, 307) and callback.headers["location"] == "/"
    code, verifier = deps.auth.exchanged[0]
    assert code == "c1" and code_challenge(verifier) == query["code_challenge"][0]
    # state é de uso único
    again = client.get("/callback", params={"code": "c1", "state": query["state"][0]}, follow_redirects=False)
    assert again.status_code == 400


def test_callback_with_error_or_unknown_state_is_400(ctx):
    client, _ = ctx
    assert client.get("/callback", params={"error": "access_denied"}).status_code == 400
    assert client.get("/callback", params={"code": "c", "state": "inventado"}).status_code == 400


def test_stats_and_reset(ctx):
    client, _ = ctx
    assert client.get("/api/stats").json()["events"] == 0
    assert client.post("/api/reset").json() == {"ok": True}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/web -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.web'`

- [ ] **Step 3: Implementar**

`services/web/__init__.py`: `"""Servidor local: API HTTP, login do Spotify e interface web."""`

`services/web/settings.py`:
```python
"""Configuração lida do .env. Só o client ID do Spotify é obrigatório."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    lastfm_api_key: str | None = None
    redirect_uri: str = "http://127.0.0.1:8000/callback"
    data_dir: Path = Path("data")
    model: str = "opus"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_dotenv()
            env = os.environ
        client_id = (env.get("SPOTIFY_CLIENT_ID") or "").strip()
        if not client_id:
            raise SystemExit("Defina SPOTIFY_CLIENT_ID no arquivo .env (veja .env.example e o README).")
        lastfm = (env.get("LASTFM_API_KEY") or "").strip() or None
        return cls(spotify_client_id=client_id, lastfm_api_key=lastfm)
```

`services/web/wiring.py`:
```python
"""Monta os serviços reais. Único lugar que conhece todas as implementações concretas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from services.agent.agent import Agent
from services.agent.theme_resolver import ThemeResolver
from services.agent.trace import Tracer
from services.agent.undo import UndoStore
from services.enrichment.cache import EnrichmentCache
from services.enrichment.enricher import Enricher
from services.enrichment.genres import GenreResolver, LastFmClient
from services.enrichment.reccobeats import ReccoBeatsClient
from services.llm.api import ClaudeLLM
from services.llm.runner import ClaudeRunner
from services.spotify.auth import SpotifyAuth, TokenStore
from services.spotify.client import SpotifyClient
from services.web.settings import Settings


@dataclass
class AppDeps:
    agent: Any
    auth: Any
    settings: Settings
    trace_path: Path
    claude_ok: bool


def build_deps(settings: Settings, claude_ok: bool) -> AppDeps:
    data = Path(settings.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(timeout=20)
    auth = SpotifyAuth(settings.spotify_client_id, settings.redirect_uri, TokenStore(data / "token.json"), http)
    spotify = SpotifyClient(auth, http)
    cache = EnrichmentCache(data / "cache.sqlite")
    lastfm = LastFmClient(settings.lastfm_api_key, http) if settings.lastfm_api_key else None
    enricher = Enricher(ReccoBeatsClient(http), GenreResolver(spotify.artist_genres, lastfm, cache), cache)
    trace_path = data / "traces.jsonl"
    tracer = Tracer(trace_path)
    # Sem cwd: o runner usa uma pasta temporária fora do projeto (ver services/llm/runner.py).
    llm = ClaudeLLM(ClaudeRunner(model=settings.model), tracer)
    agent = Agent(llm, spotify, enricher, ThemeResolver(spotify), UndoStore(data / "undo.sqlite"), tracer)
    return AppDeps(agent=agent, auth=auth, settings=settings, trace_path=trace_path, claude_ok=claude_ok)
```

`services/web/app.py`:
```python
"""API HTTP local. Uma sessão de conversa por processo (app pessoal, um usuário)."""

from __future__ import annotations

import html
import secrets
import threading
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import AgentReply, ApplyMode
from services.agent.agent import AgentError, Session
from services.agent.trace import summarize
from services.spotify.auth import authorize_url, code_challenge, make_verifier
from services.web.wiring import AppDeps

STATIC = Path(__file__).parent / "static"


class ChatIn(BaseModel):
    text: str


class ChooseIn(BaseModel):
    index: int


class ApplyIn(BaseModel):
    mode: ApplyMode


class UndoIn(BaseModel):
    undo_id: int


def create_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title="Playlist Agent")
    app.state.session = Session()
    pending_logins: dict[str, str] = {}
    lock = threading.Lock()

    def _error(status: int):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc) or "Erro inesperado."})
        return handler

    app.add_exception_handler(AgentError, _error(400))
    app.add_exception_handler(AuthRequired, _error(401))
    app.add_exception_handler(ExternalServiceError, _error(502))
    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    def login() -> RedirectResponse:
        verifier = make_verifier()
        state = secrets.token_urlsafe(16)
        pending_logins[state] = verifier
        url = authorize_url(deps.settings.spotify_client_id, deps.settings.redirect_uri, state, code_challenge(verifier))
        return RedirectResponse(url)

    @app.get("/callback")
    def callback(code: str | None = None, state: str | None = Query(None), error: str | None = None):
        verifier = pending_logins.pop(state or "", None)
        if error or not code or verifier is None:
            reason = html.escape(error or "estado inválido")
            return HTMLResponse(f"<p>Login não concluído ({reason}). <a href='/login'>Tentar de novo</a></p>", status_code=400)
        deps.auth.exchange_code(code, verifier)
        return RedirectResponse("/")

    @app.get("/api/status")
    def status() -> dict:
        return {"logged_in": deps.auth.has_token(), "claude_ok": deps.claude_ok}

    @app.post("/api/chat")
    def chat(body: ChatIn) -> AgentReply:
        with lock:
            return deps.agent.handle_message(app.state.session, body.text)

    @app.post("/api/choose")
    def choose(body: ChooseIn) -> AgentReply:
        with lock:
            return deps.agent.choose(app.state.session, body.index)

    @app.post("/api/apply")
    def apply(body: ApplyIn) -> AgentReply:
        with lock:
            return deps.agent.apply(app.state.session, body.mode)

    @app.post("/api/undo")
    def undo(body: UndoIn) -> AgentReply:
        with lock:
            return deps.agent.undo(app.state.session, body.undo_id)

    @app.post("/api/reset")
    def reset() -> dict:
        with lock:
            app.state.session = Session()
        return {"ok": True}

    @app.get("/api/stats")
    def stats() -> dict:
        return summarize(deps.trace_path)

    return app
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/web -v`
Expected: 12 passed (2 settings + 1 wiring + 9 app)

- [ ] **Step 5: Commit**

```bash
git add services/web
git commit -m "feat(web): API HTTP local, login PKCE e montagem dos serviços"
```

---

### Task 15: web, interface (HTML/CSS/JS puro) e comando de inicialização

**Files:**
- Create: `services/web/static/index.html`, `services/web/static/style.css`, `services/web/static/app.js`, `services/web/main.py`, `services/web/README.md`
- Test: `services/web/tests/test_static.py`

**Interfaces:**
- Consumes: rotas da Task 14; JSON de `AgentReply` (campos `message`, `state`, `options[].label/description`, `plan.playlists[].name/description/tracks[].track.name/track.artists[].name/tempo/genres/diff.previous_positions/missing_slots`, `plan.bpm_coverage`, `plan.genre_coverage`, `plan.can_replace_in_place`, `result.urls`, `result.undo_id`).
- Produces: comando `uv run playlist-agent` (abre o navegador em `http://127.0.0.1:8000`).

- [ ] **Step 1: Teste que falha, `services/web/tests/test_static.py`**

```python
from fastapi.testclient import TestClient

from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class _Auth:
    def has_token(self):
        return False


def _client(tmp_path):
    deps = AppDeps(agent=None, auth=_Auth(), settings=Settings(spotify_client_id="c"), trace_path=tmp_path / "t", claude_ok=True)
    return TestClient(create_app(deps))


def test_index_and_assets_are_served(tmp_path):
    client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200 and 'id="chat-log"' in page.text and 'lang="pt-BR"' in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_frontend_never_uses_innerhtml(tmp_path):
    # Títulos de música vêm de fora; tudo entra na página como texto (textContent), nunca como HTML.
    assert "innerHTML" not in _client(tmp_path).get("/static/app.js").text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/web/tests/test_static.py -v`
Expected: FAIL (arquivos estáticos ainda não existem)

- [ ] **Step 3: `services/web/static/index.html`**

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Playlist Agent</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <h1>Playlist Agent</h1>
    <span id="status" class="status">verificando...</span>
    <a id="login" class="button" href="/login" hidden>Entrar com Spotify</a>
    <button id="reset" class="ghost" type="button">Nova conversa</button>
  </header>
  <main class="layout">
    <section class="chat">
      <div id="chat-log" class="log" aria-live="polite"></div>
      <form id="composer" class="composer">
        <input id="text" autocomplete="off" placeholder="Ex.: organiza minha playlist Treino por BPM" required>
        <button type="submit">Enviar</button>
      </form>
    </section>
    <section id="preview" class="preview" hidden></section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: `services/web/static/style.css`**

```css
:root {
  --bg: #0f1210;
  --panel: #171b18;
  --line: #2a302b;
  --text: #e8ece9;
  --muted: #98a39b;
  --accent: #1ed760;
  --warn: #f5b942;
  --error: #ff6b6b;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
body.busy { cursor: progress; }
.topbar { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--line); }
.topbar h1 { font-size: 18px; margin: 0 auto 0 0; }
.status { color: var(--muted); font-size: 13px; }
.status.ok { color: var(--accent); }
button, .button {
  background: var(--accent); color: #06130a; border: 0; border-radius: 999px;
  padding: 8px 16px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 14px;
}
button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
button:disabled { opacity: .5; cursor: progress; }
.layout { display: grid; grid-template-columns: minmax(320px, 440px) 1fr; gap: 16px; padding: 16px 20px; height: calc(100vh - 58px); }
.chat { display: flex; flex-direction: column; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; min-height: 0; }
.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.msg { max-width: 90%; padding: 10px 14px; border-radius: 14px; line-height: 1.4; white-space: pre-wrap; }
.msg.user { align-self: flex-end; background: #23412d; }
.msg.agent { align-self: flex-start; background: #222824; }
.msg.pending { color: var(--muted); font-style: italic; }
.msg.error { align-self: stretch; background: #3a1f1f; color: var(--error); }
.options { display: flex; flex-direction: column; gap: 8px; }
.options button { text-align: left; background: #1b231d; color: var(--text); border: 1px solid var(--accent); border-radius: 12px; display: grid; gap: 2px; }
.options button span { color: var(--muted); font-weight: 400; font-size: 13px; }
.composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--line); }
.composer input { flex: 1; background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 10px 14px; font-size: 14px; }
.preview { overflow-y: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 20px; }
.preview h2 { margin-top: 0; }
.card { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
.card h3 { margin: 0 0 4px; }
.meta { color: var(--muted); margin: 0 0 8px; font-size: 13px; }
.warn { color: var(--warn); font-size: 13px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; }
td.missing { color: var(--muted); font-style: italic; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 16px; }
.links { margin: 0; padding-left: 18px; }
.links a { color: var(--accent); }
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; height: auto; }
  .chat { height: 70vh; }
}
```

- [ ] **Step 5: `services/web/static/app.js`**

```js
"use strict";

const log = document.getElementById("chat-log");
const form = document.getElementById("composer");
const input = document.getElementById("text");
const preview = document.getElementById("preview");
const statusEl = document.getElementById("status");
const loginLink = document.getElementById("login");

// Cria elementos só com textContent: títulos de música vêm de fora e nunca viram HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "onclick") node.addEventListener("click", value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    loginLink.hidden = false;
    throw new Error(data.detail || "Faça login no Spotify para continuar.");
  }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Erro ${response.status}`);
  return data;
}

function say(role, text) {
  const node = el("div", { class: `msg ${role}` }, text);
  log.append(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function setBusy(busy) {
  document.body.classList.toggle("busy", busy);
  for (const control of document.querySelectorAll("button, input")) control.disabled = busy;
}

async function run(waitText, call) {
  setBusy(true);
  const pending = say("agent pending", waitText);
  try {
    render(await call());
  } catch (error) {
    say("error", error.message);
  } finally {
    pending.remove();
    setBusy(false);
    input.focus();
  }
}

function render(reply) {
  say("agent", reply.message);
  if (reply.options && reply.options.length) renderOptions(reply.options);
  if (reply.plan) renderPlan(reply.plan);
  if (reply.result) renderResult(reply.result);
}

function renderOptions(options) {
  const box = el("div", { class: "options" });
  options.forEach((option, index) => {
    const pick = () => {
      box.remove();
      say("user", option.label);
      run("Montando a prévia: lendo músicas, buscando BPM e gênero...", () => api("/api/choose", { index }));
    };
    box.append(el("button", { type: "button", onclick: pick }, el("strong", {}, option.label), el("span", {}, option.description)));
  });
  log.append(box);
  log.scrollTop = log.scrollHeight;
}

const pct = (value) => `${Math.round(value * 100)}%`;

function trackRow(item, index, previous) {
  const before = previous === undefined ? "" : previous === null ? "novo" : String(previous + 1);
  return el("tr", {},
    el("td", {}, index + 1),
    el("td", {}, item.track.name),
    el("td", {}, item.track.artists.map((a) => a.name).join(", ")),
    el("td", { class: item.tempo ? "" : "missing" }, item.tempo ? Math.round(item.tempo) : "sem BPM"),
    el("td", { class: item.genres.length ? "" : "missing" }, item.genres[0] || "sem gênero"),
    el("td", {}, before));
}

function renderPlan(plan) {
  preview.replaceChildren(
    el("h2", {}, "Prévia"),
    el("p", { class: "meta" }, `BPM em ${pct(plan.bpm_coverage)} das faixas · gênero em ${pct(plan.genre_coverage)}`));
  for (const playlist of plan.playlists) {
    const previous = playlist.diff ? playlist.diff.previous_positions : null;
    const head = el("thead", {}, el("tr", {}, ...["#", "Música", "Artista", "BPM", "Gênero", "Antes"].map((h) => el("th", {}, h))));
    const body = el("tbody", {}, ...playlist.tracks.map((item, i) => trackRow(item, i, previous ? previous[i] : undefined)));
    const card = el("article", { class: "card" }, el("h3", {}, playlist.name), el("p", { class: "meta" }, playlist.description));
    if (playlist.missing_slots.length) card.append(el("p", { class: "warn" }, `Sem música encontrada: ${playlist.missing_slots.join(", ")}`));
    card.append(el("div", { class: "table-wrap" }, el("table", {}, head, body)));
    preview.append(card);
  }
  const actions = el("div", { class: "actions" },
    el("button", { type: "button", onclick: () => run("Criando no Spotify...", () => api("/api/apply", { mode: "new" })) },
      plan.playlists.length > 1 ? `Criar ${plan.playlists.length} playlists novas` : "Criar playlist nova"));
  if (plan.can_replace_in_place) {
    const replace = () => {
      if (confirm("Substituir a ordem da playlist original? Dá para desfazer depois.")) {
        run("Reordenando a original...", () => api("/api/apply", { mode: "replace" }));
      }
    };
    actions.append(el("button", { type: "button", class: "ghost", onclick: replace }, "Substituir a original"));
  }
  preview.append(actions);
  preview.hidden = false;
}

function renderResult(result) {
  const links = el("ul", { class: "links" },
    ...result.urls.map((url) => el("li", {}, el("a", { href: url, target: "_blank", rel: "noopener" }, "Abrir no Spotify"))));
  const box = el("div", { class: "actions" }, links);
  if (result.undo_id !== null && result.undo_id !== undefined) {
    box.append(el("button", { type: "button", class: "ghost",
      onclick: () => run("Desfazendo...", () => api("/api/undo", { undo_id: result.undo_id })) }, "Desfazer"));
  }
  preview.replaceChildren(el("h2", {}, "Feito"), box);
  preview.hidden = false;
}

function greet() {
  say("agent", "Oi! Posso reorganizar uma playlist sua (por BPM ou por gênero) ou montar uma nova com tema, " +
    "tipo um prédio com Primeiro Andar, Segundo Andar... O que vamos fazer?");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  say("user", text);
  run("Pensando... (o agente leva uns 10 segundos)", () => api("/api/chat", { text }));
});

document.getElementById("reset").addEventListener("click", async () => {
  await api("/api/reset", {});
  log.replaceChildren();
  preview.replaceChildren();
  preview.hidden = true;
  greet();
});

async function boot() {
  try {
    const status = await api("/api/status");
    statusEl.textContent = status.logged_in ? "Spotify conectado" : "Spotify desconectado";
    statusEl.classList.toggle("ok", status.logged_in);
    loginLink.hidden = status.logged_in;
    if (!status.claude_ok) {
      say("error", "Claude Code não encontrado. Rode `claude` no terminal, faça login e reinicie o app.");
    }
  } catch (error) {
    say("error", error.message);
  }
  greet();
}

boot();
```

- [ ] **Step 6: `services/web/main.py`**

```python
"""Ponto de entrada: `uv run playlist-agent`."""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from services.llm.runner import ClaudeRunner
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import build_deps

URL = "http://127.0.0.1:8000"


def main() -> None:
    settings = Settings.from_env()
    claude_ok = ClaudeRunner(model=settings.model).available()
    if not claude_ok:
        print("Aviso: Claude Code não encontrado ou sem login. Rode `claude`, faça login e reinicie.")
    app = create_app(build_deps(settings, claude_ok=claude_ok))
    print(f"Playlist Agent rodando em {URL} (Ctrl+C para parar)")
    threading.Timer(1.5, webbrowser.open, args=[URL]).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest services/web -v`
Expected: 14 passed

- [ ] **Step 8: Checagem visual sem Spotify**

Run: crie `.env` com `SPOTIFY_CLIENT_ID=teste` e rode `uv run playlist-agent`.
Expected: navegador abre em `http://127.0.0.1:8000` com a saudação no chat, status "Spotify desconectado" e botão "Entrar com Spotify". Mandar uma mensagem mostra o erro "Faça login no Spotify..." em vermelho, sem travar a interface. Largura de 400px empilha chat e prévia. Pare com Ctrl+C e apague o `.env` de teste.

- [ ] **Step 9: `services/web/README.md`**

```markdown
# web

Servidor local (FastAPI) em `http://127.0.0.1:8000` e interface em HTML/CSS/JS puro, sem build.

- `settings.py`: lê `.env`.
- `wiring.py`: monta os serviços reais (único arquivo que conhece todos).
- `app.py`: rotas `/login`, `/callback` (OAuth PKCE), `/api/chat|choose|apply|undo|reset|status|stats`.
- `static/`: chat, opções clicáveis, prévia em tabela, botões Criar / Substituir / Desfazer.

Rodar: `uv run playlist-agent`. Testes: `uv run pytest services/web`.
```

- [ ] **Step 10: Commit**

```bash
git add services/web
git commit -m "feat(web): interface de chat com prévia, confirmação e desfazer"
```

---

### Task 16: README, eval de temas e verificação ponta a ponta

**Files:**
- Create: `README.md`, `services/agent/evals/__init__.py`, `services/agent/evals/run_theme.py`
- Modify: `docs/superpowers/specs/2026-09-18-playlist-agent-design.md` (status e resultados medidos)

**Interfaces:**
- Consumes: tudo.
- Produces: README de instalação e uso; eval `uv run python -m services.agent.evals.run_theme`.

- [ ] **Step 1: `services/agent/evals/run_theme.py`** (e `services/agent/evals/__init__.py` com `"""Evals do agente."""`)

```python
"""Eval de temas: o LLM sugere músicas e medimos quantas existem de verdade no Spotify.

Precisa do login feito pelo app (data/token.json). Custa tokens do Claude Code e chamadas ao Spotify.
Uso: uv run python -m services.agent.evals.run_theme
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from contracts.errors import AuthRequired, ExternalServiceError
from services.web.settings import Settings
from services.web.wiring import build_deps

THRESHOLD = 0.7
MAX_SLOTS = 8
THEMES = [
    "andares de um prédio, do térreo à cobertura",
    "dias da semana, de segunda a domingo",
    "cores",
    "números de um a dez",
    "estações do ano",
]


def main() -> int:
    agent = build_deps(Settings.from_env(), claude_ok=True).agent
    rows = []
    for theme in THEMES:
        try:
            plan = agent.llm.plan_theme(theme, MAX_SLOTS)
            resolved = agent.resolver.resolve(plan)
            rows.append({
                "theme": theme, "slots": len(plan.slots),
                "slots_found": sum(t is not None for t in resolved.found),
                "tried": resolved.candidates_tried, "valid": resolved.candidates_valid,
            })
        except AuthRequired:
            print("Faça login pelo app (`uv run playlist-agent`) antes de rodar este eval.")
            return 2
        except ExternalServiceError as err:
            rows.append({"theme": theme, "error": str(err), "slots": 0, "slots_found": 0, "tried": 0, "valid": 0})
    tried = sum(r["tried"] for r in rows)
    valid = sum(r["valid"] for r in rows)
    rate = valid / tried if tried else 0.0
    for r in rows:
        print(f"{r['theme'][:40]:<40} slots {r['slots_found']}/{r['slots']}  candidatas válidas {r['valid']}/{r['tried']}"
              + (f"  ERRO {r['error']}" if "error" in r else ""))
    print(f"\nTaxa de validação das sugestões: {rate:.0%} (limiar {THRESHOLD:.0%})")
    out = Path("data/evals") / f"theme-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rate": rate, "threshold": THRESHOLD, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    return 0 if rate >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: `README.md`**

````markdown
# Playlist Agent

Converse com um agente de IA para criar, organizar e otimizar playlists do Spotify: por BPM, por gênero, ou por temas como o "prédio" (Térreo, Primeiro Andar, Segundo Andar...).

Tudo roda na sua máquina. A IA é o Claude Code instalado localmente; nada é gravado no Spotify sem você clicar em confirmar.

## Como funciona

```
você ──chat──▶ web (FastAPI) ──▶ agent ──▶ llm (claude -p)        entende o pedido e sugere
                                   │──▶ spotify (Web API)          lê e grava playlists
                                   │──▶ enrichment (ReccoBeats,    BPM e gênero
                                   │               Spotify, Last.fm)
                                   └──▶ organizer                  ordena e agrupa (código puro)
```

- O **LLM** faz o que exige interpretação: entender a mensagem, propor modelos, sugerir músicas para um tema.
- O **código** faz o que tem resposta exata: ordenar por BPM, agrupar por gênero, conferir se o título contém "Terceiro Andar".
- Cada serviço vive em `services/<nome>/` com README e testes próprios; eles só conversam pelos contratos em `contracts/`.

## Instalação

Pré-requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), [Claude Code](https://claude.com/claude-code) com login feito (`claude` no terminal), conta Spotify Premium.

1. Crie um app em https://developer.spotify.com/dashboard
   - Redirect URI: `http://127.0.0.1:8000/callback` (exatamente assim; `localhost` não é aceito)
   - APIs: marque "Web API"
   - Copie o **Client ID**
2. (Opcional, melhora os gêneros) Crie uma chave em https://www.last.fm/api/account/create
3. Copie `.env.example` para `.env` e preencha `SPOTIFY_CLIENT_ID` (e `LASTFM_API_KEY`, se tiver).
4. Instale e rode:
   ```bash
   uv sync
   uv run playlist-agent
   ```
5. No navegador, clique em **Entrar com Spotify**.

## Uso

- "organiza minha playlist Treino por BPM"
- "separa a Churrasco em várias playlists por gênero"
- "faz uma playlist prédio com músicas tipo primeiro andar, segundo andar"

O agente propõe opções, você escolhe, vê a prévia (BPM, gênero e posição anterior de cada faixa) e confirma. Por padrão ele cria uma playlist **nova e privada**. "Substituir a original" reordena a sua playlist e oferece **Desfazer**.

## Limites (regras do Spotify de 2026)

- O dono do app no painel do Spotify precisa ter Premium; o app aceita até 5 usuários.
- O Spotify não informa mais BPM: ele vem da ReccoBeats, que não conhece todas as músicas. Faixas sem BPM vão para o fim.
- O app só lê playlists suas ou colaborativas.
- O Spotify não deixa renomear músicas: o tema "prédio" escolhe músicas cujo título já contém o andar.

## Desenvolvimento

```bash
uv run pytest                                   # gate tests (sem rede, < 2s)
uv run python -m services.llm.evals.run_intent  # eval pago: interpretação (limiar 90%)
uv run python -m services.agent.evals.run_theme # eval pago: temas no Spotify real (limiar 70%)
```

Métricas de uso: `data/traces.jsonl`, resumidas em `http://127.0.0.1:8000/api/stats`.
````

- [ ] **Step 3: Suíte inteira e tempo**

Run: `uv run pytest --durations=5`
Expected: tudo passa (contracts 6, organizer 52, spotify 18, enrichment 20, llm 22, agent 30, web 14; 162 no total) e o tempo total fica abaixo de 2s. Se passar de 2s, olhar o `--durations` e corrigir o teste lento (sem `sleep` real, sem rede).

- [ ] **Step 4: Verificação ponta a ponta real** (com o `.env` real do Jone)

Rode `uv run playlist-agent` e faça, anotando o resultado de cada item:
1. Login: "Entrar com Spotify" → autorizar → volta com "Spotify conectado".
2. Crie no Spotify uma playlist de teste "Teste Agente" com ~15 músicas de estilos variados.
3. "organiza a Teste Agente por BPM" → escolher "BPM crescente" → prévia com BPM crescente e coluna "Antes" → "Criar playlist nova" → abrir o link: ordem no Spotify igual à prévia.
4. "divide a Teste Agente por gênero" → várias playlists na prévia → criar → conferir no Spotify.
5. "faz uma playlist prédio" → prévia com pelo menos 5 andares encontrados → criar → conferir títulos.
6. "organiza a Teste Agente por BPM decrescente" → "Substituir a original" → conferir no Spotify → "Desfazer" → a ordem original voltou.
7. Abra `http://127.0.0.1:8000/api/stats`: `llm_calls`, `avg_bpm_coverage` e `theme_validation_rate` preenchidos.

Qualquer divergência: parar, usar superpowers:systematic-debugging, escrever o teste que reproduz, corrigir.

- [ ] **Step 5: Evals**

Run: `uv run python -m services.llm.evals.run_intent` e `uv run python -m services.agent.evals.run_theme`
Expected: intenção >= 90%, validação de temas >= 70%. Abaixo disso: ajustar `services/llm/prompts/*.md` com base nos casos que falharam (nunca afrouxar casos nem limiares) e rodar de novo.

- [ ] **Step 6: Atualizar a spec com o que foi medido**

Em `docs/superpowers/specs/2026-09-18-playlist-agent-design.md`, trocar a linha de status para `Status: implementado` e adicionar ao final:

```markdown
## Resultados medidos (preencher com os números reais)
- Gate tests: N testes, X s.
- Eval de intenção: X% (limiar 90%). Relatório: data/evals/intent-....json
- Eval de temas: X% (limiar 70%). Relatório: data/evals/theme-....json
- Ponta a ponta (Task 16, Step 4): itens 1 a 7 OK / falhas encontradas e corrigidas.
- Cobertura média de BPM na playlist de teste: X%.
```

- [ ] **Step 7: Commit final e merge (modo solo)**

```bash
git add README.md services/agent/evals docs
git commit -m "docs: README, eval de temas e resultados medidos"
git switch main
git merge --no-ff playlist-agent-mvp
```

Não há remote configurado: nada de push. Se o Jone criar um repositório no GitHub, `git remote add origin <url>` e `git push -u origin main`.
