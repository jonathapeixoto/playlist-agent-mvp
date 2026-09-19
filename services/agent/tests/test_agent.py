import pytest

from contracts.errors import ExternalServiceError
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
        self.fail_replace_once = False
        self.fail_create_index = None

    def my_playlists(self):
        return self.playlists

    def playlist_tracks(self, pid):
        return list(self.tracks[pid])

    def create_playlist(self, name, description):
        if self.fail_create_index is not None and len(self.created) == self.fail_create_index:
            raise ExternalServiceError("Spotify fora do ar")
        pid = f"new{len(self.created)}"
        self.created.append((pid, name))
        return pid, f"https://open.spotify.com/playlist/{pid}"

    def replace_items(self, pid, uris):
        if self.fail_replace_once:
            self.fail_replace_once = False
            raise ExternalServiceError("Spotify fora do ar")
        self.replaced.append((pid, list(uris)))
        self.tracks[pid] = [_t(u.rsplit(":", 1)[-1]) for u in uris]


class FakeEnricher:
    TEMPO = {"a": 100, "b": 120, "c": 140, "x": 90, "d": 110, "e": 130, "f": 150}
    GENRES = {
        "a": ["rock"], "b": ["rock"], "c": ["pagode"], "x": [],
        "d": ["rock"], "e": ["pagode"], "f": ["pagode"],
    }

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


# F1: replace-in-place não pode apagar itens que o app não enxerga nem gravar em cima
# de uma playlist que mudou desde a prévia.

def test_choose_marks_plan_non_replaceable_when_playlist_has_unreadable_items(world):
    world["spotify"].playlists[0] = PlaylistSummary(id="src", name="Treino", total=4, owner_id="me")
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    reply = agent.choose(s, 0)
    assert reply.plan.can_replace_in_place is False
    assert "não consegue ler" in reply.message
    with pytest.raises(AgentError):
        agent.apply(s, ApplyMode.REPLACE)
    assert world["spotify"].created == [] and world["spotify"].replaced == []


def test_apply_replace_refused_when_playlist_changed_since_preview(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    world["spotify"].tracks["src"] = [_t("z"), _t("a"), _t("c")]
    with pytest.raises(AgentError):
        agent.apply(s, ApplyMode.REPLACE)
    assert world["spotify"].created == [] and world["spotify"].replaced == []


def test_apply_replace_still_works_when_nothing_changed(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    reply = agent.apply(s, ApplyMode.REPLACE)
    assert reply.state is ConversationState.APPLIED
    assert [t.id for t in world["spotify"].tracks["src"]] == ["a", "b", "c"]


# F2: falha no meio da gravação do replace-in-place não pode deixar o usuário sem o undo_id.

def test_apply_replace_failure_still_returns_undo_id_for_undo(world):
    agent, _ = world["make"]([_reorganize()])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    world["spotify"].fail_replace_once = True
    reply = agent.apply(s, ApplyMode.REPLACE)
    assert reply.state is ConversationState.APPLIED
    assert reply.result.undo_id is not None
    assert "Desfazer" in reply.message
    agent.undo(s, reply.result.undo_id)
    assert [t.id for t in world["spotify"].tracks["src"]] == ["b", "a", "c"]


# F3: falha no meio de "criar novas" não pode permitir criar duplicadas numa nova tentativa.

def test_apply_new_partial_failure_blocks_retry_and_names_created(world):
    world["spotify"].playlists[0] = PlaylistSummary(id="src", name="Treino", total=6, owner_id="me")
    world["spotify"].tracks["src"] = [_t("a"), _t("b"), _t("d"), _t("c"), _t("e"), _t("f")]
    agent, _ = world["make"]([_reorganize(options=[SPLIT])])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    world["spotify"].fail_create_index = 1
    with pytest.raises(AgentError) as exc:
        agent.apply(s, ApplyMode.NEW)
    assert "Já criei" in str(exc.value)
    assert len(world["spotify"].created) == 1
    assert s.state is ConversationState.APPLIED
    assert s.plan is None
    with pytest.raises(AgentError):
        agent.apply(s, ApplyMode.NEW)
    assert len(world["spotify"].created) == 1


def test_apply_new_failure_before_any_create_keeps_preview_for_retry(world):
    world["spotify"].playlists[0] = PlaylistSummary(id="src", name="Treino", total=6, owner_id="me")
    world["spotify"].tracks["src"] = [_t("a"), _t("b"), _t("d"), _t("c"), _t("e"), _t("f")]
    agent, _ = world["make"]([_reorganize(options=[SPLIT])])
    s = Session()
    agent.handle_message(s, "x")
    agent.choose(s, 0)
    world["spotify"].fail_create_index = 0
    with pytest.raises(ExternalServiceError):
        agent.apply(s, ApplyMode.NEW)
    assert s.state is ConversationState.PREVIEW
    assert s.plan is not None
    assert world["spotify"].created == []
    world["spotify"].fail_create_index = None
    reply = agent.apply(s, ApplyMode.NEW)
    assert reply.state is ConversationState.APPLIED
    assert len(world["spotify"].created) == 2
