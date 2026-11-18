"""Prove a graph survives a hard process kill.

1. Process #1 runs node_a (checkpointed) then dies inside node_b (os._exit).
2. Process #2 resumes the same thread_id from Postgres.
3. We assert node_a's side effect ran exactly once and node_b completed once.
"""
import subprocess
import sys
import uuid

import psycopg

from app.config import DATABASE_URL

thread = f"probe-{uuid.uuid4()}"

with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    project_id = str(
        conn.execute(
            "INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) "
            "VALUES ('probe','Probe','probe','probe',%s) RETURNING id",
            (thread,),
        ).fetchone()[0]
    )

base = [sys.executable, "-m", "app.graph.trivial"]
common = ["--thread", thread, "--project-id", project_id]

print("== process #1: start, crash inside node_b ==")
r1 = subprocess.run(base + ["start", *common, "--crash-in-b"])
assert r1.returncode == 137, f"expected crash exit 137, got {r1.returncode}"

print("== process #2: resume from checkpoint ==")
r2 = subprocess.run(base + ["resume", *common])
assert r2.returncode == 0, "resume process failed"

with psycopg.connect(DATABASE_URL) as conn:
    rows = conn.execute(
        "SELECT action, count(*) FROM audit_log WHERE project_id=%s GROUP BY action",
        (project_id,),
    ).fetchall()
counts = dict(rows)
print("audit counts:", counts)

assert counts.get("node_a_executed") == 1, "node_a re-ran after recovery!"
assert counts.get("node_b_completed") == 1, "node_b did not complete after recovery"
print("PASS: node_a ran once; node_b completed after restart")
