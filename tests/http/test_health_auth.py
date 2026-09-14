"""S-31 (boot, health, OpenAPI) and S-32 (auth checked before the database), docs/E2E.md §4.

Also covers the boot-refusal behaviour `api/app.py` implements: S-113 is WP-21's scenario to
claim (asserted against this package's code, built here, per the WP-15 card's "also on the hook
for S-112, S-113, S-114" note) — so these run under non-claiming `test_app_*` names, not
`test_s113_*`, even though they exercise exactly what S-113 describes.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys

import httpx

from tests.http.conftest import REPO_ROOT, TEST_TOKEN

# §4's route table (9 rows) plus `GET /healthz` — ten operations over seven distinct path
# strings (S-31's own count). `search`/`create`/`update`(bulk) share paths with three other
# rows, which is exactly why 9 method+path pairs collapse to 6 distinct API path strings.
#
# D250/WP-1 adds the eight `/api/docs*` operations (`routes_docs.py`) on top — documents as
# first-class residents, not yet folded into `docs/E2E.md` §4's own table (that document is a
# later WP's to update; this set has to track the shipped route surface regardless, the same way
# it already tracked the goals/board/search/tags routes before this WP existed).
EXPECTED_OPERATIONS = {
    ("GET", "/api/board"),
    ("GET", "/api/events"),
    ("GET", "/api/search"),
    ("GET", "/api/tags"),
    ("POST", "/api/goals"),
    ("GET", "/api/goals/{id}"),
    ("PATCH", "/api/goals/{id}"),
    ("PATCH", "/api/goals"),
    ("PUT", "/api/goals/{id}/schedule"),
    ("PUT", "/api/goals/{id}/parent"),
    ("POST", "/api/goals/{id}/park"),
    ("POST", "/api/goals/{id}/due_ack"),
    ("DELETE", "/api/goals/{id}"),
    ("GET", "/healthz"),
    ("POST", "/api/docs"),
    ("GET", "/api/docs"),
    ("GET", "/api/docs/{id}"),
    ("PATCH", "/api/docs/{id}"),
    ("GET", "/api/docs/{id}/history"),
    ("GET", "/api/docs/{id}/history/{revision}"),
    ("POST", "/api/docs/{id}/restore"),
    ("DELETE", "/api/docs/{id}"),
    # WP-A (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md, `verticals/api/routes_comments.py`):
    # the five comment routes.
    ("GET", "/api/goals/{id}/comments"),
    ("GET", "/api/docs/{id}/comments"),
    ("POST", "/api/comments"),
    ("POST", "/api/comments/{thread_id}/messages"),
    ("POST", "/api/comments/{thread_id}/resolve"),
}

# J7's negative space: none of these ever appear in a path string, in either direction of the
# comparison above — a scope creep into a different product would show up here first. `comment`
# left this list deliberately (WP-A): it was standing in for a reference-planner parity concept this
# project had chosen not to build, and that choice is reversed now that `/api/comments*` is a
# real, shipped part of the surface — see `tests/mcp/test_tools.py::FORBIDDEN_SUBSTRINGS`'s own
# identical reasoning for the MCP side of the same tool surface.
_FORBIDDEN_PATH_SUBSTRINGS = ("assignee", "space", "bucket", "member", "board/{id}/share")


def test_s31_boot_health_and_openapi(client: httpx.Client) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert isinstance(body["version"], int)
    assert isinstance(body["queries"], int)

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    doc = spec.json()  # "parses" — a non-JSON or malformed body raises here, not further down

    operations = {
        (method.upper(), path)
        for path, methods in doc["paths"].items()
        for method in methods
        if method.lower() in ("get", "post", "patch", "put", "delete")
    }
    assert operations == EXPECTED_OPERATIONS
    for path in doc["paths"]:
        for forbidden in _FORBIDDEN_PATH_SUBSTRINGS:
            assert forbidden not in path, f"path {path!r} must not mention {forbidden!r}"


def test_s32_auth_checked_before_database(server) -> None:
    raw = httpx.Client(base_url=server.base_url, timeout=10.0)
    try:
        q1 = raw.get("/healthz").json()["queries"]

        no_header = raw.get("/api/board", params={"date": "2026-08-08"})
        wrong_token = raw.get(
            "/api/board",
            params={"date": "2026-08-08"},
            headers={"Authorization": "Bearer wrong-value-never-authenticates"},
        )
        correct = raw.get(
            "/api/board",
            params={"date": "2026-08-08"},
            headers={"Authorization": f"Bearer {server.token}"},
        )
        assert (no_header.status_code, wrong_token.status_code, correct.status_code) == (401, 401, 200)
        for resp in (no_header, wrong_token):
            assert resp.headers.get("www-authenticate") is not None
            body = resp.json()
            assert set(body.keys()) == {"detail"}  # no schema, no version, no stack
            assert "Traceback" not in resp.text

        # Ten more repeats of just the 401 pair, inserted *before* the second probe is read —
        # "repeating the two 401s ten times leaves the delta at 2" (E2E.md): the two `/healthz`
        # bodies this scenario actually compares are q1 and this second one, and no number of
        # zero-cost 401s in between changes what it reports. A separate *third* probe taken
        # afterwards is not this assertion: every `/healthz` call costs one statement of its
        # own, so two probes with nothing but 401s between them are always exactly 1 apart, never
        # 0 — that would be measuring the probe's self-tax, not the auth path.
        for _ in range(10):
            raw.get("/api/board", params={"date": "2026-08-08"})
            raw.get(
                "/api/board",
                params={"date": "2026-08-08"},
                headers={"Authorization": "Bearer still-wrong"},
            )
        q2 = raw.get("/healthz").json()["queries"]
        # One statement for the successful board call, one for this second probe's own read —
        # the twelve 401s above (the original two plus these ten repeats) contributed zero.
        assert q2 - q1 == 2
    finally:
        raw.close()


def _boot_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL="postgresql://verticals:verticals@127.0.0.1:55432/verticals",
        VERTICALS_TOKEN=TEST_TOKEN,
        VERTICALS_BIND="127.0.0.1:18099",
    )
    env.update(overrides)
    return env


def test_app_boot_refuses_empty_token() -> None:
    """S-113 step 1's underlying behaviour: an empty `VERTICALS_TOKEN` must refuse boot before a
    socket opens. Set explicitly to `""`, not omitted — omitting it lets this repo's own real
    `.env` (`load_dotenv(override=False)`) fill in a working token, which would make this test
    pass for the wrong reason."""
    result = subprocess.run(
        [sys.executable, "-m", "verticals.api.app"],
        cwd=REPO_ROOT,
        env=_boot_env(VERTICALS_TOKEN=""),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "VERTICALS_TOKEN" in result.stderr
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        assert s.connect_ex(("127.0.0.1", 18099)) != 0, "boot-refusal path must never open a socket"


def test_app_boot_refuses_non_loopback_bind() -> None:
    """S-112's underlying behaviour: a `VERTICALS_BIND` naming any interface but 127.0.0.1 must
    refuse boot rather than publish a port."""
    env = _boot_env()
    env["VERTICALS_BIND"] = "0.0.0.0:18099"
    result = subprocess.run(
        [sys.executable, "-m", "verticals.api.app"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "VERTICALS_BIND" in result.stderr
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        assert s.connect_ex(("127.0.0.1", 18099)) != 0
