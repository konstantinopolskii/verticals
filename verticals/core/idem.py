"""Idempotent writes — IR-04's whole design in one file (`docs/IMPLEMENTATION.md` §0.3).
Satisfies AC-051, AC-052, AC-053, AC-198, AC-199; verified by `docs/E2E.md` S-29, S-30.

The table (`verticals/db/migrations/003_idempotency.sql`, WP-03) is keyed `(owner,
client_token)`, holds `request_digest` + `response_json`, and carries an index on `(owner,
created_at)` for the sweep below. Two functions are the whole surface a write-side caller
(WP-13's `create`) needs:

  * `reserve()` — the concurrency gate. `INSERT ... ON CONFLICT (owner, client_token) DO
    NOTHING RETURNING` is the one statement here that two identical *concurrent* tokens
    cannot both pass: Postgres holds the first inserter's row lock on that key until its
    transaction commits or rolls back, so a second, conflicting insert blocks rather than
    racing past a plain `SELECT`-then-`INSERT` the way a check-then-write implementation
    would (`docs/IMPLEMENTATION.md` §5, R3 — "a check-then-write implementation passes S-29
    and still double-writes under real retry"). The caller that wins gets `Reserved` and must
    perform its real write, then call `complete()`. Every other caller — concurrent or a
    later, sequential retry — gets back `Replayed` (same digest: hand back the stored
    response, write nothing) or an `IdempotencyConflict` (different digest: same token,
    different request — AC-052).
  * `complete()` — fills in the response body a `Reserved` caller promised. Split from
    `reserve()` because the response (it carries the write's generated id) does not exist
    until after the real write runs, and `response_json` is `NOT NULL` — so the reservation
    row goes in with a JSON `null` placeholder, and `complete()` overwrites it before the
    transaction that reserved it ever commits (IR-02: one transaction per request, `core/`
    never commits its own). Nothing outside this module ever observes the placeholder: a
    conflicting caller's own `INSERT` blocks until the reserving transaction resolves, and by
    the time it unblocks the row is either gone (rolled back) or carries the real response
    (committed) — never caught mid-way.

`reserve()` also runs AC-199's sweep, every call, before attempting the reservation: one
`DELETE` of the calling owner's own rows older than 24 hours, on the `(owner, created_at)`
index WP-03 built for exactly this. That is what makes a token whose prior row expired 25
hours ago look, to the `INSERT ... ON CONFLICT`, like a token nobody has used — a fresh
reservation, not a replay. Owner-scoped and one statement on purpose: scoped because an
unscoped sweep is the "stop-the-world delete" §5 R3 warns against (every owner's write would
pay for every other owner's backlog), one statement because that is what AC-199 asserts ("in
one indexed DELETE"). No scheduler, no cron, no timer — the sweep rides the write path, same
as every other mutating call.

`digest()` is the one other piece of public surface: sha256 over canonical JSON (sorted
keys, no whitespace) of whatever mapping the caller hands it. AC-051 pins the exact field set
this gets computed over for `create` — `{owner, title, vertical, anchor_date, parent_id,
body, color, tags, children}` — but assembling that mapping is `create()`'s job (WP-13), not
this module's: `digest()` itself is payload-shape-agnostic so any future mutator can reuse it.

IR-02 discipline throughout: every function here takes an open connection and never commits,
never opens a transaction of its own. `owner` is keyword-only, no default, on every function —
the same rule every other `core/` module follows (AC-013).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from verticals.core.errors import IdempotencyConflict, ValidationError

# No bound for a token's own length is pinned anywhere in the documents — chosen to match
# search.py's MAX_QUERY_CHARS-style generosity; flagged as an undocumented choice in this
# WP's result rather than silently invented.
MAX_CLIENT_TOKEN_CHARS = 200

# hashlib.sha256(...).hexdigest() is always exactly this shape. A request_digest that is not
# is a caller bug (hand-built, truncated, wrong algorithm) — refused up front rather than
# compared byte-by-byte against something that was never a real digest.
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# Owner-scoped, indexed on (owner, created_at) — AC-199's "one indexed DELETE". Runs before
# every reservation attempt, never on a schedule.
_SWEEP_SQL = """
    DELETE FROM idempotency
     WHERE owner = %(owner)s
       AND created_at < now() - interval '24 hours'
"""

# The concurrency gate. `placeholder` is JSON null — see module docstring on why the real
# response cannot be known yet and why that is safe.
_RESERVE_SQL = """
    INSERT INTO idempotency (owner, client_token, request_digest, response_json)
    VALUES (%(owner)s, %(client_token)s, %(digest)s, %(placeholder)s)
    ON CONFLICT (owner, client_token) DO NOTHING
    RETURNING owner, client_token
"""

_LOOKUP_SQL = """
    SELECT request_digest, response_json
      FROM idempotency
     WHERE owner = %(owner)s AND client_token = %(client_token)s
"""

_COMPLETE_SQL = """
    UPDATE idempotency
       SET response_json = %(response)s
     WHERE owner = %(owner)s AND client_token = %(client_token)s
"""


@dataclass(frozen=True)
class Reserved:
    """This call is the one that gets to write. Perform the real work, then call
    `complete(conn, owner=..., client_token=..., response=...)` before the transaction
    commits — every other caller waiting on this token is blocked until it does."""

    owner: str
    client_token: str


@dataclass(frozen=True)
class Replayed:
    """An earlier call already reserved and completed this token with the same digest.
    `response` is exactly what that call stored — return it verbatim; write nothing."""

    response: dict


def digest(payload: Mapping[str, object]) -> str:
    """sha256 hex of `payload`'s canonical JSON — sorted keys, no whitespace (AC-051). The
    caller normalises its own payload first (a `date` to its ISO string and so on); this
    function does no coercion of its own, so the same logical request always produces the
    same bytes to hash, and a value `json.dumps` cannot serialise fails here, loudly, rather
    than silently downstream."""
    if not isinstance(payload, Mapping):
        raise ValidationError("payload must be a mapping", field="payload")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _validate_client_token(client_token: str) -> str:
    if not isinstance(client_token, str) or not client_token:
        raise ValidationError(
            "client_token is required and must be a non-empty string", field="client_token"
        )
    if len(client_token) > MAX_CLIENT_TOKEN_CHARS:
        raise ValidationError(
            f"client_token must be at most {MAX_CLIENT_TOKEN_CHARS} characters, got "
            f"{len(client_token)}",
            field="client_token",
            maximum=MAX_CLIENT_TOKEN_CHARS,
        )
    return client_token


def _validate_digest(request_digest: str) -> str:
    if not isinstance(request_digest, str) or not _DIGEST_RE.match(request_digest):
        raise ValidationError(
            "request_digest must be a 64-character lowercase sha256 hex digest",
            field="request_digest",
        )
    return request_digest


def reserve(
    conn: psycopg.Connection, *, owner: str, client_token: str, request_digest: str
) -> Reserved | Replayed:
    """The concurrency gate. Returns `Reserved` to exactly one caller per live `(owner,
    client_token)` pair; every other caller — concurrent or a later, sequential retry — gets
    `Replayed` if the stored digest matches, or raises `IdempotencyConflict` if it does not.
    Sweeps `owner`'s rows older than 24 hours first (AC-199), so an expired row never causes
    a false replay or a false conflict. Never commits (IR-02) — the sweep, the reservation
    attempt, and (on conflict) the lookup are two or three statements on the connection the
    caller already opened, nothing more."""
    owner = _validate_owner(owner)
    client_token = _validate_client_token(client_token)
    request_digest = _validate_digest(request_digest)

    conn.execute(_SWEEP_SQL, {"owner": owner})

    won = conn.execute(
        _RESERVE_SQL,
        {
            "owner": owner,
            "client_token": client_token,
            "digest": request_digest,
            "placeholder": Jsonb(None),
        },
    ).fetchone()
    if won is not None:
        return Reserved(owner=owner, client_token=client_token)

    row = conn.execute(_LOOKUP_SQL, {"owner": owner, "client_token": client_token}).fetchone()
    if row is None:
        # Unreachable under IR-02's one-transaction-per-request rule: the row that made the
        # INSERT above report a conflict is either still live (the branch below) or was
        # rolled back in full (in which case the INSERT above would not have conflicted at
        # all). A plain RuntimeError, not one of errors.py's seven — this is not a caller
        # mistake for a transport to map, it is this file's own invariant failing.
        raise RuntimeError(
            f"idempotency row for owner={owner!r} client_token={client_token!r} vanished "
            "between the reservation attempt and its own lookup"
        )
    stored_digest, response_json = row
    if stored_digest != request_digest:
        raise IdempotencyConflict(
            "client_token reused with a different payload",
            owner=owner,
            client_token=client_token,
        )
    return Replayed(response=response_json)


def complete(
    conn: psycopg.Connection, *, owner: str, client_token: str, response: Mapping[str, object]
) -> None:
    """Fills in the response body for a token this same transaction just reserved. Called
    exactly once per `Reserved`, always before the transaction commits — see the module
    docstring for why that ordering is load-bearing, not just tidy."""
    owner = _validate_owner(owner)
    client_token = _validate_client_token(client_token)
    cur = conn.execute(
        _COMPLETE_SQL,
        {"owner": owner, "client_token": client_token, "response": Jsonb(dict(response))},
    )
    if cur.rowcount != 1:
        raise RuntimeError(
            f"complete(): no reservation row for owner={owner!r} client_token={client_token!r} "
            "— reserve() must be called first, on this same connection, in this same "
            "transaction"
        )
