import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.agents import tool_loop
from app.agents.errors import AgentOutputError
from app.agents.llm import FakeLLM
from app.agents.registry import AGENTS
from app.agents.runner import run_agent
from app.tools.web_search import LangSearchClient, SearchError
from tests import sample_data as sd

COMP = AGENTS["competitor_analysis"]


def _langsearch_body(*urls):
    return {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {"name": f"Result {i}", "url": u, "snippet": "snip", "summary": f"summary {i}"}
                    for i, u in enumerate(urls)
                ]
            }
        },
    }


def make_client(handler, key="k"):
    return LangSearchClient(api_key=key, transport=httpx.MockTransport(handler), cache_ttl_s=60)


class ToolFakeLLM(FakeLLM):
    """FakeLLM + scripted tool-calling turns (the router's chat_with_tools contract)."""

    def __init__(self, script, turns):
        super().__init__(script)
        self.turns = list(turns)
        self.tool_calls_seen = []

    async def chat_with_tools(self, messages, tools, *, tier, meta=None):
        self.tool_calls_seen.append(list(messages))
        return self.turns.pop(0)


def search_turn(*queries):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {"query": q}, "id": f"c{i}"} for i, q in enumerate(queries)
        ],
    )


def competitor_payload(evidence, url):
    d = sd.competitor()
    d = json.loads(json.dumps(d))
    d["competitors"][0]["evidence"] = evidence
    d["competitors"][0]["url"] = url
    for c in d["competitors"][1:]:
        c["evidence"], c["url"] = "model_knowledge", None
    return d


@pytest.fixture(autouse=True)
def _client(monkeypatch):
    def handler(req):
        return httpx.Response(200, json=_langsearch_body("https://www.rival.com/about", "https://x.io"))

    client = make_client(handler)
    monkeypatch.setattr(tool_loop, "get_search_client", lambda: client)
    return client


async def test_research_results_reach_the_structured_step_and_grounded_url_passes():
    llm = ToolFakeLLM(
        [competitor_payload("web_search", "https://rival.com")],
        [search_turn("boutique travel agencies"), AIMessage(content="DONE")],
    )
    res = await run_agent(COMP, llm=llm, inputs={"brand_name": "Aurum"})
    assert res.attempts == 1 and res.searches == ["boutique travel agencies"]
    final_user_msg = llm.calls[0][-1]["content"]
    assert 'name="web_research"' in final_user_msg and "rival.com" in final_user_msg


async def test_ungrounded_web_search_claim_is_rejected_then_corrected():
    llm = ToolFakeLLM(
        [
            competitor_payload("web_search", "https://made-up-competitor.com"),
            competitor_payload("model_knowledge", None),
        ],
        [search_turn("q"), AIMessage(content="DONE")],
    )
    res = await run_agent(COMP, llm=llm, inputs={"brand_name": "Aurum"})
    assert res.attempts == 2 and "not in" in res.corrections[0]


async def test_no_api_key_skips_research_and_forbids_web_search_evidence(monkeypatch):
    monkeypatch.delenv("LANGSEARCH_API_KEY", raising=False)
    keyless = make_client(lambda r: httpx.Response(500), key=None)
    monkeypatch.setattr(tool_loop, "get_search_client", lambda: keyless)
    llm = ToolFakeLLM([competitor_payload("web_search", "https://rival.com")] * 3, [])
    with pytest.raises(AgentOutputError):  # claiming web evidence with no research never passes
        await run_agent(COMP, llm=llm, inputs={"brand_name": "Aurum"}, max_corrections=2)
    assert llm.tool_calls_seen == []  # tool phase never started


async def test_budget_caps_queries_and_loop_terminates(_client):
    budget = COMP.max_tool_calls
    turns = [search_turn(f"q{i}", f"q{i}b") for i in range(budget + 2)]  # model never stops
    llm = ToolFakeLLM([competitor_payload("model_knowledge", None)], turns)
    res = await run_agent(COMP, llm=llm, inputs={"brand_name": "Aurum"})
    assert len(res.searches) <= budget + 1  # a parallel batch may overshoot by < one call
    assert len(llm.tool_calls_seen) <= budget + 1


async def test_search_http_failure_degrades_gracefully(monkeypatch):
    bad = make_client(lambda r: httpx.Response(400, json={"error": "bad"}))
    monkeypatch.setattr(tool_loop, "get_search_client", lambda: bad)
    llm = ToolFakeLLM(
        [competitor_payload("model_knowledge", None)],
        [search_turn("q"), AIMessage(content="DONE")],
    )
    res = await run_agent(COMP, llm=llm, inputs={"brand_name": "Aurum"})
    assert res.attempts == 1  # task still completes


async def test_client_caches_identical_queries():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json=_langsearch_body("https://a.com"))

    c = make_client(handler)
    await c.search("Same Query")
    await c.search("same   query")
    assert len(calls) == 1


async def test_client_without_key_raises():
    with pytest.raises(SearchError):
        await make_client(lambda r: httpx.Response(200), key=None).search("x")