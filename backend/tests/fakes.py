from types import SimpleNamespace

from app.demo.demo_embedder import DemoEmbedder as FakeEmbedder  # noqa: E402,F401


class FakeChat:
    """Stands in for a LangChain chat model: .with_structured_output(...).ainvoke(...)."""

    def __init__(self, ref, payload=None, error=None, calls=None):
        self.ref, self.payload, self.error, self.calls = (
            ref,
            payload,
            error,
            calls if calls is not None else [],
        )

    def with_structured_output(self, schema, **kw):
        return self

    async def ainvoke(self, messages):
        self.calls.append(str(self.ref))
        if self.error:
            raise self.error
        return {
            "raw": SimpleNamespace(tool_calls=[{"args": self.payload}], content=""),
            "parsed": None,
        }


class RateLimitError(Exception):  # name matches the transient heuristic
    pass
