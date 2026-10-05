"""Privacy mode: private goals and their subtrees blur on screen while the mode is on.

The flag itself is `goals.private`, written by `core.goals.update`; this module owns the
per-owner mode and rules, and the subtree expansion the app draws from."""

from __future__ import annotations

from typing import Any

import psycopg

from verticals.core.errors import ValidationError

MAX_RULES_CHARS = 4000


def _validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _settings(conn: psycopg.Connection, owner: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT mode, rules FROM privacy_settings WHERE owner = %(owner)s", {"owner": owner}
    ).fetchone()
    return (row[0], row[1]) if row else (False, "")


def view(conn: psycopg.Connection, *, owner: str) -> dict[str, Any]:
    """The mode and every goal a private flag covers, descendants included."""
    owner = _validate_owner(owner)
    mode, _ = _settings(conn, owner)
    rows = conn.execute(
        """
        SELECT DISTINCT g.id
          FROM goals m
          JOIN goals g ON g.owner = m.owner AND starts_with(g.path, m.path)
         WHERE m.owner = %(owner)s AND m.private
         ORDER BY g.id
        """,
        {"owner": owner},
    ).fetchall()
    return {"mode": mode, "hidden": [r[0] for r in rows]}


def status(conn: psycopg.Connection, *, owner: str) -> dict[str, Any]:
    """Mode, rules and the goals flagged private, for the agent."""
    owner = _validate_owner(owner)
    mode, rules = _settings(conn, owner)
    marked = conn.execute(
        "SELECT id, title FROM goals WHERE owner = %(owner)s AND private ORDER BY path",
        {"owner": owner},
    ).fetchall()
    return {"mode": mode, "rules": rules, "private": [{"id": i, "title": t} for i, t in marked]}


def set_mode(conn: psycopg.Connection, *, owner: str, mode: object) -> None:
    owner = _validate_owner(owner)
    if not isinstance(mode, bool):
        raise ValidationError("mode must be a boolean", field="mode")
    conn.execute(
        """
        INSERT INTO privacy_settings (owner, mode) VALUES (%(owner)s, %(mode)s)
        ON CONFLICT (owner) DO UPDATE SET mode = EXCLUDED.mode
        """,
        {"owner": owner, "mode": mode},
    )


def set_rules(conn: psycopg.Connection, *, owner: str, rules: object) -> None:
    owner = _validate_owner(owner)
    if not isinstance(rules, str) or len(rules) > MAX_RULES_CHARS:
        raise ValidationError(f"rules must be a string of at most {MAX_RULES_CHARS} characters", field="rules")
    conn.execute(
        """
        INSERT INTO privacy_settings (owner, rules) VALUES (%(owner)s, %(rules)s)
        ON CONFLICT (owner) DO UPDATE SET rules = EXCLUDED.rules
        """,
        {"owner": owner, "rules": rules.strip()},
    )
