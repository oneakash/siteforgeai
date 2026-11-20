"""StructuredLLM protocol + deterministic FakeLLM. Real providers: app/llm/router.py"""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

Tier = Literal["reasoning", "fast"]


@dataclass
class CallMeta:
    """Who is calling (for override resolution) + what actually served the call."""

    agent: str | None = None
    project_id: UUID | str | None = None
    used_model: str | None = None  # filled in by the router


class StructuredLLM(Protocol):
    async def generate(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        *,
        tier: Tier,
        meta: CallMeta | None = None,
    ) -> Any:
        """Return a dict, JSON string or model instance. The RUNNER validates, so
        provider quirks never leak into agents."""


class FakeLLM:
    """Deterministic LLM for tests/CI. Exceptions in `script` are raised."""

    def __init__(self, script: list[Any], model_name: str = "fake:fake"):
        self.script = list(script)
        self.calls: list[list[dict[str, str]]] = []
        self.model_name = model_name

    async def generate(self, messages, schema, *, tier, meta=None):
        self.calls.append(list(messages))
        await asyncio.sleep(0)
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if meta:
            meta.used_model = self.model_name
        return item
