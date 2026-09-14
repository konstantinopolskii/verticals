"""The MCP repeat capability through a real stdio server and real Postgres."""

from __future__ import annotations

from pathlib import Path

import anyio
import psycopg

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio


async def _exercise(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="repeat") as (session, streams):
        created = await session.call_tool(
            "create",
            {"title": "MCP recurrence", "vertical": "day", "anchor_date": "2026-08-10"},
        )
        goal_id = created.structured_content["goal"]["id"]
        configured = await session.call_tool(
            "update",
            {"id": goal_id, "repeat": {"frequency": "monthly", "month_days": [10, 20]}},
        )
        completed = await session.call_tool("update", {"id": goal_id, "done": True})
        streams.assert_hygiene(token=TEST_TOKEN)
    return goal_id, configured, completed


def test_mcp_repeat_uses_the_shared_core_and_materializes(f2_dsn: str, tmp_path: Path) -> None:
    goal_id, configured, completed = anyio.run(_exercise, f2_dsn, tmp_path)
    assert configured.is_error is False
    assert configured.structured_content["goal"]["repeat"] == {
        "frequency": "monthly", "interval": 1, "month_days": [10, 20],
    }
    assert completed.is_error is False
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        (count,) = conn.execute(
            "SELECT count(*) FROM goals WHERE owner = 't1' AND repeat_series_id = %s",
            (goal_id,),
        ).fetchone()
    assert count == 2
