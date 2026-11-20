import pytest

from app.agents.errors import TransientAgentError
from app.agents.llm import CallMeta
from app.contracts import QAReport
from app.llm.router import ModelRef, ModelRouter, OverrideRow, ProviderConfigError, pick_override
from tests.fakes import FakeChat, RateLimitError

OK = {"passed": True, "issues": [], "summary": "fine"}
P1, P2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def R(ref, project=None, agent=None, tier=None, purpose="chat"):
    return OverrideRow(project, agent, tier, purpose, ref)


def test_ref_parsing_handles_slashes_and_colons():
    r = ModelRef.parse("nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert (r.provider, r.model) == ("nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert ModelRef.parse("groq:llama:70b").model == "llama:70b"
    for bad in ("gpt-4.1", "openai:", ""):
        with pytest.raises(ProviderConfigError):
            ModelRef.parse(bad)


def test_override_precedence_most_specific_wins():
    rows = [
        R("g:general"),
        R("g:tier", tier="fast"),
        R("g:agent", agent="qa"),
        R("p:general", project=P1),
        R("p:agent", project=P1, agent="qa"),
        R("other:p2", project=P2),
    ]

    def pick(**kw):
        return pick_override(rows, purpose="chat", **kw)

    assert pick(project_id=P1, agent="qa", tier="fast") == "p:agent"
    assert (
        pick(project_id=P1, agent="seo", tier="fast") == "p:general"
    )  # project beats global tier/agent
    assert pick(project_id=None, agent="qa", tier="fast") == "g:agent"  # agent beats tier
    assert pick(project_id=None, agent="seo", tier="fast") == "g:tier"
    assert pick(project_id=None, agent="seo", tier="reasoning") == "g:general"
    assert (
        pick(project_id=P2, agent="seo", tier="fast") == "other:p2"
    )  # P1's rows never leak into P2
    assert pick_override([], project_id=None, agent=None, tier="fast", purpose="chat") is None
    assert (
        pick_override(
            [R("e:x", purpose="embedding")],
            project_id=None,
            agent=None,
            tier="fast",
            purpose="chat",
        )
        is None
    )


def make_router(rows_box, behaviors, fallbacks=()):
    calls = []

    async def fetch(_pid):
        return rows_box["rows"]

    def factory(ref):
        b = behaviors[str(ref)]
        if isinstance(b, Exception) and isinstance(b, ProviderConfigError):
            raise b
        return FakeChat(
            ref,
            payload=None if isinstance(b, Exception) else b,
            error=b if isinstance(b, Exception) else None,
            calls=calls,
        )

    # defaults are explicit so the test never depends on the developer's .env
    defaults = {"reasoning": "nvidia:default-reasoning", "fast": "nvidia:default-fast"}
    return ModelRouter(
        fetch, fallbacks=list(fallbacks), chat_factory=factory, defaults=defaults
    ), calls


async def test_switch_models_between_calls_without_restart():
    box = {"rows": []}
    router, calls = make_router(
        box,
        {
            "nvidia:default-fast": OK,
            "groq:fast-one": OK,
            "nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b": OK,
        },
    )
    meta = CallMeta(agent="qa", project_id=P1)
    await router.generate([], QAReport, tier="fast", meta=meta)
    assert meta.used_model == "nvidia:default-fast"  # env default
    box["rows"] = [R("groq:fast-one", project=P1)]  # user switches the project to Groq
    meta = CallMeta(agent="qa", project_id=P1)
    await router.generate([], QAReport, tier="fast", meta=meta)
    assert meta.used_model == "groq:fast-one"
    box["rows"] = [
        R("groq:fast-one", project=P1),
        R("nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b", project=P1, agent="qa"),
    ]
    meta = CallMeta(agent="qa", project_id=P1)
    await router.generate([], QAReport, tier="fast", meta=meta)
    assert meta.used_model.startswith("nvidia:")  # per-agent override beats project default
    assert calls == [
        "nvidia:default-fast",
        "groq:fast-one",
        "nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b",
    ]


async def test_failover_on_transient_and_on_missing_key_but_not_on_real_errors():
    box = {"rows": [R("groq:a")]}
    router, calls = make_router(
        box,
        {
            "groq:a": RateLimitError("429 slow down"),
            "google:b": ProviderConfigError("GOOGLE_API_KEY is not set"),
            "nvidia:c": OK,
        },
        fallbacks=["google:b", "nvidia:c"],
    )
    meta = CallMeta(agent="qa")
    await router.generate([], QAReport, tier="fast", meta=meta)
    assert meta.used_model == "nvidia:c" and calls == ["groq:a", "nvidia:c"]

    router2, _ = make_router({"rows": [R("groq:a")]}, {"groq:a": RateLimitError("x")}, fallbacks=[])
    with pytest.raises(TransientAgentError):  # all candidates failed => retryable
        await router2.generate([], QAReport, tier="fast")

    router3, c3 = make_router(
        {"rows": [R("groq:a")]},
        {"groq:a": ValueError("bad request"), "nvidia:c": OK},
        fallbacks=["nvidia:c"],
    )
    with pytest.raises(ValueError):  # non-transient: don't mask bugs with failover
        await router3.generate([], QAReport, tier="fast")
    assert c3 == ["groq:a"]
