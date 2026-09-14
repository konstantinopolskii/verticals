"""S-54 (reparent cycle refusal), S-55 (delete refuses a non-empty subtree) —
`docs/E2E.md` lines 1354-1366. Real stdio session, real F2 fixture, no mocks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import anyio
import psycopg

from tests.mcp.conftest import TEST_TOKEN, full_table_digest, open_mcp_stdio


def _goal_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        return count


async def _call(f2_dsn: str, tmp_path: Path, name: str, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool(name, args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


# --- S-54 --------------------------------------------------------------------------------------


async def _s54_body(f2_dsn: str, tmp_path: Path):
    """One session, two calls in it — the second (`board`) is what proves the refusal did not
    take the server process down with it (AC-139's own words, already quoted in `tools.py`)."""
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s54") as (session, streams):
        reparent = await session.call_tool("reparent", {"id": "SYNLIF01", "parent_id": "SYNSUB01"})
        board = await session.call_tool("board", {"date": "2026-08-08"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return reparent, board


def test_s54_reparent_cycle_refusal_is_a_tool_error_not_a_crash(f2_dsn: str, tmp_path: Path) -> None:
    digest_before = full_table_digest(f2_dsn)

    reparent, board = anyio.run(_s54_body, f2_dsn, tmp_path)

    assert reparent.is_error is True
    text = reparent.content[0].text
    assert len(text) < 200, f"error text must be under 200 characters, got {len(text)}: {text!r}"
    assert "SYNLIF01" in text and "SYNSUB01" in text, f"error text must name both ids: {text!r}"

    assert board.is_error is False, "the server must still answer a call after the refusal"

    digest_after = full_table_digest(f2_dsn)
    assert digest_after == digest_before, "a refused reparent must not change a single row"


# --- S-55 --------------------------------------------------------------------------------------


def test_s55_delete_nonempty_subtree_is_refused_and_writes_nothing(f2_dsn: str, tmp_path: Path) -> None:
    before = _goal_count(f2_dsn)
    result = anyio.run(_call, f2_dsn, tmp_path, "delete", {"id": "SYNDAY01"}, "s55a")

    assert result.is_error is True
    text = result.content[0].text
    assert "children=3" in text, f"expected the literal substring 'children=3': {text!r}"

    after = _goal_count(f2_dsn)
    assert after == before, f"a refused delete must remove nothing: {before} -> {after}"


def test_s55_delete_with_cascade_true_removes_exactly_four_rows(f2_dsn: str, tmp_path: Path) -> None:
    before = _goal_count(f2_dsn)
    result = anyio.run(_call, f2_dsn, tmp_path, "delete", {"id": "SYNDAY01", "cascade": True}, "s55b")

    assert result.is_error is False, result.content[0].text if result.content else result
    assert result.structured_content["removed"] == 4, result.structured_content

    after = _goal_count(f2_dsn)
    assert before - after == 4, f"expected exactly 4 rows removed, got {before - after}"


async def _list_tools(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s55c") as (session, streams):
        result = await session.list_tools()
        streams.assert_hygiene(token=TEST_TOKEN)
        return result.tools


def test_s55_cascade_omitted_defaults_to_false_in_the_schema(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    delete_tool = next(t for t in tools if t.name == "delete")
    cascade_prop = delete_tool.input_schema["properties"]["cascade"]
    assert cascade_prop.get("default") is False, (
        f"delete's cascade must default to false (never destructive by omission), "
        f"schema says {cascade_prop!r}"
    )


# --- v2 R5/R6 -------------------------------------------------------------------------------


def test_park_tool_round_trip(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_call, f2_dsn, tmp_path, "park", {"id": "SYNORD01"}, "v2-park")
    assert result.is_error is False, result.content[0].text if result.content else result
    goal = result.structured_content["goal"]
    assert goal["vertical"] is None
    assert goal["period_key"] is None
    assert goal["parked_from_vertical"] == "week"
    assert goal["anchor_date"] == "2026-08-05"


def test_update_tool_toggles_foil_and_echoes_card_field(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(
        _call, f2_dsn, tmp_path, "update", {"id": "SYNORD01", "foil": True}, "v2-foil"
    )
    assert result.is_error is False, result.content[0].text if result.content else result
    assert result.structured_content["goal"]["foil"] is True


def test_update_tool_sets_carryover_ignore_date(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(
        _call,
        f2_dsn,
        tmp_path,
        "update",
        {"id": "SYNOLD02", "carryover_ignored_until": "2026-08-09"},
        "v2-ghost-ignore",
    )
    assert result.is_error is False, result.content[0].text if result.content else result
    assert result.structured_content["goal"]["carryover_ignored_until"] == "2026-08-09"
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT carryover_ignored_until, done_at FROM goals WHERE id = 'SYNOLD02'"
        ).fetchone() == (date(2026, 8, 9), None)
