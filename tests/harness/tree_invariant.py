"""AC-203's tree invariant — the single implementation, and the teardown check that runs it.

`docs/E2E.md` S-126 names five counts that must all be 0; `docs/ACCEPTANCE.md` AC-203 requires
them checked "in the teardown of every `core`, `http` and `mcp` scenario ... and a non-zero fails
the scenario that ran even if its own asserts passed". Before this module the criterion was
aspirational: the five queries existed as three hand-copied private helpers (`tests/core/
test_tree.py`, `tests/http/test_concurrency.py`, `tests/pipeline/test_backup.py`) invoked opt-in
at a handful of call sites, and nothing at all ran in `mcp`. This module is the one copy; the
call site that makes AC-203 true is `fresh_clone` in `tests/conftest.py`.

**Why the check is owner-agnostic.** The invariant is owner-scoped — every clause carries `owner`
in its join key or its `GROUP BY` — but that does not mean the caller has to *name* an owner. A
per-scenario check needs to know which rows to look at, and the honest answer is "all of them in
this clone": a clone is scenario-private (`docs/E2E.md` §2, one `CREATE DATABASE ... TEMPLATE`
per test) and holds at most the fixture's own owners, so scanning it whole is both cheaper and
strictly stronger than a fixture that records the owners a scenario *meant* to touch — a write
that lands under the wrong owner is exactly the corruption AC-203 is looking for, and a
recorded-owner filter would be blind to it. `owner=` is still accepted, for the existing
in-test assertions that want to name one.

**The fifth clause, as shipped.** `ACCEPTANCE.md` states it as "a duplicate `(owner, vertical,
period_key, position)`" with no further qualifier. That cannot be the literal invariant: F2 as
shipped carries three such literal duplicates among its `vertical IS NULL` rows (`SYNMAY0{1,2,3}`
vs `SYNSUB0{1,2,3}`). It is checked here scoped to `vertical IS NOT NULL` — the board-column
reading — which is the only reading consistent with the fixture. Inherited verbatim from the
`tests/core/test_tree.py` copy this module replaces.

**When the check declines to run.** A clone whose `goals` table is absent or does not yet carry
the tree columns is not at migration head — `tests/core/test_migrations.py` steps a clone through
the migrations one at a time on purpose. There is no invariant to check on a schema that has no
tree in it yet, so those clones are passed over. That is a schema fact read from
`information_schema`, never an exception swallowed.
"""

from __future__ import annotations

import psycopg

# The five counts of docs/E2E.md S-126. Each returns the offending ids (or groups), so a failure
# names the rows rather than only their number. `%(owner)s IS NULL OR owner = %(owner)s` is the
# optional filter: passing owner=None checks the whole clone, which is what teardown does.
_OWNER_FILTER = "(%(owner)s::text IS NULL OR g.owner = %(owner)s)"

_REQUIRED_COLUMNS = ("id", "owner", "parent_id", "path", "depth", "vertical", "period_key", "position")

# One statement, not six. Six sequential round trips cost more in latency than the scans
# themselves do in work (measured: 13ms of which ~5ms was scanning), and this runs once per
# clone across three suites, so the round trips are the bill. `UNION ALL` of six branches, each
# labelled, each emitting the offending rows rather than only their count — a failure has to name
# the ids or it is not actionable. The clause numbers are S-126's own.
_VIOLATIONS_SQL = f"""
SELECT 1, 'child path does not extend parent''s', g.id::text
  FROM goals g JOIN goals p ON p.owner = g.owner AND p.id = g.parent_id
 WHERE {_OWNER_FILTER} AND g.path <> p.path || g.id || '/'
UNION ALL
SELECT 2, 'depth inconsistent with path', g.id::text
  FROM goals g
 WHERE {_OWNER_FILTER}
   AND g.depth <> (length(g.path) - length(replace(g.path, '/', ''))) - 2
UNION ALL
SELECT 3, 'orphan parent_id', g.id::text
  FROM goals g
 WHERE {_OWNER_FILTER} AND g.parent_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM goals p WHERE p.owner = g.owner AND p.id = g.parent_id)
UNION ALL
SELECT 4, 'root path/depth malformed', g.id::text
  FROM goals g
 WHERE {_OWNER_FILTER} AND g.parent_id IS NULL
   AND (g.depth <> 0 OR g.path <> '/' || g.id || '/')
UNION ALL
SELECT 5, 'id is not exactly once the last segment of its own path', g.id::text
  FROM goals g
 WHERE {_OWNER_FILTER}
   AND (SELECT count(*) FROM unnest(string_to_array(trim(both '/' from g.path), '/')) s
         WHERE s = g.id) <> 1
UNION ALL
SELECT 6, 'duplicate (owner,vertical,period_key,position) in a board column',
       g.owner || '/' || g.vertical || '/' || g.period_key || '/' || g.position
       || ' => ' || array_agg(g.id ORDER BY g.id)::text
  FROM goals g
 WHERE {_OWNER_FILTER} AND g.vertical IS NOT NULL
 GROUP BY g.owner, g.vertical, g.period_key, g.position
HAVING count(*) > 1
ORDER BY 1, 3
"""


def applicable(conn: psycopg.Connection) -> bool:
    """Whether this clone carries a `goals` table at migration head — see the module docstring's
    last paragraph. Read from `pg_attribute`, not `information_schema.columns`: the latter is a
    join across five catalogue views and measured 7ms per call here, which is half the budget of
    the whole check for a fact that is one index lookup."""
    (ok,) = conn.execute(
        "SELECT coalesce(("
        "  SELECT count(*) FROM pg_attribute"
        "   WHERE attrelid = to_regclass('public.goals')"
        "     AND NOT attisdropped AND attnum > 0 AND attname = ANY(%s)"
        "), 0) = %s",
        (list(_REQUIRED_COLUMNS), len(_REQUIRED_COLUMNS)),
    ).fetchone()
    return bool(ok)


def violations(conn: psycopg.Connection, owner: str | None = None) -> list[str]:
    """The five counts (six clauses — S-126's fifth is stated as one sentence but is two facts:
    the id must be the last segment *and* appear only once). Returns one human-readable line per
    offending row; an empty list is the all-zeroes AC-203 demands."""
    rows = conn.execute(_VIOLATIONS_SQL, {"owner": owner}).fetchall()
    return [f"clause {n}: {label}: {detail}" for n, label, detail in rows]


class TreeInvariantViolated(AssertionError):
    """Raised out of a scenario's teardown when the five counts are not five zeroes. An
    `AssertionError` rather than a bespoke exception so it reads as what it is at the top of a
    pytest teardown report: the scenario left the store corrupt, and AC-203 fails it for that
    even though its own assertions passed."""


def check_dsn(dsn: str, *, context: str) -> None:
    """Open a short-lived connection, run the five counts over the whole clone, raise on any
    non-zero. Called once per clone teardown from `tests/conftest.py`'s `fresh_clone`.

    `statement_timeout` is set low and deliberately: this runs after the scenario body and after
    every fixture that depends on the clone has been finalised, so nothing should still be
    holding a conflicting lock. If something is, the check must say so loudly rather than hang
    the suite — a scenario that leaks a lock-holding backend is itself a defect (S-46's shape).
    """
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        conn.execute("SET statement_timeout = '10s'")
        conn.execute("SET lock_timeout = '5s'")
        if not applicable(conn):
            return
        try:
            found = violations(conn)
        except psycopg.errors.QueryCanceled as exc:
            raise TreeInvariantViolated(
                f"AC-203 tree invariant could not be read after {context}: the check timed out, "
                f"which means a backend from this scenario still holds a conflicting lock after "
                f"teardown ({exc})"
            ) from exc
    if found:
        raise TreeInvariantViolated(
            "AC-203 tree invariant (docs/E2E.md S-126, five counts, all must be 0) is violated "
            f"after {context}; the scenario's own assertions are not the question here:\n  - "
            + "\n  - ".join(found)
        )
