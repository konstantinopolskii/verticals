"""S-48 (board), S-49 (goal breadcrumb), S-50 (outline byte-exact), S-51 (search) — `docs/E2E.md`
lines 1277-1327. Real stdio session, real F2 fixture, no mocks."""

from __future__ import annotations

import functools
import json
from datetime import date
from pathlib import Path

import anyio
import psycopg

from verticals.core import goals, moves

from tests.conftest import maintenance_dsn
from tests.harness import stmt
from tests.harness.report import gate
from tests.mcp.conftest import TEST_TOKEN, business_statement_count, open_mcp_stdio

BOARD_VERTICAL_KEYS = {"maybe", "day", "week", "month", "quarter", "year", "decade", "life"}

EXPECTED_OUTLINE_SYNQ2R01 = (
    "# Q4 follow-through   ·quarter 2026-Q3· [SYNQ2R01]\n"
    "\n"
    "- [ ] Draft the outline   ·day 2026-08-08· [SYNDAY01]\n"
    "  - [ ] Collect the sources [SYNSUB01]\n"
    "  - [ ] Name the argument [SYNSUB02]\n"
    "  - [ ] Cut the first pass [SYNSUB03]\n"
)


def _require_stmt_counter(dsn: str) -> None:
    if not stmt.available(dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


# --- S-48 ------------------------------------------------------------------------------------


async def _s48_body(f2_dsn: str, tmp_path: Path, maint_dsn: str, dbname: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s48") as (session, streams):
        stmt.reset(maint_dsn, dbname)
        result = await session.call_tool("board", {"date": "2026-08-08"})
        streams.assert_hygiene(token=TEST_TOKEN)
    # Raw stmt.count() sums BEGIN/COMMIT too (pool.connection() wraps every call in an explicit
    # transaction) — business_statement_count() filters those out so this delta means what
    # E2E.md's "execute counter" means everywhere else: real statements only. See
    # docs/PENDING_DOC_FIXES.md row 53.
    log = stmt.read(maint_dsn, dbname)
    delta = business_statement_count(log)
    return result, delta, log


def test_s48_board_in_one_call(f2_dsn: str, db_name: str, tmp_path: Path) -> None:
    maint_dsn = maintenance_dsn()
    _require_stmt_counter(maint_dsn)

    result, delta, log = anyio.run(_s48_body, f2_dsn, tmp_path, maint_dsn, db_name)

    assert result.is_error is False
    sc = result.structured_content
    assert sc is not None, "board must return structured content, not text alone"
    columns = sc["columns"]
    keys = {c["vertical"] or "maybe" for c in columns}
    assert keys == BOARD_VERTICAL_KEYS, f"column vertical set mismatch: {keys}"

    day_column = next(c for c in columns if c["vertical"] == "day")
    day_ids = {g["id"] for g in day_column["goals"]}
    assert "SYNDAY01" in day_ids, f"SYNDAY01 (2026-08-08, day) missing from the day column: {day_ids}"

    payload_bytes = len(json.dumps(sc).encode("utf-8"))
    assert payload_bytes < 128 * 1024, f"board payload is {payload_bytes} bytes, over the 128KB budget"

    assert delta == 1, f"expected exactly 1 business statement for one board() call, got {delta}: {log}"


# --- S-49 ------------------------------------------------------------------------------------


async def _goal(f2_dsn: str, tmp_path: Path, goal_id: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s49") as (session, streams):
        result = await session.call_tool("goal", {"id": goal_id})
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


def test_s49_goal_returns_the_breadcrumb(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_goal, f2_dsn, tmp_path, "SYNSUB01")
    assert result.is_error is False
    ancestors = result.structured_content["ancestors"]
    assert len(ancestors) == 6, f"expected 6 ancestors root-to-parent, got {len(ancestors)}: {ancestors}"
    ids = [a["id"] for a in ancestors]
    assert ids == ["SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01", "SYNDAY01"], ids


def test_r9_goal_tool_carries_descendant_ideas(f2_dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        value = goals.create(
            conn, owner="t1", title="SYN MCP value", vertical="life", anchor_date=date(2026, 8, 8)
        ).goal
        principle = goals.create(
            conn, owner="t1", title="SYN MCP principle", parent_id=value.id,
            vertical="life", anchor_date=date(2026, 8, 8),
        ).goal
        idea = goals.create(
            conn, owner="t1", title="SYN MCP idea", parent_id=principle.id,
            vertical="month", anchor_date=date(2026, 8, 8),
        ).goal
        moves.park(conn, owner="t1", id=idea.id)

    result = anyio.run(_goal, f2_dsn, tmp_path, value.id)
    assert result.is_error is False
    assert [row["id"] for row in result.structured_content["ideas"]] == [idea.id]


# --- S-50 ------------------------------------------------------------------------------------


async def _outline(f2_dsn: str, tmp_path: Path, goal_id: str, *, depth: int | None = None, label: str = "s50"):
    args: dict[str, object] = {"id": goal_id}
    if depth is not None:
        args["depth"] = depth
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool("outline", args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


def test_s50_outline_is_byte_exact_markdown(f2_dsn: str, tmp_path: Path) -> None:
    fn = functools.partial(_outline, f2_dsn, tmp_path, "SYNQ2R01", label="s50a")
    result = anyio.run(fn)
    assert result.is_error is False
    text = result.content[0].text
    assert text == EXPECTED_OUTLINE_SYNQ2R01, f"outline text mismatch:\n--- got ---\n{text!r}\n--- want ---\n{EXPECTED_OUTLINE_SYNQ2R01!r}"


def test_s50_outline_renders_a_body_under_its_heading(f2_dsn: str, tmp_path: Path) -> None:
    fn = functools.partial(_outline, f2_dsn, tmp_path, "SYNRET01", label="s50b")
    result = anyio.run(fn)
    assert result.is_error is False
    text = result.content[0].text
    assert "What happened." in text, f"SYNRET01's 300-char body did not render under the heading: {text!r}"


def test_s50_outline_renders_a_child_body_under_its_node(f2_dsn: str, tmp_path: Path) -> None:
    fn = functools.partial(_outline, f2_dsn, tmp_path, "SYNSCH04", label="s50c")
    result = anyio.run(fn)
    assert result.is_error is False
    text = result.content[0].text
    assert "motorcycle parts bin" in text, f"SYNSCH04's body did not render under its node: {text!r}"


def test_s50_outline_depth_1_stops_after_the_first_level(f2_dsn: str, tmp_path: Path) -> None:
    fn = functools.partial(_outline, f2_dsn, tmp_path, "SYNQ2R01", depth=1, label="s50d")
    result = anyio.run(fn)
    assert result.is_error is False
    text = result.content[0].text
    assert "SYNDAY01" in text, text
    assert "SYNSUB01" not in text, f"depth=1 must not descend to SYNSUB01: {text!r}"


# --- S-51 ------------------------------------------------------------------------------------


async def _search(f2_dsn: str, tmp_path: Path, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool("search", args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


def test_s51_search_by_query_over_mcp(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_search, f2_dsn, tmp_path, {"q": "cycl"}, "s51a")
    assert result.is_error is False
    goals = result.structured_content["goals"]
    ids = {g["id"] for g in goals}
    assert ids == {"SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"}, ids
    assert isinstance(result.structured_content, dict), "search must return structured content, not a prose blob"


def test_s51_search_by_tag_over_mcp(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_search, f2_dsn, tmp_path, {"tag": "retro"}, "s51b")
    assert result.is_error is False
    ids = {g["id"] for g in result.structured_content["goals"]}
    assert ids == {"SYNRET01", "SYNRET02"}, ids


def test_s51_search_query_and_vertical_combined_over_mcp(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_search, f2_dsn, tmp_path, {"q": "cycl", "vertical": "day"}, "s51c")
    assert result.is_error is False
    assert result.structured_content["goals"] == []
