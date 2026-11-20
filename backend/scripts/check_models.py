"""Smoke-test the models in .env with REAL calls (the test suite uses fakes).

    docker compose exec backend python -m scripts.check_models

For each chat model (defaults + fallbacks) it makes one structured-output call (tool calling,
exactly how the agents call it); for the embedding model it checks the vector size.
Exit code 1 if anything FAILs. Providers without an API key are SKIPped.
"""

import asyncio
import math
import sys
import time

from app.config import DEFAULT_CHAT_REFS, DEFAULT_EMBEDDING_REF, EMBEDDING_DIM, LLM_FALLBACKS
from app.contracts import QAReport
from app.llm.embeddings import build_embedder
from app.llm.router import (
    PROVIDERS,
    ModelRef,
    ProviderConfigError,
    build_chat_model,
    provider_ready,
)

PROMPT = [
    {
        "role": "system",
        "content": "Call the tool with a QA report for a website that has no problems.",
    },
    {
        "role": "user",
        "content": "Everything checks out: navigation, brand colors and SEO fields are all fine.",
    },
]


async def check_chat(text: str, factory=build_chat_model, timeout: float = 90.0) -> tuple[str, str]:
    try:
        ref = ModelRef.parse(text)
        ready = provider_ready(ref)
    except ProviderConfigError as e:
        return "FAIL", str(e)
    if not ready:
        return "SKIP", f"{PROVIDERS[ref.provider].env_key} is not set"
    t0 = time.time()
    try:
        runnable = factory(ref).with_structured_output(
            QAReport, method="function_calling", include_raw=True
        )
        res = await asyncio.wait_for(runnable.ainvoke(PROMPT), timeout)
    except Exception as e:  # noqa: BLE001
        return "FAIL", f"{type(e).__name__}: {str(e)[:300]}"
    dt = f"{time.time() - t0:.1f}s"
    calls = getattr(res["raw"], "tool_calls", None)
    if not calls:
        return (
            "FAIL",
            f"({dt}) model did not call the tool: it may not support tool calling, which the agents require",
        )
    try:
        QAReport.model_validate(calls[0]["args"])
    except Exception as e:  # noqa: BLE001
        return (
            "WARN",
            f"({dt}) tool calling works but the output failed validation (agents auto-correct this): {str(e)[:160]}",
        )
    return "OK", f"structured output valid ({dt})"


async def check_embedding(text: str, factory=build_embedder) -> tuple[str, str]:
    try:
        ref = ModelRef.parse(text)
        if not provider_ready(ref):
            return "SKIP", f"{PROVIDERS[ref.provider].env_key} is not set"
        emb = factory(text)
        v = await emb.embed_query("a boutique travel agency in Dhaka")
    except Exception as e:  # noqa: BLE001
        return "FAIL", f"{type(e).__name__}: {str(e)[:300]}"
    norm = math.sqrt(sum(x * x for x in v))
    if len(v) != EMBEDDING_DIM or abs(norm - 1) > 1e-3:
        return "FAIL", f"got {len(v)} dims, norm {norm:.3f}"
    return "OK", f"{len(v)} dims, normalized"


async def main() -> int:
    refs: list[tuple[str, str]] = []
    for label, r in [
        ("reasoning default", DEFAULT_CHAT_REFS["reasoning"]),
        ("fast default", DEFAULT_CHAT_REFS["fast"]),
        *[(f"fallback {i + 1}", r) for i, r in enumerate(LLM_FALLBACKS)],
    ]:
        refs.append((label, r))
    results = []
    for label, r in refs:
        results.append((label, r, *await check_chat(r)))
    results.append(
        ("embedding", DEFAULT_EMBEDDING_REF, *await check_embedding(DEFAULT_EMBEDDING_REF))
    )
    for label, r, status, detail in results:
        print(f"[{status:4}] {label:18} {r}\n       {detail}")
    return 1 if any(s == "FAIL" for _, _, s, _ in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
