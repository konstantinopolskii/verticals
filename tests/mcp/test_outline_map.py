"""D252 (KK, 2026-08-20) — the `outline` tool's fourth mode, `map`: a compact box-drawing goal
map, replacing the desk automation's hand-built version. Real stdio session, real Postgres, no
mocks (house rule). Data is seeded directly through `core.goals`/`core.moves` (matching
`tests/mcp/test_reads.py::test_r9_goal_tool_carries_descendant_ideas`'s own pattern) under a
throwaway owner (`OWNER`, not one of F2's `t1`/`t2`) so the "without id" scenario's byte-exact
assertion never has to account for F2's own fixture rows living at the same top level.

**Sibling order, deliberately controlled.** `core.moves.allocate_position`'s own group is
`(owner, vertical, period_key)`, NOT `(owner, parent_id)`, for any SCHEDULED goal
(`verticals/mcp/tools.py::_sibling_ids`'s own docstring says so). Two children of the same parent
on DIFFERENT verticals therefore sit in unrelated position sequences — their relative order is
whatever `(position, id)` happens to sort to, not creation order — caught live the first time
this file compared its rendered tree against a hand-written expected string picking two
different-vertical siblings and getting them back swapped. Every sibling PAIR this file's
byte-exact assertions actually depend on ordering is seeded on the SAME vertical and the SAME
`anchor_date` (so the same `period_key`), guaranteeing position (and so render order) follows
creation order; every other branch is a lone child, whose order is not in question either way.
"""

from __future__ import annotations

import functools
from datetime import date
from pathlib import Path

import anyio
import psycopg

from verticals.core import goals as core_goals
from verticals.core import moves as core_moves

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

OWNER = "map-owner"  # isolated from F2's t1/t2 — see module docstring


# =================================================================================================
# Tree 1 — id-scoped subtree.
#
#   Root goal [3 years]
#   ├── Year child A [Year]
#   │   └── Month grandchild [August]
#   │       └── Week great-grandchild [Week]
#   └── Year child B [Year]
#       ├── Day task live one [2026-08-20]
#       └── Day task live two [2026-08-20]
#
# ("Day task done" and "Day task parked", both siblings of the two live day tasks above, must
# not appear anywhere in the rendered text — done/parked exclusion.) Covers: non-last connector
# with its own descendants (the `│   ` continuation, three levels deep), last connector with
# multiple own children (the four-space continuation), and the year/month-name/week/day-date
# label classes. Life and quarter are covered by Tree 2 below.
# =================================================================================================

EXPECTED_MAP_SUBTREE = (
    "Root goal [3 years]\n"
    "├── Year child A [Year]\n"
    "│   └── Month grandchild [August]\n"
    "│       └── Week great-grandchild [Week]\n"
    "└── Year child B [Year]\n"
    "    ├── Day task live one [2026-08-20]\n"
    "    └── Day task live two [2026-08-20]\n"
)

EXPECTED_MAP_SUBTREE_DEPTH1 = (
    "Root goal [3 years]\n"
    "├── Year child A [Year]\n"
    "└── Year child B [Year]\n"
)


def _seed_subtree(conn: psycopg.Connection) -> dict[str, str]:
    root = core_goals.create(
        conn, owner=OWNER, title="Root goal", vertical="decade", anchor_date=date(2026, 8, 20)
    ).goal

    # Same vertical + same anchor_date (same period_key) -> same position group -> creation
    # order is render order (see module docstring).
    child_a = core_goals.create(
        conn, owner=OWNER, title="Year child A", parent_id=root.id, vertical="year", anchor_date=date(2026, 1, 1)
    ).goal
    child_b = core_goals.create(
        conn, owner=OWNER, title="Year child B", parent_id=root.id, vertical="year", anchor_date=date(2026, 1, 1)
    ).goal

    # Lone-child chain under A — no sibling group, order is not in question.
    grand_a = core_goals.create(
        conn, owner=OWNER, title="Month grandchild", parent_id=child_a.id, vertical="month", anchor_date=date(2026, 8, 1)
    ).goal
    great_grand_a = core_goals.create(
        conn, owner=OWNER, title="Week great-grandchild", parent_id=grand_a.id, vertical="week", anchor_date=date(2026, 8, 17)
    ).goal

    # Four children of B, all vertical='day' with the SAME anchor_date -> one shared position
    # group -> creation order is render order for the two survivors after done/parked filtering.
    b_live1 = core_goals.create(
        conn, owner=OWNER, title="Day task live one", parent_id=child_b.id, vertical="day", anchor_date=date(2026, 8, 20)
    ).goal
    b_done = core_goals.create(
        conn, owner=OWNER, title="Day task done", parent_id=child_b.id, vertical="day", anchor_date=date(2026, 8, 20)
    ).goal
    core_goals.update(conn, owner=OWNER, id=b_done.id, done=True)
    b_parked = core_goals.create(
        conn, owner=OWNER, title="Day task parked", parent_id=child_b.id, vertical="day", anchor_date=date(2026, 8, 20)
    ).goal
    core_moves.park(conn, owner=OWNER, id=b_parked.id)
    b_live2 = core_goals.create(
        conn, owner=OWNER, title="Day task live two", parent_id=child_b.id, vertical="day", anchor_date=date(2026, 8, 20)
    ).goal

    return {
        "root": root.id, "child_a": child_a.id, "child_b": child_b.id,
        "grand_a": grand_a.id, "great_grand_a": great_grand_a.id,
        "b_live1": b_live1.id, "b_done": b_done.id, "b_parked": b_parked.id, "b_live2": b_live2.id,
    }


async def _outline_map(f2_dsn: str, tmp_path: Path, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, owner=OWNER, label=label) as (session, streams):
        result = await session.call_tool("outline", {**args, "mode": "map"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


def test_d252_outline_map_with_id_scopes_to_the_subtree_byte_exact(f2_dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        ids = _seed_subtree(conn)

    fn = functools.partial(_outline_map, f2_dsn, tmp_path, {"id": ids["root"]}, "d252a")
    result = anyio.run(fn)
    assert result.is_error is False, result.content[0].text if result.content else result
    text = result.content[0].text
    assert text == EXPECTED_MAP_SUBTREE, f"map text mismatch:\n--- got ---\n{text!r}\n--- want ---\n{EXPECTED_MAP_SUBTREE!r}"

    # Done and parked never appear anywhere in the rendered tree, not just at the top.
    assert "Day task done" not in text
    assert "Day task parked" not in text

    # Structured content carries an empty evidence map — the map grammar has no inline ids to
    # key one off (`_handle_outline`'s own comment for `mode == 'map'`).
    assert result.structured_content == {"evidence": {}}


def test_d252_outline_map_depth_1_stops_after_the_first_level(f2_dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        ids = _seed_subtree(conn)

    fn = functools.partial(_outline_map, f2_dsn, tmp_path, {"id": ids["root"], "depth": 1}, "d252b")
    result = anyio.run(fn)
    assert result.is_error is False
    text = result.content[0].text
    assert text == EXPECTED_MAP_SUBTREE_DEPTH1, f"depth=1 map mismatch:\n--- got ---\n{text!r}\n--- want ---\n{EXPECTED_MAP_SUBTREE_DEPTH1!r}"
    assert "Month grandchild" not in text, "depth=1 must not descend past the first level"


# =================================================================================================
# Tree 2 — no-id: every LIVE top-level goal becomes its own tree, in (vertical rank, period_key,
# position, id) order (`core.markdown._fetch_owner_roots`'s own order); a done top-level goal and
# the Maybe pile are both left off entirely. Covers the Life and Quarter label classes the first
# tree does not reach.
#
#   Decade root [3 years]
#   └── Decade root child [Quarter]
#
#   Value root [Life]
# =================================================================================================

EXPECTED_MAP_ROOTS = (
    "Decade root [3 years]\n"
    "└── Decade root child [Quarter]\n"
    "\n"
    "Value root [Life]\n"
)


def _seed_roots(conn: psycopg.Connection) -> dict[str, str]:
    decade_root = core_goals.create(
        conn, owner=OWNER, title="Decade root", vertical="decade", anchor_date=date(2026, 8, 20)
    ).goal
    core_goals.create(
        conn, owner=OWNER, title="Decade root child", parent_id=decade_root.id,
        vertical="quarter", anchor_date=date(2026, 8, 20),
    )
    value_root = core_goals.create(
        conn, owner=OWNER, title="Value root", vertical="life", anchor_date=date(2026, 8, 20)
    ).goal
    done_root = core_goals.create(
        conn, owner=OWNER, title="Done root", vertical="year", anchor_date=date(2026, 8, 20)
    ).goal
    core_goals.update(conn, owner=OWNER, id=done_root.id, done=True)
    maybe_root = core_goals.create(conn, owner=OWNER, title="Maybe item").goal
    return {
        "decade_root": decade_root.id, "value_root": value_root.id,
        "done_root": done_root.id, "maybe_root": maybe_root.id,
    }


def test_d252_outline_map_without_id_lists_live_top_level_roots(f2_dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        ids = _seed_roots(conn)

    fn = functools.partial(_outline_map, f2_dsn, tmp_path, {}, "d252c")
    result = anyio.run(fn)
    assert result.is_error is False, result.content[0].text if result.content else result
    text = result.content[0].text
    assert text == EXPECTED_MAP_ROOTS, f"map roots mismatch:\n--- got ---\n{text!r}\n--- want ---\n{EXPECTED_MAP_ROOTS!r}"

    assert "Done root" not in text, "a done top-level goal must not appear in the no-id map"
    assert "Maybe item" not in text, "the Maybe pile must not appear in the no-id map"

    # The same Maybe goal DOES render, labelled [Maybe], when explicitly rooted — the one
    # documented exception (goal_map's own module comment in core/markdown.py).
    rooted_fn = functools.partial(_outline_map, f2_dsn, tmp_path, {"id": ids["maybe_root"]}, "d252d")
    rooted = anyio.run(rooted_fn)
    assert rooted.is_error is False
    assert rooted.content[0].text == "Maybe item [Maybe]\n"
