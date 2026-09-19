# organizer

Lógica pura de organização. Sem rede, sem LLM, sem estado: mesma entrada, mesma saída.

- `text.py`: normaliza títulos (acentos, caixa, "1º" = "Primeiro" = "First") e casa keywords de tema.
- `theme.py`: `pick_match` escolhe a primeira faixa cujo título contém uma keyword.
- `bpm.py`: ordena por BPM (crescente, decrescente, arco). Sem BPM vai para o fim.
- `genre.py`: agrupa por família de gênero (tabela ordenada por especificidade) ou subgênero.
- `diff.py`: posição anterior de cada faixa, para a prévia.
- `planner.py`: junta tudo em `PlaylistPlan`.

Testes: `uv run pytest services/organizer`
