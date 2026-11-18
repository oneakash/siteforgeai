"""Scenario 10 with REAL process death (os._exit(137) inside an LLM call)."""
import json
import os
import subprocess
import sys
import tempfile

import psycopg
import pytest

from app.config import DATABASE_URL
from tests.graph_env import q

pytestmark = pytest.mark.asyncio


def run(*args, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "scripts.recovery_demo", *args], capture_output=True, text=True, env=env,
                          cwd=os.path.dirname(os.path.dirname(__file__)))


async def test_crash_mid_research_then_restart_does_not_repeat_finished_work():
    d = tempfile.mkdtemp()
    log, marker = f"{d}/calls.log", f"{d}/marker"
    env = {"DEMO_LLM_CALL_LOG": log}
    # process #1: dies while the Audience agent is mid-call (3 siblings finished or in-flight)
    r1 = run("start", "--crash-on", "AudienceReport", "--marker", marker, env_extra=env)
    assert r1.returncode == 137, r1.stderr[-800:]
    pid = (await q("SELECT id FROM projects ORDER BY created_at DESC LIMIT 1"))[0][0]

    # process #2: restart + continue from the persisted checkpoint
    r2 = run("continue", "--project", str(pid), "--marker", marker, env_extra=env)
    assert r2.returncode == 0, r2.stderr[-800:]
    res = json.loads(r2.stdout.split("RESULT ", 1)[1])
    assert res["waiting"] == "brand_review"

    calls = open(log).read().split()
    assert calls.count("PlanDraft") == 1                              # plan NOT re-generated
    for name in ("NicheReport", "CompetitorReport", "SEOStrategy"):
        assert calls.count(name) == 1, f"{name} was repeated after recovery: {calls}"
    assert calls.count("AudienceReport") == 2                         # crashed call + the resumed one
    assert calls.count("BrandGuideline") == 1

    # and the human checkpoint still works after the crash
    r3 = run("approve", "--project", str(pid), "--marker", marker, env_extra=env)
    assert r3.returncode == 0 and json.loads(r3.stdout.split("RESULT ", 1)[1])["phase"] == "wireframe_complete"
    arts = await q("SELECT kind, count(*) FROM artifacts WHERE project_id=%s GROUP BY kind", (pid,))
    assert all(n == 1 for _, n in arts), arts                         # no duplicate artifacts anywhere
    # memory survived the crash cleanly: no topic has two active rows, and no log entry is duplicated
    assert not await q("SELECT topic_key FROM memories WHERE project_id=%s AND is_active AND topic_key IS NOT NULL "
                       "GROUP BY 1 HAVING count(*) > 1", (pid,))
    assert not await q("SELECT content_hash FROM memories WHERE project_id=%s AND is_active GROUP BY 1 HAVING count(*) > 1", (pid,))
    assert (await q("SELECT count(*) FROM memories WHERE project_id=%s AND topic_key='brand.palette'", (pid,)))[0][0] == 1
