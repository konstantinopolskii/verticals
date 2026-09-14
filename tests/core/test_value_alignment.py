"""D231-D233 (KK, 2026-08-15): derived value colour, value-banded column order, value filter.

The law under test: a goal's rendered colour is its life-vertical root's ("value's") stored
colour — everywhere, at read time, with no per-goal override; columns band by the life column's
own order with unvalued trees last; `board(value=...)` narrows every column except `maybe` (the
Inbox pile) to one value's subtree — since D240 the life column narrows too, and the nav menu
reads the never-narrowed `Board.values` list instead; and a stored colour is writable on value
roots alone. Real Postgres, no mocks.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import board, goals
from verticals.core.errors import NotFound, ValidationError

OWNER = "SYN-value-owner"
TODAY = date.today()
BLUE = "#278dea"
ROSE = "#df496d"
LIME = "#92ce14"
PAST_ANCHOR = date(2020, 1, 6)


def _value(conn: psycopg.Connection, title: str, color: str | None = None):
    return goals.create(
        conn, owner=OWNER, title=title, vertical="life", anchor_date=TODAY, color=color
    ).goal


def _child(
    conn: psycopg.Connection,
    title: str,
    parent_id: str,
    vertical: str = "day",
    anchor: date = TODAY,
    color: str | None = None,
):
    return goals.create(
        conn,
        owner=OWNER,
        title=title,
        parent_id=parent_id,
        vertical=vertical,
        anchor_date=anchor,
        color=color,
    ).goal


def _column(result, vertical: str | None):
    return next(column for column in result.columns if column.vertical == vertical)


def _board(conn: psycopg.Connection, value: str | None = None):
    return board.board(conn, owner=OWNER, date=TODAY, value=value)


def test_descendants_wear_the_value_colour(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value blue", BLUE)
    child = _child(db, "SYN child", value.id)
    grandchild = _child(db, "SYN grandchild", child.id)

    day = {g.id: g for g in _column(_board(db), "day").goals}
    assert day[child.id].color == BLUE
    assert day[grandchild.id].color == BLUE
    life = {g.id: g for g in _column(_board(db), "life").goals}
    assert life[value.id].color == BLUE


def test_stored_colour_below_the_root_is_never_read(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value blue", BLUE)
    # Stored at create time (create() still accepts it; only update() refuses) — the read side
    # must ignore it in favour of the root's colour on every surface.
    child = _child(db, "SYN child rogue colour", value.id, color=ROSE)

    day = {g.id: g for g in _column(_board(db), "day").goals}
    assert day[child.id].color == BLUE
    assert goals.goal(db, owner=OWNER, id=child.id).goal.color == BLUE


def test_tree_without_life_root_has_no_colour(db: psycopg.Connection) -> None:
    orphan = goals.create(
        db, owner=OWNER, title="SYN day root", vertical="day", anchor_date=TODAY, color=LIME
    ).goal
    kid = _child(db, "SYN day root kid", orphan.id)

    day = {g.id: g for g in _column(_board(db), "day").goals}
    assert day[orphan.id].color is None
    assert day[kid.id].color is None
    assert goals.goal(db, owner=OWNER, id=orphan.id).goal.color is None


def test_detail_children_carry_the_derived_colour(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value blue", BLUE)
    child = _child(db, "SYN child", value.id)
    _child(db, "SYN grandchild", child.id)

    detail = goals.goal(db, owner=OWNER, id=child.id)
    assert detail.goal.color == BLUE
    assert detail.children and all(k.color == BLUE for k in detail.children)


def test_columns_band_by_the_life_columns_own_order(db: psycopg.Connection) -> None:
    # Creation order fixes life-column positions: first < second. The day-column children are
    # created in the OPPOSITE order, and an unvalued root earlier than both — raw position order
    # would list [orphan, second's child, first's child]; the banding law demands the reverse.
    orphan = goals.create(
        db, owner=OWNER, title="SYN unvalued", vertical="day", anchor_date=TODAY
    ).goal
    first = _value(db, "SYN value first", BLUE)
    second = _value(db, "SYN value second", ROSE)
    second_child = _child(db, "SYN second child", second.id)
    first_child = _child(db, "SYN first child", first.id)

    day_ids = [g.id for g in _column(_board(db), "day").goals]
    assert day_ids == [first_child.id, second_child.id, orphan.id]


def test_value_filter_narrows_dated_columns_only(db: psycopg.Connection) -> None:
    first = _value(db, "SYN value first", BLUE)
    second = _value(db, "SYN value second", ROSE)
    first_child = _child(db, "SYN first child", first.id)
    second_child = _child(db, "SYN second child", second.id)
    orphan = goals.create(
        db, owner=OWNER, title="SYN unvalued", vertical="day", anchor_date=TODAY
    ).goal
    idea = goals.create(db, owner=OWNER, title="SYN maybe idea").goal

    filtered = _board(db, value=first.id)
    day_ids = {g.id for g in _column(filtered, "day").goals}
    assert first_child.id in day_ids
    assert second_child.id not in day_ids
    assert orphan.id not in day_ids
    # D240: life narrows too — only the selected value's rows stay in the column. The menu's
    # source moved to `Board.values`, which never narrows (or the filter could not be left).
    assert {g.id for g in _column(filtered, "life").goals} == {first.id}
    assert {g.id for g in filtered.values} == {first.id, second.id}
    assert idea.id in {g.id for g in _column(filtered, None).goals}


def test_value_filter_keeps_the_subtrees_ghosts(db: psycopg.Connection) -> None:
    first = _value(db, "SYN value first", BLUE)
    second = _value(db, "SYN value second", ROSE)
    ghosted = _child(db, "SYN first old week", first.id, vertical="week", anchor=PAST_ANCHOR)

    mine = _board(db, value=first.id)
    week_ids = {g.id for g in _column(mine, "week").goals}
    assert ghosted.id in week_ids and ghosted.id in mine.ghosts

    other = _board(db, value=second.id)
    assert ghosted.id not in {g.id for g in _column(other, "week").goals}
    assert ghosted.id not in other.ghosts


def test_value_filter_refuses_ids_that_are_not_value_roots(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value blue", BLUE)
    child = _child(db, "SYN child", value.id)
    day_root = goals.create(
        db, owner=OWNER, title="SYN day root", vertical="day", anchor_date=TODAY
    ).goal

    with pytest.raises(NotFound):
        _board(db, value="NOPE9999")
    with pytest.raises(NotFound):
        _board(db, value=child.id)
    with pytest.raises(NotFound):
        _board(db, value=day_root.id)
    with pytest.raises(ValidationError):
        _board(db, value="")


def test_colour_patch_lives_on_value_roots_only(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value")
    child = _child(db, "SYN child", value.id)
    day_root = goals.create(
        db, owner=OWNER, title="SYN day root", vertical="day", anchor_date=TODAY
    ).goal

    updated = goals.update(db, owner=OWNER, id=value.id, color=BLUE)
    assert updated.goal.color == BLUE

    with pytest.raises(ValidationError):
        goals.update(db, owner=OWNER, id=child.id, color=ROSE)
    with pytest.raises(ValidationError):
        goals.update(db, owner=OWNER, id=day_root.id, color=ROSE)


def test_bulk_colour_patch_is_atomic_across_the_refusal(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value", BLUE)
    child = _child(db, "SYN child", value.id)

    with pytest.raises(ValidationError):
        goals.update(db, owner=OWNER, ids=[value.id, child.id], color=ROSE)
    # One bad target rolled back the whole write: the legal target kept its colour too.
    assert goals.goal(db, owner=OWNER, id=value.id).goal.color == BLUE


# --- D239: the value menu's one-word short_label -------------------------------------------------


def test_short_label_lands_on_the_board_map(db: psycopg.Connection) -> None:
    value = _value(db, "SYN financial independence value", BLUE)
    _child(db, "SYN child", value.id)

    goals.update(db, owner=OWNER, id=value.id, short_label="Money")
    result = _board(db)
    # Sparse map, value roots only — the child never lands a key.
    assert result.short_labels == {value.id: "Money"}

    # Null clears; the key leaves the map rather than lingering as None.
    goals.update(db, owner=OWNER, id=value.id, short_label=None)
    assert _board(db).short_labels == {}


def test_short_label_is_refused_off_value_roots(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value", BLUE)
    child = _child(db, "SYN child", value.id)
    day_root = goals.create(
        db, owner=OWNER, title="SYN day root", vertical="day", anchor_date=TODAY
    ).goal

    for target in (child.id, day_root.id):
        with pytest.raises(ValidationError):
            goals.update(db, owner=OWNER, id=target, short_label="Nope")
    # Bulk stays atomic across the refusal, the D231 colour rule's own shape.
    with pytest.raises(ValidationError):
        goals.update(db, owner=OWNER, ids=[value.id, child.id], short_label="Nope")
    assert _board(db).short_labels == {}


def test_short_label_must_be_one_word(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value", BLUE)

    for bad in ("two words", " lead", "trail ", "a" * 25, "", "tab\tinside", 7):
        with pytest.raises(ValidationError):
            goals.update(db, owner=OWNER, id=value.id, short_label=bad)
