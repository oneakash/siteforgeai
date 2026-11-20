from .brand import BrandGuideline, ColorPalette
from .common import Contract, wcag_contrast
from .plan import AgentName, ExecutionPlan, PlanDraft, Task, TaskStatus
from .qa import ImagePlan, QAReport
from .research import AudienceReport, CompetitorReport, NicheReport, ResearchDigest, SEOStrategy
from .site import DesignTokens, Page, Section, SiteDocument
from .triage import BrandFeedbackTriage, TriageResult
from .wireframe import Wireframe

# artifact.kind -> model. Used to validate on load and to route by kind.
ARTIFACT_MODELS: dict[str, type[Contract]] = {
    "execution_plan": ExecutionPlan,
    "niche_report": NicheReport,
    "audience_report": AudienceReport,
    "competitor_report": CompetitorReport,
    "seo_strategy": SEOStrategy,
    "brand_guideline": BrandGuideline,
    "wireframe": Wireframe,
    "design_tokens": DesignTokens,
    "image_plan": ImagePlan,
    "page": Page,
    "qa_report": QAReport,
    "research_digest": ResearchDigest,
    "triage_result": TriageResult,
    "brand_feedback_triage": BrandFeedbackTriage,
    "site_document": SiteDocument, 
}

__all__ = [n for n in dir() if not n.startswith("_")]
