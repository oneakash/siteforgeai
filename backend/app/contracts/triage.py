from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from .common import Contract, SectionId, ShortText, Slug
from .plan import AgentName


class EditIntent(str, Enum):
    CONTENT_EDIT = "content_edit"
    DESIGN_CHANGE = "design_change"
    ADD_SECTION = "add_section"
    REMOVE_SECTION = "remove_section"
    ADD_PAGE = "add_page"
    RESTRUCTURE = "restructure"
    SEO_CHANGE = "seo_change"
    IMAGE_CHANGE = "image_change"
    QUESTION = "question"
    OUT_OF_SCOPE = "out_of_scope"


NEEDS_TARGET = {EditIntent.CONTENT_EDIT, EditIntent.REMOVE_SECTION, EditIntent.IMAGE_CHANGE}


class EditTarget(Contract):
    page_slug: Slug
    section_id: Optional[SectionId] = None


class EditTask(Contract):
    intent: EditIntent
    instruction: ShortText
    targets: list[EditTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def _targets(self):
        if self.intent in NEEDS_TARGET and not self.targets:
            raise ValueError(f"intent {self.intent.value} requires at least one target")
        return self


class TriageResult(Contract):
    """Post-generation chat message -> list of surgical edit tasks."""

    tasks: list[EditTask] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    clarifying_question: Optional[str] = None

    @model_validator(mode="after")
    def _confidence(self):
        if self.confidence < 0.6 and not self.clarifying_question:
            raise ValueError("confidence < 0.6 requires a clarifying_question")
        if not self.tasks and not self.clarifying_question:
            raise ValueError("need at least one task or a clarifying_question")
        return self


class BrandFeedbackTriage(Contract):
    """Brand-review feedback -> which agents must re-run (Scenario 4)."""

    affected_agents: list[AgentName] = Field(min_length=1)
    instructions: dict[str, ShortText]  # agent name -> what to change
    touches_research: bool
    confidence: float = Field(ge=0, le=1)
    clarifying_question: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        research = {AgentName.NICHE, AgentName.AUDIENCE, AgentName.COMPETITOR, AgentName.SEO}
        if self.touches_research != bool(research & set(self.affected_agents)):
            raise ValueError("touches_research must match whether a research agent is in affected_agents")
        extra = set(self.instructions) - {a.value for a in self.affected_agents}
        if extra:
            raise ValueError(f"instructions given for agents not in affected_agents: {sorted(extra)}")
        if self.confidence < 0.6 and not self.clarifying_question:
            raise ValueError("confidence < 0.6 requires a clarifying_question")
        return self
