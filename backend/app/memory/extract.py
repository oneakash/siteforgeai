"""Deterministic fact extraction: typed artifacts -> small, topic-keyed memories.

No LLM involved: facts come from validated contracts, so they are cheap, exact
and replay-safe. One memory per TOPIC (palette, typography, tone, ...) keeps
retrieval precise ("which colors?" finds the palette, not a whole guideline).
"""

from app.contracts import (
    AudienceReport,
    BrandGuideline,
    CompetitorReport,
    NicheReport,
    SEOStrategy,
    Wireframe,
)
from app.memory.types import FactSpec


def _j(items, n: int | None = None) -> str:
    return ", ".join(list(items)[:n] if n else items)


def brand_facts(b: BrandGuideline, artifact_id: str | None = None) -> list[FactSpec]:
    meta = {"revision": b.revision, "artifact_id": artifact_id, "approved": True}
    p, pe, m, c, t = b.positioning, b.personality, b.messaging, b.palette, b.typography

    def f(topic, text):
        return FactSpec("brand_decision", f"brand.{topic}", text, dict(meta))  # noqa: E731

    return [
        f(
            "positioning",
            f"Brand positioning for {b.brand_name}: {p.statement} Value proposition: {p.value_proposition} "
            f"Differentiators: {_j(p.differentiators)}.",
        ),
        f(
            "personality",
            f"Brand personality traits: {_j(pe.traits)}. Tone of voice: {pe.tone_of_voice} "
            f"Do: {_j(pe.voice_dos)}. Don't: {_j(pe.voice_donts)}.",
        ),
        f(
            "messaging",
            f'Brand tagline: "{m.tagline}". Key messages: {_j(m.key_messages)}. Elevator pitch: {m.elevator_pitch}',
        ),
        f(
            "palette",
            f"Approved color palette: primary {c.primary}, secondary {c.secondary}, accent {c.accent}, "
            f"background {c.background}, surface {c.surface}, text {c.text}. {c.rationale}",
        ),
        f(
            "typography",
            f"Approved typography: headings use {t.heading_font} ({t.heading_fallback}), body uses "
            f"{t.body_font} ({t.body_fallback}). {t.usage_notes}",
        ),
        f("logo", f"Logo direction: {b.logo.concept} Style: {b.logo.style}. {b.logo.usage_notes}"),
        f(
            "imagery",
            f"Imagery guidelines: photography {b.imagery.photo_style}; illustration {b.imagery.illustration_style}; "
            f"avoid: {_j(b.imagery.avoid)}.",
        ),
        f(
            "ui",
            f"UI/UX direction: style {_j(b.ui_direction.style_keywords)}; layout principles "
            f"{_j(b.ui_direction.layout_principles)}; components: {b.ui_direction.component_style}; motion: {b.ui_direction.motion}",
        ),
    ]


def research_facts(
    niche: NicheReport | None = None,
    audience: AudienceReport | None = None,
    competitors: CompetitorReport | None = None,
    seo: SEOStrategy | None = None,
) -> list[FactSpec]:
    out: list[FactSpec] = []
    if niche:
        out.append(
            FactSpec(
                "niche_insight",
                "research.niche",
                f"Niche: {niche.niche}. Business model: {niche.business_model}. {niche.summary} "
                f"Trends: {_j([t.trend for t in niche.market_trends])}. Typical services: {_j(niche.typical_services)}.",
            )
        )
    if audience:
        out.append(
            FactSpec(
                "audience_insight",
                "research.audience",
                f"Target audience: {_j([a.name for a in audience.primary_audiences])}. "
                f"Needs: {_j(audience.customer_needs)}. Pain points: {_j(audience.pain_points)}. "
                f"Personas: {_j([f'{p.name} ({p.occupation}) wants {p.goals[0]}' for p in audience.personas])}.",
            )
        )
    if competitors:
        out.append(
            FactSpec(
                "competitor_insight",
                "research.competitors",
                f"Competitors: {_j([c.name for c in competitors.competitors])}. Common features: "
                f"{_j(competitors.common_features)}. Differentiation opportunities: {_j(competitors.differentiation_opportunities)}.",
            )
        )
    if seo:
        out.append(
            FactSpec(
                "seo_insight",
                "research.seo.keywords",
                f"Primary SEO keywords: {_j([k.term for k in seo.primary_keywords])}. "
                f"Long-tail keywords: {_j([k.term for k in seo.long_tail_keywords])}.",
            )
        )
        out.append(
            FactSpec(
                "seo_insight",
                "research.seo.pages",
                "Recommended SEO pages: "
                + _j([f"{p.slug} (targets '{p.target_keyword}')" for p in seo.recommended_pages])
                + ".",
            )
        )
    return out


def architecture_facts(w: Wireframe, artifact_id: str | None = None) -> list[FactSpec]:
    meta = {"artifact_id": artifact_id}
    pages = "; ".join(
        f"{p.slug} {p.title} [{_j([s.section_type.value for s in p.sections])}]" for p in w.pages
    )

    def nav(items):
        return _j(
            [
                n.label + (f" > {_j([c.label for c in n.children])}" if n.children else "")
                for n in items
            ]
        )

    ctas = [w.primary_cta, *w.secondary_ctas]
    out = [
        FactSpec(
            "architecture",
            "architecture.sitemap",
            f"Website sitemap and page sections: {pages}.",
            meta,
        ),
        FactSpec(
            "architecture",
            "architecture.navigation",
            f"Main navigation: {nav(w.navigation)}. Footer links: {_j(w.footer_links) or 'none'}.",
            meta,
        ),
        FactSpec(
            "architecture",
            "architecture.ctas",
            "Calls to action: "
            + _j(
                [
                    f"{c.label} ({c.action}{' -> ' + c.target_slug if c.target_slug else ''})"
                    for c in ctas
                ]
            )
            + ".",
            meta,
        ),
    ]
    if w.functional_requirements:
        out.append(
            FactSpec(
                "architecture",
                "architecture.functionality",
                "Functional requirements: "
                + _j([f"{r.name}: {r.description}" for r in w.functional_requirements])
                + ".",
                meta,
            )
        )
    return out
