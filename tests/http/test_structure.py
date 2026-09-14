"""S-38 (`PUT /schedule`), S-39 (`PUT /parent` refuses a cycle) and S-40 (`DELETE` and cascade),
docs/E2E.md §4. Each test gets its own fresh F2 clone (`server`/`client`'s own fixture chain,
function-scoped) so absolute row counts (49, then 45) are safe to assert without any other test's
writes leaking in.
"""

from __future__ import annotations

import psycopg
import httpx


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return count


def test_s38_put_schedule_recomputes_the_key(client: httpx.Client) -> None:
    resp = client.put(
        "/api/goals/SYNMAY01/schedule", json={"vertical": "week", "anchor_date": "2026-08-08"}
    )
    assert resp.status_code == 200
    assert resp.json()["period_key"] == "2026-W32"
    assert resp.json()["descendants_clamped"] == 0

    board = client.get("/api/board", params={"date": "2026-08-08"}).json()
    by_vertical = {col["vertical"]: len(col["goals"]) for col in board["columns"]}
    assert by_vertical[None] == 4  # left Maybe
    # R10 revised (KK ruling 2026-08-16): the requested week 2026-W32 is not the wall-clock
    # current week, so F2's four former week ghosts no longer render — natives only.
    assert by_vertical["week"] == 5  # F2's 4 native + this native row
    week = next(col for col in board["columns"] if col["vertical"] == "week")
    assert sum(goal["ghost"] is False for goal in week["goals"]) == 5
    assert sum(goal["ghost"] is True for goal in week["goals"]) == 0

    clear = client.put(
        "/api/goals/SYNMAY01/schedule", json={"vertical": None, "anchor_date": None}
    )
    assert clear.status_code == 200
    assert clear.json()["period_key"] is None
    assert clear.json()["descendants_clamped"] == 0

    board_after = client.get("/api/board", params={"date": "2026-08-08"}).json()
    by_vertical_after = {col["vertical"]: len(col["goals"]) for col in board_after["columns"]}
    assert by_vertical_after[None] == 5  # back in Maybe
    assert by_vertical_after["week"] == 4
    week_after = next(col for col in board_after["columns"] if col["vertical"] == "week")
    assert sum(goal["ghost"] is False for goal in week_after["goals"]) == 4
    assert sum(goal["ghost"] is True for goal in week_after["goals"]) == 0


def test_put_schedule_reports_descendants_clamped(client: httpx.Client) -> None:
    parent = client.post(
        "/api/goals",
        json={"title": "HTTP cascade parent", "vertical": "week", "anchor_date": "2026-08-08"},
    ).json()
    child = client.post(
        "/api/goals",
        json={
            "title": "HTTP cascade child",
            "parent_id": parent["id"],
            "vertical": "week",
            "anchor_date": "2026-08-08",
        },
    ).json()

    response = client.put(
        f"/api/goals/{parent['id']}/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["descendants_clamped"] == 1
    moved_child = client.get(f"/api/goals/{child['id']}").json()
    assert (moved_child["vertical"], moved_child["period_key"]) == ("day", "2026-08-08")


def test_s39_put_parent_refuses_a_cycle_with_409(client: httpx.Client, server) -> None:
    resp = client.put("/api/goals/SYNLIF01/parent", json={"parent_id": "SYNSUB01"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "cycle"
    assert body["detail"]["reason"] == "target_is_descendant"
    assert "Traceback" not in resp.text
    assert "traceback" not in resp.text.lower()

    # The server log. S-39 asks for "one structured line, `level=warning`, not an exception", and
    # this used to be asserted only as "no traceback surfaces" because the mapped-status branch of
    # `_vertical_error_handler` called no logger at all (queue row 43) — a true assertion, but a
    # strictly weaker one that a silent server also satisfies. Both halves are now real: the
    # branch logs, and `app.py::_configure_logging` gives `verticals.*` a format that actually
    # prints the level, so `level=warning` is read off the stream rather than inferred from the
    # fact that nothing lower would have been emitted.
    #
    # Exactly one line, not "at least one": S-39 says *one*, and a handler attached twice, or a
    # logger left propagating to a root that also has one, would duplicate every record — the
    # cheapest possible detector for a logging misconfiguration nobody would otherwise notice.
    log_text = server.log_path.read_text()
    assert "Traceback" not in log_text
    refusals = [ln for ln in log_text.splitlines() if "refused CycleRefused" in ln]
    assert len(refusals) == 1, f"expected exactly one refusal line, got {len(refusals)}: {refusals}"
    line = refusals[0]
    assert "level=WARNING" in line, line
    assert "logger=verticals.api" in line, line
    assert "status=409" in line and "code=cycle" in line, line
    assert "path=/api/goals/SYNLIF01/parent" in line, line
    assert "target_is_descendant" in line, line
    assert "Traceback" not in line, line
    # The log is allowed to say more than the wire does, never the reverse: `CycleRefused`'s
    # detail carries the ids for server-side legibility, and those are exactly what a person
    # debugging this needs. Assert they are present here and absent from the response body's
    # `reason`, so the two surfaces cannot silently converge.
    assert "SYNLIF01" in line and "SYNSUB01" in line, line
    assert server.token not in log_text, "the bearer token must never reach the log (S-113)"

    still_up = client.get("/api/board", params={"date": "2026-08-08"})
    assert still_up.status_code == 200


def test_s40_delete_without_cascade_names_the_count(client: httpx.Client, server) -> None:
    before = _row_count(server.dsn)
    assert before == 49

    resp = client.delete("/api/goals/SYNDAY01")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "has_children"
    assert body["detail"]["children"] == 3
    assert body["detail"]["descendants"] == 3
    assert _row_count(server.dsn) == 49

    cascade = client.delete("/api/goals/SYNDAY01", params={"cascade": "true"})
    assert cascade.status_code == 204
    assert cascade.content == b""
    assert _row_count(server.dsn) == 45
