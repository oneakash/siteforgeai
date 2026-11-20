from enum import Enum
from typing import Literal, Optional

from pydantic import Field, model_validator

from .common import Contract, ShortText, Slug


class SectionType(str, Enum):
    HERO = "hero"
    FEATURES = "features"
    SERVICES = "services"
    ABOUT = "about"
    STATS = "stats"
    TESTIMONIALS = "testimonials"
    GALLERY = "gallery"
    PRICING = "pricing"
    FAQ = "faq"
    CTA_BANNER = "cta_banner"
    CONTACT_FORM = "contact_form"
    TEAM = "team"
    BLOG_LIST = "blog_list"
    PROCESS_STEPS = "process_steps"
    CATALOG = "catalog"
    RICH_TEXT = "rich_text"
    MAP_LOCATION = "map_location"


class CTA(Contract):
    label: str = Field(max_length=40)
    action: Literal["link", "form", "call", "booking", "email"]
    target_slug: Optional[Slug] = None


class SectionSpec(Contract):
    section_type: SectionType
    purpose: ShortText
    content_requirements: list[ShortText] = Field(min_length=1)
    audience_need: Optional[ShortText] = None
    seo_keywords: list[str] = Field(default_factory=list)
    cta: Optional[CTA] = None
    requires_visual: bool = Field(default=True, description="True for HERO, GALLERY, TEAM, TESTIMONIALS, etc.")


class PageSpec(Contract):
    slug: Slug
    title: ShortText
    purpose: ShortText
    parent_slug: Optional[Slug] = None
    meta_description: str = Field(max_length=170)
    target_keyword: Optional[str] = None
    sections: list[SectionSpec] = Field(min_length=2)


class NavLeaf(Contract):
    label: str = Field(max_length=30)
    slug: Slug


class NavItem(Contract):
    """Two levels max (item -> children). Deliberately NOT recursive: recursive
    JSON schemas are truncated by Gemini and rejected by OpenAI strict mode."""

    label: str = Field(max_length=30)
    slug: Slug
    children: list[NavLeaf] = Field(default_factory=list)


class FunctionalRequirement(Contract):
    name: str
    description: ShortText
    pages: list[Slug] = Field(default_factory=list)


class Wireframe(Contract):
    pages: list[PageSpec] = Field(min_length=1)
    navigation: list[NavItem] = Field(min_length=1)
    footer_links: list[Slug] = Field(default_factory=list)
    primary_cta: CTA
    secondary_ctas: list[CTA] = Field(default_factory=list)
    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)

    def slugs(self) -> set[str]:
        return {p.slug for p in self.pages}

    @model_validator(mode="after")
    def _consistent(self):
        slugs = [p.slug for p in self.pages]
        if len(set(slugs)) != len(slugs):
            raise ValueError("duplicate page slugs")
        known = set(slugs)
        if "/" not in known:
            raise ValueError("a homepage with slug '/' is required")
        home = next(p for p in self.pages if p.slug == "/")
        if home.sections[0].section_type != SectionType.HERO:
            raise ValueError("the homepage must start with a 'hero' section")

        for p in self.pages:
            if p.parent_slug and p.parent_slug not in known:
                raise ValueError(f"page {p.slug}: unknown parent_slug {p.parent_slug}")

        for n in self.navigation:
            for item in (n, *n.children):
                if item.slug not in known:
                    raise ValueError(f"navigation item '{item.label}' points to missing page {item.slug}")
        for s in self.footer_links:
            if s not in known:
                raise ValueError(f"footer link to missing page {s}")

        for c in [self.primary_cta, *self.secondary_ctas]:
            if c.action == "link" and (not c.target_slug or c.target_slug not in known):
                raise ValueError(f"CTA '{c.label}' is a link but target_slug is missing/unknown")
        for fr in self.functional_requirements:
            for s in fr.pages:
                if s not in known:
                    raise ValueError(f"functional requirement '{fr.name}' references missing page {s}")
        return self

