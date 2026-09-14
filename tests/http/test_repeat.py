"""Repeat rules through a real HTTP server and real Postgres; no ASGI test transport."""

from __future__ import annotations

from datetime import date

import httpx
import psycopg


def _create(client: httpx.Client) -> dict:
    response = client.post(
        "/api/goals",
        json={"title": "HTTP recurrence", "vertical": "day", "anchor_date": "2026-08-10"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_http_repeat_configures_and_completion_materializes(client: httpx.Client, server) -> None:
    created = _create(client)
    rule = {"frequency": "weekly", "interval": 1, "weekdays": [1, 4]}
    configured = client.patch(f"/api/goals/{created['id']}", json={"repeat": rule})
    assert configured.status_code == 200, configured.text
    assert configured.json()["repeat"] == rule

    completed = client.patch(f"/api/goals/{created['id']}", json={"done": True})
    assert completed.status_code == 200, completed.text
    with psycopg.connect(server.dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT repeat_index, anchor_date FROM goals"
            " WHERE owner = 't1' AND repeat_series_id = %s ORDER BY repeat_index",
            (created["id"],),
        ).fetchall()
    assert rows == [(0, date(2026, 8, 10)), (1, date(2026, 8, 13))]


def test_http_repeat_boundary_names_invalid_fields(client: httpx.Client) -> None:
    created = _create(client)
    invalid = client.patch(
        f"/api/goals/{created['id']}",
        json={"repeat": {"frequency": "weekly", "interval": 3, "weekdays": [1]}},
    )
    assert invalid.status_code == 422
    assert "repeat.weekdays" in invalid.text
    detail = client.get(f"/api/goals/{created['id']}").json()
    assert detail["repeat"] is None

    extra = client.patch(
        f"/api/goals/{created['id']}",
        json={"repeat": {"frequency": "daily", "occurrences": 4}},
    )
    assert extra.status_code == 422


def test_http_repeat_is_refused_for_bulk_patch(client: httpx.Client) -> None:
    first = _create(client)
    second = _create(client)
    response = client.patch(
        "/api/goals",
        json={
            "ids": [first["id"], second["id"]],
            "patch": {"repeat": {"frequency": "daily"}},
        },
    )
    assert response.status_code == 422
    assert "repeat" in response.text
