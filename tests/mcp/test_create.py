"""S-52 (nested create), S-53 (origin stamped by the transport), S-56 (idempotent create) —
`docs/E2E.md` lines 1329-1372. Real stdio session, real F2 fixture, no mocks."""

from __future__ import annotations

from pathlib import Path

import anyio
import psycopg

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

# S-52's own steps: a 400-character markdown body on the root.
_S52_BODY = ("The retro surfaced three carry-forward items. " * 9)[:400]
assert len(_S52_BODY) == 400, len(_S52_BODY)


def _goal_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        return count


async def _call(f2_dsn: str, tmp_path: Path, name: str, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool(name, args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


# --- S-52 --------------------------------------------------------------------------------------


def test_s52_create_with_nested_children_lands_a_whole_plan_in_one_call(f2_dsn: str, tmp_path: Path) -> None:
    before = _goal_count(f2_dsn)

    args = {
        "title": "Retro carry-forward",
        "tags": ["retro"],
        "vertical": "week",
        "anchor_date": "2026-08-10",
        "body": _S52_BODY,
        "children": [
            {
                "title": "Write up the sources",
                "vertical": "day",
                "anchor_date": "2026-08-10",
                "children": [
                    {"title": "Pull the raw notes"},
                    {"title": "Tag the quotes"},
                ],
            },
            {"title": "Fold into tomorrow's plan", "vertical": "day", "anchor_date": "2026-08-10"},
            {"title": "Someday, no promise", "vertical": None},
        ],
    }
    result = anyio.run(_call, f2_dsn, tmp_path, "create", args, "s52")

    assert result.is_error is False, result.content[0].text if result.content else result
    sc = result.structured_content
    root = sc["goal"]
    children = sc["children"]

    after = _goal_count(f2_dsn)
    assert after - before == 6, f"expected count(*) +6, got +{after - before}"

    assert root["period_key"] == "2026-W33", root["period_key"]
    assert root["origin"] == "agent", root["origin"]

    assert len(children) == 5, f"expected every descendant flattened (5), got {len(children)}: {children}"
    for c in children:
        assert c["path"].startswith(root["path"]), f"{c['id']}'s path {c['path']!r} does not start with root's {root['path']!r}"
        assert c["origin"] == "agent", c

    depths = sorted(c["depth"] for c in children)
    assert depths == [1, 1, 1, 2, 2], depths

    # Depth 1 only: the two grandchildren also carry vertical:None (never given one of their own),
    # so filtering on vertical alone would catch three nodes, not the one the scenario means —
    # "one with vertical:null" describes one of the *three top-level* children.
    null_vertical_children = [c for c in children if c["vertical"] is None and c["depth"] == 1]
    assert len(null_vertical_children) == 1, [c for c in children if c["vertical"] is None]
    leaf = null_vertical_children[0]
    assert leaf["parent_id"] == root["id"], "the vertical:null child must be attached under its parent"

    # S-25: the Maybe column is `vertical IS NULL AND parent_id IS NULL AND done_at IS NULL` — a
    # child with a real parent_id can never land there, but this proves it against the live board
    # rather than only against the schema predicate's text.
    board_result = anyio.run(_call, f2_dsn, tmp_path, "board", {"date": "2026-08-10"}, "s52-board")
    maybe_column = next(c for c in board_result.structured_content["columns"] if c["vertical"] is None)
    maybe_ids = {g["id"] for g in maybe_column["goals"]}
    assert leaf["id"] not in maybe_ids, f"{leaf['id']} (vertical:null, has a parent) leaked into Maybe: {maybe_ids}"

    search_result = anyio.run(_call, f2_dsn, tmp_path, "search", {"tag": "retro"}, "s52-search")
    assert len(search_result.structured_content["goals"]) == 3, search_result.structured_content["goals"]


# --- S-53 --------------------------------------------------------------------------------------


def test_s53_step1a_explicit_origin_argument_is_rejected_by_schema(f2_dsn: str, tmp_path: Path) -> None:
    before = _goal_count(f2_dsn)
    result = anyio.run(
        _call, f2_dsn, tmp_path, "create", {"title": "should never land", "origin": "human"}, "s53a"
    )
    assert result.is_error is True
    text = result.content[0].text
    assert "origin" in text, f"refusal text should name the offending field: {text!r}"
    after = _goal_count(f2_dsn)
    assert after == before, f"a schema-rejected create must write nothing: {before} -> {after}"


def test_s53_step1b_create_without_origin_is_stamped_agent(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(_call, f2_dsn, tmp_path, "create", {"title": "no origin argument at all"}, "s53b")
    assert result.is_error is False
    assert result.structured_content["goal"]["origin"] == "agent"


def test_s53_step2_update_leaves_the_creators_origin_unchanged(f2_dsn: str, tmp_path: Path) -> None:
    result = anyio.run(
        _call, f2_dsn, tmp_path, "update", {"id": "SYNCOL01", "body": "Touched by S-53 step 2."}, "s53c"
    )
    assert result.is_error is False
    sc = result.structured_content
    assert sc["goal"]["origin"] == "import", (
        "origin records who created the row, not who last touched it (§10-D4) — "
        f"got {sc['goal']['origin']!r}"
    )
    assert sc["last_write_origin"] == "agent", sc


# --- S-56 --------------------------------------------------------------------------------------


def test_s56_idempotent_create_over_mcp(f2_dsn: str, tmp_path: Path) -> None:
    before = _goal_count(f2_dsn)
    args = {"title": "Idempotent probe", "client_token": "ct-mcp-1"}

    first = anyio.run(_call, f2_dsn, tmp_path, "create", args, "s56a")
    assert first.is_error is False
    assert first.structured_content["replayed"] is False
    first_id = first.structured_content["goal"]["id"]

    second = anyio.run(_call, f2_dsn, tmp_path, "create", args, "s56b")
    assert second.is_error is False
    assert second.structured_content["goal"]["id"] == first_id, "a replay must return the same id"
    assert second.structured_content["replayed"] is True, "the second call must be flagged replayed:true"

    after = _goal_count(f2_dsn)
    assert after - before == 1, f"expected exactly +1 row for two identical client_token calls, got +{after - before}"
