"""R10 board ghost flag and HTTP Ignore field over live TCP.

R10 revised (KK ruling 2026-08-16): ghosts exist only on the wall-clock current period, so the
scenario anchors its own row RELATIVE TO RUNTIME TODAY (last year) and reads the board AT today —
the one date the ghost can appear on. A year's plan is the ladder's top (docs/design-handoff
S4.P1.007), so it stays in Year whatever day the suite runs on. The "returns next period" arc is
restated without a time machine: an ignore that expired before the current year's start no longer
suppresses, which is exactly the state a live board wakes up to after the ignored year rolls
over. F2's frozen rows play no part — a frozen anchor can never ghost again."""

from __future__ import annotations

from datetime import date, timedelta

import httpx


def _year_goals(response: httpx.Response) -> list[dict]:
    assert response.status_code == 200, response.text
    return next(
        column["goals"] for column in response.json()["columns"] if column["vertical"] == "year"
    )


def test_board_flags_ghost_and_http_update_suppresses_on_the_live_board(
    client: httpx.Client,
) -> None:
    today = date.today()
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    last_year = date(today.year - 1, 6, 15)

    created = client.post(
        "/api/goals",
        json={"title": "HTTP ghost probe", "vertical": "year",
              "anchor_date": last_year.isoformat()},
    )
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    current = _year_goals(client.get("/api/board", params={"date": today.isoformat()}))
    ghost = next(goal for goal in current if goal["id"] == gid)
    assert ghost["ghost"] is True
    assert ghost["ghost_until"] == year_end.isoformat()

    # Time travel carries no ghosts: in its own year the row is native, and a future year shows
    # nothing.
    own_year = _year_goals(client.get("/api/board", params={"date": last_year.isoformat()}))
    assert next(goal for goal in own_year if goal["id"] == gid)["ghost"] is False
    future = _year_goals(
        client.get("/api/board", params={"date": (year_end + timedelta(days=1)).isoformat()})
    )
    assert gid not in {goal["id"] for goal in future}

    ignored = client.patch(
        f"/api/goals/{gid}", json={"carryover_ignored_until": year_end.isoformat()}
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["carryover_ignored_until"] == year_end.isoformat()
    assert ignored.json()["done_at"] is None

    same_period = _year_goals(client.get("/api/board", params={"date": today.isoformat()}))
    assert gid not in {goal["id"] for goal in same_period}

    expired = client.patch(
        f"/api/goals/{gid}",
        json={"carryover_ignored_until": (year_start - timedelta(days=1)).isoformat()},
    )
    assert expired.status_code == 200, expired.text
    returned_goals = _year_goals(client.get("/api/board", params={"date": today.isoformat()}))
    returned = next(goal for goal in returned_goals if goal["id"] == gid)
    assert returned["ghost"] is True
    assert returned["ghost_until"] == year_end.isoformat()


def test_replan_writes_once_a_day_and_refuses_a_day_that_has_not_come(client: httpx.Client) -> None:
    """docs/design-handoff S4.P1.017, .029: the route runs the day's carry-over, a second call the same day changes
    nothing, and a date more than a day from the server's is not run."""
    today = date.today()
    created = client.post(
        "/api/goals",
        json={"title": "HTTP carried plan", "vertical": "day", "anchor_date": (today - timedelta(days=2)).isoformat()},
    )
    assert created.status_code == 201, created.text
    first = client.post("/api/replan", params={"date": today.isoformat()})
    assert first.status_code == 200, first.text
    task_id = first.json()["task_id"]
    task = client.get(f"/api/goals/{task_id}").json()
    assert task["title"] == "Replan carried-over plans" and task["origin"] == "app"
    assert f"(goal:{created.json()['id']})" in task["body"]
    again = client.post("/api/replan", params={"date": today.isoformat()})
    assert again.json()["task_id"] == task_id
    assert client.get(f"/api/goals/{task_id}").json()["updated_at"] == task["updated_at"]
    far = client.post("/api/replan", params={"date": (today + timedelta(days=5)).isoformat()})
    assert far.status_code == 200 and far.json() == {"task_id": None}, far.text
    after = client.post("/api/replan", params={"date": (today + timedelta(days=1)).isoformat()})
    assert after.json()["task_id"] == task_id
