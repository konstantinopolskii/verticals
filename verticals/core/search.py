"""Substring search over `title || ' ' || body`, plus the tag filter — WP-10.

`ARCHITECTURE.md` §3 pins the index (`goals_search`, a GIN over the concatenation with
`gin_trgm_ops`) and the matching operator (`ILIKE '%q%'`, not `to_tsvector`): lexeme search
stems whole words, so `cycl` would never find `bicycles`, which is L7 and the incumbent's
nine-month-open defect. §10-D3 pins tag matching as case-sensitive; §10-D6 pins the index and
the shortest query it will serve.

**IR-12 is the whole point of this module.** `ILIKE '%' || q || '%'` with an unescaped `q`
makes `search(q='%')` a dump of the owner's entire table — the exact thing AC-047 exists to
forbid — and this is the primary read surface an LLM reaches over MCP. So `q` is bounded,
then escaped, then bound as a parameter; the query text never carries a caller's byte.

Two rules this module is the enforcement point for, both of them house law rather than taste:

  * **Owner scoping is not optional.** `owner` is keyword-only with no default (AC-013) and
    `owner = %(owner)s` is the one clause present in every statement this module can build.
  * **Refused, not silently corrected** (§10-D2). A query below the trigram floor, a tag
    carrying whitespace, a `limit` of zero — each raises `ValidationError` naming the field,
    before any SQL is built. None of them is quietly clamped into range.

The result is capped: `limit` rows plus a `truncated` flag (AC-202). An unbounded result set
handed to an agent is a context flood, and a refusal there would be worse than a truncation —
the flag is what stops a caller believing it saw everything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import psycopg

from verticals.core.errors import ValidationError
from verticals.core.vertical import SCALE_KEYS
from verticals.models import Goal

# §10-D6 / §4's pinned limits table. The floor is 3, not 2: a trigram index cannot serve a
# pattern shorter than three characters, so a shorter query is a sequential scan wearing a
# search's clothes. (IR-12's own prose says 2; every other document — S-26, S-129, AC-045,
# §10-D6, §4's limits table — says 3, and 3 is the number with a physical reason behind it.
# Flagged in this work package's result rather than silently followed either way.)
MIN_QUERY_CHARS = 3
MAX_QUERY_CHARS = 200
MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MAX_TAG_CHARS = 48

# The LIKE escape character, in three places that must agree: the doubling in `escape_like`,
# the `ESCAPE` clause below, and nothing else anywhere.
LIKE_ESCAPE = "\\"

# `Goal`'s fields are the table's columns in the table's own order, so one list serves both
# the SELECT and the dataclass construction. Never reorder one without the other.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual, private"
)

# The predicate S-26 asserts verbatim. In SQL text this is `ESCAPE '\'` — one backslash, which
# is what `standard_conforming_strings` (on by default since 9.1) makes of `'\'`. A literal
# two-character escape string is a Postgres error ("Escape string must be empty or one
# character"), so the doubled form seen in the documents is the Python source rendering of
# this exact string, not the SQL.
TRIGRAM_PREDICATE = "(title || ' ' || body) ILIKE %(pat)s ESCAPE '\\'"

# `@>` is what the GIN index on `tags` (`goals_tags`) answers. The cast is on the parameter,
# never on the column: wrapping `tags` in a function is how an index silently stops being
# usable, which is the failure mode S-27's plan assertion exists to catch.
TAG_PREDICATE = "tags @> %(tags)s::text[]"
VERTICAL_PREDICATE = "vertical = %(vertical)s::vertical_scale"

# A total order — `id` is the primary key, so no two rows can tie — which is what makes
# "stable across three consecutive calls" (S-129) a property of the query rather than luck.
ORDER_BY = "ORDER BY anchor_date DESC NULLS LAST, id ASC"
RECENT_ORDER_BY = "ORDER BY updated_at DESC, id ASC"


@dataclass(frozen=True)
class Parent:
    """One goal of a match's chain, root first, for the board to show as the match's context (flow 5's finding,
    docs/design-handoff S1.P3.013): where it stands (vertical, period) and whether it is done."""

    id: str
    parent_id: str | None
    title: str
    vertical: str | None
    anchor_date: object
    period_key: str | None
    done_at: object
    position: int


@dataclass(frozen=True)
class SearchResult:
    """`goals` capped at the caller's `limit`; `truncated` is True when the database held at
    least one more row that matched. Deliberately not in `verticals/models.py`: that module is
    the *read-model* vocabulary, one dataclass per shape the product renders, and this is a
    call envelope — the difference between "a board" and "how one function answered"."""

    goals: tuple[Goal, ...]
    truncated: bool
    parents: dict[str, tuple[Parent, ...]] | None = None


def escape_like(text: str) -> str:
    """IR-12's escaping, and the only place it happens. Backslash first — doubling it after
    the metacharacters were already escaped would double their escapes too and turn `%` back
    into a live wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _validate_query(q: str) -> str:
    if not isinstance(q, str):
        raise ValidationError("q must be a string", field="q")
    stripped = q.strip()
    if len(stripped) < MIN_QUERY_CHARS:
        raise ValidationError(
            f"q must be at least {MIN_QUERY_CHARS} characters after stripping, got "
            f"{len(stripped)}",
            field="q",
            minimum=MIN_QUERY_CHARS,
        )
    if len(stripped) > MAX_QUERY_CHARS:
        raise ValidationError(
            f"q must be at most {MAX_QUERY_CHARS} characters, got {len(stripped)}",
            field="q",
            maximum=MAX_QUERY_CHARS,
        )
    return stripped


def _validate_tag(tag: str) -> str:
    """Not stripped, not folded, not normalised. A tag is matched byte-for-byte against a
    stored label (§10-D3), so trimming a caller's `' retro '` into a match would be the
    silent correction §10-D2 refuses — and would make `search` answer a question the caller
    did not ask."""
    if not isinstance(tag, str):
        raise ValidationError("tag must be a string", field="tag")
    if not 1 <= len(tag) <= MAX_TAG_CHARS:
        raise ValidationError(
            f"tag must be 1..{MAX_TAG_CHARS} characters, got {len(tag)}",
            field="tag",
            maximum=MAX_TAG_CHARS,
        )
    if any(ch.isspace() or ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in tag):
        raise ValidationError(
            "tag must carry no whitespace and no control characters", field="tag"
        )
    return tag


def _validate_vertical(vertical: str) -> str:
    """Membership against `core/vertical.py`'s own set — AC-012: no module outside that file
    may compare a value against one of the seven scale strings, and `SCALE_KEYS` exists so
    that a caller never has to."""
    if not isinstance(vertical, str) or vertical not in SCALE_KEYS:
        raise ValidationError(
            f"vertical must be one of {sorted(SCALE_KEYS)}, got {vertical!r}", field="vertical"
        )
    return vertical


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError("limit must be an integer", field="limit")
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise ValidationError(
            f"limit must be {MIN_LIMIT}..{MAX_LIMIT}, got {limit}",
            field="limit",
            minimum=MIN_LIMIT,
            maximum=MAX_LIMIT,
        )
    return limit


def build_statement(*, with_q: bool, with_tag: bool, with_vertical: bool) -> str:
    """The statement `search` runs, built from the same three flags the caller's arguments
    set. Public so a test can assert the text without reaching into a private name, and so
    the text a plan assertion explains is the shipped one rather than one a test wrote."""
    clauses = ["owner = %(owner)s"]
    if with_q:
        clauses.append(TRIGRAM_PREDICATE)
    if with_tag:
        clauses.append(TAG_PREDICATE)
    if with_vertical:
        clauses.append(VERTICAL_PREDICATE)
    return (
        f"SELECT {COLUMNS}\n"
        f"  FROM goals\n"
        f" WHERE " + "\n   AND ".join(clauses) + f"\n {ORDER_BY}\n LIMIT %(limit)s"
    )


def build_statement_with_parents(terms: int) -> str:
    """The title-and-notes search for the board's finding: every word of three letters or more must be in a goal's
    title or notes, each word one trigram-served predicate. Each match's chain comes in the same statement, as
    `core/board.py` builds `ancestors` over `path`, and so does its value colour (D231)."""
    chain = (
        "jsonb_build_object('id', a.id, 'parent_id', a.parent_id, 'title', a.title, 'vertical', a.vertical, "
        "'anchor_date', a.anchor_date, 'period_key', a.period_key, 'done_at', a.done_at, 'position', a.position)"
    )
    words = "\n     AND ".join(
        TRIGRAM_PREDICATE.replace("%(pat)s", f"%(pat{i})s") for i in range(terms)
    )
    return (
        f"WITH hits AS (\n"
        f"  SELECT {COLUMNS}\n"
        f"    FROM goals\n"
        f"   WHERE owner = %(owner)s\n"
        f"     AND {words}\n"
        f"   {ORDER_BY}\n"
        f"   LIMIT %(limit)s\n"
        f")\n"
        f"SELECT hits.*,\n"
        f"       COALESCE(anc.chain, '[]'::jsonb),\n"
        f"       CASE WHEN root.vertical = 'life' THEN root.color END\n"
        f"  FROM hits\n"
        f"  LEFT JOIN LATERAL (\n"
        f"    SELECT jsonb_agg({chain} ORDER BY seg.ord) AS chain\n"
        f"      FROM unnest(string_to_array(btrim(hits.path, '/'), '/')) WITH ORDINALITY AS seg(aid, ord)\n"
        f"      JOIN goals a ON a.owner = hits.owner AND a.id = seg.aid\n"
        f"     WHERE seg.ord <= hits.depth\n"
        f"  ) anc ON true\n"
        f"  LEFT JOIN LATERAL (\n"
        f"    SELECT r.color, r.vertical FROM goals r\n"
        f"     WHERE r.owner = hits.owner AND r.id = split_part(btrim(hits.path, '/'), '/', 1)\n"
        f"  ) root ON true\n"
        f" {ORDER_BY}"
    )


def search_with_parents(
    conn: psycopg.Connection,
    *,
    owner: str,
    q: str,
    limit: int = DEFAULT_LIMIT,
) -> SearchResult:
    """Every goal whose title or notes hold each word of `q` of three letters or more (shorter words are the
    board's to match), each coloured by its value, with `parents` keyed by match id and `truncated`. One
    statement."""
    owner = _validate_owner(owner)
    limit = _validate_limit(limit)
    terms = [word for word in _validate_query(q).split() if len(word) >= MIN_QUERY_CHARS]
    if not terms:
        raise ValidationError(
            f"q needs a word of at least {MIN_QUERY_CHARS} characters", field="q", minimum=MIN_QUERY_CHARS
        )
    params: dict[str, object] = {"owner": owner, "limit": limit + 1}
    for i, term in enumerate(terms):
        params[f"pat{i}"] = f"%{escape_like(term)}%"
    rows = conn.execute(build_statement_with_parents(len(terms)), params).fetchall()
    width = len(COLUMNS.split(","))
    goals: list[Goal] = []
    parents: dict[str, tuple[Parent, ...]] = {}
    for row in rows[:limit]:
        goal = replace(_to_goal(row[:width]), color=row[width + 1])
        goals.append(goal)
        parents[goal.id] = tuple(
            Parent(
                id=a["id"], parent_id=a["parent_id"], title=a["title"], vertical=a["vertical"],
                anchor_date=a["anchor_date"], period_key=a["period_key"], done_at=a["done_at"], position=a["position"],
            )
            for a in row[width]
        )
    return SearchResult(goals=tuple(goals), truncated=len(rows) > limit, parents=parents)


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])  # tags: psycopg hands back a list, `Goal` is frozen
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def search(
    conn: psycopg.Connection,
    *,
    owner: str,
    q: str | None = None,
    tag: str | None = None,
    vertical: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> SearchResult:
    """One statement, owner-scoped, with any subset of the three filters — as long as it is
    not the empty subset. `search()` with no filter at all is "give me the table", which is
    what `board` and `inbox` are for; it is refused here rather than answered with the first
    fifty rows of somebody's life.

    IR-02: takes an open connection, never commits, never opens a transaction of its own.
    """
    owner = _validate_owner(owner)
    limit = _validate_limit(limit)
    if q is None and tag is None and vertical is None:
        raise ValidationError(
            "search needs at least one of q, tag or vertical", field="q,tag,vertical"
        )

    params: dict[str, object] = {"owner": owner, "limit": limit + 1}
    if q is not None:
        params["pat"] = f"%{escape_like(_validate_query(q))}%"
    if tag is not None:
        params["tags"] = [_validate_tag(tag)]
    if vertical is not None:
        params["vertical"] = _validate_vertical(vertical)

    statement = build_statement(
        with_q=q is not None, with_tag=tag is not None, with_vertical=vertical is not None
    )
    # `limit + 1` above, not a second COUNT: one extra row is the cheapest possible answer to
    # "was there more?", and a COUNT would be a second statement over the same predicate.
    rows = conn.execute(statement, params).fetchall()
    return SearchResult(
        goals=tuple(_to_goal(row) for row in rows[:limit]), truncated=len(rows) > limit
    )


def recent(
    conn: psycopg.Connection,
    *,
    owner: str,
    limit: int,
) -> SearchResult:
    """Newest owner-scoped goals for the empty search surface.

    Kept separate from :func:`search`: an empty filtered search remains invalid for MCP and
    other callers, while the HTTP search surface has an explicit recent-default mode. One extra
    row supplies ``truncated`` without a second statement, matching ``search``.
    """
    owner = _validate_owner(owner)
    limit = _validate_limit(limit)
    rows = conn.execute(
        f"SELECT {COLUMNS}\n"
        "  FROM goals\n"
        " WHERE owner = %(owner)s\n"
        f" {RECENT_ORDER_BY}\n"
        " LIMIT %(limit)s",
        {"owner": owner, "limit": limit + 1},
    ).fetchall()
    return SearchResult(
        goals=tuple(_to_goal(row) for row in rows[:limit]), truncated=len(rows) > limit
    )
