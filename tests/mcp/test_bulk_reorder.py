"""S-133 — Bulk and reorder over MCP (L10's other half), `docs/E2E.md` lines 1455-1467. Real
stdio session, real F2 fixture, no mocks.

The reorder argument shape (`update {"id":..., "after_id":...}`) is `move_between`'s own contract
read straight through, not invented here: `core/moves.py::move_between(conn, *, owner, id,
after_id, before_id)` is the only primitive that can request a midpoint insert, and it trusts
adjacency rather than reverifying it (`core/tree.py`'s own module docstring). Handing an agent a
raw `before_id` argument would let it assert an adjacency that is not real and get a silently
wrong position back — so the MCP schema exposes `after_id` alone, and `tools.py::_derive_before_id`
computes the one real `before_id` a `children_of`/board read can prove, never taking a caller's
word for it. That is the whole reason this suite has no `before_id` property anywhere."""

from __future__ import annotations

from pathlib import Path

import anyio
import psycopg

from tests.conftest import maintenance_dsn
from tests.harness import stmt
from tests.harness.report import gate
from tests.mcp.conftest import TEST_TOKEN, business_statement_count, open_mcp_stdio


def _positions(dsn: str, ids: list[str]) -> dict[str, int]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT id, position FROM goals WHERE id = ANY(%s)", (ids,)).fetchall()
        return dict(rows)


def _done_at(dsn: str, ids: list[str]) -> dict[str, object]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT id, done_at FROM goals WHERE id = ANY(%s)", (ids,)).fetchall()
        return dict(rows)


async def _call(f2_dsn: str, tmp_path: Path, name: str, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool(name, args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


# --- step 1: bulk done=true, execute-counter delta <= 2 --------------------------------------


async def _step1_body(f2_dsn: str, tmp_path: Path, maint_dsn: str, dbname: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s133-1") as (session, streams):
        stmt.reset(maint_dsn, dbname)
        result = await session.call_tool(
            "update", {"ids": ["SYNCOL01", "SYNCOL02", "SYNCOL03"], "done": True}
        )
        streams.assert_hygiene(token=TEST_TOKEN)
    log = stmt.read(maint_dsn, dbname)
    return result, business_statement_count(log), log


def test_s133_step1_bulk_done_true_updates_three_with_a_bounded_statement_count(
    f2_dsn: str, tmp_path: Path
) -> None:
    maint_dsn = maintenance_dsn()
    if not stmt.available(maint_dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        (dbname,) = conn.execute("SELECT current_database()").fetchone()

    result, delta, log = anyio.run(_step1_body, f2_dsn, tmp_path, maint_dsn, dbname)

    assert result.is_error is False, result.content[0].text if result.content else result
    sc = result.structured_content
    assert sc["updated"] == 3, sc
    ids = {g["id"] for g in sc["goals"]}
    assert ids == {"SYNCOL01", "SYNCOL02", "SYNCOL03"}, ids
    for g in sc["goals"]:
        assert g["done_at"] is not None, f"{g['id']} must carry a set done_at: {g}"

    assert delta <= 2, f"expected <= 2 business statements (one UPDATE, one readback), got {delta}: {log}"


# --- step 2: reorder SYNORD03 between SYNORD01 (1024) and SYNORD02 (2048) --------------------


def test_s133_step2_reorder_lands_at_the_exact_midpoint_and_touches_nothing_else(
    f2_dsn: str, tmp_path: Path
) -> None:
    order_ids = ["SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04"]
    before = _positions(f2_dsn, order_ids)
    assert before == {"SYNORD01": 1024, "SYNORD02": 2048, "SYNORD03": 3072, "SYNORD04": 4096}, before

    result = anyio.run(_call, f2_dsn, tmp_path, "update", {"id": "SYNORD03", "after_id": "SYNORD01"}, "s133-2")

    assert result.is_error is False, result.content[0].text if result.content else result
    assert result.structured_content["goal"]["position"] == 1536, result.structured_content["goal"]

    after = _positions(f2_dsn, order_ids)
    assert after["SYNORD03"] == 1536, after
    assert after["SYNORD01"] == before["SYNORD01"], "SYNORD01 must not move"
    assert after["SYNORD02"] == before["SYNORD02"], "SYNORD02 must not move"
    assert after["SYNORD04"] == before["SYNORD04"], "SYNORD04 must not move"


# --- step 3: cross-owner bulk is all-or-nothing -----------------------------------------------


async def _step3_body(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s133-3") as (session, streams):
        step1 = await session.call_tool("update", {"ids": ["SYNCOL01", "SYNCOL02", "SYNCOL03"], "done": True})
        step3 = await session.call_tool("update", {"ids": ["SYNCOL01", "SYNOTH01"], "done": False})
        streams.assert_hygiene(token=TEST_TOKEN)
    return step1, step3


def test_s133_step3_cross_owner_bulk_is_refused_and_writes_nothing(f2_dsn: str, tmp_path: Path) -> None:
    step1, step3 = anyio.run(_step3_body, f2_dsn, tmp_path)
    assert step1.is_error is False, step1.content[0].text if step1.content else step1

    assert step3.is_error is True, "a bulk update spanning two owners must be refused"

    # All-or-nothing across the *whole* call, checked at the row: SYNCOL01 (t1, valid) must still
    # read exactly as step 1 left it (done=true), never flipped back toward step 3's own
    # done=false — a partial write here would be the actual bug S-44/S-133 exist to catch.
    done_after = _done_at(f2_dsn, ["SYNCOL01", "SYNOTH01"])
    assert done_after["SYNCOL01"] is not None, "step 3 must not have undone step 1's write to SYNCOL01"
    assert done_after["SYNOTH01"] is None, "SYNOTH01 (owner t2) must be untouched by a t1-scoped call"


# --- step 4: ids at 501 is a schema rejection --------------------------------------------------


def test_s133_step4_501_ids_is_a_schema_rejection(f2_dsn: str, tmp_path: Path) -> None:
    ids = [f"id{n:06d}" for n in range(501)]
    result = anyio.run(_call, f2_dsn, tmp_path, "update", {"ids": ids, "done": True}, "s133-4")
    assert result.is_error is True
    text = result.content[0].text
    assert len(text) < 200, text
    assert "500" in text, f"the refusal should name the limit: {text!r}"


# --- id and ids together ------------------------------------------------------------------------


def test_s133_id_and_ids_together_is_mutually_exclusive(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(
        _call, f2_dsn, tmp_path, "update", {"id": "SYNCOL01", "ids": ["SYNCOL02"], "done": True}, "s133-5"
    )
    assert result.is_error is True
    text = result.content[0].text
    assert len(text) < 200, text


# --- the first-position form, same tool, same group ---------------------------------------------
#
# `docs/PENDING_DOC_FIXES.md` rows 109 and 116(c). `after_id` cannot name index 0 — there is no row
# before the head to sit after — so an agent could reorder into every position except the one a
# person most often wants. `position: "first"` is that encoding, and it takes no id at all, so it
# adds no new way for a caller to assert an adjacency it cannot prove: the server reads the group.
# Named `test_update_reorder_*` rather than `test_s133_*` — S-133's own steps do not include it.


def test_update_reorder_position_first_over_mcp(f2_dsn: str, tmp_path: Path) -> None:
    """SYNORD03 to the head of G2. The head is at 1024, so the free slot is 1024 // 2 = 512, and
    the other three rows do not move — the same arithmetic `tests/http/test_update.py` asserts
    over the other transport, on the same fixture group, for the same reason step 2 above does."""
    order_ids = ["SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04"]
    before = _positions(f2_dsn, order_ids)

    result = anyio.run(
        _call, f2_dsn, tmp_path, "update", {"id": "SYNORD03", "position": "first"}, "reorder-first"
    )
    assert result.is_error is False, result.content[0].text if result.content else result

    after = _positions(f2_dsn, order_ids)
    assert after["SYNORD03"] == 512, after
    for other in ("SYNORD01", "SYNORD02", "SYNORD04"):
        assert after[other] == before[other], f"{other} must not move: {after}"
    assert min(after, key=after.get) == "SYNORD03"


def test_update_reorder_position_and_after_id_together_is_refused_over_mcp(
    f2_dsn: str, tmp_path: Path
) -> None:
    """Two spellings of one gesture. Refused rather than silently preferring one, and nothing is
    written — checked at the row, not inferred from the error."""
    order_ids = ["SYNORD01", "SYNORD02", "SYNORD03", "SYNORD04"]
    before = _positions(f2_dsn, order_ids)

    result = anyio.run(
        _call,
        f2_dsn,
        tmp_path,
        "update",
        {"id": "SYNORD03", "position": "first", "after_id": "SYNORD01"},
        "reorder-both",
    )
    assert result.is_error is True
    assert _positions(f2_dsn, order_ids) == before, "a refused call must write nothing"
