"""Step 1 checkpoint: send `worker.ping` through Redis and wait for the worker's answer."""

import sys

from app.worker.tasks import ping

try:
    answer = ping.delay().get(timeout=10)
except Exception as e:  # no worker, no Redis, wrong REDIS_URL...
    print(f"FAIL: {type(e).__name__}: {e}")
    print("Is Redis up (make infra) and is a worker running (make worker)?")
    sys.exit(1)

assert answer == "pong", f"unexpected answer: {answer!r}"
print("PASS: API -> Redis -> worker -> Redis round trip works")
