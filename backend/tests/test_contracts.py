import pytest
from pydantic import ValidationError

from app.contracts import (BrandFeedbackTriage, BrandGuideline, ExecutionPlan, PlanDraft,
                           QAReport, SEOStrategy, SiteDocument, TaskStatus, TriageResult, Wireframe, wcag_contrast)
from tests import sample_data as sd


# ---------- plan ----------
def test_plan_valid_and_batches_show_parallelism():
    plan = ExecutionPlan.from_draft(PlanDraft.model_validate(sd.plan_draft()))
    assert plan.batches() == [["niche", "audience", "competitors", "seo"], ["brand"], ["wireframe"]] or \
        [sorted(b) for b in plan.batches()] == [sorted(["niche", "audience", "competitors", "seo"]), ["brand"], ["wireframe"]]
    assert {t.key for t in plan.ready_tasks()} == {"niche", "audience", "competitors", "seo"}


def test_plan_ready_tasks_advance_and_downstream_invalidation():
    plan = ExecutionPlan.from_draft(PlanDraft.model_validate(sd.plan_draft()))
    for k in ("niche", "audience", "competitors", "seo"):
        plan.set_status(k, TaskStatus.COMPLETED)
    assert [t.key for t in plan.ready_tasks()] == ["brand"]
    assert plan.downstream_of("brand") == {"wireframe"}
    assert plan.downstream_of("niche") == {"brand", "wireframe"}


def test_plan_rejects_cycle_unknown_dep_self_dep_and_manager_task():
    d = sd.plan_draft(); d["tasks"][0]["depends_on"] = ["wireframe"]   # niche -> wireframe -> brand -> niche
    with pytest.raises(ValidationError, match="cycle"):
        PlanDraft.model_validate(d)
    d = sd.plan_draft(); d["tasks"][1]["depends_on"] = ["ghost"]
    with pytest.raises(ValidationError, match="unknown"):
        PlanDraft.model_validate(d)
    d = sd.plan_draft(); d["tasks"][1]["depends_on"] = ["audience"]
    with pytest.raises(ValidationError, match="itself"):
        PlanDraft.model_validate(d)
    d = sd.plan_draft(); d["tasks"][0]["agent"] = "manager"
    with pytest.raises(ValidationError, match="manager"):
        PlanDraft.model_validate(d)


def test_llm_cannot_set_task_status():
    d = sd.plan_draft(); d["tasks"][0]["status"] = "completed"
    with pytest.raises(ValidationError):  # extra='forbid'
        PlanDraft.model_validate(d)


# ---------- brand ----------
def test_brand_valid_roundtrip():
    b = BrandGuideline.model_validate(sd.brand())
    assert BrandGuideline.model_validate_json(b.model_dump_json()) == b


def test_brand_rejects_low_contrast_and_bad_hex():
    d = sd.brand(); d["palette"]["text"] = "#16251F"  # ~ same as background
    with pytest.raises(ValidationError, match="contrast"):
        BrandGuideline.model_validate(d)
    d = sd.brand(); d["palette"]["accent"] = "gold"
    with pytest.raises(ValidationError):
        BrandGuideline.model_validate(d)


def test_wcag_contrast_known_values():
    assert round(wcag_contrast("#000000", "#ffffff"), 1) == 21.0
    assert wcag_contrast("#777777", "#777777") == pytest.approx(1.0)


# ---------- wireframe ----------
def test_wireframe_valid():
    assert Wireframe.model_validate(sd.wireframe()).slugs() == {"/", "/destinations", "/contact"}


@pytest.mark.parametrize("mutate,msg", [
    (lambda w: w["navigation"].append({"label": "Ghost", "slug": "/ghost"}), "missing page"),
    (lambda w: w["pages"].pop(0), "homepage"),
    (lambda w: w["pages"][0]["sections"].reverse(), "hero"),
    (lambda w: w.update(primary_cta={"label": "Go", "action": "link", "target_slug": "/nope"}), "CTA"),
    (lambda w: w["pages"].append(dict(w["pages"][1])), "duplicate"),
    (lambda w: w["pages"][1].update(slug="Bad Slug"), "slug|String should match"),
])
def test_wireframe_rejects(mutate, msg):
    w = sd.wireframe(); mutate(w)
    with pytest.raises(ValidationError, match=msg):
        Wireframe.model_validate(w)


# ---------- site document ----------
def test_site_valid_hashes_are_stable_and_content_sensitive():
    a = SiteDocument.model_validate(sd.site())
    b = SiteDocument.model_validate(sd.site())
    assert a.checksum() == b.checksum()
    d = sd.site(); d["pages"][0]["sections"][0]["content"]["heading"] = "A new heading"
    c = SiteDocument.model_validate(d)
    assert a.changed_sections(c) == ["home-hero"]          # ONLY the edited section differs
    assert a.checksum() != c.checksum()


def test_site_rejects_missing_content_keys_dup_ids_and_bad_nav():
    d = sd.site(); del d["pages"][0]["sections"][0]["content"]["subheading"]
    with pytest.raises(ValidationError, match="missing content keys"):
        SiteDocument.model_validate(d)
    d = sd.site(); d["pages"][1]["sections"][0]["section_id"] = "home-hero"
    with pytest.raises(ValidationError, match="unique"):
        SiteDocument.model_validate(d)
    d = sd.site(); d["navigation"].append({"label": "X", "slug": "/x"})
    with pytest.raises(ValidationError, match="missing page"):
        SiteDocument.model_validate(d)


def test_stale_hash_from_llm_is_overwritten():
    d = sd.site(); d["pages"][0]["sections"][0]["content_hash"] = "deadbeef"
    s = SiteDocument.model_validate(d)
    assert s.pages[0].sections[0].content_hash != "deadbeef"


# ---------- triage / qa ----------
def test_triage_rules():
    with pytest.raises(ValidationError, match="clarifying_question"):
        TriageResult(tasks=[], confidence=0.3)
    with pytest.raises(ValidationError, match="target"):
        TriageResult(tasks=[{"intent": "content_edit", "instruction": "change hero"}], confidence=0.9)
    ok = TriageResult(tasks=[{"intent": "content_edit", "instruction": "change hero",
                              "targets": [{"page_slug": "/", "section_id": "home-hero"}]}], confidence=0.9)
    assert ok.tasks[0].targets[0].section_id == "home-hero"


def test_brand_feedback_triage_consistency():
    ok = BrandFeedbackTriage(affected_agents=["brand_guideline"], instructions={"brand_guideline": "dark green + gold"},
                             touches_research=False, confidence=0.9)
    assert ok.affected_agents[0].value == "brand_guideline"
    with pytest.raises(ValidationError, match="touches_research"):
        BrandFeedbackTriage(affected_agents=["brand_guideline"], instructions={}, touches_research=True, confidence=0.9)


def test_qa_report_coherence():
    with pytest.raises(ValidationError):
        QAReport(passed=True, summary="ok", issues=[{"severity": "error", "location": "global", "description": "x"}])
    with pytest.raises(ValidationError):
        QAReport(passed=False, summary="bad", issues=[])
    r = QAReport(passed=False, summary="bad", issues=[{"severity": "error", "location": "/", "description": "x", "fixable_by_agent": False}])
    assert r.needs_user
