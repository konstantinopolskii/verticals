"""due_ack over a real stdio session (migration 011), real F2, no mocks.

Dueness in `core.due_ack.acknowledge` is measured against the REAL current date (the live
board's own clock), so the overdue fixture row used here is SYNORD01 — anchored 2026-08-05,
permanently in the past — and the "not overdue" probe creates its own goal in the real current
week rather than trusting any fixture date to stay current.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

OVERDUE_ID = "SYNORD01"  # week 2026-W32, undone — overdue on any real date after 2026-08-16


def _week_card(board_result, goal_id: str):
    for column in board_result.structured_content["columns"]:
        if column["vertical"] != "week":
            continue
        for card in column["goals"]:
            if card["id"] == goal_id:
                return card
    return None


async def _full_story(f2_dsn: str, tmp_path: Path):
    today = date.today().isoformat()
    async with open_mcp_stdio(f2_dsn, tmp_path, label="dueack") as (session, streams):
        before = await session.call_tool("board", {"date": today})

        ack = await session.call_tool(
            "due_ack", {"id": OVERDUE_ID, "verdict": "overdue", "note": "seen and accepted"}
        )
        after = await session.call_tool("board", {"date": today})
        detail = await session.call_tool("goal", {"id": OVERDUE_ID})

        # Replay with the OPPOSITE verdict: first verdict wins, no completion side effect.
        replay = await session.call_tool("due_ack", {"id": OVERDUE_ID, "verdict": "done_on_time"})
        detail_after_replay = await session.call_tool("goal", {"id": OVERDUE_ID})

        # Refusals: a goal in the real current week is not overdue; unknown id is NotFound.
        created = await session.call_tool(
            "create", {"title": "SYN current week probe", "vertical": "week", "anchor_date": today}
        )
        fresh_id = created.structured_content["goal"]["id"]
        not_overdue = await session.call_tool("due_ack", {"id": fresh_id, "verdict": "overdue"})
        unknown = await session.call_tool("due_ack", {"id": "ZZZZZZZZ", "verdict": "overdue"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return before, ack, after, detail, replay, detail_after_replay, not_overdue, unknown


def test_due_ack_verdict_removes_ghost_and_lands_in_goal_history(
    f2_dsn: str, tmp_path: Path
) -> None:
    before, ack, after, detail, replay, detail_after_replay, not_overdue, unknown = anyio.run(
        _full_story, f2_dsn, tmp_path
    )

    card = _week_card(before, OVERDUE_ID)
    assert card is not None and card["ghost"] is True, "fixture premise: SYNORD01 ghosts today"

    assert ack.is_error is False, ack.content[0].text if ack.content else ack
    stored = ack.structured_content["acknowledgement"]
    assert stored["goal_id"] == OVERDUE_ID
    assert stored["verdict"] == "overdue"
    assert stored["vertical"] == "week"
    assert stored["period_key"] == "2026-W32"
    assert stored["note"] == "seen and accepted"

    assert _week_card(after, OVERDUE_ID) is None, "acknowledged ghost must leave the board"

    assert detail.is_error is False
    history = detail.structured_content["due_history"]
    assert [row["verdict"] for row in history] == ["overdue"]
    assert detail.structured_content["goal"]["done_at"] is None, "overdue verdict must not complete"

    # First verdict wins: the conflicting replay returns the stored row and completes nothing.
    assert replay.is_error is False
    assert replay.structured_content["acknowledgement"]["verdict"] == "overdue"
    assert detail_after_replay.structured_content["goal"]["done_at"] is None
    assert len(detail_after_replay.structured_content["due_history"]) == 1

    assert not_overdue.is_error is True
    assert "not overdue" in not_overdue.content[0].text
    assert unknown.is_error is True
