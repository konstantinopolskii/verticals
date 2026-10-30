"""The morning report in the browser (docs/design/morning-quality.md): what the owner sees of it. The app asks for the report by
itself once the morning hour has come, the desktop gateway runs the agent that writes it and the second agent that checks it, and the
agent is the fake one (`tests/ui/fake_agent/fake_morning.py`) playing both against the real server. What is pinned here: the step is
written inside the field, beside the turning line, never in a bubble above it; the owner is told the report is ready only after the
check; the comments left in the last report are on their tasks and listed in the ask; what could not be read stands on top of the
report in red. Sample sources only ("Team chat", "Mail")."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import psycopg
import pytest
from playwright.sync_api import Browser, expect

from tests.core.morning_sample import goal_row, make_report, make_task, report_body, source_doc, source_row, sources_section
from tests.ui.conftest import F2_OWNER, PINNED_DAY, TEST_TOKEN, UiSession, _backend, _make_ui_session
from tests.ui.test_agent_conversation import _agent_gateway
from tests.ui.test_morning_flow import CHAT_READS, RAW, YESTERDAY
from tests.ui.views import tick
from verticals.core import docs as core_docs

RED = "rgb(201, 58, 91)"
COMMENT = "Ask the lawyer first | and not before Friday"


@pytest.fixture
def ui_morning(
    browser: Browser, f2_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None, ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """F2 with two sample sources and yesterday's report, served by the desktop gateway over the fake agent, the pinned day's
    morning report NOT taken: the app (its clock says 09:00) asks for it by itself as it opens. `request.param` shapes the day:
    `scenario` (the fake agent's, `fake_morning.py`), `mail_approved`, `comment` (left in yesterday's report on a task)."""
    plan = getattr(request, "param", {})
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        with _agent_gateway(backend, tmp_path, env={"VERTICALS_TEST_CHECK_LIMIT": "30"}) as base_url:
            with psycopg.connect(backend.dsn, autocommit=True) as conn:
                source_doc(conn, F2_OWNER, "Team chat", reads=CHAT_READS)
                source_doc(conn, F2_OWNER, "Mail", approved=plan.get("mail_approved", True))
                rows = []
                if plan.get("comment"):
                    rows = [goal_row(make_task(conn, F2_OWNER, "Launch plan is shared"), "Launch plan is shared", comment=plan["comment"])]
                make_report(conn, F2_OWNER, date.fromisoformat(YESTERDAY), report_body(rows, sources_section([
                    source_row("Team chat", "2026-08-06 07:00", "2026-08-07 07:00", 2, ref="sources/team-chat.md"),
                    source_row("Mail", "2026-08-06 07:00", "2026-08-07 07:00", 1, ref="sources/mail.md"),
                ])))
            scenario = tmp_path / "desktop-state" / "chat-workspace" / "scenario.json"
            scenario.write_text(json.dumps({"morning": True, "raw": RAW, **plan.get("scenario", {})}))
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=base_url, request=request, reduced_motion=ui_reduced_motion,
            )


def _api(session: UiSession) -> httpx.Client:
    return httpx.Client(base_url=session.backend.base_url, headers={"Authorization": f"Bearer {TEST_TOKEN}"}, timeout=30)


def _report(session: UiSession, day: str = PINNED_DAY) -> dict:
    with _api(session) as api:
        docs = {d["path"]: d["id"] for d in api.get("/api/docs").json()["docs"]}
        return api.get(f"/api/docs/{docs[f'reports/morning/{day}.md']}").json()


def _stored_events(session: UiSession) -> list[dict]:
    """Every event the page kept of its conversations, oldest first of each."""
    return session.page.evaluate(
        "() => Object.entries(localStorage).filter(([key]) => key.startsWith('vt-chat:events:'))"
        ".flatMap(([, value]) => JSON.parse(value))")


def test_the_window_saves_its_agent_settings_for_the_background_timer(ui_morning: UiSession, tmp_path: Path) -> None:
    page = ui_morning.page
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Morning report", timeout=30000)
    page.locator('.circle-field__shape').click()
    page.locator('.agent-tag').click()
    with page.expect_response(lambda r: r.url.endswith('/__chat/morning') and r.request.method == 'POST', timeout=5000):
        page.get_by_role('button', name='Bypass permissions', exact=True).click()
    page.screenshot(path=str(tmp_path / "background-settings.png"))
    with page.expect_response(lambda r: r.url.endswith('/__chat/morning') and r.request.method == 'POST', timeout=5000):
        page.reload()
    saved = json.loads((ui_morning.backend._tmp_path / "desktop-state/morning.json").read_text())
    assert saved["settings"]["provider"] == "claude"
    assert saved["settings"]["permission"] == "bypassPermissions"
    assert saved["timezone"] == page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
    report = _report(ui_morning)
    page.goto(f"{ui_morning.base_url}/#doc/{report['id']}")
    expect(page.locator('.doc-detail__body')).to_contain_text("all 10 passed")
    page.screenshot(path=str(tmp_path / "background-report.png"))


@pytest.mark.parametrize("ui_morning", [{"scenario": {"checker_delay": 4}}], indirect=True)
def test_the_step_is_written_inside_the_field_and_the_report_is_told_only_after_the_check(ui_morning: UiSession) -> None:
    page = ui_morning.page
    step = page.locator('[data-role="agent-step"]')
    answer = page.locator('[data-role="circle-answer"]')
    # While the second agent reads: the circle is a pill, its step inside it, the line turning at its left end.
    expect(step).to_have_text("Checking the report", timeout=30000)
    expect(page.locator(".circle-field")).to_have_attribute("data-state", "working")
    assert page.locator('.circle-field__shape [data-role="agent-step"]').count() == 1, "the step stands inside the field"
    shape = page.locator(".circle-field__shape").bounding_box()
    assert shape is not None and abs(shape["width"] - 360) <= 1 and abs(shape["height"] - 84) <= 1
    line = page.locator(".circle-field__line").bounding_box()
    assert line is not None and abs((line["x"] + line["width"] / 2) - (shape["x"] + 42)) <= 1.5, "the line keeps the circle's centre"
    words = step.bounding_box()
    assert words is not None and words["x"] >= shape["x"] + 78 and words["x"] + words["width"] <= shape["x"] + shape["width"] - 52
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(1)
    # No bubble above it, and the owner is told nothing yet: the report stands in the library saying it is not checked.
    assert page.locator(".agent-step").count() == 0
    expect(answer).to_have_count(0)
    assert _report(ui_morning)["body"].split("\n")[0].startswith("Not checked yet")
    # Ready: the circle holds the one answer, the step is gone, and the report says who checked it.
    expect(answer).to_contain_text("Morning report", timeout=30000)
    expect(step).to_have_count(0)
    assert _report(ui_morning)["body"].split("\n")[0] == "Checked against the sources by a second agent: all 10 passed."
    events = _stored_events(ui_morning)
    assert [e["label"] for e in events if e["t"] == "step"] == ["Checking the report"]
    assert [e["step"] for e in events if e["t"] == "tool" and e.get("step")] == ["Reading Team chat"]
    assert [e.get("next") for e in events if e["t"] == "done"] == ["check", "verdict", None]


@pytest.mark.parametrize("ui_morning", [{"scenario": {"miss": 2, "checker_delay": 1.5}}], indirect=True)
def test_a_report_that_fails_its_check_is_fixed_while_the_field_goes_on_working_and_is_told_once(ui_morning: UiSession) -> None:
    page = ui_morning.page
    answer = page.locator('[data-role="circle-answer"]')
    expect(page.locator('[data-role="agent-step"]')).to_have_text("Checking the report", timeout=30000)
    expect(answer).to_contain_text("Morning report", timeout=40000)
    events = _stored_events(ui_morning)
    assert [e["label"] for e in events if e["t"] == "step"] == ["Checking the report", "Fixing the report", "Checking it again"]
    kinds = [e["t"] for e in events]
    assert kinds.index("text") > max(i for i, e in enumerate(events) if e["t"] == "done" and e.get("next")), "told after the last check"
    assert sum(1 for e in events if e["t"] == "done" and not e.get("next")) == 1
    body = _report(ui_morning)["body"]
    assert body.split("\n")[0] == "Checked against the sources by a second agent: all 10 passed."
    assert "| Every message placed | Fixed |" in body
    expect(page.locator('[data-role="agent-step"]')).to_have_count(0)


@pytest.mark.parametrize("ui_morning", [{"comment": COMMENT}], indirect=True)
def test_the_comments_left_in_the_last_report_are_on_their_tasks_word_for_word_and_the_ask_lists_them(ui_morning: UiSession) -> None:
    page = ui_morning.page
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Morning report", timeout=40000)
    with psycopg.connect(ui_morning.backend.dsn, autocommit=True) as conn:
        goal_id = conn.execute("SELECT id FROM goals WHERE owner = %s AND title = 'Launch plan is shared'", (F2_OWNER,)).fetchone()[0]
    with _api(ui_morning) as api:
        threads = api.get(f"/api/goals/{goal_id}/comments").json()["threads"]
        assert [t["messages"][0]["body"] for t in threads] == [COMMENT]
        old = _report(ui_morning, YESTERDAY)["body"]
    assert COMMENT.replace("|", "\\|") not in old and "Your comment is on the task." in old, "the cell is cleared, with its receipt"
    asked = next(e["text"] for e in _stored_events(ui_morning) if e["t"] == "user" and e.get("app"))
    assert f"- Launch plan is shared (id {goal_id}): {json.dumps(COMMENT)}" in asked
    assert "word for word" in asked


@pytest.mark.parametrize("ui_morning", [{"mail_approved": False, "scenario": {"unread": ["Mail: waiting for your Approve, so it was not read."]}}],
                         indirect=True)
def test_what_could_not_be_read_stands_on_top_of_the_report_in_red(ui_morning: UiSession) -> None:
    page = ui_morning.page
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Morning report", timeout=40000)
    report = _report(ui_morning)
    assert report["body"].startswith("```unread\nMail: waiting for your Approve")
    page.goto("about:blank")
    page.goto(f"{ui_morning.base_url}/#doc/{report['id']}")
    block = page.locator('[data-role="doc-detail"] pre[data-md-fence="unread"]')
    expect(block).to_contain_text("Mail: waiting for your Approve", timeout=15000)
    expect(block).to_have_css("color", RED)
    expect(block).to_have_css("border-left-color", RED)
    # It is the first thing in the document.
    assert block.evaluate("el => el.previousElementSibling === null || !el.previousElementSibling.textContent.trim()")


def test_a_parent_task_in_a_report_table_is_a_bold_link_that_opens_it_and_a_plain_save_writes_it_back_as_written(
    ui_f2: UiSession,
) -> None:
    """The report writes a task with children in bold, as a link: `**[Name](goal:<id>)**` (web lib/bodyMarkdown.ts). It draws as
    one bold link, no asterisks and nothing to type over, it opens its task, and a save of the words around it writes the cell
    back exactly as it was written."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = make_task(conn, F2_OWNER, "Launch plan is shared", day=date.fromisoformat(PINNED_DAY))
        body = ("Words before it.\n\n| Task | Purpose |\n| --- | --- |\n"
                f"| **[Launch plan is shared](goal:{goal_id})** | The team works from one plan. |\n"
                f"| – [Press list is ready](goal:{goal_id}) | Reporters are named. |\n\nWords after it.")
        doc_id = core_docs.create(conn, owner=F2_OWNER, path="syn-report/bold.md", title="Bold links", body=body).doc.id

    def open_doc():
        page.goto("about:blank")
        page.goto(f"{session.base_url}/#doc/{doc_id}")
        return page.locator('[data-cap="docs"] [data-role="doc-body"]')

    text = open_doc()
    link = text.locator("td strong a")
    expect(link).to_have_text("Launch plan is shared", timeout=10000)
    expect(link).to_have_attribute("data-link-kind", "goal")
    expect(link).to_have_attribute("data-link-target", goal_id)
    assert "**" not in text.inner_text() and text.locator("td a").count() == 2
    # It opens its task (a click on a link while the text is being edited only places the caret, so this comes first).
    tick(page)
    link.click()
    expect(page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')).to_be_visible(timeout=10000)
    # A plain save of the words around the table: the cell comes back as it was.
    text = open_doc()
    expect(text.locator("td strong a")).to_have_count(1, timeout=10000)
    tick(page)
    text.locator("p", has_text="Words after it.").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" Edited.")
    page.wait_for_timeout(1500)
    with _api(session) as api:
        saved = api.get(f"/api/docs/{doc_id}").json()
    assert saved["revision"] > 1 and saved["body"] == body.replace("Words after it.", "Words after it. Edited.")
