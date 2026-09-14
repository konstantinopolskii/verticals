"""WP-33 (docs/EVIDENCE.md §10, S-136..S-144) — evidence metadata through real core calls and
real Postgres; no mocks. Groups 1-6 and 8 of the spec's acceptance list live here; group 7
(reader summaries over MCP) is tests/mcp/test_evidence_tools.py's; group 9 (backup) extends
tests/pipeline/test_backup.py.

The trigger tests talk SQL directly on purpose: `content_revision`'s whole contract is that the
DATABASE bumps it, whichever path wrote the row — proving that through `core.goals.update`
alone would leave "app code did the bump" as an undetected implementation. One test each way:
raw UPDATE (the trigger alone) and the core verb (the shipped path).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from verticals.core import evidence, goals
from verticals.core.errors import NotFound, RevisionMismatch, ValidationError

OWNER = "evidence-core"
OTHER_OWNER = "evidence-other"

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
# review_after is compared against the REAL wall clock inside core (`as_of = now(utc)`), so a
# fixed offset from NOW is a time bomb: NOW + 7 days expired mid-day 2026-08-18 and demoted
# every "just verified" row to stale. Keep it relative to the actual clock — always a year out.
LATER = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=365)

PAYLOAD = {
    "identity": {"project": "207", "disambiguation": "synthetic"},
    "sources": [
        {"id": "S1", "type": "transcript", "ref": "SYNREF01", "date": "2026-07-31", "read_scope": "full"},
    ],
    "claims": [{"id": "C1", "text": "a short agent formulation", "source_ids": ["S1"]}],
    "unresolved": ["one open question"],
}


def _goal(conn: psycopg.Connection, *, owner: str = OWNER, title: str = "Synthetic subject"):
    return goals.create(conn, owner=owner, title=title, body="a body", tags=["t1"]).goal


def _revision(conn: psycopg.Connection, goal_id: str) -> int:
    (rev,) = conn.execute("SELECT content_revision FROM goals WHERE id = %s", (goal_id,)).fetchone()
    return rev


def _verify(conn: psycopg.Connection, goal_id: str, *, review_after=LATER, owner: str = OWNER):
    return evidence.evidence_update(
        conn, owner=owner, goal_id=goal_id,
        expected_content_revision=_revision(conn, goal_id),
        status="verified", verified_at=NOW, source_cutoff_at=NOW, review_after=review_after,
        payload=PAYLOAD,
    )


# --- group 1-2: the trigger ----------------------------------------------------------------------


def test_trigger_bumps_on_each_watched_column(db: psycopg.Connection) -> None:
    g = _goal(db)
    assert _revision(db, g.id) == 0

    watched = [
        ("title", "'renamed'"),
        ("body", "'rewritten'"),
        ("vertical", "'day'"),
        ("anchor_date", "DATE '2026-08-11'"),
        ("period_key", "'2026-08-11'"),  # rides along with vertical; NOT watched alone — no bump expected for it
        ("done_at", "now()"),
        ("tags", "ARRAY['t1','t2']"),
    ]
    # Raw single-column UPDATEs, so the DB alone is on the hook. period_key is set in the same
    # breath as vertical needs it (constraint vertical_period_together), so vertical+period_key
    # land as one statement = one bump.
    db.execute("UPDATE goals SET title = 'renamed' WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 1
    db.execute("UPDATE goals SET body = 'rewritten' WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 2
    db.execute(
        "UPDATE goals SET vertical = 'day', anchor_date = DATE '2026-08-11', "
        "period_key = '2026-08-11', parked_from_vertical = NULL WHERE id = %s",
        (g.id,),
    )
    assert _revision(db, g.id) == 3, "vertical+anchor_date+period_key in one statement = one bump"
    db.execute("UPDATE goals SET done_at = now() WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 4
    db.execute("UPDATE goals SET tags = ARRAY['t1','t2'] WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 5
    db.execute("""UPDATE goals SET repeat_rule = '{"frequency":"daily"}'::jsonb,
                  repeat_series_id = id, repeat_index = 0, repeat_start_date = anchor_date
                  WHERE id = %s""", (g.id,))
    assert _revision(db, g.id) == 6, "repeat_rule counts; the identity fields ride along in the same statement"
    assert watched  # documents the list this test walked


def test_trigger_bumps_once_for_a_multi_column_update(db: psycopg.Connection) -> None:
    g = _goal(db)
    db.execute("UPDATE goals SET title = 'both', body = 'at once', tags = ARRAY['x'] WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 1, "one statement = one meaning change = +1, however many columns"


def test_trigger_ignores_color_position_and_evidence_writes(db: psycopg.Connection) -> None:
    g = _goal(db)
    db.execute("UPDATE goals SET color = '#278dea' WHERE id = %s", (g.id,))
    db.execute("UPDATE goals SET position = 40 WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 0, "color and position are presentation, not meaning"

    before = db.execute("SELECT content_revision, updated_at FROM goals WHERE id = %s", (g.id,)).fetchone()
    _verify(db, g.id)
    after = db.execute("SELECT content_revision, updated_at FROM goals WHERE id = %s", (g.id,)).fetchone()
    assert after == before, "an evidence write must not touch the goals row at all"


def test_trigger_done_transition_not_timestamp_value(db: psycopg.Connection) -> None:
    g = _goal(db)
    db.execute("UPDATE goals SET done_at = now() WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 1
    db.execute("UPDATE goals SET done_at = now() + interval '1 hour' WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 1, "done_at value drift is noise; only the NULL<->NOT NULL transition counts"
    db.execute("UPDATE goals SET done_at = NULL WHERE id = %s", (g.id,))
    assert _revision(db, g.id) == 2


def test_shipped_core_update_rides_the_same_trigger(db: psycopg.Connection) -> None:
    g = _goal(db)
    goals.update(db, owner=OWNER, id=g.id, title="via core")
    assert _revision(db, g.id) == 1, "the shipped write path bumps through the trigger, no app-level double-bump"


# --- group 3: the composite FK -------------------------------------------------------------------


def test_fk_refuses_an_owner_that_drifted_from_the_goal(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO goal_evidence (goal_id, owner, status, verified_against_revision) "
            "VALUES (%s, %s, 'unverified', 0)",
            (g.id, OTHER_OWNER),
        )


def test_goal_delete_cascades_the_evidence_row(db: psycopg.Connection) -> None:
    g = _goal(db)
    _verify(db, g.id)
    assert db.execute("SELECT count(*) FROM goal_evidence WHERE goal_id = %s", (g.id,)).fetchone() == (1,)
    goals.delete(db, owner=OWNER, id=g.id)
    assert db.execute("SELECT count(*) FROM goal_evidence WHERE goal_id = %s", (g.id,)).fetchone() == (0,)


# --- group 4: every branch of §5's formula -------------------------------------------------------


def test_effective_no_row_is_unverified(db: psycopg.Connection) -> None:
    g = _goal(db)
    detail = evidence.detail_for(db, owner=OWNER, goal_id=g.id)
    assert detail["status"] == "unverified"
    assert detail["stored_status"] is None
    assert detail["payload"] == {}
    summary = evidence.summaries_for(db, owner=OWNER, ids=[g.id])[g.id]
    assert summary == {"status": "unverified", "verified_at": None, "review_after": None}


def test_effective_stored_non_verified_statuses_pass_through(db: psycopg.Connection) -> None:
    g = _goal(db)
    for stored in ("unverified", "index_only", "partial"):
        evidence.evidence_update(
            db, owner=OWNER, goal_id=g.id, expected_content_revision=_revision(db, g.id),
            status=stored, payload={},
        )
        assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == stored


def test_effective_partial_with_revision_mismatch_stays_partial(db: psycopg.Connection) -> None:
    """§5's stated consequence: stale only demotes verified."""
    g = _goal(db)
    evidence.evidence_update(
        db, owner=OWNER, goal_id=g.id, expected_content_revision=0, status="partial", payload={},
    )
    goals.update(db, owner=OWNER, id=g.id, title="meaning changed")
    assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == "partial"


def test_effective_verified_demotes_to_stale_on_revision_mismatch(db: psycopg.Connection) -> None:
    g = _goal(db)
    _verify(db, g.id)
    assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == "verified"
    goals.update(db, owner=OWNER, id=g.id, body="meaning changed")
    assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == "stale"


def test_effective_verified_demotes_to_stale_past_review_after(db: psycopg.Connection) -> None:
    g = _goal(db)
    _verify(db, g.id, review_after=NOW - timedelta(seconds=1))
    assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == "stale"


def test_effective_verified_with_null_review_after_never_expires(db: psycopg.Connection) -> None:
    g = _goal(db)
    _verify(db, g.id, review_after=None)
    assert evidence.detail_for(db, owner=OWNER, goal_id=g.id)["status"] == "verified"


# --- group 5: evidence_update semantics ----------------------------------------------------------


def test_update_success_stamps_verified_against_revision(db: psycopg.Connection) -> None:
    g = _goal(db)
    goals.update(db, owner=OWNER, id=g.id, title="rev 1")
    result = _verify(db, g.id)
    assert result.replayed is False
    assert result.evidence["verified_against_revision"] == 1
    assert result.evidence["content_revision"] == 1
    assert result.evidence["evidence_revision"] == 0
    assert result.evidence["payload"] == PAYLOAD


def test_update_refuses_a_stale_content_revision_with_the_current_one(db: psycopg.Connection) -> None:
    g = _goal(db)
    goals.update(db, owner=OWNER, id=g.id, title="rev 1")
    with pytest.raises(RevisionMismatch) as excinfo:
        evidence.evidence_update(
            db, owner=OWNER, goal_id=g.id, expected_content_revision=0,
            status="verified", verified_at=NOW, payload={},
        )
    assert excinfo.value.detail["content_revision"] == 1
    assert db.execute("SELECT count(*) FROM goal_evidence WHERE goal_id = %s", (g.id,)).fetchone() == (0,)


def test_update_refuses_a_stale_evidence_revision(db: psycopg.Connection) -> None:
    g = _goal(db)
    _verify(db, g.id)  # evidence_revision now 0
    evidence.evidence_update(  # second write, unguarded: revision now 1
        db, owner=OWNER, goal_id=g.id, expected_content_revision=0, status="partial", payload={},
    )
    with pytest.raises(RevisionMismatch) as excinfo:
        evidence.evidence_update(
            db, owner=OWNER, goal_id=g.id, expected_content_revision=0,
            expected_evidence_revision=0, status="partial", payload={},
        )
    assert excinfo.value.detail["evidence_revision"] == 1


def test_update_unknown_and_foreign_ids_raise_indistinguishable_notfound(db: psycopg.Connection) -> None:
    foreign = _goal(db, owner=OTHER_OWNER)
    kwargs = dict(expected_content_revision=0, status="unverified", payload={})
    with pytest.raises(NotFound) as unknown_exc:
        evidence.evidence_update(db, owner=OWNER, goal_id="ZZZZZZZZ", **kwargs)
    with pytest.raises(NotFound) as foreign_exc:
        evidence.evidence_update(db, owner=OWNER, goal_id=foreign.id, **kwargs)
    # Same TYPE and same message SHAPE (S-41's contract; the id in the text is the caller's own
    # input, present in both). Neither says anything a caller did not already know.
    assert str(unknown_exc.value) == f"no goal 'ZZZZZZZZ' for owner {OWNER!r}"
    assert str(foreign_exc.value) == f"no goal {foreign.id!r} for owner {OWNER!r}"


def test_update_replay_via_client_token_writes_nothing_twice(db: psycopg.Connection) -> None:
    g = _goal(db)
    kwargs = dict(
        owner=OWNER, goal_id=g.id, expected_content_revision=0,
        status="verified", verified_at=NOW, review_after=LATER, payload=PAYLOAD,
        client_token="evidence-token-1",
    )
    first = evidence.evidence_update(db, **kwargs)
    replay = evidence.evidence_update(db, **kwargs)
    assert first.replayed is False and replay.replayed is True
    assert replay.evidence == first.evidence
    (ev_rev,) = db.execute("SELECT evidence_revision FROM goal_evidence WHERE goal_id = %s", (g.id,)).fetchone()
    assert ev_rev == 0, "a replay must not increment evidence_revision"


def test_update_refuses_verified_without_timestamp_and_bad_payloads(db: psycopg.Connection) -> None:
    g = _goal(db)
    with pytest.raises(ValidationError):
        evidence.evidence_update(
            db, owner=OWNER, goal_id=g.id, expected_content_revision=0, status="verified", payload={},
        )
    bad_payloads = [
        {"unknown_key": 1},
        {"sources": [{"id": "S1"}, {"id": "S1"}]},  # duplicate source id
        {"claims": [{"id": "C1", "text": "x", "source_ids": ["S9"]}]},  # dangling source ref
        {"unresolved": [42]},
    ]
    for bad in bad_payloads:
        with pytest.raises(ValidationError):
            evidence.evidence_update(
                db, owner=OWNER, goal_id=g.id, expected_content_revision=0, status="partial", payload=bad,
            )
    assert db.execute("SELECT count(*) FROM goal_evidence WHERE goal_id = %s", (g.id,)).fetchone() == (0,)


# --- group 6: evidence_due -----------------------------------------------------------------------


def test_due_projection_is_slim_and_filters_on_effective_status(db: psycopg.Connection) -> None:
    fresh = _goal(db, title="never touched")            # no row -> unverified
    partial = _goal(db, title="partial one")
    evidence.evidence_update(db, owner=OWNER, goal_id=partial.id, expected_content_revision=0,
                             status="partial", payload={})
    verified = _goal(db, title="green one")
    _verify(db, verified.id)                            # verified, review LATER -> not due now
    stale = _goal(db, title="drifted one")
    _verify(db, stale.id)
    goals.update(db, owner=OWNER, id=stale.id, title="meaning moved")  # -> stale

    result = evidence.due(db, owner=OWNER, due_before=NOW)
    by_id = {item["goal_id"]: item for item in result.items}
    assert set(by_id) == {fresh.id, partial.id, stale.id}, "verified-and-current is never due"
    assert by_id[stale.id]["effective_status"] == "stale"
    assert by_id[partial.id]["effective_status"] == "partial"
    for item in result.items:
        assert "payload" not in item, "the worklist is slim by contract — never the payload"
        assert set(item) == {
            "goal_id", "title", "vertical", "anchor_date", "effective_status",
            "verified_at", "review_after", "content_revision", "verified_against_revision",
        }

    only_stale = evidence.due(db, owner=OWNER, due_before=NOW, statuses=["stale"])
    assert {i["goal_id"] for i in only_stale.items} == {stale.id}

    # due_before as "what will be due by then": the LATER deadline crosses, verified joins the list
    future = evidence.due(db, owner=OWNER, due_before=LATER + timedelta(seconds=1), statuses=["stale"])
    assert verified.id in {i["goal_id"] for i in future.items}


def test_due_pagination_is_exhaustive_and_non_overlapping(db: psycopg.Connection) -> None:
    ids = {_goal(db, title=f"bulk {i}").id for i in range(7)}  # all unverified, review_after NULL
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = evidence.due(db, owner=OWNER, limit=3, cursor=cursor)
        seen.extend(item["goal_id"] for item in page.items)
        pages += 1
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert pages == 3
    assert len(seen) == len(set(seen)) == 7, "pages must neither overlap nor drop rows"
    assert set(seen) == ids  # exhaustive; the intra-page order is the database's own id collation

    with pytest.raises(ValidationError):
        evidence.due(db, owner=OWNER, cursor="not-a-token")
    with pytest.raises(ValidationError):
        evidence.due(db, owner=OWNER, limit=evidence.DUE_MAX_LIMIT + 1)


def test_due_orders_null_review_first_then_deadlines_ascending(db: psycopg.Connection) -> None:
    never = _goal(db, title="no evidence at all")
    soon = _goal(db, title="due soon")
    _verify(db, soon.id, review_after=NOW - timedelta(days=2))
    later = _goal(db, title="due later")
    _verify(db, later.id, review_after=NOW - timedelta(days=1))

    result = evidence.due(db, owner=OWNER, due_before=NOW)
    assert [i["goal_id"] for i in result.items] == [never.id, soon.id, later.id], (
        "a goal with no evidence row has no review_after and is the most due thing there is"
    )


def test_due_is_owner_scoped(db: psycopg.Connection) -> None:
    mine = _goal(db)
    theirs = _goal(db, owner=OTHER_OWNER)
    listed = {i["goal_id"] for i in evidence.due(db, owner=OWNER).items}
    assert mine.id in listed and theirs.id not in listed


# --- group 8: repeat interaction -----------------------------------------------------------------


def test_next_occurrence_starts_unverified(db: psycopg.Connection) -> None:
    first = goals.create(
        db, owner=OWNER, title="Recurring subject", vertical="day", anchor_date=date(2026, 8, 10),
    ).goal
    goals.update(db, owner=OWNER, id=first.id, repeat={"frequency": "daily", "interval": 1})
    _verify(db, first.id)

    goals.update(db, owner=OWNER, id=first.id, done=True)  # materializes occurrence 1
    (next_id,) = db.execute(
        "SELECT id FROM goals WHERE owner = %s AND repeat_series_id = %s AND repeat_index = 1",
        (OWNER, first.id),
    ).fetchone()
    detail = evidence.detail_for(db, owner=OWNER, goal_id=next_id)
    assert detail["status"] == "unverified" and detail["stored_status"] is None, (
        "a materialized occurrence is a new row: no evidence copied, effective unverified (§7 safe v1)"
    )
