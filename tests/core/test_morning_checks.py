"""The second agent's verdict becomes the report's check, with the server's own floor under it (docs/design/morning-quality.md,
`core/morning_checks.py`): a count that does not add up, a window that leaves a hole or a task that is closed fails the check
whatever the second agent said, and a check nobody answered is a gap, never a pass."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg
import pytest

from tests.core.morning_sample import NOW, goal_row, make_report, make_task, report_body, source_doc, source_row, sources_section
from verticals.core import docs as core_docs
from verticals.core import goals, morning, morning_checks
from verticals.core import morning_report as report
from verticals.core import sources as core_sources
from verticals.core.errors import NotFound, ValidationError
from verticals.core.morning_report import FAIL, GAP, PASS, Outcome

OWNER = "SYN-checks-owner"
SUNDAY, MONDAY = date(2026, 10, 11), date(2026, 10, 12)
PATH = "reports/morning/2026-10-12.md"
PASSES = {key: {"result": "pass"} for key in report.KEYS}


class Day:
    """A small board with two sources, a report for Sunday, and Monday's report waiting to be checked."""

    def __init__(self, db: psycopg.Connection) -> None:
        self.db = db
        self.chat = source_doc(db, OWNER, "Team chat")
        self.mail = source_doc(db, OWNER, "Mail")
        self.task = morning.begin(db, owner=OWNER, day=MONDAY).task_id
        self.launch = make_task(db, OWNER, "Launch is planned")
        self.notes = make_task(db, OWNER, "Notes are written", parent=self.launch)
        make_report(db, OWNER, SUNDAY, report_body(sources=sources_section([
            source_row("Team chat", "2026-10-10 07:00", "2026-10-11 06:58", 12, ref="sources/team-chat.md"),
            source_row("Mail", "2026-10-10 07:00", "2026-10-11 06:41", 5, ref="sources/mail.md"),
        ])))

    def sources(self, chat: str | None = None, mail: str | None = None) -> str:
        return sources_section([
            chat or source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 42, 11, 4, 6, 3, 15, 3, ref="sources/team-chat.md"),
            mail or source_row("Mail", "2026-10-11 06:41", "2026-10-12 06:57", 8, ref="sources/mail.md"),
        ])

    def write(self, rows: list[str] | None = None, *, sources: str | None = None, **kw) -> str:
        """Monday's report, made or (when it is there) written again, linked to the Morning report task."""
        rows = rows if rows is not None else [goal_row(self.launch, "Launch is planned", bold=True),
                                              goal_row(self.notes, "Notes are written", child=True)]
        body = report_body(rows, sources=sources or self.sources(), **kw)
        try:
            doc = core_docs.get_by_path(self.db, owner=OWNER, path=PATH)
        except NotFound:
            return make_report(self.db, OWNER, MONDAY, body, task=self.task)
        core_docs.save(self.db, owner=OWNER, id=doc.id, expected_revision=doc.revision, body=body)
        return doc.id

    def apply(self, asked: object = PASSES, **kw) -> morning_checks.Applied:
        return morning_checks.apply(self.db, owner=OWNER, path=PATH, asked=asked, now=NOW, **kw)

    def body(self) -> str:
        return core_docs.get_by_path(self.db, owner=OWNER, path=PATH).body


def test_a_sound_report_passes_all_ten_and_says_so_in_one_line(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    applied = day.apply()
    assert (applied.failed, applied.gaps, applied.state) == ((), (), "checked")
    assert day.body().splitlines()[0] == "Checked against the sources by a second agent: all 10 passed."
    assert report.check_state(day.body()) == "checked"


def test_only_the_check_changes_in_the_report(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    before = day.body()
    day.apply()
    after = day.body()
    assert after.replace(after.splitlines()[0], report.PENDING, 1) == before


def test_counts_that_do_not_add_up_fail_the_check_whatever_the_second_agent_said(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=day.sources(chat=source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 44, 11, 4, 6, 3, 15, 3,
                                                  ref="sources/team-chat.md")))
    applied = day.apply()
    assert applied.failed == ("inputs",)
    assert applied.outcomes["inputs"].note == "Team chat: 44 read, 42 placed."
    assert "| Every message placed | Failed | Team chat: 44 read, 42 placed. |" in day.body()
    assert day.body().splitlines()[0].endswith("9 of 10 passed, 1 failed.")


def test_a_counts_cell_that_is_not_a_number_fails_too(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=day.sources(mail="| [Mail](doc:sources/mail.md) | 2026-10-11 06:41 – 2026-10-12 06:57 | many | 3 | 0 | 0 | 0 | 0 | 0 |"))
    assert day.apply().outcomes["inputs"].note == "Mail: not every count is a number."


def test_a_window_that_starts_after_the_last_report_stopped_leaves_a_hole_and_fails(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=day.sources(chat=source_row("Team chat", "2026-10-11 09:00", "2026-10-12 06:57", 7, ref="sources/team-chat.md")))
    applied = day.apply()
    assert applied.failed == ("continuity",)
    assert applied.outcomes["continuity"].note == "Team chat: starts 2026-10-11 09:00, but the last report stopped at 2026-10-11 06:58."


def test_a_window_that_starts_exactly_where_the_last_stopped_or_earlier_is_continuous(db: psycopg.Connection) -> None:
    day = Day(db)
    early = source_row("Mail", "2026-10-11 05:00", "2026-10-12 06:57", 9, ref="sources/mail.md")  # overlap is not a hole
    day.write(sources=day.sources(mail=early))
    assert day.apply().failed == ()


def test_a_window_that_ends_before_the_last_one_did_or_before_it_began_fails(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=day.sources(chat=source_row("Team chat", "2026-10-11 06:58", "2026-10-11 06:00", 1, ref="sources/team-chat.md")))
    applied = day.apply()
    assert applied.failed == ("continuity",)
    assert "ends before it starts" in applied.outcomes["continuity"].note and "before the last report's" in applied.outcomes["continuity"].note


def test_the_first_morning_has_nothing_to_continue_from(db: psycopg.Connection) -> None:
    other = "SYN-checks-first"
    source_doc(db, other, "Team chat")
    task = morning.begin(db, owner=other, day=MONDAY).task_id
    make_report(db, other, MONDAY, report_body(sources=sources_section(
        [source_row("Team chat", "2026-10-01 00:00", "2026-10-12 06:57", 3, ref="sources/team-chat.md")])), task=task)
    assert morning_checks.apply(db, owner=other, path=PATH, asked=PASSES, now=NOW).failed == ()


def test_a_source_with_no_row_is_not_covered(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=sources_section([source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 1, ref="sources/team-chat.md")]))
    applied = day.apply()
    assert applied.failed == ("sources",) and applied.outcomes["sources"].note == "No row in Sources for Mail."


def test_a_report_with_no_sources_section_fails_the_sources_and_breaks_nothing(db: psycopg.Connection) -> None:
    day = Day(db)
    make_report(db, OWNER, MONDAY, "A report written another way.\n", task=day.task)
    applied = day.apply()
    assert "sources" in applied.failed and "no Sources section" in applied.outcomes["sources"].note


def test_a_source_waiting_for_the_owners_approval_must_be_named_at_the_top(db: psycopg.Connection) -> None:
    day = Day(db)
    waiting = source_doc(db, OWNER, "Calendar", approved=False)
    section = sources_section([
        source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 1, ref="sources/team-chat.md"),
        source_row("Mail", "2026-10-11 06:41", "2026-10-12 06:57", 1, ref="sources/mail.md"),
        source_row("Calendar", "2026-10-11 07:00", "2026-10-11 07:00", 0, 0, 0, 0, 0, 0, 0, ref=waiting),
    ])
    day.write(sources=section)
    silent = day.apply()
    assert silent.failed == ("sources",)
    assert silent.outcomes["sources"].note == "Calendar cannot be read now and is not named in the red block at the top."
    day.write(sources=section, unread=["Calendar: waiting for your Approve, so it was not read."])
    assert day.apply().failed == ()


def test_a_source_that_is_red_must_be_named_at_the_top(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    chat = core_sources.find(db, owner=OWNER, ref=day.chat)
    t0 = NOW - timedelta(hours=1)
    for when in (t0, t0 + timedelta(minutes=6)):  # two failures five minutes apart make red
        core_sources.record(db, owner=OWNER, doc_id=day.chat, check_hash=chat.check.hash,
                            result=core_sources.Result(ok=False, detail="last exit code 127"), now=when)
    assert core_sources.view(core_sources.find(db, owner=OWNER, ref=day.chat), NOW).status == core_sources.RED
    assert day.apply().outcomes["sources"].note == "Team chat cannot be read now and is not named in the red block at the top."


def test_a_closed_task_in_the_table_fails_the_current_state(db: psycopg.Connection) -> None:
    day = Day(db)
    goals.update(db, owner=OWNER, id=day.notes, done=True)
    day.write()
    applied = day.apply()
    assert applied.failed == ("state",) and applied.outcomes["state"].note == "Notes are written is closed and still in the table."


def test_a_child_set_under_a_task_that_is_not_its_parent_fails_the_hierarchy(db: psycopg.Connection) -> None:
    day = Day(db)
    other = make_task(db, OWNER, "Another thing is planned")
    day.write([goal_row(other, "Another thing is planned", bold=True), goal_row(day.notes, "Notes are written", child=True)])
    applied = day.apply()
    assert applied.failed == ("hierarchy",)
    assert applied.outcomes["hierarchy"].note == "Notes are written is set under a task that is not its parent."
    day.write([goal_row(day.notes, "Notes are written", child=True)])  # a child with no parent row above it
    assert day.apply().failed == ("hierarchy",)
    day.write([goal_row(day.launch, "Launch is planned", bold=True), goal_row(day.notes, "Notes are written", child=True)])
    assert day.apply().failed == ()


def test_a_row_linking_a_task_that_is_not_on_the_board_fails_where_each_item_went(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write([goal_row(day.launch, "Launch is planned"), goal_row("NOSUCHID", "A task that is not")])
    applied = day.apply()
    assert applied.failed == ("where",) and applied.outcomes["where"].note == "No task on the board behind A task that is not."


def test_a_proposal_with_no_task_yet_links_nothing_and_is_not_failed_for_it(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write([goal_row(day.launch, "Launch is planned"), "| Thanks are sent | Nobody owns it yet. | – | Decide who sends them. |  |"])
    assert day.apply().failed == ()


def test_the_copy_is_the_days_title_linked_to_the_morning_task(db: psycopg.Connection) -> None:
    day = Day(db)
    core_docs.create(db, owner=OWNER, path=PATH, title="A report", body=report_body(sources=day.sources()))
    applied = day.apply()
    assert applied.failed == ("copy",)
    assert applied.outcomes["copy"].note == ("The title is 'A report', not 'Morning report — 12 October 2026'. "
                                              "The document is not linked to its Morning report task.")


def test_a_check_the_second_agent_did_not_answer_is_a_gap_and_never_a_pass(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    asked = {key: {"result": "pass"} for key in report.KEYS if key not in ("names", "state", "inbox")}
    asked["inbox"] = {"result": "perhaps", "note": "unsure"}
    asked["state"] = "pass"  # the short form is a pass too
    applied = day.apply(asked)
    assert applied.failed == () and applied.gaps == ("inbox", "names")
    assert applied.outcomes["names"].note == "The second agent gave no answer to this check."
    assert "'perhaps', which is not pass, fail or gap" in applied.outcomes["inbox"].note
    assert day.body().splitlines()[0] == "Checked against the sources by a second agent: 8 of 10 passed, 2 gaps."
    nothing = day.apply(None)
    assert len(nothing.gaps) == 10 and nothing.failed == ()


def test_the_worse_of_the_second_agent_and_the_floor_stands_and_both_reasons_show(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write(sources=day.sources(chat=source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 44, 11, 4, 6, 3, 15, 3,
                                                  ref="sources/team-chat.md")))
    asked = PASSES | {"inputs": {"result": "fail", "note": "Two voice notes have no place."}}
    note = day.apply(asked).outcomes["inputs"].note
    assert note == "Two voice notes have no place. Team chat: 44 read, 42 placed."
    gap = day.apply(PASSES | {"names": {"result": "gap", "note": "Could not open the notes."}})
    assert gap.outcomes["names"].result == GAP and gap.outcomes["names"].note == "Could not open the notes."


def test_a_check_that_failed_first_and_passes_after_the_fix_is_shown_as_fixed(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    first = {"names": Outcome(FAIL, "Two rows are named by what is done.")}
    applied = day.apply(first={**{key: Outcome(PASS) for key in report.KEYS}, **first})
    assert applied.failed == ()
    assert "| Names | Fixed | Failed at first: Two rows are named by what is done. |" in day.body()
    assert day.body().splitlines()[0].endswith("all 10 passed.")


def test_a_report_is_pending_or_unchecked_until_a_verdict_and_is_never_left_saying_it_was_checked(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    day.apply()
    marked = morning_checks.mark(db, owner=OWNER, path=PATH, state="unchecked", reason="The second agent stopped.")
    assert marked.state == "unchecked"
    assert day.body().splitlines()[0] == "Not checked: The second agent stopped."
    assert morning_checks.mark(db, owner=OWNER, path=PATH, state="pending").state == "pending"
    assert day.body().splitlines()[0] == report.PENDING
    day.apply()  # and a verdict after that replaces it
    assert report.check_state(day.body()) == "checked"


def test_the_check_goes_under_the_red_block(db: psycopg.Connection) -> None:
    day = Day(db)
    waiting = source_doc(db, OWNER, "Calendar", approved=False)
    day.write(sources=sources_section([
        source_row("Team chat", "2026-10-11 06:58", "2026-10-12 06:57", 1, ref="sources/team-chat.md"),
        source_row("Mail", "2026-10-11 06:41", "2026-10-12 06:57", 1, ref="sources/mail.md"),
        source_row("Calendar", "2026-10-11 07:00", "2026-10-11 07:00", 0, 0, 0, 0, 0, 0, 0, ref=waiting),
    ]), unread=["Calendar: waiting for your Approve, so it was not read."])
    day.apply()
    lines = day.body().split("\n")
    assert lines[:4] == ["```unread", "Calendar: waiting for your Approve, so it was not read.", "```", ""]
    assert lines[4].startswith("Checked against the sources")


def test_a_path_that_is_not_a_report_and_a_report_that_is_not_there_are_refused(db: psycopg.Connection) -> None:
    Day(db)
    with pytest.raises(ValidationError):
        morning_checks.apply(db, owner=OWNER, path="notes/today.md", asked=PASSES, now=NOW)
    with pytest.raises(NotFound):
        morning_checks.apply(db, owner=OWNER, path="reports/morning/2026-10-12.md", asked=PASSES, now=NOW)
    with pytest.raises(ValidationError):
        morning_checks.mark(db, owner=OWNER, path=PATH, state="checked")


def test_another_owners_report_is_not_reachable(db: psycopg.Connection) -> None:
    day = Day(db)
    day.write()
    with pytest.raises(NotFound):
        morning_checks.apply(db, owner="SYN-checks-other", path=PATH, asked=PASSES, now=NOW)
    assert report.check_state(day.body()) == "pending"


def test_with_no_sources_a_report_has_no_sources_section_and_the_sources_check_passes(db: psycopg.Connection) -> None:
    """Nothing to read means nothing to list: the report says so in one line at the top and has no Sources table, and the floor
    holds nothing against it. The app's own Connections is not a source, so it does not count as one here either."""
    owner = "SYN-checks-none"
    core_sources.ensure_connections(db, owner=owner)
    task = morning.begin(db, owner=owner, day=MONDAY).task_id
    launch = make_task(db, owner, "Launch is planned")
    body = report_body([goal_row(launch, "Launch is planned")], sources="",
                       unread=["No sources yet. The agent reaches chat and mail. Tell it what to read each morning, in one sentence."])
    assert "## Sources" not in body
    make_report(db, owner, MONDAY, body, task=task)
    applied = morning_checks.apply(db, owner=owner, path=PATH, asked=PASSES, now=NOW)
    assert (applied.outcomes["sources"].result, applied.outcomes["inputs"].result, applied.outcomes["continuity"].result) == (PASS, PASS, PASS)
    assert applied.failed == ()
