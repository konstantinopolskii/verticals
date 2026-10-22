"""A step's date decides where it shows (docs/design/checklist-steps.md): the tools an agent writes with say so, and do what
they say. The owner, 21 Oct 2026: "It should be clear from the MCP ... so NOBODY will do same mistake again." Real
`tools/list` and `tools/call` over stdio against F2, no mocks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import anyio
import psycopg

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio
from verticals.core import board as core_board
from verticals.mcp.tool_schemas import STEP_DATES

TASK = "SYNORD01"  # "Order one", a Week task of F2 (2026-W32)
OWNER = "t1"


def _words(text: str | None) -> str:
    return " ".join((text or "").split())


def test_create_and_schedule_say_where_a_steps_date_puts_it(f2_dsn: str, tmp_path: Path) -> None:
    async def listed():
        async with open_mcp_stdio(f2_dsn, tmp_path, label="step-dates-list") as (session, streams):
            tools = {t.name: t for t in (await session.list_tools()).tools}
            streams.assert_hygiene(token=TEST_TOKEN)
            return tools

    tools = anyio.run(listed)
    for name in ("create", "schedule"):
        assert _words(STEP_DATES) in _words(tools[name].description), name
    create = tools["create"].input_schema
    for field in (create["properties"]["anchor_date"], create["$defs"]["child"]["properties"]["anchor_date"]):
        assert "Leave both out for a step the owner does not track on the board" in field["description"]
    schedule = tools["schedule"].input_schema["properties"]["anchor_date"]["description"]
    assert "a parentless goal goes to the Inbox, a step stays inside its parent" in schedule


def test_a_step_made_without_a_date_lives_inside_its_parent_and_keeps_it_when_its_date_goes(
    f2_dsn: str, tmp_path: Path,
) -> None:
    async def calls():
        async with open_mcp_stdio(f2_dsn, tmp_path, label="step-dates-calls") as (session, streams):
            made = await session.call_tool("create", {"title": "SYN agent checklist step", "parent_id": TASK,
                                                      "children": [{"title": "SYN sub-agent task"}]})
            step = made.structured_content["goal"]["id"]
            dated = await session.call_tool("schedule", {"id": step, "vertical": "week", "anchor_date": "2026-08-05"})
            undated = await session.call_tool("schedule", {"id": step, "vertical": None, "anchor_date": None})
            streams.assert_hygiene(token=TEST_TOKEN)
            return step, made, dated, undated

    step, made, dated, undated = anyio.run(calls)
    assert not (made.is_error or dated.is_error or undated.is_error)
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT title, parent_id, vertical::text, period_key FROM goals WHERE id = %s OR parent_id = %s ORDER BY depth",
            (step, step),
        ).fetchall()
        # Made with no date, dated, then its date taken away: the step is under its task again with no date, and its own
        # step, made with no date, never had one.
        assert rows == [("SYN agent checklist step", TASK, None, None), ("SYN sub-agent task", step, None, None)]
        assert made.structured_content["goal"]["vertical"] is None
        # The board carries the undated step among its parent's children, where the opened parent lists it from.
        kids = core_board.board(conn, owner=OWNER, date=date(2026, 8, 8)).children[TASK]
        assert step in [kid.id for kid in kids if kid.vertical is None]
