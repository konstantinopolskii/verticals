"""Documents as first-class residents (D250, KK 2026-08-20, WP-1) — `014_docs.sql` end to end:
path/title/body validation, the append-only revision history, the folder tree read, restore, and
the link table derived from markdown link text in both bodies.

Three design facts carried over from the ruling, restated here because this file is where they
become code:

  * **The folder tree is just paths.** `docs.path` (e.g. `strategy/ai-native.md`) IS the
    hierarchy — there is no folder table and this module never builds one; `tree()` returns a
    flat, path-ordered list and a client groups it on `/` itself.
  * **Every save appends a revision. Nothing here is ever destructive.** `save()` and `restore()`
    both INSERT a new `doc_revisions` row and bump `docs.revision`; neither this module nor any
    other code path issues an `UPDATE`/`DELETE` against `doc_revisions` — restoring an old
    revision is spelled as copying its text forward as a NEW revision, never as rewinding history.
  * **Links live in the text; `goal_doc_links` is a derived cache of it, not a second truth.**
    `extract_links()` is the one place `goal:<id>`/`doc:<path>` markdown-link destinations are
    parsed; every writer that changes a body re-derives that body's own outbound rows from
    scratch (delete, then re-insert what the text says now) rather than diffing — rebuilding from
    the text can never drift from the text, incremental patching of a cache always eventually can.

IR-02 discipline throughout: every function takes an open connection and never commits; each
multi-statement body wraps itself in `with conn.transaction()` (a SAVEPOINT when the caller
already has one open, same as `core/tree.py`/`core/evidence.py`). `owner` is keyword-only with no
default on every function, matching every sibling `core/` module.

`core/goals.py` calls exactly one function here — `rewrite_goal_links`, from inside `update()`,
only when a body was actually written — and this module never imports `core/goals.py` back: one
direction, no cycle, the same rule `core/field_rules.py`'s own docstring states for its own split
from `goals.py`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from verticals.core.errors import NotFound, RevisionMismatch, ValidationError
from verticals.core.field_rules import (
    generate_id as _generate_id,
    is_control as _is_control,
    require_str as _require_str,
    validate_owner as _validate_owner,
)
from verticals.models import (
    Ancestor,
    Doc,
    DocLink,
    DocLinkAncestor,
    DocRevision,
    DocRevisionSummary,
    DocSummary,
    GoalLink,
)

# --- bounds ----------------------------------------------------------------------------------

MAX_PATH_CHARS = 512
MAX_DOC_TITLE_CHARS = 250  # same order of magnitude as core.field_rules.MAX_TITLE_CHARS (250)

# A Verticals doc is a full markdown file, not a goal's body — `core.field_rules.MAX_BODY_BYTES`
# (64 KiB) is a card-comment-length bound and would cut off an ordinary document. Half of
# `api/app.py`'s own outer request cap (1 MiB, `MAX_BODY_BYTES` there) leaves headroom for the
# JSON envelope, `path` and `title` in the same PATCH call while still letting a doc be genuinely
# long. Documented here rather than imported from `api/` — `core/` never imports a transport
# module (`tests/static/test_seam.py`), so the two numbers are related by comment, not by code.
MAX_DOC_BODY_BYTES = 512 * 1024

_ID_MAX_ATTEMPTS = 3  # IR-05's own budget, mirrored from core/goals.py's _ID_MAX_ATTEMPTS

COLUMNS = "id, owner, path, title, body, revision, created_at, updated_at"


# --- small helpers -----------------------------------------------------------------------------


def _to_doc(row: tuple) -> Doc:
    return Doc(*row)


def _validate_positive_int(value: object, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{field} must be an integer >= {minimum}", field=field)
    return value


# --- path/title/body validation (refuse, never silently correct — house style) -----------------


def validate_path(value: object) -> str:
    """Relative, `/`-separated, every segment non-empty and not `.`/`..`, no whitespace or
    control characters in any segment, must end `.md`, at most `MAX_PATH_CHARS` characters
    total. `path` is the doc's whole identity (unique per owner) — refused shapes are refused
    before any statement runs, same as every other `core/` validator."""
    if not isinstance(value, str) or not value:
        raise ValidationError("path is required and must be a non-empty string", field="path")
    if len(value) > MAX_PATH_CHARS:
        raise ValidationError(
            f"path must be at most {MAX_PATH_CHARS} characters, got {len(value)}",
            field="path",
            maximum=MAX_PATH_CHARS,
        )
    if value.startswith("/") or value.endswith("/"):
        raise ValidationError(
            "path must be relative, with no leading or trailing '/'", field="path"
        )
    for segment in value.split("/"):
        if not segment or segment in (".", ".."):
            raise ValidationError(
                f"path segment {segment!r} is invalid — each segment must be non-empty and not "
                f"'.' or '..'",
                field="path",
            )
        if any(ch.isspace() or _is_control(ch) for ch in segment):
            raise ValidationError(
                "path segments must carry no whitespace and no control characters", field="path"
            )
    if not value.endswith(".md"):
        raise ValidationError("path must end with '.md'", field="path")
    return value


def validate_doc_title(value: object) -> str | None:
    """`None` clears/omits the title (the column carries no `NOT NULL`); a given title must be
    non-blank after strip, at most `MAX_DOC_TITLE_CHARS`, and carry no control characters — the
    same shape `core.field_rules.validate_title` enforces for goals, minus the lower bound
    (a doc, unlike a goal, can legitimately have no title at all)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("title must be a string or null", field="title")
    stripped = value.strip()
    if not stripped:
        raise ValidationError(
            "title must be non-blank when given (use null for no title)", field="title"
        )
    if len(stripped) > MAX_DOC_TITLE_CHARS:
        raise ValidationError(
            f"title must be at most {MAX_DOC_TITLE_CHARS} characters, got {len(stripped)}",
            field="title",
            maximum=MAX_DOC_TITLE_CHARS,
        )
    if any(_is_control(ch) for ch in stripped):
        raise ValidationError("title must carry no control characters", field="title")
    return stripped


def validate_doc_body(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("body must be a string", field="body")
    size = len(value.encode("utf-8"))
    if size > MAX_DOC_BODY_BYTES:
        raise ValidationError(
            f"body must be at most {MAX_DOC_BODY_BYTES} bytes of UTF-8, got {size}",
            field="body",
            maximum=MAX_DOC_BODY_BYTES,
        )
    return value


# --- link parsing: one pure function, no I/O ----------------------------------------------------
#
# Matches a markdown link's DESTINATION only — `[label](goal:<id>)` / `[label](doc:<path>)` —
# never the label text, so a link whose visible text happens to contain the substring "goal:" is
# never mistaken for one. No whitespace is allowed inside the destination (`validate_path` already
# refuses a path containing one, and `core.field_rules.generate_id`'s alphabet never produces one
# either), which is what lets the destination be matched by "everything up to the next `)` or
# whitespace" with no ambiguity about where it ends.

_LINK_DEST_RE = re.compile(r"\]\(\s*(goal|doc):([^)\s]+)\s*\)")


@dataclass(frozen=True)
class ExtractedLinks:
    """`extract_links()`'s return shape — every distinct goal id and doc path a markdown body
    references, deduplicated (a body linking the same target twice contributes one entry)."""

    goal_ids: frozenset[str]
    doc_paths: frozenset[str]


def extract_links(text: str) -> ExtractedLinks:
    """Pure: no connection, no I/O, safe to call on text that was never saved anywhere. Existence
    (does this goal id or doc path actually resolve for the caller's owner) is deliberately not
    this function's job — `_rewrite_doc_links`/`rewrite_goal_links` below skip a dangling
    reference rather than erroring, and doing that here would need a connection this function is
    not given.

    Behaviour table (every row exercised by `tests/core/test_docs.py`):

        text                                             -> goal_ids       doc_paths
        "[the vision](goal:2VHolmfU)"                     {"2VHolmfU"}     {}
        "[baseline](doc:money/baseline.md)"                {}              {"money/baseline.md"}
        "[a](goal:X) and [b](doc:y.md) and [c](goal:X)"    {"X"}           {"y.md"}
        "no links here at all"                             {}              {}
        "[weird](goal: X)"  (space after colon)            {}              {}
        ""                                                 {}              {}
    """
    goal_ids: set[str] = set()
    doc_paths: set[str] = set()
    for kind, dest in _LINK_DEST_RE.findall(text or ""):
        (goal_ids if kind == "goal" else doc_paths).add(dest)
    return ExtractedLinks(goal_ids=frozenset(goal_ids), doc_paths=frozenset(doc_paths))


def _rewrite_doc_links(conn: psycopg.Connection, *, owner: str, doc_id: str, body: str) -> None:
    """This doc's own `source='doc'` rows, rebuilt from `body`'s current text. A goal id the
    text names that does not exist (or exists for a different owner) is silently skipped — a doc
    may legitimately reference a goal that was since deleted (module docstring)."""
    extracted = extract_links(body)
    with conn.transaction():
        conn.execute(
            "DELETE FROM goal_doc_links WHERE owner = %(owner)s AND doc_id = %(doc_id)s AND source = 'doc'",
            {"owner": owner, "doc_id": doc_id},
        )
        if extracted.goal_ids:
            conn.execute(
                """
                INSERT INTO goal_doc_links (owner, goal_id, doc_id, source)
                SELECT %(owner)s, g.id, %(doc_id)s, 'doc'
                  FROM goals g
                 WHERE g.owner = %(owner)s AND g.id = ANY(%(goal_ids)s)
                ON CONFLICT DO NOTHING
                """,
                {"owner": owner, "doc_id": doc_id, "goal_ids": list(extracted.goal_ids)},
            )


def rewrite_goal_links(conn: psycopg.Connection, *, owner: str, goal_id: str, body: str) -> None:
    """The goal-side mirror of `_rewrite_doc_links`, public because `core/goals.py::update` is
    the one caller outside this module (the module docstring's "surgical touch"). A doc path the
    text names that does not resolve for this owner is silently skipped, same reasoning as the
    doc side reversed."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    extracted = extract_links(body)
    with conn.transaction():
        conn.execute(
            "DELETE FROM goal_doc_links WHERE owner = %(owner)s AND goal_id = %(goal_id)s AND source = 'goal'",
            {"owner": owner, "goal_id": goal_id},
        )
        if extracted.doc_paths:
            conn.execute(
                """
                INSERT INTO goal_doc_links (owner, goal_id, doc_id, source)
                SELECT %(owner)s, %(goal_id)s, d.id, 'goal'
                  FROM docs d
                 WHERE d.owner = %(owner)s AND d.path = ANY(%(paths)s)
                ON CONFLICT DO NOTHING
                """,
                {"owner": owner, "goal_id": goal_id, "paths": list(extracted.doc_paths)},
            )


# --- create -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Created:
    doc: Doc


@dataclass(frozen=True)
class Updated:
    doc: Doc


def create(
    conn: psycopg.Connection, *, owner: str, path: str, title: str | None, body: str = ""
) -> Created:
    """One doc, revision 1, in one transaction. A duplicate `(owner, path)` is `ValidationError`
    naming `path` — not `NotFound`, not a silent overwrite (§10-D2's "refused, not silently
    corrected"). `body`'s own links are parsed and recorded immediately (module docstring: a
    fresh doc's initial text is still "the text", not a special case)."""
    owner = _validate_owner(owner)
    path = validate_path(path)
    title = validate_doc_title(title)
    body = validate_doc_body(body)

    for _ in range(_ID_MAX_ATTEMPTS):
        new_id = _generate_id()
        row = None
        try:
            with conn.transaction():
                row = conn.execute(
                    f"""
                    INSERT INTO docs (id, owner, path, title, body, revision, created_at, updated_at)
                    VALUES (%(id)s, %(owner)s, %(path)s, %(title)s, %(body)s, 1, now(), clock_timestamp())
                    ON CONFLICT (id) DO NOTHING
                    RETURNING {COLUMNS}
                    """,
                    {"id": new_id, "owner": owner, "path": path, "title": title, "body": body},
                ).fetchone()
                if row is not None:
                    conn.execute(
                        """
                        INSERT INTO doc_revisions (doc_id, owner, revision, path, title, body)
                        VALUES (%(doc_id)s, %(owner)s, 1, %(path)s, %(title)s, %(body)s)
                        """,
                        {"doc_id": new_id, "owner": owner, "path": path, "title": title, "body": body},
                    )
                    _rewrite_doc_links(conn, owner=owner, doc_id=new_id, body=body)
        except psycopg.errors.UniqueViolation as exc:
            # `ON CONFLICT (id)` only ever suppresses an id collision (handled below, by retry);
            # a UniqueViolation that still reaches here is necessarily `docs_path_unique_per_owner`.
            raise ValidationError(
                f"a doc already exists at path {path!r} for owner {owner!r}", field="path"
            ) from exc
        if row is not None:
            return Created(doc=_to_doc(row))
    raise ValidationError(f"could not generate a unique id after {_ID_MAX_ATTEMPTS} attempts", field="id")


# --- reads: get, get_by_path, tree ---------------------------------------------------------------


def get(conn: psycopg.Connection, *, owner: str, id: str) -> Doc:
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    row = conn.execute(
        f"SELECT {COLUMNS} FROM docs WHERE owner = %(owner)s AND id = %(id)s",
        {"owner": owner, "id": id},
    ).fetchone()
    if row is None:
        raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
    return _to_doc(row)


def get_by_path(conn: psycopg.Connection, *, owner: str, path: str) -> Doc:
    owner = _validate_owner(owner)
    path = _require_str(path, "path")
    row = conn.execute(
        f"SELECT {COLUMNS} FROM docs WHERE owner = %(owner)s AND path = %(path)s",
        {"owner": owner, "path": path},
    ).fetchone()
    if row is None:
        raise NotFound(f"no doc at path {path!r} for owner {owner!r}", path=path, owner=owner)
    return _to_doc(row)


def tree(conn: psycopg.Connection, *, owner: str) -> tuple[DocSummary, ...]:
    """Every doc's `(id, path, title, updated_at, revision)`, path order — the flat list a
    client derives its own folder tree from (module docstring: no folder table, no server-side
    grouping)."""
    owner = _validate_owner(owner)
    rows = conn.execute(
        "SELECT id, path, title, updated_at, revision FROM docs WHERE owner = %(owner)s ORDER BY path",
        {"owner": owner},
    ).fetchall()
    return tuple(DocSummary(id=r[0], path=r[1], title=r[2], updated_at=r[3], revision=r[4]) for r in rows)


# --- save (optimistic concurrency, append-only) ---------------------------------------------------


def save(
    conn: psycopg.Connection,
    *,
    owner: str,
    id: str,
    expected_revision: int,
    title: object = None,
    body: object = None,
    path: object = None,
) -> Updated:
    """`expected_revision` guards the write the same way `core.evidence.evidence_update` guards
    its own (docs/EVIDENCE.md §6.2's precedent): a mismatch is `RevisionMismatch` naming the
    CURRENT revision, so the caller re-reads instead of guessing. `title`/`body`/`path` default
    to `None`, meaning omitted — unlike `core.goals.update()`'s `_UNSET` sentinel, plain `None`
    is enough here because none of the three can ever be legitimately written as `None` through
    this call (`path` is never null, `body` is `NOT NULL DEFAULT ''`, and a title explicitly
    cleared to null is a `create()`-time decision, not a `save()`-time one — the shape this WP's
    own spec asked for). Every real write — whichever fields changed — lands as exactly one new
    `doc_revisions` row (S-44's "one write, one readback" reasoning, mirrored)."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    expected_revision = _validate_positive_int(expected_revision, "expected_revision", minimum=1)

    title_given = title is not None
    body_given = body is not None
    path_given = path is not None
    if title_given:
        title = validate_doc_title(title)
    if body_given:
        body = validate_doc_body(body)
    if path_given:
        path = validate_path(path)

    with conn.transaction():
        row = conn.execute(
            f"SELECT {COLUMNS} FROM docs WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
        current = _to_doc(row)
        if current.revision != expected_revision:
            raise RevisionMismatch(
                f"doc {id!r} is at revision {current.revision}, not {expected_revision} — re-read it",
                id=id,
                revision=current.revision,
                expected=expected_revision,
            )

        final_title = title if title_given else current.title
        final_body = body if body_given else current.body
        final_path = path if path_given else current.path
        new_revision = current.revision + 1

        try:
            updated_row = conn.execute(
                f"""
                UPDATE docs SET path = %(path)s, title = %(title)s, body = %(body)s,
                       revision = %(revision)s, updated_at = clock_timestamp()
                 WHERE owner = %(owner)s AND id = %(id)s
                RETURNING {COLUMNS}
                """,
                {
                    "owner": owner, "id": id, "path": final_path, "title": final_title,
                    "body": final_body, "revision": new_revision,
                },
            ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValidationError(
                f"a doc already exists at path {final_path!r} for owner {owner!r}", field="path"
            ) from exc

        doc = _to_doc(updated_row)
        conn.execute(
            """
            INSERT INTO doc_revisions (doc_id, owner, revision, path, title, body)
            VALUES (%(doc_id)s, %(owner)s, %(revision)s, %(path)s, %(title)s, %(body)s)
            """,
            {
                "doc_id": id, "owner": owner, "revision": new_revision,
                "path": final_path, "title": final_title, "body": final_body,
            },
        )
        if body_given:
            _rewrite_doc_links(conn, owner=owner, doc_id=id, body=final_body)

    return Updated(doc=doc)


# --- history, get_revision, restore ---------------------------------------------------------------


def history(conn: psycopg.Connection, *, owner: str, id: str) -> tuple[DocRevisionSummary, ...]:
    """`(revision, path, title, saved_at, body_length)` per stored revision, oldest first —
    never `body` (`DocRevisionSummary`'s own docstring). `length()` is Postgres's own codepoint
    count, the same unit `len(str)` uses in Python, so `body_length` matches whatever a caller
    would get from `len(get_revision(...).body)` without this call ever fetching the text."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    exists = conn.execute(
        "SELECT 1 FROM docs WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id}
    ).fetchone()
    if exists is None:
        raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
    rows = conn.execute(
        "SELECT revision, path, title, saved_at, length(body) FROM doc_revisions"
        " WHERE doc_id = %(id)s AND owner = %(owner)s ORDER BY revision",
        {"owner": owner, "id": id},
    ).fetchall()
    return tuple(
        DocRevisionSummary(revision=r[0], path=r[1], title=r[2], saved_at=r[3], body_length=r[4])
        for r in rows
    )


def get_revision(conn: psycopg.Connection, *, owner: str, id: str, revision: int) -> DocRevision:
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    revision = _validate_positive_int(revision, "revision", minimum=1)
    exists = conn.execute(
        "SELECT 1 FROM docs WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id}
    ).fetchone()
    if exists is None:
        raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
    row = conn.execute(
        "SELECT doc_id, revision, path, title, body, saved_at FROM doc_revisions"
        " WHERE doc_id = %(id)s AND owner = %(owner)s AND revision = %(revision)s",
        {"owner": owner, "id": id, "revision": revision},
    ).fetchone()
    if row is None:
        raise NotFound(f"no revision {revision} for doc {id!r}", id=id, revision=revision)
    return DocRevision(doc_id=row[0], revision=row[1], path=row[2], title=row[3], body=row[4], saved_at=row[5])


def restore(
    conn: psycopg.Connection, *, owner: str, id: str, revision: int, expected_revision: int
) -> Updated:
    """Copies `revision`'s own title+body forward as a NEW revision — `path` stays whatever it
    currently is (module docstring: restoring text is not the same act as undoing a rename).
    Guarded by the same `expected_revision` optimistic lock as `save()`, because a restore IS a
    save (one more `doc_revisions` row, one more revision bump), just one whose title/body come
    from history instead of from the caller directly."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    revision = _validate_positive_int(revision, "revision", minimum=1)
    expected_revision = _validate_positive_int(expected_revision, "expected_revision", minimum=1)

    with conn.transaction():
        row = conn.execute(
            f"SELECT {COLUMNS} FROM docs WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
        current = _to_doc(row)
        if current.revision != expected_revision:
            raise RevisionMismatch(
                f"doc {id!r} is at revision {current.revision}, not {expected_revision} — re-read it",
                id=id,
                revision=current.revision,
                expected=expected_revision,
            )

        old = conn.execute(
            "SELECT title, body FROM doc_revisions WHERE doc_id = %(id)s AND owner = %(owner)s"
            " AND revision = %(revision)s",
            {"owner": owner, "id": id, "revision": revision},
        ).fetchone()
        if old is None:
            raise NotFound(f"no revision {revision} for doc {id!r}", id=id, revision=revision)
        old_title, old_body = old
        new_revision = current.revision + 1

        updated_row = conn.execute(
            f"""
            UPDATE docs SET title = %(title)s, body = %(body)s, revision = %(revision)s,
                   updated_at = clock_timestamp()
             WHERE owner = %(owner)s AND id = %(id)s
            RETURNING {COLUMNS}
            """,
            {"owner": owner, "id": id, "title": old_title, "body": old_body, "revision": new_revision},
        ).fetchone()
        doc = _to_doc(updated_row)
        conn.execute(
            """
            INSERT INTO doc_revisions (doc_id, owner, revision, path, title, body)
            VALUES (%(doc_id)s, %(owner)s, %(revision)s, %(path)s, %(title)s, %(body)s)
            """,
            {
                "doc_id": id, "owner": owner, "revision": new_revision,
                "path": doc.path, "title": old_title, "body": old_body,
            },
        )
        _rewrite_doc_links(conn, owner=owner, doc_id=id, body=old_body)

    return Updated(doc=doc)


# --- delete -----------------------------------------------------------------------------------


def delete(conn: psycopg.Connection, *, owner: str, id: str) -> None:
    """Refused, `ValidationError`, naming every linked goal id, when any `goal_doc_links` row
    references this doc — either direction: the query below filters on `doc_id` alone, which
    both `source='doc'` and `source='goal'` rows carry regardless of which side declared the
    link, so one read covers "either direction" as the spec asks. Nothing else here is
    destructive beyond the one `DELETE` this function's whole job is."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")
    with conn.transaction():
        row = conn.execute(
            "SELECT 1 FROM docs WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no doc {id!r} for owner {owner!r}", id=id, owner=owner)
        linked = conn.execute(
            "SELECT DISTINCT goal_id FROM goal_doc_links WHERE owner = %(owner)s AND doc_id = %(id)s"
            " ORDER BY goal_id",
            {"owner": owner, "id": id},
        ).fetchall()
        if linked:
            linked_ids = [r[0] for r in linked]
            raise ValidationError(
                f"doc {id!r} is linked from goal(s) {linked_ids!r}; remove the link(s) before deleting",
                field="id",
                linked_goal_ids=linked_ids,
            )
        conn.execute("DELETE FROM docs WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id})


# --- link reads --------------------------------------------------------------------------------


def links_for_goal(conn: psycopg.Connection, *, owner: str, goal_id: str) -> tuple[DocLink, ...]:
    """Every doc this goal links to (`source='doc'`, the doc's own body named this goal) or is
    linked from (`source='goal'`, this goal's own body named the doc) — both directions,
    deduplicated by the table's own PK (module docstring: two facts, not two copies of one)."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    rows = conn.execute(
        """
        SELECT d.id, d.path, d.title, l.source
          FROM goal_doc_links l JOIN docs d ON d.id = l.doc_id AND d.owner = l.owner
         WHERE l.owner = %(owner)s AND l.goal_id = %(goal_id)s
         ORDER BY d.path, l.source
        """,
        {"owner": owner, "goal_id": goal_id},
    ).fetchall()
    return tuple(DocLink(doc_id=r[0], path=r[1], title=r[2], source=r[3]) for r in rows)


def links_for_goal_with_inherited(
    conn: psycopg.Connection, *, owner: str, goal_id: str, ancestors: Sequence[Ancestor]
) -> tuple[DocLink, ...]:
    """D251 (KK, 2026-08-20): docs "ghost" down a goal's ancestor chain, derived at READ time —
    zero new rows, zero new tables ("otherwise the agent will try to append the doc TO ALL which
    is not needed"). Returns `goal_id`'s own links first (`links_for_goal()`'s exact rows,
    `inherited_from=None`), then every doc linked — either direction — to an ANCESTOR, each
    carrying `inherited_from` (the nearest ancestor whose own link it rides down from).

    One statement over `goal_id = ANY([goal_id, *ancestor ids])` — this is the read the read-
    isolation budget at `GET /api/goals/{id}` counts (S-42, `tests/http/test_read_isolation.py`,
    held at 3): it REPLACES the plain `links_for_goal` call `routes_goals.py::get_goal` used to
    make, not a fourth statement added beside it.

    Dedupe, both rules resolved in Python because both are about `ancestors`'s given ORDER, which
    SQL has no way to see:
      * a doc `goal_id` links directly is OWN, and is excluded from the inherited list even when
        some ancestor also links it — own wins, every time, regardless of `source`;
      * a doc two different ancestors both link is attributed to whichever is CLOSEST.
    `ancestors` MUST be given NEAREST-FIRST (immediate parent, ..., root) for "closest" to fall
    out of "first match wins" below. `core.goals.goal()`'s own `ancestors` tuple is root-first
    (its own docstring), so every caller passes it reversed — `routes_goals.py::get_goal` and
    `mcp/tools.py::_handle_goal` both do."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    ancestor_ids = [a.id for a in ancestors]
    rows = conn.execute(
        """
        SELECT l.goal_id, d.id, d.path, d.title, l.source
          FROM goal_doc_links l JOIN docs d ON d.id = l.doc_id AND d.owner = l.owner
         WHERE l.owner = %(owner)s AND l.goal_id = ANY(%(ids)s)
         ORDER BY d.path, l.source
        """,
        {"owner": owner, "ids": [goal_id, *ancestor_ids]},
    ).fetchall()

    own: list[DocLink] = []
    own_doc_ids: set[str] = set()
    for link_goal_id, doc_id, path, title, source in rows:
        if link_goal_id == goal_id:
            own.append(DocLink(doc_id=doc_id, path=path, title=title, source=source))
            own_doc_ids.add(doc_id)

    ancestor_rank = {a.id: i for i, a in enumerate(ancestors)}
    ancestor_title = {a.id: a.title for a in ancestors}
    # doc_id -> (rank of the closest ancestor seen so far, that ancestor's id, path, title, source)
    nearest: dict[str, tuple[int, str, str, str | None, str]] = {}
    for link_goal_id, doc_id, path, title, source in rows:
        if link_goal_id == goal_id or doc_id in own_doc_ids:
            continue
        rank = ancestor_rank[link_goal_id]
        current = nearest.get(doc_id)
        if current is None or rank < current[0]:
            nearest[doc_id] = (rank, link_goal_id, path, title, source)

    inherited = tuple(
        DocLink(
            doc_id=doc_id, path=path, title=title, source=source,
            inherited_from=DocLinkAncestor(id=link_goal_id, title=ancestor_title[link_goal_id]),
        )
        for doc_id, (_rank, link_goal_id, path, title, source) in sorted(
            nearest.items(), key=lambda kv: kv[1][2]  # path, same order the SQL itself uses
        )
    )
    return tuple(own) + inherited


def links_for_doc(conn: psycopg.Connection, *, owner: str, doc_id: str) -> tuple[GoalLink, ...]:
    """The mirror of `links_for_goal` — every goal linked to or from this doc."""
    owner = _validate_owner(owner)
    doc_id = _require_str(doc_id, "doc_id")
    rows = conn.execute(
        """
        SELECT g.id, g.title, l.source
          FROM goal_doc_links l JOIN goals g ON g.id = l.goal_id AND g.owner = l.owner
         WHERE l.owner = %(owner)s AND l.doc_id = %(doc_id)s
         ORDER BY g.title, l.source
        """,
        {"owner": owner, "doc_id": doc_id},
    ).fetchall()
    return tuple(GoalLink(goal_id=r[0], title=r[1], source=r[2]) for r in rows)
