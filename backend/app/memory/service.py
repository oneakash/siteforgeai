"""MemoryService: the lifecycle of long-term memory.

  remember()  dedupe -> supersede -> insert (one transaction). Embedding failure NEVER blocks a write:
              the text is the source of truth; the vector is a rebuildable index.
  recall()    pinned facts (by topic, always) + semantic top-k (current embedding model only).
  to_prompt() context compression: dedupe, truncate, budget.
  summarize_decisions()  LLM compaction of the decision log.
"""
import hashlib
import re
from typing import Any, Mapping, Sequence
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.memory.extract import architecture_facts, brand_facts, research_facts
from app.memory.profiles import profile_for
from app.memory.store import _vec
from app.memory.types import FactSpec, Memory, RememberResult, Scope

DUP_THRESHOLD = 0.92   # cosine similarity above which two log entries count as the same memory
MIN_SIM = 0.15         # below this a semantic hit is noise


def normalize_text(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def content_hash(t: str) -> str:
    return hashlib.sha256(normalize_text(t).encode()).hexdigest()[:32]


_COLS = "id, scope, kind, topic_key, content, version, metadata, is_active"


def _row(r, sim: float | None = None) -> Memory:
    return Memory(id=r[0], scope=r[1], kind=r[2], topic_key=r[3], content=r[4], version=r[5], metadata=r[6],
                  similarity=sim, is_active=r[7])


class MemoryService:
    def __init__(self, embedders, *, dup_threshold: float = DUP_THRESHOLD, min_sim: float = MIN_SIM):
        self.embedders, self.dup_threshold, self.min_sim = embedders, dup_threshold, min_sim

    # ------------------------------------------------------------------ embedding (degrades, never raises)
    async def _embed_doc(self, project_id, text: str):
        try:
            e = await self.embedders.get(project_id)
            [v] = await e.embed_documents([text])
            return v, e.ref
        except Exception:  # noqa: BLE001  missing key / provider down: store text without a vector
            return None, None

    async def _embed_query(self, project_id, text: str):
        try:
            e = await self.embedders.get(project_id)
            return await e.embed_query(text), e.ref
        except Exception:  # noqa: BLE001
            return None, None

    # ------------------------------------------------------------------ write
    async def remember(self, conn: AsyncConnection, *, scope: Scope, user_id: str, kind: str, content: str,
                       project_id: UUID | str | None = None, session_id: str | None = None,
                       topic_key: str | None = None, metadata: Mapping[str, Any] | None = None,
                       source: Mapping[str, Any] | None = None) -> RememberResult:
        pid = str(project_id) if project_id else None
        if (scope == "user") != (pid is None) or (scope == "session") != (session_id is not None):
            raise ValueError(f"invalid ids for scope '{scope}' (project_id={pid}, session_id={session_id})")
        h = content_hash(content)
        vec, ref = await self._embed_doc(pid, content)      # network call OUTSIDE the transaction
        owner = (scope, user_id, pid, session_id)
        owner_sql = ("scope=%s AND user_id=%s AND project_id IS NOT DISTINCT FROM %s::uuid "
                     "AND session_id IS NOT DISTINCT FROM %s::text")
        async with conn.transaction():
            active = None
            if topic_key:   # FACT: at most one active version per topic
                active = await (await conn.execute(
                    f"SELECT id, version, content_hash, embedding_model FROM memories WHERE is_active AND topic_key=%s AND {owner_sql} FOR UPDATE",
                    (topic_key, *owner))).fetchone()
                if active and active[2] == h:
                    return RememberResult("duplicate", active[0], active[1], active[3] is not None)
            else:           # LOG entry: suppress exact and near duplicates
                dup = await (await conn.execute(
                    f"SELECT id, version, embedding_model FROM memories WHERE is_active AND topic_key IS NULL AND kind=%s "
                    f"AND content_hash=%s AND {owner_sql} LIMIT 1", (kind, h, *owner))).fetchone()
                if not dup and vec is not None:
                    dup = await (await conn.execute(
                        f"SELECT id, version, embedding_model FROM memories WHERE is_active AND topic_key IS NULL AND kind=%s "
                        f"AND embedding_model=%s AND {owner_sql} AND 1 - (embedding <=> %s::vector) >= %s "
                        f"ORDER BY embedding <=> %s::vector LIMIT 1",
                        (kind, ref, *owner, _vec(vec), self.dup_threshold, _vec(vec)))).fetchone()
                if dup:
                    return RememberResult("duplicate", dup[0], dup[1], dup[2] is not None)
            if active:
                await conn.execute("UPDATE memories SET is_active=false, superseded_at=now() WHERE id=%s", (active[0],))
            version = active[1] + 1 if active else 1
            new_id = (await (await conn.execute(
                "INSERT INTO memories (user_id, project_id, scope, session_id, kind, topic_key, content, content_hash, "
                "metadata, source, embedding, embedding_model, version) "
                "VALUES (%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s) RETURNING id",
                (user_id, pid, scope, session_id, kind, topic_key, content, h, Jsonb(dict(metadata or {})),
                 Jsonb(dict(source or {})), _vec(vec) if vec is not None else None, ref, version))).fetchone())[0]
            if active:
                await conn.execute("UPDATE memories SET superseded_by=%s WHERE id=%s", (new_id, active[0]))
        return RememberResult("superseded" if active else "created", new_id, version, vec is not None)

    async def _write_facts(self, conn, facts: Sequence[FactSpec], *, user_id, project_id, source) -> list[RememberResult]:
        return [await self.remember(conn, scope="project", user_id=user_id, project_id=project_id, kind=f.kind,
                                    topic_key=f.topic_key, content=f.content, metadata=f.metadata, source=source)
                for f in facts]

    async def write_research(self, conn, *, user_id, project_id, niche=None, audience=None, competitors=None, seo=None):
        return await self._write_facts(conn, research_facts(niche, audience, competitors, seo), user_id=user_id,
                                       project_id=project_id, source={"stage": "research"})

    async def write_brand(self, conn, *, user_id, project_id, guideline, artifact_id=None):
        """ONLY call with an APPROVED guideline: drafts are not memory."""
        return await self._write_facts(conn, brand_facts(guideline, str(artifact_id) if artifact_id else None),
                                       user_id=user_id, project_id=project_id,
                                       source={"stage": "brand_approved", "revision": guideline.revision})

    async def write_architecture(self, conn, *, user_id, project_id, wireframe, artifact_id=None):
        return await self._write_facts(conn, architecture_facts(wireframe, str(artifact_id) if artifact_id else None),
                                       user_id=user_id, project_id=project_id, source={"stage": "wireframe"})

    async def log_decision(self, conn, *, user_id, project_id, text: str, metadata=None) -> RememberResult:
        return await self.remember(conn, scope="project", user_id=user_id, project_id=project_id, kind="decision",
                                   content=text, metadata=metadata)

    async def add_preference(self, conn, *, user_id: str, text: str, topic_key: str | None = None) -> RememberResult:
        """User-level memory: follows the user into ALL their future projects."""
        return await self.remember(conn, scope="user", user_id=user_id, kind="preference", content=text, topic_key=topic_key)

    # ------------------------------------------------------------------ read
    async def recall(self, conn: AsyncConnection, *, project_id, user_id: str, query: str,
                     kinds: Sequence[str] | None = None, k: int = 5, session_id: str | None = None,
                     pinned_topics: Sequence[str] = (), min_sim: float | None = None,
                     metadata_filter: Mapping[str, Any] | None = None) -> list[Memory]:
        pid = str(project_id)
        scope_sql = ("((scope='project' AND project_id=%(p)s::uuid) OR (scope='user' AND user_id=%(u)s) "
                     "OR (scope='session' AND project_id=%(p)s::uuid AND session_id=%(s)s::text))")
        params: dict[str, Any] = {"p": pid, "u": user_id, "s": session_id}
        out: list[Memory] = []
        if pinned_topics:   # metadata lookup: works even with NO embeddings at all
            rows = await (await conn.execute(
                f"SELECT {_COLS} FROM memories WHERE is_active AND {scope_sql} AND topic_key LIKE ANY(%(pins)s::text[]) "
                "ORDER BY topic_key", {**params, "pins": list(pinned_topics)})).fetchall()
            out = [_row(r) for r in rows]
        qv, ref = await self._embed_query(pid, query)
        if qv is not None:
            rows = await (await conn.execute(
                f"SELECT {_COLS}, 1 - (embedding <=> %(q)s::vector) AS sim FROM memories "
                f"WHERE is_active AND embedding_model=%(m)s AND {scope_sql} "
                "AND (%(kinds)s::text[] IS NULL OR kind = ANY(%(kinds)s::text[])) "
                "AND (%(meta)s::jsonb IS NULL OR metadata @> %(meta)s::jsonb) "
                "AND 1 - (embedding <=> %(q)s::vector) >= %(ms)s ORDER BY embedding <=> %(q)s::vector LIMIT %(k)s",
                {**params, "q": _vec(qv), "m": ref, "kinds": list(kinds) if kinds else None,
                 "meta": Jsonb(dict(metadata_filter)) if metadata_filter else None,
                 "ms": self.min_sim if min_sim is None else min_sim, "k": k})).fetchall()
            seen = {m.id for m in out}
            out += [_row(r[:8], float(r[8])) for r in rows if r[0] not in seen]
        return out

    async def for_agent(self, conn, *, project_id, user_id: str, agent: str, query: str,
                        session_id: str | None = None) -> list[Memory]:
        prof = profile_for(agent)
        return await self.recall(conn, project_id=project_id, user_id=user_id, query=query, kinds=prof.kinds,
                                 k=prof.k, session_id=session_id, pinned_topics=prof.pinned)

    @staticmethod
    def to_prompt(memories: Sequence[Memory], budget_chars: int = 4000, per_item: int = 500) -> list[tuple[str, str]]:
        """Context compression: one entry per topic, trimmed, within a budget (pinned first, then by similarity)."""
        ordered = sorted(memories, key=lambda m: (m.similarity is not None, -(m.similarity or 0.0)))
        out, used, seen = [], 0, set()
        for m in ordered:
            key = m.topic_key or str(m.id)
            if key in seen:
                continue
            text = m.content if len(m.content) <= per_item else m.content[: per_item - 1] + "…"
            if used + len(text) > budget_chars:
                break
            seen.add(key)
            out.append((m.topic_key or m.kind, text))
            used += len(text)
        return out

    async def list_memories(self, conn, *, project_id, include_inactive: bool = False, kind: str | None = None) -> list[Memory]:
        rows = await (await conn.execute(
            f"SELECT {_COLS} FROM memories WHERE project_id=%s::uuid AND (%s OR is_active) AND (%s::text IS NULL OR kind=%s) "
            "ORDER BY COALESCE(topic_key,''), version, created_at", (str(project_id), include_inactive, kind, kind))).fetchall()
        return [_row(r) for r in rows]

    # ------------------------------------------------------------------ summarization
    async def summarize_decisions(self, conn, llm, *, project_id, user_id: str, min_items: int = 8,
                                  keep_last: int = 3) -> RememberResult | None:
        """When the decision log grows past `min_items`, compress all but the newest `keep_last`
        into ONE summary fact (topic 'decisions.summary') and archive the originals."""
        from app.agents.registry import AGENTS
        from app.agents.runner import run_agent

        rows = await (await conn.execute(
            "SELECT id, content FROM memories WHERE is_active AND scope='project' AND project_id=%s::uuid AND kind='decision' "
            "ORDER BY created_at, id", (str(project_id),))).fetchall()
        if len(rows) <= min_items:
            return None
        old = rows[:-keep_last]
        res = await run_agent(AGENTS["memory.summarize"], llm=llm, project_id=str(project_id),
                              inputs={"decisions_oldest_first": [r[1] for r in old]},
                              instruction="Summarize these past decisions.")
        s = res.output
        text = "Summary of earlier decisions: " + s.summary + " Key decisions: " + "; ".join(s.key_decisions)
        r = await self.remember(conn, scope="project", user_id=user_id, project_id=project_id, kind="decision_summary",
                                topic_key="decisions.summary", content=text, metadata={"covers": [str(x[0]) for x in old]})
        await conn.execute("UPDATE memories SET is_active=false, superseded_at=now(), superseded_by=%s WHERE id = ANY(%s::uuid[])",
                           (r.id, [x[0] for x in old]))
        return r
