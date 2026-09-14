"""S-128 — every row of §4's input-limits table refused, and nothing partial written.

AC-200's Method also wants the 9-deep/201-node refusals exercised over `core/` directly, not
only over HTTP — `grep -rn 'test_ac200' verticals/ tests/` finds nothing, so that core-level half
does not exist yet. Out of this file's scope (the bound itself is `core/goals.py:48-49`,
`MAX_CHILDREN_DEPTH = 8` / `MAX_NODES_PER_CREATE = 200`, already enforced correctly — a missing
test over correct code, not a missing behaviour); this file is the HTTP half only, which is what
docs/E2E.md's own S-128 steps actually describe (literal HTTP requests asserting HTTP statuses).

AC-200 also names the refusals `children_too_deep` / `children_too_many`. The shipped
`core.goals.create()` raises a plain `ValidationError(field="children", maximum=...)` for both —
no `code` anywhere in `.detail`, and `api/errors.py::validation_error_response` only ever forwards
`field`/`message`, so no such string reaches the wire either. Not asserted here for that reason;
flagged in this WP's result instead of invented.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import psycopg

from verticals.core.goals import MAX_BODY_BYTES


def _snapshot(dsn: str) -> tuple[int, str]:
    """Row count and a full-table digest in one round trip — `tests/core/test_tree.py::_digest`'s
    own query (`md5(string_agg(goals::text, '|' ORDER BY id))`), duplicated here rather than
    imported across the suite boundary, matching this suite's established convention (see
    tests/http/conftest.py's own f2_dsn docstring)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*), md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals"
        ).fetchone()
    return row[0], row[1]


def _deep_chain(levels: int) -> dict:
    """A single-child chain: the returned node is level 1, its one child is level 2, ... down to
    a leaf at `levels`. `children nest N levels` (E2E.md's own phrasing) means the deepest node
    sits at level N."""
    node: dict = {"title": f"leaf L{levels}"}
    for level in range(levels - 1, 0, -1):
        node = {"title": f"chain L{level}", "children": [node]}
    return node


def _assert_422_named(resp: httpx.Response, label: str) -> None:
    assert resp.status_code == 422, f"{label}: expected 422, got {resp.status_code}: {resp.text[:300]}"
    detail = resp.json()["detail"]
    assert isinstance(detail, list) and detail, f"{label}: empty detail"
    assert detail[0]["loc"], f"{label}: no loc"
    assert detail[0]["msg"], f"{label}: no msg"


def test_s128_every_limit_is_enforced_and_nothing_partial_is_written(
    client: httpx.Client, server
) -> None:
    rows: list[tuple[str, Callable[[], httpx.Response]]] = [
        (
            "body over 64KB",
            lambda: client.post("/api/goals", json={"title": "ok", "body": "x" * 70000}),
        ),
        (
            "1.5MB request body",
            lambda: client.post("/api/goals", json={"title": "ok", "body": "x" * 1_500_000}),
        ),
        (
            "17 tags",
            lambda: client.post(
                "/api/goals", json={"title": "ok", "tags": [f"t{i}" for i in range(17)]}
            ),
        ),
        (
            "tag over 48 chars",
            lambda: client.post("/api/goals", json={"title": "ok", "tags": ["x" * 49]}),
        ),
        (
            "tag with whitespace",
            lambda: client.post("/api/goals", json={"title": "ok", "tags": ["a b"]}),
        ),
        (
            "children nest 9 levels",
            lambda: client.post(
                "/api/goals", json={"title": "root", "children": [_deep_chain(9)]}
            ),
        ),
        (
            "201 nodes total",
            lambda: client.post(
                "/api/goals",
                json={"title": "root", "children": [{"title": f"n{i}"} for i in range(200)]},
            ),
        ),
        (
            "bulk PATCH with 501 ids",
            lambda: client.patch(
                "/api/goals",
                json={"ids": [f"id{i:06d}" for i in range(501)], "patch": {"done": True}},
            ),
        ),
        (
            "search q under the 3-char floor",
            lambda: client.get("/api/search", params={"q": "cy"}),
        ),
    ]

    for label, make_request in rows:
        before = _snapshot(server.dsn)
        resp = make_request()
        after = _snapshot(server.dsn)
        assert after == before, f"{label}: full-table digest moved — partial write"

        if label == "1.5MB request body":
            assert resp.status_code == 413, f"{label}: expected 413, got {resp.status_code}"
            assert resp.json() == {"error": "body_too_large"}, "413 must carry no body echo"
            assert "x-query-count" not in {k.lower() for k in resp.headers}, (
                "a route ran — the body was deserialised before the size check"
            )
        else:
            _assert_422_named(resp, label)

    # Field-specific spot checks E2E.md names explicitly (loc's last segment, not full equality —
    # `validation_error_response` always prefixes `loc` with "body" regardless of whether the
    # field actually came from the request body or, as with `q` here, a query parameter; a real
    # minor imprecision, flagged in this WP's result, not one any scenario asserts against).
    body_row = client.post("/api/goals", json={"title": "ok", "body": "x" * 70000})
    assert body_row.json()["detail"][0]["loc"][-1] == "body"
    tags_row = client.post("/api/goals", json={"title": "ok", "tags": ["x" * 49]})
    assert tags_row.json()["detail"][0]["loc"][-1] == "tags"
    ids_row = client.patch(
        "/api/goals", json={"ids": [f"id{i:06d}" for i in range(501)], "patch": {"done": True}}
    )
    assert ids_row.json()["detail"][0]["loc"][-1] == "ids"
    q_row = client.get("/api/search", params={"q": "cy"})
    assert q_row.json()["detail"][0]["loc"][-1] == "q"

    # --- positive control: exactly 200 nodes, 8 levels, 16 tags, a 64 KB body -------------------
    before_positive = _snapshot(server.dsn)
    chain = _deep_chain(8)  # 8 nodes, deepest at level 8 — at the boundary, not over it
    extras = [{"title": f"extra{i}"} for i in range(191)]  # 1 (root) + 8 (chain) + 191 = 200
    positive_payload = {
        "title": "positive control",
        "body": "x" * MAX_BODY_BYTES,
        "tags": [f"tag{i}" for i in range(16)],
        "children": [chain] + extras,
    }
    positive = client.post("/api/goals", json=positive_payload)
    assert positive.status_code == 201, positive.text[:500]

    after_positive = _snapshot(server.dsn)
    assert after_positive[0] - before_positive[0] == 200
