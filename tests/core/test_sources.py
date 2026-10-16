"""Sources (docs/design/sources.md, `core/sources.py`, `018_sources.sql`) against a real database, on a clock the test
moves by hand: the two-failures rule, grey that is never red, an approval bound to the exact check, and the claim that
keeps two passes from running one check twice."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from verticals.core import docs as core_docs
from verticals.core import source_checks as sc
from verticals.core import sources as core
from verticals.core.errors import NotFound, RevisionMismatch, ValidationError
from verticals.core.sources import GREY, OK, RED, Result

OWNER = "SYN-sources-owner"
OTHER = "SYN-sources-other"
T0 = datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)

HTTP = {"kind": "http", "url": "https://example.test/health"}
MCP = {"kind": "mcp", "url": "http://127.0.0.1:9100/mcp", "tool": "get_status", "args": {"scope": "all"}}
FILE = {"kind": "file", "path": "~/logs/run.log", "max_age_hours": 26}
# The state machine below (the two-failures rule, grey, ordering) is shown on a name lookup, approved first: nothing in those
# rules depends on what a check reaches. The tests of approval itself use every kind.
NAME = {"kind": "dns", "host": "example.test"}
CMD = {"kind": "cmd", "argv": ["/bin/echo", "disk 71% used"], "parse": r"(\d+)%", "max": 90}
GOOD = Result(ok=True, detail="HTTP 200", ms=12)
BAD = Result(ok=False, detail="HTTP 503", ms=9)


def _source(db: psycopg.Connection, name: str, raw: dict | None, *, owner: str = OWNER, approved: bool = True) -> core.Source:
    """A source document. Every check the agent writes waits for the owner, so unless `approved` is False the owner has
    pressed Approve on it, and the state machine can be looked at."""
    body = "No check here." if raw is None else sc.build_body(
        gives="Something.", how="Read it.", since="Every hour.", check=sc.Check.from_dict(raw), fixes=[])
    doc = core_docs.create(db, owner=owner, path=f"sources/{name}.md", title=name.title(), body=body).doc
    source = core.find(db, owner=owner, ref=doc.id)
    if approved and source.check is not None:
        core.approve(db, owner=owner, doc_id=source.id, check_hash=source.check.hash, now=T0)
        source = core.find(db, owner=owner, ref=doc.id)
    return source


def _edit(db: psycopg.Connection, source: core.Source, raw: dict, *, approve: bool = True) -> core.Source:
    """The check in the document changes; by default the owner approves the new text, as the state tests need."""
    current = core.find(db, owner=OWNER, ref=source.id)
    body = sc.set_section(current.body, "check", sc.render_block(sc.Check.from_dict(raw)))
    core_docs.save(db, owner=OWNER, id=source.id, expected_revision=current.revision, body=body)
    changed = core.find(db, owner=OWNER, ref=source.id)
    if approve:
        core.approve(db, owner=OWNER, doc_id=source.id, check_hash=changed.check.hash, now=T0)
        changed = core.find(db, owner=OWNER, ref=source.id)
    return changed


def _look(db: psycopg.Connection, source: core.Source, now: datetime) -> core.View:
    return core.view(core.find(db, owner=OWNER, ref=source.id), now)


def _record(db: psycopg.Connection, source: core.Source, result: Result, now: datetime) -> core.Recorded:
    return core.record(db, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, result=result, now=now)


# --- the two-failures rule -------------------------------------------------------------------------------------------


def test_one_failure_is_looked_at_again_quietly_and_two_make_red(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    first = _record(db, source, GOOD, T0)
    assert (first.failures, first.next_check_at) == (0, T0 + timedelta(hours=1))
    assert _look(db, source, T0 + MIN).status == OK

    # The hour comes round and the check fails: still not red, and the next look is in five minutes.
    t1 = T0 + timedelta(hours=1)
    one = _record(db, source, BAD, t1)
    assert (one.failures, one.turned_red, one.next_check_at) == (1, False, t1 + timedelta(minutes=5))
    quiet = _look(db, source, t1 + MIN)
    assert (quiet.status, quiet.why, quiet.since) == (OK, None, None)

    # Five minutes later it fails again: red, "not answering since" the first failure.
    t2 = t1 + timedelta(minutes=5)
    two = _record(db, source, BAD, t2)
    assert (two.failures, two.turned_red) == (2, True)
    assert two.next_check_at == t2 + timedelta(hours=1)
    red = _look(db, source, t2 + MIN)
    assert (red.status, red.since, red.detail, red.checked_at) == (RED, t1, "HTTP 503", t2)

    # Still failing at the next hourly look: still red, not "newly" red, and the first failure is still the start.
    t3 = t2 + timedelta(hours=1)
    three = _record(db, source, BAD, t3)
    assert (three.failures, three.turned_red) == (3, False)
    assert _look(db, source, t3).since == t1


def test_a_failure_that_comes_too_soon_is_not_the_second(db: psycopg.Connection) -> None:
    """The agent runs a check by hand a minute after the timer saw it fail: that is the same incident."""
    source = _source(db, "web", NAME)
    _record(db, source, BAD, T0)
    soon = _record(db, source, BAD, T0 + 2 * MIN)
    assert (soon.failures, soon.turned_red) == (1, False)
    assert soon.next_check_at == T0 + timedelta(minutes=5), "the quiet look stays five minutes after the first failure"
    assert _look(db, source, T0 + 3 * MIN).status == OK
    later = _record(db, source, BAD, T0 + timedelta(minutes=6))
    assert (later.failures, later.turned_red) == (2, True)
    assert _look(db, source, T0 + timedelta(minutes=7)).since == T0


def test_a_pass_clears_red_at_once_and_says_so(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    _record(db, source, BAD, T0)
    _record(db, source, BAD, T0 + timedelta(minutes=5))
    back = _record(db, source, GOOD, T0 + timedelta(minutes=65))
    assert (back.failures, back.recovered, back.turned_red) == (0, True, False)
    green = _look(db, source, T0 + timedelta(minutes=66))
    assert (green.status, green.since, green.detail) == (OK, None, "HTTP 200")
    # A fresh failure after that starts the count from one again.
    again = _record(db, source, BAD, T0 + timedelta(minutes=125))
    assert (again.failures, again.turned_red) == (1, False)


def test_an_answer_to_an_edited_check_starts_the_count_again(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    _record(db, source, BAD, T0)
    _record(db, source, BAD, T0 + timedelta(minutes=5))
    assert _look(db, source, T0 + timedelta(minutes=6)).status == RED

    edited = _edit(db, source, {**NAME, "host": "ready.example.test"})
    # The old answers say nothing about the new check: grey until it has run once.
    seen = core.view(edited, T0 + timedelta(minutes=7))
    assert (seen.status, seen.why, seen.detail, seen.checked_at) == (GREY, core.NEW, "", None)
    assert core.due(edited, T0 + timedelta(minutes=7)), "a changed check is looked at now, not at the next hour"
    fresh = core.record(db, owner=OWNER, doc_id=edited.id, check_hash=edited.check.hash, result=BAD,
                        now=T0 + timedelta(minutes=8))
    assert (fresh.failures, fresh.turned_red) == (1, False)


# --- grey is never red -----------------------------------------------------------------------------------------------


def test_an_answer_older_than_two_hours_is_grey_not_red(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    _record(db, source, BAD, T0)
    _record(db, source, BAD, T0 + timedelta(minutes=5))
    t = T0 + timedelta(minutes=5)
    assert core.view(core.find(db, owner=OWNER, ref=source.id), t + timedelta(hours=1, minutes=59)).status == RED
    asleep = core.view(core.find(db, owner=OWNER, ref=source.id), t + timedelta(hours=2, minutes=1))
    assert (asleep.status, asleep.why, asleep.checked_at) == (GREY, core.STALE_ANSWER, t)
    assert asleep.since is None
    # The same for a source that was fine.
    other = _source(db, "mail", NAME)
    _record(db, other, GOOD, T0)
    assert core.view(core.find(db, owner=OWNER, ref=other.id), T0 + timedelta(hours=3)).why == core.STALE_ANSWER


def test_a_source_with_no_check_or_an_unreadable_one_or_no_answer_yet_is_grey(db: psycopg.Connection) -> None:
    plain = _source(db, "notes", None)
    assert (core.view(plain, T0).status, core.view(plain, T0).why) == (GREY, core.NO_CHECK)
    assert not core.due(plain, T0)
    broken = core_docs.create(db, owner=OWNER, path="sources/broken.md", title="Broken",
                              body="```check\n{\"kind\": \"cmd\", \"argv\": \"df -k /\"}\n```").doc
    unreadable = core.view(core.find(db, owner=OWNER, ref=broken.id), T0)
    assert (unreadable.status, unreadable.why) == (GREY, core.UNREADABLE)
    assert "never a shell line" in unreadable.error
    fresh = _source(db, "web", NAME)
    assert (core.view(fresh, T0).why, core.due(fresh, T0)) == (core.NEW, True)


# --- approval --------------------------------------------------------------------------------------------------------


def test_a_command_waits_for_the_owner_and_only_for_that_exact_check(db: psycopg.Connection) -> None:
    source = _source(db, "disk", CMD, approved=False)
    waiting = core.view(source, T0)
    assert (waiting.status, waiting.why, waiting.needs_approval, waiting.approved) == (GREY, core.WAITING, True, False)
    assert waiting.summary.startswith("Runs /bin/echo 'disk 71% used' on this Mac")
    assert not core.due(source, T0), "an unapproved command is never run"

    with pytest.raises(RevisionMismatch):
        core.approve(db, owner=OWNER, doc_id=source.id, check_hash="0" * 64, now=T0)
    assert core.view(core.find(db, owner=OWNER, ref=source.id), T0).why == core.WAITING

    approved = core.approve(db, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, now=T0)
    assert (approved.approved, approved.needs_approval, approved.why) == (True, False, core.NEW)
    assert core.due(core.find(db, owner=OWNER, ref=source.id), T0), "approving makes it due now"

    # The agent changes one word of the command: paused again until the owner approves that.
    changed = _edit(db, source, {**CMD, "argv": ["/bin/echo", "disk 95% used"]}, approve=False)
    assert core.view(changed, T0).why == core.WAITING and not core.due(changed, T0)
    # The old approval does not fit the new text.
    with pytest.raises(RevisionMismatch):
        core.approve(db, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, now=T0)
    # Changing the text back to what was approved needs no new approval.
    restored = _edit(db, source, CMD, approve=False)
    assert core.view(restored, T0).why == core.NEW and core.due(restored, T0)


def test_every_check_waits_for_the_owner_once_and_only_the_apps_own_does_not(db: psycopg.Connection) -> None:
    for name, raw in (("web", HTTP), ("tool", MCP), ("disk", CMD), ("log", FILE), ("host", NAME)):
        source = _source(db, name, raw, approved=False)
        seen = core.view(source, T0)
        assert (seen.status, seen.why, seen.needs_approval, seen.approved) == (GREY, core.WAITING, True, False), name
        assert not core.due(source, T0), f"an unapproved {raw['kind']} check is never run"
        approved = core.approve(db, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, now=T0)
        assert (approved.approved, approved.needs_approval, approved.why) == (True, False, core.NEW), name
        assert core.due(core.find(db, owner=OWNER, ref=source.id), T0), f"approved, a {raw['kind']} check is due now"

    # The app's own check of the agent's servers is written by the app and runs without asking; there is nothing to approve.
    own = core.find(db, owner=OWNER, ref=core.ensure_connections(db, owner=OWNER))
    assert (core.view(own, T0).needs_approval, core.view(own, T0).why) == (False, core.NEW)
    assert core.due(own, T0), "the app asks about its own connections without asking anyone"
    with pytest.raises(ValidationError, match="needs no approval"):
        core.approve(db, owner=OWNER, doc_id=own.id, check_hash=own.check.hash, now=T0)
    plain = _source(db, "notes", None)
    with pytest.raises(ValidationError, match="no check to approve"):
        core.approve(db, owner=OWNER, doc_id=plain.id, check_hash="x", now=T0)
    with pytest.raises(NotFound):
        core.approve(db, owner=OWNER, doc_id="NOSUCHID", check_hash="x", now=T0)


def test_an_address_waits_again_when_any_part_of_it_changes_and_the_summary_shows_what_is_sent(db: psycopg.Connection) -> None:
    web = _source(db, "web", HTTP, approved=False)
    core.approve(db, owner=OWNER, doc_id=web.id, check_hash=web.check.hash, now=T0)
    assert core.view(core.find(db, owner=OWNER, ref=web.id), T0).why == core.NEW
    # The address, the field it reads, the limit: each is a different check, and none rides on the old approval.
    for change in ({"url": "https://example.test/other"}, {"url": "https://example.test/health?a=1"}, {"status": 204},
                   {"value": "queue.depth"}, {"expect": {"status": "ok"}}):
        edited = _edit(db, web, {**HTTP, **change}, approve=False)
        seen = core.view(edited, T0)
        assert (seen.why, seen.approved, seen.needs_approval) == (core.WAITING, False, True), change
        _edit(db, web, HTTP, approve=False)  # back to what was approved: no new approval needed
    tool = _source(db, "tool", MCP, approved=False)
    assert core.view(tool, T0).summary == (
        'Calls the tool get_status of http://127.0.0.1:9100/mcp with {"scope": "all"} every hour.'), "what is sent is shown"
    core.approve(db, owner=OWNER, doc_id=tool.id, check_hash=tool.check.hash, now=T0)
    changed = _edit(db, tool, {**MCP, "args": {"scope": "everything"}}, approve=False)
    assert core.view(changed, T0).why == core.WAITING, "other arguments are another check"


def test_an_owner_sees_and_approves_only_their_own_sources(db: psycopg.Connection) -> None:
    mine = _source(db, "disk", CMD)
    _source(db, "theirs", NAME, owner=OTHER)
    assert [s.path for s in core.sources(db, owner=OWNER)] == ["sources/disk.md"]
    with pytest.raises(NotFound):
        core.approve(db, owner=OTHER, doc_id=mine.id, check_hash=mine.check.hash, now=T0)
    with pytest.raises(NotFound):
        core.find(db, owner=OTHER, ref="sources/disk.md")


# --- who runs a check, and when --------------------------------------------------------------------------------------


def test_a_check_is_due_when_its_time_comes_and_one_pass_takes_it(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    assert core.due(source, T0)
    assert core.claim(db, owner=OWNER, source=source, now=T0)
    # A second pass that read the same row loses the claim: the first pass owns the check for ten minutes.
    assert not core.claim(db, owner=OWNER, source=source, now=T0)
    held = core.find(db, owner=OWNER, ref=source.id)
    assert held.row.leased_until == T0 + core.LEASE
    assert not core.due(held, T0 + 5 * MIN), "nobody else runs what a pass is running"
    assert not core.claim(db, owner=OWNER, source=source, now=T0 + 5 * MIN)

    _record(db, source, GOOD, T0 + MIN)
    done = core.find(db, owner=OWNER, ref=source.id)
    assert done.row.leased_until is None
    assert not core.due(done, T0 + timedelta(minutes=59)) and core.due(done, T0 + timedelta(minutes=61))
    # A pass that crashed after its claim leaves nothing stuck: the lease runs out and the next pass takes over.
    assert core.claim(db, owner=OWNER, source=done, now=T0 + timedelta(minutes=61))
    crashed = core.find(db, owner=OWNER, ref=source.id)
    assert not core.due(crashed, T0 + timedelta(minutes=65))
    assert core.due(crashed, T0 + timedelta(minutes=72))
    assert core.claim(db, owner=OWNER, source=crashed, now=T0 + timedelta(minutes=72))


def test_the_row_of_tiles_puts_what_needs_a_look_first(db: psycopg.Connection) -> None:
    red = _source(db, "zeta", NAME)
    _source(db, "yankee", CMD, approved=False)
    stale = _source(db, "whisky", NAME)
    _source(db, "victor", NAME)
    fine = _source(db, "alpha", NAME)
    _record(db, red, BAD, T0 + timedelta(hours=4))
    _record(db, red, BAD, T0 + timedelta(hours=4, minutes=5))
    _record(db, stale, GOOD, T0)
    _record(db, fine, GOOD, T0 + timedelta(hours=4))
    order = [(v.path, v.status, v.why) for v in core.views(db, owner=OWNER, now=T0 + timedelta(hours=4, minutes=10))]
    assert order == [
        ("sources/zeta.md", RED, None),
        ("sources/yankee.md", GREY, core.WAITING),
        ("sources/whisky.md", GREY, core.STALE_ANSWER),
        ("sources/victor.md", GREY, core.NEW),
        ("sources/alpha.md", OK, None),
    ]
    assert all(v.excerpt for v in core.views(db, owner=OWNER, now=T0))


def test_an_answer_is_one_printable_line(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    _record(db, source, Result(ok=False, detail="line one\nline two\x07 " + "x" * 400), T0)
    detail = core.view(core.find(db, owner=OWNER, ref=source.id), T0).detail
    assert "\n" not in detail and "\x07" not in detail and len(detail) <= core.MAX_DETAIL and detail.endswith("…")
    assert core.one_line("  a \t b\n c ") == "a b c"


# --- the document goes, the answers go -------------------------------------------------------------------------------


def test_deleting_the_document_takes_its_answers(db: psycopg.Connection) -> None:
    source = _source(db, "web", NAME)
    _record(db, source, GOOD, T0)
    assert db.execute("SELECT count(*) FROM source_state").fetchone() == (1,)
    core_docs.delete(db, owner=OWNER, id=source.id)
    assert db.execute("SELECT count(*) FROM source_state").fetchone() == (0,)


def test_a_document_outside_sources_is_not_a_source(db: psycopg.Connection) -> None:
    core_docs.create(db, owner=OWNER, path="reports/morning/2026-10-11.md", title="Report", body="```check\n{}\n```")
    assert core.sources(db, owner=OWNER) == []


def test_a_document_under_sources_without_a_check_is_a_plain_document_not_a_source(db: psycopg.Connection) -> None:
    """A transcript saved under the folder before sources existed, or any note put there: with no check block it is not listed,
    not checked and not in the row, so it never stands in red for want of a check. By its id it is still found, so the agent's
    tool can give it a check and make it one."""
    plain = core_docs.create(db, owner=OWNER, path="sources/elena/transcript.md", title="A transcript", body="No check here.").doc
    disk = _source(db, "disk", NAME)
    assert [s.id for s in core.sources(db, owner=OWNER)] == [disk.id]
    assert [v.id for v in core.views(db, owner=OWNER, now=T0)] == [disk.id]
    found = core.find(db, owner=OWNER, ref=plain.id)
    assert (found.missing, found.check) == (True, None)
    assert core.judge(found, T0) == (GREY, core.NO_CHECK)


def test_the_connections_document_is_made_once_and_left_alone_after(db: psycopg.Connection) -> None:
    first = core.ensure_connections(db, owner=OWNER)
    assert core.ensure_connections(db, owner=OWNER) == first
    source = core.find(db, owner=OWNER, ref=core.CONNECTIONS_PATH)
    assert (source.title, source.check.kind, source.check.where, source.waiting) == ("Connections", "connections", "here", False)
    assert core.due(source, T0)
    core_docs.save(db, owner=OWNER, id=first, expected_revision=1, body=source.body + "\nThe owner's note.\n")
    assert core.ensure_connections(db, owner=OWNER) == first
    assert "The owner's note." in core.find(db, owner=OWNER, ref=first).body


# --- the tools that read a source, and where the last report stopped (docs/design/morning-quality.md) ----------------------

CHAT_READS = ["mcp__chat__list_messages", "mcp__chat__unread_summary"]


def test_a_view_carries_the_tools_that_read_the_source_and_they_are_only_the_approved_ones_to_use(db: psycopg.Connection) -> None:
    source = _source(db, "team-chat", {**NAME, "reads": CHAT_READS})
    seen = _look(db, source, T0 + MIN)
    assert (seen.reads, seen.approved, seen.needs_approval) == (tuple(CHAT_READS), True, False)
    assert seen.as_dict()["reads"] == CHAT_READS and seen.as_dict()["cutoff"] is None
    # A tool added to the list is a different check: the owner has not approved it, and the view says so beside the list.
    changed = _edit(db, source, {**NAME, "reads": [*CHAT_READS, "mcp__chat__get_thread"]}, approve=False)
    waiting = _look(db, changed, T0 + MIN)
    assert (len(waiting.reads), waiting.approved, waiting.needs_approval, waiting.why) == (3, False, True, core.WAITING)
    assert "get_thread" in waiting.summary


def test_a_source_with_no_reads_has_none(db: psycopg.Connection) -> None:
    assert _look(db, _source(db, "web", NAME), T0 + MIN).reads == ()
    assert _look(db, _source(db, "log", FILE), T0 + MIN).as_dict()["reads"] == []


def test_the_list_puts_the_cut_off_of_each_source_beside_it(db: psycopg.Connection) -> None:
    chat, mail = _source(db, "team-chat", NAME), _source(db, "mail", HTTP)
    found = {v.id: v for v in core.views(db, owner=OWNER, now=T0 + MIN, cutoffs={chat.id: "2026-10-11T06:58:00+02:00"})}
    assert found[chat.id].cutoff == "2026-10-11T06:58:00+02:00" and found[chat.id].as_dict()["cutoff"] == "2026-10-11T06:58:00+02:00"
    assert found[mail.id].cutoff is None
