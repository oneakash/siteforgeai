import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Literal, Mapping, Sequence

import psycopg
from pydantic import BaseModel

from app.agents.errors import TransientAgentError
from app.agents.llm import CallMeta, Tier
from app.config import (
    DATABASE_URL,
    DEFAULT_CHAT_REFS,
    DEFAULT_EMBEDDING_REF,
    LLM_FALLBACKS,
    LLM_TIMEOUT_S,
)

logger = logging.getLogger(__name__)


class ProviderConfigError(Exception):
    pass


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    @classmethod
    def parse(cls, text: str) -> "ModelRef":
        provider, sep, model = text.strip().partition(":")
        if not sep or not model:
            raise ProviderConfigError(
                f"model ref must look like 'provider:model_id', got '{text}'"
            )
        return cls(provider.lower(), model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ProviderSpec:
    env_key: str
    base_url: str | None = None
    temperature: float = 0.4
    top_p: float | None = None
    max_tokens: int | None = None
    extra_body: Mapping[str, Any] | None = None
    chat: bool = True
    embeddings: bool = False


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec("OPENAI_API_KEY", embeddings=True),
    "nvidia": ProviderSpec(
        "NVIDIA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
        temperature=1.0,
        top_p=0.95,
        max_tokens=16384,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    ),
    "groq": ProviderSpec("GROQ_API_KEY"),
    "google": ProviderSpec("GOOGLE_API_KEY", embeddings=True),
}


def _spec(ref: ModelRef) -> ProviderSpec:
    spec = PROVIDERS.get(ref.provider)
    if not spec:
        raise ProviderConfigError(
            f"unknown provider '{ref.provider}' (known: {sorted(PROVIDERS)})"
        )
    return spec


def provider_ready(ref: ModelRef) -> bool:
    return bool(os.environ.get(_spec(ref).env_key))


def build_chat_model(ref: ModelRef, timeout: float = LLM_TIMEOUT_S):
    spec = _spec(ref)
    key = os.environ.get(spec.env_key)
    if not key:
        raise ProviderConfigError(f"{spec.env_key} is not set (needed for '{ref}')")

    if ref.provider in ("openai", "nvidia"):
        from langchain_openai import ChatOpenAI

        kw: dict[str, Any] = dict(
            model=ref.model,
            api_key=key,
            temperature=spec.temperature,
            timeout=timeout,
            max_retries=0,
        )
        if spec.base_url:
            kw["base_url"] = spec.base_url
        if spec.top_p is not None:
            kw["top_p"] = spec.top_p
        if spec.max_tokens is not None:
            kw["max_tokens"] = spec.max_tokens
        if spec.extra_body is not None:
            kw["extra_body"] = dict(spec.extra_body)
        return ChatOpenAI(**kw)

    if ref.provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=ref.model,
            api_key=key,
            temperature=spec.temperature,
            timeout=timeout,
            max_retries=0,
        )

    if ref.provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=ref.model,
            google_api_key=key,
            temperature=spec.temperature,
            timeout=timeout,
            max_retries=0,
        )

    raise ProviderConfigError(f"provider '{ref.provider}' has no chat adapter")


_TRANSIENT_NAMES = (
    "Timeout",
    "RateLimit",
    "APIConnection",
    "InternalServer",
    "ServiceUnavailable",
    "ResourceExhausted",
    "DeadlineExceeded",
    "TooManyRequests",
    "BadGateway",
)


def is_transient(e: Exception) -> bool:
    if any(k in type(e).__name__ for k in _TRANSIENT_NAMES):
        return True
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    return code in (408, 429, 500, 502, 503, 504)


@dataclass(frozen=True)
class OverrideRow:
    project_id: str | None
    agent: str | None
    tier: str | None
    purpose: str
    model_ref: str


def pick_override(
    rows: Iterable[OverrideRow],
    *,
    project_id: str | None,
    agent: str | None,
    tier: str | None,
    purpose: Literal["chat", "embedding"],
) -> str | None:
    best: tuple[int, str] | None = None
    for r in rows:
        if r.purpose != purpose:
            continue
        if r.project_id is not None and r.project_id != project_id:
            continue
        if r.agent is not None and r.agent != agent:
            continue
        if r.tier is not None and r.tier != tier:
            continue
        score = (
            (100 if r.project_id else 0)
            + (20 if r.agent else 0)
            + (10 if r.tier else 0)
        )
        if best is None or score > best[0]:
            best = (score, r.model_ref)
    return best[1] if best else None


_OVERRIDE_CACHE_TTL_S = 2.0
_override_cache: dict[str | None, tuple[float, list[OverrideRow]]] = {}


async def fetch_overrides_pg(project_id: str | None) -> list[OverrideRow]:
    now = time.monotonic()
    cached = _override_cache.get(project_id)
    if cached and (now - cached[0]) < _OVERRIDE_CACHE_TTL_S:
        return cached[1]

    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, autocommit=True
    ) as conn:
        cur = await conn.execute(
            "SELECT project_id::text, agent, tier, purpose, model_ref FROM model_overrides "
            "WHERE project_id IS NULL OR project_id::text = %s",
            (project_id,),
        )
        rows = [OverrideRow(*row) for row in await cur.fetchall()]

    _override_cache[project_id] = (now, rows)
    return rows


class ModelRouter:
    def __init__(
        self,
        fetch_overrides: Callable[
            [str | None], Awaitable[Sequence[OverrideRow]]
        ] = fetch_overrides_pg,
        fallbacks: Sequence[str] | None = None,
        chat_factory: Callable[[ModelRef], Any] = build_chat_model,
        defaults: Mapping[str, str] | None = None,
    ):
        self._fetch = fetch_overrides
        self._fallbacks = list(LLM_FALLBACKS if fallbacks is None else fallbacks)
        self._factory = chat_factory
        self._defaults = dict(DEFAULT_CHAT_REFS if defaults is None else defaults)
        self._runnables: dict[tuple[str, str, int], Any] = {}

    async def chain_for(
        self, *, agent: str | None, tier: Tier, project_id: Any
    ) -> list[ModelRef]:
        pid = str(project_id) if project_id else None
        rows = await self._fetch(pid)
        override_ref = pick_override(
            rows, project_id=pid, agent=agent, tier=tier, purpose="chat"
        )
        default_ref = self._defaults[tier]

        candidates = (
            [override_ref, default_ref, *self._fallbacks]
            if override_ref
            else [default_ref, *self._fallbacks]
        )

        refs: list[ModelRef] = []
        for text in candidates:
            if not text:
                continue
            try:
                ref = ModelRef.parse(text)
            except ProviderConfigError as e:
                logger.warning("Skipping invalid model ref '%s': %s", text, e)
                continue
            if ref not in refs:
                refs.append(ref)

        if not refs:
            raise ProviderConfigError(f"No valid model refs resolved for tier '{tier}'")
        return refs

    def _runnable(self, ref: ModelRef, schema: type[BaseModel]):
        spec = _spec(ref)
        key_hash = hash(os.environ.get(spec.env_key, ""))
        cache_key = (str(ref), schema.__name__, key_hash)

        if cache_key not in self._runnables:
            self._runnables[cache_key] = self._factory(ref).with_structured_output(
                schema, method="function_calling", include_raw=True
            )
        return self._runnables[cache_key]

    async def generate(self, messages, schema, *, tier: Tier, meta: CallMeta | None = None):
        chain = await self.chain_for(
            agent=meta.agent if meta else None,
            tier=tier,
            project_id=meta.project_id if meta else None,
        )
        last: Exception | None = None
        for ref in chain:
            try:
                res = await self._runnable(ref, schema).ainvoke(messages)
            except ProviderConfigError as e:
                last = e
                continue
            except Exception as e:
                if is_transient(e):
                    last = TransientAgentError(f"{ref}: {type(e).__name__}: {e}")
                    continue
                raise

            if meta:
                meta.used_model = str(ref)

            raw = res["raw"]
            if getattr(raw, "tool_calls", None):
                return raw.tool_calls[0]["args"]
            if res.get("parsed") is not None:
                parsed = res["parsed"]
                return parsed.model_dump() if isinstance(parsed, BaseModel) else parsed

            content = raw.content if isinstance(raw.content, str) else str(raw.content)
            if "</think>" in content:
                content = content.split("</think>", 1)[-1].strip()
            return content

        assert last is not None
        raise last