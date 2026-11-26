"""Minimal VALID payloads for every contract (deep-copied per test)."""

import copy

CTA = {"label": "Book now", "action": "link", "target_slug": "/contact"}

PALETTE = {
    "primary": "#0B3D2E",
    "secondary": "#1F5C47",
    "accent": "#C9A227",
    "background": "#0F1A15",
    "surface": "#16251E",
    "text": "#F4F1E8",
    "rationale": "Deep green and gold convey premium heritage.",
}


def brand():
    return copy.deepcopy(
        {
            "brand_name": "Aurum Escapes",
            "positioning": {
                "statement": "Luxury private travel.",
                "value_proposition": "Bespoke journeys, zero friction.",
                "differentiators": ["Private concierge", "Insider access"],
            },
            "personality": {
                "traits": ["refined", "warm", "assured"],
                "tone_of_voice": "Confident, understated.",
                "voice_dos": ["Be specific", "Be warm"],
                "voice_donts": ["No hype", "No jargon"],
            },
            "messaging": {
                "tagline": "Travel, tailored.",
                "key_messages": ["Bespoke", "Private", "Seamless"],
                "elevator_pitch": "We design private journeys end to end.",
            },
            "palette": PALETTE,
            "typography": {
                "heading_font": "Playfair Display",
                "body_font": "Inter",
                "usage_notes": "Serif headings.",
            },
            "logo": {
                "concept": "Monogram A in gold",
                "style": "Minimal",
                "usage_notes": "Clear space = A height.",
            },
            "imagery": {
                "photo_style": "Warm natural light",
                "illustration_style": "Line art",
                "avoid": ["Stock cliches"],
            },
            "ui_direction": {
                "style_keywords": ["dark", "elegant", "spacious"],
                "layout_principles": ["Generous whitespace", "Big imagery"],
                "component_style": "Soft corners, thin gold rules",
                "motion": "Subtle fades",
            },
            "inspirations": ["Aman Resorts", "Black Tomato"],
        }
    )


def seo():
    def kw(t):
        return {"term": t, "intent": "commercial", "priority": "high"}

    return copy.deepcopy(
        {
            "primary_keywords": [kw("luxury travel agency"), kw("private tours")],
            "secondary_keywords": [kw("bespoke holidays"), kw("custom itineraries")],
            "long_tail_keywords": [
                kw("private safari for couples"),
                kw("luxury honeymoon planner"),
                kw("family villa holidays"),
            ],
            "recommended_pages": [
                {
                    "slug": "/",
                    "title": "Home",
                    "target_keyword": "luxury travel agency",
                    "intent": "commercial",
                },
                {
                    "slug": "/destinations",
                    "title": "Destinations",
                    "target_keyword": "private tours",
                    "intent": "commercial",
                    "required": True,
                },
            ],
            "content_topics": ["Honeymoon guides", "Safari planning"],
            "structure_recommendations": ["Destination hubs", "Internal linking from blog"],
            "strategy_summary": "Own high-intent luxury queries through destination hubs.",
        }
    )


def section_spec(t="features"):
    return {"section_type": t, "purpose": "Explain value", "content_requirements": ["3 benefits"]}


def wireframe():
    return copy.deepcopy(
        {
            "pages": [
                {
                    "slug": "/",
                    "title": "Home",
                    "purpose": "Convert",
                    "meta_description": "Luxury travel.",
                    "sections": [section_spec("hero"), section_spec("features")],
                },
                {
                    "slug": "/destinations",
                    "title": "Destinations",
                    "purpose": "Browse",
                    "meta_description": "Where we go.",
                    "sections": [section_spec("catalog"), section_spec("faq")],
                },
                {
                    "slug": "/contact",
                    "title": "Contact",
                    "purpose": "Enquire",
                    "meta_description": "Talk to us.",
                    "sections": [section_spec("contact_form"), section_spec("map_location")],
                },
            ],
            "navigation": [
                {"label": "Home", "slug": "/"},
                {"label": "Destinations", "slug": "/destinations"},
                {"label": "Contact", "slug": "/contact"},
            ],
            "footer_links": ["/contact"],
            "primary_cta": CTA,
        }
    )


def plan_draft():
    def t(k, a, d=()):
        return {"key": k, "agent": a, "description": f"{a} work", "depends_on": list(d)}

    return copy.deepcopy(
        {
            "goal": "Launch a luxury travel site",
            "website_purpose": "Generate enquiries",
            "business_model": "Service-based bookings",
            "expected_functionality": ["Enquiry form"],
            "rationale": "Research in parallel, then brand, then build.",
            "tasks": [
                t("niche", "niche_analysis"),
                t("audience", "audience_research"),
                t("competitors", "competitor_analysis"),
                t("seo", "seo_analysis"),
                t("brand", "brand_guideline", ["niche", "audience", "competitors", "seo"]),
                t("wireframe", "wireframe", ["brand"]),
            ],
        }
    )


def site():
    def sec(i, typ, **c):
        return {"section_id": i, "type": typ, "content": c}

    return copy.deepcopy(
        {
            "brand_name": "Aurum Escapes",
            "tokens": {"colors": PALETTE, "heading_font": "Playfair Display", "body_font": "Inter"},
            "navigation": [
                {"label": "Home", "slug": "/"},
                {"label": "Contact", "slug": "/contact"},
            ],
            "pages": [
                {
                    "slug": "/",
                    "title": "Home",
                    "meta": {
                        "title": "Aurum Escapes",
                        "description": "Luxury private travel, designed around you.",
                    },
                    "sections": [
                        sec(
                            "home-hero",
                            "hero",
                            heading="Travel, tailored.",
                            subheading="Private journeys.",
                            primary_cta={"label": "Enquire"},
                        ),
                        sec(
                            "home-features", "features", heading="Why us", items=[{"t": "Private"}]
                        ),
                    ],
                },
                {
                    "slug": "/contact",
                    "title": "Contact",
                    "meta": {
                        "title": "Contact us",
                        "description": "Get in touch and we will design your journey.",
                    },
                    "sections": [
                        sec(
                            "contact-form",
                            "contact_form",
                            heading="Talk to us",
                            fields=["name", "email"],
                        )
                    ],
                },
            ],
        }
    )


def page(slug: str = "/"):
    """A generated Page that satisfies the section rules (contracts/section_rules.py)."""
    ph = {"width": 1200, "height": 600, "bg_hex": "1d3557", "text_hex": "f1faee"}

    def sec(i, typ, image=None, **c):
        out = {"section_id": i, "type": typ, "content": c}
        if image:
            out["image_placeholder"] = {**ph, "label": image}
        return out

    pages = {
        "/": {
            "title": "Home",
            "meta": {
                "title": "Aurum Escapes | Luxury Travel",
                "description": "Tailor-made luxury journeys, planned end to end by travel designers.",
            },
            "sections": [
                sec(
                    "home-hero",
                    "hero",
                    image="Hero",
                    heading="Travel, tailored.",
                    subheading="Private journeys designed around you.",
                    primary_cta={"label": "Plan my trip", "href": "/contact"},
                ),
                sec(
                    "home-features",
                    "features",
                    heading="Why Aurum",
                    items=[
                        {"title": "Private", "description": "Never a group tour."},
                        {"title": "Local", "description": "Guides who live there."},
                        {"title": "Seamless", "description": "One point of contact."},
                    ],
                ),
                sec(
                    "home-faq",
                    "faq",
                    heading="Questions",
                    items=[
                        {"question": f"Question {n}?", "answer": f"Answer {n}."} for n in range(3)
                    ],
                ),
            ],
        },
        "/about": {
            "title": "About",
            "meta": {
                "title": "About Aurum Escapes",
                "description": "Meet the travel designers behind Aurum Escapes and how we work.",
            },
            "sections": [
                sec("about-story", "about", heading="Our story", body="Founded by travellers."),
                sec(
                    "about-team",
                    "team",
                    heading="The team",
                    items=[
                        {"title": "Ava", "description": "Founder"},
                        {"title": "Noor", "description": "Designer"},
                    ],
                ),
            ],
        },
        "/contact": {
            "title": "Contact",
            "meta": {
                "title": "Contact Aurum Escapes",
                "description": "Tell us where you want to go and we will design the journey.",
            },
            "sections": [
                sec(
                    "contact-form",
                    "contact_form",
                    heading="Talk to us",
                    fields=[
                        {"label": "Name"},
                        {"label": "Email", "type": "email", "required": True},
                        {"label": "Message", "type": "textarea"},
                    ],
                ),
                sec("contact-map", "map_location", heading="Visit", address="1 Gold Street"),
            ],
        },
    }
    return copy.deepcopy({"slug": slug, **pages[slug]})


# ---------- research + triage samples (used by DemoLLM and tests) ----------
def niche():
    return copy.deepcopy(
        {
            "niche": "Luxury travel",
            "business_model": "Commission + service fees on bespoke trips",
            "summary": "High-touch bespoke travel for affluent clients who value time and access.",
            "industry_characteristics": [
                "Relationship driven",
                "High average order value",
                "Long consideration cycle",
            ],
            "market_trends": [
                {
                    "trend": "Experiential travel",
                    "impact_on_website": "Lead with stories, not packages",
                },
                {
                    "trend": "Sustainable luxury",
                    "impact_on_website": "Show responsible-travel credentials",
                },
            ],
            "opportunities": ["Personalisation at scale", "Concierge positioning"],
            "challenges": ["Trust for high-value bookings", "Seasonality"],
            "typical_services": ["Private tours", "Villa rentals", "Honeymoon planning"],
            "terminology": [
                {"term": "FIT", "meaning": "Fully independent traveller"},
                {"term": "DMC", "meaning": "Destination management company"},
                {"term": "Familiarisation trip", "meaning": "Supplier-hosted research trip"},
            ],
        }
    )


def audience():
    def seg(n):
        return {
            "name": n,
            "description": f"{n} luxury travellers",
            "demographics": "30-60, high income",
            "interests": ["Culture"],
        }

    def persona(n):
        return {
            "name": n,
            "age_range": "35-50",
            "occupation": "Executive",
            "goals": ["Effortless trip"],
            "pain_points": ["No time to plan"],
            "motivations": ["Exclusive access"],
            "purchase_behavior": "Researches for weeks, books by enquiry",
            "expectations_from_website": ["Proof of expertise"],
        }

    return copy.deepcopy(
        {
            "primary_audiences": [seg("Couples")],
            "secondary_audiences": [seg("Families")],
            "customer_needs": ["Trust", "Personalisation", "Speed of response"],
            "pain_points": ["Hidden costs", "Generic itineraries"],
            "personas": [persona("Amara"), persona("Daniel")],
        }
    )


def competitor():
    def c(n):
        return {
            "name": n,
            "positioning": "Ultra-luxury curated trips",
            "strengths": ["Brand"],
            "weaknesses": ["Price"],
            "site_structure": ["Home", "Destinations", "Contact"],
            "messaging_notes": "Aspirational, image-led",
            "evidence": "model_knowledge",
        }

    return copy.deepcopy(
        {
            "competitors": [c("Black Tomato"), c("Abercrombie & Kent"), c("Scott Dunn")],
            "common_site_patterns": ["Full-bleed hero", "Destination hubs"],
            "common_features": ["Enquiry form", "Trip filters"],
            "differentiation_opportunities": ["Transparent pricing bands", "Local-expert profiles"],
        }
    )


ORIGINAL_PALETTE = {
    "primary": "#1D3557",
    "secondary": "#457B9D",
    "accent": "#E63946",
    "background": "#FFFFFF",
    "surface": "#F1FAEE",
    "text": "#1D3557",
    "rationale": "Classic, trustworthy navy.",
}


def brand_original():
    b = brand()
    b["palette"] = copy.deepcopy(ORIGINAL_PALETTE)
    return b


def brand_revised(revision_note="Premium dark green and gold palette."):
    b = brand()
    b["change_summary"] = revision_note
    return b


def triage_brand_only(instruction="Switch to a premium dark green and gold palette."):
    return {
        "affected_agents": ["brand_guideline"],
        "instructions": {"brand_guideline": instruction},
        "touches_research": False,
        "confidence": 0.95,
    }


def triage_audience(instruction="Target younger remote-working travellers."):
    return {
        "affected_agents": ["audience_research", "brand_guideline"],
        "instructions": {
            "audience_research": instruction,
            "brand_guideline": "Reflect the new audience.",
        },
        "touches_research": True,
        "confidence": 0.9,
    }


def triage_unsure():
    return {
        "affected_agents": ["brand_guideline"],
        "instructions": {"brand_guideline": "tbd"},
        "touches_research": False,
        "confidence": 0.3,
        "clarifying_question": "Do you want a lighter or a darker look?",
    }
