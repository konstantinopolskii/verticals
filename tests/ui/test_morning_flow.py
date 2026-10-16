"""The morning report written, checked by a second agent and told ready once (docs/design/morning-quality.md), through the real
desktop gateway, the real server and its database. The agent is the fake one, which plays the writer, the second agent and the
fixer against the server's own API (`tests/ui/fake_agent/fake_morning.py`): what these tests pin is the machinery around a model,
not what a model reads. Sample sources only ("Team chat", "Mail").

What is pinned: each source starts where the last report stopped it; every item read is placed and counted; a check that fails
holds the report back until it is fixed, and the app is told once; a count that does not add up fails whatever the second agent
says; a second agent that gives no verdict, never answers, crashes or is stopped never leaves a report claiming a check; the
second agent has a lower effort and only reads; every MCP tool of a morning turn comes to the gateway, which runs a declared read
without asking and puts any other tool to the reader (declines it for the second agent)."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import psycopg
import pytest

from tests.core.morning_sample import make_report, report_body, source_doc, source_row, sources_section
from tests.ui.conftest import F2_OWNER, TEST_TOKEN, Server, _backend
from tests.ui.test_agent_conversation import _agent_gateway, _cli_starts, _flag
from verticals.core import sources as core_sources
from verticals.core.sources import Result

DAY, YESTERDAY = "2026-08-08", "2026-08-07"
ZONE = "Europe/Berlin"
NOW = "2026-08-08 07:00"
THEN = "2026-08-07 07:00"
CHAT_READS = ["mcp__chat__list_messages", "mcp__chat__unread_summary"]


def at(day: str, time_: str) -> str:
    return f"{day}T{time_}:00+02:00"


# Sample items of the two sources: some before the last report's cut-off, some inside the window it leaves.
RAW = {
    "Team chat": [{"at": at(YESTERDAY, "06:00")}, {"at": at(YESTERDAY, "09:30")}, {"at": at(YESTERDAY, "18:40")},
                  {"at": at(DAY, "03:15")}, {"at": at(DAY, "06:40")}],
    "Mail": [{"at": at(YESTERDAY, "05:00")}, {"at": at(YESTERDAY, "12:00")}, {"at": at(DAY, "02:00")}],
}


@dataclass
class Run:
    events: list[dict]
    session: str
    base: str

    def kinds(self) -> list[str]:
        return [event["t"] for event in self.events]

    def final(self) -> dict:
        return next(event for event in reversed(self.events) if event["t"] == "done")

    def last_next(self) -> int:
        """The place of the last turn that ended with the report not ready."""
        return max((i for i, e in enumerate(self.events) if e["t"] == "done" and e.get("next")), default=-1)

    def words(self) -> str:
        return "".join(event["text"] for event in self.events if event["t"] == "text")


class Morning:
    """A board, a server and a gateway to play the morning on."""

    def __init__(self, backend: Server, base: str, tmp_path: Path) -> None:
        self.backend, self.base, self.tmp = backend, base, tmp_path
        self.workspace = tmp_path / "desktop-state" / "chat-workspace"
        self.api = httpx.Client(base_url=backend.base_url, headers={"Authorization": f"Bearer {TEST_TOKEN}"}, timeout=30)
        self.gateway = httpx.Client(base_url=base, timeout=60)

    def scenario(self, **kw) -> None:
        (self.workspace / "scenario.json").write_text(json.dumps({"morning": True, "raw": RAW, **kw}))

    def db(self) -> psycopg.Connection:
        return psycopg.connect(self.backend.dsn, autocommit=True)

    def sources(self, *, mail_approved: bool = True) -> None:
        with self.db() as conn:
            source_doc(conn, F2_OWNER, "Team chat", reads=CHAT_READS)
            source_doc(conn, F2_OWNER, "Mail", approved=mail_approved)

    def last_report(self, *, chat_end: str = THEN, mail_end: str = THEN, comment_row: str | None = None) -> None:
        """Yesterday's report: where it stopped reading each source is all the morning needs of it."""
        with self.db() as conn:
            make_report(conn, F2_OWNER, date.fromisoformat(YESTERDAY), report_body(sources=sources_section([
                source_row("Team chat", "2026-08-06 07:00", chat_end, 2, ref="sources/team-chat.md"),
                source_row("Mail", "2026-08-06 07:00", mail_end, 1, ref="sources/mail.md"),
            ])))

    def task(self, day: str = DAY) -> str:
        begun = self.api.post("/api/morning", params={"date": day}).json()
        assert begun["asked"] is True
        return begun["task_id"]

    def goal(self, title: str) -> str:
        return self.api.post("/api/goals", json={"title": title}).json()["id"]

    def ask(self, task: str, *, day: str = DAY, now: str = NOW, effort: str = "high") -> Run:
        """What the app sends for the morning (web lib/morning.ts), then every event until the answer ends."""
        session = self.send(task, day=day, now=now, effort=effort)
        return Run(self.events(session), session, self.base)

    def send(self, task: str, *, day: str = DAY, now: str = NOW, effort: str = "high") -> str:
        """What the app sends for the morning, and nothing read: for a test that answers the reader's questions as they come."""
        session = str(uuid.uuid4())
        text = (f'Make my morning report for {day}, following the morning report guide in your instructions. Save it as the '
                f'document reports/morning/{day}.md titled "Morning report" and link it to its task, "Morning report" '
                f"(id {task}), which is in Day for today already. Then answer in two short lines and link the document.")
        sent = self.gateway.post("/__chat/send", json={
            "session": session, "text": text, "mode": "send",
            "context": {"today": day, "tz": ZONE, "now": now, "morning": {"day": day, "task": task}},
            "settings": {"provider": "claude", "permission": "board", "effort": effort, "sources": "connected"}})
        assert sent.status_code == 200, sent.text
        return session

    def events(self, session: str, until: Callable[[dict], bool] | None = None, seconds: float = 90) -> list[dict]:
        until = until or (lambda e: (e["t"] == "done" and not e.get("next")) or e["t"] == "exit")
        seen: list[dict] = []
        with httpx.stream("GET", f"{self.base}/__chat/events", params={"session": session, "since": 0, "boot": ""},
                          timeout=httpx.Timeout(seconds, read=seconds)) as stream:
            for line in stream.iter_lines():
                if line.startswith("data:") and '"seq"' in line:
                    seen.append(json.loads(line[5:])["event"])
                    if until(seen[-1]):
                        break
        return seen

    def report(self, day: str = DAY) -> str:
        docs = {d["path"]: d["id"] for d in self.api.get("/api/docs").json()["docs"]}
        return self.api.get(f"/api/docs/{docs[f'reports/morning/{day}.md']}").json()["body"]

    def rows(self, day: str = DAY) -> dict[str, tuple[str, str, int, int]]:
        """The sources section of a report: source -> window start, window end, read, placed."""
        out = {}
        for name, start, end, numbers in re.findall(
                r"^\| \[([^\]]+)\]\([^)]*\) \| (\S+ \S+) – (\S+ \S+) \| ([\d |]+)\|$", self.report(day), re.M):
            counts = [int(n) for n in numbers.split("|") if n.strip()]
            out[name] = (start, end, counts[0], sum(counts[1:]))
        return out

    def starts(self) -> list[list[str]]:
        return _cli_starts(self.tmp)

    def decisions(self) -> list[dict]:
        """What the gateway answered each time the fake agent's CLI asked about a tool (`fake_agent/claude`, `decisions.log`)."""
        log = self.workspace / "decisions.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def morning(f2_dsn: str, tmp_path: Path) -> Iterator[Morning]:
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        with _agent_gateway(backend, tmp_path, env={"VERTICALS_TEST_CHECK_LIMIT": "6"}) as base:
            yield Morning(backend, base, tmp_path)


def first_line(body: str) -> str:
    return body.split("\n", 1)[0]


# --- the whole morning ---------------------------------------------------------------------------------------------


def test_a_report_starts_each_source_where_the_last_report_stopped_and_counts_every_item(morning: Morning) -> None:
    morning.sources()
    morning.last_report(chat_end="2026-08-07 09:00", mail_end="2026-08-07 07:00")
    task = morning.task()
    morning.scenario(rows=[{"id": morning.goal("Launch plan is shared"), "title": "Launch plan is shared"}])
    run = morning.ask(task)
    assert run.final()["error"] is False
    rows = morning.rows()
    # Team chat resumes at 09:00 and has four items after it (09:30 is the first), Mail at 07:00 and has two.
    assert rows["Team chat"] == ("2026-08-07 09:00", NOW, 4, 4)
    assert rows["Mail"] == ("2026-08-07 07:00", NOW, 2, 2)
    body = morning.report()
    assert first_line(body) == "Checked against the sources by a second agent: all 10 passed."
    assert "Times in Europe/Berlin." in body and "(goal:" in body


def test_a_task_the_sources_show_done_is_closed_on_the_board_listed_once_and_left_out_of_the_rows(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    task = morning.task()
    open_id, done_id = morning.goal("Launch plan is shared"), morning.goal("Announcement draft is approved")
    morning.scenario(rows=[{"id": open_id, "title": "Launch plan is shared"}],
                     close=[{"id": done_id, "title": "Announcement draft is approved", "evidence": "Team chat shows it approved."}])
    run = morning.ask(task)
    assert run.final()["error"] is False
    assert morning.api.get(f"/api/goals/{done_id}").json()["done_at"] is not None
    assert morning.api.get(f"/api/goals/{open_id}").json()["done_at"] is None
    body = morning.report()
    closed = body.split("## Closed since the last report")[1].split("\n## ")[0]
    assert body.count(f"(goal:{done_id})") == 1 and f"(goal:{done_id})" in closed, "listed once, in what was closed, never in the rows"
    assert first_line(body) == "Checked against the sources by a second agent: all 10 passed."
    # Closed with `update`, its evidence recorded with `evidence_update`: the two writes the morning turn may make besides the report.
    assert [e["name"] for e in run.events if e["t"] == "tool" and e["name"] in ("update", "evidence_update")] == ["update", "evidence_update"]


def test_a_morning_that_runs_after_another_starts_where_that_one_ended_and_a_source_it_could_not_read_keeps_its_end(morning: Morning) -> None:
    morning.sources(mail_approved=False)  # the reader has not approved Mail's check: it cannot be read
    morning.last_report(chat_end="2026-08-07 09:00", mail_end="2026-08-07 07:00")
    task = morning.task()
    morning.scenario(unread=["Mail: waiting for your Approve, so it was not read."])
    first = morning.ask(task)
    assert first.final()["error"] is False
    one = morning.rows()
    assert one["Team chat"][:2] == ("2026-08-07 09:00", NOW) and one["Mail"] == ("2026-08-07 07:00", "2026-08-07 07:00", 0, 0)
    body = morning.report()
    assert body.split("\n")[:3] == ["```unread", "Mail: waiting for your Approve, so it was not read.", "```"]
    assert body.split("\n")[4].startswith("Checked against the sources by a second agent")
    # The next morning: Team chat starts at the end of this one, and Mail again at its old end.
    next_day = "2026-08-09"
    task2 = morning.task(next_day)
    morning.scenario(unread=["Mail: waiting for your Approve, so it was not read."])
    morning.ask(task2, day=next_day, now="2026-08-09 07:00")
    two = morning.rows(next_day)
    assert two["Team chat"][:2] == (NOW, "2026-08-09 07:00") and two["Mail"][:2] == ("2026-08-07 07:00", "2026-08-07 07:00")


def test_the_owner_hears_of_the_report_once_after_the_check_and_every_turn_before_is_an_answer_of_its_own(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    task = morning.task()
    morning.scenario(checker_delay=1.5)
    run = morning.ask(task)
    kinds = run.kinds()
    # writing, then the check: each turn starts and ends on its own, and says the report is not ready
    assert [e.get("stage") for e in run.events if e["t"] == "turn_start"] == [None, "check"]
    assert [e.get("next") for e in run.events if e["t"] == "done"] == ["check", "verdict", None]
    assert [e["label"] for e in run.events if e["t"] == "step"] == ["Checking the report"]
    # the words are told once, after the last turn that was not the end, and just before the end
    assert kinds.index("text") > run.last_next() and kinds[-1] == "done" and "[Morning report — 8 August 2026]" in run.words()
    assert run.words().count("Morning report") == 1
    # a declared tool names its source in the step the field shows
    reading = [e["step"] for e in run.events if e["t"] == "tool" and e.get("step")]
    assert reading == ["Reading Team chat"]
    assert not any(e["t"] == "tool" and e["name"] == "mcp__verticals__doc_get" for e in run.events), "the second agent's tools stay quiet"


def test_the_second_agent_is_a_fresh_one_at_a_lower_effort_that_only_reads_and_keeps_the_owners_servers(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario()
    morning.ask(morning.task(), effort="high")
    writer, checker = morning.starts()
    assert _flag(writer, "--effort") == "high" and _flag(checker, "--effort") == "medium"
    # The owner's own settings and servers stay, so the sources' tools are there; one ask rule sends every MCP tool to the gateway.
    for args in (writer, checker):
        assert "--setting-sources" not in args and "--strict-mcp-config" not in args
        assert json.loads(_flag(args, "--settings"))["permissions"] == {"ask": ["mcp__*"]}
    assert _flag(writer, "--session-id") != _flag(checker, "--session-id")
    wrote = set(_flag(writer, "--allowedTools").split(","))
    read = set(_flag(checker, "--allowedTools").split(","))
    assert {"mcp__verticals__doc_save", "mcp__verticals__update"} & wrote == {"mcp__verticals__doc_save"}
    assert not {"mcp__verticals__doc_save", "mcp__verticals__doc_create", "mcp__verticals__evidence_update"} & read
    assert set(CHAT_READS) <= wrote and set(CHAT_READS) <= read
    assert "## This turn: the second check" in _flag(checker, "--append-system-prompt")
    assert "## This turn: the second check" not in _flag(writer, "--append-system-prompt")


def test_every_mcp_tool_comes_to_the_gateway_a_declared_read_is_not_asked_and_any_other_tool_is(morning: Morning) -> None:
    """The fake agent asks its host about every tool the command line's ask rule matches, as the CLI does, whatever the
    command line allows. The tools the sources declare and Verticals' own reading tools and report writes run with no question
    to the reader; a tool no source lists is put to the reader, from the agent that writes the report, and declined for the
    second agent, which has nobody to ask and writes nothing."""
    morning.sources()
    morning.last_report()
    task = morning.task()
    morning.scenario(writer_tools=["mcp__chat__send_message"], checker_tools=["mcp__chat__send_message", "mcp__verticals__doc_save"])
    session = morning.send(task)
    # The writer's tool no source lists is asked of the reader, by name; nothing before it was.
    seen = morning.events(session, until=lambda e: e["t"] in ("permission", "exit") or (e["t"] == "done" and not e.get("next")))
    assert seen[-1]["t"] == "permission" and [e["t"] for e in seen].count("permission") == 1, "the first thing asked of the reader"
    ask = seen[-1]
    assert ask["title"] == "Allow Claude to use mcp__chat__send_message?" and ask["tool"] == "mcp__chat__send_message"
    morning.gateway.post("/__chat/permission", json={"session": session, "requestId": ask["requestId"], "value": "decline"})
    events = morning.events(session)
    assert [e["t"] for e in events].count("permission") == 1, "no declared read, no report write and nothing of the second agent's was asked"
    assert events[-1]["t"] == "done" and events[-1]["error"] is False and "[Morning report" in "".join(
        e["text"] for e in events if e["t"] == "text")
    decided = [(d["seat"], d["tool"], d["behavior"]) for d in morning.decisions()]
    for seat, tool in (("writer", "mcp__verticals__sources"), ("writer", "mcp__chat__list_messages"),
                       ("writer", "mcp__verticals__doc_create"), ("writer", "mcp__verticals__doc_link"),
                       ("checker", "mcp__verticals__doc_get"), ("checker", "mcp__verticals__sources")):
        assert (seat, tool, "allow") in decided, (seat, tool)
    assert ("writer", "mcp__chat__send_message", "deny") in decided, "the reader declined it"
    assert ("checker", "mcp__chat__send_message", "deny") in decided and ("checker", "mcp__verticals__doc_save", "deny") in decided
    assert not [d for d in decided if d[0] == "checker" and d[2] == "allow" and d[1] in ("mcp__chat__send_message", "mcp__verticals__doc_save")]
    assert first_line(morning.report()) == "Checked against the sources by a second agent: all 10 passed."


# --- a failing check holds the report back ---------------------------------------------------------------------------


def test_a_failing_check_holds_the_report_back_until_it_is_fixed_and_then_it_is_told_once(morning: Morning) -> None:
    morning.sources()
    morning.last_report(chat_end="2026-08-07 09:00", mail_end="2026-08-07 07:00")
    morning.scenario(miss=2, checker_delay=1.0)  # the writer reads two items fewer than Team chat gave
    run = morning.ask(morning.task())
    stages = [(e["t"], e.get("stage") or e.get("next")) for e in run.events if e["t"] in ("turn_start", "done")]
    assert stages == [("turn_start", None), ("done", "check"), ("turn_start", "check"), ("done", "verdict"),
                      ("turn_start", "fix"), ("done", "check"), ("turn_start", "check"), ("done", "verdict"), ("done", None)]
    assert [e["label"] for e in run.events if e["t"] == "step"] == ["Checking the report", "Fixing the report", "Checking it again"]
    # Nothing of the writer's was told while the report was held; the one thing told is the fixed report's.
    assert run.kinds().index("text") > run.last_next() and run.words().count("[Morning report") == 1
    body = morning.report()
    assert first_line(body) == "Checked against the sources by a second agent: all 10 passed."
    assert "| Every message placed | Fixed | Failed at first: Mail: I count 2 items, the report says 0. Team chat: I count 4 items, the report says 2. |" in body
    assert morning.rows()["Team chat"] == ("2026-08-07 09:00", NOW, 4, 4)  # the fixed report has every item
    assert len(morning.starts()) == 2, "the writer's agent fixed it and the second agent checked again: two processes, not four"


def test_a_count_that_does_not_add_up_fails_even_when_the_second_agent_says_pass(morning: Morning) -> None:
    morning.sources()
    morning.last_report(chat_end="2026-08-07 09:00", mail_end="2026-08-07 07:00")
    morning.scenario(unbalanced=True, checker_mode="blind")  # the second agent looks at nothing and passes everything
    run = morning.ask(morning.task())
    assert [e.get("stage") for e in run.events if e["t"] == "turn_start"] == [None, "check", "fix", "check"]
    body = morning.report()
    assert "| Every message placed | Fixed | Failed at first: Mail: 2 read, 1 placed. Team chat: 4 read, 3 placed. |" in body
    assert morning.rows()["Team chat"][2:] == (4, 4)


def test_a_report_that_still_fails_after_its_one_fix_is_told_with_the_failure_in_it_and_is_not_fixed_again(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    both = {"names": {"result": "fail", "note": "Two rows are named by what is done."}}
    morning.scenario(checker=[both, both])
    run = morning.ask(morning.task())
    assert [e.get("stage") for e in run.events if e["t"] == "turn_start"] == [None, "check", "fix", "check"]  # one fix, one more look
    assert run.final()["error"] is False
    body = morning.report()
    assert first_line(body) == "Checked against the sources by a second agent: 9 of 10 passed, 1 failed."
    assert "| Names | Failed | Two rows are named by what is done. |" in body


def test_a_check_that_could_not_be_made_is_a_gap_in_the_report_and_never_a_pass(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario(checker=[{"where": {"result": "gap", "note": "Mail did not answer."}}])
    run = morning.ask(morning.task())
    assert [e.get("stage") for e in run.events if e["t"] == "turn_start"] == [None, "check"]  # a gap does not hold the report
    body = morning.report()
    assert first_line(body) == "Checked against the sources by a second agent: 9 of 10 passed, 1 gap."
    assert "| Where each item went | Gap | Mail did not answer. |" in body


# --- a second agent that does not deliver ----------------------------------------------------------------------------


@pytest.mark.parametrize("mode, said", [
    ("garbage", "Not checked: The second agent gave no verdict."),
    ("silent", "Not checked: The second agent did not answer in time."),
    ("crash", "Not checked: The second agent stopped: it exited with code 3."),
])
def test_a_second_agent_that_gives_nothing_never_holds_the_report_and_the_report_never_claims_a_check(
    morning: Morning, mode: str, said: str,
) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario(checker_mode=mode)
    started = time.monotonic()
    run = morning.ask(morning.task())
    assert run.final()["error"] is False and "[Morning report" in run.words()  # the report is told, with its truth in it
    assert first_line(morning.report()) == said
    assert time.monotonic() - started < 60


def test_a_second_agent_that_answers_in_prose_once_is_asked_again(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario(checker_mode="garbage_once")
    morning.ask(morning.task())
    assert first_line(morning.report()) == "Checked against the sources by a second agent: all 10 passed."
    assert len(morning.starts()) == 2  # asked again in the same conversation


def test_stopping_while_the_second_agent_reads_leaves_the_report_saying_it_was_not_checked(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario(checker_delay=8)
    task = morning.task()
    session = str(uuid.uuid4())
    morning.gateway.post("/__chat/send", json={
        "session": session, "text": f"Make my morning report for {DAY}. (id {task})", "mode": "send",
        "context": {"today": DAY, "tz": ZONE, "now": NOW, "morning": {"day": DAY, "task": task}},
        "settings": {"provider": "claude", "permission": "board", "effort": "high", "sources": "connected"}})
    morning.events(session, until=lambda e: e["t"] == "step")  # the second agent has begun
    morning.gateway.post("/__chat/stop", json={"session": session})
    events = morning.events(session)
    assert events[-1]["t"] == "done" and events[-1]["error"] is True
    assert first_line(morning.report()) == "Not checked: It stopped before the check was finished."


def test_a_writer_that_fails_after_writing_leaves_a_report_that_says_it_was_not_finished(morning: Morning) -> None:
    morning.sources()
    morning.last_report()
    morning.scenario(writer_mode="fail_after_write")
    run = morning.ask(morning.task())
    assert run.final()["error"] is True and len(morning.starts()) == 1, "no second agent reads what was not finished"
    assert first_line(morning.report()) == "Not checked: It was not finished."


def test_a_morning_that_wrote_no_report_is_not_checked(morning: Morning) -> None:
    """The old behaviour stays: an agent that answers without a report (an echo, a refusal) gets its answer told at once."""
    morning.scenario(morning=False)
    run = morning.ask(morning.task())
    assert run.final()["error"] is False and "Make my morning report" in run.words() and len(morning.starts()) == 1
    assert [e["t"] for e in run.events if e["t"] in ("step",)] == []


def test_with_no_sources_the_red_block_is_one_line_naming_the_servers_and_there_is_no_sources_table(morning: Morning) -> None:
    with morning.db() as conn:
        connections = core_sources.ensure_connections(conn, owner=F2_OWNER)
        own = core_sources.find(conn, owner=F2_OWNER, ref=connections)
        core_sources.record(conn, owner=F2_OWNER, doc_id=connections, check_hash=own.check.hash,
                            result=Result(ok=True, detail="all 2 answer: chat, mail", value=2.0, ms=5), now=datetime.now(timezone.utc))
    task = morning.task()
    morning.scenario(rows=[{"id": morning.goal("Launch plan is shared"), "title": "Launch plan is shared"}])
    run = morning.ask(task)
    assert run.final()["error"] is False
    body = morning.report()
    assert body.split("\n")[:3] == ["```unread", "No sources yet. The agent reaches chat and mail. Tell it what to read each morning, in one sentence.", "```"]
    assert "## Sources" not in body and morning.rows() == {}
    assert body.split("\n")[4] == "Checked against the sources by a second agent: all 10 passed."
