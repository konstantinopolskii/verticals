"""Comments as structured rows (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md, WP-A) —
`015_comments.sql` end to end: thread/message validation, the one-target rule, resolve/
unresolve, and the three list reads (`list_for_goal`, `list_for_doc`, `list_unresolved`).

Mirrors `core/docs.py`'s own conventions throughout: owner-scoped, `ValidationError`/`NotFound`
from `core.errors`, ids via `core.field_rules.generate_id` (8-char base62, retried on collision
same as `docs.create`/`goals.create`), every function takes an open connection and never
commits (IR-02) — a multi-statement body wraps itself in `with conn.transaction()`.

**Why this exists at all.** Agents are first-class writers of Verticals, not a second-class API
bolted onto a UI feature — a comment thread is the return channel between KK (web, `author=
'human'`) and his agents (MCP, `author='agent'`), so the whole point of storing threads as ROWS
rather than the kit's own localStorage `innerHTML` snapshot (KK decision 5) is that an agent can
actually read one. `author` is therefore never a caller-supplied field on either transport — it
is decided by which transport made the call (`api/routes_comments.py` always passes `'human'`;
`mcp/comments.py` always passes `'agent'`) and only re-validated here as the closed-set check
every `core/` boundary applies to every enum-shaped input, defence in depth against a transport
bug, not a real choice a caller gets to make.

**Exactly one target, checked twice, for two different reasons.** `create_thread` refuses a
call naming zero or both of `goal_id`/`doc_id` before any statement runs (the same "refused, not
silently corrected" stance every `core/` validator takes), and separately pre-checks that the
NAMED target actually exists for this owner before inserting — `015_comments.sql`'s own FK
already enforces referential integrity, but a raw `psycopg.errors.ForeignKeyViolation` is not
one of the eight closed `VerticalError` types, so the pre-check exists purely to turn "no such
goal" into a clean `NotFound` instead of an unmapped database exception leaking through
`api/errors.py`'s/`mcp/tools.py`'s own catch-alls (`core/docs.py::create`'s own
`docs_path_unique_per_owner` catch is the same move, one constraint over).

**Anchor trio, validated here, never as a database CHECK** (`015_comments.sql`'s own header:
"a plain CHECK cannot express as cleanly as core/comments.py can" — the exact stance
`core/docs.py::validate_path` already takes for path shape). All three of
`anchor_quote`/`anchor_prefix`/`anchor_suffix` are `None` together (a whole-card/whole-doc
thread) or `quote` is a non-empty string with `prefix`/`suffix` each a string, possibly empty
(docs/COMMENTS_SPEC.md: "prefix/suffix may be empty strings").

**Idempotency is real for the two writes that create rows, absent for the one that does not.**
`create_thread`/`add_message` both accept `client_token` and wire it through `core/idem.py`
exactly like `core.goals.create`/`core.evidence.evidence_update` — a retried thread-or-message
POST must not double-post the comment. `set_resolved` takes no `client_token` at all: flipping
`resolved_at` between a timestamp and `NULL` is idempotent by construction (a second identical
call lands on the same final state, never a duplicate row), so there is nothing here for a
replay ledger to protect against — the same reasoning `core.docs.py`'s own module docstring
gives for why `doc_link`/`doc_unlink` need no idempotency machinery of their own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime as _datetime

import psycopg

from verticals.core import idem
from verticals.core.errors import NotFound, ValidationError
from verticals.core.field_rules import (
    generate_id as _generate_id,
    optional_str as _optional_str,
    require_str as _require_str,
    validate_owner as _validate_owner,
)
from verticals.models import CommentAnchor, CommentMessage, CommentTarget, CommentThread, UnresolvedThread

# --- bounds ----------------------------------------------------------------------------------

# A comment message is a chat-length reply, not a document (`core.docs.MAX_DOC_BODY_BYTES` is
# 512 KiB for exactly that reason it would be the wrong bound here) — sized the same order of
# magnitude as `core.field_rules.MAX_BODY_BYTES` (a goal's own body, 64 KiB), a quarter of it,
# because a comment is conversational, not the primary content it is attached to. Chosen, not
# pinned anywhere in docs/COMMENTS_SPEC.md beyond the literal number itself (16384).
MAX_MESSAGE_BODY_BYTES = 16384

# docs/COMMENTS_SPEC.md's own caps, verbatim.
MAX_ANCHOR_QUOTE_CHARS = 2048
MAX_ANCHOR_PREFIX_CHARS = 256
MAX_ANCHOR_SUFFIX_CHARS = 256

AUTHORS: frozenset[str] = frozenset({"human", "agent"})

_ID_MAX_ATTEMPTS = 3  # IR-05's own budget, mirrored from core/docs.py's _ID_MAX_ATTEMPTS

_THREAD_COLUMNS = (
    "id, owner, goal_id, doc_id, anchor_quote, anchor_prefix, anchor_suffix, resolved_at, created_at"
)
_THREAD_COLUMNS_QUALIFIED = (
    "ct.id, ct.owner, ct.goal_id, ct.doc_id, ct.anchor_quote, ct.anchor_prefix, ct.anchor_suffix, "
    "ct.resolved_at, ct.created_at"
)
_MESSAGE_COLUMNS = "id, author, body, created_at"


# --- validation (refuse, never silently correct — house style) ---------------------------------


def validate_message_body(value: object) -> str:
    """Non-blank after strip (the same emptiness test `core.field_rules.validate_title` applies
    to a title), at most `MAX_MESSAGE_BODY_BYTES` of UTF-8 — but, unlike a title, the STORED
    value is never stripped: a message is free text the same way a goal's `body` is
    (`core.field_rules.validate_body`'s own stance), and trimming a caller's own whitespace
    would be a silent correction this codebase's own §10-D2 rule refuses to make."""
    if not isinstance(value, str):
        raise ValidationError("body must be a string", field="body")
    if not value.strip():
        raise ValidationError("body must be non-blank after strip", field="body")
    size = len(value.encode("utf-8"))
    if size > MAX_MESSAGE_BODY_BYTES:
        raise ValidationError(
            f"body must be at most {MAX_MESSAGE_BODY_BYTES} bytes of UTF-8, got {size}",
            field="body",
            maximum=MAX_MESSAGE_BODY_BYTES,
        )
    return value


def validate_author(value: object) -> str:
    """Never a caller-decided field over the wire (module docstring) — this is the defence-in-
    depth check for a transport bug, not a real choice."""
    if not isinstance(value, str) or value not in AUTHORS:
        raise ValidationError(f"author must be one of {sorted(AUTHORS)}, got {value!r}", field="author")
    return value


def validate_anchor(value: object) -> tuple[str | None, str | None, str | None]:
    """`None` in -> `(None, None, None)` out (whole-card/whole-doc thread). A given anchor must
    be a mapping carrying a non-empty `quote` (there is no such thing as selecting zero
    characters on purpose); `prefix`/`suffix` default to `""` when omitted and may legitimately
    stay empty — a selection touching the very start or end of the body has nothing to
    disambiguate on that side (docs/COMMENTS_SPEC.md: "prefix/suffix may be empty strings")."""
    if value is None:
        return None, None, None
    if not isinstance(value, Mapping):
        raise ValidationError(
            "anchor must be an object with quote/prefix/suffix, or null", field="anchor"
        )

    quote = value.get("quote")
    if not isinstance(quote, str) or not quote:
        raise ValidationError(
            "anchor.quote is required and must be a non-empty string when anchor is given",
            field="anchor",
        )
    if len(quote) > MAX_ANCHOR_QUOTE_CHARS:
        raise ValidationError(
            f"anchor.quote must be at most {MAX_ANCHOR_QUOTE_CHARS} characters, got {len(quote)}",
            field="anchor",
            maximum=MAX_ANCHOR_QUOTE_CHARS,
        )

    prefix = value.get("prefix") if value.get("prefix") is not None else ""
    suffix = value.get("suffix") if value.get("suffix") is not None else ""
    if not isinstance(prefix, str):
        raise ValidationError("anchor.prefix must be a string", field="anchor")
    if not isinstance(suffix, str):
        raise ValidationError("anchor.suffix must be a string", field="anchor")
    if len(prefix) > MAX_ANCHOR_PREFIX_CHARS:
        raise ValidationError(
            f"anchor.prefix must be at most {MAX_ANCHOR_PREFIX_CHARS} characters, got {len(prefix)}",
            field="anchor",
            maximum=MAX_ANCHOR_PREFIX_CHARS,
        )
    if len(suffix) > MAX_ANCHOR_SUFFIX_CHARS:
        raise ValidationError(
            f"anchor.suffix must be at most {MAX_ANCHOR_SUFFIX_CHARS} characters, got {len(suffix)}",
            field="anchor",
            maximum=MAX_ANCHOR_SUFFIX_CHARS,
        )
    return quote, prefix, suffix


# --- small helpers -----------------------------------------------------------------------------


def _build_anchor(quote: str | None, prefix: str | None, suffix: str | None) -> CommentAnchor | None:
    if quote is None:
        return None
    return CommentAnchor(quote=quote, prefix=prefix or "", suffix=suffix or "")


def _build_thread(row: tuple, *, messages: tuple[CommentMessage, ...]) -> CommentThread:
    id_, owner, goal_id, doc_id, quote, prefix, suffix, resolved_at, created_at = row
    return CommentThread(
        id=id_,
        owner=owner,
        goal_id=goal_id,
        doc_id=doc_id,
        anchor=_build_anchor(quote, prefix, suffix),
        resolved_at=resolved_at,
        created_at=created_at,
        messages=messages,
    )


def _goal_exists(conn: psycopg.Connection, *, owner: str, goal_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM goals WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": goal_id}
        ).fetchone()
        is not None
    )


def _doc_exists(conn: psycopg.Connection, *, owner: str, doc_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM docs WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": doc_id}
        ).fetchone()
        is not None
    )


def _insert_message(
    conn: psycopg.Connection, *, owner: str, thread_id: str, author: str, body: str
) -> CommentMessage:
    """Same collision-retry shape as every generated id in this codebase
    (`core.docs.create`/`core.goals.create`), even though a fresh `thread_id` has zero existing
    messages to collide with in practice — the loop costs nothing and keeps every id-minting
    call site in this module identical rather than special-casing "the first message is safe"."""
    for _ in range(_ID_MAX_ATTEMPTS):
        new_id = _generate_id()
        row = conn.execute(
            f"""
            INSERT INTO comment_messages (thread_id, id, owner, author, body, created_at)
            VALUES (%(thread_id)s, %(id)s, %(owner)s, %(author)s, %(body)s, clock_timestamp())
            ON CONFLICT (thread_id, id) DO NOTHING
            RETURNING {_MESSAGE_COLUMNS}
            """,
            {"thread_id": thread_id, "id": new_id, "owner": owner, "author": author, "body": body},
        ).fetchone()
        if row is not None:
            return CommentMessage(id=row[0], author=row[1], body=row[2], created_at=row[3])
    raise ValidationError(
        f"could not generate a unique message id after {_ID_MAX_ATTEMPTS} attempts", field="id"
    )


def _messages_for_thread(conn: psycopg.Connection, *, owner: str, thread_id: str) -> tuple[CommentMessage, ...]:
    rows = conn.execute(
        f"SELECT {_MESSAGE_COLUMNS} FROM comment_messages"
        " WHERE owner = %(owner)s AND thread_id = %(id)s ORDER BY created_at",
        {"owner": owner, "id": thread_id},
    ).fetchall()
    return tuple(CommentMessage(id=r[0], author=r[1], body=r[2], created_at=r[3]) for r in rows)


def _attach_messages(
    conn: psycopg.Connection, *, owner: str, thread_rows: list[tuple]
) -> tuple[CommentThread, ...]:
    """Two statements total for a whole list read, not N+1 — every thread's messages in one
    `thread_id = ANY(...)` query, grouped in Python, the same shape `core.docs.py::goal()`'s own
    ancestor subquery avoids a per-row round trip for."""
    if not thread_rows:
        return ()
    thread_ids = [r[0] for r in thread_rows]
    rows = conn.execute(
        f"SELECT thread_id, {_MESSAGE_COLUMNS} FROM comment_messages"
        " WHERE owner = %(owner)s AND thread_id = ANY(%(ids)s) ORDER BY created_at",
        {"owner": owner, "ids": thread_ids},
    ).fetchall()
    by_thread: dict[str, list[CommentMessage]] = {tid: [] for tid in thread_ids}
    for thread_id, mid, author, body, created_at in rows:
        by_thread[thread_id].append(CommentMessage(id=mid, author=author, body=body, created_at=created_at))
    return tuple(_build_thread(row, messages=tuple(by_thread[row[0]])) for row in thread_rows)


# --- idem replay serialisation (core-internal; never the transport wire shape) ------------------
#
# `core.goals.py`'s own `_goal_response`/`_goal_from_response` pattern, applied to
# `CommentThread`/`CommentMessage`: a JSON-safe dict `idem.digest`/`idem.complete` can store, and
# the exact inverse for a `Replayed` read. Deliberately separate from `api/schemas.py`'s and
# `mcp/comments.py`'s own wire serialisers — this shape is core's private replay-ledger format,
# not a transport contract, and the two are free to diverge without either one noticing.


def _message_response(m: CommentMessage) -> dict:
    return {"id": m.id, "author": m.author, "body": m.body, "created_at": m.created_at.isoformat()}


def _message_from_response(d: Mapping[str, object]) -> CommentMessage:
    return CommentMessage(
        id=d["id"], author=d["author"], body=d["body"], created_at=_datetime.fromisoformat(d["created_at"])
    )


def _thread_response(t: CommentThread) -> dict:
    return {
        "id": t.id,
        "owner": t.owner,
        "goal_id": t.goal_id,
        "doc_id": t.doc_id,
        "anchor": (
            {"quote": t.anchor.quote, "prefix": t.anchor.prefix, "suffix": t.anchor.suffix}
            if t.anchor else None
        ),
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "created_at": t.created_at.isoformat(),
        "messages": [_message_response(m) for m in t.messages],
    }


def _thread_from_response(d: Mapping[str, object]) -> CommentThread:
    anchor = d.get("anchor")
    return CommentThread(
        id=d["id"],
        owner=d["owner"],
        goal_id=d["goal_id"],
        doc_id=d["doc_id"],
        anchor=CommentAnchor(quote=anchor["quote"], prefix=anchor["prefix"], suffix=anchor["suffix"])
        if anchor else None,
        resolved_at=_datetime.fromisoformat(d["resolved_at"]) if d["resolved_at"] else None,
        created_at=_datetime.fromisoformat(d["created_at"]),
        messages=tuple(_message_from_response(m) for m in d["messages"]),
    )


# --- create_thread -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadCreated:
    thread: CommentThread
    replayed: bool = False


def create_thread(
    conn: psycopg.Connection,
    *,
    owner: str,
    goal_id: str | None = None,
    doc_id: str | None = None,
    body: str,
    author: str,
    anchor: Mapping[str, object] | None = None,
    client_token: str | None = None,
) -> ThreadCreated:
    """A new thread and its first message, in one transaction (mirroring
    `core.docs.create`'s "one doc, revision 1, in one transaction"). Exactly one of
    `goal_id`/`doc_id`; the named target must exist for this owner (module docstring: FK gives
    integrity, this gives a clean `NotFound`)."""
    owner = _validate_owner(owner)
    if (goal_id is None) == (doc_id is None):
        raise ValidationError(
            "create_thread needs exactly one of goal_id or doc_id, not zero or both",
            field="goal_id,doc_id",
        )
    goal_id = _optional_str(goal_id, "goal_id")
    doc_id = _optional_str(doc_id, "doc_id")
    body = validate_message_body(body)
    author = validate_author(author)
    quote, prefix, suffix = validate_anchor(anchor)

    digest = None
    if client_token is not None:
        digest = idem.digest(
            {
                "owner": owner, "goal_id": goal_id, "doc_id": doc_id, "body": body, "author": author,
                "anchor_quote": quote, "anchor_prefix": prefix, "anchor_suffix": suffix,
            }
        )

    with conn.transaction():
        if client_token is not None:
            reservation = idem.reserve(conn, owner=owner, client_token=client_token, request_digest=digest)
            if isinstance(reservation, idem.Replayed):
                return ThreadCreated(thread=_thread_from_response(reservation.response), replayed=True)

        if goal_id is not None and not _goal_exists(conn, owner=owner, goal_id=goal_id):
            raise NotFound(f"no goal {goal_id!r} for owner {owner!r}", id=goal_id, owner=owner)
        if doc_id is not None and not _doc_exists(conn, owner=owner, doc_id=doc_id):
            raise NotFound(f"no doc {doc_id!r} for owner {owner!r}", id=doc_id, owner=owner)

        thread_row = None
        for _ in range(_ID_MAX_ATTEMPTS):
            new_id = _generate_id()
            thread_row = conn.execute(
                f"""
                INSERT INTO comment_threads
                       (id, owner, goal_id, doc_id, anchor_quote, anchor_prefix, anchor_suffix, created_at)
                VALUES (%(id)s, %(owner)s, %(goal_id)s, %(doc_id)s, %(quote)s, %(prefix)s, %(suffix)s, now())
                ON CONFLICT (id) DO NOTHING
                RETURNING {_THREAD_COLUMNS}
                """,
                {
                    "id": new_id, "owner": owner, "goal_id": goal_id, "doc_id": doc_id,
                    "quote": quote, "prefix": prefix, "suffix": suffix,
                },
            ).fetchone()
            if thread_row is not None:
                break
        if thread_row is None:
            raise ValidationError(
                f"could not generate a unique thread id after {_ID_MAX_ATTEMPTS} attempts", field="id"
            )

        message = _insert_message(conn, owner=owner, thread_id=thread_row[0], author=author, body=body)
        thread = _build_thread(thread_row, messages=(message,))

        if client_token is not None:
            idem.complete(conn, owner=owner, client_token=client_token, response=_thread_response(thread))

    return ThreadCreated(thread=thread, replayed=False)


# --- add_message ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageAdded:
    message: CommentMessage
    replayed: bool = False


def add_message(
    conn: psycopg.Connection,
    *,
    owner: str,
    thread_id: str,
    body: str,
    author: str,
    client_token: str | None = None,
) -> MessageAdded:
    """A reply into an existing thread — resolved or not; v1 carries no rule against replying to
    a resolved thread (docs/COMMENTS_SPEC.md names no such restriction, and re-opening a
    conversation by replying is a legitimate use the UI's own resolve/unresolve toggle already
    covers explicitly)."""
    owner = _validate_owner(owner)
    thread_id = _require_str(thread_id, "thread_id")
    body = validate_message_body(body)
    author = validate_author(author)

    digest = None
    if client_token is not None:
        digest = idem.digest({"owner": owner, "thread_id": thread_id, "body": body, "author": author})

    with conn.transaction():
        if client_token is not None:
            reservation = idem.reserve(conn, owner=owner, client_token=client_token, request_digest=digest)
            if isinstance(reservation, idem.Replayed):
                return MessageAdded(message=_message_from_response(reservation.response), replayed=True)

        exists = conn.execute(
            "SELECT 1 FROM comment_threads WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": thread_id},
        ).fetchone()
        if exists is None:
            raise NotFound(f"no comment thread {thread_id!r} for owner {owner!r}", id=thread_id, owner=owner)

        message = _insert_message(conn, owner=owner, thread_id=thread_id, author=author, body=body)

        if client_token is not None:
            idem.complete(conn, owner=owner, client_token=client_token, response=_message_response(message))

    return MessageAdded(message=message, replayed=False)


# --- set_resolved ----------------------------------------------------------------------------------


def set_resolved(conn: psycopg.Connection, *, owner: str, thread_id: str, resolved: bool) -> CommentThread:
    """Sets `resolved_at` to `clock_timestamp()` when `resolved` is true, clears it to `NULL`
    otherwise — no `client_token` (module docstring: idempotent by construction, nothing here for
    a replay ledger to protect). Returns the full thread, messages included, matching
    docs/COMMENTS_SPEC.md's wire shape for this route ("-> updated thread")."""
    owner = _validate_owner(owner)
    thread_id = _require_str(thread_id, "thread_id")
    if not isinstance(resolved, bool):
        raise ValidationError("resolved must be a boolean", field="resolved")

    with conn.transaction():
        row = conn.execute(
            f"""
            UPDATE comment_threads
               SET resolved_at = CASE WHEN %(resolved)s THEN clock_timestamp() ELSE NULL END
             WHERE owner = %(owner)s AND id = %(id)s
            RETURNING {_THREAD_COLUMNS}
            """,
            {"resolved": resolved, "owner": owner, "id": thread_id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no comment thread {thread_id!r} for owner {owner!r}", id=thread_id, owner=owner)
        messages = _messages_for_thread(conn, owner=owner, thread_id=thread_id)

    return _build_thread(row, messages=messages)


# --- list reads --------------------------------------------------------------------------------


def list_for_goal(conn: psycopg.Connection, *, owner: str, goal_id: str) -> tuple[CommentThread, ...]:
    """Every thread anchored to this goal, oldest-first threads, oldest-first messages. The goal
    itself must exist for this owner — an unknown or foreign id is `NotFound`, never a silent
    empty list a typo'd id could hide behind (the same stance `core.docs.get`/`goal` take)."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    if not _goal_exists(conn, owner=owner, goal_id=goal_id):
        raise NotFound(f"no goal {goal_id!r} for owner {owner!r}", id=goal_id, owner=owner)
    thread_rows = conn.execute(
        f"SELECT {_THREAD_COLUMNS} FROM comment_threads"
        " WHERE owner = %(owner)s AND goal_id = %(id)s ORDER BY created_at",
        {"owner": owner, "id": goal_id},
    ).fetchall()
    return _attach_messages(conn, owner=owner, thread_rows=thread_rows)


def list_for_doc(conn: psycopg.Connection, *, owner: str, doc_id: str) -> tuple[CommentThread, ...]:
    """The doc-side mirror of `list_for_goal`."""
    owner = _validate_owner(owner)
    doc_id = _require_str(doc_id, "doc_id")
    if not _doc_exists(conn, owner=owner, doc_id=doc_id):
        raise NotFound(f"no doc {doc_id!r} for owner {owner!r}", id=doc_id, owner=owner)
    thread_rows = conn.execute(
        f"SELECT {_THREAD_COLUMNS} FROM comment_threads"
        " WHERE owner = %(owner)s AND doc_id = %(id)s ORDER BY created_at",
        {"owner": owner, "id": doc_id},
    ).fetchall()
    return _attach_messages(conn, owner=owner, thread_rows=thread_rows)


def list_unresolved(conn: psycopg.Connection, *, owner: str) -> tuple[UnresolvedThread, ...]:
    """The agent worklist (docs/COMMENTS_SPEC.md: "every unresolved thread for the owner" when
    an MCP `comments` call names neither `goal_id` nor `doc`) — every thread with `resolved_at
    IS NULL`, each paired with a `CommentTarget` naming what it is about, so an agent never needs
    a second call per row just to orient itself. One statement for the threads-plus-targets read
    (a `LEFT JOIN` on both `goals` and `docs`, exactly one of which ever matches per row, per
    `comment_threads_one_target`), one more for their messages (`_attach_messages`)."""
    owner = _validate_owner(owner)
    rows = conn.execute(
        f"""
        SELECT {_THREAD_COLUMNS_QUALIFIED}, g.title, d.path, d.title
          FROM comment_threads ct
          LEFT JOIN goals g ON g.id = ct.goal_id AND g.owner = ct.owner
          LEFT JOIN docs d  ON d.id = ct.doc_id  AND d.owner = ct.owner
         WHERE ct.owner = %(owner)s AND ct.resolved_at IS NULL
         ORDER BY ct.created_at
        """,
        {"owner": owner},
    ).fetchall()
    if not rows:
        return ()

    thread_rows: list[tuple] = []
    targets: list[CommentTarget] = []
    for (
        id_, row_owner, goal_id, doc_id, quote, prefix, suffix, resolved_at, created_at,
        goal_title, doc_path, doc_title,
    ) in rows:
        thread_rows.append((id_, row_owner, goal_id, doc_id, quote, prefix, suffix, resolved_at, created_at))
        if goal_id is not None:
            targets.append(CommentTarget(kind="goal", id=goal_id, title=goal_title, path=None))
        else:
            targets.append(CommentTarget(kind="doc", id=doc_id, title=doc_title, path=doc_path))

    threads = _attach_messages(conn, owner=owner, thread_rows=thread_rows)
    return tuple(UnresolvedThread(thread=t, target=tg) for t, tg in zip(threads, targets))
