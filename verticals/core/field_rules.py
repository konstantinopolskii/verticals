"""Field bounds and per-field validators for the content verbs — split out of `core/goals.py`
when D239's `short_label` pushed that module past S-90a's 750-line cap (the same cap event that
produced `mcp/shapes.py` out of `mcp/tools.py` at WP-33). One direction, no cycle: `goals.py`
imports from here (aliasing back to its own `_validate_*` names so its call sites read
unchanged), and nothing here imports `goals.py` — this module knows fields and bounds, never
verbs, connections or SQL.

The bounds are IR-11's, pinned once (docs/IMPLEMENTATION.md §0.3; docs/E2E.md "Input limits").
External readers (`mcp/tools.py`'s schema caps, tests) keep importing them via `core.goals`,
which re-exports every name below — the public seam does not move with the file split.
"""

from __future__ import annotations

import secrets
import string
from datetime import date as _date
from datetime import datetime as _datetime

from verticals.core import vertical as vertical_mod
from verticals.core.errors import ValidationError

MIN_TITLE_CHARS = 1
MAX_TITLE_CHARS = 250
MAX_SHORT_LABEL_CHARS = 24  # 013's CHECK, mirrored below the same way color_is_canon is
MAX_BODY_BYTES = 64 * 1024
MAX_TAGS = 16
MAX_TAG_CHARS = 48

# `001_init.sql`'s `color_is_canon` CHECK, mirrored so a bad color is a clean `ValidationError`
# rather than a raw `psycopg.errors.CheckViolation` surfacing from the database.
CANON_COLORS: frozenset[str] = frozenset(
    {"#ecce32", "#df496d", "#92ce14", "#278dea", "#955be0", "#f2713a"}
)

# IR-05: 8-char base62, `secrets.choice`, `ON CONFLICT DO NOTHING RETURNING` (in `tree.attach`),
# three attempts before giving up loudly — 62^8 makes three collisions in a row a non-event.
# The attempt budget itself (`_ID_MAX_ATTEMPTS`) stays in `goals.py` beside the retry loop.
_ID_ALPHABET = string.ascii_letters + string.digits
_ID_LENGTH = 8


def is_control(ch: str) -> bool:
    """C0 (< 0x20, includes CR/LF/TAB) plus DEL through C1 (0x7F..0x9F) — `search.py`'s own range."""
    return ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F


def validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} is required and must be a non-empty string", field=field)
    return value


def optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return require_str(value, field)


def validate_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("title must be a string", field="title")
    stripped = value.strip()
    if not (MIN_TITLE_CHARS <= len(stripped) <= MAX_TITLE_CHARS):
        raise ValidationError(
            f"title must be {MIN_TITLE_CHARS}..{MAX_TITLE_CHARS} characters after strip, got "
            f"{len(stripped)}",
            field="title",
            minimum=MIN_TITLE_CHARS,
            maximum=MAX_TITLE_CHARS,
        )
    if any(is_control(ch) for ch in stripped):
        raise ValidationError(
            "title must carry no control characters, including CR, LF and TAB", field="title"
        )
    return stripped


def validate_body(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("body must be a string", field="body")
    size = len(value.encode("utf-8"))
    if size > MAX_BODY_BYTES:
        raise ValidationError(
            f"body must be at most {MAX_BODY_BYTES} bytes of UTF-8, got {size}",
            field="body",
            maximum=MAX_BODY_BYTES,
        )
    return value


def validate_short_label(value: object) -> str | None:
    """013's `short_label_is_one_word` CHECK, mirrored (the `validate_color` precedent): one
    word — no whitespace, no control characters — at most 24 chars, or None to clear."""
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_SHORT_LABEL_CHARS
        or any(ch.isspace() or is_control(ch) for ch in value)
    ):
        raise ValidationError(
            f"short_label must be one word of at most {MAX_SHORT_LABEL_CHARS} characters "
            f"(no whitespace) or None, got {value!r}",
            field="short_label",
        )
    return value


def validate_color(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in CANON_COLORS:
        raise ValidationError(
            f"color must be one of {sorted(CANON_COLORS)} or None, got {value!r}", field="color"
        )
    return value


def validate_tag(tag: object) -> str:
    """Byte-for-byte `search.py`'s own `_validate_tag` rule — not stripped, not folded (§10-D3)."""
    if not isinstance(tag, str):
        raise ValidationError("tag must be a string", field="tags")
    if not (1 <= len(tag) <= MAX_TAG_CHARS):
        raise ValidationError(
            f"tag must be 1..{MAX_TAG_CHARS} characters, got {len(tag)}",
            field="tags",
            maximum=MAX_TAG_CHARS,
        )
    if any(ch.isspace() or is_control(ch) for ch in tag):
        raise ValidationError("tag must carry no whitespace and no control characters", field="tags")
    return tag


def validate_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError("tags must be a list of strings", field="tags")
    if len(value) > MAX_TAGS:
        raise ValidationError(
            f"tags must be at most {MAX_TAGS} elements, got {len(value)}",
            field="tags",
            maximum=MAX_TAGS,
        )
    return tuple(validate_tag(t) for t in value)


def validate_schedule_fields(
    vertical: object, anchor_date: object
) -> tuple[str | None, _date | None, str | None]:
    """`vertical`/`anchor_date` in, `period_key` derived (AC-012: the arithmetic lives only in
    `core/vertical.py`) — called for `create`'s own root and every nested child spec, so the rule
    is enforced once. `anchor_date` without `vertical` is refused, not silently ignored: nothing
    in the product ever reads it in that state (§10-D2)."""
    if vertical is None:
        if anchor_date is not None:
            raise ValidationError(
                "anchor_date requires vertical to be set", field="vertical,anchor_date"
            )
        return None, None, None
    if not isinstance(vertical, str) or vertical not in vertical_mod.SCALE_KEYS:
        raise ValidationError(
            f"vertical must be one of {sorted(vertical_mod.SCALE_KEYS)} or None, got {vertical!r}",
            field="vertical",
        )
    if isinstance(anchor_date, _datetime) or not isinstance(anchor_date, _date):
        raise ValidationError(
            "anchor_date must be a date (not a datetime) when vertical is set", field="anchor_date"
        )
    return vertical, anchor_date, vertical_mod.period_key(vertical, anchor_date)


def generate_id() -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(_ID_LENGTH))
