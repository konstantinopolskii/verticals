"""Sources (docs/design/sources.md): the agent's two tools, `sources` and `source`, over a real stdio session, real
Postgres, no mocks.

What is pinned: a source is a document under sources/ whose plain sections and one check the tool writes; the tool runs
the check once and returns the answer beside what the check saw; every check the agent writes (an address, a tool, a
command, a file, a name lookup) waits for the owner (the only approval is the app's, so there is no tool that approves, and
the test approves the way the Approve button does, through `core`); a changed check waits again; one failure is not red; a
taken name is refused instead of numbered; a bad check is refused with the field and writes nothing. Checks run against a
tiny local web server, `/bin/echo` and `localhost`, never a real service.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest

from tests.mcp.conftest import TEST_OWNER, TEST_TOKEN, open_mcp_stdio
from verticals.core import sources as core


class _Page(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the name the server calls
        if self.path == "/queue":
            body, code = json.dumps({"status": "ok", "queue": {"depth": 7}}).encode(), 200
        else:
            body, code = b"maintenance window", 503
        self.send_response(code)
        self.send_header("Content-Type", "application/json" if code == 200 else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def web() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


QUEUE = {
    "title": "Queue",
    "gives": "How many jobs wait for the worker.",
    "how": "Read the depth from the status page.",
    "since": "the last report",
    "fixes": ["Restart the worker."],
}


def _approve(dsn: str, doc_id: str, check_hash: str) -> None:
    """What the app's Approve button does: the one writer of an approval."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        core.approve(conn, owner=TEST_OWNER, doc_id=doc_id, check_hash=check_hash, now=datetime.now(timezone.utc))


async def _made_checked_and_listed(f2_dsn: str, tmp_path: Path, web: str) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-http") as (session, streams):
        empty = await session.call_tool("sources", {})
        assert empty.is_error is False and empty.structured_content["sources"] == []

        check = {"kind": "http", "url": f"{web}/queue", "expect": {"status": "ok"}, "value": "queue.depth", "max": 10,
                 "say": "{v} jobs waiting"}
        made = await session.call_tool("source", {**QUEUE, "check": check})
        assert made.is_error is False, made.content
        out = made.structured_content
        # An address reaches something, so it waits for the owner: written, shown in words, not asked.
        assert (out["created"], out["saved"], out["ran"], out["result"]) == (True, True, False, None)
        assert "waiting for the owner" in out["why_not"] and f"{web}/queue" in out["why_not"]
        source = out["source"]
        assert (source["path"], source["title"], source["status"], source["why"], source["kind"], source["where"]) == (
            "sources/queue.md", "Queue", "grey", "waiting", "http", "here")
        assert (source["needs_approval"], source["checked_at"], len(source["check_hash"])) == (True, None, 64)
        assert "Created source" in made.content[0].text and "not run: waiting for the owner" in made.content[0].text

        # It is a document like any other: the plain sections, then the one check, as the owner will read it.
        doc = await session.call_tool("doc_get", {"path": "sources/queue.md"})
        body = doc.structured_content["doc"]["body"]
        assert "How many jobs wait for the worker." in body and "Restart the worker." in body
        assert "```check" in body and f"{web}/queue" in body

        # Asking again changes nothing: the agent cannot approve, and a run that is not allowed is not made.
        retry = await session.call_tool("source", {"id": source["id"]})
        assert (retry.structured_content["ran"], retry.structured_content["saved"]) == (False, False)

        _approve(f2_dsn, source["id"], source["check_hash"])
        ran = await session.call_tool("source", {"id": source["id"]})
        assert ran.is_error is False, ran.content
        out = ran.structured_content
        assert (out["created"], out["saved"], out["ran"], out["why_not"]) == (False, False, True, None)
        assert out["result"]["ok"] is True and out["result"]["value"] == 7.0
        assert out["result"]["detail"] == "7 jobs waiting"
        assert '"depth"' in out["result"]["raw"], "the number stands beside what the check saw"
        assert out["result"]["ms"] is not None
        assert (out["source"]["status"], out["source"]["approved"], out["source"]["failures"]) == ("ok", True, 0)
        assert out["source"]["checked_at"] is not None
        assert "checked: ok, 7 jobs waiting" in ran.content[0].text

        listed = await session.call_tool("sources", {})
        rows = listed.structured_content["sources"]
        assert [(r["id"], r["status"]) for r in rows] == [(source["id"], "ok")]
        assert "body" not in rows[0] and "excerpt" not in rows[0], "the list stays short"
        one = await session.call_tool("sources", {"id": "sources/queue.md"})
        assert one.structured_content["source"]["body"] == body

        # Changing only the fixes leaves the rest of the document as the owner left it, the approval stands, and the check runs.
        again = await session.call_tool("source", {"id": source["id"], "fixes": []})
        assert again.is_error is False, again.content
        assert (again.structured_content["created"], again.structured_content["saved"], again.structured_content["ran"]) == (
            False, True, True)
        body2 = (await session.call_tool("doc_get", {"path": "sources/queue.md"})).structured_content["doc"]["body"]
        assert "None. Anything else stays red." in body2 and "Restart the worker." not in body2
        assert body2.count("```check") == 1 and f"{web}/queue" in body2
        assert "How many jobs wait for the worker." in body2

        # Nothing changed: nothing written.
        same = await session.call_tool("source", {"id": source["id"], "fixes": []})
        assert same.structured_content["saved"] is False and same.structured_content["ran"] is True

        # Another address is another check: written, and waiting for the owner again.
        moved = await session.call_tool("source", {"id": source["id"], "check": {**check, "url": f"{web}/queue?full=1"}})
        assert (moved.structured_content["saved"], moved.structured_content["ran"]) == (True, False)
        assert (moved.structured_content["source"]["status"], moved.structured_content["source"]["why"]) == ("grey", "waiting")

        # A second source under a name that is taken is refused, naming the one that has it.
        twin = await session.call_tool("source", {**QUEUE, "check": check})
        assert twin.is_error is True
        assert "sources/queue.md" in twin.content[0].text and source["id"] in twin.content[0].text
        assert len((await session.call_tool("sources", {})).structured_content["sources"]) == 1
        streams.assert_hygiene(token=TEST_TOKEN)


def test_a_source_is_made_checked_listed_and_changed(f2_dsn: str, tmp_path: Path, web: str) -> None:
    anyio.run(_made_checked_and_listed, f2_dsn, tmp_path, web)


async def _command_waits(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-cmd") as (session, streams):
        names = {t.name for t in (await session.list_tools()).tools}
        assert {"sources", "source"} <= names
        assert not [n for n in names if "approv" in n], "the agent proposes; only the owner's app approves"
        schema = next(t for t in (await session.list_tools()).tools if t.name == "source").input_schema
        assert not [p for p in schema["properties"] if "approv" in p]

        check = {"kind": "cmd", "argv": ["/bin/echo", "7 percent used"], "parse": r"(\d+) percent", "max": 90}
        made = await session.call_tool("source", {**QUEUE, "title": "Disk", "check": check})
        assert made.is_error is False, made.content
        out = made.structured_content
        assert (out["created"], out["ran"], out["result"]) == (True, False, None)
        assert "waiting for the owner" in out["why_not"] and "/bin/echo" in out["why_not"]
        source = out["source"]
        assert (source["status"], source["why"], source["needs_approval"], source["approved"]) == ("grey", "waiting", True, False)
        assert source["checked_at"] is None and len(source["check_hash"]) == 64

        # Nothing the agent can call changes that. Asking again to run it changes nothing either.
        retry = await session.call_tool("source", {"id": source["id"]})
        assert retry.structured_content["ran"] is False and retry.structured_content["saved"] is False

        _approve(f2_dsn, source["id"], source["check_hash"])
        ran = await session.call_tool("source", {"id": source["id"]})
        assert ran.is_error is False, ran.content
        result = ran.structured_content["result"]
        assert ran.structured_content["ran"] is True
        assert (result["ok"], result["value"]) == (True, 7.0)
        assert result["raw"].strip() == "7 percent used", "the number stands beside the command's own words"
        assert ran.structured_content["source"]["status"] == "ok" and ran.structured_content["source"]["approved"] is True

        # Any change to the check is a different check: it waits for the owner again, and is not run.
        edited = await session.call_tool("source", {"id": source["id"], "check": {**check, "argv": ["/bin/echo", "8 percent used"]}})
        assert edited.is_error is False, edited.content
        assert (edited.structured_content["saved"], edited.structured_content["ran"]) == (True, False)
        now = edited.structured_content["source"]
        assert (now["status"], now["why"], now["needs_approval"]) == ("grey", "waiting", True)
        assert now["check_hash"] != source["check_hash"]
        streams.assert_hygiene(token=TEST_TOKEN)


def test_a_command_waits_for_the_owner_and_a_changed_one_waits_again(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_command_waits, f2_dsn, tmp_path)


async def _one_failure(f2_dsn: str, tmp_path: Path, web: str) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-down") as (session, streams):
        made = await session.call_tool("source", {**QUEUE, "title": "Status page", "check": {"kind": "http", "url": f"{web}/down"}})
        assert made.is_error is False, made.content
        assert made.structured_content["ran"] is False, "an address waits for the owner first"
        source = made.structured_content["source"]
        _approve(f2_dsn, source["id"], source["check_hash"])

        ran = await session.call_tool("source", {"id": source["id"]})
        assert ran.is_error is False, ran.content
        out = ran.structured_content
        assert out["ran"] is True and out["result"]["ok"] is False
        assert out["result"]["detail"] == "HTTP 503"
        assert "maintenance window" in out["result"]["raw"], "the failure stands beside what the check saw"
        assert "NOT ok" in ran.content[0].text
        source = out["source"]
        # The first failure is looked at again quietly: not red, and when.
        assert (source["status"], source["failures"], source["detail"]) == ("ok", 1, "HTTP 503")
        first = datetime.fromisoformat(source["checked_at"])
        assert (datetime.fromisoformat(source["next_check_at"]) - first).total_seconds() == 300

        # Running it again at once is not a second failure, so it is still not red.
        again = await session.call_tool("source", {"id": source["id"]})
        assert again.structured_content["result"]["ok"] is False
        assert (again.structured_content["source"]["status"], again.structured_content["source"]["failures"]) == ("ok", 1)
        listed = (await session.call_tool("sources", {})).structured_content["sources"]
        assert [(r["status"], r["failures"]) for r in listed] == [("ok", 1)]
        streams.assert_hygiene(token=TEST_TOKEN)


def test_one_failure_is_shown_beside_what_it_saw_and_is_not_red(f2_dsn: str, tmp_path: Path, web: str) -> None:
    anyio.run(_one_failure, f2_dsn, tmp_path, web)


async def _lookup_and_tool_wait(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-dns") as (session, streams):
        made = await session.call_tool("source", {**QUEUE, "title": "Name", "check": {"kind": "dns", "host": "localhost"}})
        assert made.is_error is False, made.content
        out = made.structured_content
        assert (out["ran"], out["result"]) == (False, None), "a name lookup waits for the owner like every check"
        assert "waiting for the owner" in out["why_not"] and "Looks up localhost" in out["why_not"]
        source = out["source"]
        assert (source["status"], source["why"], source["kind"], source["where"], source["needs_approval"]) == (
            "grey", "waiting", "dns", "anywhere", True)

        _approve(f2_dsn, source["id"], source["check_hash"])
        ran = await session.call_tool("source", {"id": source["id"]})
        assert ran.is_error is False, ran.content
        out = ran.structured_content
        assert (out["ran"], out["why_not"], out["result"]["ok"]) == (True, None, True)
        assert out["result"]["detail"].startswith("resolves to ") and out["result"]["raw"].strip()
        assert (out["source"]["status"], out["source"]["approved"]) == ("ok", True)

        # A tool of an MCP server waits too, and the words say what it will be sent.
        tool = await session.call_tool("source", {**QUEUE, "title": "Tool", "check": {
            "kind": "mcp", "url": "http://127.0.0.1:9/mcp", "tool": "get_status", "args": {"scope": "all"}}})
        assert tool.is_error is False, tool.content
        assert tool.structured_content["ran"] is False and tool.structured_content["result"] is None
        assert 'with {"scope": "all"}' in tool.structured_content["why_not"]
        assert tool.structured_content["source"]["why"] == "waiting"
        streams.assert_hygiene(token=TEST_TOKEN)


def test_a_name_lookup_and_a_tool_of_an_mcp_server_wait_for_the_owner_like_every_check(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_lookup_and_tool_wait, f2_dsn, tmp_path)


async def _refusals(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-refused") as (session, streams):
        bad = {
            "a shell line instead of a command and its words": {"kind": "cmd", "argv": "echo hi"},
            "a field the kind does not take": {"kind": "http", "url": "http://127.0.0.1:1/x", "bogus": 1},
            "a tool that is not a reading tool": {"kind": "mcp", "url": "http://127.0.0.1:1/mcp", "tool": "delete_everything"},
            "a password in the address": {"kind": "http", "url": "http://user:pw@127.0.0.1/x"},
            "a kind only the app uses": {"kind": "connections"},
            "a file with no home or root": {"kind": "file", "path": "relative/path"},
        }
        for why, check in bad.items():
            refused = await session.call_tool("source", {**QUEUE, "check": check})
            assert refused.is_error is True, why
            assert refused.content[0].text.startswith("check:"), (why, refused.content[0].text)
        for args, word in (
            ({"title": "Queue"}, "needs gives"),   # a new source needs all its parts
            ({**QUEUE, "run": "yes"}, "run"),
            ({**QUEUE, "check": {"kind": "dns", "host": "localhost"}, "stray": 1}, "stray"),
            ({"id": "sources/nothing.md", "fixes": []}, "nothing.md"),
        ):
            refused = await session.call_tool("source", args)
            assert refused.is_error is True and word in refused.content[0].text, (args, refused.content[0].text)
        assert (await session.call_tool("sources", {"id": "sources/nothing.md"})).is_error is True
        assert (await session.call_tool("sources", {})).structured_content["sources"] == [], "a refusal writes nothing"
        streams.assert_hygiene(token=TEST_TOKEN)


def test_a_bad_check_is_refused_with_why_and_writes_nothing(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_refusals, f2_dsn, tmp_path)


# --- the tools that read a source, and where the last report stopped (docs/design/morning-quality.md) -------------------

CHAT = {"title": "Team chat", "gives": "What the team wrote.", "how": "Read the dialogs, then the unread ones.",
        "since": "the last report's cut-off"}
READS = ["mcp__chat__list_messages", "mcp__chat__unread_summary"]
LAST_REPORT = """Checked against the sources by a second agent: all 10 passed.

## Sources

Times in Europe/Berlin.

| Source | Window | Read | Tasks | Inbox | Done | Put off | Context | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Team chat](doc:sources/team-chat.md) | 2026-10-10 07:00 – 2026-10-11 06:58 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
"""


async def _reads_and_cutoff(f2_dsn: str, tmp_path: Path) -> None:
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-reads") as (session, streams):
        check = {"kind": "dns", "host": "localhost", "reads": READS}
        made = await session.call_tool("source", {**CHAT, "check": check})
        assert made.is_error is False, made.content
        source = made.structured_content["source"]
        # The tools are in the check the owner approves, and the owner reads them beside Approve.
        assert source["reads"] == READS and source["needs_approval"] is True
        assert source["summary"].endswith("The morning report may call list_messages and unread_summary on chat.")
        body = (await session.call_tool("doc_get", {"path": "sources/team-chat.md"})).structured_content["doc"]["body"]
        assert '"reads"' in body and "mcp__chat__list_messages" in body

        # No report before it: no cut-off, and the document's own "Since when" says where to start.
        first = await session.call_tool("sources", {"day": "2026-10-12"})
        assert first.structured_content["sources"][0]["cutoff"] is None

        await session.call_tool("doc_create", {"path": "reports/morning/2026-10-11.md", "title": "Morning report — 11 October 2026",
                                               "body": LAST_REPORT})
        listed = await session.call_tool("sources", {"day": "2026-10-12"})
        assert listed.structured_content["sources"][0]["cutoff"] == "2026-10-11T06:58:00+02:00"
        one = await session.call_tool("sources", {"id": "sources/team-chat.md", "day": "2026-10-12"})
        assert one.structured_content["source"]["cutoff"] == "2026-10-11T06:58:00+02:00"
        # The same report is the day's own, not the one before it: its cut-off is not offered to itself.
        same_day = await session.call_tool("sources", {"day": "2026-10-11"})
        assert same_day.structured_content["sources"][0]["cutoff"] is None
        assert (await session.call_tool("sources", {"day": "yesterday"})).is_error is True

        # A source cannot hand the morning turn a tool of Verticals itself.
        refused = await session.call_tool("source", {**CHAT, "title": "Sneaky", "check": {**check, "reads": ["mcp__verticals__delete"]}})
        assert refused.is_error is True and "Verticals itself" in refused.content[0].text
        streams.assert_hygiene(token=TEST_TOKEN)


def test_a_source_names_the_tools_that_read_it_and_the_list_says_where_the_last_report_stopped(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_reads_and_cutoff, f2_dsn, tmp_path)


async def _connections_is_not_listed(f2_dsn: str, tmp_path: Path) -> None:
    """The app's own check of the agent's servers is nothing to read, so the morning's list leaves it out; by its path it is still
    there to look at. A document under sources/ with no check is a plain document, not a source: the list leaves it out too."""
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        connections = core.ensure_connections(conn, owner=TEST_OWNER)
    async with open_mcp_stdio(f2_dsn, tmp_path, label="source-connections") as (session, streams):
        await session.call_tool("doc_create", {"path": "sources/elena/transcript.md", "title": "A transcript", "body": "No check here."})
        made = await session.call_tool("source", {**CHAT, "check": {"kind": "dns", "host": "localhost", "reads": READS}})
        assert made.is_error is False, made.content
        listed = await session.call_tool("sources", {})
        assert [s["path"] for s in listed.structured_content["sources"]] == ["sources/team-chat.md"]
        assert listed.content[0].text.startswith("1 source(s)")
        one = await session.call_tool("sources", {"id": "sources/connections.md"})
        assert (one.structured_content["source"]["id"], one.structured_content["source"]["kind"]) == (connections, "connections")
        streams.assert_hygiene(token=TEST_TOKEN)


def test_the_list_leaves_connections_and_plain_documents_out(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_connections_is_not_listed, f2_dsn, tmp_path)
