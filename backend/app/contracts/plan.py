"""Manager Agent plan: a trackable DAG of tasks."""

import re
from enum import Enum

from pydantic import Field, model_validator

from .common import Contract, ShortText, TaskKey


class AgentName(str, Enum):
    MANAGER = "manager"
    NICHE = "niche_analysis"
    AUDIENCE = "audience_research"
    COMPETITOR = "competitor_analysis"
    SEO = "seo_analysis"
    BRAND = "brand_guideline"
    WIREFRAME = "wireframe"
    CONTENT = "content"
    DESIGN = "design"
    IMAGE = "image"
    WEBSITE = "website_generation"
    QA = "qa"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    SUPERSEDED = "superseded"


class TaskDraft(Contract):
    """What the Manager LLM may emit. No status/attempts: the LLM cannot
    declare its own work 'completed'."""

    key: TaskKey
    agent: AgentName
    description: ShortText
    depends_on: list[TaskKey] = Field(default_factory=list)


class PlanDraft(Contract):
    goal: ShortText
    website_purpose: ShortText
    business_model: ShortText
    expected_functionality: list[ShortText] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=1500)
    tasks: list[TaskDraft] = Field(min_length=2, max_length=40)

    @model_validator(mode="after")
    def _dag(self):
        _validate_dag(self.tasks)
        return self


def ancestors_of(tasks: list[TaskDraft], key: str) -> set[str]:
    """All tasks `key` (transitively) depends on."""
    by = {t.key: t for t in tasks}
    out: set[str] = set()
    stack = list(by[key].depends_on)
    while stack:
        k = stack.pop()
        if k not in out:
            out.add(k)
            stack.extend(by[k].depends_on)
    return out


class Task(TaskDraft):
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    error: str | None = None


def _validate_dag(tasks: list[TaskDraft]) -> None:
    keys = [t.key for t in tasks]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate task keys")
    known = set(keys)
    for t in tasks:
        if t.agent == AgentName.MANAGER:
            raise ValueError(f"task '{t.key}': the manager does not delegate to itself")
        if t.key in t.depends_on:
            raise ValueError(f"task '{t.key}' depends on itself")
        missing = [d for d in t.depends_on if d not in known]
        if missing:
            raise ValueError(f"task '{t.key}' depends on unknown tasks {missing}")
    # Kahn's algorithm: leftover nodes => cycle
    indeg = {t.key: len(t.depends_on) for t in tasks}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for t in tasks:
        for d in t.depends_on:
            children[d].append(t.key)
    queue = [k for k, n in indeg.items() if n == 0]
    seen = 0
    while queue:
        k = queue.pop()
        seen += 1
        for c in children[k]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    if seen != len(keys):
        raise ValueError("task dependencies contain a cycle")


class ExecutionPlan(Contract):
    version: int = Field(default=1, ge=1)
    goal: str
    website_purpose: str
    business_model: str
    expected_functionality: list[str]
    rationale: str
    tasks: list[Task]

    @model_validator(mode="after")
    def _dag(self):
        _validate_dag(self.tasks)
        return self

    @classmethod
    def from_draft(cls, draft: PlanDraft, version: int = 1) -> "ExecutionPlan":
        data = draft.model_dump()
        data["tasks"] = [Task(**t).model_dump() for t in data["tasks"]]
        return cls(version=version, **data)

    # ---- scheduling helpers the Manager uses to decide parallel vs sequential
    def _by_key(self) -> dict[str, Task]:
        return {t.key: t for t in self.tasks}

    def ready_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies are all completed (safe to run
        together => the Manager fans these out in parallel)."""
        done = {t.key for t in self.tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)}
        return [
            t for t in self.tasks if t.status == TaskStatus.PENDING and set(t.depends_on) <= done
        ]

    def batches(self) -> list[list[str]]:
        """Topological levels: tasks in one level can run in parallel."""
        level: dict[str, int] = {}
        by_key = self._by_key()

        def depth(k: str) -> int:
            if k not in level:
                deps = by_key[k].depends_on
                level[k] = 0 if not deps else 1 + max(depth(d) for d in deps)
            return level[k]

        for k in by_key:
            depth(k)
        out: dict[int, list[str]] = {}
        for k, lv in level.items():
            out.setdefault(lv, []).append(k)
        return [out[i] for i in sorted(out)]

    def set_status(self, key: str, status: TaskStatus, error: str | None = None) -> None:
        t = self._by_key()[key]
        t.status = status
        t.error = error

    def downstream_of(self, key: str) -> set[str]:
        """All tasks that (transitively) depend on `key` — what must be
        invalidated when `key` is re-run after user feedback."""
        out: set[str] = set()
        frontier = [key]
        while frontier:
            cur = frontier.pop()
            for t in self.tasks:
                if cur in t.depends_on and t.key not in out:
                    out.add(t.key)
                    frontier.append(t.key)
        return out

    # ---- revision support (user feedback => re-run only what is affected)
    def active_task(self, agent: str) -> Task | None:
        live = [
            t for t in self.tasks if t.agent.value == agent and t.status != TaskStatus.SUPERSEDED
        ]
        return live[-1] if live else None

    def _next_key(self, key: str) -> str:
        base = re.sub(r"_r\d+$", "", key)
        n = 1 + max(
            [
                int(m.group(1))
                for t in self.tasks
                if (m := re.fullmatch(rf"{re.escape(base)}_r(\d+)", t.key))
            ]
            or [1]
        )
        return f"{base}_r{n}"

    def rerun(self, keys: set[str]) -> dict[str, str]:
        """Invalidate `keys` and everything downstream of them.

        Tasks that already ran are SUPERSEDED and cloned under a new key (a new
        ledger row, so a new artifact version); not-yet-run tasks keep their key
        and are just re-wired. Returns {old_key: new_key}. Unaffected completed
        tasks (e.g. research the user did not touch) are never re-executed.
        """
        by = self._by_key()
        closure = set(keys)
        for k in list(keys):
            closure |= self.downstream_of(k)
        ran = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)
        mapping = {
            t.key: self._next_key(t.key) for t in self.tasks if t.key in closure and t.status in ran
        }
        clones = []
        for old, new in mapping.items():
            t = by[old]
            clones.append(
                Task(
                    key=new, agent=t.agent, description=t.description, depends_on=list(t.depends_on)
                )
            )
            t.status = TaskStatus.SUPERSEDED
        self.tasks.extend(clones)
        for t in self.tasks:
            if t.status != TaskStatus.SUPERSEDED:
                t.depends_on = [mapping.get(d, d) for d in t.depends_on]
        self.version += 1
        ExecutionPlan.model_validate(self.model_dump())  # still a valid DAG?
        return mapping
