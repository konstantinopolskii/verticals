"""WP-A (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md) — the three comment tools
(`verticals/mcp/comments.py`) over a real stdio session, real F2, no mocks.

One session per test, several asserts per session — a server subprocess is the expensive part
here (tests/mcp house pattern, `tests/mcp/test_evidence_tools.py`'s own docstring). Covers:
agent authorship (every message this transport writes is `author='agent'`), reply-vs-new-thread
branching on `comment_add`, doc-by-path targeting (both on `comment_add` and on `comments`),
`client_token` replay, resolve/reopen, and owner isolation.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_OWNER_OTHER, TEST_TOKEN, open_mcp_stdio

GOAL_ID = "SYNDAY01"  # F2's own fixed id (docs/E2E.md §2), same one test_doc_tools.py reuses
DOC_PATH = "strategy/comment-probe.md"


# =================================================================================================
# new thread by goal_id, new thread by doc PATH, reply branching, refusals
# =================================================================================================


async def _round_trip(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="comment-round-trip") as (session, streams):
        doc = await session.call_tool("doc_create", {"path": DOC_PATH, "title": "Comment probe", "body": "v1"})
        doc_id = doc.structured_content["doc"]["id"]

        on_goal = await session.call_tool("comment_add", {"goal_id": GOAL_ID, "body": "agent note on goal"})
        thread_id = on_goal.structured_content["thread"]["id"]

        # doc-by-path targeting: the SAME `doc` field convention `doc_link`/`doc_get` use
        # (trailing '.md' read as a path).
        on_doc = await session.call_tool("comment_add", {"doc": DOC_PATH, "body": "agent note on doc"})

        with_anchor = await session.call_tool(
            "comment_add",
            {
                "goal_id": GOAL_ID, "body": "about this span",
                "anchor": {"quote": "the important bit", "prefix": "", "suffix": ""},
            },
        )

        reply = await session.call_tool("comment_add", {"thread_id": thread_id, "body": "a reply"})

        # branching refusal: thread_id together with a target arg is refused, not silently
        # merged — a reply already belongs to its own thread.
        reply_with_goal = await session.call_tool(
            "comment_add", {"thread_id": thread_id, "goal_id": GOAL_ID, "body": "should be refused"}
        )
        reply_with_anchor = await session.call_tool(
            "comment_add",
            {"thread_id": thread_id, "body": "should be refused", "anchor": {"quote": "x"}},
        )

        # comments: scoped by goal_id, scoped by doc PATH, both given at once is refused.
        goal_scoped = await session.call_tool("comments", {"goal_id": GOAL_ID})
        doc_scoped_by_path = await session.call_tool("comments", {"doc": DOC_PATH})
        both_scoped = await session.call_tool("comments", {"goal_id": GOAL_ID, "doc": DOC_PATH})

        streams.assert_hygiene(token=TEST_TOKEN)
    return (
        doc_id, on_goal, on_doc, with_anchor, reply, reply_with_goal, reply_with_anchor,
        goal_scoped, doc_scoped_by_path, both_scoped, thread_id,
    )


def test_comment_add_round_trip_and_reply_branching(f2_dsn: str, tmp_path: Path) -> None:
    (
        doc_id, on_goal, on_doc, with_anchor, reply, reply_with_goal, reply_with_anchor,
        goal_scoped, doc_scoped_by_path, both_scoped, thread_id,
    ) = anyio.run(_round_trip, f2_dsn, tmp_path)

    assert on_goal.is_error is False, on_goal.content[0].text if on_goal.content else on_goal
    t = on_goal.structured_content["thread"]
    assert t["goal_id"] == GOAL_ID and t["doc_id"] is None
    assert on_goal.structured_content["replayed"] is False
    # agent authorship: every message this transport writes is stamped 'agent', unconditionally.
    assert t["messages"][0]["author"] == "agent"

    assert on_doc.is_error is False, on_doc.content[0].text if on_doc.content else on_doc
    assert on_doc.structured_content["thread"]["doc_id"] == doc_id
    assert on_doc.structured_content["thread"]["messages"][0]["author"] == "agent"

    assert with_anchor.is_error is False
    anchor = with_anchor.structured_content["thread"]["anchor"]
    assert anchor == {"quote": "the important bit", "prefix": "", "suffix": ""}

    assert reply.is_error is False, reply.content[0].text if reply.content else reply
    assert reply.structured_content["thread_id"] == thread_id
    assert reply.structured_content["message"]["author"] == "agent"
    assert reply.structured_content["message"]["body"] == "a reply"

    assert reply_with_goal.is_error is True, "thread_id + goal_id together must be refused"
    assert "thread_id" in reply_with_goal.content[0].text
    assert reply_with_anchor.is_error is True, "thread_id + anchor together must be refused"

    assert goal_scoped.is_error is False
    goal_thread_ids = {t["id"] for t in goal_scoped.structured_content["threads"]}
    assert thread_id in goal_thread_ids
    assert on_doc.structured_content["thread"]["id"] not in goal_thread_ids

    assert doc_scoped_by_path.is_error is False, (
        doc_scoped_by_path.content[0].text if doc_scoped_by_path.content else doc_scoped_by_path
    )
    doc_thread_ids = {t["id"] for t in doc_scoped_by_path.structured_content["threads"]}
    assert on_doc.structured_content["thread"]["id"] in doc_thread_ids
    assert thread_id not in doc_thread_ids

    assert both_scoped.is_error is True, "comments accepts at most one of goal_id/doc"


# =================================================================================================
# comments with neither arg: the unresolved worklist, each row carrying its target
# =================================================================================================


async def _worklist(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="comment-worklist") as (session, streams):
        opened = await session.call_tool("comment_add", {"goal_id": GOAL_ID, "body": "needs attention"})
        thread_id = opened.structured_content["thread"]["id"]

        worklist_before = await session.call_tool("comments", {})

        resolved = await session.call_tool("comment_resolve", {"thread_id": thread_id})
        worklist_after = await session.call_tool("comments", {})

        reopened = await session.call_tool("comment_resolve", {"thread_id": thread_id, "resolved": False})
        worklist_reopened = await session.call_tool("comments", {})

        unknown = await session.call_tool("comment_resolve", {"thread_id": "ZZZZZZZZ"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return thread_id, worklist_before, resolved, worklist_after, reopened, worklist_reopened, unknown


def test_comments_worklist_and_resolve_reopen(f2_dsn: str, tmp_path: Path) -> None:
    (
        thread_id, worklist_before, resolved, worklist_after, reopened, worklist_reopened, unknown,
    ) = anyio.run(_worklist, f2_dsn, tmp_path)

    assert worklist_before.is_error is False
    before_ids = {t["id"] for t in worklist_before.structured_content["threads"]}
    assert thread_id in before_ids
    row = next(t for t in worklist_before.structured_content["threads"] if t["id"] == thread_id)
    assert row["target"] == {"kind": "goal", "id": GOAL_ID, "title": "Draft the outline", "path": None}

    assert resolved.is_error is False, resolved.content[0].text if resolved.content else resolved
    assert resolved.structured_content["thread"]["resolved_at"] is not None

    assert worklist_after.is_error is False
    after_ids = {t["id"] for t in worklist_after.structured_content["threads"]}
    assert thread_id not in after_ids, "a resolved thread must not appear in the worklist"

    assert reopened.is_error is False
    assert reopened.structured_content["thread"]["resolved_at"] is None

    reopened_ids = {t["id"] for t in worklist_reopened.structured_content["threads"]}
    assert thread_id in reopened_ids, "reopening returns the thread to the worklist"

    assert unknown.is_error is True


# =================================================================================================
# client_token replay
# =================================================================================================


async def _replay(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="comment-replay") as (session, streams):
        first = await session.call_tool(
            "comment_add", {"goal_id": GOAL_ID, "body": "idempotent thread", "client_token": "mcp-thread-1"}
        )
        replay = await session.call_tool(
            "comment_add", {"goal_id": GOAL_ID, "body": "idempotent thread", "client_token": "mcp-thread-1"}
        )
        streams.assert_hygiene(token=TEST_TOKEN)
    return first, replay


def test_comment_add_client_token_replay_writes_nothing_twice(f2_dsn: str, tmp_path: Path) -> None:
    first, replay = anyio.run(_replay, f2_dsn, tmp_path)
    assert first.is_error is False and replay.is_error is False
    assert first.structured_content["replayed"] is False
    assert replay.structured_content["replayed"] is True
    assert replay.structured_content["thread"]["id"] == first.structured_content["thread"]["id"]


# =================================================================================================
# owner isolation
# =================================================================================================


async def _owner_isolation(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="comment-owner-a") as (session, streams):
        created = await session.call_tool("comment_add", {"goal_id": GOAL_ID, "body": "owner a only"})
        streams.assert_hygiene(token=TEST_TOKEN)
    thread_id = created.structured_content["thread"]["id"]

    async with open_mcp_stdio(f2_dsn, tmp_path, owner=TEST_OWNER_OTHER, label="comment-owner-b") as (session2, streams2):
        foreign_reply = await session2.call_tool("comment_add", {"thread_id": thread_id, "body": "hijack"})
        foreign_resolve = await session2.call_tool("comment_resolve", {"thread_id": thread_id})
        foreign_worklist = await session2.call_tool("comments", {})
        streams2.assert_hygiene(token=TEST_TOKEN)
    return thread_id, foreign_reply, foreign_resolve, foreign_worklist


def test_comment_owner_isolation(f2_dsn: str, tmp_path: Path) -> None:
    thread_id, foreign_reply, foreign_resolve, foreign_worklist = anyio.run(
        _owner_isolation, f2_dsn, tmp_path
    )
    assert foreign_reply.is_error is True, "a foreign owner must not be able to reply into another owner's thread"
    assert foreign_resolve.is_error is True
    assert foreign_worklist.is_error is False
    assert thread_id not in {t["id"] for t in foreign_worklist.structured_content["threads"]}
