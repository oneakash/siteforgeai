from typing import Literal

from pydantic import Field, model_validator

from .common import Contract, SectionId, ShortText


class QAIssue(Contract):
    severity: Literal["error", "warning"]
    location: str  # e.g. "/about#team-grid" or "global"
    description: ShortText
    fixable_by_agent: bool = True


class QAReport(Contract):
    passed: bool
    issues: list[QAIssue] = Field(default_factory=list)
    summary: ShortText

    @model_validator(mode="after")
    def _coherent(self):
        has_error = any(i.severity == "error" for i in self.issues)
        if self.passed and has_error:
            raise ValueError("passed=true is inconsistent with error-severity issues")
        if not self.passed and not has_error:
            raise ValueError("passed=false requires at least one error-severity issue")
        return self

    @property
    def needs_user(self) -> bool:
        return any(i.severity == "error" and not i.fixable_by_agent for i in self.issues)


class ImageSpec(Contract):
    section_id: SectionId
    alt_text: ShortText
    prompt: str = Field(min_length=10, max_length=800)
    aspect_ratio: Literal["1:1", "4:3", "3:2", "16:9", "9:16"] = "16:9"


class ImagePlan(Contract):
    images: list[ImageSpec] = Field(min_length=1)
    style_notes: str | None = None
