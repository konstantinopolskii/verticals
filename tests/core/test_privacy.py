"""Privacy mode: the `private` flag, its subtree cover and the owner's mode and rules."""

from __future__ import annotations

import psycopg
import pytest

from verticals.core import goals, privacy
from verticals.core.errors import ValidationError

OWNER = "SYN-privacy-owner"


def test_private_covers_subtree_and_leaves_content_revision(db: psycopg.Connection) -> None:
    root = goals.create(db, owner=OWNER, title="SYN private root").goal
    child = goals.create(db, owner=OWNER, title="SYN private child", parent_id=root.id).goal
    other = goals.create(db, owner=OWNER, title="SYN public").goal
    goals.create(db, owner="SYN-someone-else", title="SYN foreign")

    assert privacy.view(db, owner=OWNER) == {"mode": False, "hidden": []}
    updated = goals.update(db, owner=OWNER, ids=[root.id], private=True)
    assert updated[0].goal.private is True
    revision = db.execute("SELECT content_revision FROM goals WHERE id = %s", (root.id,)).fetchone()[0]
    assert revision == 0

    assert privacy.view(db, owner=OWNER)["hidden"] == sorted([root.id, child.id])
    assert other.id not in privacy.view(db, owner=OWNER)["hidden"]
    assert privacy.status(db, owner=OWNER)["private"] == [{"id": root.id, "title": "SYN private root"}]

    goals.update(db, owner=OWNER, id=root.id, private=False)
    assert privacy.view(db, owner=OWNER)["hidden"] == []


def test_mode_and_rules_are_per_owner(db: psycopg.Connection) -> None:
    privacy.set_mode(db, owner=OWNER, mode=True)
    privacy.set_rules(db, owner=OWNER, rules="  tasks that name other people ")
    assert privacy.status(db, owner=OWNER) == {
        "mode": True, "rules": "tasks that name other people", "private": [],
    }
    privacy.set_mode(db, owner=OWNER, mode=False)
    assert privacy.status(db, owner=OWNER)["rules"] == "tasks that name other people"
    assert privacy.view(db, owner="SYN-someone-else")["mode"] is False


def test_refuses_bad_values(db: psycopg.Connection) -> None:
    target = goals.create(db, owner=OWNER, title="SYN refuse").goal
    with pytest.raises(ValidationError):
        goals.update(db, owner=OWNER, id=target.id, private="yes")
    with pytest.raises(ValidationError):
        privacy.set_mode(db, owner=OWNER, mode=1)
    with pytest.raises(ValidationError):
        privacy.set_rules(db, owner=OWNER, rules="x" * (privacy.MAX_RULES_CHARS + 1))
