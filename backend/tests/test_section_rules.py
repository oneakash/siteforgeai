"""Output validator for generated sections (no database needed)."""

import copy

import pytest

from app.agents.registry import AGENTS, page_is_renderable
from app.agents.runner import run_agent
from app.contracts import Page, SiteDocument
from app.contracts.section_rules import (
    RULES,
    describe_content_rules,
    section_prefix,
    validate_page,
)
from app.contracts.wireframe import SectionType
from tests import sample_data as sd

PAGES = ["/", "/about", "/contact"]


def problems(d: dict, **kw) -> list[str]:
    kw.setdefault("expected_slug", d["slug"])
    kw.setdefault("available_pages", PAGES)
    return validate_page(Page.model_validate(d), **kw)


def home() -> dict:
    return sd.page("/")


# ---------- the happy path ----------
@pytest.mark.parametrize("slug", PAGES)
def test_sample_pages_pass(slug):
    assert problems(sd.page(slug)) == []


def test_validated_pages_assemble_into_a_site_document():
    """Per-page ids are prefixed, so pages generated in parallel can never collide."""
    pages = [sd.page(s) for s in PAGES]
    site = sd.site()
    site["pages"] = pages
    site["navigation"] = [{"label": p["title"], "slug": p["slug"]} for p in pages]
    SiteDocument.model_validate(site)


def test_every_section_type_has_a_rule_and_is_in_the_prompt():
    assert set(RULES) == set(SectionType)
    text = describe_content_rules()
    assert all(f"- {t.value}:" in text for t in SectionType)
    assert describe_content_rules() in AGENTS["website_generation"].system_prompt


def test_section_prefix():
    assert [section_prefix(s) for s in ("/", "/about", "/services/web-design")] == [
        "home",
        "about",
        "services-web-design",
    ]


# ---------- page level ----------
def test_wrong_slug_is_rejected():
    d = sd.page("/about")
    assert any("slug must be exactly '/contact'" in p for p in problems(d, expected_slug="/contact"))


def test_homepage_must_start_with_hero_and_have_one_hero():
    d = home()
    d["sections"].reverse()
    assert any("first section must be a 'hero'" in p for p in problems(d))
    d = home()
    d["sections"].append(copy.deepcopy(d["sections"][0]) | {"section_id": "home-hero-2"})
    assert any("only one 'hero'" in p for p in problems(d))


def test_section_ids_need_the_page_prefix():
    d = sd.page("/about")
    d["sections"][0]["section_id"] = "hero"
    assert any("must start with 'about-'" in p for p in problems(d))


def test_section_count_bounds():
    d = home()
    d["sections"] = d["sections"][:1]
    assert any("needs 2-8 sections" in p for p in problems(d))


# ---------- content ----------
def test_html_in_text_is_rejected_but_plain_angle_brackets_are_fine():
    d = home()
    d["sections"][0]["content"]["heading"] = "<b>Travel</b>, tailored"
    assert any("contains HTML" in p for p in problems(d))
    d["sections"][0]["content"]["heading"] = "Trips for 2 < 3 people"
    assert problems(d) == []


def test_length_caps():
    d = home()
    d["sections"][0]["content"]["heading"] = "x" * 141
    assert any("max 140" in p for p in problems(d))


def test_item_shapes_are_enforced_with_actionable_messages():
    d = home()
    d["sections"][1]["content"]["items"] = [{"t": "Private"}, {"title": "A", "description": "B"}]
    out = problems(d)
    assert any("items[0].title is required" in p for p in out)
    assert any("items[0].description is required" in p for p in out)

    d = home()
    d["sections"][1]["content"]["items"] = [{"title": "A", "description": "B"}]
    assert any("needs 2-12 items, got 1" in p for p in problems(d))

    d = home()
    d["sections"][1]["content"]["items"] = ["just a string", "another"]
    assert any("must be an object" in p for p in problems(d))


def test_faq_needs_three_items_and_question_answer_keys():
    d = home()
    d["sections"][2]["content"]["items"] = [{"title": "Q", "description": "A"}] * 3
    assert any("items[0].question is required" in p for p in problems(d))


@pytest.mark.parametrize(
    "href,ok",
    [
        ("/contact", True),
        ("https://example.com/book", True),
        ("/pricing", False),  # valid slug, but not a page of this site
        ("javascript:alert(1)", False),
        ("//evil.example", False),
        ("http://", False),
        ("contact", False),
    ],
)
def test_cta_links(href, ok):
    d = home()
    d["sections"][0]["content"]["primary_cta"]["href"] = href
    assert (problems(d) == []) is ok


def test_cta_without_href_is_fine_but_needs_a_short_label():
    d = home()
    d["sections"][0]["content"]["primary_cta"] = {"label": "Enquire"}
    assert problems(d) == []
    d["sections"][0]["content"]["primary_cta"] = {"label": "x" * 41}
    assert any("label must be 1-40" in p for p in problems(d))
    d["sections"][0]["content"]["primary_cta"] = "Enquire"
    assert any("must be an object" in p for p in problems(d))


def test_contact_form_fields():
    d = sd.page("/contact")
    d["sections"][0]["content"]["fields"] = [{"label": "Pass", "type": "password"}, {"x": 1}]
    out = problems(d)
    assert any("type must be one of" in p for p in out)
    assert any("fields[1] needs a label" in p for p in out)
    d["sections"][0]["content"]["fields"] = ["Name", "Email"]  # plain strings still accepted
    assert problems(d) == []


def test_visual_sections_need_a_readable_placeholder():
    d = home()
    del d["sections"][0]["image_placeholder"]
    assert any("image_placeholder is required" in p for p in problems(d))
    d = home()
    d["sections"][0]["image_placeholder"].update(bg_hex="e2e8f0", text_hex="ffffff")
    assert any("has contrast" in p for p in problems(d))


# ---------- wiring: the agent validator drives the corrective re-prompt ----------
class ScriptedLLM:
    def __init__(self, *payloads):
        self.payloads, self.messages = list(payloads), []

    async def generate(self, messages, schema, *, tier, meta=None):
        self.messages.append(messages)
        return self.payloads.pop(0)


INPUTS = {"slug": "/", "available_pages": PAGES}


def test_validator_is_registered_on_the_website_agent():
    assert page_is_renderable in AGENTS["website_generation"].validators


async def test_bad_page_is_corrected_before_it_is_saved():
    bad = home()
    bad["sections"][0]["content"]["heading"] = "<h1>Hi</h1>"
    llm = ScriptedLLM(bad, home())
    res = await run_agent(AGENTS["website_generation"], llm=llm, inputs=INPUTS)
    assert res.attempts == 2
    assert "contains HTML" in res.corrections[0]
    assert "contains HTML" in llm.messages[1][-1]["content"]  # the model is told what to fix
    assert res.output.sections[0].content["heading"] == "Travel, tailored."


async def test_wrong_slug_triggers_a_correction():
    llm = ScriptedLLM(sd.page("/about"), home())
    res = await run_agent(AGENTS["website_generation"], llm=llm, inputs=INPUTS)
    assert res.attempts == 2 and "slug must be exactly '/'" in res.corrections[0]
