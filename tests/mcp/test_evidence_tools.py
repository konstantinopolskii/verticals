"""WP-33 (docs/EVIDENCE.md §10, group 7 + the MCP half of group 5) — the two evidence tools and
the reader summaries over a real stdio session, real F2, no mocks.

One session per test, several asserts per session — a server subprocess is the expensive part
here (tests/mcp house pattern), and every scenario below is a read-modify-read story that only
makes sense inside one session anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_TOKEN, open_mcp_stdio

SUMMARY_FIELDS = {"status", "verified_at", "review_after"}
NOW = "2026-08-11T12:00:00+00:00"
# review_after is compared against the REAL wall clock inside core (`as_of = now(utc)`), so a
# fixed date here is a time bomb: the original 2026-08-18T12:00Z expired mid-day 2026-08-18 and
# demoted every "just verified" row to stale. Keep it relative — always a year out.
LATER = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=365)).isoformat()

PAYLOAD = {
    "sources": [{"id": "S1", "type": "transcript", "ref": "SYNREF01", "date": "2026-07-31"}],
    "claims": [{"id": "C1", "text": "a short agent formulation", "source_ids": ["S1"]}],
    "unresolved": ["one open question"],
}


async def _verify_then_read_everywhere(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="wp33") as (session, streams):
        goal = await session.call_tool("goal", {"id": "SYNDAY01"})
        assert goal.is_error is False
        revision = goal.structured_content["evidence"]["content_revision"]

        written = await session.call_tool(
            "evidence_update",
            {
                "goal_id": "SYNDAY01",
                "expected_content_revision": revision,
                "status": "verified",
                "verified_at": NOW,
                "review_after": LATER,
                "payload": PAYLOAD,
                "client_token": "wp33-write-1",
            },
        )
        board = await session.call_tool("board", {"date": "2026-08-08"})
        search = await session.call_tool("search", {"q": "outline"})
        outline = await session.call_tool("outline", {"id": "SYNQ2R01"})
        detail = await session.call_tool("goal", {"id": "SYNDAY01"})

        # Group 5, the MCP no-oracle half: unknown vs foreign ids must be indistinguishable —
        # same error text with only the caller's own input varying (S-41's contract).
        # client_token is REQUIRED on this tool (spec §6.2, D102) — distinct per call below,
        # so the no-oracle pair and the stale probe each reach core instead of replaying.
        args = {"expected_content_revision": 0, "status": "unverified", "payload": {}}
        unknown = await session.call_tool("evidence_update", {"goal_id": "ZZZZZZZZ", "client_token": "wp33-unknown", **args})
        foreign = await session.call_tool("evidence_update", {"goal_id": "SYNOTH01", "client_token": "wp33-foreign", **args})

        stale = await session.call_tool(
            "evidence_update",
            {"goal_id": "SYNDAY01", "expected_content_revision": revision + 41, "status": "partial", "payload": {}, "client_token": "wp33-stale"},
        )
        # The D102 requirement itself: a tokenless write is refused at the schema boundary,
        # before core ever sees it.
        tokenless = await session.call_tool(
            "evidence_update",
            {"goal_id": "SYNDAY01", "expected_content_revision": revision, "status": "partial", "payload": {}},
        )
        streams.assert_hygiene(token=TEST_TOKEN)
    return written, board, search, outline, detail, unknown, foreign, stale, tokenless


def test_wp33_write_then_every_reader_reports_the_summary(f2_dsn: str, tmp_path: Path) -> None:
    written, board, search, outline, detail, unknown, foreign, stale, tokenless = anyio.run(
        _verify_then_read_everywhere, f2_dsn, tmp_path
    )

    assert written.is_error is False, written.content[0].text if written.content else written
    ev = written.structured_content["evidence"]
    assert ev["stored_status"] == "verified"
    assert ev["status"] == "verified", "just verified against the live revision — not stale"
    assert ev["evidence_revision"] == 0
    assert written.structured_content["replayed"] is False

    # board: summary present for the verified card AND for every other drawn goal (unverified),
    # exactly three fields, keyed like progress/ancestors/children.
    assert board.is_error is False, board.content[0].text if board.content else board
    bsc = board.structured_content
    assert set(bsc["evidence"]["SYNDAY01"]) == SUMMARY_FIELDS
    assert bsc["evidence"]["SYNDAY01"]["status"] == "verified"
    drawn = {g["id"] for c in bsc["columns"] for g in c["goals"]}
    assert drawn <= set(bsc["evidence"]), "every drawn card carries a summary"
    other = next(gid for gid in drawn if gid != "SYNDAY01")
    assert bsc["evidence"][other] == {"status": "unverified", "verified_at": None, "review_after": None}

    # search: same summary map beside the cards; never a payload.
    ssc = search.structured_content
    assert set(ssc["evidence"].get("SYNDAY01", {})) == SUMMARY_FIELDS
    for entry in ssc["evidence"].values():
        assert "payload" not in entry and set(entry) == SUMMARY_FIELDS

    # outline: the markdown text is untouched as content; the summary map rides beside it,
    # keyed by the ids the outline itself printed inline.
    md = outline.content[0].text
    assert "[SYNDAY01]" in md
    osc = outline.structured_content
    assert osc["evidence"]["SYNDAY01"]["status"] == "verified"
    assert set(osc["evidence"]["SYNDAY01"]) == SUMMARY_FIELDS

    # goal: the ONE full-evidence reader — payload, revisions, cutoff.
    dev = detail.structured_content["evidence"]
    assert dev["payload"] == PAYLOAD
    assert dev["verified_against_revision"] == dev["content_revision"]
    assert dev["status"] == "verified"

    # the no-oracle pair: byte-identical but for the caller's own id.
    unknown_text = unknown.content[0].text
    foreign_text = foreign.content[0].text
    assert unknown.is_error is True and foreign.is_error is True
    assert unknown_text.replace("ZZZZZZZZ", "X") == foreign_text.replace("SYNOTH01", "X"), (
        f"unknown vs foreign must be indistinguishable: {unknown_text!r} vs {foreign_text!r}"
    )

    # optimistic lock over the wire: refused, current revision named, so the agent re-reads.
    assert stale.is_error is True
    assert "content revision" in stale.content[0].text

    # D102: client_token is required on this one write tool — refused at the schema boundary.
    assert tokenless.is_error is True
    assert "client_token" in tokenless.content[0].text


async def _due_walk(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="wp33due") as (session, streams):
        first = await session.call_tool("evidence_due", {"limit": 10})
        seen = [item["goal_id"] for item in first.structured_content["items"]]
        cursor = first.structured_content["next_cursor"]
        pages = 1
        while cursor is not None:
            page = await session.call_tool("evidence_due", {"limit": 10, "cursor": cursor})
            seen.extend(item["goal_id"] for item in page.structured_content["items"])
            cursor = page.structured_content["next_cursor"]
            pages += 1
        scoped = await session.call_tool("evidence_due", {"verticals": ["day"], "limit": 200})
        streams.assert_hygiene(token=TEST_TOKEN)
    return first, seen, pages, scoped


def test_wp33_due_pages_the_whole_f2_corpus_slim(f2_dsn: str, tmp_path: Path) -> None:
    first, seen, pages, scoped = anyio.run(_due_walk, f2_dsn, tmp_path)

    assert first.is_error is False
    assert pages > 1, "F2 (t1: 46 rows, all unverified) must not fit one 10-row page"
    assert len(seen) == len(set(seen)) == 46, "t1's whole F2 corpus, no page overlap, no drops"
    assert "SYNOTH01" not in seen, "t2's row never appears — owner-scoped like every reader"
    for item in first.structured_content["items"]:
        assert set(item) == {
            "goal_id", "title", "vertical", "anchor_date", "effective_status",
            "verified_at", "review_after", "content_revision", "verified_against_revision",
        }, "the worklist is slim by contract"

    day_items = scoped.structured_content["items"]
    assert day_items and all(i["vertical"] == "day" for i in day_items)
