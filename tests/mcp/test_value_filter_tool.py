"""`board(value=...)` and the D231 colour law over a real stdio session, real F2, no mocks.

One session, one story: filter to SYNLIF01's subtree, watch the life column narrow while the
top-level `values` list stays whole (D240), watch the Maybe exemption hold, watch the
refusals fire, and prove `update`'s colour write obeys the value-roots-only rule end to end.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

DATE = "2026-08-08"  # F2's census date (E2E.md §2)
BLUE = "#278dea"


def _column(board_result, vertical: str | None) -> dict:
    for column in board_result.structured_content["columns"]:
        if column["vertical"] == vertical:
            return {card["id"]: card for card in column["goals"]}
    raise AssertionError(f"no {vertical!r} column in board result")


async def _full_story(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="valuefilter") as (session, streams):
        unfiltered = await session.call_tool("board", {"date": DATE})
        filtered = await session.call_tool("board", {"date": DATE, "value": "SYNLIF01"})
        unknown = await session.call_tool("board", {"date": DATE, "value": "NOPE9999"})
        not_a_root = await session.call_tool("board", {"date": DATE, "value": "SYNCOL01"})

        painted = await session.call_tool("update", {"id": "SYNLIF01", "color": BLUE})
        # D239 rides the same story: the one-word menu label writes on the value root,
        # lands in the board's sparse short_labels map, and is refused off roots.
        labelled = await session.call_tool("update", {"id": "SYNLIF01", "short_label": "Money"})
        board_after = await session.call_tool("board", {"date": DATE})
        child_refused = await session.call_tool("update", {"id": "SYNDAY01", "color": BLUE})
        label_refused = await session.call_tool("update", {"id": "SYNDAY01", "short_label": "Nope"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return (
        unfiltered, filtered, unknown, not_a_root, painted, labelled, board_after,
        child_refused, label_refused,
    )


def test_board_value_filter_and_colour_law_over_stdio(f2_dsn: str, tmp_path: Path) -> None:
    (
        unfiltered, filtered, unknown, not_a_root, painted, labelled, board_after,
        child_refused, label_refused,
    ) = anyio.run(_full_story, f2_dsn, tmp_path)

    assert filtered.is_error is False, filtered.content[0].text if filtered.content else filtered
    day = _column(filtered, "day")
    assert "SYNDAY01" in day, "SYNLIF01's day descendant must survive its own filter"
    assert "SYNCOL01" not in day, "an unvalued day root must not survive the filter"
    # D240: life narrows to the selected value's own rows; the menu's source is the top-level
    # `values` list, which rides both responses unfiltered (F2 has one value — the multi-value
    # narrowing proof is the core suite's; the wire proof is the list's presence and shape).
    assert set(_column(filtered, "life")) == {"SYNLIF01"}
    assert [v["id"] for v in filtered.structured_content["values"]] == ["SYNLIF01"]
    assert [v["id"] for v in unfiltered.structured_content["values"]] == ["SYNLIF01"]
    assert set(_column(filtered, None)) == set(_column(unfiltered, None))

    assert unknown.is_error is True
    assert not_a_root.is_error is True, "a non-value-root id must be refused, not treated as empty"

    assert painted.is_error is False, painted.content[0].text if painted.content else painted
    after_day = _column(board_after, "day")
    assert after_day["SYNDAY01"]["color"] == BLUE, "descendant must wear the derived value colour"
    assert after_day["SYNCOL01"]["color"] is None, "stored colour below no life root is never read"

    assert child_refused.is_error is True
    assert "value roots" in (child_refused.content[0].text if child_refused.content else "")

    # D239 over the wire: the label is in the board's sparse map, and the root gate holds.
    assert labelled.is_error is False, labelled.content[0].text if labelled.content else labelled
    assert board_after.structured_content["short_labels"] == {"SYNLIF01": "Money"}
    assert label_refused.is_error is True
    assert "value roots" in (label_refused.content[0].text if label_refused.content else "")
