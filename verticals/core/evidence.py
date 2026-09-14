"""Agent evidence metadata — docs/EVIDENCE.md (WP-33) end to end: payload validation, the
effective-status formula, the `evidence_update` write and the `evidence_due` worklist.

Three design facts carried over from the spec, restated here because this file is where they
become code:

  * **The database decides freshness.** `goals.content_revision` is written only by
    `007_evidence.sql`'s trigger; nothing in this module (or anywhere else) ever sets it. This
    module only ever *reads* it — to check a caller's `expected_content_revision` and to stamp
    `verified_against_revision`.
  * **`stale` is computed, never stored.** The formula lives in exactly one SQL fragment below
    (`_EFFECTIVE_SQL`), used verbatim by every read that reports an effective status —
    `summaries_for`, `detail_for` and `due` cannot drift from each other because they share the
    literal text. §5's rule: `stale` only demotes `verified`; a `partial` with a revision
    mismatch stays `partial` (the weekly skill rechecks those regardless).
  * **An evidence write never touches `goals`.** Structural (own table, 007), but the S-41
    consequence is enforced here: an unknown id and a foreign owner's id both raise `NotFound`
    with the same message shape every other core/ module uses, *before* any revision is
    compared — `RevisionMismatch` (409) exists only for the caller's own goal and can never
    become an existence oracle.

IR-02 discipline throughout: every function takes an open connection and never commits;
`evidence_update` wraps its body in `with conn.transaction()`. `owner` is keyword-only with no
default on every function (AC-013; `tests/core/test_owner_scoping.py` globs this file too).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime as _datetime
from datetime import timezone as _timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from verticals.core import idem
from verticals.core.errors import NotFound, RevisionMismatch, ValidationError
from verticals.core.vertical import SCALE_KEYS

# --- bounds (docs/EVIDENCE.md §4; same spirit as 001_init.sql's tags_bounded) -------------------
STORED_STATUSES: frozenset[str] = frozenset({"unverified", "index_only", "partial", "verified"})
DUE_STATUSES: frozenset[str] = frozenset({"unverified", "index_only", "partial", "stale"})
MAX_SOURCES = 32
MAX_CLAIMS = 64
MAX_UNRESOLVED = 32
MAX_PAYLOAD_BYTES = 32 * 1024
DUE_DEFAULT_LIMIT = 50
DUE_MAX_LIMIT = 200

_IDENTITY_KEYS = frozenset({"project", "person", "disambiguation"})
_SOURCE_KEYS = frozenset({"id", "type", "ref", "date", "read_scope"})
_CLAIM_KEYS = frozenset({"id", "text", "source_ids"})
_PAYLOAD_KEYS = frozenset({"identity", "sources", "claims", "unresolved"})

# The §5 formula exists as ONE function; every reader that reports an effective status —
# this module's three, and `core/board.py`'s single-statement board — renders its SQL from
# here, so they cannot drift. `%(as_of)s` is the reference instant: now for a live answer, or
# `evidence_due`'s `due_before` ("what will be due by then").


def effective_sql(goal_alias: str, evidence_alias: str) -> str:
    """The §5 CASE, with the caller's own aliases for the goals row and the LEFT-JOINed
    `goal_evidence` row. The caller binds `%(as_of)s`."""
    g, e = goal_alias, evidence_alias
    return (
        f"CASE\n"
        f"  WHEN {e}.goal_id IS NULL THEN 'unverified'\n"
        f"  WHEN {e}.status <> 'verified' THEN {e}.status\n"
        f"  WHEN {e}.verified_against_revision <> {g}.content_revision THEN 'stale'\n"
        f"  WHEN {e}.review_after IS NOT NULL AND %(as_of)s >= {e}.review_after THEN 'stale'\n"
        f"  ELSE 'verified'\n"
        f"END"
    )


_EFFECTIVE_SQL = effective_sql("g", "e")


@dataclass(frozen=True)
class EvidenceUpdated:
    """`evidence_update`'s call envelope (the `Created`/`Updated` precedent, not `models.py`'s
    read vocabulary). `evidence` is the full row as `detail_for` would report it; `replayed`
    distinguishes a fresh write from an idempotency replay, same contract as `create`'s."""

    evidence: dict[str, Any]
    replayed: bool = False


@dataclass(frozen=True)
class DueResult:
    """`due`'s call envelope. `next_cursor` is None on the last page; otherwise an opaque token
    for the next call. `items` carry the slim §6.3 projection only — never `payload`."""

    items: tuple[dict[str, Any], ...]
    next_cursor: str | None


# --- small validators (house style: refuse, never silently correct) ------------------------------


def _validate_owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} is required and must be a non-empty string", field=field)
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or null", field=field)
    return value


def _optional_ts(value: object, field: str) -> _datetime | None:
    """Timestamps arrive as real, tz-aware `datetime`s — the transport parses ISO strings, this
    boundary refuses naive values (a naive stamp compared against timestamptz is a silent
    off-by-timezone bug, the worst kind)."""
    if value is None:
        return None
    if not isinstance(value, _datetime) or value.tzinfo is None:
        raise ValidationError(f"{field} must be a timezone-aware datetime or null", field=field)
    return value


def _validate_revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field} must be a non-negative integer", field=field)
    return value


def validate_payload(payload: object) -> dict[str, Any]:
    """§4's whole shape, refused field by field. Returns the payload unchanged (a plain dict) —
    no coercion, no defaulting; what the caller sent is what gets stored."""
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object", field="payload")

    unknown = sorted(set(payload) - _PAYLOAD_KEYS)
    if unknown:
        raise ValidationError(f"payload has unknown key(s): {unknown}", field="payload")

    identity = payload.get("identity")
    if identity is not None:
        if not isinstance(identity, dict):
            raise ValidationError("payload.identity must be an object", field="payload.identity")
        bad = sorted(set(identity) - _IDENTITY_KEYS)
        if bad:
            raise ValidationError(f"payload.identity has unknown key(s): {bad}", field="payload.identity")
        for key in _IDENTITY_KEYS:
            if key in identity and not isinstance(identity[key], str):
                raise ValidationError(f"payload.identity.{key} must be a string", field=f"payload.identity.{key}")

    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        raise ValidationError("payload.sources must be a list", field="payload.sources")
    if len(sources) > MAX_SOURCES:
        raise ValidationError(
            f"payload.sources accepts at most {MAX_SOURCES} entries, got {len(sources)}",
            field="payload.sources", maximum=MAX_SOURCES,
        )
    source_ids: set[str] = set()
    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValidationError(f"payload.sources[{i}] must be an object", field="payload.sources")
        bad = sorted(set(source) - _SOURCE_KEYS)
        if bad:
            raise ValidationError(f"payload.sources[{i}] has unknown key(s): {bad}", field="payload.sources")
        sid = _require_str(source.get("id"), f"payload.sources[{i}].id")
        for key in ("type", "ref", "date", "read_scope"):
            if key in source and not isinstance(source[key], str):
                raise ValidationError(f"payload.sources[{i}].{key} must be a string", field="payload.sources")
        if sid in source_ids:
            raise ValidationError(f"payload.sources has duplicate id {sid!r}", field="payload.sources")
        source_ids.add(sid)

    claims = payload.get("claims", [])
    if not isinstance(claims, list):
        raise ValidationError("payload.claims must be a list", field="payload.claims")
    if len(claims) > MAX_CLAIMS:
        raise ValidationError(
            f"payload.claims accepts at most {MAX_CLAIMS} entries, got {len(claims)}",
            field="payload.claims", maximum=MAX_CLAIMS,
        )
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValidationError(f"payload.claims[{i}] must be an object", field="payload.claims")
        bad = sorted(set(claim) - _CLAIM_KEYS)
        if bad:
            raise ValidationError(f"payload.claims[{i}] has unknown key(s): {bad}", field="payload.claims")
        _require_str(claim.get("id"), f"payload.claims[{i}].id")
        _require_str(claim.get("text"), f"payload.claims[{i}].text")
        refs = claim.get("source_ids", [])
        if not isinstance(refs, list):
            raise ValidationError(f"payload.claims[{i}].source_ids must be a list", field="payload.claims")
        for ref in refs:
            if not isinstance(ref, str) or ref not in source_ids:
                raise ValidationError(
                    f"payload.claims[{i}] references source id {ref!r}, which is not in payload.sources",
                    field="payload.claims",
                )

    unresolved = payload.get("unresolved", [])
    if not isinstance(unresolved, list):
        raise ValidationError("payload.unresolved must be a list", field="payload.unresolved")
    if len(unresolved) > MAX_UNRESOLVED:
        raise ValidationError(
            f"payload.unresolved accepts at most {MAX_UNRESOLVED} entries, got {len(unresolved)}",
            field="payload.unresolved", maximum=MAX_UNRESOLVED,
        )
    for i, item in enumerate(unresolved):
        if not isinstance(item, str):
            raise ValidationError(f"payload.unresolved[{i}] must be a string", field="payload.unresolved")

    size = len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise ValidationError(
            f"payload must be at most {MAX_PAYLOAD_BYTES} bytes canonical JSON, got {size}",
            field="payload", maximum=MAX_PAYLOAD_BYTES,
        )
    return payload


# --- reads ---------------------------------------------------------------------------------------


def _iso(value: _datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def summaries_for(
    conn: psycopg.Connection, *, owner: str, ids: list[str] | tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """The §6.1 three-field summary for each id — effective status (computed here, so callers
    never apply the formula themselves), `verified_at`, `review_after`. Ids the owner does not
    hold are simply absent from the result (a reader's ids come from a read that was already
    owner-scoped — nothing here to 404). A goal with no evidence row reports
    `{"status": "unverified", "verified_at": None, "review_after": None}`."""
    owner = _validate_owner(owner)
    if not ids:
        return {}
    rows = conn.execute(
        f"""
        SELECT g.id, {_EFFECTIVE_SQL} AS effective_status, e.verified_at, e.review_after
          FROM goals g
          LEFT JOIN goal_evidence e ON e.goal_id = g.id AND e.owner = g.owner
         WHERE g.owner = %(owner)s AND g.id = ANY(%(ids)s)
        """,
        {"owner": owner, "ids": list(ids), "as_of": _datetime.now(_timezone.utc)},
    ).fetchall()
    return {
        gid: {"status": status, "verified_at": _iso(verified_at), "review_after": _iso(review_after)}
        for gid, status, verified_at, review_after in rows
    }


def detail_for(conn: psycopg.Connection, *, owner: str, goal_id: str) -> dict[str, Any]:
    """The full evidence row for one goal — §6.1's `goal`-tool shape. Raises `NotFound` (same
    message shape as every other core/ module) for an unknown or foreign id. A goal with no
    evidence row reports effective `unverified` with null stored fields and an empty payload."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    row = conn.execute(
        f"""
        SELECT {_EFFECTIVE_SQL} AS effective_status,
               e.status, e.verified_at, e.source_cutoff_at, e.review_after,
               e.verified_against_revision, e.payload, e.evidence_revision,
               g.content_revision
          FROM goals g
          LEFT JOIN goal_evidence e ON e.goal_id = g.id AND e.owner = g.owner
         WHERE g.owner = %(owner)s AND g.id = %(goal_id)s
        """,
        {"owner": owner, "goal_id": goal_id, "as_of": _datetime.now(_timezone.utc)},
    ).fetchone()
    if row is None:
        raise NotFound(f"no goal {goal_id!r} for owner {owner!r}", id=goal_id, owner=owner)
    (effective, status, verified_at, source_cutoff_at, review_after,
     verified_against_revision, payload, evidence_revision, content_revision) = row
    return {
        "goal_id": goal_id,
        "status": effective,
        "stored_status": status,
        "verified_at": _iso(verified_at),
        "source_cutoff_at": _iso(source_cutoff_at),
        "review_after": _iso(review_after),
        "verified_against_revision": verified_against_revision,
        "evidence_revision": evidence_revision,
        "content_revision": content_revision,
        "payload": payload if payload is not None else {},
    }


# --- the due worklist ----------------------------------------------------------------------------


def _encode_cursor(review_after: _datetime | None, goal_id: str) -> str:
    raw = json.dumps({"r": _iso(review_after), "g": goal_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[_datetime | None, str]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        goal_id = raw["g"]
        review_after = _datetime.fromisoformat(raw["r"]) if raw["r"] is not None else None
        if not isinstance(goal_id, str) or not goal_id:
            raise ValueError("bad goal id")
        if review_after is not None and review_after.tzinfo is None:
            raise ValueError("naive timestamp")
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError("cursor is not a token this tool issued", field="cursor") from exc
    return review_after, goal_id


def due(
    conn: psycopg.Connection,
    *,
    owner: str,
    due_before: _datetime | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
    verticals: list[str] | tuple[str, ...] | None = None,
    limit: int = DUE_DEFAULT_LIMIT,
    cursor: str | None = None,
) -> DueResult:
    """§6.3: the review worklist, slim projection only. `due_before` is the reference instant
    the staleness clause is evaluated at — omit it for "due now", pass next Monday for "what
    will be due by then". Ordered `review_after ASC NULLS FIRST, goal_id`: NULLS FIRST because
    a goal with no evidence row has no `review_after` and is the most due thing there is. The
    cursor is keyset pagination over that exact pair — exhaustive and non-overlapping, no
    OFFSET drift when rows change between pages."""
    owner = _validate_owner(owner)
    as_of = _optional_ts(due_before, "due_before") or _datetime.now(_timezone.utc)

    wanted = list(statuses) if statuses is not None else sorted(DUE_STATUSES)
    if not wanted:
        raise ValidationError("statuses must not be empty", field="statuses")
    for s in wanted:
        if s not in DUE_STATUSES:
            raise ValidationError(
                f"statuses entries must be one of {sorted(DUE_STATUSES)}, got {s!r}", field="statuses"
            )

    scales = None
    if verticals is not None:
        scales = list(verticals)
        if not scales:
            raise ValidationError("verticals must not be empty", field="verticals")
        for h in scales:
            if h not in SCALE_KEYS:
                raise ValidationError(
                    f"verticals entries must be one of {sorted(SCALE_KEYS)}, got {h!r}", field="verticals"
                )

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= DUE_MAX_LIMIT:
        raise ValidationError(f"limit must be between 1 and {DUE_MAX_LIMIT}", field="limit", maximum=DUE_MAX_LIMIT)

    params: dict[str, Any] = {"owner": owner, "as_of": as_of, "statuses": wanted}
    clauses = ["t.effective_status = ANY(%(statuses)s)"]
    if scales is not None:
        clauses.append("t.vertical = ANY(%(verticals)s)")
        params["verticals"] = scales
    if cursor is not None:
        cur_ra, cur_id = _decode_cursor(_require_str(cursor, "cursor"))
        if cur_ra is None:
            # Still inside the NULLS-FIRST prefix: later null-review rows by id, then everything
            # with a real review_after.
            clauses.append("((t.review_after IS NULL AND t.id > %(cur_id)s) OR t.review_after IS NOT NULL)")
            params["cur_id"] = cur_id
        else:
            clauses.append("(t.review_after IS NOT NULL AND (t.review_after, t.id) > (%(cur_ra)s, %(cur_id)s))")
            params["cur_ra"] = cur_ra
            params["cur_id"] = cur_id
    params["limit_plus_one"] = limit + 1

    rows = conn.execute(
        f"""
        SELECT t.id, t.title, t.vertical, t.anchor_date, t.effective_status,
               t.verified_at, t.review_after, t.content_revision, t.verified_against_revision
          FROM (
            SELECT g.id, g.title, g.vertical, g.anchor_date, g.content_revision,
                   {_EFFECTIVE_SQL} AS effective_status,
                   e.verified_at, e.review_after, e.verified_against_revision
              FROM goals g
              LEFT JOIN goal_evidence e ON e.goal_id = g.id AND e.owner = g.owner
             WHERE g.owner = %(owner)s
          ) t
         WHERE {' AND '.join(clauses)}
         ORDER BY t.review_after ASC NULLS FIRST, t.id
         LIMIT %(limit_plus_one)s
        """,
        params,
    ).fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = tuple(
        {
            "goal_id": gid,
            "title": title,
            "vertical": vertical,
            "anchor_date": anchor_date.isoformat() if anchor_date else None,
            "effective_status": effective,
            "verified_at": _iso(verified_at),
            "review_after": _iso(review_after),
            "content_revision": content_revision,
            "verified_against_revision": verified_against_revision,
        }
        for gid, title, vertical, anchor_date, effective, verified_at, review_after,
            content_revision, verified_against_revision in rows
    )
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last[6], last[0])  # (review_after, id) — the sort pair
    return DueResult(items=items, next_cursor=next_cursor)


# --- the write -----------------------------------------------------------------------------------


def evidence_update(
    conn: psycopg.Connection,
    *,
    owner: str,
    goal_id: str,
    expected_content_revision: int,
    status: str,
    payload: dict[str, Any],
    expected_evidence_revision: int | None = None,
    verified_at: _datetime | None = None,
    source_cutoff_at: _datetime | None = None,
    review_after: _datetime | None = None,
    client_token: str | None = None,
) -> EvidenceUpdated:
    """§6.2, all six semantics: atomic (revision checks and the upsert inside one transaction,
    with the goals row share-locked so a concurrent content edit cannot slip between check and
    write), 409 on either revision mismatch with the current value in `detail`, byte-identical
    `NotFound` for unknown vs foreign ids, idempotent replay via `client_token`, and — by
    construction — never a write to `goals`.

    `verified_against_revision` is stamped from `expected_content_revision`, which the check
    below has just proven equal to the goal's live `content_revision`: what the agent verified
    against is what is current, or the call refuses."""
    owner = _validate_owner(owner)
    goal_id = _require_str(goal_id, "goal_id")
    expected_content_revision = _validate_revision(expected_content_revision, "expected_content_revision")
    if expected_evidence_revision is not None:
        expected_evidence_revision = _validate_revision(expected_evidence_revision, "expected_evidence_revision")
    if not isinstance(status, str) or status not in STORED_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(STORED_STATUSES)}, got {status!r}", field="status"
        )
    verified_at = _optional_ts(verified_at, "verified_at")
    source_cutoff_at = _optional_ts(source_cutoff_at, "source_cutoff_at")
    review_after = _optional_ts(review_after, "review_after")
    if status == "verified" and verified_at is None:
        raise ValidationError("verified_at is required when status is 'verified'", field="verified_at")
    payload = validate_payload(payload)

    digest = None
    if client_token is not None:
        digest = idem.digest(
            {
                "owner": owner,
                "goal_id": goal_id,
                "expected_content_revision": expected_content_revision,
                "expected_evidence_revision": expected_evidence_revision,
                "status": status,
                "verified_at": _iso(verified_at),
                "source_cutoff_at": _iso(source_cutoff_at),
                "review_after": _iso(review_after),
                "payload": payload,
            }
        )

    with conn.transaction():
        if client_token is not None:
            reservation = idem.reserve(conn, owner=owner, client_token=client_token, request_digest=digest)
            if isinstance(reservation, idem.Replayed):
                return EvidenceUpdated(evidence=reservation.response, replayed=True)

        # FOR SHARE: a concurrent content UPDATE on this goal (which needs the row's exclusive
        # lock) blocks until this transaction resolves — the revision proven here is still the
        # revision when the evidence row commits. NotFound BEFORE any revision talk: unknown and
        # foreign ids are indistinguishable, same message shape as every sibling module.
        row = conn.execute(
            "SELECT content_revision FROM goals WHERE id = %(id)s AND owner = %(owner)s FOR SHARE",
            {"id": goal_id, "owner": owner},
        ).fetchone()
        if row is None:
            raise NotFound(f"no goal {goal_id!r} for owner {owner!r}", id=goal_id, owner=owner)
        (current_content_revision,) = row
        if current_content_revision != expected_content_revision:
            raise RevisionMismatch(
                f"goal {goal_id!r} is at content revision {current_content_revision}, "
                f"not {expected_content_revision} — re-read it",
                goal_id=goal_id,
                content_revision=current_content_revision,
                expected=expected_content_revision,
            )

        existing = conn.execute(
            "SELECT evidence_revision FROM goal_evidence WHERE goal_id = %(id)s AND owner = %(owner)s FOR UPDATE",
            {"id": goal_id, "owner": owner},
        ).fetchone()
        if expected_evidence_revision is not None:
            current_ev = existing[0] if existing is not None else None
            if current_ev != expected_evidence_revision:
                raise RevisionMismatch(
                    f"evidence for goal {goal_id!r} is at revision {current_ev}, "
                    f"not {expected_evidence_revision} — re-read it",
                    goal_id=goal_id,
                    evidence_revision=current_ev,
                    expected=expected_evidence_revision,
                )

        conn.execute(
            """
            INSERT INTO goal_evidence
                   (goal_id, owner, status, verified_at, source_cutoff_at, review_after,
                    verified_against_revision, payload, evidence_revision, updated_at)
            VALUES (%(goal_id)s, %(owner)s, %(status)s, %(verified_at)s, %(source_cutoff_at)s,
                    %(review_after)s, %(varev)s, %(payload)s, 0, clock_timestamp())
            ON CONFLICT (goal_id) DO UPDATE SET
                   status = EXCLUDED.status,
                   verified_at = EXCLUDED.verified_at,
                   source_cutoff_at = EXCLUDED.source_cutoff_at,
                   review_after = EXCLUDED.review_after,
                   verified_against_revision = EXCLUDED.verified_against_revision,
                   payload = EXCLUDED.payload,
                   evidence_revision = goal_evidence.evidence_revision + 1,
                   updated_at = clock_timestamp()
            """,
            {
                "goal_id": goal_id,
                "owner": owner,
                "status": status,
                "verified_at": verified_at,
                "source_cutoff_at": source_cutoff_at,
                "review_after": review_after,
                "varev": expected_content_revision,
                "payload": Jsonb(payload),
            },
        )

        result = detail_for(conn, owner=owner, goal_id=goal_id)

        if client_token is not None:
            idem.complete(conn, owner=owner, client_token=client_token, response=result)

    return EvidenceUpdated(evidence=result, replayed=False)
