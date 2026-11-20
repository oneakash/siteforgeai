"""Context envelope: the ONLY way an agent sees upstream information.

Typed artifacts + a few retrieved memories, wrapped in delimiters and sized to a
budget. Never the full conversation history.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

TRUNC_MARK = "…[truncated]"


def _neutralize(text: str) -> str:
    # Stop untrusted text (web research, user prompts) from closing our tags
    # and masquerading as instructions.
    return text.replace("</", "<\\/")


def _to_text(v: Any) -> str:
    if isinstance(v, BaseModel):
        return v.model_dump_json()
    if isinstance(v, str):
        return v
    return json.dumps(v, separators=(",", ":"), default=str)


def build_envelope(
    inputs: Mapping[str, Any],
    memories: Sequence[tuple[str, str]] = (),
    budget_chars: int = 24_000,
) -> str:
    """inputs: name -> artifact/str/dict.  memories: (kind, text) pairs from pgvector."""
    blocks = {name: _neutralize(_to_text(v)) for name, v in inputs.items()}
    mem = [(k, _neutralize(t)) for k, t in memories]

    def total() -> int:
        return sum(len(v) for v in blocks.values()) + sum(len(t) for _, t in mem)

    # Shrink the largest block first until we fit (keeps small, high-signal inputs intact).
    guard = 0
    while total() > budget_chars and guard < 50:
        guard += 1
        name = max(blocks, key=lambda k: len(blocks[k]))
        over = total() - budget_chars
        keep = max(200, len(blocks[name]) - over - len(TRUNC_MARK))
        blocks[name] = blocks[name][:keep] + TRUNC_MARK

    parts = ["<context>"]
    for name, text in blocks.items():
        parts.append(f'<artifact name="{name}">\n{text}\n</artifact>')
    for kind, text in mem:
        parts.append(f'<memory kind="{kind}">{text}</memory>')
    parts.append("</context>")
    return "\n".join(parts)
