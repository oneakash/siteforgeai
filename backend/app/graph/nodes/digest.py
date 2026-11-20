"""Research-digest builder."""

from __future__ import annotations

from typing import Any

from app.contracts import AudienceReport, CompetitorReport, NicheReport, ResearchDigest, SEOStrategy


def build_digest(arts: dict[str, Any], ids: dict[str, str]) -> ResearchDigest:
    n: NicheReport | None = arts.get("niche_report")
    a: AudienceReport | None = arts.get("audience_report")
    c: CompetitorReport | None = arts.get("competitor_report")
    s: SEOStrategy | None = arts.get("seo_strategy")
    return ResearchDigest(
        niche=n.niche if n else "",
        business_model=n.business_model if n else "",
        top_trends=[t.trend for t in n.market_trends[:4]] if n else [],
        needs=list(a.customer_needs[:5]) if a else [],
        personas=[f"{p.name}: {p.goals[0]}" for p in a.personas] if a else [],
        competitors=[x.name for x in c.competitors] if c else [],
        differentiators=(list(c.differentiation_opportunities[:4]) if c else []),
        primary_keywords=[k.term for k in s.primary_keywords] if s else [],
        recommended_pages=[p.slug for p in s.recommended_pages] if s else [],
        source_artifact_ids=ids,
    )
