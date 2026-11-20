from typing import Literal

from pydantic import Field

from .common import Contract, ShortText, Slug


# ---------------- Niche ----------------
class Trend(Contract):
    trend: ShortText
    impact_on_website: ShortText


class Term(Contract):
    term: str
    meaning: ShortText


class NicheReport(Contract):
    niche: str
    business_model: ShortText
    summary: str = Field(min_length=20, max_length=1500)
    industry_characteristics: list[ShortText] = Field(min_length=3)
    market_trends: list[Trend] = Field(min_length=2)
    opportunities: list[ShortText] = Field(min_length=2)
    challenges: list[ShortText] = Field(min_length=2)
    typical_services: list[ShortText] = Field(min_length=3)
    terminology: list[Term] = Field(min_length=3)


# ---------------- Audience ----------------
class AudienceSegment(Contract):
    name: str
    description: ShortText
    demographics: ShortText
    interests: list[ShortText] = Field(min_length=1)


class Persona(Contract):
    name: str
    age_range: str
    occupation: str
    goals: list[ShortText] = Field(min_length=1)
    pain_points: list[ShortText] = Field(min_length=1)
    motivations: list[ShortText] = Field(min_length=1)
    purchase_behavior: ShortText
    expectations_from_website: list[ShortText] = Field(min_length=1)


class AudienceReport(Contract):
    primary_audiences: list[AudienceSegment] = Field(min_length=1)
    secondary_audiences: list[AudienceSegment] = Field(default_factory=list)
    customer_needs: list[ShortText] = Field(min_length=3)
    pain_points: list[ShortText] = Field(min_length=2)
    personas: list[Persona] = Field(min_length=2, max_length=5)


# ---------------- Competitors ----------------
class Competitor(Contract):
    name: str
    url: str | None = None
    positioning: ShortText
    strengths: list[ShortText] = Field(min_length=1)
    weaknesses: list[ShortText] = Field(min_length=1)
    site_structure: list[ShortText] = Field(min_length=1)
    notable_features: list[ShortText] = Field(default_factory=list)
    messaging_notes: ShortText
    # Honesty flag: an LLM without search can hallucinate competitors.
    evidence: Literal["web_search", "model_knowledge"]


class CompetitorReport(Contract):
    competitors: list[Competitor] = Field(min_length=3, max_length=8)
    common_site_patterns: list[ShortText] = Field(min_length=2)
    common_features: list[ShortText] = Field(min_length=2)
    differentiation_opportunities: list[ShortText] = Field(min_length=2)


# ---------------- SEO ----------------
class Keyword(Contract):
    term: str
    intent: Literal["informational", "navigational", "commercial", "transactional"]
    priority: Literal["high", "medium", "low"]


class PageRecommendation(Contract):
    slug: Slug
    title: ShortText
    target_keyword: str
    intent: Literal["informational", "navigational", "commercial", "transactional"]
    required: bool = True


class SEOStrategy(Contract):
    primary_keywords: list[Keyword] = Field(min_length=2)
    secondary_keywords: list[Keyword] = Field(min_length=2)
    long_tail_keywords: list[Keyword] = Field(min_length=3)
    recommended_pages: list[PageRecommendation] = Field(min_length=2)
    content_topics: list[ShortText] = Field(min_length=2)
    structure_recommendations: list[ShortText] = Field(min_length=2)
    strategy_summary: str = Field(min_length=20, max_length=1500)


class ResearchDigest(Contract):
    """Manager's compact consolidation of all research. Downstream agents get this
    instead of four full reports (context compression)."""

    niche: str = ""
    business_model: str = ""
    top_trends: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    primary_keywords: list[str] = Field(default_factory=list)
    recommended_pages: list[str] = Field(default_factory=list)
    source_artifact_ids: dict[str, str] = Field(
        default_factory=dict
    )  # kind -> artifact id it was built from
