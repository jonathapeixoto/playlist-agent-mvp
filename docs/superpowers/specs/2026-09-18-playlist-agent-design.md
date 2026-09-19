# Spec: Playlist Agent

Data: 2026-09-18 · Status: implementado (verificação real pendente)

## Contexto

Jone quer um app em que ele conversa com um agente de IA, o agente entende o pedido, sugere modelos de organização (BPM, gênero/subgênero, temas divertidos como o "prédio": Primeiro Andar, Segundo Andar...) e, após confirmação, cria ou edita playlists no Spotify. A pasta está vazia (só CLAUDE.md), então é projeto novo, caminho arquitetural.

Decisões do Jone: tem Spotify Premium; escopo = reorganizar playlists existentes E descobrir músicas novas; linguagem Python.

Restrições externas verificadas (set/2026):
- Spotify removeu `audio-features` e `recommendations` (nov/2024). BPM vem de fonte externa (ReccoBeats, aceita ID do Spotify). Sugestão de músicas novas vem do LLM, validada na busca do Spotify.
- Modo dev (fev/2026): dono precisa de Premium, máx. 5 usuários, busca com `limit` máx. 10 (paginar com `offset`), `/tracks` virou `/items`, criar playlist = `POST /me/playlists`, conteúdo só de playlists próprias/colaborativas, sem endpoints em lote (`GET /artists` em lote removido; `GET /artists/{id}` individual continua).
- Spotify não permite renomear faixas: o tema "prédio" funciona escolhendo músicas cujo título já contém o andar.
- CLAUDE.md: LLM via Claude Code local (`claude -p`), nunca API paga; melhor modelo disponível; serviços independentes com contratos; testes + evals no mesmo commit.

## Arquitetura

App local: servidor Python em `http://127.0.0.1:8000`, interface web em HTML/JS puro. Local porque o Claude Code roda na máquina do Jone e o Spotify exige redirect em IP de loopback (`127.0.0.1`, não `localhost`).

Divisão latente vs determinística (regra do CLAUDE.md):
- **Latente (LLM):** entender a mensagem, propor modelos de organização, sugerir músicas para temas, escrever nomes/descrições criativas.
- **Determinístico (código):** ordenar por BPM, agrupar por gênero, casar título com tema ("andar 3" == "Terceiro Andar"), chamadas de API, diff da playlist.

```
contracts/            modelos pydantic compartilhados (Track, EnrichedTrack, Intent, Strategy, PlaylistPlan, PlaylistDiff)
services/
  spotify/            OAuth PKCE, cliente httpx fino, tokens em arquivo local
  enrichment/         BPM (ReccoBeats) + gênero (Spotify artist genres, fallback Last.fm tags) + cache SQLite
  organizer/          estratégias puras: bpm (crescente, decrescente, arco/rampa), gênero (agrupar ou dividir em várias playlists), tema sequencial (prédio e similares)
  llm/                wrapper de `claude -p --output-format json`, prompts versionados, validação pydantic + 1 retry
  agent/              orquestrador da conversa (máquina de estados)
  web/                FastAPI + estático (chat, prévia, botão confirmar/desfazer)
docs/superpowers/specs/  spec escrita após aprovação
```

Cada serviço tem `README.md`, `tests/` e, quando usa LLM, `evals/`.

### Stack (Layer 1, tried-and-true)
- Python 3.12, `uv` para ambiente/dependências.
- FastAPI + uvicorn (servidor), httpx (HTTP), pydantic (contratos), sqlite3 da stdlib (cache e histórico), pytest + respx (mock de HTTP).
- Sem spotipy: ainda usa endpoints renomeados/removidos em fev/2026. Cliente próprio de ~10 endpoints é menor que remendar a lib. Checar de novo no início da implementação; se spotipy estiver atualizado, usar.
- Last.fm API (chave grátis) como fallback de gênero, porque muitos artistas vêm com `genres` vazio no Spotify.

## Fluxo da conversa (services/agent)

Estados: `ENTENDER -> PROPOR -> PREVIA -> CONFIRMAR -> APLICAR`.

1. Jone escreve ("organiza minha playlist Treino por BPM" / "faz uma playlist prédio").
2. `llm.interpret(message, contexto)` devolve um `Intent` estruturado: fonte (playlist existente X | descoberta), estratégia candidata, parâmetros faltando.
3. Se faltar algo, o agente pergunta. Senão propõe 2-3 modelos (ex.: "BPM crescente", "arco: sobe e desce", "dividir por subgênero").
4. Jone escolhe. Código carrega faixas, enriquece (BPM/gênero), aplica a estratégia e gera `PlaylistPlan` + `PlaylistDiff`.
5. Prévia na tela: ordem nova, BPM/gênero de cada faixa, faixas sem dado marcadas.
6. Confirmar: padrão = **criar playlist nova** ("Treino · por BPM"). Opção de reordenar a original in place, com snapshot da ordem antiga no SQLite e botão **Desfazer**.

Fluxo de descoberta (tema "prédio"):
- LLM gera slots ordenados (`Primeiro Andar`, `Segundo Andar`, ... ou `Térreo`, `Cobertura`) e 3-5 candidatos (título, artista) por slot.
- Código busca cada candidato no Spotify e aceita só se o título normalizado (sem acento, minúsculo, número por extenso ou dígito) contém a palavra-chave do slot. Primeiro procura nas playlists do próprio Jone.
- Slot sem match: busca direta pelo nome do slot no Spotify; se ainda falhar, o slot é pulado e aparece na prévia como "sem música encontrada".

## Tratamento de erros
- Token expirado: refresh automático; refresh falhou: volta para tela de login.
- 429 do Spotify/ReccoBeats: respeitar `Retry-After`, backoff exponencial, máx. 3 tentativas.
- Faixa sem BPM: vai para o fim, agrupada como "sem BPM", nunca some da playlist.
- BPM dobrado/metade (ex.: 70 vs 140): opção "normalizar tempo" dobra valores abaixo de 90 antes de ordenar (determinístico, testado).
- LLM devolve JSON inválido: 1 retry com o erro de validação no prompt; falhou de novo: mensagem clara no chat.
- `claude` não instalado/logado: checagem no startup com instrução de correção.
- Nada é escrito no Spotify sem confirmação explícita na interface.

## Medição (outcome + trace)
Log JSONL em `data/traces.jsonl` por interação, com:
- acerto de intenção (eval), cobertura de BPM (% de faixas com tempo), cobertura de gênero, taxa de validação de sugestões do LLM (% de candidatos achados no Spotify), latência do LLM.
- Página `/stats` simples lendo esse arquivo.

## Testes e evals
- **Gate tests (pytest, sem rede, <2s):** organizer (ordenações, arco, agrupamento, casamento de títulos com números por extenso), spotify (paginação, renomeados `/items`, refresh, 429) com respx, enrichment (cache, fallback Last.fm), agent (transições de estado com LLM fake), contratos. Pre-commit hook roda a suíte.
- **Evals (pagos em tokens do Claude Code, manuais/antes de ship):**
  - `llm/evals/intent`: ~25 mensagens em português com intenção esperada, limiar 90%.
  - `llm/evals/theme`: 5 temas (prédio, dias da semana, cores, números, estações), limiar 70% de candidatos validados no Spotify real.

## Setup que o Jone fará (vou documentar passo a passo no README)
1. Criar app em developer.spotify.com, redirect URI `http://127.0.0.1:8000/callback`.
2. Criar chave Last.fm em last.fm/api.
3. `.env` com `SPOTIFY_CLIENT_ID`, `LASTFM_API_KEY` (PKCE dispensa client secret). `.gitignore` cobre `.env` e `data/`.
4. `uv sync` e `uv run playlist-agent`.

## Verificação ponta a ponta
- `uv run pytest` verde.
- Evals rodados, scores registrados.
- Teste manual real: login Spotify; reorganizar uma playlist de teste por BPM (checar ordem no app do Spotify); dividir por gênero; criar playlist "prédio" com pelo menos 5 andares validados; reordenar in place e usar Desfazer, conferindo que a ordem original voltou.

## Resultados medidos

- Gate tests: 166 testes, 1.34s.
- Eval de intenção: 100% (25/25, limiar 90%). Relatório: data/evals/intent-20260919-010243.json
- Eval de temas: pendente (precisa de login no Spotify: `uv run python -m services.agent.evals.run_theme`).
- Ponta a ponta: pendente (roteiro no plano, Task 16 Step 4).
- Cobertura média de BPM: pendente (medida no teste ponta a ponta).
