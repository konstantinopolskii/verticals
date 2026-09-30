"""S-33 (`GET /api/board`) and S-134 (`GET /api/search`), docs/E2E.md §4.

Both routes are single-call, single-statement reads (IR-07 for board; `core/search.py` unchanged
underneath for search) — the assertions here are the HTTP-layer proof that holds regardless of
what `tests/core/test_board.py` / `tests/core/test_search.py` already proved about the SQL: a
caller who never opens a database connection still gets `X-Query-Count`, still gets the envelope
size guarantee, still gets the same refusals.
"""

from __future__ import annotations

from datetime import date

import httpx

from verticals.core.vertical import VERTICALS, period_key

# §2's F2 census at 2026-08-08, keyed by the JSON `columns[].vertical` value (`None` for Maybe —
# `core/board.py::_column_for`'s own encoding, not a guess). 8 columns, matches the
# already-established fixture invariant guarded independently in tests/core/test_board.py.
#
# R10 revised (KK ruling 2026-08-16): ghosts exist only where the requested period IS the real
# current one, so the day and week ghosts of the frozen board date are gone for good. KK, 26 Sep
# 2026: a carried plan lands in the first eligible window (Day to three years), so how many ghosts
# each live column holds follows the wall clock and cannot be pinned here. What is pinned: the
# native census (no ghost, any date), no ghost in a column that is not live for the requested
# period, and every column's total being its native cards plus its ghosts.
REQUESTED = date(2026, 8, 8)
_LIVE = {
    h.key for h in VERTICALS
    if h.bounds_fn(REQUESTED) is not None and period_key(h.key, REQUESTED) == period_key(h.key, date.today())
}

EXPECTED_NATIVE_CENSUS = {
    None: 5, "day": 10, "week": 4, "month": 6,
    "quarter": 2, "year": 1, "decade": 0, "life": 1,
}

# tests/core/test_search.py's own pinned constant (module-level `CYCL`), repeated here rather
# than imported across the suite boundary — same reasoning as this suite's own f2_dsn duplication.
CYCL = ["SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"]
RETRO_BY_ANCHOR_DATE_DESC = ["SYNRET01", "SYNRET02"]  # test_s27a's own established order
RECENT_BY_UPDATED_AT_DESC = [
    "SYNEDG07", "SYNEDG06", "SYNEDG05", "SYNEDG04", "SYNEDG03",
    "SYNEDG02", "SYNEDG01", "SYNDON02", "SYNDON01", "SYNOLD02",
]


def test_s33_board_is_one_call(client: httpx.Client) -> None:
    resp = client.get("/api/board", params={"date": REQUESTED.isoformat()})
    assert resp.status_code == 200
    assert resp.headers.get("x-query-count") == "1"
    assert len(resp.content) < 128 * 1024, f"{len(resp.content)} bytes, over the 128 KB envelope budget"

    body = resp.json()
    columns = body["columns"]
    assert len(columns) == 8
    census = {col["vertical"]: len(col["goals"]) for col in columns}
    native_census = {
        col["vertical"]: sum(card["ghost"] is False for card in col["goals"])
        for col in columns
    }
    ghost_census = {
        col["vertical"]: sum(card["ghost"] is True for card in col["goals"])
        for col in columns
    }
    assert native_census == EXPECTED_NATIVE_CENSUS
    assert [key for key, n in ghost_census.items() if n and key not in _LIVE] == []
    assert census == {key: native_census[key] + ghost_census[key] for key in native_census}

    for col in columns:
        for card in col["goals"]:
            assert "body" not in card, f"card {card['id']} carries body in a list response"
            assert "body_chars" in card
            assert isinstance(card["body_chars"], int)
            assert isinstance(card["ghost"], bool)


def test_s134_search_matches_core_over_http(client: httpx.Client, server_factory) -> None:
    # 1: ?q=cycl
    r1 = client.get("/api/search", params={"q": "cycl"})
    assert r1.status_code == 200
    assert r1.headers.get("x-query-count") == "1"
    assert [g["id"] for g in r1.json()["goals"]] == CYCL

    # 2: ?q=CYCL — case-insensitive, same order
    r2 = client.get("/api/search", params={"q": "CYCL"})
    assert r2.status_code == 200
    assert r2.headers.get("x-query-count") == "1"
    assert [g["id"] for g in r2.json()["goals"]] == CYCL

    # 3: ?tag=retro — anchor_date DESC, off-board rows the board response never carries
    r3 = client.get("/api/search", params={"tag": "retro"})
    assert r3.status_code == 200
    assert r3.headers.get("x-query-count") == "1"
    assert [g["id"] for g in r3.json()["goals"]] == RETRO_BY_ANCHOR_DATE_DESC

    # 4: ?q=cycl&vertical=month — all of G4 is month 2026-08, same four
    r4 = client.get("/api/search", params={"q": "cycl", "vertical": "month"})
    assert r4.status_code == 200
    assert r4.headers.get("x-query-count") == "1"
    assert [g["id"] for g in r4.json()["goals"]] == CYCL

    # 5: ?q=cy — under the 3-char floor
    r5 = client.get("/api/search", params={"q": "cy"})
    assert r5.status_code == 422
    detail = r5.json()["detail"]
    assert detail and detail[0]["loc"] and detail[0]["msg"]

    # P-01 recent-default mode: explicitly bounded, newest update first.
    r6 = client.get("/api/search", params={"limit": 10})
    assert r6.status_code == 200
    assert r6.headers.get("x-query-count") == "1"
    assert [g["id"] for g in r6.json()["goals"]] == RECENT_BY_UPDATED_AT_DESC

    # limit=201 — over MAX_LIMIT.
    r7 = client.get("/api/search", params={"q": "cycl", "limit": 201})
    assert r7.status_code == 422

    # Cross-owner isolation: the identical query against a server configured for owner t2 (same
    # F2 database, `server_factory`'s whole reason to exist — see tests/http/conftest.py) returns
    # 200 with zero rows, never 403. `core.search.search`'s own owner-scoping, over the wire.
    with server_factory(owner="t2") as t2_server:
        t2_client = httpx.Client(
            base_url=t2_server.base_url,
            headers={"Authorization": f"Bearer {t2_server.token}"},
            timeout=10.0,
        )
        try:
            r8 = t2_client.get("/api/search", params={"q": "cycl"})
            assert r8.status_code == 200
            assert r8.json()["goals"] == []
        finally:
            t2_client.close()
