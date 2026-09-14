"""D250 WP-2 — the eight document tools (`verticals/mcp/docs.py`) and the `outline` tool's new
`mode` parameter, over a real stdio session, real F2, no mocks.

One session per test, several asserts per session — a server subprocess is the expensive part
here (tests/mcp house pattern, `tests/mcp/test_evidence_tools.py`'s own docstring), and every
scenario below is a read-modify-read story that only makes sense inside one session anyway.

**The truncation-cap investigation (WP-2's own instruction).** KK reported outline text being
swallowed in a real session — bodies missing for some nodes, no error. Every candidate spot was
read looking for a size cap, a byte budget, or a silent-drop path: `core/markdown.py::outline`
itself (no cap of any kind — it renders every byte of every body in the subtree, the only prune
is the caller-supplied, explicit `depth` argument, which drops whole nodes, never trims a body
it still renders); `verticals/mcp/tools.py::_handle_outline` and `verticals/mcp/shapes.py` (the
128 KB budget documented there, S-48, belongs to the `board` tool alone — `outline`'s own
`content` is handed back whole, uncapped); the `mcp` SDK's stdio/streamable-http transports
(no per-message byte cap in the installed `mcp` package — `anyio.create_memory_object_stream`'s
`max_buffer_size` bounds queued *messages*, not a message's own size). **Finding: no cap,
truncation, or depth limit exists anywhere in the current outline code path that would silently
drop body text.** Nothing here was found to make explicit, so no truncation-marker test is added;
if bodies really did go missing in a live session, the cause sits outside this file's own reach
(most plausibly the calling agent's own context window, not this server) — reported as a finding,
not patched over with an invented cap this codebase's own behaviour does not have.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from tests.mcp.conftest import TEST_OWNER_OTHER, TEST_TOKEN, open_mcp_stdio

DOC_PATH = "strategy/wp2-probe.md"


# =================================================================================================
# create -> get -> save -> history -> restore round-trip, plus the stale/missing-field refusals
# =================================================================================================


async def _round_trip(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="doc-round-trip") as (session, streams):
        created = await session.call_tool(
            "doc_create", {"path": DOC_PATH, "title": "WP-2 probe", "body": "v1 body"}
        )
        doc_id = created.structured_content["doc"]["id"]

        got = await session.call_tool("doc_get", {"id": doc_id})
        got_by_path = await session.call_tool("doc_get", {"path": DOC_PATH})
        both_and_neither = await session.call_tool("doc_get", {"id": doc_id, "path": DOC_PATH})

        saved = await session.call_tool(
            "doc_save", {"id": doc_id, "expected_revision": 1, "body": "v2 body"}
        )
        history = await session.call_tool("doc_history", {"id": doc_id})
        revision1 = await session.call_tool("doc_revision", {"id": doc_id, "revision": 1})
        restored = await session.call_tool(
            "doc_restore", {"id": doc_id, "revision": 1, "expected_revision": 2}
        )
        tree = await session.call_tool("doc_tree", {})

        stale = await session.call_tool(
            "doc_save", {"id": doc_id, "expected_revision": 1, "body": "stale write"}
        )
        # D102's own pattern (docs/EVIDENCE.md §6.2, tests/mcp/test_evidence_tools.py), applied
        # to this tool family's own truly-required field: a `doc_save` missing
        # `expected_revision` is refused at the schema boundary (`_validate_top_level`), before
        # `core.docs.save()` is ever called.
        missing_expected_revision = await session.call_tool("doc_save", {"id": doc_id, "body": "no lock"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return (
        created, got, got_by_path, both_and_neither, saved, history, revision1, restored, tree,
        stale, missing_expected_revision,
    )


def test_wp2_doc_create_get_save_history_restore_round_trip(f2_dsn: str, tmp_path: Path) -> None:
    (
        created, got, got_by_path, both_and_neither, saved, history, revision1, restored, tree,
        stale, missing_expected_revision,
    ) = anyio.run(_round_trip, f2_dsn, tmp_path)

    assert created.is_error is False, created.content[0].text if created.content else created
    doc = created.structured_content["doc"]
    assert doc["path"] == DOC_PATH
    assert doc["title"] == "WP-2 probe"
    assert doc["body"] == "v1 body"
    assert doc["revision"] == 1
    assert doc["linked_goals"] == []

    assert got.is_error is False and got.structured_content["doc"]["id"] == doc["id"]
    assert got_by_path.is_error is False and got_by_path.structured_content["doc"]["id"] == doc["id"]
    assert both_and_neither.is_error is True, "doc_get needs exactly one of id or path, not both"

    assert saved.is_error is False, saved.content[0].text if saved.content else saved
    assert saved.structured_content["doc"]["revision"] == 2
    assert saved.structured_content["doc"]["body"] == "v2 body"
    assert saved.structured_content["doc"]["path"] == DOC_PATH, "path untouched when not sent"
    assert saved.structured_content["doc"]["title"] == "WP-2 probe", "title untouched when not sent"

    assert history.is_error is False
    revisions = history.structured_content["revisions"]
    assert [r["revision"] for r in revisions] == [1, 2]
    assert all("body" not in r for r in revisions), "history is a picker, never the body text"
    assert revisions[0]["body_length"] == len("v1 body")

    assert revision1.is_error is False
    assert revision1.structured_content["revision"]["body"] == "v1 body"

    assert restored.is_error is False, restored.content[0].text if restored.content else restored
    assert restored.structured_content["doc"]["revision"] == 3, "restore appends, never rewinds history"
    assert restored.structured_content["doc"]["body"] == "v1 body"
    assert restored.structured_content["doc"]["path"] == DOC_PATH, "restore never touches path"

    assert tree.is_error is False
    tree_docs = tree.structured_content["docs"]
    assert doc["id"] in {d["id"] for d in tree_docs}
    assert all("body" not in d for d in tree_docs), "the tree is a folder listing, never a body"

    assert stale.is_error is True, "expected_revision=1 against a doc now at revision 3 must be refused"
    assert "revision" in stale.content[0].text.lower()

    assert missing_expected_revision.is_error is True
    assert "expected_revision" in missing_expected_revision.content[0].text


# =================================================================================================
# doc_delete refusal while a goal body links the doc
# =================================================================================================


async def _delete_refusal(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="doc-delete-refusal") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/linked.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]
        doc_path = created.structured_content["doc"]["path"]

        linked = await session.call_tool(
            "update", {"id": "SYNDAY01", "body": f"see [the plan](doc:{doc_path})"}
        )
        refused = await session.call_tool("doc_delete", {"id": doc_id})
        still_there = await session.call_tool("doc_get", {"id": doc_id})

        # Remove the link, then the same delete succeeds — proves the refusal really was about
        # the link, not some other defect.
        await session.call_tool("update", {"id": "SYNDAY01", "body": "no link anymore"})
        unlinked_delete = await session.call_tool("doc_delete", {"id": doc_id})
        streams.assert_hygiene(token=TEST_TOKEN)
    return linked, refused, still_there, unlinked_delete


def test_wp2_doc_delete_refused_while_a_goal_links_it(f2_dsn: str, tmp_path: Path) -> None:
    linked, refused, still_there, unlinked_delete = anyio.run(_delete_refusal, f2_dsn, tmp_path)

    assert linked.is_error is False, linked.content[0].text if linked.content else linked
    assert refused.is_error is True
    assert "SYNDAY01" in refused.content[0].text, "the refusal must name the linking goal id"
    assert still_there.is_error is False, "the doc must still exist — the delete never ran"

    assert unlinked_delete.is_error is False, (
        unlinked_delete.content[0].text if unlinked_delete.content else unlinked_delete
    )


# =================================================================================================
# owner isolation
# =================================================================================================


async def _owner_isolation(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="doc-owner-a") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/owner-only.md", "body": "t1 only"})
        streams.assert_hygiene(token=TEST_TOKEN)

    doc_id = created.structured_content["doc"]["id"]

    async with open_mcp_stdio(f2_dsn, tmp_path, owner=TEST_OWNER_OTHER, label="doc-owner-b") as (session2, streams2):
        foreign_get = await session2.call_tool("doc_get", {"id": doc_id})
        foreign_tree = await session2.call_tool("doc_tree", {})
        streams2.assert_hygiene(token=TEST_TOKEN)
    return doc_id, foreign_get, foreign_tree


def test_wp2_doc_owner_isolation(f2_dsn: str, tmp_path: Path) -> None:
    doc_id, foreign_get, foreign_tree = anyio.run(_owner_isolation, f2_dsn, tmp_path)
    assert foreign_get.is_error is True, "a foreign owner must not be able to read another owner's doc"
    assert doc_id not in {d["id"] for d in foreign_tree.structured_content["docs"]}


# =================================================================================================
# outline modes: full / headlines / headlines+docs, over a seeded goal<->doc mutual link
# =================================================================================================


async def _outline_modes(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="doc-outline-modes") as (session, streams):
        doc = await session.call_tool("doc_create", {"path": "strategy/outline-probe.md", "body": "doc side"})
        doc_id = doc.structured_content["doc"]["id"]
        doc_path = doc.structured_content["doc"]["path"]

        # A mutual link: the goal's own body names the doc (`source='goal'`) and the doc's own
        # body names the goal back (`source='doc'`) — two independent `goal_doc_links` rows for
        # the same pair, so `headlines+docs` reporting the path exactly once proves the dedup,
        # not just the happy path of a single link.
        await session.call_tool(
            "update", {"id": "SYNDAY01", "body": f"secret body text\n\n[the plan](doc:{doc_path})"}
        )
        await session.call_tool(
            "doc_save", {"id": doc_id, "expected_revision": 1, "body": "doc side\n\n[the day](goal:SYNDAY01)"}
        )

        full = await session.call_tool("outline", {"id": "SYNQ2R01"})
        headlines = await session.call_tool("outline", {"id": "SYNQ2R01", "mode": "headlines"})
        headlines_docs = await session.call_tool("outline", {"id": "SYNQ2R01", "mode": "headlines+docs"})
        bad_mode = await session.call_tool("outline", {"id": "SYNQ2R01", "mode": "not-a-real-mode"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return doc_path, full, headlines, headlines_docs, bad_mode


def test_wp2_outline_modes(f2_dsn: str, tmp_path: Path) -> None:
    doc_path, full, headlines, headlines_docs, bad_mode = anyio.run(_outline_modes, f2_dsn, tmp_path)

    assert full.is_error is False
    full_md = full.content[0].text
    assert "secret body text" in full_md, "'full' is byte-identical to the original outline: bodies included"
    assert "[SYNDAY01]" in full_md and "[SYNQ2R01]" in full_md

    assert headlines.is_error is False
    headlines_md = headlines.content[0].text
    assert "secret body text" not in headlines_md, "'headlines' must carry no body text anywhere"
    assert "[SYNDAY01]" in headlines_md and "[SYNQ2R01]" in headlines_md, "node lines (id inline) stay"
    assert "doc:" not in headlines_md, "'headlines' (not '+docs') never mentions doc links"

    assert headlines_docs.is_error is False
    hd_md = headlines_docs.content[0].text
    assert "secret body text" not in hd_md, "'headlines+docs' still carries no body text"
    assert hd_md.count(f"doc: {doc_path}") == 1, "the doc path appears exactly once despite the mutual link"
    hd_lines = hd_md.splitlines()
    day_idx = next(i for i, ln in enumerate(hd_lines) if "[SYNDAY01]" in ln)
    assert f"doc: {doc_path}" in hd_lines[day_idx + 1], "the doc line sits directly under its own goal's node line"

    assert bad_mode.is_error is True
    assert "mode" in bad_mode.content[0].text


# =================================================================================================
# D254 (KK, 2026-08-24) — doc_link / doc_unlink. Goal card xMSR1MXF found the verb gap: D250 made
# links text-derived, but gave an agent no VERB to attach or detach one. The acceptance test below
# is the card's own six steps, verbatim. SYNDAY01/SYNSUB01 is the same fixed F2 parent/child pair
# `test_d251_goal_tool_carries_inherited_docs` above reuses (SYNSUB01's parent is SYNDAY01).
# =================================================================================================


async def _d254_acceptance(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-acceptance") as (session, streams):
        # 1. Create a native document.
        created = await session.call_tool(
            "doc_create", {"path": "strategy/d254-acceptance.md", "title": "D254 acceptance doc", "body": "v1"}
        )
        doc_id = created.structured_content["doc"]["id"]
        doc_path = created.structured_content["doc"]["path"]

        # 2. Attach it to a parent goal.
        linked = await session.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": doc_id})

        # 3. Confirm that a child inherits it.
        child = await session.call_tool("goal", {"id": "SYNSUB01"})

        # 4. Save revision 2 and confirm that the link survives.
        saved = await session.call_tool("doc_save", {"id": doc_id, "expected_revision": 1, "body": "v2"})
        parent_after_save = await session.call_tool("goal", {"id": "SYNDAY01"})

        # 5. Unlink it.
        unlinked = await session.call_tool("doc_unlink", {"goal_id": "SYNDAY01", "doc": doc_path})

        # 6. Confirm that the document and both revisions remain intact.
        doc_after = await session.call_tool("doc_get", {"id": doc_id})
        history = await session.call_tool("doc_history", {"id": doc_id})

        streams.assert_hygiene(token=TEST_TOKEN)
    return doc_id, doc_path, linked, child, saved, parent_after_save, unlinked, doc_after, history


def test_d254_doc_link_unlink_acceptance(f2_dsn: str, tmp_path: Path) -> None:
    (
        doc_id, doc_path, linked, child, saved, parent_after_save, unlinked, doc_after, history,
    ) = anyio.run(_d254_acceptance, f2_dsn, tmp_path)

    assert linked.is_error is False, linked.content[0].text if linked.content else linked
    assert linked.structured_content == {
        "goal_id": "SYNDAY01", "doc_id": doc_id, "doc_path": doc_path,
        "already_linked": False, "inherited_from": None,
    }

    assert child.is_error is False, child.content[0].text if child.content else child
    assert child.structured_content["docs"] == [
        {
            "id": doc_id, "path": doc_path, "title": "D254 acceptance doc", "source": "goal",
            "inherited_from": {"id": "SYNDAY01", "title": "Draft the outline"},
        }
    ], "the child must inherit the parent's link, D251-shaped"

    assert saved.is_error is False, saved.content[0].text if saved.content else saved
    assert saved.structured_content["doc"]["revision"] == 2

    assert parent_after_save.is_error is False
    parent_docs = parent_after_save.structured_content["docs"]
    assert any(d["id"] == doc_id and d["inherited_from"] is None for d in parent_docs), (
        "the link lives in SYNDAY01's own body text — a doc_save on the document itself must "
        "never touch it"
    )

    assert unlinked.is_error is False, unlinked.content[0].text if unlinked.content else unlinked
    assert unlinked.structured_content == {
        "goal_id": "SYNDAY01", "doc_id": doc_id, "doc_path": doc_path,
        "removed": True, "doc_side_link_remains": False,
    }

    assert doc_after.is_error is False, "the document must still exist after unlink"
    assert doc_after.structured_content["doc"]["id"] == doc_id
    assert doc_after.structured_content["doc"]["revision"] == 2
    assert doc_after.structured_content["doc"]["body"] == "v2"

    assert history.is_error is False
    assert [r["revision"] for r in history.structured_content["revisions"]] == [1, 2], (
        "both revisions must remain intact — unlink never touches docs or doc_revisions"
    )


# =================================================================================================
# doc_link is retry-safe: linking an already-(own-)linked document a second time succeeds without
# writing again — the goal's body must be byte-identical before and after the replay.
# =================================================================================================


async def _double_link_idempotent(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-double-link") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/double-link.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]

        first = await session.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": doc_id})
        after_first = await session.call_tool("goal", {"id": "SYNDAY01"})
        second = await session.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": doc_id})
        after_second = await session.call_tool("goal", {"id": "SYNDAY01"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return first, after_first, second, after_second


def test_d254_doc_link_is_idempotent_on_retry(f2_dsn: str, tmp_path: Path) -> None:
    first, after_first, second, after_second = anyio.run(_double_link_idempotent, f2_dsn, tmp_path)

    assert first.is_error is False
    assert first.structured_content["already_linked"] is False

    assert second.is_error is False, second.content[0].text if second.content else second
    assert second.structured_content["already_linked"] is True

    assert after_first.structured_content["goal"]["body"] == after_second.structured_content["goal"]["body"], (
        "a replayed doc_link must write nothing — the goal body must be byte-identical"
    )


# =================================================================================================
# doc_link refuses a redundant descendant link, naming the ancestor it would duplicate (D251's
# ghosting law: every descendant already inherits an ancestor-linked document for free).
# =================================================================================================


async def _link_refused_when_inherited(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-link-refused") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/inherited-refuse.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]

        linked_parent = await session.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": doc_id})
        refused = await session.call_tool("doc_link", {"goal_id": "SYNSUB01", "doc": doc_id})

        streams.assert_hygiene(token=TEST_TOKEN)
    return linked_parent, refused


def test_d254_doc_link_refused_when_already_inherited(f2_dsn: str, tmp_path: Path) -> None:
    linked_parent, refused = anyio.run(_link_refused_when_inherited, f2_dsn, tmp_path)

    assert linked_parent.is_error is False, linked_parent.content[0].text if linked_parent.content else linked_parent

    assert refused.is_error is True
    text = refused.content[0].text
    assert "SYNDAY01" in text, "the refusal must name the ancestor's id"
    assert "Draft the outline" in text, "the refusal must name the ancestor's title"


# =================================================================================================
# doc_unlink is a no-op success when the goal never linked the document directly.
# =================================================================================================


async def _unlink_noop(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-unlink-noop") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/never-linked.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]

        before = await session.call_tool("goal", {"id": "SYNDAY01"})
        result = await session.call_tool("doc_unlink", {"goal_id": "SYNDAY01", "doc": doc_id})
        after = await session.call_tool("goal", {"id": "SYNDAY01"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return before, result, after


def test_d254_doc_unlink_is_a_noop_when_not_linked(f2_dsn: str, tmp_path: Path) -> None:
    before, result, after = anyio.run(_unlink_noop, f2_dsn, tmp_path)

    assert result.is_error is False, result.content[0].text if result.content else result
    assert result.structured_content["removed"] is False
    assert result.structured_content["doc_side_link_remains"] is False
    assert before.structured_content["goal"]["body"] == after.structured_content["goal"]["body"], (
        "a no-op unlink must write nothing"
    )


# =================================================================================================
# doc_unlink removes the GOAL's own link but never the document's own words: a mutual link (the
# goal's body naming the doc AND the doc's body naming the goal back) leaves the doc-side half
# standing, reported in the result and still visible on the goal's own docs field.
# =================================================================================================


async def _unlink_reports_doc_side_link(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-unlink-doc-side") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/mutual-link.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]

        await session.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": doc_id})
        await session.call_tool(
            "doc_save", {"id": doc_id, "expected_revision": 1, "body": "[the day](goal:SYNDAY01)"}
        )

        unlinked = await session.call_tool("doc_unlink", {"goal_id": "SYNDAY01", "doc": doc_id})
        goal_after = await session.call_tool("goal", {"id": "SYNDAY01"})

        streams.assert_hygiene(token=TEST_TOKEN)
    return doc_id, unlinked, goal_after


def test_d254_doc_unlink_leaves_doc_side_link_intact_and_reports_it(f2_dsn: str, tmp_path: Path) -> None:
    doc_id, unlinked, goal_after = anyio.run(_unlink_reports_doc_side_link, f2_dsn, tmp_path)

    assert unlinked.is_error is False, unlinked.content[0].text if unlinked.content else unlinked
    assert unlinked.structured_content["removed"] is True, "the goal-side link text was removed"
    assert unlinked.structured_content["doc_side_link_remains"] is True

    goal_docs = goal_after.structured_content["docs"]
    assert any(d["id"] == doc_id and d["source"] == "doc" for d in goal_docs), (
        "the document's own body still names this goal back — that link must survive"
    )
    assert not any(d["id"] == doc_id and d["source"] == "goal" for d in goal_docs), (
        "the goal's own body no longer names the document"
    )


# =================================================================================================
# doc_link/doc_unlink's own truly-required field (`doc`/`goal_id`) is refused at the schema
# boundary before either core/ module runs — D102's pattern, same class of scenario as
# `test_wp2_doc_create_get_save_history_restore_round_trip`'s `missing_expected_revision`.
# =================================================================================================


async def _missing_required_field(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-missing-field") as (session, streams):
        missing_doc = await session.call_tool("doc_link", {"goal_id": "SYNDAY01"})
        missing_goal_id = await session.call_tool("doc_unlink", {"doc": "strategy/whatever.md"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return missing_doc, missing_goal_id


def test_d254_doc_link_unlink_missing_required_field_refused_at_schema_boundary(
    f2_dsn: str, tmp_path: Path
) -> None:
    missing_doc, missing_goal_id = anyio.run(_missing_required_field, f2_dsn, tmp_path)

    assert missing_doc.is_error is True
    assert "doc" in missing_doc.content[0].text

    assert missing_goal_id.is_error is True
    assert "goal_id" in missing_goal_id.content[0].text


# =================================================================================================
# owner isolation: a foreign owner can reach neither side of a link — not another owner's goal,
# not another owner's document — even knowing the ids.
# =================================================================================================


async def _link_owner_isolation(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="d254-owner-a") as (session, streams):
        created = await session.call_tool("doc_create", {"path": "strategy/owner-a-link.md", "body": ""})
        doc_id = created.structured_content["doc"]["id"]
        streams.assert_hygiene(token=TEST_TOKEN)

    async with open_mcp_stdio(
        f2_dsn, tmp_path, owner=TEST_OWNER_OTHER, label="d254-owner-b"
    ) as (session2, streams2):
        own_doc = await session2.call_tool("doc_create", {"path": "strategy/owner-b-link.md", "body": ""})
        own_doc_id = own_doc.structured_content["doc"]["id"]
        # Owner B's own document, but owner A's goal id — refused (that goal does not exist for B).
        foreign_goal = await session2.call_tool("doc_link", {"goal_id": "SYNDAY01", "doc": own_doc_id})
        # Owner B's own goal, but owner A's document id — refused (that document does not exist for B).
        foreign_doc = await session2.call_tool("doc_link", {"goal_id": "SYNOTH01", "doc": doc_id})
        streams2.assert_hygiene(token=TEST_TOKEN)
    return foreign_goal, foreign_doc


def test_d254_doc_link_owner_isolation(f2_dsn: str, tmp_path: Path) -> None:
    foreign_goal, foreign_doc = anyio.run(_link_owner_isolation, f2_dsn, tmp_path)
    assert foreign_goal.is_error is True, "a foreign owner must not reach another owner's goal"
    assert foreign_doc.is_error is True, "a foreign owner must not reach another owner's document"


# =================================================================================================
# D251 (KK, 2026-08-20): the `goal` tool's `docs` field carries own-plus-inherited, same shape
# HTTP's `GET /api/goals/{id}` carries (`tests/http/test_docs.py`'s own mirror scenario). SYNSUB01
# is a fixed F2 fixture row whose parent is SYNDAY01 (`tests/fixtures/f2_synth.sql`, also the
# ancestor chain `tests/http/test_read_isolation.py::ANCESTORS_ROOT_TO_PARENT` pins) — reused here
# rather than building a fresh chain, since the fixture already gives an exact, stable parent-child
# pair.
# =================================================================================================


async def _goal_tool_inherited_docs(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="goal-inherited-docs") as (session, streams):
        doc = await session.call_tool("doc_create", {"path": "strategy/inherited-mcp.md", "body": ""})
        doc_id = doc.structured_content["doc"]["id"]
        doc_path = doc.structured_content["doc"]["path"]

        await session.call_tool("update", {"id": "SYNDAY01", "body": f"[link](doc:{doc_path})"})
        detail = await session.call_tool("goal", {"id": "SYNSUB01"})
        streams.assert_hygiene(token=TEST_TOKEN)
    return doc_id, doc_path, detail


def test_d251_goal_tool_carries_inherited_docs(f2_dsn: str, tmp_path: Path) -> None:
    doc_id, doc_path, detail = anyio.run(_goal_tool_inherited_docs, f2_dsn, tmp_path)
    assert detail.is_error is False, detail.content[0].text if detail.content else detail
    assert detail.structured_content["docs"] == [
        {
            "id": doc_id, "path": doc_path, "title": None, "source": "goal",
            "inherited_from": {"id": "SYNDAY01", "title": "Draft the outline"},
        }
    ]
