"""Máquina de estados da conversa. O LLM entende e sugere; o código decide, ordena e só escreve após confirmação."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from contracts.errors import ExternalServiceError
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
        incomplete = False
        if choice.kind is StrategyKind.THEME:
            plan = self._plan_theme(choice)
        else:
            if s.source is None:
                raise AgentError("Diga qual playlist organizar.")
            tracks = self.spotify.playlist_tracks(s.source.id)
            if not tracks:
                raise AgentError(f'A playlist "{s.source.name}" está vazia.')
            plan = plan_reorganize(choice, s.source, self.enricher.enrich(tracks))
            if len(tracks) != s.source.total:
                incomplete = True
                plan = plan.model_copy(update={"source_playlist_id": None})
        s.history.append(("usuário", f"Escolhi: {choice.label}"))
        s.plan = plan
        self.tracer(
            "plan", kind=choice.kind.value, playlists=len(plan.playlists),
            tracks=sum(len(p.tracks) for p in plan.playlists),
            bpm_coverage=round(plan.bpm_coverage, 3), genre_coverage=round(plan.genre_coverage, 3),
        )
        message = describe_plan(plan)
        if incomplete:
            message += (
                " A playlist tem itens que o app não consegue ler (arquivos locais ou podcasts),"
                " então só dá para criar uma playlist nova."
            )
        return self._say(s, message, State.PREVIEW, plan=plan)

    def apply(self, s: Session, mode: ApplyMode) -> AgentReply:
        if s.state is not State.PREVIEW or s.plan is None:
            raise AgentError("Nada para aplicar. Gere uma prévia primeiro.")
        plan = s.plan
        if mode is ApplyMode.REPLACE:
            if not plan.can_replace_in_place or plan.source_playlist_id is None:
                raise AgentError("Este plano só pode criar playlists novas.")
            pid = plan.source_playlist_id
            current = self.spotify.playlist_tracks(pid)
            fresh = next((p for p in self.spotify.my_playlists() if p.id == pid), None)
            planned_uris = [t.track.uri for t in plan.playlists[0].tracks]
            if (
                fresh is None
                or fresh.total != len(current)
                or Counter(t.uri for t in current) != Counter(planned_uris)
            ):
                raise AgentError(
                    "A playlist mudou desde a prévia ou tem itens que o app não lê."
                    " Gere a prévia de novo ou crie uma playlist nova."
                )
            undo_id = self.undo_store.save(pid, [t.uri for t in current])
            url = f"https://open.spotify.com/playlist/{pid}"
            try:
                self.spotify.replace_items(pid, planned_uris)
            except ExternalServiceError:
                s.plan = None
                self.tracer("apply_failed", mode=mode.value)
                return self._say(
                    s,
                    "Deu erro no meio da gravação e a playlist pode ter ficado incompleta."
                    " Use Desfazer para voltar à ordem original.",
                    State.APPLIED,
                    result=ApplyResult(mode=mode, playlist_ids=[pid], urls=[url], undo_id=undo_id),
                )
            result = ApplyResult(mode=mode, playlist_ids=[pid], urls=[url], undo_id=undo_id)
            message = "Pronto: a playlist original foi reordenada. Se não gostar, use Desfazer."
        else:
            ids: list[str] = []
            urls: list[str] = []
            names: list[str] = []
            try:
                for planned in plan.playlists:
                    if not planned.tracks:
                        continue
                    pid, url = self.spotify.create_playlist(planned.name, planned.description)
                    self.spotify.replace_items(pid, [t.track.uri for t in planned.tracks])
                    ids.append(pid)
                    urls.append(url)
                    names.append(planned.name)
            except ExternalServiceError:
                if names:
                    s.plan = None
                    s.state = State.APPLIED
                    self.tracer("apply_failed", mode=mode.value)
                    raise AgentError(
                        f"Falhou no meio da gravação. Já criei: {', '.join(names)}."
                        " Confira no Spotify antes de tentar de novo."
                    ) from None
                raise
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
