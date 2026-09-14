"""S-115 settle correction: board provenance marks were retired by D110."""

from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession


def _create_agent_row(dsn: str, owner: str) -> str:
    from verticals.mcp import tools as mcp_tools

    with psycopg.connect(dsn, autocommit=True) as conn:
        result = mcp_tools.call_tool(
            conn,
            owner=owner,
            name="create",
            arguments={"title": "Synthetic agent board row", "vertical": "day", "anchor_date": "2026-08-08"},
        )
        assert not result.is_error, "MCP create failed during synthetic setup"
        goal_id = result.structured_content["goal"]["id"]
        (origin,) = conn.execute("SELECT origin FROM goals WHERE id = %s", (goal_id,)).fetchone()
        assert origin == "agent", "MCP create did not stamp agent origin"
        return goal_id


def test_s115_agent_writes_unmarked_on_board(ui_f2: UiSession) -> None:
    session = ui_f2
    agent_id = _create_agent_row(session.backend.dsn, "t1")
    session.page.reload()
    card = session.page.locator(f'[data-vertical] [data-goal-id="{agent_id}"]')
    card.wait_for(state="visible", timeout=10_000)

    # D110 scope is board-only: detail/transports retain provenance, board cards repeat no mark.
    assert card.locator('[data-role="origin-mark"], [data-origin]').count() == 0, (
        "D110: board card must not render retired provenance hooks"
    )
