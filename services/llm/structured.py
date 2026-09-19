"""Converte modelos pydantic em JSON Schema autocontido e valida a resposta, com uma nova tentativa."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from services.llm.runner import LLMError, RunResult

T = TypeVar("T", bound=BaseModel)


class _Runner(Protocol):
    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> RunResult: ...


def inline_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("title", "default"):
                continue
            if key == "properties":
                out[key] = {name: resolve(sub) for name, sub in value.items()}
            else:
                out[key] = resolve(value)
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out

    return resolve(schema)


def call_structured(runner: _Runner, system: str, prompt: str, model_cls: type[T]) -> tuple[T, RunResult]:
    schema = inline_schema(model_cls)
    result = runner.run(system, prompt, schema)
    try:
        return model_cls.model_validate(result.data), result
    except ValidationError as first:
        retry = f"{prompt}\n\nSua resposta anterior foi inválida:\n{first}\nResponda de novo seguindo o schema e as regras."
        result = runner.run(system, retry, schema)
        try:
            return model_cls.model_validate(result.data), result
        except ValidationError as second:
            raise LLMError(f"Resposta do agente inválida mesmo após nova tentativa: {second}") from second
