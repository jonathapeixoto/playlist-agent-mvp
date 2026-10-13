# llm

Chama o Claude Code local (`claude -p`) com `--json-schema`, `--system-prompt` próprio e `--tools ""`. Nada de API paga.

- `providers/claude_code.py`: Claude Code local (`claude -p`), sem chave.
- `providers/openai_compatible.py`: qualquer API no formato da OpenAI (Gemini, Groq, OpenRouter, Mistral, Ollama, LM Studio).
- `registry.py`: atalhos de provedor (endereço, modelo sugerido, onde pegar a chave).
- `config_store.py`: a escolha do usuário em `data/llm.json`.
- `factory.py`: monta o runner a partir da configuração.
- `structured.py`: schema JSON a partir dos modelos pydantic, com uma nova tentativa em caso de resposta inválida.
- `api.py`: `interpret` e `plan_theme`, com troca de motor em tempo de execução.
- `prompts/`: prompts versionados em markdown. Mudou prompt, rode o eval.

Gate tests: `uv run pytest services/llm` (sem chamar o Claude).
Eval pago: `uv run python -m services.llm.evals.run_intent` (25 casos, limiar 90%, relatório em `data/evals/`).
