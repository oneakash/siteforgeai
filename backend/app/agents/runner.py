"""run_agent: the single choke point through which every agent call passes.

   envelope -> LLM -> validate (schema + semantic) -> [corrective re-prompt]* -> typed result

Invalid output is NEVER returned to the graph. After `max_corrections` failed
corrections we raise AgentOutputError (non-transient) for the Manager to handle.
"""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ValidationError

from app.agents.envelope import build_envelope
from app.agents.errors import AgentOutputError
from app.agents.llm import CallMeta, StructuredLLM
from app.agents.registry import AgentSpec
from app.config import LLM_TIMEOUT_S


@dataclass
class AgentResult:
    output: BaseModel
    attempts: int
    corrections: list[str] = field(default_factory=list)  # problems fixed along the way
    model: str | None = None  # 'provider:model' that actually served the call


def format_problems(exc: Exception, limit: int = 8) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for e in exc.errors()[:limit]:
            loc = ".".join(str(x) for x in e["loc"]) or "(root)"
            lines.append(f"- {loc}: {e['msg']}")
        extra = len(exc.errors()) - limit
        if extra > 0:
            lines.append(f"- ...and {extra} more")
        return "\n".join(lines)
    return f"- {exc}"


def coerce(raw: Any, model: type[BaseModel]) -> BaseModel:
    if isinstance(raw, BaseModel):
        return model.model_validate(raw.model_dump())  # re-validate: never trust pre-parsed objects
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:] if text.lower().startswith("json") else text
        return model.model_validate_json(text)
    return model.model_validate(raw)


def build_messages(spec: AgentSpec, envelope: str, instruction: str) -> list[dict[str, str]]:
    user = f"{envelope}\n\nTask: {instruction}" if instruction else envelope
    return [{"role": "system", "content": spec.system_prompt}, {"role": "user", "content": user}]


async def run_agent(
    spec: AgentSpec,
    *,
    llm: StructuredLLM,
    inputs: Mapping[str, Any],
    memories: Sequence[tuple[str, str]] = (),
    instruction: str = "",
    project_id: Any = None,
    max_corrections: int = 2,
    timeout_s: float = LLM_TIMEOUT_S,
) -> AgentResult:
    envelope = build_envelope(inputs, memories, spec.context_budget_chars)
    messages = build_messages(spec, envelope, instruction)
    problems_seen: list[str] = []
    meta = CallMeta(agent=spec.name, project_id=project_id)

    for attempt in range(1, max_corrections + 2):
        # TransientAgentError / TimeoutError propagate: LangGraph RetryPolicy owns those.
        raw = await asyncio.wait_for(
            llm.generate(messages, spec.output_model, tier=spec.tier, meta=meta), timeout=timeout_s
        )
        try:
            out = coerce(raw, spec.output_model)
            sem = [p for v in spec.validators for p in v(out, inputs)]
            if sem:
                raise ValueError("\n".join(f"- {p}" for p in sem))
            return AgentResult(output=out, attempts=attempt, corrections=problems_seen, model=meta.used_model)
        except (ValidationError, ValueError) as exc:
            problem = format_problems(exc)
            problems_seen.append(problem)
            shown = raw if isinstance(raw, str) else json.dumps(
                raw.model_dump() if isinstance(raw, BaseModel) else raw, default=str
            )
            messages = messages + [
                {"role": "assistant", "content": shown[:6000]},
                {
                    "role": "user",
                    "content": "Your previous output was rejected by validation:\n"
                    f"{problem}\nReturn a corrected, complete output that fixes every problem.",
                },
            ]
    raise AgentOutputError(spec.name, problems_seen)
