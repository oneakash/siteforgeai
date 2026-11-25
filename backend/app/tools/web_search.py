"""LangSearch web-search tool (free API: https://docs.langsearch.com/api).

Design notes
- One shared client per process: a concurrency cap + TTL cache protect the free tier
  (the 4 research agents run in parallel and often issue near-identical queries).
- Never raises into the agent loop: failures come back as a tool error string so the
  model can continue (or stop) instead of crashing the task.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

LANGSEARCH_URL = "https://api.langsearch.com/v1/web-search"
SNIPPET_CHARS = 600


def host_of(url: str) -> str:
    h = (urlparse(url if "//" in url else f"//{url}").hostname or "").lower()
    return h.removeprefix("www.")


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published: str | None = None


def _parse(body: dict[str, Any]) -> list[SearchHit]:
    # LangSearch wraps the Bing-compatible payload in {"code":..,"data":{...}}; accept both shapes.
    data = body.get("data", body)
    items = (data.get("webPages") or {}).get("value") or []
    hits: list[SearchHit] = []
    for it in items:
        url = it.get("url")
        if not url:
            continue
        text = (it.get("summary") or it.get("snippet") or "").strip()
        hits.append(
            SearchHit(
                title=(it.get("name") or url).strip(),
                url=url,
                snippet=text[:SNIPPET_CHARS],
                published=it.get("datePublished"),
            )
        )
    return hits


class LangSearchClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        max_concurrency: int = 2,
        cache_ttl_s: float = 3600.0,
        timeout_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._key = api_key
        self._sem = asyncio.Semaphore(max_concurrency)
        self._ttl = cache_ttl_s
        self._timeout = timeout_s
        self._transport = transport
        self._cache: dict[tuple, tuple[float, list[SearchHit]]] = {}

    @property
    def api_key(self) -> str | None:
        return self._key or os.environ.get("LANGSEARCH_API_KEY")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def search(
        self, query: str, *, count: int = 5, freshness: str = "noLimit"
    ) -> list[SearchHit]:
        query = " ".join(query.split())[:400]
        if not query:
            raise SearchError("empty query")
        if not self.enabled:
            raise SearchError("LANGSEARCH_API_KEY is not set")
        count = max(1, min(count, 8))
        key = (query.lower(), count, freshness)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]

        payload = {"query": query, "freshness": freshness, "summary": True, "count": count}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        async with self._sem:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(
                        timeout=self._timeout, transport=self._transport
                    ) as http:
                        r = await http.post(LANGSEARCH_URL, json=payload, headers=headers)
                    if r.status_code in (429, 500, 502, 503, 504):
                        last = SearchError(f"HTTP {r.status_code}")
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    hits = _parse(r.json())
                    self._cache[key] = (time.monotonic(), hits)
                    return hits
                except (httpx.HTTPError, ValueError) as e:
                    last = e
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise SearchError(f"search failed: {last}")


_client: LangSearchClient | None = None


def get_search_client() -> LangSearchClient:
    global _client
    if _client is None:
        _client = LangSearchClient()
    return _client


# OpenAI-format tool schema: accepted by bind_tools() for openai/nvidia/groq/google.
WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the live web. Use for facts you cannot know reliably: real competitors and "
            "their sites, current market trends, what keywords/pages rank. Do NOT use for "
            "general knowledge. Write specific queries (include location/industry)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Specific search query"},
                "freshness": {
                    "type": "string",
                    "enum": ["noLimit", "oneYear", "oneMonth", "oneWeek"],
                    "description": "Recency filter; default noLimit",
                },
            },
            "required": ["query"],
        },
    },
}