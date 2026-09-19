# spotify

Login OAuth PKCE (`auth.py`) e cliente da Web API (`client.py`) já nas regras de fevereiro de 2026:

- itens de playlist em `/playlists/{id}/items`, faixa em `item`;
- criar playlist com `POST /me/playlists` (privada por padrão);
- busca com no máximo 10 resultados por página;
- só lê playlists próprias ou colaborativas;
- sem endpoints em lote: gênero é buscado artista por artista (e cacheado pelo `enrichment`).

Retry: 429 e 5xx respeitam `Retry-After` até 3 vezes; 401 renova o token uma vez.

Testes: `uv run pytest services/spotify` (HTTP simulado com respx, sem rede).
