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
