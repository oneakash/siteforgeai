"""Output rules for generated sections.

`Section.content` is deliberately a free-form dict (the Site Document stays readable for
old versions and for hand edits). That makes the *rules* the contract: what the model must
emit per section type, and what the renderer knows how to draw.

This module is the single source of truth for both:
  * `describe_content_rules()` renders the rules into the agent prompt, and
  * `validate_page()` enforces them on the agent's output.
A violation is returned as a human-readable problem; `run_agent` feeds the problems back to
the model as a corrective re-prompt, so the model fixes its own output before it is saved.

Strict on the way in (model output), tolerant on the way out: stored documents are NOT
re-validated with these rules, and the renderer still accepts the older shapes.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Any

from .common import Slug, wcag_contrast
from .site import REQUIRED_CONTENT_KEYS, Page, Section
from .wireframe import SectionType

# --------------------------------------------------------------------------- limits

MIN_SECTIONS_PER_PAGE = 2
MAX_SECTIONS_PER_PAGE = 8
MIN_PLACEHOLDER_CONTRAST = 3.0  # label text on the placehold.co image (large text, WCAG AA)
FIELD_TYPES = ("text", "email", "tel", "textarea")

# Per-key character caps. Anything else falls back to DEFAULT_MAX_LEN.
DEFAULT_MAX_LEN = 600
MAX_LEN: dict[str, int] = {
    "heading": 140,
    "subheading": 300,
    "title": 120,
    "question": 200,
    "label": 80,
    "author": 80,
    "role": 80,
    "price": 40,
    "value": 40,
    "features": 160,
    "quote": 500,
    "description": 600,
    "answer": 1200,
    "address": 200,
    "body": 4000,
}

_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z!][^>]*>")
_SLUG = re.compile(Slug.__metadata__[0].pattern)  # type: ignore[attr-defined]
_EXTERNAL_URL = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


# --------------------------------------------------------------------------- the rules


@dataclass(frozen=True)
class ItemRule:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    min_items: int = 2
    max_items: int = 12


@dataclass(frozen=True)
class SectionRule:
    items: ItemRule | None = None
    optional_text: tuple[str, ...] = ()
    needs_image: bool = False


# content keys that are objects/lists rather than text
STRUCTURED_KEYS = ("items", "fields", "primary_cta")

_CARD = ItemRule(required=("title", "description"))

RULES: dict[SectionType, SectionRule] = {
    SectionType.HERO: SectionRule(optional_text=(), needs_image=True),
    SectionType.FEATURES: SectionRule(items=_CARD),
    SectionType.SERVICES: SectionRule(items=_CARD),
    SectionType.PROCESS_STEPS: SectionRule(items=_CARD),
    SectionType.TEAM: SectionRule(items=_CARD),
    SectionType.CATALOG: SectionRule(items=ItemRule(("title", "description"), ("price",))),
    SectionType.PRICING: SectionRule(
        items=ItemRule(("title", "price"), ("description", "features"), max_items=4)
    ),
    SectionType.FAQ: SectionRule(items=ItemRule(("question", "answer"), min_items=3)),
    SectionType.TESTIMONIALS: SectionRule(items=ItemRule(("quote", "author"), ("role",))),
    SectionType.STATS: SectionRule(items=ItemRule(("value", "label"), max_items=6)),
    SectionType.GALLERY: SectionRule(items=ItemRule(("label",), ("caption",)), needs_image=True),
    SectionType.ABOUT: SectionRule(),
    SectionType.RICH_TEXT: SectionRule(optional_text=("heading",)),
    SectionType.CTA_BANNER: SectionRule(optional_text=("subheading",)),
    SectionType.CONTACT_FORM: SectionRule(optional_text=("subheading",)),
    SectionType.BLOG_LIST: SectionRule(),
    SectionType.MAP_LOCATION: SectionRule(),
}
assert set(RULES) == set(SectionType) == set(REQUIRED_CONTENT_KEYS)  # a new type needs a rule


def section_prefix(slug: str) -> str:
    """'/' -> 'home', '/about' -> 'about', '/services/web' -> 'services-web'.

    Every section_id on a page starts with this prefix, which is what keeps ids unique across
    pages that are generated in parallel without seeing each other."""
    return "-".join(p for p in slug.split("/") if p) or "home"


def describe_content_rules() -> str:
    """The rules above as prompt text (generated, so prompt and validator cannot drift)."""
    lines = []
    for t in SectionType:
        rule, required = RULES[t], REQUIRED_CONTENT_KEYS[t]
        parts = [k for k in required if k not in STRUCTURED_KEYS]
        parts += [f"{k}?" for k in rule.optional_text]
        if "primary_cta" in required:
            parts.append("primary_cta{label, href?}")
        if "fields" in required:
            parts.append(f"fields[ str | {{label, type?, required?}} ] (type: {'|'.join(FIELD_TYPES)})")
        if rule.items:
            keys = [*rule.items.required, *(f"{k}?" for k in rule.items.optional)]
            parts.append(
                f"items[{rule.items.min_items}-{rule.items.max_items}] of {{{', '.join(keys)}}}"
            )
        image = " + image_placeholder (required)" if rule.needs_image else ""
        lines.append(f"- {t.value}: content = {{{', '.join(parts)}}}{image}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- checks


def _walk_strings(value: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """Yield (path, key, text) for every string inside content."""
    if isinstance(value, str):
        yield path, path.rsplit(".", 1)[-1].split("[")[0], value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_strings(v, f"{path}[{i}]")


def _check_link(href: Any, where: str, available_pages: Collection[str] | None) -> list[str]:
    if not isinstance(href, str) or not href:
        return [f"{where}: href must be a non-empty string"]
    if _EXTERNAL_URL.match(href):
        return []
    if not href.startswith("/") or not _SLUG.match(href):
        return [f"{where}: href '{href}' must be an https:// URL or a page slug like '/contact'"]
    if available_pages is not None and href not in available_pages:
        return [f"{where}: href '{href}' is not a page of this site; use one of {sorted(available_pages)}"]
    return []


def _check_cta(cta: Any, where: str, available_pages: Collection[str] | None) -> list[str]:
    if not isinstance(cta, dict):
        return [f"{where} must be an object like {{\"label\": \"Book now\", \"href\": \"/contact\"}}"]
    label = cta.get("label")
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
        return [f"{where}.label must be 1-40 characters"]
    if cta.get("href") is not None:
        return _check_link(cta["href"], f"{where}.href", available_pages)
    return []


def _check_fields(fields: Any, where: str) -> list[str]:
    if not isinstance(fields, list) or not 1 <= len(fields) <= 10:
        return [f"{where} must be a list of 1-10 form fields"]
    problems = []
    for i, f in enumerate(fields):
        if isinstance(f, str) and f.strip():
            continue
        if not isinstance(f, dict) or not (f.get("label") or f.get("name")):
            problems.append(f"{where}[{i}] needs a label (string or object with 'label')")
            continue
        if f.get("type", "text") not in FIELD_TYPES:
            problems.append(f"{where}[{i}].type must be one of {list(FIELD_TYPES)}")
        if "required" in f and not isinstance(f["required"], bool):
            problems.append(f"{where}[{i}].required must be true or false")
    return problems


def _check_items(items: Any, rule: ItemRule, where: str) -> list[str]:
    if not isinstance(items, list):
        return [f"{where} must be a list of objects"]
    if not rule.min_items <= len(items) <= rule.max_items:
        return [f"{where} needs {rule.min_items}-{rule.max_items} items, got {len(items)}"]
    problems = []
    for i, it in enumerate(items):
        at = f"{where}[{i}]"
        if not isinstance(it, dict):
            problems.append(f"{at} must be an object with keys {list(rule.required)}")
            continue
        for key in rule.required:
            if not isinstance(it.get(key), str) or not it[key].strip():
                problems.append(f"{at}.{key} is required (non-empty text)")
        if "features" in it and not (
            isinstance(it["features"], list) and all(isinstance(x, str) and x for x in it["features"])
        ):
            problems.append(f"{at}.features must be a list of strings")
    return problems


def _check_image(section: Section, rule: SectionRule) -> list[str]:
    ph = section.image_placeholder
    if ph is None:
        return ["image_placeholder is required for this section type"] if rule.needs_image else []
    ratio = wcag_contrast(f"#{ph.bg_hex}", f"#{ph.text_hex}")
    if ratio < MIN_PLACEHOLDER_CONTRAST:
        return [
            f"image_placeholder text #{ph.text_hex} on #{ph.bg_hex} has contrast {ratio:.1f}; "
            f"need >= {MIN_PLACEHOLDER_CONTRAST}. Pick a darker/lighter text_hex."
        ]
    return []


def validate_section(
    section: Section, available_pages: Collection[str] | None = None
) -> list[str]:
    rule, c = RULES[section.type], section.content
    problems: list[str] = []

    for path, key, text in _walk_strings(c):
        if _HTML_TAG.search(text):
            problems.append(f"content.{path} contains HTML/markup; write plain text only")
        elif len(text) > MAX_LEN.get(key, DEFAULT_MAX_LEN):
            problems.append(
                f"content.{path} is {len(text)} chars; max {MAX_LEN.get(key, DEFAULT_MAX_LEN)}"
            )

    required = REQUIRED_CONTENT_KEYS[section.type]
    for key in (*(k for k in required if k not in STRUCTURED_KEYS), *rule.optional_text):
        if key in c and not isinstance(c[key], str):
            problems.append(f"content.{key} must be text")
    if "primary_cta" in required:
        problems += _check_cta(c.get("primary_cta"), "content.primary_cta", available_pages)
    if "fields" in required:
        problems += _check_fields(c.get("fields"), "content.fields")
    if rule.items is not None:
        problems += _check_items(c.get("items"), rule.items, "content.items")
    problems += [f"image_placeholder: {p}" for p in _check_image(section, rule)]
    return [f"section '{section.section_id}' ({section.type.value}): {p}" for p in problems]


def validate_page(
    page: Page,
    *,
    expected_slug: str | None = None,
    available_pages: Collection[str] | None = None,
) -> list[str]:
    """All problems with one generated page (empty list = OK)."""
    problems: list[str] = []
    if expected_slug is not None and page.slug != expected_slug:
        problems.append(f"slug must be exactly '{expected_slug}', got '{page.slug}'")

    n = len(page.sections)
    if not MIN_SECTIONS_PER_PAGE <= n <= MAX_SECTIONS_PER_PAGE:
        problems.append(
            f"page needs {MIN_SECTIONS_PER_PAGE}-{MAX_SECTIONS_PER_PAGE} sections, got {n}"
        )
    if page.slug == "/" and page.sections[0].type != SectionType.HERO:
        problems.append("the homepage's first section must be a 'hero'")
    if sum(s.type == SectionType.HERO for s in page.sections) > 1:
        problems.append("a page can have only one 'hero' section")

    prefix = section_prefix(expected_slug or page.slug)
    for s in page.sections:
        if not s.section_id.startswith(f"{prefix}-"):
            problems.append(
                f"section_id '{s.section_id}' must start with '{prefix}-' (e.g. '{prefix}-{s.type.value.replace('_', '-')}')"
            )
        problems += validate_section(s, available_pages)
    return problems
