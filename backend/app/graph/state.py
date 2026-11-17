from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import model_validator

from app.contracts.common import Contract


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    """Reducer: parallel workers each contribute keys; later writes win per key."""
    return {**(a or {}), **(b or {})}


class RootState(TypedDict, total=False):
    # immutable inputs
    project_id: str
    user_id: str
    brand_name: str
    prompt: str
    niche: str
    # manager's working memory (small!). Bulky outputs live in Postgres; state holds ids.
    plan: dict
    task_ids: Annotated[dict[str, str], merge_dicts]
    instructions: Annotated[dict[str, str], merge_dicts]
    artifact_ids: Annotated[dict[str, str], merge_dicts]   # kind -> latest artifact id
    task_results: Annotated[dict[str, dict], merge_dicts]
    specs: list[dict]                                      # (subgraph plumbing)
    # workflow flags
    phase: str
    digest_for: str
    brand_approved: bool
    brand_feedback: str
    review_decision: dict
    clarification: Optional[str]
    clarify_rounds: int


class WorkerPayload(TypedDict, total=False):
    project_id: str
    user_id: str
    brand_name: str
    prompt: str
    niche: str
    task_key: str
    task_id: str
    agent: str
    instruction: str
    is_revision: bool


class ResearchState(TypedDict, total=False):
    project_id: str
    user_id: str
    brand_name: str
    prompt: str
    niche: str
    specs: list[dict]
    artifact_ids: Annotated[dict[str, str], merge_dicts]
    task_results: Annotated[dict[str, dict], merge_dicts]


# ---- human decisions (validated at the API boundary AND inside the nodes)
class ReviewDecision(Contract):
    action: Literal["approve", "revise"]
    feedback: str = ""

    @model_validator(mode="after")
    def _need_feedback(self):
        if self.action == "revise" and not self.feedback.strip():
            raise ValueError("feedback is required when requesting changes")
        return self


class ClarificationAnswer(Contract):
    answer: str


class TaskDecision(Contract):
    action: Literal["retry", "skip"]
