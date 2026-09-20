# Motor de IA plugável: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deixar quem usa escolher o motor de IA (Claude Code local ou qualquer API compatível com OpenAI), validado por um teste de compatibilidade que bloqueia motores que não atendem ao formato que o app precisa.

**Architecture:** o agente continua falando com `contracts.ports.LLMPort`. O serviço `services/llm` ganha dois adaptadores (`providers/claude_code.py` e `providers/openai_compatible.py`), presets de provedores, armazenamento local da configuração, uma fábrica que monta o runner e um teste de compatibilidade de 3 chamadas. A troca de motor vale na chamada seguinte, sem reiniciar.

**Tech Stack:** Python 3.12+, httpx, pydantic v2, FastAPI, pytest + respx, HTML/CSS/JS puro.

**Spec:** `docs/superpowers/specs/2026-09-19-motor-de-ia-plugavel-design.md`

## Global Constraints

- Nada em `contracts/ports.py`, `services/agent`, `services/organizer`, `services/spotify` ou `services/enrichment` muda de comportamento.
- Gate tests: sem rede, sem subprocess real, suíte inteira abaixo de 2s. Evals (pagos) são scripts separados, nunca coletados pelo pytest.
- A chave do provedor nunca sai do servidor: a API devolve `has_key: true|false`, nunca o valor.
- Configuração em `data/llm.json` (git-ignored, junto do token do Spotify). Arquivo ausente ou corrompido significa "sem configuração", nunca erro na inicialização.
- Sem configuração salva, o motor é o Claude Code local com o modelo de `Settings.model` ("opus"), o comportamento de hoje.
- Textos de interface e mensagens de erro em português do Brasil, sem travessão.
- Erros de motor sobem como `contracts.errors.ExternalServiceError` (o `LLMError` já é subclasse), que a camada web mapeia para 502; nada é gravado no Spotify quando a IA falha.
- Um modelo por motor. Modelo diferente por tarefa está fora do escopo.
- `cost_usd` só é confiável no Claude Code; motores compatíveis com OpenAI reportam 0.

## Mapa de arquivos

```
contracts/models.py                      + ProviderKind, LLMConfig
services/llm/
  runner.py                              passa a conter só LLMError e RunResult (tipos compartilhados)
  providers/__init__.py
  providers/claude_code.py               ClaudeRunner (movido de runner.py)
  providers/openai_compatible.py         OpenAICompatibleRunner (novo)
  registry.py                            PRESETS + find()
  config_store.py                        LLMConfigStore (data/llm.json)
  factory.py                             build_runner(), describe()
  scoring.py                             score_intent (movido de evals/scoring.py)
  compat.py                              CompatCheck, CompatReport, check()
  api.py                                 ClaudeLLM -> AgentLLM, com set_runner() e trace de provider/model
  evals/run_intent.py                    usa o motor configurado; aceita override por variável de ambiente
services/agent/trace.py                  summarize ganha llm_by_provider
services/web/
  wiring.py                              monta AgentLLM a partir da configuração salva
  app.py                                 GET /api/llm, POST /api/llm/test, POST /api/llm
  static/index.html, app.js, style.css   painel "Motor de IA"
README.md                                seção sobre escolher o motor
```

## Ordem

Task 1 (contratos e armazenamento) primeiro. Tasks 2 e 3 (adaptadores) podem sair em qualquer ordem depois dela. Task 4 depende de 2 e 3; Task 5 depende de 4; Tasks 6 e 7 dependem de 5; Task 8 fecha.

---

### Task 1: contratos da configuração, presets e armazenamento

**Files:**
- Modify: `contracts/models.py` (acrescentar ao fim, antes de nenhuma classe existente ser alterada)
- Create: `services/llm/registry.py`, `services/llm/config_store.py`
- Test: `contracts/tests/test_models.py` (acrescentar), `services/llm/tests/test_registry.py`, `services/llm/tests/test_config_store.py`

**Interfaces:**
- Produces: `contracts.models.ProviderKind` (`CLAUDE_CODE = "claude_code"`, `OPENAI = "openai_compatible"`); `contracts.models.LLMConfig(provider, model, base_url="", api_key="", preset="claude_code")` com `to_public_dict() -> dict` (sem a chave, com `has_key: bool`); `services.llm.registry.Preset(key, label, base_url, model, needs_key, help_url)`, `PRESETS: tuple[Preset, ...]`, `find(key: str) -> Preset | None`; `services.llm.config_store.LLMConfigStore(path)` com `load() -> LLMConfig | None` e `save(config: LLMConfig) -> None`.

- [ ] **Step 1: Testes que falham**

Acrescentar em `contracts/tests/test_models.py`:
```python
def test_llm_config_public_dict_hides_the_key():
    from contracts.models import LLMConfig, ProviderKind

    config = LLMConfig(provider=ProviderKind.OPENAI, model="gemini-2.5-flash",
                       base_url="https://exemplo/v1", api_key="segredo", preset="gemini")
    public = config.to_public_dict()
    assert public == {
        "provider": "openai_compatible", "model": "gemini-2.5-flash",
        "base_url": "https://exemplo/v1", "preset": "gemini", "has_key": True,
    }
    assert "segredo" not in str(public)


def test_llm_config_without_key_reports_has_key_false():
    from contracts.models import LLMConfig, ProviderKind

    assert LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus").to_public_dict()["has_key"] is False
```

`services/llm/tests/test_registry.py`:
```python
import pytest

from services.llm.registry import PRESETS, find


def test_every_preset_has_label_and_model_except_custom():
    for preset in PRESETS:
        assert preset.key and preset.label
        if preset.key != "custom":
            assert preset.model
            assert preset.base_url or preset.key == "claude_code"


@pytest.mark.parametrize("key", ["gemini", "groq", "openrouter", "mistral"])
def test_remote_presets_need_a_key_and_point_to_where_to_get_it(key):
    preset = find(key)
    assert preset.needs_key and preset.help_url.startswith("https://")
    assert preset.base_url.startswith("https://")


@pytest.mark.parametrize("key", ["ollama", "lmstudio"])
def test_local_presets_need_no_key(key):
    preset = find(key)
    assert not preset.needs_key
    assert preset.base_url.startswith("http://127.0.0.1")


def test_claude_code_preset_has_no_base_url_and_no_key():
    preset = find("claude_code")
    assert preset.base_url == "" and not preset.needs_key


def test_find_unknown_key():
    assert find("inventado") is None
```

`services/llm/tests/test_config_store.py`:
```python
from contracts.models import LLMConfig, ProviderKind
from services.llm.config_store import LLMConfigStore


def _config():
    return LLMConfig(provider=ProviderKind.OPENAI, model="llama-3.3-70b-versatile",
                     base_url="https://api.groq.com/openai/v1", api_key="k-123", preset="groq")


def test_round_trip(tmp_path):
    store = LLMConfigStore(tmp_path / "llm.json")
    assert store.load() is None
    store.save(_config())
    loaded = store.load()
    assert loaded == _config()
    assert loaded.api_key == "k-123"


def test_corrupted_file_means_no_configuration(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text("isso não é json", encoding="utf-8")
    assert LLMConfigStore(path).load() is None


def test_file_with_unknown_provider_means_no_configuration(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text('{"provider": "telepatia", "model": "x"}', encoding="utf-8")
    assert LLMConfigStore(path).load() is None


def test_save_creates_the_directory(tmp_path):
    store = LLMConfigStore(tmp_path / "sub" / "llm.json")
    store.save(_config())
    assert store.load().preset == "groq"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest contracts services/llm -q`
Expected: FAIL com `ImportError` de `LLMConfig` e `ModuleNotFoundError` de `services.llm.registry` e `services.llm.config_store`

- [ ] **Step 3: Implementar os contratos**

Acrescentar ao fim de `contracts/models.py`:
```python
class ProviderKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    OPENAI = "openai_compatible"


class LLMConfig(BaseModel):
    """Motor de IA escolhido pelo usuário. A chave fica só no servidor."""

    provider: ProviderKind
    model: str
    base_url: str = ""
    api_key: str = ""
    preset: str = "claude_code"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider.value,
            "model": self.model,
            "base_url": self.base_url,
            "preset": self.preset,
            "has_key": bool(self.api_key),
        }
```

- [ ] **Step 4: Implementar `services/llm/registry.py`**

```python
"""Atalhos de provedores. Só dados: quem fala o formato da OpenAI cabe no mesmo adaptador."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    base_url: str
    model: str
    needs_key: bool
    help_url: str


PRESETS: tuple[Preset, ...] = (
    Preset("claude_code", "Claude Code (nesta máquina)", "", "opus", False, "https://claude.com/claude-code"),
    Preset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
           "gemini-2.5-flash", True, "https://aistudio.google.com/apikey"),
    Preset("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", True,
           "https://console.groq.com/keys"),
    Preset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "google/gemini-2.5-flash", True,
           "https://openrouter.ai/keys"),
    Preset("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", True,
           "https://console.mistral.ai/api-keys"),
    Preset("ollama", "Ollama (nesta máquina)", "http://127.0.0.1:11434/v1", "llama3.1:8b", False,
           "https://ollama.com/download"),
    Preset("lmstudio", "LM Studio (nesta máquina)", "http://127.0.0.1:1234/v1", "local-model", False,
           "https://lmstudio.ai"),
    Preset("custom", "Personalizado", "", "", False, ""),
)


def find(key: str) -> Preset | None:
    return next((p for p in PRESETS if p.key == key), None)
```

- [ ] **Step 5: Implementar `services/llm/config_store.py`**

```python
"""Configuração do motor em data/llm.json. Arquivo ilegível vale como 'sem configuração'."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from contracts.models import LLMConfig


class LLMConfigStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> LLMConfig | None:
        if not self.path.exists():
            return None
        try:
            return LLMConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError, OSError):
            return None

    def save(self, config: LLMConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(config.model_dump_json(), encoding="utf-8")
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest contracts services/llm -q`
Expected: tudo passa (2 novos em contracts, 6 em registry, 4 em config_store)

- [ ] **Step 7: Commit**

```bash
git add contracts services/llm
git commit -m "feat(llm): contratos, presets e armazenamento da escolha de motor"
```

---

### Task 2: separar o runner do Claude Code em um adaptador

**Files:**
- Create: `services/llm/providers/__init__.py`, `services/llm/providers/claude_code.py`
- Modify: `services/llm/runner.py` (passa a conter só `LLMError` e `RunResult`), `services/llm/api.py`, `services/llm/evals/run_intent.py`, `services/web/wiring.py`, `services/web/main.py`, `services/llm/tests/test_runner.py` (imports)
- Test: `services/llm/tests/test_runner.py` (mesmo conteúdo, novo import)

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `services.llm.runner.LLMError`, `services.llm.runner.RunResult` (inalterados, agora só tipos); `services.llm.providers.claude_code.ClaudeRunner` com a mesma assinatura de hoje (`model="opus"`, `binary=None`, `cwd=None`, `timeout=180.0`, `run=subprocess.run`, `clock=time.monotonic`, métodos `available()` e `run(system, prompt, schema)`).

- [ ] **Step 1: Mover o código**

Mover a classe `ClaudeRunner` de `services/llm/runner.py` para `services/llm/providers/claude_code.py`, junto dos imports que só ela usa (`json`, `shutil`, `subprocess`, `tempfile`, `time`, `Path`, `Any`, `Callable`), acrescentando no topo:

```python
"""Adaptador do Claude Code local (claude -p). Não usa chave: depende do login feito no terminal."""

from __future__ import annotations

from services.llm.runner import LLMError, RunResult
```

`services/llm/providers/__init__.py`: `"""Adaptadores de motor de IA."""`

`services/llm/runner.py` fica com o docstring `"""Tipos compartilhados pelos adaptadores de motor."""`, os imports `from __future__ import annotations`, `from dataclasses import dataclass`, `from typing import Any`, `from contracts.errors import ExternalServiceError`, e as duas definições `LLMError` e `RunResult`, sem mais nada.

- [ ] **Step 2: Atualizar os imports**

Trocar em `services/llm/tests/test_runner.py`, `services/llm/evals/run_intent.py`, `services/web/wiring.py` e `services/web/main.py`:
```python
from services.llm.runner import ClaudeRunner, LLMError   # antes
from services.llm.providers.claude_code import ClaudeRunner  # depois (LLMError continua vindo de services.llm.runner)
```
Em `services/llm/tests/test_runner.py`, o `monkeypatch.setattr("services.llm.runner.shutil.which", ...)` vira `monkeypatch.setattr("services.llm.providers.claude_code.shutil.which", ...)` (duas ocorrências).

- [ ] **Step 3: Rodar a suíte inteira**

Run: `uv run pytest -q`
Expected: mesmo número de testes de antes, todos passando (nenhum teste novo nesta task: é movimentação pura)

- [ ] **Step 4: Commit**

```bash
git add services
git commit -m "refactor(llm): Claude Code vira um adaptador em providers/"
```

---

### Task 3: adaptador compatível com OpenAI

**Files:**
- Create: `services/llm/providers/openai_compatible.py`
- Test: `services/llm/tests/test_openai_compatible.py`

**Interfaces:**
- Consumes: `services.llm.runner.LLMError`, `services.llm.runner.RunResult`.
- Produces: `services.llm.providers.openai_compatible.OpenAICompatibleRunner(base_url: str, model: str, api_key: str | None = None, http: httpx.Client | None = None, timeout: float = 120.0, clock=time.monotonic)` com `available() -> bool` e `run(system: str, prompt: str, schema: dict) -> RunResult`.

**Formato:** `POST {base_url}/chat/completions` com `messages` (system + user) e `response_format` do tipo `json_schema` com `strict: true`. É o mesmo formato aceito por Gemini, Groq, OpenRouter, Mistral, Ollama e LM Studio.

- [ ] **Step 1: Teste que falha, `services/llm/tests/test_openai_compatible.py`**

```python
import json

import httpx
import pytest
import respx

from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.llm.runner import LLMError

BASE = "https://api.exemplo.com/v1"
SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"], "additionalProperties": False}


def _runner(api_key="k-123", **kwargs):
    return OpenAICompatibleRunner(BASE, "modelo-1", api_key, httpx.Client(), **kwargs)


def _reply(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@respx.mock
def test_sends_schema_messages_and_key():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=_reply('{"x": "ok"}'))
    result = _runner().run("SISTEMA", "PERGUNTA", SCHEMA)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "modelo-1"
    assert body["messages"] == [{"role": "system", "content": "SISTEMA"}, {"role": "user", "content": "PERGUNTA"}]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert route.calls.last.request.headers["Authorization"] == "Bearer k-123"
    assert result.data == {"x": "ok"}
    assert result.cost_usd == 0.0
    assert result.latency_s >= 0


@respx.mock
def test_local_provider_without_key_sends_no_authorization():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=_reply('{"x": "ok"}'))
    _runner(api_key=None).run("s", "p", SCHEMA)
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
def test_base_url_with_trailing_slash_is_normalized():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=_reply('{"x": "ok"}'))
    OpenAICompatibleRunner(f"{BASE}/", "modelo-1", "k", httpx.Client()).run("s", "p", SCHEMA)
    assert route.call_count == 1


@respx.mock
def test_content_split_in_parts_is_joined():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": [{"text": '{"x": '}, {"text": '"ok"}'}]}}]})
    )
    assert _runner().run("s", "p", SCHEMA).data == {"x": "ok"}


@respx.mock
@pytest.mark.parametrize(
    ("status", "trecho"),
    [(401, "chave"), (403, "chave"), (429, "limite"), (500, "respondeu 500")],
)
def test_http_errors_become_readable_messages(status, trecho):
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(status, text="detalhe"))
    with pytest.raises(LLMError, match=trecho):
        _runner().run("s", "p", SCHEMA)


@respx.mock
def test_unreachable_endpoint_says_so():
    respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectError("sem rota"))
    with pytest.raises(LLMError, match="Não consegui falar com"):
        _runner().run("s", "p", SCHEMA)


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"erro": "formato estranho"},
    ],
)
def test_response_without_content_is_an_error(payload):
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(LLMError, match="fora do formato"):
        _runner().run("s", "p", SCHEMA)


@respx.mock
@pytest.mark.parametrize("content", ["isso não é json", "[1, 2, 3]"])
def test_content_that_is_not_a_json_object_is_an_error(content):
    respx.post(f"{BASE}/chat/completions").mock(return_value=_reply(content))
    with pytest.raises(LLMError, match="JSON"):
        _runner().run("s", "p", SCHEMA)


def test_available_requires_base_url_and_model():
    assert _runner().available()
    assert not OpenAICompatibleRunner("", "modelo", "k", httpx.Client()).available()
    assert not OpenAICompatibleRunner(BASE, "", "k", httpx.Client()).available()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/llm/tests/test_openai_compatible.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.llm.providers.openai_compatible'`

- [ ] **Step 3: Implementar**

```python
"""Adaptador para qualquer API no formato da OpenAI: Gemini, Groq, OpenRouter, Mistral, Ollama, LM Studio."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx

from services.llm.runner import LLMError, RunResult


class OpenAICompatibleRunner:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or None
        self.http = http or httpx.Client()
        self.timeout = timeout
        self.clock = clock

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": schema},
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        start = self.clock()
        try:
            response = self.http.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as err:
            raise LLMError(f"Não consegui falar com {self.base_url}: {err}") from err
        latency = self.clock() - start
        if response.status_code in (401, 403):
            raise LLMError("O provedor recusou a chave. Confira a chave na configuração do motor de IA.")
        if response.status_code == 429:
            raise LLMError("O provedor atingiu o limite de uso. Tente de novo mais tarde ou escolha outro motor.")
        if response.status_code >= 400:
            raise LLMError(f"O provedor respondeu {response.status_code}: {response.text[:200]}")
        return RunResult(data=self._parse(response), latency_s=latency, cost_usd=0.0)

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as err:
            raise LLMError("Resposta do provedor fora do formato esperado.") from err
        if isinstance(content, list):
            # Alguns provedores devolvem o texto em pedaços.
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError) as err:
            raise LLMError(f"O modelo {self.model} não devolveu JSON. Escolha um modelo que aceite schema JSON.") from err
        if not isinstance(parsed, dict):
            raise LLMError(f"O modelo {self.model} devolveu JSON que não é um objeto.")
        return parsed
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest services/llm -q`
Expected: 16 testes novos passando (1 + 1 + 1 + 1 + 4 + 1 + 3 + 2 + 1 + 1), nada quebrado

- [ ] **Step 5: Commit**

```bash
git add services/llm
git commit -m "feat(llm): adaptador para APIs compatíveis com OpenAI"
```

---

### Task 4: fábrica de motor e LLM trocável em tempo de execução

**Files:**
- Create: `services/llm/factory.py`
- Modify: `services/llm/api.py` (renomear `ClaudeLLM` para `AgentLLM`, acrescentar `set_runner`, `description` e o trace de motor), `services/web/wiring.py` (import e uso), `services/llm/README.md`
- Test: `services/llm/tests/test_factory.py`, `services/llm/tests/test_api.py` (acrescentar)

**Interfaces:**
- Consumes: Tasks 1, 2 e 3.
- Produces: `services.llm.factory.build_runner(config: LLMConfig, http: httpx.Client | None = None)` (devolve `ClaudeRunner` ou `OpenAICompatibleRunner`), `services.llm.factory.describe(config: LLMConfig) -> str` (ex.: `"Google Gemini · gemini-2.5-flash"`); `services.llm.api.AgentLLM(runner, tracer=None, description="")` com `interpret`, `plan_theme`, `set_runner(runner, description)` e o atributo `description`.

- [ ] **Step 1: Testes que falham**

`services/llm/tests/test_factory.py`:
```python
import httpx
import pytest

from contracts.models import LLMConfig, ProviderKind
from services.llm.factory import build_runner, describe
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.llm.runner import LLMError


def test_builds_the_claude_code_runner():
    runner = build_runner(LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="haiku"))
    assert isinstance(runner, ClaudeRunner) and runner.model == "haiku"


def test_builds_the_openai_compatible_runner_with_key_and_shared_client():
    http = httpx.Client()
    config = LLMConfig(provider=ProviderKind.OPENAI, model="m", base_url="https://x/v1", api_key="k", preset="groq")
    runner = build_runner(config, http)
    assert isinstance(runner, OpenAICompatibleRunner)
    assert (runner.base_url, runner.model, runner.api_key) == ("https://x/v1", "m", "k")
    assert runner.http is http


def test_openai_compatible_without_base_url_is_refused():
    with pytest.raises(LLMError, match="endereço"):
        build_runner(LLMConfig(provider=ProviderKind.OPENAI, model="m", preset="custom"))


def test_openai_compatible_without_model_is_refused():
    with pytest.raises(LLMError, match="modelo"):
        build_runner(LLMConfig(provider=ProviderKind.OPENAI, model="", base_url="https://x/v1", preset="custom"))


def test_describe_uses_the_preset_label():
    assert describe(LLMConfig(provider=ProviderKind.OPENAI, model="gemini-2.5-flash",
                              base_url="https://x/v1", preset="gemini")) == "Google Gemini · gemini-2.5-flash"
    assert describe(LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus")) == "Claude Code (nesta máquina) · opus"
    assert describe(LLMConfig(provider=ProviderKind.OPENAI, model="m", base_url="https://x/v1",
                              preset="custom")) == "Personalizado · m"
```

Acrescentar em `services/llm/tests/test_api.py`:
```python
def test_trace_records_provider_and_model():
    events = []
    runner = FakeRunner({"action": "chat", "reply": "Oi!", "options": []})
    llm = AgentLLM(runner, tracer=lambda event, **f: events.append((event, f)), description="Google Gemini · flash")
    llm.interpret("oi", [], [])
    assert events[0][1]["motor"] == "Google Gemini · flash"


def test_set_runner_takes_effect_on_the_next_call():
    first = FakeRunner({"action": "chat", "reply": "um", "options": []})
    second = FakeRunner({"action": "chat", "reply": "dois", "options": []})
    llm = AgentLLM(first, description="A")
    assert llm.interpret("oi", [], []).reply == "um"
    llm.set_runner(second, "B")
    assert llm.interpret("oi", [], []).reply == "dois"
    assert llm.description == "B"
```

No mesmo arquivo, trocar todas as ocorrências de `ClaudeLLM` por `AgentLLM` e o import correspondente.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/llm -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.llm.factory'` e `ImportError` de `AgentLLM`

- [ ] **Step 3: Implementar `services/llm/factory.py`**

```python
"""Monta o runner a partir da configuração escolhida pelo usuário."""

from __future__ import annotations

import httpx

from contracts.models import LLMConfig, ProviderKind
from services.llm.providers.claude_code import ClaudeRunner
from services.llm.providers.openai_compatible import OpenAICompatibleRunner
from services.llm.registry import find
from services.llm.runner import LLMError


def build_runner(config: LLMConfig, http: httpx.Client | None = None):
    if config.provider is ProviderKind.CLAUDE_CODE:
        return ClaudeRunner(model=config.model or "opus")
    if not config.base_url:
        raise LLMError("Informe o endereço da API do provedor.")
    if not config.model:
        raise LLMError("Informe o modelo que o provedor deve usar.")
    return OpenAICompatibleRunner(config.base_url, config.model, config.api_key or None, http)


def describe(config: LLMConfig) -> str:
    preset = find(config.preset)
    label = preset.label if preset else config.base_url or config.provider.value
    return f"{label} · {config.model}"
```

- [ ] **Step 4: Ajustar `services/llm/api.py`**

Renomear a classe e acrescentar os dois membros novos:

```python
class AgentLLM:
    def __init__(self, runner: Any, tracer: Callable[..., None] | None = None, description: str = "") -> None:
        self.runner = runner
        self.tracer = tracer or _no_trace
        self.description = description

    def set_runner(self, runner: Any, description: str) -> None:
        """Troca o motor. Vale a partir da próxima chamada; não há estado por motor."""
        self.runner = runner
        self.description = description

    def _call(self, kind: str, prompt_name: str, prompt: str, model_cls: type) -> Any:
        model, run = call_structured(self.runner, load_prompt(prompt_name), prompt, model_cls)
        self.tracer(
            "llm", kind=kind, latency_s=round(run.latency_s, 2), cost_usd=run.cost_usd, motor=self.description
        )
        return model
```

O resto do arquivo (`interpret`, `plan_theme`, funções de prompt) fica igual.

- [ ] **Step 5: Ajustar `services/web/wiring.py`**

Trocar o import `from services.llm.api import ClaudeLLM` por `from services.llm.api import AgentLLM` e a linha de montagem por:

```python
    llm_store = LLMConfigStore(data / "llm.json")
    llm_config = llm_store.load() or LLMConfig(provider=ProviderKind.CLAUDE_CODE, model=settings.model)
    llm = AgentLLM(build_runner(llm_config, http), tracer, describe(llm_config))
```

com os imports novos (`from contracts.models import LLMConfig, ProviderKind`, `from services.llm.config_store import LLMConfigStore`, `from services.llm.factory import build_runner, describe`). Acrescentar `llm`, `llm_store` e `http` aos campos de `AppDeps` e ao `return AppDeps(...)`, mantendo os campos atuais:

```python
@dataclass
class AppDeps:
    agent: Any
    auth: Any
    settings: Settings
    trace_path: Path
    claude_ok: bool
    llm: Any = None
    llm_store: Any = None
    http: Any = None
```

(os três com default `None` para não quebrar os testes que constroem `AppDeps` à mão)

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q`
Expected: tudo passa, incluindo os 5 de factory e os 2 novos de api

- [ ] **Step 7: Atualizar `services/llm/README.md`**

Trocar a seção de arquivos por:

```markdown
- `providers/claude_code.py`: Claude Code local (`claude -p`), sem chave.
- `providers/openai_compatible.py`: qualquer API no formato da OpenAI (Gemini, Groq, OpenRouter, Mistral, Ollama, LM Studio).
- `registry.py`: atalhos de provedor (endereço, modelo sugerido, onde pegar a chave).
- `config_store.py`: a escolha do usuário em `data/llm.json`.
- `factory.py`: monta o runner a partir da configuração.
- `structured.py`: schema JSON a partir dos modelos pydantic, com uma nova tentativa em caso de resposta inválida.
- `api.py`: `interpret` e `plan_theme`, com troca de motor em tempo de execução.
- `prompts/`: prompts versionados em markdown. Mudou prompt, rode o eval.
```

- [ ] **Step 8: Commit**

```bash
git add services
git commit -m "feat(llm): fábrica de motor e troca sem reiniciar"
```

---

### Task 5: teste de compatibilidade (o padrão mínimo)

**Files:**
- Create: `services/llm/scoring.py`, `services/llm/compat.py`
- Delete: `services/llm/evals/scoring.py` (conteúdo movido)
- Modify: `services/llm/evals/run_intent.py` (import), `services/llm/tests/test_scoring.py` (import)
- Test: `services/llm/tests/test_compat.py`

**Interfaces:**
- Consumes: `services.llm.api.AgentLLM` (Task 4), `services.llm.runner.LLMError`.
- Produces: `services.llm.scoring.score_intent(case: dict, intent: Intent) -> tuple[bool, str]` (mesma função de hoje, novo lugar); `services.llm.compat.CompatCheck(name: str, ok: bool, detail: str, latency_s: float)`, `CompatReport(checks: list[CompatCheck])` com `ok: bool` e `to_dict() -> dict`, `check(runner) -> CompatReport`.

- [ ] **Step 1: Mover a pontuação**

Mover `services/llm/evals/scoring.py` para `services/llm/scoring.py` sem mudar o conteúdo, e trocar o import em `services/llm/evals/run_intent.py` e em `services/llm/tests/test_scoring.py`:
```python
from services.llm.evals.scoring import score_intent   # antes
from services.llm.scoring import score_intent          # depois
```

Run: `uv run pytest services/llm -q`
Expected: tudo passa (movimentação pura)

- [ ] **Step 2: Teste que falha, `services/llm/tests/test_compat.py`**

```python
import pytest

from services.llm.compat import check
from services.llm.runner import LLMError, RunResult

INTENT_OK = {
    "action": "reorganize", "reply": "Posso fazer assim:", "playlist_name": "Treino",
    "options": [{"kind": "bpm", "label": "BPM crescente", "description": "d", "bpm_mode": "asc"}],
}
THEME_OK = {
    "playlist_name": "Playlist colorida", "description": "cores nos títulos",
    "slots": [
        {"label": "Azul", "keywords": ["Azul"], "candidates": [{"title": "Azul", "artist": "X"}]},
        {"label": "Verde", "keywords": ["Verde"], "candidates": [{"title": "Verde", "artist": "Y"}]},
    ],
}


class FakeRunner:
    """Responde conforme o schema pedido: Intent ou ThemePlan."""

    def __init__(self, intent=INTENT_OK, theme=THEME_OK, raises=None):
        self.intent = intent
        self.theme = theme
        self.raises = raises
        self.calls = 0

    def run(self, system, prompt, schema):
        self.calls += 1
        if self.raises:
            raise self.raises
        data = self.theme if "slots" in schema["properties"] else self.intent
        return RunResult(data=data, latency_s=0.5, cost_usd=0.0)


def test_good_engine_passes_all_three_checks():
    runner = FakeRunner()
    report = check(runner)
    assert report.ok
    assert [c.name for c in report.checks] == [
        "Entender um pedido simples", "Propor opções para um pedido aberto", "Montar um tema pequeno"
    ]
    assert runner.calls == 3
    assert all(c.latency_s >= 0 for c in report.checks)


def test_engine_that_misreads_the_request_fails_the_first_check():
    intent = {**INTENT_OK, "action": "chat", "playlist_name": None, "options": []}
    report = check(FakeRunner(intent=intent))
    assert not report.ok
    assert not report.checks[0].ok and "action" in report.checks[0].detail


def test_engine_that_proposes_nothing_fails():
    report = check(FakeRunner(intent={**INTENT_OK, "options": []}))
    assert not report.ok
    assert "opção" in report.checks[1].detail


def test_engine_with_a_weak_theme_fails_the_third_check():
    theme = {**THEME_OK, "slots": THEME_OK["slots"][:1]}
    report = check(FakeRunner(theme=theme))
    assert report.checks[0].ok and report.checks[1].ok
    assert not report.checks[2].ok and "posições" in report.checks[2].detail


def test_theme_without_candidates_fails():
    theme = {**THEME_OK, "slots": [{"label": "Azul", "keywords": ["Azul"], "candidates": []},
                                   {"label": "Verde", "keywords": ["Verde"], "candidates": []}]}
    assert "sugestões" in check(FakeRunner(theme=theme)).checks[2].detail


def test_engine_error_becomes_the_failure_reason():
    report = check(FakeRunner(raises=LLMError("O provedor recusou a chave.")))
    assert not report.ok
    assert all("recusou a chave" in c.detail for c in report.checks)


def test_report_to_dict_is_serializable():
    data = check(FakeRunner()).to_dict()
    assert data["ok"] is True
    assert data["checks"][0]["name"] == "Entender um pedido simples"
    assert set(data["checks"][0]) == {"name", "ok", "detail", "latency_s"}
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest services/llm/tests/test_compat.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'services.llm.compat'`

- [ ] **Step 4: Implementar `services/llm/compat.py`**

```python
"""Padrão mínimo: 3 chamadas reais que provam que o motor escolhido serve para o app."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from contracts.models import ThemePlan
from services.llm.api import AgentLLM
from services.llm.runner import LLMError
from services.llm.scoring import score_intent

PLAYLISTS = ["Treino", "Churrasco"]
SIMPLE_CASE = {
    "message": "organiza minha playlist Treino por BPM",
    "action": "reorganize", "playlist": "Treino", "kinds": ["bpm"], "question": False,
}
OPEN_CASE = {
    "message": "arruma a Treino do jeito que você achar melhor",
    "action": "reorganize", "playlist": "Treino",
}
THEME = "músicas cujo título tem uma cor"
THEME_SLOTS = 3


@dataclass
class CompatCheck:
    name: str
    ok: bool
    detail: str
    latency_s: float


@dataclass
class CompatReport:
    checks: list[CompatCheck]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [asdict(c) for c in self.checks]}


def _theme_ok(plan: ThemePlan) -> tuple[bool, str]:
    if not plan.playlist_name.strip():
        return False, "veio sem nome de playlist"
    if len(plan.slots) < 2:
        return False, f"devolveu {len(plan.slots)} posições, esperava ao menos 2"
    if any(not slot.candidates for slot in plan.slots):
        return False, "alguma posição veio sem sugestões de música"
    return True, "ok"


def check(runner: Any) -> CompatReport:
    llm = AgentLLM(runner)
    checks: list[CompatCheck] = []
    for name, case in (
        ("Entender um pedido simples", SIMPLE_CASE),
        ("Propor opções para um pedido aberto", OPEN_CASE),
    ):
        start = time.monotonic()
        try:
            intent = llm.interpret(case["message"], [], PLAYLISTS)
            ok, detail = score_intent(case, intent)
            if ok and not intent.options:
                ok, detail = False, "não propôs nenhuma opção de organização"
        except LLMError as err:
            ok, detail = False, str(err)
        checks.append(CompatCheck(name, ok, detail, round(time.monotonic() - start, 2)))
    start = time.monotonic()
    try:
        ok, detail = _theme_ok(llm.plan_theme(THEME, THEME_SLOTS))
    except LLMError as err:
        ok, detail = False, str(err)
    checks.append(CompatCheck("Montar um tema pequeno", ok, detail, round(time.monotonic() - start, 2)))
    return CompatReport(checks)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest services/llm -q`
Expected: 7 testes novos passando

- [ ] **Step 6: Commit**

```bash
git add services/llm
git commit -m "feat(llm): teste de compatibilidade do motor escolhido"
```

---

### Task 6: rotas da configuração de motor

**Files:**
- Modify: `services/web/app.py`, `services/web/wiring.py` (campo `compat_check` em `AppDeps`)
- Test: `services/web/tests/test_llm_routes.py`

**Interfaces:**
- Consumes: Tasks 1, 4 e 5.
- Produces: `GET /api/llm` → `{"current": {...públicos...}, "description": str, "presets": [ {key,label,base_url,model,needs_key,help_url} ]}`; `POST /api/llm/test` com `{preset, base_url, model, api_key}` → relatório do teste (200 mesmo quando reprova); `POST /api/llm` com o mesmo corpo → salva e troca o motor se os 3 testes passarem, senão 400 com o relatório. `AppDeps` ganha `compat_check` (injeção usada nos testes; o padrão é `services.llm.compat.check`).

- [ ] **Step 1: Teste que falha, `services/web/tests/test_llm_routes.py`**

```python
import json

import pytest
from fastapi.testclient import TestClient

from contracts.models import LLMConfig, ProviderKind
from services.llm.compat import CompatCheck, CompatReport
from services.llm.config_store import LLMConfigStore
from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class FakeLLM:
    def __init__(self):
        self.description = "Claude Code (nesta máquina) · opus"
        self.runner = object()

    def set_runner(self, runner, description):
        self.runner = runner
        self.description = description


def _report(ok: bool) -> CompatReport:
    detail = "ok" if ok else "o modelo não devolveu JSON"
    return CompatReport([CompatCheck("Entender um pedido simples", ok, detail, 0.4)])


@pytest.fixture
def ctx(tmp_path):
    calls = {"checked": []}

    def compat_check(runner):
        calls["checked"].append(runner)
        return _report(calls.get("ok", True))

    deps = AppDeps(
        agent=None, auth=None, settings=Settings(spotify_client_id="cid", data_dir=tmp_path),
        trace_path=tmp_path / "t.jsonl", claude_ok=True, llm=FakeLLM(),
        llm_store=LLMConfigStore(tmp_path / "llm.json"), http=None, compat_check=compat_check,
    )
    return TestClient(create_app(deps)), deps, calls


def test_get_llm_lists_presets_and_current_engine(ctx):
    client, deps, _ = ctx
    data = client.get("/api/llm").json()
    assert data["description"] == "Claude Code (nesta máquina) · opus"
    assert data["current"]["provider"] == "claude_code"
    assert data["current"]["has_key"] is False
    keys = [p["key"] for p in data["presets"]]
    assert {"claude_code", "gemini", "groq", "ollama", "custom"} <= set(keys)


def test_test_route_does_not_save(ctx):
    client, deps, calls = ctx
    body = {"preset": "gemini", "model": "gemini-2.5-flash", "api_key": "k-1"}
    data = client.post("/api/llm/test", json=body).json()
    assert data["ok"] is True
    assert deps.llm_store.load() is None
    assert deps.llm.description == "Claude Code (nesta máquina) · opus"


def test_save_runs_the_check_stores_and_swaps(ctx):
    client, deps, _ = ctx
    body = {"preset": "groq", "model": "llama-3.3-70b-versatile", "api_key": "k-2"}
    data = client.post("/api/llm", json=body).json()
    assert data["ok"] is True
    assert data["description"] == "Groq · llama-3.3-70b-versatile"
    saved = deps.llm_store.load()
    assert saved.api_key == "k-2" and saved.base_url == "https://api.groq.com/openai/v1"
    assert deps.llm.description == "Groq · llama-3.3-70b-versatile"


def test_save_is_refused_when_the_check_fails(ctx):
    client, deps, calls = ctx
    calls["ok"] = False
    response = client.post("/api/llm", json={"preset": "gemini", "model": "modelo-fraco", "api_key": "k"})
    assert response.status_code == 400
    assert response.json()["report"]["checks"][0]["detail"] == "o modelo não devolveu JSON"
    assert deps.llm_store.load() is None
    assert deps.llm.description == "Claude Code (nesta máquina) · opus"


def test_key_is_kept_when_the_user_does_not_retype_it(ctx):
    client, deps, _ = ctx
    client.post("/api/llm", json={"preset": "groq", "model": "m1", "api_key": "k-3"})
    client.post("/api/llm", json={"preset": "groq", "model": "m2", "api_key": ""})
    saved = deps.llm_store.load()
    assert saved.model == "m2" and saved.api_key == "k-3"


def test_switching_preset_without_a_key_starts_empty(ctx):
    client, deps, _ = ctx
    client.post("/api/llm", json={"preset": "groq", "model": "m1", "api_key": "k-3"})
    client.post("/api/llm", json={"preset": "gemini", "model": "m2", "api_key": ""})
    assert deps.llm_store.load().api_key == ""


def test_custom_preset_requires_a_base_url(ctx):
    client, _, _ = ctx
    response = client.post("/api/llm", json={"preset": "custom", "model": "m", "base_url": ""})
    assert response.status_code == 502
    assert "endereço" in response.json()["detail"]


def test_claude_code_preset_saves_without_key_or_url(ctx):
    client, deps, _ = ctx
    assert client.post("/api/llm", json={"preset": "claude_code", "model": "haiku"}).json()["ok"] is True
    assert deps.llm_store.load().provider == ProviderKind.CLAUDE_CODE
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/web/tests/test_llm_routes.py -q`
Expected: FAIL com `TypeError` (campo `compat_check` não existe em `AppDeps`) e 404 nas rotas

- [ ] **Step 3: Acrescentar `compat_check` a `AppDeps`**

Em `services/web/wiring.py`, acrescentar o campo com default:
```python
    compat_check: Any = None
```

- [ ] **Step 4: Implementar as rotas em `services/web/app.py`**

Imports novos:
```python
from dataclasses import asdict

from contracts.models import LLMConfig, ProviderKind
from services.llm.compat import check as default_compat_check
from services.llm.factory import build_runner, describe
from services.llm.registry import PRESETS, find
```

Modelo de entrada, junto dos outros:
```python
class LLMConfigIn(BaseModel):
    preset: str = "custom"
    model: str
    base_url: str = ""
    api_key: str = ""
```

Dentro de `create_app`, antes do `return app`:
```python
    def _current_config() -> LLMConfig:
        saved = deps.llm_store.load() if deps.llm_store else None
        return saved or LLMConfig(provider=ProviderKind.CLAUDE_CODE, model=deps.settings.model)

    def _config_from(body: LLMConfigIn) -> LLMConfig:
        preset = find(body.preset)
        provider = ProviderKind.CLAUDE_CODE if body.preset == "claude_code" else ProviderKind.OPENAI
        base_url = body.base_url or (preset.base_url if preset else "")
        current = _current_config()
        # A chave não volta para a tela, então um campo vazio significa "mantém a que já estava".
        api_key = body.api_key or (current.api_key if current.preset == body.preset else "")
        return LLMConfig(provider=provider, model=body.model, base_url=base_url, api_key=api_key, preset=body.preset)

    @app.get("/api/llm")
    def llm_config() -> dict:
        return {
            "current": _current_config().to_public_dict(),
            "description": getattr(deps.llm, "description", ""),
            "presets": [asdict(p) for p in PRESETS],
        }

    @app.post("/api/llm/test")
    def llm_test(body: LLMConfigIn) -> dict:
        runner = build_runner(_config_from(body), deps.http)
        return (deps.compat_check or default_compat_check)(runner).to_dict()

    @app.post("/api/llm")
    def llm_save(body: LLMConfigIn):
        config = _config_from(body)
        runner = build_runner(config, deps.http)
        report = (deps.compat_check or default_compat_check)(runner)
        if not report.ok:
            return JSONResponse(
                status_code=400,
                content={"detail": "O motor não passou no teste. Nada foi salvo.", "report": report.to_dict()},
            )
        deps.llm_store.save(config)
        deps.llm.set_runner(runner, describe(config))
        return {"ok": True, "description": describe(config), "report": report.to_dict()}
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest services/web -q`
Expected: 8 testes novos passando, os antigos intactos

- [ ] **Step 6: Commit**

```bash
git add services/web
git commit -m "feat(web): rotas para escolher e testar o motor de IA"
```

---

### Task 7: painel "Motor de IA" na interface

**Files:**
- Modify: `services/web/static/index.html`, `services/web/static/app.js`, `services/web/static/style.css`
- Test: `services/web/tests/test_static.py` (acrescentar)

**Interfaces:**
- Consumes: as rotas da Task 6.
- Produces: painel na interface com lista de provedores, endereço, modelo, chave, "Testar e salvar", "Só testar" e o resultado dos 3 testes.

- [ ] **Step 1: Testes que falham, acrescentar em `services/web/tests/test_static.py`**

```python
def test_page_has_the_engine_panel(tmp_path):
    page = _client(tmp_path).get("/").text
    assert 'id="engine"' in page and 'id="llm-panel"' in page
    assert 'id="llm-preset"' in page and 'id="llm-model"' in page and 'id="llm-key"' in page
    assert 'type="password"' in page


def test_frontend_talks_to_the_engine_routes(tmp_path):
    script = _client(tmp_path).get("/static/app.js").text
    assert '"/api/llm"' in script and '"/api/llm/test"' in script
    assert "innerHTML" not in script
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/web/tests/test_static.py -q`
Expected: FAIL nas duas asserções novas

- [ ] **Step 3: `services/web/static/index.html`**

Acrescentar o botão na barra de cima, logo antes do botão "Nova conversa":
```html
    <button id="engine" class="ghost" type="button">Motor de IA</button>
```

E, logo depois de `</main>`, o painel:
```html
  <section id="llm-panel" class="panel" hidden aria-label="Motor de IA">
    <h2>Motor de IA</h2>
    <p class="meta" id="llm-current"></p>
    <form id="llm-form" class="panel-form">
      <label>Provedor
        <select id="llm-preset"></select>
      </label>
      <label id="llm-base-url-row">Endereço da API
        <input id="llm-base-url" autocomplete="off" placeholder="https://exemplo.com/v1">
      </label>
      <label>Modelo
        <input id="llm-model" autocomplete="off" required>
      </label>
      <label id="llm-key-row">Chave
        <input id="llm-key" type="password" autocomplete="off" placeholder="vazio mantém a chave atual">
      </label>
      <p class="meta" id="llm-help"></p>
      <div class="actions">
        <button type="submit">Testar e salvar</button>
        <button type="button" class="ghost" id="llm-only-test">Só testar</button>
        <button type="button" class="ghost" id="llm-close">Fechar</button>
      </div>
    </form>
    <ul id="llm-report" class="links"></ul>
  </section>
```

- [ ] **Step 4: `services/web/static/app.js`**

Acrescentar ao fim do arquivo, antes da chamada `boot();`, e mover `boot();` para depois deste bloco:

```js
const panel = document.getElementById("llm-panel");
const presetSelect = document.getElementById("llm-preset");
const baseUrlInput = document.getElementById("llm-base-url");
const modelInput = document.getElementById("llm-model");
const keyInput = document.getElementById("llm-key");
const helpText = document.getElementById("llm-help");
const reportList = document.getElementById("llm-report");
const currentText = document.getElementById("llm-current");
let presets = [];

function presetByKey(key) {
  return presets.find((p) => p.key === key) || null;
}

function applyPreset(key, { keepFields = false } = {}) {
  const preset = presetByKey(key);
  if (!preset) return;
  if (!keepFields) {
    baseUrlInput.value = preset.base_url;
    modelInput.value = preset.model;
    keyInput.value = "";
  }
  document.getElementById("llm-base-url-row").hidden = key !== "custom";
  document.getElementById("llm-key-row").hidden = !preset.needs_key;
  helpText.replaceChildren();
  if (preset.help_url) {
    helpText.append(
      preset.needs_key ? "Pegue a chave em " : "Saiba mais em ",
      el("a", { href: preset.help_url, target: "_blank", rel: "noopener" }, preset.help_url));
  }
}

function renderReport(report) {
  reportList.replaceChildren(
    ...report.checks.map((c) =>
      el("li", { class: c.ok ? "" : "warn" }, `${c.ok ? "OK" : "FALHOU"} · ${c.name}: ${c.detail} (${c.latency_s}s)`)));
}

async function loadEngine() {
  const data = await api("/api/llm");
  presets = data.presets;
  presetSelect.replaceChildren(...presets.map((p) => el("option", { value: p.key }, p.label)));
  presetSelect.value = data.current.preset;
  applyPreset(data.current.preset);
  baseUrlInput.value = data.current.base_url;
  modelInput.value = data.current.model;
  currentText.textContent = data.current.has_key
    ? `Em uso: ${data.description} (chave salva)`
    : `Em uso: ${data.description}`;
}

function engineBody() {
  return {
    preset: presetSelect.value,
    model: modelInput.value.trim(),
    base_url: baseUrlInput.value.trim(),
    api_key: keyInput.value,
  };
}

async function submitEngine(path) {
  reportList.replaceChildren(el("li", {}, "Testando o motor: 3 chamadas reais, pode levar alguns segundos..."));
  setBusy(true);
  try {
    const data = await api(path, engineBody());
    renderReport(data.report || data);
    if (data.ok && path === "/api/llm") {
      currentText.textContent = `Em uso: ${data.description}`;
      keyInput.value = "";
      say("agent", `Pronto: agora estou usando ${data.description}.`);
    }
  } catch (error) {
    reportList.replaceChildren(el("li", { class: "warn" }, error.message));
  } finally {
    setBusy(false);
  }
}

presetSelect.addEventListener("change", () => applyPreset(presetSelect.value));
document.getElementById("engine").addEventListener("click", async () => {
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    reportList.replaceChildren();
    try {
      await loadEngine();
    } catch (error) {
      reportList.replaceChildren(el("li", { class: "warn" }, error.message));
    }
  }
});
document.getElementById("llm-close").addEventListener("click", () => {
  panel.hidden = true;
});
document.getElementById("llm-only-test").addEventListener("click", () => submitEngine("/api/llm/test"));
document.getElementById("llm-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitEngine("/api/llm");
});
```

Ajuste necessário no tratamento de erro do `api()`: a rota de salvar devolve 400 com `{"detail": ..., "report": ...}`. Trocar a linha do `throw` em `api()` por:

```js
  if (!response.ok) {
    if (data.report) renderReport(data.report);
    throw new Error(typeof data.detail === "string" ? data.detail : `Erro ${response.status}`);
  }
```

`renderReport` é declarada depois, mas `function` sobe no escopo do módulo, então a chamada funciona.

Ainda em `app.js`, corrigir o aviso da inicialização: hoje ele acusa a falta do Claude Code mesmo quando o motor ativo é outro. Em `boot()`, trocar o bloco do aviso por:

```js
    if (!status.claude_ok) {
      const engine = await api("/api/llm").catch(() => ({ description: "" }));
      if (engine.description.startsWith("Claude Code")) {
        say("error", "Claude Code não encontrado. Rode `claude` no terminal e faça login, ou escolha outro motor em Motor de IA.");
      }
    }
```

- [ ] **Step 5: `services/web/static/style.css`**

Acrescentar ao fim:
```css
.panel { grid-column: 1 / -1; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 20px; margin: 0 20px 16px; }
.panel h2 { margin-top: 0; }
.panel-form { display: grid; gap: 10px; max-width: 520px; }
.panel-form label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
.panel-form input, .panel-form select { background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 14px; }
#llm-report { margin-top: 12px; font-size: 13px; }
#llm-report .warn { color: var(--warn); }
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest services/web -q`
Expected: tudo passa

- [ ] **Step 7: Checagem sem navegador**

Suba o servidor com um agente falso, como na verificação da interface anterior:
```bash
uv run python -c "import uvicorn; from pathlib import Path; import tempfile; from services.web.app import create_app; from services.web.settings import Settings; from services.web.wiring import build_deps; s=Settings(spotify_client_id='teste', data_dir=Path(tempfile.mkdtemp())); uvicorn.run(create_app(build_deps(s, claude_ok=True)), host='127.0.0.1', port=8765, log_level='warning')"
```
e confira com curl: `GET /` traz `id="llm-panel"`, `GET /api/llm` traz a lista de presets com `claude_code` selecionado, e `GET /static/app.js` responde 200. Se `node` existir, rode `node --check services/web/static/app.js`. Encerre o servidor depois e registre as saídas no relatório.

- [ ] **Step 8: Commit**

```bash
git add services/web
git commit -m "feat(web): painel para escolher e testar o motor de IA"
```

---

### Task 8: medição por motor, eval em qualquer motor e documentação

**Files:**
- Modify: `services/agent/trace.py`, `services/llm/evals/run_intent.py`, `README.md`, `docs/superpowers/specs/2026-09-19-motor-de-ia-plugavel-design.md`
- Test: `services/agent/tests/test_trace.py` (acrescentar)

**Interfaces:**
- Consumes: Tasks 1 a 7.
- Produces: `summarize()` passa a devolver também `llm_by_motor: dict[str, {"calls": int, "cost_usd": float, "avg_latency_s": float}]`; `run_intent` roda no motor configurado, com override por variáveis de ambiente.

- [ ] **Step 1: Teste que falha, acrescentar em `services/agent/tests/test_trace.py`**

```python
def test_summarize_groups_by_engine(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = Tracer(path)
    tracer("llm", kind="interpret", latency_s=2.0, cost_usd=0.10, motor="Claude Code (nesta máquina) · opus")
    tracer("llm", kind="theme", latency_s=4.0, cost_usd=0.20, motor="Claude Code (nesta máquina) · opus")
    tracer("llm", kind="interpret", latency_s=1.0, cost_usd=0.0, motor="Google Gemini · gemini-2.5-flash")
    tracer("llm", kind="interpret", latency_s=1.0, cost_usd=0.0)
    by_motor = summarize(path)["llm_by_motor"]
    assert by_motor["Claude Code (nesta máquina) · opus"] == {"calls": 2, "cost_usd": 0.3, "avg_latency_s": 3.0}
    assert by_motor["Google Gemini · gemini-2.5-flash"]["calls"] == 1
    assert by_motor["desconhecido"]["calls"] == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest services/agent/tests/test_trace.py -q`
Expected: FAIL com `KeyError: 'llm_by_motor'`

- [ ] **Step 3: Implementar em `services/agent/trace.py`**

Dentro de `summarize`, antes do `return`:
```python
    by_motor: dict[str, dict[str, float]] = {}
    for event in llm:
        key = str(event.get("motor") or "desconhecido")
        row = by_motor.setdefault(key, {"calls": 0, "cost_usd": 0.0, "latency_total": 0.0})
        row["calls"] += 1
        row["cost_usd"] += event.get("cost_usd", 0.0)
        row["latency_total"] += event.get("latency_s", 0.0)
```
e no dicionário devolvido:
```python
        "llm_by_motor": {
            key: {
                "calls": int(row["calls"]),
                "cost_usd": round(row["cost_usd"], 4),
                "avg_latency_s": round(row["latency_total"] / row["calls"], 2),
            }
            for key, row in by_motor.items()
        },
```

- [ ] **Step 4: `services/llm/evals/run_intent.py` roda em qualquer motor**

Trocar a montagem do LLM por:

```python
import os

from contracts.models import LLMConfig, ProviderKind
from services.llm.api import AgentLLM
from services.llm.config_store import LLMConfigStore
from services.llm.factory import build_runner, describe
from services.llm.registry import find


def _config_from_env_or_file() -> LLMConfig:
    """Override por ambiente: PLAYLIST_AGENT_PRESET, PLAYLIST_AGENT_MODEL, PLAYLIST_AGENT_API_KEY."""
    preset_key = os.environ.get("PLAYLIST_AGENT_PRESET")
    if preset_key:
        preset = find(preset_key)
        if preset is None:
            raise SystemExit(f"Preset desconhecido: {preset_key}")
        provider = ProviderKind.CLAUDE_CODE if preset.key == "claude_code" else ProviderKind.OPENAI
        return LLMConfig(
            provider=provider,
            model=os.environ.get("PLAYLIST_AGENT_MODEL") or preset.model,
            base_url=preset.base_url,
            api_key=os.environ.get("PLAYLIST_AGENT_API_KEY", ""),
            preset=preset.key,
        )
    saved = LLMConfigStore(Path("data/llm.json")).load()
    return saved or LLMConfig(provider=ProviderKind.CLAUDE_CODE, model="opus")
```

e, em `main()`:
```python
    config = _config_from_env_or_file()
    motor = describe(config)
    llm = AgentLLM(build_runner(config))
    print(f"Motor: {motor}\n")
```
O relatório JSON ganha `"motor": motor` junto de `score` e `threshold`, e a linha final passa a imprimir `f"\nAcerto: {score:.0%} (limiar {THRESHOLD:.0%}) no motor {motor}"`.

- [ ] **Step 5: Rodar os gate tests**

Run: `uv run pytest -q`
Expected: tudo passa; `run_intent` não é coletado pelo pytest

- [ ] **Step 6: README**

Acrescentar depois da seção "Instalação":

```markdown
## Escolher o motor de IA

Por padrão o app usa o Claude Code instalado na sua máquina. Para trocar, clique em **Motor de IA** no topo da tela. Dá para usar:

- **Claude Code (nesta máquina):** sem chave, usa o login que você já fez no terminal.
- **Google Gemini, Groq, OpenRouter, Mistral:** precisam de uma chave gratuita do provedor; o painel mostra o link de onde pegar.
- **Ollama ou LM Studio:** modelos rodando no seu computador, sem chave e sem enviar nada para fora.
- **Personalizado:** qualquer endereço que fale o formato da OpenAI.

Ao salvar, o app faz 3 chamadas de teste (entender um pedido, propor opções e montar um tema pequeno). O motor só passa a valer se as três funcionarem, então modelos pequenos demais são recusados na hora, com o motivo na tela.

A chave fica em `data/llm.json`, na sua máquina, em texto simples, do mesmo jeito que o token do Spotify. Essa pasta está no `.gitignore`.

Para comparar motores com os mesmos 25 casos:

```bash
PLAYLIST_AGENT_PRESET=gemini PLAYLIST_AGENT_API_KEY=sua-chave uv run python -m services.llm.evals.run_intent
```
```

- [ ] **Step 7: Spec**

Em `docs/superpowers/specs/2026-09-19-motor-de-ia-plugavel-design.md`, trocar a linha de status para `Status: implementado (verificação com motor real pendente)` e acrescentar ao fim a seção:

```markdown
## Resultados medidos

- Gate tests: o número e o tempo da última linha de `uv run pytest`.
- Teste de compatibilidade: para cada motor testado no painel, quais das 3 checagens passaram e o motivo de qualquer falha.
- Eval de intenção por motor: acerto, tempo médio e custo de cada relatório em `data/evals/intent-*.json`, um por motor.
```

- [ ] **Step 8: Commit**

```bash
git add services README.md docs
git commit -m "feat: medição por motor, eval em qualquer motor e documentação"
```

- [ ] **Step 9: Verificação ponta a ponta (com o Jone)**

Rode `uv run playlist-agent` e confira, anotando cada resultado:

1. Sem `data/llm.json`, o topo mostra "Claude Code (nesta máquina) · opus" e o chat funciona como antes.
2. No painel, escolher Gemini, colar a chave e clicar em "Testar e salvar": os 3 testes passam e a tela mostra o motor novo, sem reiniciar o app.
3. Mandar um pedido no chat e conferir que ele foi atendido pelo motor novo (o tempo e o custo aparecem em `/api/stats`, separados por motor).
4. Escolher um modelo fraco de propósito (ex.: um modelo pequeno no Ollama) e conferir que o teste falha com o motivo e que o motor anterior continua valendo.
5. Colar uma chave errada e conferir a mensagem "O provedor recusou a chave".
6. Rodar o eval de intenção em dois motores e comparar acerto, tempo e custo.
7. Preencher a seção "Resultados medidos" da spec com esses números.
