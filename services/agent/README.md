# agent

Orquestra a conversa. Estados: `understand` → `propose` → `preview` → `applied`.

- `handle_message`: o LLM interpreta; o código acha a playlist (`lookup.py`) e filtra as opções válidas.
- `choose`: carrega faixas, enriquece (BPM/gênero) e monta o plano com o `organizer`. Tema: o LLM sugere, o `theme_resolver` valida cada título no Spotify.
- `apply`: única etapa que escreve no Spotify. Padrão cria playlist nova (privada); `replace` salva snapshot para `undo`.
- `trace.py`: cada etapa grava uma linha em `data/traces.jsonl`; `summarize` alimenta `/api/stats`.

Testes: `uv run pytest services/agent` (LLM, Spotify e enrichment falsos).
