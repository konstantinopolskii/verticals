"""S-34 (create with only a title), S-35 (rigid input validation, nine requests) and S-43
(idempotency over HTTP) — all `POST /api/goals`, docs/E2E.md §4.

S-35's nine rows arrive at a 422 by two different code paths that this file deliberately does
not distinguish, because the caller cannot either: rows validated inside `schemas.py`
(`_check_title`/`_check_color`/pydantic's own `extra='forbid'`/required-field check) never reach
`core/`, so FastAPI's own default `RequestValidationError` handler answers; rows `schemas.py`
does not check at all (`vertical`'s enum membership, `vertical` set without `anchor_date`) reach
`core.goals.create()`, which raises `verticals.core.errors.ValidationError`, mapped by
`api/errors.py::validation_error_response`. Both converge on the same
`{"detail": [{"loc": [...], "msg": ...}]}` list shape — confirmed by reading both code paths,
not assumed — which is what makes "every 422 body has `detail[].loc` and `detail[].msg`" one
assertion instead of two.
"""

from __future__ import annotations

import httpx
import psycopg


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return count


def test_s34_create_with_only_a_title(client: httpx.Client, server) -> None:
    resp = client.post("/api/goals", json={"title": "Idea"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["vertical"] is None
    assert body["period_key"] is None
    assert body["parent_id"] is None
    assert body["origin"] == "human"
    assert resp.headers["location"] == f"/api/goals/{body['id']}"

    board = client.get("/api/board", params={"date": "2026-08-08"}).json()
    maybe = next(col for col in board["columns"] if col["vertical"] is None)
    assert len(maybe["goals"]) == 6  # F2's 5 plus this one


# --- S-35: nine requests, one row each -------------------------------------------------------

_ROWS: list[tuple[dict, int]] = [
    ({}, 422),
    ({"title": "   "}, 422),
    ({"title": "x" * 251}, 422),
    ({"title": "a\nb"}, 422),
    ({"title": "ok", "vertical": "fortnight"}, 422),
    ({"title": "ok", "vertical": "week"}, 422),  # anchor_date required when vertical is set
    ({"title": "ok", "color": "#ff0000"}, 422),  # not in the closed set of six
    ({"title": "ok", "nonsense": 1}, 422),  # extra='forbid'
    ({"title": "ok", "body": "x" * 60000}, 201),  # under the 64 KB cap
]


def test_s35_rigid_input_validation(client: httpx.Client, server) -> None:
    before = _row_count(server.dsn)

    for i, (payload, expected_status) in enumerate(_ROWS):
        resp = client.post("/api/goals", json=payload)
        assert resp.status_code == expected_status, f"row {i} {payload!r}: got {resp.status_code}"
        if expected_status == 422:
            detail = resp.json()["detail"]
            assert isinstance(detail, list) and detail, f"row {i}: empty detail"
            assert detail[0]["loc"], f"row {i}: no loc"
            assert detail[0]["msg"], f"row {i}: no msg"

    # Row 0's own literal loc, called out by name in E2E.md's table.
    row0 = client.post("/api/goals", json={})
    assert row0.json()["detail"][0]["loc"] == ["body", "title"]

    after = _row_count(server.dsn)
    # _ROWS ran once inside the loop above, plus row 0 was repeated once more just now (its own
    # 422, contributing nothing) — only row 8 (the 201) ever wrote a row, exactly once.
    assert after - before == 1


# --- S-43: idempotency over HTTP --------------------------------------------------------------


def test_s43_idempotency_over_http(client: httpx.Client, server) -> None:
    before = _row_count(server.dsn)
    payload = {"title": "idempotent create"}
    headers = {"Idempotency-Key": "ct-http-1"}

    first = client.post("/api/goals", json=payload, headers=headers)
    assert first.status_code == 201
    first_id = first.json()["id"]
    assert "Idempotent-Replay" not in first.headers

    second = client.post("/api/goals", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    assert second.headers.get("idempotent-replay") == "true"

    after = _row_count(server.dsn)
    assert after - before == 1

    conflict = client.post(
        "/api/goals", json={"title": "different body, same key"}, headers=headers
    )
    assert conflict.status_code == 409
    # E2E.md's own prose (`{"error":"idempotency_conflict"}`) is an abbreviated subset, not the
    # literal body: `IdempotencyConflict`'s raise site (`core/idem.py`) also carries `owner` and
    # `client_token` in `.detail`, surfaced verbatim by `api/errors.py`'s generic VerticalError
    # branch — asserted on the key that matters, not by full-dict equality against the prose.
    assert conflict.json()["error"] == "idempotency_conflict"

    # The conflict wrote nothing either.
    assert _row_count(server.dsn) == after
