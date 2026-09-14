"""D231/D233 over real HTTP (`GET /api/board?value=...`, `PATCH color`), docs/E2E.md §4.

The core law is proved in tests/core/test_value_alignment.py; this file is the transport-layer
proof: the filter rides the same single statement (X-Query-Count stays 1), the exemptions and
refusals survive serialization, and the derived colour is what the wire actually carries.

F2 facts used (E2E.md §2): SYNLIF01 is the only parentless life root; its chain runs
SYNLIF01 > SYNDEC01 > SYNYRR01 > SYNQ1R01 > SYNQ2R01 > SYNDAY01 > SYNSUB0x. SYNCOL01-07 are
parentless DAY roots with stored colours — under D231 those stored colours are never read.
"""

from __future__ import annotations

import httpx

DATE = "2026-08-08"
BLUE = "#278dea"


def _columns(body: dict) -> dict:
    return {col["vertical"]: {card["id"]: card for card in col["goals"]} for col in body["columns"]}


def test_value_filter_is_one_call_and_narrows_dated_columns_only(client: httpx.Client) -> None:
    resp = client.get("/api/board", params={"date": DATE, "value": "SYNLIF01"})
    assert resp.status_code == 200
    assert resp.headers.get("x-query-count") == "1"

    body = resp.json()
    cols = _columns(body)
    assert "SYNDAY01" in cols["day"], "SYNLIF01's own day descendant must survive its filter"
    assert "SYNCOL01" not in cols["day"], "an unvalued day root must not survive the filter"
    # D240: the life column narrows like every other column — only the selected value's own
    # life rows remain. The menu's source is the top-level `values` list, which never narrows
    # (F2 has one value, so the multi-value narrowing proof lives in the core suite; the wire
    # proof here is that `values` exists on BOTH responses and matches the unfiltered roots).
    assert set(cols["life"]) == {"SYNLIF01"}
    unfiltered_body = client.get("/api/board", params={"date": DATE}).json()
    unfiltered = _columns(unfiltered_body)
    assert set(cols[None]) == set(unfiltered[None])
    assert [v["id"] for v in body["values"]] == ["SYNLIF01"]
    assert [v["id"] for v in unfiltered_body["values"]] == ["SYNLIF01"]


def test_value_filter_refusals(client: httpx.Client) -> None:
    assert client.get("/api/board", params={"date": DATE, "value": "NOPE9999"}).status_code == 404
    # A real goal that is not a parentless life root is refused identically.
    assert client.get("/api/board", params={"date": DATE, "value": "SYNDAY01"}).status_code == 404
    assert client.get("/api/board", params={"date": DATE, "value": "SYNCOL01"}).status_code == 404
    assert client.get("/api/board", params={"date": DATE, "value": ""}).status_code == 422


def test_colour_is_derived_on_the_wire(client: httpx.Client) -> None:
    patched = client.patch("/api/goals/SYNLIF01", json={"color": BLUE})
    assert patched.status_code == 200, patched.text

    cols = _columns(client.get("/api/board", params={"date": DATE}).json())
    assert cols["day"]["SYNDAY01"]["color"] == BLUE, "descendant must wear the value's colour"
    assert cols["day"]["SYNCOL01"]["color"] is None, "stored colour on a day root is never read"

    detail = client.get("/api/goals/SYNSUB01")
    assert detail.status_code == 200
    assert detail.json()["color"] == BLUE


def test_colour_patch_lives_on_value_roots_only(client: httpx.Client) -> None:
    for target in ("SYNDAY01", "SYNCOL01"):
        resp = client.patch(f"/api/goals/{target}", json={"color": BLUE})
        assert resp.status_code == 422, f"{target}: {resp.status_code} {resp.text}"
        assert resp.json()["detail"][0]["loc"] == ["body", "color"]


def test_short_label_rides_the_board_and_is_root_gated(client: httpx.Client) -> None:
    # D239: the one-word menu label lands in the board's sparse `short_labels` map.
    patched = client.patch("/api/goals/SYNLIF01", json={"short_label": "Money"})
    assert patched.status_code == 200, patched.text
    body = client.get("/api/board", params={"date": DATE}).json()
    assert body["short_labels"] == {"SYNLIF01": "Money"}

    # Null clears — the key leaves the map.
    assert client.patch("/api/goals/SYNLIF01", json={"short_label": None}).status_code == 200
    assert client.get("/api/board", params={"date": DATE}).json()["short_labels"] == {}

    # Refused off value roots and refused for anything that is not one word, same 422 envelope
    # as the colour law's own refusal.
    refused = client.patch("/api/goals/SYNDAY01", json={"short_label": "Nope"})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "short_label"]
    two_words = client.patch("/api/goals/SYNLIF01", json={"short_label": "two words"})
    assert two_words.status_code == 422
    assert two_words.json()["detail"][0]["loc"] == ["body", "short_label"]
