from __future__ import annotations

from pathlib import Path

import anyio
import httpx2

from tests.mcp.conftest import TEST_TOKEN, api_server, open_mcp_stdio


async def _privacy_round_trip(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="privacy") as (session, streams):
        marked = await session.call_tool("update", {"ids": ["SYNORD01"], "private": True})
        assert marked.is_error is False
        assert marked.structured_content["goals"][0]["private"] is True

        state = await session.call_tool("privacy", {"on": True, "rules": "other people"})
        assert state.is_error is False
        assert state.structured_content["mode"] is True
        assert state.structured_content["rules"] == "other people"
        assert [g["id"] for g in state.structured_content["private"]] == ["SYNORD01"]
        streams.assert_hygiene(token=TEST_TOKEN)

    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(base_url=api.base_url, headers={"Authorization": f"Bearer {api.token}"}) as client:
            view = client.get("/api/privacy").json()
            assert view["mode"] is True
            assert "SYNORD01" in view["hidden"]
            off = client.put("/api/privacy", json={"mode": False})
            assert off.status_code == 200
            assert off.json()["mode"] is False
            assert client.put("/api/privacy", json={"mode": "no"}).status_code == 422


def test_privacy_flag_mode_and_http_view(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_privacy_round_trip, f2_dsn, tmp_path)
