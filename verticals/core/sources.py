"""Sources (docs/design/sources.md): the answers the timer keeps about each source document, and what an answer means.

The check is in the document (`core/source_checks.py`); the table `source_state` (`018_sources.sql`) keeps what the
timer learned: the last answer, the failures in a row, the check the owner approved. Everything here takes an open
connection and the time, and never reads the clock itself, so a test can run a week of checks in a moment. `owner` is
keyword-only with no default, as in every `core/` module. Nothing here runs a check; `verticals/sources/` does, and
hands the answer to `record`.

Three rules live here and nowhere else:

  * **Two failures make red.** The first failure is looked at again after five minutes, quietly. A second one at least
    five minutes after the first turns the source red, "not answering since" the first. Any pass clears it. A run that
    comes sooner than five minutes after a failure (the agent's run-once) does not count as the second.
  * **Grey is never red.** A source waiting for approval, with no check, with a check nobody can read, not yet checked,
    or last checked over two hours ago ("not checked since", the Mac was asleep) is grey. Only a fresh answer is red.
  * **Every check runs only on approval, once.** `http`, `mcp`, `cmd`, `file` and `dns` need `approved_hash` to equal the
    hash of the check in the document now; only the app's own `connections` check runs without it. `approve` is the one
    writer of that hash, and no MCP tool calls it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import psycopg

from verticals.core import docs as core_docs
from verticals.core import source_checks as sc
from verticals.core.errors import NotFound, RevisionMismatch, ValidationError
from verticals.core.field_rules import require_str, validate_owner

EVERY = timedelta(hours=1)      # between two looks at a source that answers
RECHECK = timedelta(minutes=5)  # after a first failure, and the least between two failures that count
STALE = timedelta(hours=2)      # an answer older than this says nothing now: grey
LEASE = timedelta(minutes=10)   # how long a pass owns a check it is running
EXCERPT = 1500                  # the start of the body a tile draws as its page, as the Documents desk reads it
MAX_DETAIL = 200

OK, RED, GREY = "ok", "red", "grey"
WAITING, NEW, STALE_ANSWER, NO_CHECK, UNREADABLE = "waiting", "new", "stale", "no_check", "unreadable"
# The row of tiles puts what needs a look first.
_RANK = {RED: 0, WAITING: 1, UNREADABLE: 2, NO_CHECK: 2, STALE_ANSWER: 3, NEW: 4, OK: 5}

CONNECTIONS_PATH = sc.PREFIX + "connections.md"


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def one_line(text: object, limit: int = MAX_DETAIL) -> str:
    """One printable line: what an answer says about itself is read by the owner and by the agent, so it carries no
    control characters, no line breaks and no more than `limit` characters."""
    cleaned = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Result:
    """What one run of a check found: passed or not, one line of why, the number worth showing, how long it took. `raw`
    is what the check saw (the command's output, the page's start) for the agent's run-once to show beside the number;
    it is never stored."""

    ok: bool
    detail: str
    value: float | None = None
    ms: int | None = None
    raw: str = ""


@dataclass(frozen=True)
class Row:
    ran_hash: str | None
    approved_hash: str | None
    checked_at: datetime | None
    ok: bool | None
    detail: str
    value: float | None
    ms: int | None
    failures: int
    failing_since: datetime | None
    last_failure_at: datetime | None
    next_check_at: datetime
    leased_until: datetime | None


@dataclass(frozen=True)
class Source:
    """A document under `sources/` as the timer finds it: its check (or why there is none) and what it knows. `missing` says
    the document has no check block at all: then it is a plain document, and `sources` leaves it out."""

    id: str
    path: str
    title: str | None
    body: str
    updated_at: datetime
    revision: int
    check: sc.Check | None
    error: str | None
    missing: bool
    row: Row | None

    @property
    def approved(self) -> bool:
        return bool(self.check and self.row and self.row.approved_hash == self.check.hash)

    @property
    def waiting(self) -> bool:
        return bool(self.check and self.check.gated and not self.approved)


@dataclass(frozen=True)
class View:
    """A source as the Inbox and the agent read it. `status` is ok, red or grey; for grey, `why` says which grey."""

    id: str
    path: str
    title: str | None
    kind: str | None
    where: str | None
    status: str
    why: str | None
    detail: str
    value: float | None
    ms: int | None
    checked_at: datetime | None
    since: datetime | None
    needs_approval: bool
    approved: bool
    check_hash: str | None
    summary: str | None
    error: str | None
    updated_at: datetime
    failures: int = 0
    next_check_at: datetime | None = None
    excerpt: str = ""
    body: str | None = None
    # The tools of the owner's other servers that read this source for the morning report (the check block's `reads`), and
    # where the last morning report stopped reading it, as an ISO time with its offset (docs/design/morning-quality.md).
    reads: tuple[str, ...] = ()
    cutoff: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id, "path": self.path, "title": self.title, "kind": self.kind, "where": self.where,
            "status": self.status, "why": self.why, "detail": self.detail, "value": self.value, "ms": self.ms,
            "checked_at": _iso(self.checked_at), "since": _iso(self.since), "needs_approval": self.needs_approval,
            "approved": self.approved, "check_hash": self.check_hash, "summary": self.summary, "error": self.error,
            "updated_at": _iso(self.updated_at), "failures": self.failures, "next_check_at": _iso(self.next_check_at),
            "reads": list(self.reads), "cutoff": self.cutoff,
        }
        if self.excerpt:
            out["excerpt"] = self.excerpt
        if self.body is not None:
            out["body"] = self.body
        return out


@dataclass(frozen=True)
class Recorded:
    """What `record` did: the failures now in a row and whether this answer changed the colour."""

    failures: int
    turned_red: bool
    recovered: bool
    next_check_at: datetime


# --- reading ---------------------------------------------------------------------------------------------------------

_SELECT = """
    SELECT d.id, d.path, d.title, d.body, d.updated_at, d.revision,
           s.doc_id IS NOT NULL, s.ran_hash, s.approved_hash, s.checked_at, s.ok, s.detail, s.value, s.ms, s.failures,
           s.failing_since, s.last_failure_at, s.next_check_at, s.leased_until
      FROM docs d LEFT JOIN source_state s ON s.doc_id = d.id AND s.owner = d.owner
     WHERE d.owner = %(owner)s AND starts_with(d.path, %(prefix)s)
"""


def _source(r: tuple) -> Source:
    row = Row(*r[7:]) if r[6] else None
    try:
        check, error, missing = sc.parse_check(r[3], app=True), None, False
    except ValidationError as exc:
        check, error, missing = None, exc.message.removeprefix("check: "), bool(exc.detail.get("missing"))
    return Source(id=r[0], path=r[1], title=r[2], body=r[3], updated_at=r[4], revision=r[5], check=check,
                  error=error, missing=missing, row=row)


def sources(conn: psycopg.Connection, *, owner: str) -> list[Source]:
    """Every source: a document under `sources/` with a check block, path order. A document there without one (a transcript
    saved before sources existed, a note) is a plain document, not a source: not listed, not checked, not in the Inbox's row,
    not in the report. `find` still finds it by its id, so the agent's tool can give it a check and make it a source."""
    owner = validate_owner(owner)
    rows = conn.execute(_SELECT + " ORDER BY d.path", {"owner": owner, "prefix": sc.PREFIX}).fetchall()
    return [s for s in (_source(r) for r in rows) if not s.missing]


def find(conn: psycopg.Connection, *, owner: str, ref: str) -> Source:
    """One source by its document's id or its path (a trailing `.md` reads as a path, as `doc_link` reads it)."""
    owner = validate_owner(owner)
    ref = require_str(ref, "id")
    column = "d.path" if ref.endswith(".md") else "d.id"
    r = conn.execute(_SELECT + f" AND {column} = %(ref)s", {"owner": owner, "prefix": sc.PREFIX, "ref": ref}).fetchone()
    if r is None:
        raise NotFound(f"no source {ref!r} for owner {owner!r}", id=ref, owner=owner)
    return _source(r)


# --- what an answer means --------------------------------------------------------------------------------------------


def judge(source: Source, now: datetime) -> tuple[str, str | None]:
    """ok, red or grey, and for grey which grey. Pure: the clock is the caller's."""
    check, row = source.check, source.row
    if check is None:
        return GREY, NO_CHECK if source.missing else UNREADABLE
    if source.waiting:
        return GREY, WAITING
    if row is None or row.checked_at is None or row.ran_hash != check.hash:
        return GREY, NEW
    if now - row.checked_at > STALE:
        return GREY, STALE_ANSWER
    return (RED, None) if row.failures >= 2 else (OK, None)


def view(source: Source, now: datetime, *, excerpt: bool = False, body: bool = False) -> View:
    status, why = judge(source, now)
    row, check = source.row, source.check
    answered = row is not None and check is not None and row.ran_hash == check.hash and row.checked_at is not None
    return View(
        id=source.id, path=source.path, title=source.title,
        kind=check.kind if check else None, where=check.where if check else None,
        status=status, why=why,
        detail=row.detail if answered else "", value=row.value if answered else None, ms=row.ms if answered else None,
        checked_at=row.checked_at if answered else None,
        since=row.failing_since if status == RED else None,
        needs_approval=source.waiting, approved=source.approved,
        check_hash=check.hash if check else None, summary=check.summary() if check else None, error=source.error,
        updated_at=source.updated_at, failures=row.failures if answered else 0,
        next_check_at=row.next_check_at if answered and not source.waiting else None,
        excerpt=source.body[:EXCERPT] if excerpt else "", body=source.body if body else None,
        reads=tuple(check.fields.get("reads") or ()) if check else (),
    )


def views(
    conn: psycopg.Connection, *, owner: str, now: datetime, excerpt: bool = True, cutoffs: Mapping[str, str] | None = None
) -> list[View]:
    """Every source with its state, what needs a look first: red, then waiting, then the rest, then by name. The tiles
    draw each source's page, so they ask for the excerpt; the agent's list does not need it. `cutoffs` is where the last
    morning report stopped reading each source, by the source's id (`core/morning.py::cutoffs`)."""
    out = [view(s, now, excerpt=excerpt) for s in sources(conn, owner=owner)]
    if cutoffs:
        out = [replace(v, cutoff=cutoffs[v.id]) if v.id in cutoffs else v for v in out]
    out.sort(key=lambda v: (_RANK[v.why or v.status], (v.title or v.path).lower(), v.path))
    return out


# --- running ---------------------------------------------------------------------------------------------------------


def due(source: Source, now: datetime) -> bool:
    """Whether the timer should run this source's check now: it has one, it may run (one the agent wrote only when the owner
    approved it), and either its time has come or the check changed since the last answer."""
    check, row = source.check, source.row
    if check is None or source.waiting:
        return False
    if row is None:
        return True
    if row.leased_until is not None and row.leased_until > now:
        return False  # a pass is running it
    return row.next_check_at <= now or row.ran_hash != check.hash


def claim(conn: psycopg.Connection, *, owner: str, source: Source, now: datetime, lease: timedelta = LEASE) -> bool:
    """Take the right to run this check: one statement that sets the lease only if nobody has set it since the pass read
    the row. Whoever updates first runs the check; the other gets False. A lease that ran out (a pass that died) is
    taken over the same way."""
    owner = validate_owner(owner)
    expected = source.row.leased_until if source.row else None
    got = conn.execute(
        """
        INSERT INTO source_state (doc_id, owner, next_check_at, leased_until)
        VALUES (%(id)s, %(owner)s, %(now)s, %(lease)s)
        ON CONFLICT (doc_id) DO UPDATE SET leased_until = EXCLUDED.leased_until
         WHERE source_state.leased_until IS NOT DISTINCT FROM %(expected)s
        RETURNING doc_id
        """,
        {"id": source.id, "owner": owner, "now": now, "lease": now + lease, "expected": expected},
    ).fetchone()
    return got is not None


def record(
    conn: psycopg.Connection, *, owner: str, doc_id: str, check_hash: str, result: Result, now: datetime
) -> Recorded:
    """Keep one answer and apply the two-failures rule. An answer to a different check than the one before it starts the
    count again."""
    owner = validate_owner(owner)
    with conn.transaction():
        prior = conn.execute(
            "SELECT ran_hash, failures, failing_since, last_failure_at FROM source_state"
            " WHERE doc_id = %(id)s AND owner = %(owner)s FOR UPDATE",
            {"id": doc_id, "owner": owner},
        ).fetchone()
        same = prior is not None and prior[0] == check_hash
        failures, since, last = (prior[1], prior[2], prior[3]) if same else (0, None, None)
        before = failures
        if result.ok:
            failures, since, last, nxt = 0, None, None, now + EVERY
        elif failures == 0:
            failures, since, last, nxt = 1, now, now, now + RECHECK
        elif now - last >= RECHECK:
            failures, last, nxt = failures + 1, now, now + EVERY
        else:
            nxt = last + RECHECK  # too soon to be a second failure: look again when five minutes have gone
        conn.execute(
            """
            INSERT INTO source_state (doc_id, owner, ran_hash, checked_at, ok, detail, value, ms, failures,
                                      failing_since, last_failure_at, next_check_at, leased_until)
            VALUES (%(id)s, %(owner)s, %(hash)s, %(now)s, %(ok)s, %(detail)s, %(value)s, %(ms)s, %(failures)s,
                    %(since)s, %(last)s, %(next)s, NULL)
            ON CONFLICT (doc_id) DO UPDATE SET ran_hash = EXCLUDED.ran_hash, checked_at = EXCLUDED.checked_at,
                ok = EXCLUDED.ok, detail = EXCLUDED.detail, value = EXCLUDED.value, ms = EXCLUDED.ms,
                failures = EXCLUDED.failures, failing_since = EXCLUDED.failing_since,
                last_failure_at = EXCLUDED.last_failure_at, next_check_at = EXCLUDED.next_check_at,
                leased_until = NULL
            """,
            {"id": doc_id, "owner": owner, "hash": check_hash, "now": now, "ok": result.ok,
             "detail": one_line(result.detail), "value": result.value, "ms": result.ms, "failures": failures,
             "since": since, "last": last, "next": nxt},
        )
    return Recorded(failures=failures, turned_red=failures >= 2 > before, recovered=result.ok and before >= 2,
                    next_check_at=nxt)


def wake(conn: psycopg.Connection, *, owner: str, doc_id: str, now: datetime) -> None:
    """A source document was just written by the agent's tool: the source is due at the next pass, and the bell rings (the
    trigger on this table), which a document's save alone does not. The open app reads the Sources row again when it rings,
    so a source waiting for approval appears at once instead of when the Inbox is next opened."""
    owner = validate_owner(owner)
    conn.execute(
        """
        INSERT INTO source_state (doc_id, owner, next_check_at) VALUES (%(id)s, %(owner)s, %(now)s)
        ON CONFLICT (doc_id) DO UPDATE SET next_check_at = LEAST(source_state.next_check_at, EXCLUDED.next_check_at)
        """,
        {"id": doc_id, "owner": owner, "now": now},
    )


# --- approving -------------------------------------------------------------------------------------------------------


def approve(conn: psycopg.Connection, *, owner: str, doc_id: str, check_hash: str, now: datetime) -> View:
    """The owner pressed Approve on the check they were shown. It is refused if the check in the document has moved
    since (the owner approves what they read, nothing else), and the source is made due now. Only the HTTP route calls
    this; no MCP tool does, so the agent can propose a check and never approve its own."""
    owner = validate_owner(owner)
    source = find(conn, owner=owner, ref=require_str(doc_id, "id"))
    if source.check is None:
        raise ValidationError(f"this source has no check to approve: {source.error}", field="check")
    if not source.check.gated:
        raise ValidationError("this check is the app's own and needs no approval", field="check")
    if source.check.hash != check_hash:
        raise RevisionMismatch("the check has changed since it was shown: read it again", id=source.id,
                               check_hash=source.check.hash)
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO source_state (doc_id, owner, approved_hash, approved_at, next_check_at)
            VALUES (%(id)s, %(owner)s, %(hash)s, %(now)s, %(now)s)
            ON CONFLICT (doc_id) DO UPDATE SET approved_hash = EXCLUDED.approved_hash,
                approved_at = EXCLUDED.approved_at, next_check_at = EXCLUDED.next_check_at
            """,
            {"id": source.id, "owner": owner, "hash": check_hash, "now": now},
        )
    return view(find(conn, owner=owner, ref=source.id), now, excerpt=True)


# --- the one source the app writes itself ----------------------------------------------------------------------------

_CONNECTIONS = sc.Check.from_dict({"kind": "connections"}, app=True)


def ensure_connections(conn: psycopg.Connection, *, owner: str) -> str:
    """The document called Connections, made once when the app is told to ask Claude Code which of its MCP servers
    answer. Returns its id. A document already there (the owner's, or an agent's) is left as it is."""
    owner = validate_owner(owner)
    try:
        return core_docs.get_by_path(conn, owner=owner, path=CONNECTIONS_PATH).id
    except NotFound:
        pass
    body = sc.build_body(
        gives="Which of the agent's tools answer: every MCP server Claude Code knows, as `claude mcp list` reports it.",
        how="Read this source before the others. A server that does not answer is a source the report cannot read.",
        since="Every hour.",
        check=_CONNECTIONS,
        fixes=[],
    )
    try:
        return core_docs.create(conn, owner=owner, path=CONNECTIONS_PATH, title="Connections", body=body).doc.id
    except ValidationError:  # made by someone between the look and the write
        return core_docs.get_by_path(conn, owner=owner, path=CONNECTIONS_PATH).id
