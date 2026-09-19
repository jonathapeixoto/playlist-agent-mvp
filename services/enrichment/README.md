# enrichment

Completa cada faixa com BPM, energia e gêneros.

- BPM e energia: ReccoBeats (`GET /v1/audio-features?ids=`, até 40 IDs do Spotify, sem login). O Spotify removeu esse dado da API em nov/2024.
- Versões alternativas: a ReccoBeats guarda BPM por ID do Spotify, e a mesma gravação costuma ter vários IDs (single, álbum, coletânea). Quando o ID da playlist não tem BPM, `alternates.py` busca no Spotify outras versões do mesmo artista, com o mesmo título e duração até 2s diferente, e usa o BPM delas. Até 100 buscas por lote, 4 em paralelo; se o Spotify falhar, as buscas param e nada é cacheado como "sem BPM".
- Gênero: `GET /artists/{id}` do Spotify (artista principal). Se vier vazio ou falhar, tags do Last.fm (`LASTFM_API_KEY`), filtrando tags que não são gênero ("seen live", "90s").
- Cache SQLite em `data/cache.sqlite`. Acertos não expiram; "sem dado" expira em 7 dias; falha de rede não é cacheada.

Testes: `uv run pytest services/enrichment`
Eval (pago em chamadas reais, precisa de login): `uv run python -m services.enrichment.evals.run_bpm_coverage [playlist ...]`. Mede a cobertura de BPM sem e com versões alternativas; passa com >= 85% e ganho real. Medido em 19/09/2026 nas playlists do Jone (482 faixas): 86% -> 93%.
