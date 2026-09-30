import json

import pytest
from pydantic import BaseModel

from services.llm.runner import LLMError, RunResult
from services.llm.structured import call_structured, inline_schema


class Inner(BaseModel):
    title: str


class Outer(BaseModel):
    items: list[Inner]
    note: str | None = None


def test_inline_schema_removes_refs_and_closes_objects():
    schema = inline_schema(Outer)
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    inner = schema["properties"]["items"]["items"]
    assert inner["additionalProperties"] is False
    # Campo chamado "title" é propriedade de verdade e precisa sobreviver; só o metadado "title" some.
    assert "title" in inner["properties"]
    assert "title" not in schema


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def run(self, system, prompt, schema):
        self.prompts.append(prompt)
        return RunResult(data=self.outputs.pop(0), latency_s=1.0, cost_usd=0.01)


def test_call_structured_validates_output():
    model, run = call_structured(FakeRunner([{"items": [{"title": "a"}]}]), "s", "p", Outer)
    assert model.items[0].title == "a"
    assert run.cost_usd == 0.01


def test_retries_once_with_validation_error_in_prompt():
    runner = FakeRunner([{"items": "ruim"}, {"items": []}])
    model, _ = call_structured(runner, "s", "p", Outer)
    assert model.items == []
    assert len(runner.prompts) == 2
    assert "inválida" in runner.prompts[1]


def test_gives_up_after_second_invalid_output():
    with pytest.raises(LLMError):
        call_structured(FakeRunner([{"items": "ruim"}, {"items": "ruim"}]), "s", "p", Outer)


def test_gives_up_message_names_the_engine_when_given():
    with pytest.raises(LLMError, match="O motor Google Gemini · flash devolveu resposta inválida"):
        call_structured(
            FakeRunner([{"items": "ruim"}, {"items": "ruim"}]), "s", "p", Outer, engine="Google Gemini · flash"
        )
