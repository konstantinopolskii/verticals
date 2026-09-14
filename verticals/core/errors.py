"""The closed error taxonomy (docs/IMPLEMENTATION.md IR-03) — exactly these eight types and no
others (seven original, plus `RevisionMismatch` added by WP-33 through exactly the two-file
change this paragraph promised). `core/` raises them; each transport maps them through its own
literal table (`api/errors.py`'s HTTP status table, `mcp/tools.py`'s `isError` text) rather
than inspecting message text, so adding a ninth type is a two-file change, not a `grep` through
every `except`.

Every member carries `.detail`, a plain, JSON-serialisable dict built from whatever keyword
arguments the raise site passes. `core/errors.py` only owns the seven names and the common
shape — what goes into a given type's `detail` is the raising module's call, made where the
refusal actually happens and documented there (e.g. `CycleRefused(..., reason=...)`).
"""

from __future__ import annotations


class VerticalError(Exception):
    """Base of the closed taxonomy. Never raised directly — always one of the eight below."""

    def __init__(self, message: str, /, **detail: object) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, object] = dict(detail)


class ValidationError(VerticalError):
    """A caller-supplied value fails a rule `core/` enforces before writing anything — an
    unknown field, an out-of-bounds value, a query too short to search. Refused, not silently
    corrected (§10-D2): the caller's bug should surface, not hide for years."""


class NotFound(VerticalError):
    """No row exists for the given id within the caller's own `owner` scope. Also the answer
    for an id that exists but belongs to a different owner — the two cases are
    indistinguishable on purpose; that leaks nothing about who owns what."""


class CycleRefused(VerticalError):
    """A `reparent` would make a goal its own ancestor or descendant. `detail['reason']` names
    which — e.g. `'self'` for the trivial case, `'target_is_descendant'` for the indirect one
    (docs/E2E.md S-08, S-09)."""


class HasChildren(VerticalError):
    """A `delete` without `cascade=True` would silently take a non-empty subtree with it."""


class IdempotencyConflict(VerticalError):
    """A replayed `client_token` (IR-04) is paired with a request that does not match the
    digest stored from its first use — same token, different request."""


class RevisionMismatch(VerticalError):
    """An optimistic-lock guard on `evidence_update` (docs/EVIDENCE.md §6.2) refused a write:
    the caller's `expected_content_revision` no longer matches the goal, or its
    `expected_evidence_revision` no longer matches the evidence row — someone else got there
    first. `detail` carries the CURRENT revision(s) so the caller re-reads instead of guessing.
    Only ever raised for the caller's own goal — an unknown or foreign id is `NotFound` before
    any revision is compared, so this type can never become an existence oracle."""


class LockNotAvailable(VerticalError):
    """A row lock could not be acquired before the transport's own timeout. Transient by
    nature — the caller's own retry (the same one idempotency exists for) is the fix."""


class DatabaseUnavailable(VerticalError):
    """The database refused the connection or dropped it mid-transaction. Distinct from every
    other type here: nothing about the request was wrong, the dependency was just gone."""
