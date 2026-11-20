from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

Scope = Literal["user", "project", "session"]


@dataclass(frozen=True)
class FactSpec:
    kind: str
    topic_key: str | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Memory:
    id: UUID
    scope: str
    kind: str
    topic_key: str | None
    content: str
    version: int
    metadata: dict[str, Any]
    similarity: float | None = None  # None => pinned (fetched by topic, not by similarity)
    is_active: bool = True


@dataclass(frozen=True)
class RememberResult:
    status: Literal["created", "superseded", "duplicate"]
    id: UUID
    version: int
    embedded: bool
