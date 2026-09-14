"""R10 board ghost flag and HTTP Ignore field over live TCP.

R10 revised (KK ruling 2026-08-16): ghosts exist only on the wall-clock current period, so the
scenario anchors its own row RELATIVE TO RUNTIME TODAY (previous ISO week) and reads the board
AT today — the one date the ghost can appear on. The "returns next period" arc is restated
without a time machine: an ignore that expired before the current week's start no longer
suppresses, which is exactly the state a live board wakes up to after the ignored week rolls
over. F2's frozen rows play no part — a frozen anchor can never ghost again."""

from __future__ import annotations

from datetime import date, timedelta

import httpx


def _week_goals(response: httpx.Response) -> list[dict]:
    assert response.status_code == 200, response.text
    return next(
        column["goals"] for column in response.json()["columns"] if column["vertical"] == "week"
    )


def test_board_flags_ghost_and_http_update_suppresses_on_the_live_board(
    client: httpx.Client,
) -> None:
    today = date.today()
    week_start = today - timedelta(days=today.isoweekday() - 1)
    week_end = week_start + timedelta(days=6)
    last_week = today - timedelta(days=7)

    created = client.post(
        "/api/goals",
        json={"title": "HTTP ghost probe", "vertical": "week",
              "anchor_date": last_week.isoformat()},
    )
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    current = _week_goals(client.get("/api/board", params={"date": today.isoformat()}))
    ghost = next(goal for goal in current if goal["id"] == gid)
    assert ghost["ghost"] is True
    assert ghost["ghost_until"] == week_end.isoformat()

    # Time travel carries no ghosts: on its own week the row is native, one week earlier it is
    # absent, and a future week shows nothing either.
    own_week = _week_goals(client.get("/api/board", params={"date": last_week.isoformat()}))
    assert next(goal for goal in own_week if goal["id"] == gid)["ghost"] is False
    future = _week_goals(
        client.get("/api/board", params={"date": (today + timedelta(days=7)).isoformat()})
    )
    assert gid not in {goal["id"] for goal in future}

    ignored = client.patch(
        f"/api/goals/{gid}", json={"carryover_ignored_until": week_end.isoformat()}
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["carryover_ignored_until"] == week_end.isoformat()
    assert ignored.json()["done_at"] is None

    same_period = _week_goals(client.get("/api/board", params={"date": today.isoformat()}))
    assert gid not in {goal["id"] for goal in same_period}

    expired = client.patch(
        f"/api/goals/{gid}",
        json={"carryover_ignored_until": (week_start - timedelta(days=1)).isoformat()},
    )
    assert expired.status_code == 200, expired.text
    returned_goals = _week_goals(client.get("/api/board", params={"date": today.isoformat()}))
    returned = next(goal for goal in returned_goals if goal["id"] == gid)
    assert returned["ghost"] is True
    assert returned["ghost_until"] == week_end.isoformat()
