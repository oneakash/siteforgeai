"""Deterministic LLM that returns valid sample payloads per schema.

Lets the whole graph run with no API key (demos, CI, crash tests). Tests inject
`scripts` (per-schema queues of payloads / exceptions / callables) to simulate
bad output, failures and feedback.
"""

import asyncio
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.demo import sample_data as sd


def _has(messages, needle: str) -> bool:
    return any(needle in m["content"] for m in messages)


class DemoLLM:
    def __init__(
        self,
        scripts: dict[str, list[Any]] | None = None,
        delay: float = 0.0,
        call_log: str | None = None,
        crash_on: str | None = None,
        crash_marker: str | None = None,
    ):
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.delay, self.call_log = delay, call_log or os.environ.get("DEMO_LLM_CALL_LOG")
        self.crash_on, self.crash_marker = crash_on, crash_marker
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.models_used: list[str] = []
        self.last_messages: dict[str, list] = {}

    def count(self, schema_name: str) -> int:
        return self.calls.count(schema_name)

    def _default(self, name: str, messages) -> dict:
        if name == "PlanDraft":
            return sd.plan_draft()
        if name == "NicheReport":
            return sd.niche()
        if name == "AudienceReport":
            return sd.audience()
        if name == "CompetitorReport":
            return sd.competitor()
        if name == "SEOStrategy":
            return sd.seo()
        if name == "BrandGuideline":
            return (
                sd.brand_revised()
                if _has(messages, "previous_brand_guideline")
                else sd.brand_original()
            )
        if name == "BrandFeedbackTriage":
            return (
                sd.triage_audience()
                if _has(messages, "audience")
                and not _has(messages, 'palette":"x')
                and "younger" in messages[-1]["content"]
                else sd.triage_brand_only()
            )
        if name == "Wireframe":
            return sd.wireframe()
        if name == "MemorySummary":
            return {
                "summary": "The user iterated on the brand palette and approved the premium dark look.",
                "key_decisions": ["Premium dark green and gold palette"],
            }
        raise AssertionError(f"DemoLLM has no default for {name}")

    async def generate(self, messages, schema: type[BaseModel], *, tier, meta=None):
        name = schema.__name__
        self.calls.append(name)
        self.last_messages[name] = messages
        if self.call_log:
            with open(self.call_log, "a") as f:
                f.write(name + "\n")
        if self.crash_on == name and self.crash_marker and not os.path.exists(self.crash_marker):
            open(self.crash_marker, "w").close()
            await asyncio.sleep(
                self.delay * 4
            )  # let sibling agents FINISH (and commit) before the process dies
            print(f"!! simulating hard crash inside {name}", flush=True)
            os._exit(137)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            queue = self.scripts.get(name)
            if queue:
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                payload = item(messages) if isinstance(item, Callable) else item  # type: ignore[arg-type]
            else:
                payload = self._default(name, messages)
            if meta:
                meta.used_model = "demo:demo"
            return payload
        finally:
            self.in_flight -= 1
