"""Exceções que atravessam fronteiras de serviço."""


class AuthRequired(Exception):
    """O usuário precisa (re)fazer login no Spotify."""


class ExternalServiceError(Exception):
    """Falha em serviço externo (Spotify, ReccoBeats, Last.fm, Claude Code). A mensagem é mostrável ao usuário."""
