"""The morning report, played by the fake agent (docs/design/morning-quality.md): no model, but the real machinery around it.

The fake `claude` calls this module when a scenario file (`scenario.json`, beside `argv.log`) turns the morning on. It then plays
the three seats the gateway starts, told apart by the instructions they were started with:

  * the **writer** reads the sources through the server's own list (`GET /api/sources?day=`, which carries each source's cut-off),
    "reads" the sample items the scenario gives for each source inside its window, and saves a report in the shape of the
    morning-report skill: the red block, the check line, the rows, what it closed and the sources with their windows and counts;
  * the **second agent** reads that report back, counts the same sample items inside the windows the report states, and answers
    the ten checks as a fenced json block, with the verdicts the scenario asks for laid over its own count;
  * the **fixer** is the writer again, told which checks failed: it writes the report again without the defects the scenario
    planted.

Everything it writes goes through the server's HTTP API with the token the test gateway wrote beside it (`fake-agent.json`), so a
scenario checks the cut-offs, the arithmetic, the check line and the hold-back for real. What the fake cannot show is whether a
model reads a source well: that is the second agent's job in the real app. Sample data only: the sources are "Team chat" and
"Mail", the tasks are whatever the scenario's board has.
"""
import json
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

KEYS = ("sources", "inputs", "continuity", "inbox", "changes", "state", "names", "hierarchy", "where", "copy")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def load(name):
    try:
        with open(name) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Api:
    def __init__(self, conf):
        self.base, self.token = conf["api"], conf["token"]

    def call(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")

    def doc_by_path(self, path):
        for doc in self.call("GET", "/api/docs")["docs"]:
            if doc["path"] == path:
                return self.call("GET", f"/api/docs/{doc['id']}")
        return None


def context_of(text):
    """The app context the gateway put before the words: the day, the zone and the time now."""
    block = text.split("<app_context>")[-1].split("</app_context>")[0]
    today = re.search(r"^Today: (\d{4}-\d{2}-\d{2})(?: \(([^)]+)\))?", block, re.M)
    now = re.search(r"^Now: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", block, re.M)
    return {"today": today.group(1) if today else None, "tz": (today.group(2) if today else None) or "UTC",
            "now": now.group(1) if now else None}


def local(moment, zone):
    return moment.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M")


def moment(text, zone):
    """'2026-08-07 22:10' (the zone's) or an ISO time with its offset, as an aware time."""
    parsed = datetime.fromisoformat(text.replace(" ", "T"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(zone))


def servers_of(detail):
    """The servers named by the Connections check's line ("all 3 answer: chat, mail, calendar")."""
    head = detail.split(";")[0]
    return [name.strip() for name in head.partition(": ")[2].split(",") if name.strip()] if ": " in head else []


def no_sources_line(servers):
    named = servers[0] if len(servers) == 1 else ", ".join(servers[:-1]) + " and " + servers[-1] if servers else ""
    return (f"No sources yet. The agent reaches {named}. Tell it what to read each morning, in one sentence." if named
            else "No sources yet. Tell the agent what to read each morning, in one sentence.")


def items_between(scenario, title, start, end, zone):
    return [item for item in scenario.get("raw", {}).get(title, []) if start <= moment(item["at"], zone) <= end]


# --- the writer ----------------------------------------------------------------------------------------------------


def write_report(scenario, api, words, ctx, tool, *, defects=True):
    """The report of the day asked for, saved as the skill shapes it. `defects` False writes it without the ones the scenario
    plants (a miss, counts that do not add up): that is the fixing turn."""
    day = re.search(r"for (\d{4}-\d{2}-\d{2})", words).group(1)
    task = re.search(r"\(id (\w+)\)", words).group(1)
    zone, now = ctx["tz"], moment(ctx["now"], ctx["tz"])
    tool("sources")
    listed = api.call("GET", f"/api/sources?day={day}")["sources"]
    sources = [s for s in listed if s["path"] != "sources/connections.md"]
    unread = list(scenario.get("unread", []))
    if not sources:
        # Nothing to read: the one line the contract asks for, naming the servers the app's Connections check found answering.
        connections = next((s for s in listed if s["path"] == "sources/connections.md"), None)
        unread.append(no_sources_line(servers_of(connections["detail"] if connections else "")))
    lines, rows = [], []
    for source in sources:
        title = source["title"]
        for read_tool in source.get("reads", [])[:1]:
            tool(read_tool)
        silent = any(line.lower().startswith(title.lower() + ":") for line in unread)
        cutoff = moment(source["cutoff"], zone) if source.get("cutoff") else None
        start = cutoff or moment(scenario.get("since", ctx["now"]), zone)
        if silent:
            read, places, end = 0, (0, 0, 0, 0, 0, 0), start
        else:
            found = len(items_between(scenario, title, start, now, zone))
            read = max(0, found - (scenario.get("miss", 0) if defects else 0))
            places = (read - (1 if scenario.get("unbalanced") and defects and read else 0), 0, 0, 0, 0, 0)
            end = now
        rows.append(f"| [{title}](doc:{source['path']}) | {local(start, zone)} – {local(end, zone)} | {read} | "
                    + " | ".join(str(n) for n in places) + " |")
    head = ["| Source | Window | Read | Tasks | Inbox | Done | Put off | Context | Gap |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    groups = {}  # heading -> rows, in the order the scenario first names the headings
    for goal in scenario.get("rows", []):
        # A row with no `id` is a proposal: no task yet, named by its result, linking nothing.
        name = f"[{goal['title']}](goal:{goal['id']})" if goal.get("id") else goal["title"]
        name = f"**{name}**" if goal.get("bold") else f"– {name}" if goal.get("child") else name
        groups.setdefault(goal.get("group", "Today"), []).append(
            f"| {name} | {goal.get('purpose', 'The purpose.')} | {goal.get('latest', 'Started.')} | {goal.get('next', 'Finish it.')}"
            f" | {goal.get('comment', '')} |")
    closed = []
    for item in scenario.get("close", []):
        gid, title, why = (item, item, "the sources show it is done.") if isinstance(item, str) else (
            item["id"], item.get("title", item["id"]), item.get("evidence", "the sources show it is done."))
        tool("update", {"id": gid, "done": True})
        api.call("PATCH", f"/api/goals/{gid}", {"done": True})
        tool("evidence_update")
        closed.append(f"- [{title}](goal:{gid}): {why}")
    parts = []
    if unread:
        parts.append("```unread\n" + "\n".join(unread) + "\n```")
    parts.append("Not checked yet: a second agent is reading it against the sources.")
    for heading, table in groups.items():
        parts.append(f"## {heading}\n\n| Task | Purpose | Latest | Next action | Your comment |\n| --- | --- | --- | --- | --- |\n"
                     + "\n".join(table))
    if closed:
        parts.append("## Closed since the last report\n\n" + "\n".join(closed))
    if sources:
        parts.append(f"## Sources\n\nTimes in {zone}.\n\n" + "\n".join(head + rows))
    body = "\n\n".join(parts) + "\n"
    year, month, dom = (int(n) for n in day.split("-"))
    title = f"Morning report — {dom} {MONTHS[month - 1]} {year}"
    path = f"reports/morning/{day}.md"
    existing = api.doc_by_path(path)
    if existing:
        tool("doc_save")
        saved = api.call("PATCH", f"/api/docs/{existing['id']}", {"expected_revision": existing["revision"], "body": body})
    else:
        tool("doc_create")
        saved = api.call("POST", "/api/docs", {"path": path, "title": title, "body": body})
        tool("doc_link")
        goal = api.call("GET", f"/api/goals/{task}")
        api.call("PATCH", f"/api/goals/{task}", {"body": (goal.get("body") or "") + f"[{title}](doc:{path})"})
    waiting = sum(1 for g in scenario.get("rows", []) if g.get("group", "Today").startswith("Inbox"))
    today = sum(1 for g in scenario.get("rows", []) if g.get("group", "Today") == "Today" and not g.get("child"))
    # Two short lines, the document's link on its own line, as the morning turn's rules ask.
    return (f"{waiting} {'decision waits' if waiting == 1 else 'decisions wait'} in the Inbox and "
            f"{today} {'thing is' if today == 1 else 'things are'} for today.\n[{title}](#doc/{saved['id']})")


# --- the second agent ------------------------------------------------------------------------------------------------


def check_report(scenario, api, words, ctx, tool, round_no):
    """The ten checks as the second agent would answer them: its own count of the sample items inside each window the report
    states, laid under the verdicts the scenario asks for in this round."""
    path = re.search(r"reports/morning/\d{4}-\d{2}-\d{2}\.md", words).group(0)  # `words` is the path, or the ask that names it
    tool("doc_get")
    doc = api.doc_by_path(path)
    verdict = {key: {"result": "pass"} for key in KEYS}
    if doc and scenario.get("checker_mode") != "blind":
        zone = (re.search(r"Times in (\S+?)\.", doc["body"]) or [None, ctx["tz"]])[1]
        misses = []
        for name, window, read in re.findall(r"^\| \[([^\]]+)\]\([^)]*\) \| ([^|]+?) \| (\d+) \|", doc["body"], re.M):
            found = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", window)
            if len(found) == 2:
                tool("sources")
                counted = len(items_between(scenario, name, moment(found[0], zone), moment(found[1], zone), zone))
                if counted != int(read):
                    misses.append(f"{name}: I count {counted} items, the report says {read}.")
        if misses:
            verdict["inputs"] = {"result": "fail", "note": " ".join(misses)}
    rounds = scenario.get("checker", [])
    for key, answer in (rounds[round_no] if round_no < len(rounds) else {}).items():
        verdict[key] = answer
    return "```json\n" + json.dumps({"checks": verdict}) + "\n```"
