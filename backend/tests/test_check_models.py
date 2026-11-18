from types import SimpleNamespace

from scripts.check_models import check_chat, check_embedding
from tests.fakes import FakeChat, FakeEmbedder

GOOD = {"passed": True, "issues": [], "summary": "fine"}


class NoTools:
    def with_structured_output(self, *a, **k): return self
    async def ainvoke(self, m): return {"raw": SimpleNamespace(tool_calls=[], content="sure!")}


async def test_check_chat_ok_warn_fail_skip(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert (await check_chat("nvidia:m", lambda r: FakeChat(r, payload=GOOD)))[0] == "OK"
    assert (await check_chat("nvidia:m", lambda r: FakeChat(r, payload={"bad": 1})))[0] == "WARN"
    st, msg = await check_chat("nvidia:m", lambda r: NoTools())
    assert st == "FAIL" and "tool calling" in msg
    st, msg = await check_chat("nvidia:m", lambda r: FakeChat(r, error=RuntimeError("404 model not found")))
    assert st == "FAIL" and "404" in msg
    assert (await check_chat("groq:m"))[0] == "SKIP"                      # no key => skipped, not failed
    assert (await check_chat("not-a-ref"))[0] == "FAIL"
    assert (await check_chat("martian:m"))[0] == "FAIL"


async def test_check_embedding(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert (await check_embedding("google:gemini-embedding-2", lambda r: FakeEmbedder(r)))[0] == "OK"

    class Wrong:
        async def embed_query(self, t): return [1.0] * 3072                  # un-truncated Gemini output
    assert (await check_embedding("google:gemini-embedding-2", lambda r: Wrong()))[0] == "FAIL"
    monkeypatch.delenv("GOOGLE_API_KEY")
    assert (await check_embedding("google:gemini-embedding-2"))[0] == "SKIP"
