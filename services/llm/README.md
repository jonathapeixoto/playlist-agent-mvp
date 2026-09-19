# llm

Chama o Claude Code local (`claude -p`) com `--json-schema`, `--system-prompt` próprio e `--tools ""`. Nada de API paga.

- `runner.py`: executa o comando, mede latência e custo, transforma falhas em `LLMError`.
- `structured.py`: gera o JSON Schema a partir dos modelos pydantic e valida a resposta (1 nova tentativa com o erro no prompt).
- `api.py`: `interpret` (mensagem vira `Intent`) e `plan_theme` (tema vira `ThemePlan`).
- `prompts/`: prompts versionados em markdown. Mudou prompt, rode o eval.

Gate tests: `uv run pytest services/llm` (sem chamar o Claude).
Eval pago: `uv run python -m services.llm.evals.run_intent` (25 casos, limiar 90%, relatório em `data/evals/`).
