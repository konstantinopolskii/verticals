"""R6 HTTP park route over a real server and database."""

from __future__ import annotations

import httpx


def test_post_park_round_trip_and_double_park_error(client: httpx.Client) -> None:
    response = client.post("/api/goals/SYNORD01/park")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertical"] is None
    assert body["period_key"] is None
    assert body["parked_from_vertical"] == "week"
    assert body["anchor_date"] == "2026-08-05"

    refused = client.post("/api/goals/SYNORD01/park")
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "id"]


def test_park_refuses_life_value(client: httpx.Client) -> None:
    response = client.post("/api/goals/SYNLIF01/park")
    assert response.status_code == 422
    assert "life value" in response.json()["detail"][0]["msg"]


def test_park_unknown_and_foreign_ids_are_byte_identical(client: httpx.Client) -> None:
    unknown = client.post("/api/goals/SYNNOPE1/park")
    foreign = client.post("/api/goals/SYNOTH01/park")
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.content == foreign.content
