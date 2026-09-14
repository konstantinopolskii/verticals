from __future__ import annotations

import psycopg

from verticals.core import goals, tag_meta


def test_mark_unmark_and_list_tags_without_inventing_goals(db: psycopg.Connection) -> None:
    goals.create(db, owner="tag-owner", title="Synthetic tagged", tags=["SYNTAG1", "plain"])
    before = db.execute("SELECT count(*) FROM goals").fetchone()[0]

    assert tag_meta.mark(db, owner="tag-owner", tag="SYNTAG1", project=True) == {
        "tag": "SYNTAG1", "project": True,
    }
    assert tag_meta.mark(db, owner="tag-owner", tag="SYNUNKNOWN", project=True)["project"] is True
    listed = {row["tag"]: row["project"] for row in tag_meta.list_tags(db, owner="tag-owner")}
    assert listed == {"SYNTAG1": True, "SYNUNKNOWN": True, "plain": False}
    assert db.execute("SELECT count(*) FROM goals").fetchone()[0] == before

    tag_meta.mark(db, owner="tag-owner", tag="SYNTAG1", project=False)
    listed = {row["tag"]: row["project"] for row in tag_meta.list_tags(db, owner="tag-owner")}
    assert listed["SYNTAG1"] is False
