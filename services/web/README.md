# web

Servidor local (FastAPI) em `http://127.0.0.1:8000` e interface em HTML/CSS/JS puro, sem build.

- `settings.py`: lê `.env`.
- `wiring.py`: monta os serviços reais (único arquivo que conhece todos).
- `app.py`: rotas `/login`, `/callback` (OAuth PKCE), `/api/chat|choose|apply|undo|reset|status|stats`.
- `static/`: chat, opções clicáveis, prévia em tabela, botões Criar / Substituir / Desfazer.

Rodar: `uv run playlist-agent`. Testes: `uv run pytest services/web`.
