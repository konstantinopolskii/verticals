from __future__ import annotations

from pathlib import Path

import anyio
import httpx2
import psycopg

from tests.mcp.conftest import TEST_TOKEN, api_server, open_mcp_stdio


async def _tag_round_trip(f2_dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        conn.execute("UPDATE goals SET tags = ARRAY['SYNTAG1','plain'] WHERE id = 'SYNORD01'")
        before = conn.execute("SELECT count(*) FROM goals").fetchone()[0]

    async with open_mcp_stdio(f2_dsn, tmp_path, label="r11-tags") as (session, streams):
        marked = await session.call_tool("tag_mark", {"tag": "SYNTAG1", "project": True})
        assert marked.is_error is False
        listed = await session.call_tool("tags", {})
        assert listed.is_error is False
        by_tag = {row["tag"]: row["project"] for row in listed.structured_content["tags"]}
        assert by_tag["SYNTAG1"] is True
        assert by_tag["plain"] is False
        streams.assert_hygiene(token=TEST_TOKEN)

    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(base_url=api.base_url, headers={"Authorization": f"Bearer {api.token}"}) as client:
            response = client.get("/api/tags")
            assert response.status_code == 200
            assert response.json() == listed.structured_content

    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM goals").fetchone()[0] == before


def test_r11_tag_tools_and_http_read_parity(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_tag_round_trip, f2_dsn, tmp_path)


async def _size_round_trip(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="r12-sizes") as (session, streams):
        expected = await session.call_tool(
            "update", {"id": "SYNORD01", "size_expected": "2x45-120 1x10-15"}
        )
        assert expected.is_error is False
        assert expected.structured_content["goal"]["size_expected"] == ["45-120m", "45-120m", "10-15m"]

        actual = await session.call_tool(
            "size_report", {"goal_id": "SYNORD01", "size_actual": ["45-120m"]}
        )
        assert actual.is_error is False
        assert actual.structured_content["goal"]["size_actual"] == ["45-120m"]

        refused = await session.call_tool(
            "size_report", {"goal_id": "SYNQ1R01", "size_actual": ["10-15m"]}
        )
        assert refused.is_error is True
        streams.assert_hygiene(token=TEST_TOKEN)

    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(base_url=api.base_url, headers={"Authorization": f"Bearer {api.token}"}) as client:
            detail = client.get("/api/goals/SYNORD01")
            assert detail.status_code == 200
            assert detail.json()["size_actual"] == ["45-120m"]
            changed = client.patch("/api/goals/SYNORD01", json={"size_expected": "1x<5m"})
            assert changed.status_code == 200
            assert changed.json()["size_expected"] == ["<5m"]
            no_actual_surface = client.patch("/api/goals/SYNORD01", json={"size_actual": ["<5m"]})
            assert no_actual_surface.status_code == 422


def test_r12_expected_both_transports_actual_agent_only(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_size_round_trip, f2_dsn, tmp_path)
