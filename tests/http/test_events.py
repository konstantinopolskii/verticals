"""D237 — `GET /api/events`: a real SSE stream over a real socket, rung by a real write.

The whole feature is cross-process by construction (MCP writes, API notifies), and Postgres is
the only shared piece — so the honest E2E is: open the stream, write through the ordinary HTTP
route on a DIFFERENT connection, and watch the doorbell arrive on this one. No mocks, no
direct pg_notify calls — the migration 012 trigger is part of what is under test.
"""

from __future__ import annotations

import threading
import time

import httpx

from tests.http.conftest import TEST_TOKEN


def test_events_requires_auth(server) -> None:
    raw = httpx.Client(base_url=server.base_url, timeout=10.0)
    try:
        assert raw.get("/api/events").status_code == 401
    finally:
        raw.close()


def test_events_stream_rings_after_a_write(server) -> None:
    writer = httpx.Client(
        base_url=server.base_url,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        timeout=10.0,
    )
    reader = httpx.Client(
        base_url=server.base_url,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        # The read timeout is the test's own deadline: pings arrive every 15s, the doorbell far
        # sooner. A stream that stays silent past 30s is a real failure, reported as a timeout.
        timeout=httpx.Timeout(10.0, read=30.0),
    )
    fired = threading.Timer(
        1.0, lambda: writer.patch("/api/goals/SYNDAY01", json={"title": "SYN rung by a write"})
    )
    try:
        with reader.stream("GET", "/api/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            # The write is issued from a second thread AFTER the stream is open — issuing it
            # first would race the LISTEN registration and pass or fail on scheduling luck.
            fired.start()
            deadline = time.monotonic() + 25.0
            saw_changed = False
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    saw_changed = True
                    break
                if time.monotonic() > deadline:
                    break
            assert saw_changed, "no data frame arrived after a goals write"
    finally:
        fired.cancel()
        writer.close()
        reader.close()
