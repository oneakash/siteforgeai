"""The Site Document: the website as a versioned, declarative JSON model.

Agents never emit HTML. They emit sections of typed content; the renderer
turns the document into HTML. Section ids + content hashes make incremental
edits, diffing and QA possible.
"""
import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from .brand import ColorPalette
from .common import Contract, SectionId, ShortText, Slug
from .wireframe import NavItem, SectionType

# Minimum content keys per section type (validated centrally, not per prompt).
REQUIRED_CONTENT_KEYS: dict[SectionType, list[str]] = {
    SectionType.HERO: ["heading", "subheading", "primary_cta"],
    SectionType.FEATURES: ["heading", "items"],
    SectionType.SERVICES: ["heading", "items"],
    SectionType.ABOUT: ["heading", "body"],
    SectionType.STATS: ["items"],
    SectionType.TESTIMONIALS: ["heading", "items"],
    SectionType.GALLERY: ["heading", "items"],
    SectionType.PRICING: ["heading", "items"],
    SectionType.FAQ: ["heading", "items"],
    SectionType.CTA_BANNER: ["heading", "primary_cta"],
    SectionType.CONTACT_FORM: ["heading", "fields"],
    SectionType.TEAM: ["heading", "items"],
    SectionType.BLOG_LIST: ["heading"],
    SectionType.PROCESS_STEPS: ["heading", "items"],
    SectionType.CATALOG: ["heading", "items"],
    SectionType.RICH_TEXT: ["body"],
    SectionType.MAP_LOCATION: ["heading", "address"],
}


def hash_section(section_type: str, content: dict[str, Any]) -> str:
    canon = json.dumps({"type": section_type, "content": content}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


class DesignTokens(Contract):
    colors: ColorPalette
    heading_font: str
    body_font: str
    base_font_size_px: int = Field(default=16, ge=14, le=20)
    radius: Literal["none", "sm", "md", "lg", "full"] = "md"
    spacing: Literal["compact", "comfortable", "spacious"] = "comfortable"
    style_notes: str = ""


class Section(Contract):
    section_id: SectionId
    type: SectionType
    content: dict[str, Any]
    image_prompts: list[ShortText] = Field(default_factory=list)
    content_hash: str = ""

    @model_validator(mode="after")
    def _check(self):
        missing = [k for k in REQUIRED_CONTENT_KEYS[self.type] if not self.content.get(k)]
        if missing:
            raise ValueError(f"section '{self.section_id}' ({self.type.value}) missing content keys {missing}")
        self.content_hash = hash_section(self.type.value, self.content)  # always recomputed
        return self


class PageMeta(Contract):
    title: str = Field(max_length=70)
    description: str = Field(max_length=170)


class Page(Contract):
    slug: Slug
    title: ShortText
    meta: PageMeta
    sections: list[Section] = Field(min_length=1)


class SiteDocument(Contract):
    version: int = Field(default=1, ge=1)
    brand_name: str
    tokens: DesignTokens
    navigation: list[NavItem] = Field(min_length=1)
    footer_links: list[Slug] = Field(default_factory=list)
    pages: list[Page] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self):
        slugs = [p.slug for p in self.pages]
        if len(set(slugs)) != len(slugs):
            raise ValueError("duplicate page slugs")
        if "/" not in slugs:
            raise ValueError("site needs a '/' page")
        ids = [s.section_id for p in self.pages for s in p.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("section_id must be unique across the whole site")

        for n in self.navigation:
            for item in (n, *n.children):
                if item.slug not in slugs:
                    raise ValueError(f"navigation points to missing page {item.slug}")
        return self

    def checksum(self) -> str:
        canon = self.model_dump_json(exclude={"version"})
        return hashlib.sha256(canon.encode()).hexdigest()

    def section_hashes(self) -> dict[str, str]:
        return {s.section_id: s.content_hash for p in self.pages for s in p.sections}

    def changed_sections(self, other: "SiteDocument") -> list[str]:
        a, b = self.section_hashes(), other.section_hashes()
        return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
