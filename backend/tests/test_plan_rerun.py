from app.contracts import ExecutionPlan, PlanDraft, TaskStatus
from tests import sample_data as sd


def done_plan():
    p = ExecutionPlan.from_draft(PlanDraft.model_validate(sd.plan_draft()))
    for k in ("niche", "audience", "competitors", "seo", "brand"):
        p.set_status(k, TaskStatus.COMPLETED)
    return p


def test_rerun_brand_only_leaves_research_untouched_and_rewires_pending_wireframe():
    p = done_plan()
    m = p.rerun({"brand"})
    assert m == {"brand": "brand_r2"}
    st = {t.key: t.status for t in p.tasks}
    assert st["brand"] == TaskStatus.SUPERSEDED and st["brand_r2"] == TaskStatus.PENDING
    assert all(st[k] == TaskStatus.COMPLETED for k in ("niche", "audience", "competitors", "seo"))
    assert next(t for t in p.tasks if t.key == "wireframe").depends_on == ["brand_r2"]
    assert [t.key for t in p.ready_tasks()] == ["brand_r2"]
    assert p.version == 2


def test_rerun_research_cascades_to_brand_but_not_other_research():
    p = done_plan()
    m = p.rerun({"audience"})
    assert set(m) == {"audience", "brand"} and m["audience"] == "audience_r2"
    live = {t.key for t in p.tasks if t.status != TaskStatus.SUPERSEDED}
    assert live == {"niche", "competitors", "seo", "audience_r2", "brand_r2", "wireframe"}
    assert [t.key for t in p.ready_tasks()] == ["audience_r2"]  # brand_r2 waits for it
    assert set(next(t for t in p.tasks if t.key == "brand_r2").depends_on) == {
        "niche",
        "audience_r2",
        "competitors",
        "seo",
    }


def test_second_revision_increments_suffix_and_active_task_follows():
    p = done_plan()
    p.rerun({"brand"})
    p.set_status("brand_r2", TaskStatus.COMPLETED)
    assert p.rerun({"brand_r2"}) == {"brand_r2": "brand_r3"}
    assert p.active_task("brand_guideline").key == "brand_r3"
