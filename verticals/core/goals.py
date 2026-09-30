"""Caller-facing content verbs: create, read, update and delete (WP-13; IR-02/05/11).

Tree structure and timing live in `core/tree.py` and `core/moves.py`. This layer owns id
generation plus tags, nesting, node-count and period-key validation; every input is validated
before a goals-table write. `period_key` remains discoverable but never caller-settable (S-04).
Every function takes an open connection and never commits; owner is keyword-only throughout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as _date
from datetime import datetime as _datetime
from dataclasses import dataclass
from dataclasses import replace as _replace

import psycopg

from verticals.core import docs as docs_mod
from verticals.core import vertical as vertical_mod
from verticals.core import ideas as ideas_mod
from verticals.core import idem
from verticals.core import moves, repeat as repeat_mod, sizes as sizes_mod
from verticals.core import tree
from verticals.core.errors import HasChildren, LockNotAvailable, NotFound, ValidationError
# The field bounds and per-field validators moved to `core/field_rules.py` when D239's
# `short_label` pushed this module past S-90a's 750-line cap. The bounds re-export here (plain
# names) keeps the public seam where it always was — `mcp/tools.py` and the tests import them
# from `core.goals`; the `_validate_*` aliases keep every call site below reading unchanged.
from verticals.core.field_rules import (  # noqa: F401 — re-exported bounds
    CANON_COLORS,
    MAX_BODY_BYTES,
    MAX_SHORT_LABEL_CHARS,
    MAX_TAG_CHARS,
    MAX_TAGS,
    MAX_TITLE_CHARS,
    MIN_TITLE_CHARS,
)
from verticals.core.field_rules import (
    generate_id as _generate_id,
    is_control as _is_control,
    optional_str as _optional_str,
    require_str as _require_str,
    validate_body as _validate_body,
    validate_color as _validate_color,
    validate_owner as _validate_owner,
    validate_schedule_fields as _validate_schedule_fields,
    validate_short_label as _validate_short_label,
    validate_tag as _validate_tag,
    validate_tags as _validate_tags,
    validate_title as _validate_title,
)
from verticals.models import Ancestor, Goal

MAX_CHILDREN_DEPTH = 8  # levels below the created root — distinct from tree.MAX_DEPTH (32, absolute)
MAX_NODES_PER_CREATE = 200  # root + every descendant, one `create` call

# `goal_origin`'s labels (001_init.sql, 016_replan.sql). Who is *allowed* to pass 'agent' is an MCP-layer
# rule (S-53); this module accepts whatever a caller, including a trusted transport, names. 'app' is
# the server's own writer, the carry-over task (core/replan.py).
_ORIGINS: frozenset[str] = frozenset({"human", "agent", "import", "app"})

# IR-05's retry budget — the alphabet/length live with `generate_id` in `field_rules.py`.
_ID_MAX_ATTEMPTS = 3

_CHILD_SPEC_KEYS = frozenset({"title", "body", "color", "tags", "vertical", "anchor_date", "children"})

# `Goal`'s fields, table order — pinned locally, matching every sibling core module.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual"
)

_UNSET = object()  # S-04: period_key is discoverable on create(), never actually settable


@dataclass(frozen=True)
class Created:
    """`create`'s call envelope (matches `tree.RewrittenRow` / `search.SearchResult`'s own
    precedent, not `models.py`'s read vocabulary). `children` is every descendant flattened, not
    only direct children — S-52's "a whole plan in one call" needs grandchildren visible too.
    `replayed` distinguishes a fresh write from an idempotency replay (S-43's HTTP 201-vs-200 +
    `Idempotent-Replay` header contract needs exactly this, one layer up) — `False` by default
    for every caller that never passes `client_token` at all, where the distinction is moot."""

    goal: Goal
    children: tuple[Goal, ...]
    replayed: bool = False


@dataclass(frozen=True)
class Updated:
    """`update`'s call envelope. `open_descendants` is set only when this call set `done=True`
    (S-19) — `None` otherwise distinguishes "didn't touch completion" from "closed a leaf"."""

    goal: Goal
    open_descendants: int | None


GoalDetail = ideas_mod.GoalDetail


# --- small helpers, local to this module (house convention: no cross-import between core siblings) --


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])  # tags: psycopg hands back a list, `Goal` is frozen
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def _escape_like(text: str) -> str:
    """Local copy of `tree.py`'s `_escape_like` / `search.py`'s `escape_like` (both local too)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- nested `children`: validate, bound, and flatten in one recursive pass ----------------------


def _validate_child_spec(spec: object, *, level: int) -> tuple[dict, int]:
    """Returns `(normalized_spec, node_count_including_self)`. `level` is this node's distance
    below the created root (its direct children are level 1) — checked against
    `MAX_CHILDREN_DEPTH`, distinct from `tree.py`'s own *absolute* `MAX_DEPTH` (checked
    separately, by `tree.attach`, once each node's real `parent_id` is known)."""
    if not isinstance(spec, Mapping):
        raise ValidationError("each entry in children must be a mapping", field="children")
    unexpected = set(spec.keys()) - _CHILD_SPEC_KEYS
    if unexpected:
        raise ValidationError(
            f"unexpected key(s) in a child spec: {sorted(unexpected)}", field="children"
        )
    if level > MAX_CHILDREN_DEPTH:
        raise ValidationError(
            f"children nesting must be at most {MAX_CHILDREN_DEPTH} levels below the created "
            f"root, got a node at level {level}",
            field="children",
            maximum=MAX_CHILDREN_DEPTH,
        )
    if "title" not in spec:
        raise ValidationError("each child needs a title", field="title")

    title = _validate_title(spec["title"])
    body = _validate_body(spec.get("body", ""))
    color = _validate_color(spec.get("color"))
    tags = _validate_tags(spec.get("tags", ()))
    vertical, anchor_date, period_key = _validate_schedule_fields(
        spec.get("vertical"), spec.get("anchor_date")
    )

    raw_children = spec.get("children", ())
    if not isinstance(raw_children, (list, tuple)):
        raise ValidationError("children must be a list", field="children")

    normalized_children: list[dict] = []
    count = 1
    for child_spec in raw_children:
        normalized_child, child_count = _validate_child_spec(child_spec, level=level + 1)
        normalized_children.append(normalized_child)
        count += child_count

    normalized = {
        "title": title,
        "body": body,
        "color": color,
        "tags": tags,
        "vertical": vertical,
        "anchor_date": anchor_date,
        "period_key": period_key,
        "children": normalized_children,
    }
    return normalized, count


def _payload_children(specs: list[dict]) -> list[dict]:
    """JSON-safe rendering of the validated `children` tree for `idem.digest` (AC-051: hashed
    over *resolved* arguments; dates as ISO strings, same convention as `create`'s own payload)."""
    return [
        {
            "title": s["title"],
            "body": s["body"],
            "color": s["color"],
            "tags": list(s["tags"]),
            "vertical": s["vertical"],
            "anchor_date": s["anchor_date"].isoformat() if s["anchor_date"] else None,
            "children": _payload_children(s["children"]),
        }
        for s in specs
    ]


def _create_node(
    conn: psycopg.Connection, *, owner: str, parent_id: str | None, title: str, body: str,
    vertical: str | None, anchor_date: _date | None, period_key: str | None, color: str | None,
    tags: tuple[str, ...], origin: str, position: int | None,
) -> Goal:
    """IR-05's retry loop: `tree.attach` returns `None` on an id collision rather than raising,
    so the retry is this function's job, not `tree.py`'s."""
    for _ in range(_ID_MAX_ATTEMPTS):
        g = tree.attach(
            conn, owner=owner, id=_generate_id(), parent_id=parent_id, title=title, body=body,
            vertical=vertical, anchor_date=anchor_date, period_key=period_key, color=color,
            tags=tags, origin=origin, position=position,
        )
        if g is not None:
            return g
    raise ValidationError(f"could not generate a unique id after {_ID_MAX_ATTEMPTS} attempts", field="id")


def _create_children(
    conn: psycopg.Connection, *, owner: str, parent: Goal, specs: list[dict], origin: str
) -> tuple[Goal, ...]:
    """No advisory lock here, unlike `create`'s own root: `parent.id` was minted inside this
    same, still-open transaction, so no concurrent transaction can know it exists yet — the race
    AC-204 guards against cannot occur for a group keyed on an id nobody else can see.
    `position=None` lets `tree.attach`'s own internal, unlocked `tree.renumber` call allocate the
    tail position directly."""
    created: list[Goal] = []
    for spec in specs:
        child = _create_node(
            conn, owner=owner, parent_id=parent.id, title=spec["title"], body=spec["body"],
            vertical=spec["vertical"], anchor_date=spec["anchor_date"], period_key=spec["period_key"],
            color=spec["color"], tags=spec["tags"], origin=origin, position=None,
        )
        created.append(child)
        created.extend(
            _create_children(conn, owner=owner, parent=child, specs=spec["children"], origin=origin)
        )
    return tuple(created)


# --- idempotency response (de)serialisation -------------------------------------------------------
# Table-driven over `Goal`'s own declared fields (JSON has no date/timestamp type, so
# `core/board.py`'s `_goal_from_jsonb` faces the same problem and solves it the same way, field by
# field) — a field added to `models.Goal` needs no matching edit here to stay correct.

_GOAL_DATE_FIELDS = frozenset({"anchor_date", "repeat_start_date", "carryover_ignored_until"})
_GOAL_DATETIME_FIELDS = frozenset({"done_at", "created_at", "updated_at"})
def _goal_response(g: Goal) -> dict:
    out: dict = {}
    for name in Goal.__dataclass_fields__:
        value = getattr(g, name)
        if name == "tags" or name.startswith("size_"):
            value = list(value) if value is not None else None
        elif name in _GOAL_DATE_FIELDS or name in _GOAL_DATETIME_FIELDS:
            value = value.isoformat() if value is not None else None
        out[name] = value
    return out


def _goal_from_response(d: Mapping) -> Goal:
    kwargs: dict = {}
    for name in Goal.__dataclass_fields__:
        # Responses persisted before migration 006 have no recurrence keys. Their honest replay
        # is the same non-repeating goal, so absent new nullable fields read as None.
        if name.startswith("repeat_") or name.startswith("size_") or name in {"parked_from_vertical", "carryover_ignored_until"}:
            value = d.get(name)
        elif name == "foil":
            value = d.get(name, False)
        else:
            value = d[name]
        if name == "tags":
            value = tuple(value)
        elif name.startswith("size_"):
            value = tuple(value) if value is not None else None
        elif name in _GOAL_DATE_FIELDS:
            value = _date.fromisoformat(value) if value else None
        elif name in _GOAL_DATETIME_FIELDS:
            value = _datetime.fromisoformat(value) if value else None
        kwargs[name] = value
    return Goal(**kwargs)


def _created_response(created: Created) -> dict:
    return {
        "goal": _goal_response(created.goal),
        "children": [_goal_response(c) for c in created.children],
    }


def _created_from_response(response: Mapping[str, object]) -> Created:
    return Created(
        goal=_goal_from_response(response["goal"]),  # type: ignore[arg-type]
        children=tuple(_goal_from_response(c) for c in response["children"]),  # type: ignore[union-attr]
    )


# --- create -----------------------------------------------------------------------------------


def create(
    conn: psycopg.Connection,
    *,
    owner: str,
    title: str,
    body: str = "",
    parent_id: str | None = None,
    vertical: str | None = None,
    anchor_date: _date | None = None,
    color: str | None = None,
    tags: Sequence[str] = (),
    children: Sequence[Mapping] = (),
    origin: str = "human",
    after_id: str | None = None,
    before_id: str | None = None,
    client_token: str | None = None,
    period_key: object = _UNSET,
) -> Created:
    """A single node, or a whole nested plan, in one transaction and (when `client_token` is
    given) one idempotency record for all of it (S-52: "+6 rows from one call, replayable").
    `period_key` is never an input (S-04) — see the module docstring. The root's own position
    goes through `moves.allocate_position` (AC-204's lock); `children` do not need it (see
    `_create_children`)."""
    owner = _validate_owner(owner)
    if period_key is not _UNSET:
        raise ValidationError(
            "period_key is derived from vertical and anchor_date, never accepted as input",
            field="period_key",
        )
    if not isinstance(origin, str) or origin not in _ORIGINS:
        raise ValidationError(f"origin must be one of {sorted(_ORIGINS)}, got {origin!r}", field="origin")
    parent_id = _optional_str(parent_id, "parent_id")

    root_title = _validate_title(title)
    root_body = _validate_body(body)
    root_color = _validate_color(color)
    root_tags = _validate_tags(tags)
    root_vertical, root_anchor_date, root_period_key = _validate_schedule_fields(vertical, anchor_date)

    if not isinstance(children, (list, tuple)):
        raise ValidationError("children must be a list", field="children")
    normalized_children: list[dict] = []
    total_nodes = 1
    for child_spec in children:
        normalized_child, child_count = _validate_child_spec(child_spec, level=1)
        normalized_children.append(normalized_child)
        total_nodes += child_count
    if total_nodes > MAX_NODES_PER_CREATE:
        raise ValidationError(
            f"create accepts at most {MAX_NODES_PER_CREATE} nodes total (root + children), got "
            f"{total_nodes}",
            field="children",
            maximum=MAX_NODES_PER_CREATE,
        )

    digest = None
    if client_token is not None:
        payload = {
            "owner": owner,
            "title": root_title,
            "vertical": root_vertical,
            "anchor_date": root_anchor_date.isoformat() if root_anchor_date else None,
            "parent_id": parent_id,
            "body": root_body,
            "color": root_color,
            "tags": list(root_tags),
            "children": _payload_children(normalized_children),
        }
        digest = idem.digest(payload)

    with conn.transaction():
        if client_token is not None:
            reservation = idem.reserve(conn, owner=owner, client_token=client_token, request_digest=digest)
            if isinstance(reservation, idem.Replayed):
                replay = _created_from_response(reservation.response)
                return Created(goal=replay.goal, children=replay.children, replayed=True)

        position = moves.allocate_position(
            conn, owner=owner, vertical=root_vertical, period_key=root_period_key,
            parent_id=parent_id, after_id=after_id, before_id=before_id,
        )
        root = _create_node(
            conn, owner=owner, parent_id=parent_id, title=root_title, body=root_body,
            vertical=root_vertical, anchor_date=root_anchor_date, period_key=root_period_key,
            color=root_color, tags=root_tags, origin=origin, position=position,
        )
        descendants = _create_children(conn, owner=owner, parent=root, specs=normalized_children, origin=origin)
        # A goal BORN with doc links in its body must index them the same turn — `update()` alone
        # doing this left create-with-body goals linkless until their first edit (found by D250
        # WP-3's chip test, which had to work around it with a create-then-update).
        for node in (root, *descendants):
            if node.body:
                docs_mod.rewrite_goal_links(conn, owner=owner, goal_id=node.id, body=node.body)
        created = Created(goal=root, children=descendants)

        if client_token is not None:
            idem.complete(conn, owner=owner, client_token=client_token, response=_created_response(created))

    return created


# --- reads: goal, children_of --------------------------------------------------------------------


def goal(conn: psycopg.Connection, *, owner: str, id: str) -> GoalDetail:
    """The target row, its breadcrumb (root-first, not including itself) and its direct
    children — independent of any board date (see `GoalDetail`'s own docstring). Two statements,
    not three (S-42's "server statement delta ≤ 2"): the breadcrumb rides along as a `json_agg`
    subquery on the same round trip as the target row. `json_agg` over zero ancestors is SQL
    NULL, not `[]` — handled explicitly below."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")

    row = conn.execute(
        f"""
        SELECT {COLUMNS},
               (SELECT json_agg(json_build_object('id', a.id, 'title', a.title, 'vertical', a.vertical)
                                 ORDER BY seg.ord)
                  FROM unnest(string_to_array(btrim(g.path, '/'), '/')) WITH ORDINALITY AS seg(aid, ord)
                  JOIN goals a ON a.owner = g.owner AND a.id = seg.aid
                 WHERE seg.ord <= g.depth) AS ancestors_json,
               (SELECT r.color
                  FROM goals r
                 WHERE r.owner = g.owner
                   AND r.id = split_part(btrim(g.path, '/'), '/', 1)
                   AND r.vertical = 'life') AS value_color
          FROM goals g
         WHERE g.owner = %(owner)s AND g.id = %(id)s
        """,
        {"owner": owner, "id": id},
    ).fetchone()
    if row is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    # D231 (KK, 2026-08-15): the detail carries the derived value colour — its life-vertical
    # root's, or none — exactly like every board card (`core/board.py`'s `root` lateral). The
    # subquery rides the same statement, so S-42's statement delta is unchanged. `kids`/`ideas`
    # share the target's root by construction (they are its descendants), so one substitution
    # covers all three shapes.
    value_color = row[-1]
    target = _replace(_to_goal(row[:-2]), color=value_color)
    ancestors = tuple(Ancestor(id=a["id"], title=a["title"], vertical=a["vertical"]) for a in row[-2] or ())

    kids, ideas = ideas_mod.detail_family(conn, owner=owner, target=target)
    kids = tuple(_replace(k, color=value_color) for k in kids)
    ideas = tuple(_replace(k, color=value_color) for k in ideas)

    return GoalDetail(goal=target, ancestors=ancestors, children=kids, ideas=ideas)


def children_of(conn: psycopg.Connection, *, owner: str, id: str) -> tuple[Goal, ...]:
    """Direct children only, position order. Confirms `id` exists under `owner` first (S-20 row
    3: another owner's id is `NotFound`, not an empty tuple — indistinguishable from "no
    children", which would leak that the id exists)."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")

    exists = conn.execute(
        "SELECT 1 FROM goals WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id}
    ).fetchone()
    if exists is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)

    rows = conn.execute(
        f"SELECT {COLUMNS} FROM goals WHERE owner = %(owner)s AND parent_id = %(id)s ORDER BY position, id",
        {"owner": owner, "id": id},
    ).fetchall()
    return tuple(_to_goal(r) for r in rows)


# --- update -----------------------------------------------------------------------------------


def _resolve_ids(id: str | None, ids: Sequence[str] | None) -> tuple[tuple[str, ...], bool]:
    if (id is None) == (ids is None):
        raise ValidationError("update needs exactly one of id or ids", field="id,ids")
    if id is not None:
        return (_require_str(id, "id"),), False
    if not isinstance(ids, (list, tuple)) or not ids:
        raise ValidationError("ids must be a non-empty list", field="ids")
    return tuple(_require_str(i, "ids") for i in ids), True


def update(
    conn: psycopg.Connection,
    *,
    owner: str,
    id: str | None = None,
    ids: Sequence[str] | None = None,
    title: object = _UNSET,
    body: object = _UNSET,
    color: object = _UNSET,
    tags: object = _UNSET,
    done: object = _UNSET,
    foil: object = _UNSET,
    carryover_ignored_until: object = _UNSET,
    repeat: object = _UNSET,
    size_expected: object = _UNSET,
    short_label: object = _UNSET,
) -> Updated | tuple[Updated, ...]:
    """Patch content, recurrence, and expected size; structure/timing stay in ``core.moves``.
    Exactly one of ``id`` or ``ids`` is accepted. Sentinel defaults distinguish omitted fields
    from explicit nulls. Bulk writes are atomic: one missing or invalid target rolls back all.
    """
    owner = _validate_owner(owner)
    target_ids, bulk = _resolve_ids(id, ids)
    if bulk and repeat is not _UNSET:
        raise ValidationError("repeat targets one goal, not ids", field="repeat")

    # `clock_timestamp()`, never transaction-start `now()`: a writer waiting on a row lock must
    # stamp after the writer it followed, so readers never see `updated_at` move backwards (S-58,
    # migration 005). Every other core write uses the same rule.
    set_clauses = ["updated_at = clock_timestamp()"]
    params: dict[str, object] = {"owner": owner, "ids": list(target_ids)}
    if title is not _UNSET:
        params["title"] = _validate_title(title)
        set_clauses.append("title = %(title)s")
    if body is not _UNSET:
        params["body"] = _validate_body(body)
        set_clauses.append("body = %(body)s")
    if color is not _UNSET:
        params["color"] = _validate_color(color)
        set_clauses.append("color = %(color)s")
    if short_label is not _UNSET:
        params["short_label"] = _validate_short_label(short_label)
        set_clauses.append("short_label = %(short_label)s")
    if tags is not _UNSET:
        params["tags"] = list(_validate_tags(tags))
        set_clauses.append("tags = %(tags)s")
    if done is not _UNSET:
        if not isinstance(done, bool):
            raise ValidationError("done must be a boolean", field="done")
        params["done"] = done
        # `clock_timestamp()` here for the same reason as `updated_at` above, and so the two
        # stamps this statement writes carry the same meaning ("when the write happened") rather
        # than two different ones. Nothing compares `done_at` to `updated_at`, so the sub-
        # microsecond gap between the two evaluations is not observable by any contract.
        set_clauses.append("done_at = CASE WHEN %(done)s THEN clock_timestamp() ELSE NULL END")
    if foil is not _UNSET:
        if not isinstance(foil, bool):
            raise ValidationError("foil must be a boolean", field="foil")
        params["foil"] = foil
        set_clauses.append("foil = %(foil)s")
    if carryover_ignored_until is not _UNSET:
        if (
            carryover_ignored_until is not None
            and (
                isinstance(carryover_ignored_until, _datetime)
                or not isinstance(carryover_ignored_until, _date)
            )
        ):
            raise ValidationError(
                "carryover_ignored_until must be a date (not a datetime) or null",
                field="carryover_ignored_until",
            )
        params["carryover_ignored_until"] = carryover_ignored_until
        set_clauses.append("carryover_ignored_until = %(carryover_ignored_until)s")
    normalized_repeat: object = _UNSET
    if repeat is not _UNSET:
        normalized_repeat, repeat_params, repeat_clauses = repeat_mod.update_assignment(repeat)
        params.update(repeat_params)
        set_clauses.extend(repeat_clauses)
    if size_expected is not _UNSET:
        _, size_params, size_clauses = sizes_mod.update_assignment(size_expected)
        params.update(size_params)
        set_clauses.extend(size_clauses)
    if len(set_clauses) == 1:
        raise ValidationError(
            "update needs at least one of title, body, color, tags, done, foil, "
            "carryover_ignored_until, repeat, size_expected, short_label",
            field="title,body,color,tags,done,foil,carryover_ignored_until,repeat,size_expected,short_label",
        )

    with conn.transaction():
        if size_expected is not _UNSET:
            sizes_mod.validate_targets(conn, owner=owner, ids=target_ids)
        if normalized_repeat is not _UNSET and normalized_repeat is not None:
            repeat_mod.validate_target(conn, owner=owner, id=target_ids[0])
        rows = conn.execute(
            f"""
            UPDATE goals SET {', '.join(set_clauses)}
             WHERE owner = %(owner)s AND id = ANY(%(ids)s)
             RETURNING {COLUMNS}
            """,
            params,
        ).fetchall()

        found_ids = {r[0] for r in rows}
        missing = [i for i in target_ids if i not in found_ids]
        if missing:
            raise NotFound(f"no goal {missing[0]!r} for owner {owner!r}", id=missing[0], owner=owner)

        goals_by_id = {r[0]: _to_goal(r) for r in rows}
        # D250 (WP-1): a goal's body can carry `[label](doc:<path>)` links — the goal-side half
        # of `core/docs.py`'s link table, kept in the same transaction as the write that changed
        # the text it is derived from. Gated on `body is not _UNSET` (only fires when this call
        # actually touched body — every other field leaves the text, and therefore the links
        # derived from it, unchanged). Reads `g.body`, the post-write value the `UPDATE` above
        # just returned, so the derived rows can never be one write behind. `core/docs.py` never
        # imports this module back — see its own module docstring for why that direction is the
        # only safe one; this is the single, surgical call site on this side of the seam.
        if body is not _UNSET:
            for g in goals_by_id.values():
                docs_mod.rewrite_goal_links(conn, owner=owner, goal_id=g.id, body=g.body)
        # D231 (KK, 2026-08-15): colour lives on value roots only — a parentless life-vertical
        # goal. Everywhere else the rendered colour is derived from that root (`core/board.py`'s
        # own `root` lateral), so a stored colour anywhere else is a write nothing can ever read
        # back; refused rather than silently swallowed. Checked off the UPDATE's own RETURNING
        # rows inside the open transaction — a bulk patch with one bad target rolls back whole,
        # same atomicity rule as the missing-id check above.
        # D239 rides the same law: `short_label` is the value's one-word menu name (App.vue's
        # nav row), meaningless anywhere the menu never looks.
        for gated_field, was_sent in (("color", color is not _UNSET), ("short_label", short_label is not _UNSET)):
            if not was_sent:
                continue
            for g in goals_by_id.values():
                if g.parent_id is not None or not vertical_mod.is_value_scale(g.vertical):
                    raise ValidationError(
                        f"{gated_field} lives on value roots only (life vertical, no parent) — "
                        f"goal {g.id!r} is not one",
                        field=gated_field,
                    )
        if done is True:
            for completed in tuple(goals_by_id.values()):
                repeat_mod.materialize_next(conn, owner=owner, completed=completed)
        open_descendants: dict[str, int] = {}
        if done is True:
            # One statement for every affected row (S-44: "one UPDATE, one readback", never one
            # readback per id). No ESCAPE needed: `g.path` is built only from IR-05's generated
            # alphanumeric ids, so a LIKE metacharacter in it cannot occur.
            open_descendants = dict(
                conn.execute(
                    "SELECT g.id, count(d.id) FROM goals g"
                    "  LEFT JOIN goals d ON d.owner = g.owner AND d.path LIKE g.path || '%%'"
                    "   AND d.id <> g.id AND d.done_at IS NULL"
                    " WHERE g.owner = %(owner)s AND g.id = ANY(%(ids)s) GROUP BY g.id",
                    {"owner": owner, "ids": list(found_ids)},
                ).fetchall()
            )

        by_id = {
            gid: Updated(goal=g, open_descendants=open_descendants.get(gid) if done is True else None)
            for gid, g in goals_by_id.items()
        }

    ordered = tuple(by_id[i] for i in target_ids)
    return ordered if bulk else ordered[0]


# --- delete -----------------------------------------------------------------------------------


def delete(conn: psycopg.Connection, *, owner: str, id: str, cascade: bool = False) -> int:
    """A leaf deletes itself; a non-empty subtree is refused (`HasChildren`, naming both the
    direct-child and total-descendant counts — S-14) unless `cascade=True`, in which case parent
    and subtree go together in the single `DELETE` below (S-15's "one transaction"; the FK's `ON
    DELETE RESTRICT` — `001_init.sql` — is why a leaves-first walk would otherwise be needed).

    S-16: a lock this call cannot acquire before the caller's own `lock_timeout` (set on `conn`
    by the caller, never here) surfaces as the closed taxonomy's `LockNotAvailable`, not a raw
    `psycopg` error; `with conn.transaction()` has already rolled back by then, so nothing is
    partially removed and `conn` is immediately usable again."""
    owner = _validate_owner(owner)
    id = _require_str(id, "id")

    try:
        with conn.transaction():
            row = conn.execute(
                "SELECT path FROM goals WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
                {"owner": owner, "id": id},
            ).fetchone()
            if row is None:
                raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
            (path,) = row
            pattern = _escape_like(path) + "%"

            (children,) = conn.execute(
                "SELECT count(*) FROM goals WHERE owner = %(owner)s AND parent_id = %(id)s",
                {"owner": owner, "id": id},
            ).fetchone()
            (descendants,) = conn.execute(
                "SELECT count(*) FROM goals"
                " WHERE owner = %(owner)s AND path LIKE %(pattern)s ESCAPE '\\' AND id <> %(id)s",
                {"owner": owner, "pattern": pattern, "id": id},
            ).fetchone()

            if children > 0 and not cascade:
                raise HasChildren(
                    f"{id!r} has {children} direct children; pass cascade=True to remove the "
                    f"subtree",
                    id=id,
                    owner=owner,
                    children=children,
                    descendants=descendants,
                )

            cur = conn.execute(
                "DELETE FROM goals"
                " WHERE owner = %(owner)s AND (id = %(id)s OR path LIKE %(pattern)s ESCAPE '\\')",
                {"owner": owner, "id": id, "pattern": pattern},
            )
            removed = cur.rowcount
    except psycopg.errors.LockNotAvailable as exc:
        raise LockNotAvailable(f"could not acquire a lock to delete {id!r}", id=id, owner=owner) from exc
    return removed
