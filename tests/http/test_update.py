"""S-36 (PATCH updates only what is sent), S-37 (complete/un-complete) and S-44 (bulk PATCH),
docs/E2E.md §4.

`goal_to_card` (`api/schemas.py`) never carries `body` — only a detail response
(`GET /api/goals/{id}`) does — so every before/after comparison below that needs `body` reads
the detail endpoint, not the PATCH response itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

# SYNCOL01..07: the day column, F2's own comment (positions 2048..8192) — seven siblings, plenty
# to spend one per assertion without any sub-test disturbing another's fixture state.
SYNDAY01_ANCESTORS = ["SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01"]


def _iso_to_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_s36_patch_updates_only_what_is_sent(client: httpx.Client) -> None:
    # D231 moved colour writes to value roots only, so this scenario's one-field patch now
    # exercises SYNLIF01 (the F2 value root) — the isolation property under test is unchanged.
    before = client.get("/api/goals/SYNLIF01").json()

    resp = client.patch("/api/goals/SYNLIF01", json={"color": "#278dea"})
    assert resp.status_code == 200
    assert resp.json()["color"] == "#278dea"

    after = client.get("/api/goals/SYNLIF01").json()
    assert after["color"] == "#278dea"
    assert after["color"] != before["color"]

    for field in (
        "title", "body", "tags", "position", "vertical", "period_key", "parent_id",
        "origin", "created_at",
    ):
        assert after[field] == before[field], f"{field} changed: {before[field]!r} -> {after[field]!r}"

    assert _iso_to_dt(after["updated_at"]) > _iso_to_dt(before["updated_at"])


def test_v2_patch_toggles_foil_and_echoes_it(client: httpx.Client) -> None:
    enabled = client.patch("/api/goals/SYNCOL02", json={"foil": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["foil"] is True
    assert client.get("/api/goals/SYNCOL02").json()["foil"] is True

    disabled = client.patch("/api/goals/SYNCOL02", json={"foil": False})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["foil"] is False


def test_s37_complete_and_uncomplete(client: httpx.Client) -> None:
    ancestors_before = {
        aid: client.get(f"/api/goals/{aid}").json()["updated_at"] for aid in SYNDAY01_ANCESTORS
    }

    done_resp = client.patch("/api/goals/SYNDAY01", json={"done": True})
    assert done_resp.status_code == 200
    done_body = done_resp.json()
    assert done_body["open_descendants"] == 3
    done_at = _iso_to_dt(done_body["done_at"])
    now = datetime.now(timezone.utc)
    assert abs((now - done_at).total_seconds()) < 2, done_body["done_at"]

    undone_resp = client.patch("/api/goals/SYNDAY01", json={"done": False})
    assert undone_resp.status_code == 200
    undone_body = undone_resp.json()
    # Not 3: `core.goals.update()` only computes `open_descendants` `if done is True`
    # (`Updated`'s own docstring, and S-19's stated intent — "guard the close," a warning
    # reported at the moment of closing) — `done=False` and "done not sent at all" both collapse
    # to `None`. E2E.md's own S-37 text says "both responses carry open_descendants = 3," which
    # this run shows does not match the shipped code; flagged in this WP's result rather than
    # asserted against here.
    assert undone_body["open_descendants"] is None
    assert undone_body["done_at"] is None

    # S-18: ancestors are read-time aggregates (board's own progress JOIN), never rows this call
    # writes to — each ancestor's own `updated_at` must be byte-identical across the round trip.
    for aid, before_updated_at in ancestors_before.items():
        after_updated_at = client.get(f"/api/goals/{aid}").json()["updated_at"]
        assert after_updated_at == before_updated_at, f"{aid}'s updated_at moved"


def test_s44_bulk_patch_is_first_class(client: httpx.Client) -> None:
    # One id from a foreign owner: 404, all-or-nothing — SYNCOL04 must come back untouched.
    before_syncol04 = client.get("/api/goals/SYNCOL04").json()
    mixed = client.patch(
        "/api/goals", json={"ids": ["SYNCOL04", "SYNOTH01"], "patch": {"done": True}}
    )
    assert mixed.status_code == 404
    assert mixed.json() == {"error": "not_found"}
    after_syncol04 = client.get("/api/goals/SYNCOL04").json()
    assert after_syncol04["done_at"] is None
    assert after_syncol04["updated_at"] == before_syncol04["updated_at"]

    # A well-formed bulk call: three same-owner ids, one UPDATE, one readback.
    ok = client.patch(
        "/api/goals",
        json={"ids": ["SYNCOL01", "SYNCOL02", "SYNCOL03"], "patch": {"done": True}},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["updated"] == 3
    assert int(ok.headers["x-query-count"]) <= 2
    for g in body["goals"]:
        assert g["done_at"] is not None

    # 501 ids: refused by schemas.py's own `max_length=500` before any statement runs.
    too_many = client.patch(
        "/api/goals",
        json={"ids": [f"id{i:06d}" for i in range(501)], "patch": {"done": True}},
    )
    assert too_many.status_code == 422


# --- reorder: `after_id`, docs/PENDING_DOC_FIXES.md row 32 -----------------------------------
#
# No catalogue scenario names this exact sequence over HTTP (§4's route table and capability
# table both promise `reorder` on this route; no S-NN in docs/E2E.md ever exercises it — verified
# by reading every heading in that file, not assumed). Named `test_update_reorder_*`, not
# `test_s<NN>_*`, for exactly that reason — the harness's own naming law (tests/harness/report.py)
# and the precedent already in this suite (`test_deps_*`, `test_app_*`, `test_pool_*`,
# `test_security_*`) for a real, asserted behaviour with no catalogue id to claim.
#
# F2's G2 group (`SYNORD01..04`, owner t1, vertical week, period_key 2026-W32, positions
# 1024/2048/3072/4096) — the same fixture group S-133 (MCP) and S-127 (HTTP concurrency) both
# use, confirmed against tests/fixtures/f2_synth.sql directly rather than assumed from memory.


def test_update_reorder_after_id_moves_between_siblings(client: httpx.Client) -> None:
    """SYNORD03 after SYNORD01 lands at 1536 — the exact midpoint S-133's own MCP steps compute
    for the identical fixture group (E2E.md:1455, step 2: `after_id=SYNORD01` -> position 1536
    between 1024 and 2048). Reusing the same arithmetic over HTTP is deliberate: it cross-checks
    that both transports drive `core.moves.move_between` to the same result, not just that each
    one individually returns *a* 200.

    Gap here is a full 1024 (not exhausted), so this is the plain midpoint path — no other
    sibling's position moves. The exhausted-gap/renumber branch is a different test entirely
    (tests/http/test_concurrency.py::test_concurrency_reorder_into_exhausted_gap_forces_renumber),
    because forcing it requires manually shrinking a gap first; nothing in F2 ships pre-exhausted.
    """
    resp = client.patch("/api/goals/SYNORD03", json={"after_id": "SYNORD01"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "SYNORD03"
    assert body["position"] == 1536

    # Deliberate shape: a reorder response is `goal_to_card` alone, same as `reparent_goal` and
    # `schedule_goal` — never `open_descendants` (that key only exists on the content-update
    # branch of this same route, `updated.open_descendants`, S-37's own concern).
    assert "open_descendants" not in body

    positions = {
        gid: client.get(f"/api/goals/{gid}").json()["position"]
        for gid in ("SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04")
    }
    assert positions == {"SYNORD01": 1024, "SYNORD02": 2048, "SYNORD03": 1536, "SYNORD04": 4096}, (
        f"only SYNORD03 should have moved: {positions}"
    )
    ordered = sorted(positions, key=positions.get)
    assert ordered == ["SYNORD01", "SYNORD03", "SYNORD02", "SYNORD04"]


def test_update_reorder_cannot_combine_with_content_fields(client: httpx.Client) -> None:
    """`routes_goals.py::patch_goal`'s own refusal — mirrors `verticals/mcp/tools.py`'s `update`
    tool refusing the identical combination for the identical reason (reorder is its own path,
    never mixed with a content edit in the same call)."""
    before = client.get("/api/goals/SYNORD02").json()

    resp = client.patch("/api/goals/SYNORD02", json={"after_id": "SYNORD01", "done": True})
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"] == ["body", "after_id"]
    assert "after_id" in detail["msg"] and "done" in detail["msg"]

    after = client.get("/api/goals/SYNORD02").json()
    assert after["position"] == before["position"]
    assert after["done_at"] is None
    assert after["updated_at"] == before["updated_at"], "refused request must not touch the row"


def test_update_reorder_rejects_non_sibling_after_id(client: httpx.Client) -> None:
    """SYNCOL01 is real (F2's day column) but not a member of SYNORD02's group (week,
    2026-W32) — `_derive_before_id` must refuse it rather than silently compute a meaningless
    midpoint against a sibling list SYNCOL01 was never part of."""
    before = client.get("/api/goals/SYNORD02").json()

    resp = client.patch("/api/goals/SYNORD02", json={"after_id": "SYNCOL01"})
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"] == ["body", "after_id"]
    assert "not a sibling" in detail["msg"]

    after = client.get("/api/goals/SYNORD02").json()
    assert after["position"] == before["position"]
    assert after["updated_at"] == before["updated_at"]


def test_update_bulk_patch_refuses_after_id(client: httpx.Client) -> None:
    """`patch_goals_bulk`'s own guard, checked before any connection opens: reorder targets one
    id (`core.moves.move_between`'s own signature), not a list — matching
    `verticals/mcp/tools.py`'s `update` tool ("after_id (reorder) targets a single id, not ids")."""
    before = {
        gid: client.get(f"/api/goals/{gid}").json()["position"] for gid in ("SYNORD01", "SYNORD02")
    }

    resp = client.patch(
        "/api/goals",
        json={"ids": ["SYNORD01", "SYNORD02"], "patch": {"after_id": "SYNORD03"}},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"] == ["body", "after_id"]
    assert "single id" in detail["msg"]

    after = {
        gid: client.get(f"/api/goals/{gid}").json()["position"] for gid in ("SYNORD01", "SYNORD02")
    }
    assert after == before, "refused bulk request must not touch either row"


# --- reorder: the first-position form -------------------------------------------------------------
#
# `docs/PENDING_DOC_FIXES.md` rows 109 and 116(c): `after_id` cannot name index 0 (there is no row
# before the head to sit after), so "move this to the top" had no encoding at all and the shipped UI
# marked its up control `aria-disabled` at index 1. `position: "first"` is that encoding. Same
# fixture group as the `after_id` tests above (G2: SYNORD01..04 at 1024/2048/3072/4096), same
# naming reasoning — no catalogue id claims this behaviour.


def test_update_reorder_position_first_reaches_the_head(client: httpx.Client) -> None:
    """SYNORD03 to the top: the head sits at 1024, so the free slot below it is 1024 // 2 = 512 —
    strictly below the head and above nothing, which is what makes it free by construction. No
    other row moves; the group's order is read back to prove it, not inferred from one position."""
    resp = client.patch("/api/goals/SYNORD03", json={"position": "first"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "SYNORD03"
    assert body["position"] == 512
    assert "open_descendants" not in body

    positions = {
        gid: client.get(f"/api/goals/{gid}").json()["position"]
        for gid in ("SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04")
    }
    assert positions == {"SYNORD01": 1024, "SYNORD02": 2048, "SYNORD03": 512, "SYNORD04": 4096}, (
        f"only SYNORD03 should have moved: {positions}"
    )
    ordered = sorted(positions, key=positions.get)
    assert ordered == ["SYNORD03", "SYNORD01", "SYNORD02", "SYNORD04"]


def test_update_reorder_position_first_on_the_head_itself_is_a_no_op_order(
    client: httpx.Client,
) -> None:
    """A row already first stays first. It is not refused — "move to top" asked for a state, and
    the state holds — and the rest of the group is left exactly where it was."""
    before = {
        gid: client.get(f"/api/goals/{gid}").json()["position"]
        for gid in ("SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04")
    }
    resp = client.patch("/api/goals/SYNORD01", json={"position": "first"})
    assert resp.status_code == 200, resp.text

    after = {
        gid: client.get(f"/api/goals/{gid}").json()["position"]
        for gid in ("SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04")
    }
    assert min(after, key=after.get) == "SYNORD01"
    assert sorted(after, key=after.get) == sorted(before, key=before.get)


def test_update_reorder_position_refuses_content_fields_and_after_id(client: httpx.Client) -> None:
    """The same two refusals `after_id` already carries, and one more: the two ordering forms are
    two spellings of one gesture, so sending both is a caller that has not decided."""
    before = client.get("/api/goals/SYNORD02").json()

    both = client.patch("/api/goals/SYNORD02", json={"position": "first", "after_id": "SYNORD01"})
    assert both.status_code == 422
    assert both.json()["detail"][0]["loc"] == ["body", "after_id,position"]

    with_content = client.patch("/api/goals/SYNORD02", json={"position": "first", "done": True})
    assert with_content.status_code == 422
    detail = with_content.json()["detail"][0]
    assert detail["loc"] == ["body", "position"]
    assert "position" in detail["msg"] and "done" in detail["msg"]

    bad_value = client.patch("/api/goals/SYNORD02", json={"position": "last"})
    assert bad_value.status_code == 422, "position is an enum of one — 'last' is not a member"

    after = client.get("/api/goals/SYNORD02").json()
    assert after["position"] == before["position"]
    assert after["done_at"] is None
    assert after["updated_at"] == before["updated_at"], "refused request must not touch the row"
