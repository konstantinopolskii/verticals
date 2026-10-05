"""S-47 — the tool surface itself: `docs/E2E.md` lines 1263-1275. Real `tools/list` over a real
stdio session, no mocks."""

from __future__ import annotations

from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

# `comment` LEFT this list deliberately (WP-A, KK decisions 2026-08-25, docs/COMMENTS_SPEC.md):
# it was standing in for a reference-planner parity concept this project had chosen not to build, and
# that choice is reversed now that `comments`/`comment_add`/`comment_resolve` are a real, shipped
# part of the tool surface — asserting the substring's absence would refuse the very feature this
# migration exists to add. The other five still name concepts this project has never adopted
# (`assignee`, `board_id`, `bucket`, `space`, `invite` — multi-user/kanban/workspace vocabulary),
# so they stay forbidden.
FORBIDDEN_SUBSTRINGS = ("assignee", "board_id", "bucket", "space", "invite")
# D250 WP-2: the eight document tools join the surface (`verticals/mcp/docs.py`) — this pin moves
# from sixteen to twenty-four deliberately, per WP-2's own instruction, not as an accidental
# drift. `doc_get`/`doc_tree`/`doc_history`/`doc_revision` are reads; `doc_create`/`doc_save`/
# `doc_restore`/`doc_delete` are the four new mutators, each with the same optional client_token
# every S-47-era mutator carries.
# D254: `doc_link`/`doc_unlink` join the surface (the verb gap goal card xMSR1MXF found — D250
# gave documents no attach/detach verb, only a text convention) — this pin moves again, twenty-four
# to twenty-six, deliberately. Both are mutators (goal-body text edits through `core.goals.update`,
# `verticals/mcp/docs.py`'s own D254 section), each with the same optional client_token.
# WP-A: `comments`/`comment_add`/`comment_resolve` join the surface (`verticals/mcp/comments.py`)
# — twenty-six to twenty-nine, deliberately. `comments` is a read; `comment_add`/`comment_resolve`
# are mutators, each with the same optional client_token (`comment_resolve`'s is accepted and
# never read by `core.comments.set_resolved`, the same stance `doc_delete` already takes — see
# `verticals/mcp/comments.py`'s own module docstring).
EXPECTED_TOOL_NAMES = {"board", "goal", "outline", "search", "create", "update", "schedule", "reparent", "delete", "park", "evidence_update", "evidence_due", "tags", "tag_mark", "size_report", "due_ack", "doc_create", "doc_get", "doc_save", "doc_tree", "doc_history", "doc_revision", "doc_restore", "doc_delete", "doc_link", "doc_unlink", "comments", "comment_add", "comment_resolve", "privacy"}
MUTATING_TOOLS = {"create", "update", "schedule", "reparent", "delete", "park", "evidence_update", "tag_mark", "size_report", "due_ack", "doc_create", "doc_save", "doc_restore", "doc_delete", "doc_link", "doc_unlink", "comment_add", "comment_resolve", "privacy"}


async def _list_tools(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s47") as (session, streams):
        result = await session.list_tools()
        streams.assert_hygiene(token=TEST_TOKEN)
        return result.tools


def test_s47_tool_surface_is_exactly_thirty_named_tools(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    names = {t.name for t in tools}
    assert len(tools) == 30, f"expected exactly 30 tools, got {len(tools)}: {sorted(names)}"
    assert names == EXPECTED_TOOL_NAMES, f"tool set mismatch: {sorted(names)}"


def test_s47_every_tool_has_a_non_empty_description(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    empty = [t.name for t in tools if not (t.description or "").strip()]
    assert not empty, f"tool(s) with an empty description: {empty}"


def test_s47_every_schema_has_additional_properties_false(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    bad = [t.name for t in tools if t.input_schema.get("additionalProperties") is not False]
    assert not bad, f"tool(s) whose schema does not pin additionalProperties: false: {bad}"


def test_s47_every_mutating_tool_has_an_optional_client_token(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    by_name = {t.name: t for t in tools}
    missing = []
    for name in MUTATING_TOOLS:
        props = by_name[name].input_schema.get("properties", {})
        prop = props.get("client_token")
        required = by_name[name].input_schema.get("required", [])
        # `evidence_update` is the one write tool that REQUIRES the token (docs/EVIDENCE.md
        # §6.2, D102 — agent-only surface; a tokenless retry would bump evidence_revision and
        # 409 its own second attempt). The other five keep it optional, S-47's original shape.
        want_required = name == "evidence_update"
        if prop is None or ("client_token" in required) != want_required:
            missing.append(name)
    assert not missing, f"client_token contract broken (optional for S-47 tools, required for evidence_update): {missing}"


def test_s47_no_tool_name_or_description_leaks_a_forbidden_word(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    hits = []
    for t in tools:
        haystack = f"{t.name} {t.description or ''}".lower()
        for word in FORBIDDEN_SUBSTRINGS:
            if word in haystack:
                hits.append((t.name, word))
    assert not hits, f"forbidden substring(s) found in tool name/description: {hits}"


def test_s47_update_accepts_bulk_ids_and_after_id_not_in_architecture_sketch(f2_dsn: str, tmp_path: Path) -> None:
    """The scenario's own second half: `ARCHITECTURE.md` §5's sketch of `update` omits `ids` and
    `after_id` entirely (recorded there as "a disagreement with §5, §14" in the scenario text
    itself, not something to silently correct here). Without them S-59's `bulk_update`/`reorder`
    manifest rows could not validate against any real schema."""
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    update = next(t for t in tools if t.name == "update")
    props = update.input_schema.get("properties", {})

    assert "id" in props, "update must still accept a single id"
    ids_prop = props.get("ids")
    assert ids_prop is not None, "update must accept a bulk ids: string[]"
    assert ids_prop.get("type") == "array", f"ids must be an array, got {ids_prop.get('type')!r}"
    assert ids_prop.get("items", {}).get("type") == "string", "ids must be an array of strings"
    assert ids_prop.get("maxItems") == 500, f"ids maxItems must be 500, got {ids_prop.get('maxItems')!r}"

    after_id_prop = props.get("after_id")
    assert after_id_prop is not None, "update must accept an ordering argument after_id"
    after_id_type = after_id_prop.get("type")
    types_present = set(after_id_type) if isinstance(after_id_type, list) else {after_id_type}
    assert types_present == {"string", "null"}, f"after_id must be string|null, got {after_id_type!r}"

    required = update.input_schema.get("required", [])
    assert "id" not in required and "ids" not in required, (
        "id/ids must not both be required (they are mutually exclusive) — "
        f"schema 'required' is {required!r}"
    )

    foil_prop = props.get("foil")
    assert foil_prop is not None and foil_prop.get("type") == "boolean"

    ignored_prop = props.get("carryover_ignored_until")
    assert ignored_prop is not None
    assert set(ignored_prop.get("type", [])) == {"string", "null"}
    assert ignored_prop.get("format") == "date"


def test_v2_park_schema_requires_only_id(f2_dsn: str, tmp_path: Path) -> None:
    tools = anyio.run(_list_tools, f2_dsn, tmp_path)
    park = next(t for t in tools if t.name == "park")
    assert park.input_schema["required"] == ["id"]
    assert set(park.input_schema["properties"]) == {"id", "client_token"}
