"""Project-tag registry: one global setting per literal tag, plus an owner-scoped tag list."""

from __future__ import annotations

from typing import Any

import psycopg

from verticals.core.errors import ValidationError

MAX_TAG_CHARS = 48


def _validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _validate_tag(tag: object) -> str:
    if not isinstance(tag, str):
        raise ValidationError("tag must be a string", field="tag")
    if not 1 <= len(tag) <= MAX_TAG_CHARS:
        raise ValidationError(f"tag must be 1..{MAX_TAG_CHARS} characters", field="tag")
    if any(ch.isspace() or ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in tag):
        raise ValidationError("tag must carry no whitespace and no control characters", field="tag")
    return tag


def list_tags(conn: psycopg.Connection, *, owner: str) -> tuple[dict[str, Any], ...]:
    """Every tag used by this owner plus registry-only tags, sorted literally."""
    owner = _validate_owner(owner)
    rows = conn.execute(
        """
        WITH known AS (
          SELECT DISTINCT unnest(tags) AS tag FROM goals WHERE owner = %(owner)s
          UNION
          SELECT tag FROM tag_meta
        )
        SELECT known.tag, coalesce(tag_meta.project, false)
          FROM known LEFT JOIN tag_meta USING (tag)
         ORDER BY known.tag
        """,
        {"owner": owner},
    ).fetchall()
    return tuple({"tag": tag, "project": project} for tag, project in rows)


def mark(
    conn: psycopg.Connection, *, owner: str, tag: str, project: bool
) -> dict[str, Any]:
    """Set or clear project presentation for a tag. Never creates or edits a goal."""
    _validate_owner(owner)
    tag = _validate_tag(tag)
    if not isinstance(project, bool):
        raise ValidationError("project must be a boolean", field="project")
    row = conn.execute(
        """
        INSERT INTO tag_meta (tag, project) VALUES (%(tag)s, %(project)s)
        ON CONFLICT (tag) DO UPDATE SET project = EXCLUDED.project
        RETURNING tag, project
        """,
        {"tag": tag, "project": project},
    ).fetchone()
    return {"tag": row[0], "project": row[1]}
