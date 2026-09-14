"""S-130 — The input limits hold on the surface the agent drives, `docs/E2E.md` lines 1469-1478.
Real stdio session, real F2 fixture, no mocks. Required by AC-205.

Every one of the seven cases below comes back `isError: true` from the outside regardless of
which layer actually catches it — `tools.py::call_tool`'s own `except VerticalError` routes both
`_validate_top_level`'s schema-level refusals (only `maxItems` on an array is actually enforced
there, despite `maxLength` also being declared in several schemas as a client-facing hint) and
every `core/` validator's refusal through the identical `_error_result(...)` path, which caps
every message at 200 characters no matter its source. So this file asserts the black-box
contract the scenario states (refused, short message, nothing written, server still alive)
rather than which internal function happened to raise — the two schema-enforced cases (17 tags,
501 ids) are noted inline, not asserted differently."""

from __future__ import annotations

from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_TOKEN, full_table_digest, open_mcp_stdio

MAX_BODY_BYTES = 64 * 1024


def _deep_chain(levels: int) -> dict[str, object]:
    """A single-child chain `levels` deep below whatever it is attached as `children` to."""
    node: dict[str, object] = {"title": f"level {levels}"}
    for level in range(levels - 1, 0, -1):
        node = {"title": f"level {level}", "children": [node]}
    return node


async def _plant_and_check_alive(f2_dsn: str, tmp_path: Path, tool: str, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        bad = await session.call_tool(tool, args)
        board = await session.call_tool("board", {"date": "2026-08-08"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return bad, board


def _assert_refused_and_harmless(
    f2_dsn: str, tmp_path: Path, tool: str, args: dict[str, object], label: str
) -> str:
    digest_before = full_table_digest(f2_dsn)
    bad, board = anyio.run(_plant_and_check_alive, f2_dsn, tmp_path, tool, args, label)

    assert bad.is_error is True, f"{label}: expected a refusal, got {bad}"
    text = bad.content[0].text
    assert len(text) < 200, f"{label}: refusal text must be under 200 characters, got {len(text)}: {text!r}"

    assert board.is_error is False, f"{label}: the server must still answer a call after the refusal"

    digest_after = full_table_digest(f2_dsn)
    assert digest_after == digest_before, f"{label}: a refused call must not change a single row"
    return text


def test_s130_over_cap_body_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    body = "x" * (MAX_BODY_BYTES + 1)
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "create", {"title": "t", "body": body}, "s130-body")
    assert "body" in text, text


def test_s130_seventeen_tags_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    """Schema-enforced: `tags` declares `maxItems: 16` on the top-level property itself, so this
    one is caught by `_validate_top_level` before `core/` ever runs."""
    tags = [f"t{n}" for n in range(17)]
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "create", {"title": "t", "tags": tags}, "s130-tags-count")
    assert "tags" in text, text


def test_s130_49_char_tag_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    text = _assert_refused_and_harmless(
        f2_dsn, tmp_path, "create", {"title": "t", "tags": ["a" * 49]}, "s130-tag-length"
    )
    assert "tag" in text, text


def test_s130_children_nested_9_deep_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    args = {"title": "root", "children": [_deep_chain(9)]}
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "create", args, "s130-depth")
    assert "children" in text or "level" in text, text


def test_s130_201_nodes_in_one_create_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    args = {"title": "root", "children": [{"title": f"child {n}"} for n in range(200)]}
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "create", args, "s130-node-count")
    assert "200" in text, text


def test_s130_501_ids_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    """Schema-enforced: `ids` declares `maxItems: 500` on `update`'s own top-level property."""
    ids = [f"id{n:06d}" for n in range(501)]
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "update", {"ids": ids, "done": True}, "s130-ids")
    assert "500" in text, text


def test_s130_2_char_query_is_refused(f2_dsn: str, tmp_path: Path) -> None:
    text = _assert_refused_and_harmless(f2_dsn, tmp_path, "search", {"q": "ab"}, "s130-query")
    assert "q" in text, text
