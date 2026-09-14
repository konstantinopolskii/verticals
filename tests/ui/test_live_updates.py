"""D237 in the browser: an out-of-band write appears on the board with NO page reload.

The write below goes through the raw HTTP API from the test process — exactly the path an
agent's MCP write takes from the board's point of view (a different client, a different
connection, the same Postgres). The page is never reloaded and never touched; the card must
simply arrive, carried by migration 012's trigger -> /api/events -> store.liveReload.
"""

from __future__ import annotations

import httpx

from tests.ui.conftest import UiSession


def test_agent_write_lands_without_page_reload(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # A sentinel proves no reload sneaks in: any navigation would wipe window state.
    page.evaluate("window.__liveProbe = 'armed'")

    created = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json={"title": "SYN live arrival", "vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    # SSE doorbell -> debounced silent refetch. 10s is generous; the real path is sub-second.
    page.wait_for_selector(f'[data-goal-id="{new_id}"]', timeout=10000)
    assert page.evaluate("window.__liveProbe") == "armed", "the board must not have reloaded"

    # The reverse direction too: an out-of-band delete clears the card without a reload.
    deleted = httpx.delete(
        f"{session.backend.base_url}/api/goals/{new_id}",
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert deleted.status_code == 204, deleted.text
    page.wait_for_selector(f'[data-goal-id="{new_id}"]', state="detached", timeout=10000)
    assert page.evaluate("window.__liveProbe") == "armed"
