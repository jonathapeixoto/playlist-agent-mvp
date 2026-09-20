# Playlist Agent

Um agente de IA que organiza suas playlists do Spotify por conversa. Você diz o que quer, ele propõe algumas formas de organizar, mostra como ficaria e só grava depois que você confirmar.

Dá para ordenar por andamento, agrupar por gênero, separar uma playlist grande em várias, ou montar uma playlist nova a partir de um tema, escolhendo músicas cujo título combina com a ideia.

Tudo roda na sua máquina, com o Claude Code que você já tem instalado.

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
- "quero uma playlist em que os títulos das músicas contem uma história"

O agente propõe opções, você escolhe, vê a prévia (BPM, gênero e posição anterior de cada faixa) e confirma. Por padrão ele cria uma playlist **nova e privada**. "Substituir a original" reordena a sua playlist e oferece **Desfazer**.

## Limites (regras do Spotify de 2026)

- O dono do app no painel do Spotify precisa ter Premium; o app aceita até 5 usuários.
- O Spotify não informa mais BPM: ele vem da ReccoBeats, que não conhece todas as músicas. Faixas sem BPM vão para o fim.
- O app só lê playlists suas ou colaborativas.
- O Spotify não deixa renomear músicas: o tema "prédio" escolhe músicas cujo título já contém o andar.
- `data/` (token do Spotify, cache e traces) fica dentro da pasta do projeto e está no `.gitignore`. Se a pasta estiver no OneDrive, esses arquivos também são sincronizados; mova o projeto para fora do OneDrive se preferir mantê-los só na máquina.

## Desenvolvimento

```bash
uv run pytest                                   # gate tests (sem rede, < 2s)
uv run python -m services.llm.evals.run_intent  # eval pago: interpretação (limiar 90%)
uv run python -m services.agent.evals.run_theme # eval pago: temas no Spotify real (limiar 70%)
```

Métricas de uso: `data/traces.jsonl`, resumidas em `http://127.0.0.1:8000/api/stats`.
