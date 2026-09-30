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
