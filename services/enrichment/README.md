# enrichment

Completa cada faixa com BPM, energia e gêneros.

- BPM e energia: ReccoBeats (`GET /v1/audio-features?ids=`, até 40 IDs do Spotify, sem login). O Spotify removeu esse dado da API em nov/2024.
- Gênero: `GET /artists/{id}` do Spotify (artista principal). Se vier vazio ou falhar, tags do Last.fm (`LASTFM_API_KEY`), filtrando tags que não são gênero ("seen live", "90s").
- Cache SQLite em `data/cache.sqlite`. Acertos não expiram; "sem dado" expira em 7 dias; falha de rede não é cacheada.

Testes: `uv run pytest services/enrichment`
