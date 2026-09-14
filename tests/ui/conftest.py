"""Shared fixtures for suite D (`ui`, `docs/E2E.md` §6) — Playwright (Chromium) against the real
production build and a real backend, no mocks anywhere (E2E.md §1's house rule). Raw `playwright`
(the Python package pinned in `pyproject.toml`'s `dev` extra), not `pytest-playwright` — that
plugin is not a dependency (`docs/PENDING_DOC_FIXES.md` row 36 is the doc side of this; this file
is the code side: `browser`/`context`/`page` are hand-built below via `sync_playwright()`, not
injected by a plugin fixture of the same name).

Layering, most specific last, mirroring `tests/http/conftest.py`'s own documented shape:

    db_dsn (tests/conftest.py)     a fresh F0 clone: migrations at head, zero rows
    f1_dsn / f1u_dsn / f2_dsn       the same clone with a fixture loaded on top
    backend (below)                 a live `python -m verticals.api.app` subprocess, free port
    static (below)                   `npm run build` once per session, then a live
                                     `vite preview` subprocess pointed at `backend` via
                                     `VITE_API_PROXY_TARGET` (`web/vite.config.ts`'s own
                                     `preview.proxy` — see that file's WP-22 comment, which
                                     names this exact fixture as the intended caller)
    ui_f1 / ui_f1u / ui_f2 (below)  browser context + page, instrumented, navigated to `static`

E2E.md §6's own teardown line for this suite: "dump the console log and the network log to
`artifacts/ui/<S-id>/`, assert zero uncaught exceptions and zero failed requests other than those
the scenario deliberately caused, close the browser context, stop uvicorn and the static server,
then `DROP DATABASE ... WITH (FORCE)`. The built `dist/` is reused across scenarios and rebuilt
once per run." Every scenario in this package is a happy path (none deliberately causes a failed
request), so the zero-failure assertion is unconditional here rather than plumbed as a per-test
opt-out nobody in this package would ever exercise.

Test-side instrumentation (E2E.md §1's exactly-three-entries list): this file installs entry 1
(dialog recorder) and entry 3 (pinned clock). Entry 2 (audio recorder) is not installed here —
none of S-61/62/63/64/65/66/125 touches audio (that is S-70/S-74, WP-23's "sounds" card), and
S-109's static audit counts the *union* actually present in `tests/ui/`, so adding unused
instrumentation here would be inventing a mechanism this package has no scenario to justify.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg
import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from tests.harness.report import artifact, scenario_id_of
from tests.ui.gesture_counter import GestureCounter

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
F1_SQL = REPO_ROOT / "verticals" / "db" / "seed_sample.sql"
F1U_SQL = FIXTURES_DIR / "f1u_user_rows.sql"
F2_SQL = FIXTURES_DIR / "f2_synth.sql"

# Test-only, never a value that means anything outside this suite's own throwaway subprocesses —
# same convention as tests/http/conftest.py's TEST_TOKEN.
TEST_TOKEN = "ui-suite-test-token-not-a-real-deployment"
F2_OWNER = "t1"  # F2's primary owner (docs/E2E.md §2); none of this package's scenarios need t2
F1_OWNER = "local"  # seed_sample.sql's own owner (docs/IMPLEMENTATION.md §6.3 default) — S-61/62
                     # run against the single-owner Stage-0 board, not F2's multi-owner one

# docs/E2E.md §6: "launches Chromium at 1458×779 unless stated ... Animations are disabled with
# prefers-reduced-motion."
VIEWPORT = {"width": 1458, "height": 779}
UI_REDUCED_MOTION = "reduce"
# The pinned date, verbatim from E2E.md §1 instrumentation entry 3 and repeated in §6's own line.
PINNED_CLOCK_ISO = "2026-08-08T09:00:00+03:00"

ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "ui"


EXPANDED_COLUMN_CLASS = "pattern-vertical-board__column--active"


def expand_column(page: Page, vertical: str) -> None:
    """Compact board (D244): unfold one column's stacks via its header toggle. Same-column
    subtasks leave a compact column's DOM flow entirely, so any scenario that reads or drags a
    nested card must expand its column first — exactly the user's own gesture. Idempotent: an
    already-expanded column is left alone (the header click is a TOGGLE; clicking again would
    fold it)."""
    column = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]')
    if vertical == "maybe" or column.count() == 0:
        return
    if EXPANDED_COLUMN_CLASS in (column.get_attribute("class") or ""):
        return
    header = column.locator(".pattern-vertical-board__header").first
    if header.count() == 0:
        return
    header.click()
    page.wait_for_function(
        """vertical => document.querySelector(
             `.pattern-vertical-board__column[data-vertical="${vertical}"]`
           )?.classList.contains('pattern-vertical-board__column--active')""",
        arg=vertical,
        timeout=5000,
    )


def activate_column(page: Page, vertical: str) -> None:
    """Make one column's contents reachable for the pointer. On the compact board (D244 — the
    product default) that means the header-toggle expansion; on the dev-panel 3D deck it is the
    original D181 pointer-strip promotion."""
    board = page.locator(".pattern-vertical-board")
    if board.count() == 0:
        # Callers often land here straight off page.reload(), before Vue has mounted the board.
        # Returning on that transient made the whole call a silent no-op and the column stayed
        # compact — a real, reproduced flake (test_v2_subgoals' D242 split test, full-suite run
        # 2026-08-17). Wait out the mount; a context with genuinely no board (a non-board view)
        # still gets the old no-op, just after the grace instead of instantly.
        try:
            board.first.wait_for(state="attached", timeout=10_000)
        except PlaywrightTimeoutError:
            return
    if "pattern-vertical-board--flat" in (board.get_attribute("class") or ""):
        expand_column(page, vertical)
        return

    if vertical == "day":
        return
    viewport = page.viewport_size
    if viewport is not None and viewport["width"] < 900:
        return

    column = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]')
    column.wait_for(state="visible")
    active_class = "pattern-vertical-board__column--deck-active"
    if active_class in (column.get_attribute("class") or ""):
        return

    box = column.bounding_box()
    if box is None:
        raise AssertionError(f"activate_column: {vertical!r} column has no live bounding box")
    next_column = column.locator("xpath=following-sibling::*[1]")
    next_box = next_column.bounding_box() if next_column.count() else None
    visible_right = next_box["x"] if next_box is not None else box["x"] + box["width"]
    viewport_width = float(viewport["width"]) if viewport is not None else visible_right
    strip_left = max(0.0, box["x"])
    strip_right = min(viewport_width, visible_right)
    if strip_right <= strip_left:
        column.scroll_into_view_if_needed()
        box = column.bounding_box()
        next_box = next_column.bounding_box() if next_column.count() else None
        if box is None:
            raise AssertionError(f"activate_column: {vertical!r} vanished after scroll")
        visible_right = next_box["x"] if next_box is not None else box["x"] + box["width"]
        strip_left = max(0.0, box["x"])
        strip_right = min(viewport_width, visible_right)
    point = {
        "x": (strip_left + strip_right) / 2,
        "y": box["y"] + box["height"] / 2,
    }
    page.mouse.move(
        point["x"],
        point["y"],
        steps=5,
    )

    deadline = time.monotonic() + 5.0
    previous: dict[str, float] | None = None
    while time.monotonic() < deadline:
        if active_class not in (column.get_attribute("class") or ""):
            page.wait_for_timeout(25)
            continue
        current = column.bounding_box()
        if current is None:
            previous = None
            page.wait_for_timeout(100)
            continue
        if previous is not None and all(abs(current[key] - previous[key]) < 0.5 for key in current):
            return
        previous = current
        page.wait_for_timeout(100)
    hit_vertical = page.evaluate(
        "point => document.elementFromPoint(point.x, point.y)?.closest('[data-vertical]')?.dataset.vertical || null",
        point,
    )
    raise AssertionError(
        f"activate_column: {vertical!r} did not become active with stable geometry "
        f"(point={point}, hit_vertical={hit_vertical!r}, box={box}, next_box={next_box})"
    )


def _free_port() -> int:
    """Reserve a loopback port for a throwaway test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def f1_dsn(db_dsn: str) -> str:
    """`db_dsn` (tests/conftest.py) with F1 — the shipped sample board — loaded on top."""
    conn = psycopg.connect(db_dsn, autocommit=True)
    try:
        conn.execute(F1_SQL.read_text())
        conn.execute("ANALYZE goals")
    finally:
        conn.close()
    return db_dsn


@pytest.fixture
def f1u_dsn(f1_dsn: str) -> str:
    """F1 plus `USERROW1`/`USERROW2` (docs/E2E.md §2, "F1u"). Depends on `f1_dsn`, not `db_dsn`
    directly, so F1 always loads first — `tests/fixtures/f1u_user_rows.sql`'s own header states
    this ordering requirement; making it a Python fixture dependency is what enforces it rather
    than trusting every caller to remember the sequence."""
    conn = psycopg.connect(f1_dsn, autocommit=True)
    try:
        conn.execute(F1U_SQL.read_text())
        conn.execute("ANALYZE goals")
    finally:
        conn.close()
    return f1_dsn


@pytest.fixture
def f2_dsn(db_dsn: str) -> str:
    """Identical reasoning to `tests/http/conftest.py::f2_dsn` — duplicated rather than shared
    across a suite boundary."""
    conn = psycopg.connect(db_dsn, autocommit=True)
    try:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")
    finally:
        conn.close()
    return db_dsn


# --- backend: a real `python -m verticals.api.app` subprocess -----------------------------------


@dataclass
class Server:
    base_url: str
    token: str
    dsn: str
    log_path: Path
    #: The live subprocess and the port it holds. Both are here, rather than closed over inside
    #: `_backend` below, for exactly one scenario: S-75 ("the UI degrades honestly when the backend
    #: is gone") has to *actually kill uvicorn* and later bring it back — E2E.md §1's no-mocks rule
    #: means a simulated outage (route interception, an injected 503) is not the scenario. Every
    #: other test in this package leaves both fields alone and the fixture's own teardown is
    #: unchanged.
    port: int = 0
    proc: subprocess.Popen | None = None
    owner: str = ""
    _tmp_path: Path | None = None

    def kill_backend(self) -> None:
        """SIGTERM the uvicorn subprocess and wait for the port to be released. Idempotent — a
        second call on an already-dead server is a no-op, so a test that kills in a step and the
        fixture teardown that kills again never fight."""
        if self.proc is None or self.proc.poll() is not None:
            return
        _shutdown(self.proc, self.port)
        self.proc = None

    def restart_backend(self) -> None:
        """Start a fresh `python -m verticals.api.app` on the *same* port, against the same DSN.
        Same port is not a detail: the static server in front of the browser was started with
        `VITE_API_PROXY_TARGET` pointing at this exact origin, and Vite's preview proxy resolves
        that target per request, so a restart on the same port is transparent to the page."""
        assert self._tmp_path is not None, "restart_backend called on a Server built by hand"
        self.proc = _spawn_backend(self.dsn, self.owner, self.port, self.log_path, self._tmp_path)
        _wait_http_ok(f"{self.base_url}/healthz", self.proc, self.log_path)


def _wait_http_ok(url: str, proc: subprocess.Popen, log_path: Path, timeout: float = 10.0) -> None:
    """Poll `url` until it answers (any response at all means the server is up and routing —
    the backend's own `/healthz` returns 200 specifically; the static server's `/` returns 200
    with the built `index.html`). A process that has already exited is a clearer failure than a
    client timeout later, so `poll()` is checked every loop turn — same shape as
    `tests/http/conftest.py::_wait_healthy`, duplicated for the same stated reason."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise RuntimeError(f"process exited early (code {proc.returncode}); tail of log:\n{tail}")
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.1)
    raise TimeoutError(f"{url} never returned 200 within {timeout}s (last error: {last_exc})")


def _shutdown(proc: subprocess.Popen, port: int) -> None:
    """SIGTERM, wait up to 5s, SIGKILL if still alive, then assert the port was released —
    identical to `tests/http/conftest.py::_shutdown`."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
    time.sleep(0.1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        released = s.connect_ex(("127.0.0.1", port)) != 0
    assert released, f"port {port} still accepting connections after teardown"


def _spawn_backend(dsn: str, owner: str, port: int, log_path: Path, tmp_path: Path) -> subprocess.Popen:
    """One `python -m verticals.api.app` subprocess on `port`. Factored out of `_backend` below so
    `Server.restart_backend` (S-75) can produce a byte-identical second process rather than a
    near-copy that drifts from this one."""
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL=dsn,
        VERTICALS_TOKEN=TEST_TOKEN,
        VERTICALS_OWNER=owner,
        VERTICALS_BIND=f"127.0.0.1:{port}",
        VERTICALS_POOL_MIN="2",
        VERTICALS_POOL_MAX="10",
        VERTICALS_LOG_LEVEL="warning",
    )
    # Append, never truncate: a restart must not erase the first process's log, which is the only
    # record of what the backend was doing before the scenario killed it.
    logfile = open(log_path, "a")
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "verticals.api.app"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        logfile.close()  # the child holds its own dup of the fd; the parent's copy is not needed


@contextmanager
def _backend(dsn: str, owner: str, tmp_path: Path) -> Iterator[Server]:
    port = _free_port()
    log_path = tmp_path / "backend.log"
    log_path.write_text("")
    proc = _spawn_backend(dsn, owner, port, log_path, tmp_path)
    base_url = f"http://127.0.0.1:{port}"
    server = Server(
        base_url=base_url,
        token=TEST_TOKEN,
        dsn=dsn,
        log_path=log_path,
        port=port,
        proc=proc,
        owner=owner,
        _tmp_path=tmp_path,
    )
    try:
        _wait_http_ok(f"{base_url}/healthz", proc, log_path)
        yield server
    finally:
        server.kill_backend()


# --- static server: `npm run build` once per session, `vite preview` per test ------------------


@pytest.fixture(scope="session")
def web_dist() -> None:
    """`npm --prefix web run build` — the Makefile's own `build-web` target, invoked the same
    way, once per test-session (E2E.md §6: "the built `dist/` is reused across scenarios and
    rebuilt once per run"). A real subprocess, real esbuild/rollup, real output on disk — nothing
    about the production bundle is faked for the test.

    `web/src/lib/api.ts`'s own header comment states the contract this fixture must keep:
    "`tests/ui/conftest.py` controls both halves for the suite and keeps them equal by
    construction" — `VITE_VERTICALS_TOKEN` (baked into the client bundle at this build) must equal
    `TEST_TOKEN` (handed to every `_backend()` subprocess as `VERTICALS_TOKEN`). `VITE_VERTICALS_TOKEN`
    is explicitly set here, in the subprocess's own `env`, rather than left to whatever `web/.env*`
    happens to hold on a given machine — Vite's documented precedence is that a real process
    env var beats a same-named `.env`/`.env.local` value, so this line is what keeps the built
    bundle's token correct regardless of any local `.env.local` a developer's own manual-testing
    session may have left on disk (found the hard way: a stray `web/.env.local` from an earlier
    manual-verification pass baked in a different token and 401'd every request F1/F1u/F2 made)."""
    env = dict(os.environ)
    env["VITE_VERTICALS_TOKEN"] = TEST_TOKEN
    proc = subprocess.run(
        ["npm", "--prefix", "web", "run", "build"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"npm run build failed (exit {proc.returncode}):\nstdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    dist_index = WEB_DIR / "dist" / "index.html"
    if not dist_index.exists():
        raise RuntimeError(f"build reported success but {dist_index} does not exist")


@contextmanager
def _static_server(api_base_url: str, tmp_path: Path) -> Iterator[str]:
    """`vite preview` — a real static server in front of the just-built `dist/`, same-origin
    `/api` and `/healthz` proxy onto `api_base_url` via `VITE_API_PROXY_TARGET`
    (`web/vite.config.ts`'s `preview.proxy`). This is what makes the browser's requests
    same-origin (S-114/S-125's own CORS-closed assertion) without touching
    `verticals/api/app.py`, which registers no `CORSMiddleware` on purpose."""
    port = _free_port()
    log_path = tmp_path / "static.log"
    env = dict(os.environ)
    env["VITE_API_PROXY_TARGET"] = api_base_url
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            ["npm", "run", "preview", "--", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
            cwd=WEB_DIR,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_http_ok(f"{base_url}/", proc, log_path)
            yield base_url
        finally:
            _shutdown(proc, port)


# --- Playwright: session-scoped driver + browser, per-test context -----------------------------
#
# `playwright_driver`/`browser` themselves now live in the root `tests/conftest.py` — one
# `sync_playwright()` per process, shared with `tests/uidiff`, so a combined
# `PYTEST="tests/ui tests/uidiff"` run does not try to open the sync driver twice in one process
# (see that file's own comment on the collision this fixes). Everything below this line still
# resolves `browser` normally through pytest's fixture lookup; only the two upstream fixtures moved.


# Instrumentation entry 1 (E2E.md §1): a MutationObserver installed before app load, recording
# every node added with role="dialog" or [data-modal]. Context-level `add_init_script` so it is
# live for the *first* navigation of every test, not just reloads after the first.
_DIALOG_RECORDER_SCRIPT = """
(function () {
  window.__dialogRecords = [];
  function isDialog(node) {
    return node.nodeType === 1 && (
      (node.getAttribute && node.getAttribute('role') === 'dialog') ||
      (node.hasAttribute && node.hasAttribute('data-modal'))
    );
  }
  function record(node) {
    window.__dialogRecords.push({
      tag: node.tagName,
      role: node.getAttribute ? node.getAttribute('role') : null,
      dataModal: node.hasAttribute ? node.hasAttribute('data-modal') : false,
    });
  }
  var observer = new MutationObserver(function (mutations) {
    for (var i = 0; i < mutations.length; i++) {
      var added = mutations[i].addedNodes;
      for (var j = 0; j < added.length; j++) {
        var node = added[j];
        if (node.nodeType !== 1) continue;
        if (isDialog(node)) record(node);
        if (node.querySelectorAll) {
          var nested = node.querySelectorAll('[role="dialog"],[data-modal]');
          for (var k = 0; k < nested.length; k++) record(nested[k]);
        }
      }
    }
  });
  // `document.documentElement` (the <html> node) does not exist yet at the moment an
  // `add_init_script` binding runs — Chromium creates the Document before the HTML parser has
  // inserted <html>, so `.observe(document.documentElement, ...)` throws
  // "parameter 1 is not of type 'Node'" (confirmed live: documentElement is NULL at this point
  // for both about:blank and a real navigated page). `document` itself (the Document node) is
  // always a valid Node from the first instant a script can run, and observing it with
  // `subtree: true` covers every future descendant including the eventual <html> insertion, so
  // no dialog addition anywhere in the tree is missed.
  observer.observe(document, { childList: true, subtree: true });
})();
"""


@dataclass
class UiSession:
    """Everything a `test_sNN_*` function needs, bundled once per test so every scenario test
    reads the same shape. `gestures` starts at 0 at the moment this is handed to the test — the
    initial `page.goto` is infrastructure, not a scripted step of any scenario, and is issued
    before this object is constructed."""

    page: Page
    context: BrowserContext
    backend: Server
    base_url: str
    gestures: GestureCounter
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    bad_responses: list[str] = field(default_factory=list)
    #: Every completed request this session's page has issued, in order:
    #: `{"method", "url", "status", "headers"}`. Not part of E2E.md §6's teardown dump (that is
    #: `failed_requests`/`bad_responses` only) — this is a general request log so an individual
    #: scenario can assert its own exact request count/content (S-64's "exactly 1 request to
    #: `/api/goals`", S-65's create POST, S-125's `GET /api/search?q=cycl` and its Origin-header
    #: check) without each test wiring its own ad-hoc `page.on("request", ...)` listener. A test
    #: that only cares about requests issued *after* some point in the scenario should snapshot
    #: `len(session.request_log)` before acting and slice from there, same as `gestures.count`.
    #:
    #: Polling this list for a request that has not landed *yet* (a click fired an optimistic UI
    #: update before its network call settled — completeGoal's own shape) must poll via
    #: `session.page.wait_for_timeout(ms)` in the loop, never a bare `time.sleep(...)`. Confirmed
    #: live (`test_s64_complete_one_gesture.py`'s own history): Playwright's Python sync API is a
    #: greenlet bridge onto an async driver, and callbacks registered via `page.on(...)` — this
    #: file's own `requestfinished` listener below, which is what fills this list — are only
    #: actually dispatched when a Playwright call yields control back to the driver. A bare
    #: `time.sleep` in a test's own poll loop never yields to it, so a request that already
    #: finished in the real browser can sit un-dispatched for the *entire* sleep — a 2-second
    #: `time.sleep`-based poll found 0 requests on 3 straight runs for a request that had actually
    #: completed in well under 500ms every time.
    request_log: list[dict] = field(default_factory=list)
    #: E2E.md §6's teardown line assert "zero failed requests **other than those the scenario
    #: deliberately caused**". Every scenario in this package except one is a happy path and leaves
    #: this False, keeping the assertion unconditional for them. S-75 is the exception the doc
    #: sentence was written for: it kills uvicorn on purpose, so the failed request, the >=400
    #: response and the console error the dead backend produces are the scenario's *subject*, not
    #: a defect. Setting this suppresses only those three assertions — `page_errors` (uncaught
    #: exceptions) stays asserted unconditionally, because S-75's own text requires zero of those
    #: even with the backend gone. Both logs are still dumped to `artifacts/ui/<S-id>/` either way.
    expects_network_failures: bool = False

    def dialog_records(self) -> list[dict]:
        return self.page.evaluate("window.__dialogRecords || []")


def _make_ui_session(
    *, browser: Browser, backend: Server, static_base_url: str, request: pytest.FixtureRequest,
    reduced_motion: str,
) -> Iterator[UiSession]:
    context = browser.new_context(
        viewport=VIEWPORT,
        reduced_motion=reduced_motion,
    )
    context.add_init_script(script=_DIALOG_RECORDER_SCRIPT)
    page = context.new_page()

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []
    request_log: list[dict] = []

    page.on(
        "console",
        # Chromium mirrors every failed resource load into the console; the D226 sweep's benign
        # `?prefetch=1` 404 (see the requestfailed/response notes below) would otherwise trip
        # this gate through a second door. Same exemption, same reasoning, console edition.
        lambda msg: console_errors.append(f"[{msg.type}] {msg.text}")
        if msg.type == "error" and "prefetch=1" not in (msg.location or {}).get("url", "")
        else None,
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on(
        "requestfailed",
        # D237: `/api/events` is an endless SSE stream whose ONLY exit is an abort — page
        # reloads, navigation, and context teardown all cancel it by design, and Chromium
        # reports that cancel as a failed request. Excluding it here is recording reality, not
        # weakening the gate: an events stream that fails to OPEN surfaces as a >=400 response
        # (bad_responses) or as the board never live-updating, both still asserted elsewhere.
        lambda req: failed_requests.append(
            f"{req.method} {req.url} — {req.failure or 'unknown'}"
        )
        if "/api/events" not in req.url
        else None,
    )
    page.on(
        "response",
        # A 404 on a `?prefetch=1` detail read is the D226 sweep's one benign failure mode: the
        # goal was deleted (user gesture or a D237 agent write) between queueing and fetching.
        # The sweep revalidates against the live board before each fetch, but a request already
        # in flight when the delete lands can still answer 404 — best-effort by design, marked
        # on the wire precisely so this gate can keep failing every OTHER >=400 response.
        # The request body rides along because a >=400 on a write is unactionable without it:
        # "422 PATCH /api/goals/X" names the endpoint, `post_data` names the actual bad write.
        lambda res: bad_responses.append(
            f"{res.status} {res.request.method} {res.url} :: {res.request.post_data}"
        )
        if res.status >= 400 and not (res.status == 404 and "prefetch=1" in res.url)
        else None,
    )
    page.on(
        "requestfinished",
        lambda req: request_log.append(
            {
                "method": req.method,
                "url": req.url,
                "status": req.response().status if req.response() else None,
                "headers": req.headers,
            }
        ),
    )

    # Instrumentation entry 3 (E2E.md §1): fixes what the app reads as "now". Set before the
    # first navigation so every period-key computation in this session sees the pinned date.
    page.clock.set_fixed_time(PINNED_CLOCK_ISO)

    page.goto(static_base_url)

    session = UiSession(
        page=page,
        context=context,
        backend=backend,
        base_url=static_base_url,
        gestures=GestureCounter(page, activate_column),
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        bad_responses=bad_responses,
        request_log=request_log,
    )
    try:
        yield session
    finally:
        _dump_artifacts_and_assert_clean(session, request)
        context.close()


def _dump_artifacts_and_assert_clean(session: UiSession, request: pytest.FixtureRequest) -> None:
    """E2E.md §6's teardown line, in full: dump console + network logs to
    `artifacts/ui/<S-id>/`, then assert zero uncaught exceptions and zero failed requests. Every
    scenario in this package is a happy path (see module docstring), so both assertions are
    unconditional rather than gated behind a per-test opt-out nothing here would ever use."""
    sid = scenario_id_of(request.node.name) or "unknown"
    out_dir = ARTIFACTS_ROOT / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    console_path = out_dir / "console.log"
    console_path.write_text("\n".join(session.console_errors) or "(no console errors)")
    artifact(request, str(console_path.relative_to(REPO_ROOT)))

    network_path = out_dir / "network.log"
    network_lines = [f"FAILED  {line}" for line in session.failed_requests] + [
        f"STATUS  {line}" for line in session.bad_responses
    ]
    network_path.write_text("\n".join(network_lines) or "(no failed requests, no >=400 responses)")
    artifact(request, str(network_path.relative_to(REPO_ROOT)))

    assert session.page_errors == [], f"uncaught exception(s) in {sid}: {session.page_errors}"
    if session.expects_network_failures:
        return
    assert session.failed_requests == [], f"failed request(s) in {sid}: {session.failed_requests}"
    assert session.bad_responses == [], f">=400 response(s) in {sid}: {session.bad_responses}"
    assert session.console_errors == [], f"console error(s) in {sid}: {session.console_errors}"


@pytest.fixture
def ui_reduced_motion() -> str:
    """UI-suite motion preference; behavioural scenarios keep animation disabled by default."""
    return UI_REDUCED_MOTION


@pytest.fixture
def ui_f1(
    browser: Browser, f1_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """S-61: F1 on a fresh database, owner `local`. `web_dist` is a real dependency, not
    decoration — `_static_server` below serves `web/dist/`, so every fixture that starts one must
    force the session-scoped build first. pytest's own fixture caching means only the *first*
    test in a session actually runs `npm run build`; the other two fixtures (`ui_f1u`, `ui_f2`)
    get the cached result for free, matching E2E.md §6's "rebuilt once per run.\""""
    with _backend(f1_dsn, F1_OWNER, tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as static_base_url:
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=static_base_url, request=request,
                reduced_motion=ui_reduced_motion,
            )


@pytest.fixture
def ui_f1u(
    browser: Browser, f1u_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """S-62: F1u (F1 + USERROW1/USERROW2), owner `local`. See `ui_f1` on why `web_dist` is listed
    explicitly here too."""
    with _backend(f1u_dsn, F1_OWNER, tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as static_base_url:
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=static_base_url, request=request,
                reduced_motion=ui_reduced_motion,
            )


@pytest.fixture
def ui_f2(
    browser: Browser, f2_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """S-63 through S-66, S-125: F2, owner `t1` — the default fixture for this suite unless
    stated (E2E.md §6). See `ui_f1` on why `web_dist` is listed explicitly here too — all three
    fixtures share the one session-scoped build via pytest's normal fixture caching regardless of
    which test triggers it first."""
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as static_base_url:
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=static_base_url, request=request,
                reduced_motion=ui_reduced_motion,
            )
