"""D250 (KK, 2026-08-20), WP-1 — documents as first-class residents, through real `core.docs`
calls and real Postgres, no mocks. Path validation, the append-only revision history, restore,
delete refusal while linked, link parsing in both directions (including the surgical
`core.goals.py::update` hook), and owner isolation.
"""

from __future__ import annotations

import psycopg
import pytest

from verticals.core import docs, goals
from verticals.core.errors import NotFound, RevisionMismatch, ValidationError

OWNER = "docs-core"
OTHER_OWNER = "docs-other"


def _doc(conn: psycopg.Connection, *, owner: str = OWNER, path: str = "strategy/ai-native.md",
          title: str | None = "AI-native strategy", body: str = "initial text"):
    return docs.create(conn, owner=owner, path=path, title=title, body=body).doc


def _goal(conn: psycopg.Connection, *, owner: str = OWNER, title: str = "Subject", body: str = ""):
    return goals.create(conn, owner=owner, title=title, body=body).goal


# --- create: happy path, duplicate path -----------------------------------------------------


def test_create_inserts_doc_and_revision_one(db: psycopg.Connection) -> None:
    d = _doc(db)
    assert d.revision == 1
    assert d.title == "AI-native strategy"
    assert d.body == "initial text"

    history = docs.history(db, owner=OWNER, id=d.id)
    assert len(history) == 1
    assert history[0].revision == 1
    assert history[0].body_length == len("initial text")


def test_create_title_may_be_null(db: psycopg.Connection) -> None:
    d = docs.create(db, owner=OWNER, path="untitled.md", title=None, body="").doc
    assert d.title is None


def test_create_duplicate_path_is_refused(db: psycopg.Connection) -> None:
    _doc(db, path="dup.md")
    with pytest.raises(ValidationError) as excinfo:
        docs.create(db, owner=OWNER, path="dup.md", title="second", body="")
    assert excinfo.value.detail["field"] == "path"
    # a duplicate path for a DIFFERENT owner is not a conflict at all (owner-scoped uniqueness)
    other = docs.create(db, owner=OTHER_OWNER, path="dup.md", title="third", body="").doc
    assert other.path == "dup.md"


# --- path validation: every invalid shape ------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "/abs/path.md",
        "trailing/slash/.md/",
        "a//b.md",
        "a/./b.md",
        "a/../b.md",
        "..",
        ".",
        "no-extension",
        "no-extension.txt",
        "a/b\t.md",
        "a/b\n.md",
        "x" * 513 + ".md",
    ],
)
def test_create_refuses_every_invalid_path_shape(db: psycopg.Connection, bad_path: str) -> None:
    with pytest.raises(ValidationError):
        docs.create(db, owner=OWNER, path=bad_path, title="t", body="")


def test_create_accepts_a_deep_relative_path(db: psycopg.Connection) -> None:
    d = docs.create(db, owner=OWNER, path="a/b/c/d.md", title="deep", body="").doc
    assert d.path == "a/b/c/d.md"


# --- title/body validation --------------------------------------------------------------------


def test_create_refuses_blank_and_oversized_title(db: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        docs.create(db, owner=OWNER, path="a.md", title="   ", body="")
    with pytest.raises(ValidationError):
        docs.create(db, owner=OWNER, path="b.md", title="x" * (docs.MAX_DOC_TITLE_CHARS + 1), body="")


def test_create_refuses_oversized_body(db: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        docs.create(db, owner=OWNER, path="big.md", title="t", body="x" * (docs.MAX_DOC_BODY_BYTES + 1))


# --- save: revision append, RevisionMismatch ----------------------------------------------------


def test_save_bumps_revision_and_appends_history(db: psycopg.Connection) -> None:
    d = _doc(db)
    updated = docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="second text").doc
    assert updated.revision == 2
    assert updated.body == "second text"
    assert updated.title == d.title  # omitted -> unchanged
    assert updated.path == d.path

    history = docs.history(db, owner=OWNER, id=d.id)
    assert [h.revision for h in history] == [1, 2]
    assert history[1].body_length == len("second text")


def test_save_can_change_title_and_path_independently(db: psycopg.Connection) -> None:
    d = _doc(db)
    updated = docs.save(db, owner=OWNER, id=d.id, expected_revision=1, title="renamed").doc
    assert updated.title == "renamed" and updated.body == d.body and updated.path == d.path

    moved = docs.save(db, owner=OWNER, id=d.id, expected_revision=2, path="moved/here.md").doc
    assert moved.path == "moved/here.md" and moved.title == "renamed"


def test_save_refuses_a_stale_revision_with_the_current_one(db: psycopg.Connection) -> None:
    d = _doc(db)
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="v2")
    with pytest.raises(RevisionMismatch) as excinfo:
        docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="v3-conflict")
    assert excinfo.value.detail["revision"] == 2
    # the refused write left no trace
    history = docs.history(db, owner=OWNER, id=d.id)
    assert len(history) == 2


def test_save_to_a_path_already_taken_is_refused(db: psycopg.Connection) -> None:
    _doc(db, path="taken.md")
    d2 = _doc(db, path="free.md")
    with pytest.raises(ValidationError):
        docs.save(db, owner=OWNER, id=d2.id, expected_revision=1, path="taken.md")


def test_save_unknown_and_foreign_ids_raise_indistinguishable_notfound(db: psycopg.Connection) -> None:
    foreign = _doc(db, owner=OTHER_OWNER, path="theirs.md")
    with pytest.raises(NotFound) as unknown_exc:
        docs.save(db, owner=OWNER, id="ZZZZZZZZ", expected_revision=1, body="x")
    with pytest.raises(NotFound) as foreign_exc:
        docs.save(db, owner=OWNER, id=foreign.id, expected_revision=1, body="x")
    assert str(unknown_exc.value) == f"no doc 'ZZZZZZZZ' for owner {OWNER!r}"
    assert str(foreign_exc.value) == f"no doc {foreign.id!r} for owner {OWNER!r}"


# --- history / get_revision ---------------------------------------------------------------------


def test_get_revision_returns_full_text(db: psycopg.Connection) -> None:
    d = _doc(db)
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="second text")
    rev1 = docs.get_revision(db, owner=OWNER, id=d.id, revision=1)
    assert rev1.body == "initial text"
    rev2 = docs.get_revision(db, owner=OWNER, id=d.id, revision=2)
    assert rev2.body == "second text"


def test_get_revision_unknown_revision_is_notfound(db: psycopg.Connection) -> None:
    d = _doc(db)
    with pytest.raises(NotFound):
        docs.get_revision(db, owner=OWNER, id=d.id, revision=99)


def test_history_and_get_revision_unknown_doc_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        docs.history(db, owner=OWNER, id="ZZZZZZZZ")
    with pytest.raises(NotFound):
        docs.get_revision(db, owner=OWNER, id="ZZZZZZZZ", revision=1)


# --- restore: copies old text forward as a NEW revision --------------------------------------


def test_restore_copies_old_revision_forward_as_new_revision(db: psycopg.Connection) -> None:
    d = _doc(db, body="v1 text")
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="v2 text")
    docs.save(db, owner=OWNER, id=d.id, expected_revision=2, body="v3 text", path=d.path)

    restored = docs.restore(db, owner=OWNER, id=d.id, revision=1, expected_revision=3).doc
    assert restored.revision == 4, "restore is a NEW revision, never a rewind of the counter"
    assert restored.body == "v1 text"
    assert restored.path == d.path, "restore never touches path"

    history = docs.history(db, owner=OWNER, id=d.id)
    assert [h.revision for h in history] == [1, 2, 3, 4]
    assert history[0].body_length == len("v1 text") and history[3].body_length == len("v1 text")


def test_restore_refuses_stale_expected_revision(db: psycopg.Connection) -> None:
    d = _doc(db)
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body="v2")
    with pytest.raises(RevisionMismatch):
        docs.restore(db, owner=OWNER, id=d.id, revision=1, expected_revision=1)


def test_restore_unknown_revision_is_notfound(db: psycopg.Connection) -> None:
    d = _doc(db)
    with pytest.raises(NotFound):
        docs.restore(db, owner=OWNER, id=d.id, revision=99, expected_revision=1)


# --- delete: refused while linked, clean otherwise ----------------------------------------------


def test_delete_refused_while_linked_from_a_goal(db: psycopg.Connection) -> None:
    d = _doc(db, path="linked.md")
    g = _goal(db, body="")
    goals.update(db, owner=OWNER, id=g.id, body=f"[see](doc:{d.path})")

    with pytest.raises(ValidationError) as excinfo:
        docs.delete(db, owner=OWNER, id=d.id)
    assert excinfo.value.detail["linked_goal_ids"] == [g.id]

    # removing the link (editing the goal's body) clears the way
    goals.update(db, owner=OWNER, id=g.id, body="no more link")
    docs.delete(db, owner=OWNER, id=d.id)
    with pytest.raises(NotFound):
        docs.get(db, owner=OWNER, id=d.id)


def test_delete_refused_while_the_doc_itself_links_a_goal(db: psycopg.Connection) -> None:
    g = _goal(db)
    d = docs.create(db, owner=OWNER, path="refs-goal.md", title="t", body=f"[link](goal:{g.id})").doc
    with pytest.raises(ValidationError) as excinfo:
        docs.delete(db, owner=OWNER, id=d.id)
    assert excinfo.value.detail["linked_goal_ids"] == [g.id]


def test_delete_unlinked_doc_cascades_revisions(db: psycopg.Connection) -> None:
    d = _doc(db)
    docs.delete(db, owner=OWNER, id=d.id)
    (count,) = db.execute("SELECT count(*) FROM doc_revisions WHERE doc_id = %s", (d.id,)).fetchone()
    assert count == 0


def test_delete_unknown_id_is_notfound(db: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        docs.delete(db, owner=OWNER, id="ZZZZZZZZ")


# --- link parsing: extract_links itself (pure function) ------------------------------------------


def test_extract_links_behaviour_table() -> None:
    cases = [
        ("[the vision](goal:2VHolmfU)", {"2VHolmfU"}, set()),
        ("[baseline](doc:money/baseline.md)", set(), {"money/baseline.md"}),
        ("[a](goal:X) and [b](doc:y.md) and [c](goal:X)", {"X"}, {"y.md"}),
        ("no links here at all", set(), set()),
        ("[weird](goal: X)", set(), set()),  # a space after the colon is not this destination form
        ("", set(), set()),
    ]
    for text, expected_goals, expected_docs in cases:
        result = docs.extract_links(text)
        assert set(result.goal_ids) == expected_goals, text
        assert set(result.doc_paths) == expected_docs, text


# --- link parsing: doc side (create + save) -----------------------------------------------------


def test_doc_create_and_save_parse_and_rewrite_doc_side_links(db: psycopg.Connection) -> None:
    g1 = _goal(db, title="target one")
    g2 = _goal(db, title="target two")

    d = docs.create(db, owner=OWNER, path="notes.md", title="t", body=f"[one](goal:{g1.id})").doc
    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {(link.goal_id, link.source) for link in links} == {(g1.id, "doc")}

    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body=f"[two](goal:{g2.id})")
    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {(link.goal_id, link.source) for link in links} == {(g2.id, "doc")}, (
        "save rebuilds from the current text — the old link is gone, not merely supplemented"
    )

    docs.save(db, owner=OWNER, id=d.id, expected_revision=2, body="no links anymore")
    assert docs.links_for_doc(db, owner=OWNER, doc_id=d.id) == ()


def test_doc_save_without_touching_body_leaves_links_untouched(db: psycopg.Connection) -> None:
    g = _goal(db)
    d = docs.create(db, owner=OWNER, path="stable.md", title="t", body=f"[g](goal:{g.id})").doc
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, title="renamed only")
    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {(link.goal_id, link.source) for link in links} == {(g.id, "doc")}


# --- link parsing: goal side, via the surgical core.goals.update hook ---------------------------


def test_goal_body_update_parses_and_rewrites_goal_side_links(db: psycopg.Connection) -> None:
    d = docs.create(db, owner=OWNER, path="money/baseline.md", title="t", body="").doc
    g = _goal(db, body="plain body, no links yet")
    assert docs.links_for_doc(db, owner=OWNER, doc_id=d.id) == ()

    goals.update(db, owner=OWNER, id=g.id, body=f"[baseline](doc:{d.path})")
    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {(link.goal_id, link.source) for link in links} == {(g.id, "goal")}

    # a non-body update (title only) must not touch the link table at all
    goals.update(db, owner=OWNER, id=g.id, title="renamed goal")
    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {(link.goal_id, link.source) for link in links} == {(g.id, "goal")}

    # editing the body to remove the link makes the row go
    goals.update(db, owner=OWNER, id=g.id, body="link removed now")
    assert docs.links_for_doc(db, owner=OWNER, doc_id=d.id) == ()


def test_goal_and_doc_can_each_declare_the_same_link_independently(db: psycopg.Connection) -> None:
    d = docs.create(db, owner=OWNER, path="both.md", title="t", body="").doc
    g = _goal(db, body="")
    goals.update(db, owner=OWNER, id=g.id, body=f"[d](doc:{d.path})")
    docs.save(db, owner=OWNER, id=d.id, expected_revision=1, body=f"[g](goal:{g.id})")

    links = docs.links_for_doc(db, owner=OWNER, doc_id=d.id)
    assert {link.source for link in links} == {"doc", "goal"}, "both sides' own declarations coexist"

    goal_links = docs.links_for_goal(db, owner=OWNER, goal_id=g.id)
    assert {link.source for link in goal_links} == {"doc", "goal"}


# --- link parsing: dangling references are skipped, not errors -----------------------------------


def test_dangling_goal_reference_in_a_doc_body_is_skipped_not_an_error(db: psycopg.Connection) -> None:
    d = docs.create(db, owner=OWNER, path="dangling.md", title="t", body="[gone](goal:ZZZZZZZZ)").doc
    assert docs.links_for_doc(db, owner=OWNER, doc_id=d.id) == ()


def test_dangling_doc_reference_in_a_goal_body_is_skipped_not_an_error(db: psycopg.Connection) -> None:
    g = _goal(db, body="")
    goals.update(db, owner=OWNER, id=g.id, body="[gone](doc:nowhere.md)")
    assert docs.links_for_goal(db, owner=OWNER, goal_id=g.id) == ()


def test_a_goal_may_not_link_another_owners_doc(db: psycopg.Connection) -> None:
    theirs = docs.create(db, owner=OTHER_OWNER, path="theirs.md", title="t", body="").doc
    g = _goal(db, body="")
    goals.update(db, owner=OWNER, id=g.id, body=f"[x](doc:{theirs.path})")
    assert docs.links_for_goal(db, owner=OWNER, goal_id=g.id) == ()


# --- owner isolation -----------------------------------------------------------------------------


def test_owner_cannot_read_or_write_another_owners_doc(db: psycopg.Connection) -> None:
    theirs = _doc(db, owner=OTHER_OWNER, path="theirs-only.md")
    with pytest.raises(NotFound):
        docs.get(db, owner=OWNER, id=theirs.id)
    with pytest.raises(NotFound):
        docs.get_by_path(db, owner=OWNER, path="theirs-only.md")
    with pytest.raises(NotFound):
        docs.save(db, owner=OWNER, id=theirs.id, expected_revision=1, body="hijacked")
    with pytest.raises(NotFound):
        docs.delete(db, owner=OWNER, id=theirs.id)
    with pytest.raises(NotFound):
        docs.history(db, owner=OWNER, id=theirs.id)


def test_tree_is_owner_scoped(db: psycopg.Connection) -> None:
    mine = _doc(db, path="mine.md")
    _doc(db, owner=OTHER_OWNER, path="theirs.md")
    listed = {d.id for d in docs.tree(db, owner=OWNER)}
    assert listed == {mine.id}


def test_goal_created_with_body_links_indexes_them_immediately(db: psycopg.Connection) -> None:
    """D250 follow-up (found by WP-3): a goal BORN with a doc link in its body must produce its
    goal_doc_links row in the same create call — not only after a later update()."""
    d = docs.create(db, owner=OWNER, path="born/linked.md", title="Linked").doc
    g = goals.create(
        db, owner=OWNER, title="Born linking", body="see [baseline](doc:born/linked.md)",
    ).goal
    linked = docs.links_for_goal(db, owner=OWNER, goal_id=g.id)
    assert [link.doc_id for link in linked] == [d.id]
    assert linked[0].source == "goal"


# --- D251 (KK, 2026-08-20): docs "ghost" down the ancestor chain -----------------------------
#
# `docs.links_for_goal_with_inherited` takes `ancestors` NEAREST-FIRST (its own docstring); every
# test below builds that argument the same way a real caller does — `goals.goal()`'s own
# `ancestors` (root-first) reversed — rather than hand-building the list, so a caller-order bug
# would show up here too.


def _nearest_first_ancestors(conn: psycopg.Connection, *, goal_id: str):
    return tuple(reversed(goals.goal(conn, owner=OWNER, id=goal_id).ancestors))


def test_grandchild_inherits_grandparent_linked_doc_with_nearest_ancestor_attribution(
    db: psycopg.Connection,
) -> None:
    d = _doc(db, path="strategy/inherit.md", title="Inherit Target")
    grandparent = _goal(db, title="Grandparent")
    goals.update(db, owner=OWNER, id=grandparent.id, body=f"[t](doc:{d.path})")
    parent = goals.create(db, owner=OWNER, title="Parent", parent_id=grandparent.id).goal
    grandchild = goals.create(db, owner=OWNER, title="Grandchild", parent_id=parent.id).goal

    result = docs.links_for_goal_with_inherited(
        db, owner=OWNER, goal_id=grandchild.id,
        ancestors=_nearest_first_ancestors(db, goal_id=grandchild.id),
    )

    assert len(result) == 1
    link = result[0]
    assert link.doc_id == d.id
    assert link.inherited_from is not None
    assert link.inherited_from.id == grandparent.id
    assert link.inherited_from.title == "Grandparent"


def test_own_link_wins_over_an_inherited_copy_of_the_same_doc(db: psycopg.Connection) -> None:
    d = _doc(db, path="strategy/own-wins.md")
    parent = _goal(db, title="Parent")
    goals.update(db, owner=OWNER, id=parent.id, body=f"[t](doc:{d.path})")
    child = goals.create(db, owner=OWNER, title="Child", parent_id=parent.id).goal
    goals.update(db, owner=OWNER, id=child.id, body=f"[t](doc:{d.path})")

    result = docs.links_for_goal_with_inherited(
        db, owner=OWNER, goal_id=child.id, ancestors=_nearest_first_ancestors(db, goal_id=child.id),
    )

    assert len(result) == 1
    assert result[0].doc_id == d.id
    assert result[0].source == "goal"
    assert result[0].inherited_from is None  # own wins, not ghosted


def test_two_ancestors_linking_the_same_doc_attributes_to_the_nearest(db: psycopg.Connection) -> None:
    d = _doc(db, path="strategy/nearest.md")
    grandparent = _goal(db, title="Grandparent")
    goals.update(db, owner=OWNER, id=grandparent.id, body=f"[t](doc:{d.path})")
    parent = goals.create(db, owner=OWNER, title="Parent", parent_id=grandparent.id).goal
    goals.update(db, owner=OWNER, id=parent.id, body=f"[t](doc:{d.path})")
    child = goals.create(db, owner=OWNER, title="Child", parent_id=parent.id).goal

    result = docs.links_for_goal_with_inherited(
        db, owner=OWNER, goal_id=child.id, ancestors=_nearest_first_ancestors(db, goal_id=child.id),
    )

    assert len(result) == 1
    assert result[0].inherited_from is not None
    assert result[0].inherited_from.id == parent.id  # nearest wins, not the grandparent


def test_inheritance_does_not_leak_sideways_to_a_sibling(db: psycopg.Connection) -> None:
    d = _doc(db, path="strategy/sideways.md")
    parent = _goal(db, title="Parent")
    child_a = goals.create(db, owner=OWNER, title="Child A", parent_id=parent.id).goal
    child_b = goals.create(db, owner=OWNER, title="Child B", parent_id=parent.id).goal
    # child_a links a doc directly — this is a SIBLING's own link, not an ancestor's, so child_b
    # (which shares only the parent, not child_a) must never see it, inherited or otherwise.
    goals.update(db, owner=OWNER, id=child_a.id, body=f"[t](doc:{d.path})")

    result_b = docs.links_for_goal_with_inherited(
        db, owner=OWNER, goal_id=child_b.id, ancestors=_nearest_first_ancestors(db, goal_id=child_b.id),
    )
    assert result_b == ()
