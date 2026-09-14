"""WP-A (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md) — `core.comments` through real calls
and real Postgres, no mocks. Thread/message CRUD, the one-target rule, caps, resolve/unresolve,
unresolved listing (with its target descriptor), cascade on goal AND doc delete, owner
isolation, and `client_token` replay for the two writes that mint rows.
"""

from __future__ import annotations

import psycopg
import pytest

from verticals.core import comments, docs, goals
from verticals.core.errors import IdempotencyConflict, NotFound, ValidationError

OWNER = "comments-core"
OTHER_OWNER = "comments-other"


def _goal(conn: psycopg.Connection, *, owner: str = OWNER, title: str = "Subject", body: str = ""):
    return goals.create(conn, owner=owner, title=title, body=body).goal


def _doc(conn: psycopg.Connection, *, owner: str = OWNER, path: str = "notes.md", title: str = "Notes", body: str = ""):
    return docs.create(conn, owner=owner, path=path, title=title, body=body).doc


def _thread_on_goal(conn: psycopg.Connection, *, owner: str = OWNER, goal_id: str, body: str = "first message", author: str = "human", **kw):
    return comments.create_thread(conn, owner=owner, goal_id=goal_id, body=body, author=author, **kw)


# --- create_thread: happy path, both targets --------------------------------------------------


def test_create_thread_on_goal_returns_thread_with_first_message(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = comments.create_thread(db, owner=OWNER, goal_id=g.id, body="hello", author="human")
    t = created.thread
    assert created.replayed is False
    assert t.goal_id == g.id and t.doc_id is None
    assert t.anchor is None
    assert t.resolved_at is None
    assert len(t.messages) == 1
    assert t.messages[0].author == "human"
    assert t.messages[0].body == "hello"


def test_create_thread_on_doc_returns_thread_with_first_message(db: psycopg.Connection) -> None:
    d = _doc(db)
    created = comments.create_thread(db, owner=OWNER, doc_id=d.id, body="agent note", author="agent")
    t = created.thread
    assert t.doc_id == d.id and t.goal_id is None
    assert t.messages[0].author == "agent"


# --- one-target rule --------------------------------------------------------------------------


def test_create_thread_requires_exactly_one_target(db: psycopg.Connection) -> None:
    g = _goal(db)
    d = _doc(db)
    with pytest.raises(ValidationError) as neither:
        comments.create_thread(db, owner=OWNER, body="x", author="human")
    assert neither.value.detail["field"] == "goal_id,doc_id"

    with pytest.raises(ValidationError) as both:
        comments.create_thread(db, owner=OWNER, goal_id=g.id, doc_id=d.id, body="x", author="human")
    assert both.value.detail["field"] == "goal_id,doc_id"


def test_create_thread_unknown_goal_and_doc_are_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        comments.create_thread(db, owner=OWNER, goal_id="ZZZZZZZZ", body="x", author="human")
    with pytest.raises(NotFound):
        comments.create_thread(db, owner=OWNER, doc_id="ZZZZZZZZ", body="x", author="human")


def test_create_thread_refuses_another_owners_target(db: psycopg.Connection) -> None:
    """No existence oracle: a foreign goal reads the same as an unknown one."""
    theirs = _goal(db, owner=OTHER_OWNER)
    with pytest.raises(NotFound):
        comments.create_thread(db, owner=OWNER, goal_id=theirs.id, body="x", author="human")


# --- caps and validation ------------------------------------------------------------------------


def test_create_thread_refuses_blank_and_oversized_body(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(ValidationError):
        comments.create_thread(db, owner=OWNER, goal_id=g.id, body="   ", author="human")
    with pytest.raises(ValidationError):
        comments.create_thread(
            db, owner=OWNER, goal_id=g.id,
            body="x" * (comments.MAX_MESSAGE_BODY_BYTES + 1), author="human",
        )


def test_create_thread_refuses_bad_author(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(ValidationError):
        comments.create_thread(db, owner=OWNER, goal_id=g.id, body="x", author="robot")


def test_create_thread_with_anchor_round_trips(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = comments.create_thread(
        db, owner=OWNER, goal_id=g.id, body="see this bit", author="human",
        anchor={"quote": "the important part", "prefix": "before ", "suffix": " after"},
    )
    anchor = created.thread.anchor
    assert anchor is not None
    assert anchor.quote == "the important part"
    assert anchor.prefix == "before "
    assert anchor.suffix == " after"


def test_create_thread_anchor_prefix_suffix_default_to_empty_string(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = comments.create_thread(
        db, owner=OWNER, goal_id=g.id, body="x", author="human", anchor={"quote": "q"},
    )
    anchor = created.thread.anchor
    assert anchor.prefix == "" and anchor.suffix == ""


def test_create_thread_anchor_requires_nonempty_quote(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(ValidationError):
        comments.create_thread(db, owner=OWNER, goal_id=g.id, body="x", author="human", anchor={"quote": ""})
    with pytest.raises(ValidationError):
        comments.create_thread(db, owner=OWNER, goal_id=g.id, body="x", author="human", anchor={})


def test_create_thread_anchor_caps(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(ValidationError):
        comments.create_thread(
            db, owner=OWNER, goal_id=g.id, body="x", author="human",
            anchor={"quote": "q" * (comments.MAX_ANCHOR_QUOTE_CHARS + 1)},
        )
    with pytest.raises(ValidationError):
        comments.create_thread(
            db, owner=OWNER, goal_id=g.id, body="x", author="human",
            anchor={"quote": "q", "prefix": "p" * (comments.MAX_ANCHOR_PREFIX_CHARS + 1)},
        )
    with pytest.raises(ValidationError):
        comments.create_thread(
            db, owner=OWNER, goal_id=g.id, body="x", author="human",
            anchor={"quote": "q", "suffix": "s" * (comments.MAX_ANCHOR_SUFFIX_CHARS + 1)},
        )


# --- add_message -----------------------------------------------------------------------------


def test_add_message_appends_oldest_first(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id, body="first")
    comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="second", author="agent")
    comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="third", author="human")

    threads = comments.list_for_goal(db, owner=OWNER, goal_id=g.id)
    assert len(threads) == 1
    bodies = [m.body for m in threads[0].messages]
    authors = [m.author for m in threads[0].messages]
    assert bodies == ["first", "second", "third"]
    assert authors == ["human", "agent", "human"]


def test_add_message_unknown_thread_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        comments.add_message(db, owner=OWNER, thread_id="ZZZZZZZZ", body="x", author="human")


def test_add_message_refuses_blank_and_oversized_body(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    with pytest.raises(ValidationError):
        comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="", author="human")
    with pytest.raises(ValidationError):
        comments.add_message(
            db, owner=OWNER, thread_id=created.thread.id,
            body="x" * (comments.MAX_MESSAGE_BODY_BYTES + 1), author="human",
        )


def test_add_message_to_resolved_thread_is_allowed(db: psycopg.Connection) -> None:
    """v1 carries no rule against replying to a resolved thread (module docstring)."""
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    comments.set_resolved(db, owner=OWNER, thread_id=created.thread.id, resolved=True)
    added = comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="still here", author="agent")
    assert added.message.body == "still here"


# --- resolve / unresolve -------------------------------------------------------------------------


def test_set_resolved_sets_and_clears_resolved_at(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    resolved = comments.set_resolved(db, owner=OWNER, thread_id=created.thread.id, resolved=True)
    assert resolved.resolved_at is not None
    assert len(resolved.messages) == 1, "resolve returns the full thread, messages included"

    reopened = comments.set_resolved(db, owner=OWNER, thread_id=created.thread.id, resolved=False)
    assert reopened.resolved_at is None


def test_set_resolved_unknown_thread_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        comments.set_resolved(db, owner=OWNER, thread_id="ZZZZZZZZ", resolved=True)


def test_set_resolved_refuses_non_boolean(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    with pytest.raises(ValidationError):
        comments.set_resolved(db, owner=OWNER, thread_id=created.thread.id, resolved="yes")


# --- list_for_goal / list_for_doc -----------------------------------------------------------------


def test_list_for_goal_is_oldest_first_and_scoped(db: psycopg.Connection) -> None:
    g1 = _goal(db, title="G1")
    g2 = _goal(db, title="G2")
    t1 = _thread_on_goal(db, goal_id=g1.id, body="t1").thread
    _thread_on_goal(db, goal_id=g2.id, body="other goal's thread")
    t3 = _thread_on_goal(db, goal_id=g1.id, body="t3").thread

    threads = comments.list_for_goal(db, owner=OWNER, goal_id=g1.id)
    assert [t.id for t in threads] == [t1.id, t3.id]


def test_list_for_goal_unknown_goal_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        comments.list_for_goal(db, owner=OWNER, goal_id="ZZZZZZZZ")


def test_list_for_doc_mirrors_list_for_goal(db: psycopg.Connection) -> None:
    d = _doc(db)
    created = comments.create_thread(db, owner=OWNER, doc_id=d.id, body="on the doc", author="human")
    threads = comments.list_for_doc(db, owner=OWNER, doc_id=d.id)
    assert [t.id for t in threads] == [created.thread.id]


def test_list_for_doc_unknown_doc_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        comments.list_for_doc(db, owner=OWNER, doc_id="ZZZZZZZZ")


# --- list_unresolved: the agent worklist, with its target descriptor -----------------------------


def test_list_unresolved_excludes_resolved_and_carries_target(db: psycopg.Connection) -> None:
    g = _goal(db, title="Needs a look")
    d = _doc(db, path="worklist.md", title="Worklist doc")
    open_on_goal = _thread_on_goal(db, goal_id=g.id, body="open").thread
    resolved_on_goal = _thread_on_goal(db, goal_id=g.id, body="closed").thread
    comments.set_resolved(db, owner=OWNER, thread_id=resolved_on_goal.id, resolved=True)
    open_on_doc = comments.create_thread(db, owner=OWNER, doc_id=d.id, body="doc open", author="agent").thread

    unresolved = comments.list_unresolved(db, owner=OWNER)
    ids = {u.thread.id for u in unresolved}
    assert ids == {open_on_goal.id, open_on_doc.id}
    assert resolved_on_goal.id not in ids

    by_id = {u.thread.id: u for u in unresolved}
    goal_target = by_id[open_on_goal.id].target
    assert goal_target.kind == "goal" and goal_target.id == g.id and goal_target.title == "Needs a look"
    assert goal_target.path is None

    doc_target = by_id[open_on_doc.id].target
    assert doc_target.kind == "doc" and doc_target.id == d.id and doc_target.title == "Worklist doc"
    assert doc_target.path == "worklist.md"


def test_list_unresolved_is_owner_scoped(db: psycopg.Connection) -> None:
    mine = _goal(db)
    theirs = _goal(db, owner=OTHER_OWNER)
    _thread_on_goal(db, goal_id=mine.id, body="mine")
    comments.create_thread(db, owner=OTHER_OWNER, goal_id=theirs.id, body="theirs", author="human")

    unresolved = comments.list_unresolved(db, owner=OWNER)
    assert len(unresolved) == 1
    assert unresolved[0].thread.goal_id == mine.id


# --- cascade on goal delete AND doc delete --------------------------------------------------------


def test_cascade_on_goal_delete_removes_threads_and_messages(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="reply", author="agent")

    goals.delete(db, owner=OWNER, id=g.id)

    (thread_count,) = db.execute(
        "SELECT count(*) FROM comment_threads WHERE id = %s", (created.thread.id,)
    ).fetchone()
    (message_count,) = db.execute(
        "SELECT count(*) FROM comment_messages WHERE thread_id = %s", (created.thread.id,)
    ).fetchone()
    assert thread_count == 0
    assert message_count == 0


def test_cascade_on_doc_delete_removes_threads_and_messages(db: psycopg.Connection) -> None:
    d = _doc(db, path="to-delete.md")
    created = comments.create_thread(db, owner=OWNER, doc_id=d.id, body="on a doc", author="human")
    comments.add_message(db, owner=OWNER, thread_id=created.thread.id, body="reply", author="agent")

    docs.delete(db, owner=OWNER, id=d.id)

    (thread_count,) = db.execute(
        "SELECT count(*) FROM comment_threads WHERE id = %s", (created.thread.id,)
    ).fetchone()
    (message_count,) = db.execute(
        "SELECT count(*) FROM comment_messages WHERE thread_id = %s", (created.thread.id,)
    ).fetchone()
    assert thread_count == 0
    assert message_count == 0


# --- owner isolation -----------------------------------------------------------------------------


def test_owner_cannot_read_or_write_another_owners_thread(db: psycopg.Connection) -> None:
    theirs_goal = _goal(db, owner=OTHER_OWNER)
    theirs_thread = comments.create_thread(
        db, owner=OTHER_OWNER, goal_id=theirs_goal.id, body="private", author="human"
    ).thread

    with pytest.raises(NotFound):
        comments.add_message(db, owner=OWNER, thread_id=theirs_thread.id, body="hijack", author="human")
    with pytest.raises(NotFound):
        comments.set_resolved(db, owner=OWNER, thread_id=theirs_thread.id, resolved=True)
    # the target goal itself is foreign too, so the list read refuses the same way
    with pytest.raises(NotFound):
        comments.list_for_goal(db, owner=OWNER, goal_id=theirs_goal.id)


# --- client_token replay: create_thread and add_message ------------------------------------------


def test_create_thread_replay_via_client_token_writes_nothing_twice(db: psycopg.Connection) -> None:
    g = _goal(db)
    kwargs = dict(owner=OWNER, goal_id=g.id, body="idempotent", author="human", client_token="thread-token-1")
    first = comments.create_thread(db, **kwargs)
    replay = comments.create_thread(db, **kwargs)
    assert first.replayed is False and replay.replayed is True
    assert replay.thread.id == first.thread.id
    (thread_count,) = db.execute(
        "SELECT count(*) FROM comment_threads WHERE goal_id = %s", (g.id,)
    ).fetchone()
    assert thread_count == 1, "a replay must not mint a second thread"


def test_add_message_replay_via_client_token_writes_nothing_twice(db: psycopg.Connection) -> None:
    g = _goal(db)
    created = _thread_on_goal(db, goal_id=g.id)
    kwargs = dict(
        owner=OWNER, thread_id=created.thread.id, body="reply once", author="agent",
        client_token="message-token-1",
    )
    first = comments.add_message(db, **kwargs)
    replay = comments.add_message(db, **kwargs)
    assert first.replayed is False and replay.replayed is True
    assert replay.message.id == first.message.id
    (message_count,) = db.execute(
        "SELECT count(*) FROM comment_messages WHERE thread_id = %s", (created.thread.id,)
    ).fetchone()
    assert message_count == 2, "the first message plus exactly one reply — the replay wrote nothing"


def test_create_thread_client_token_reused_with_different_body_conflicts(db: psycopg.Connection) -> None:
    g = _goal(db)
    comments.create_thread(db, owner=OWNER, goal_id=g.id, body="v1", author="human", client_token="dup-token")
    with pytest.raises(IdempotencyConflict):
        comments.create_thread(db, owner=OWNER, goal_id=g.id, body="v2", author="human", client_token="dup-token")
