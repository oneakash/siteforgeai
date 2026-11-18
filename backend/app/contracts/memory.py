from pydantic import Field

from .common import Contract, ShortText


class MemorySummary(Contract):
    """LLM compaction of old decision-log entries."""

    summary: str = Field(min_length=20, max_length=1500)
    key_decisions: list[ShortText] = Field(min_length=1, max_length=12)
