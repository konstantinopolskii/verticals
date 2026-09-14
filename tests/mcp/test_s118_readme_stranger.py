"""S-118 — The stranger's agent, configured from the README and nothing else (`docs/E2E.md` §5).

Intent: M2's whole claim. Required by AC-161 (a third-party agent connects using only the README),
AC-162 (the README's config block cannot drift from the tested one), AC-163 (the agent path needs
no browser). Serves J2, L5, Stage 0.

**Fixture:** F1 (`verticals/db/seed_sample.sql`, the shipped six-row sample board, owner `local`) on
a fresh instance that has never held F2 or F3 — a fresh F0 clone, asserted empty before F1 lands,
which is the strongest available reading of "never held" on a template-cloned harness.

**Steps, per the catalogue:**
  1. extract the MCP configuration block from `README.md` **by reading the file**, never from a
     copy held in the test;
  2. hand it verbatim to a real `mcp` SDK client;
  3. `tools/list`;  4. `board`;  5. `create` one row;
  6. read that row back over `GET /api/goals/{id}` and then in a browser.

**Assert:** the extracted block is the block executed (a README edit that breaks it fails this
scenario, which is the point); `tools/list` returns the fourteen tools of S-47 (+WP-33, R11, R12); `board` returns the six
sample rows; the created row is visible over HTTP and then in the browser. The static server is
never started for steps 1-5 — no process is listening on the UI port — so the agent path is proven
not to need a browser.

---

**"Verbatim" against a block that carries three placeholders.** The README's block is a template
whose own prose names what a reader substitutes: `/absolute/path/to/verticals` ("Replace ... with
your checkout's real path") and `${VERTICALS_TOKEN}` ("If your client does not expand
`${VERTICALS_TOKEN}` ... replace it with the literal value the command above printed"). This module
performs exactly those two substitutions, and each is *asserted to have been necessary* — the
placeholder must be present in the extracted text, or the scenario fails. That is what keeps
"verbatim" meaningful: a README that stops carrying the placeholder, changes the command, renames
the server key, or drops an env variable fails here rather than being silently accommodated.

There is a third value this module rewrites, and it is a divergence rather than a substitution:
`VERTICALS_DATABASE_URL`. The block hardcodes the development database `make db-up` brings up
(`postgresql://verticals:verticals@127.0.0.1:55432/verticals`); this test must run against its own
throwaway clone, because the harness "refuses to run against a database whose name does not start
with `verticals_t`" (`docs/E2E.md` §2, `tests/conftest.py::_guard`) and because step 5 writes a row.
The URL is therefore replaced with this test's own clone DSN — same cluster, same credentials, a
different database name — after asserting that what the README carried was a `postgresql://` URL in
the first place. Everything the scenario is actually about (which interpreter, which module, which
env variable names, which owner, how the token reaches the process) is executed exactly as written.
This is reported as a doc-vs-code note rather than hidden: a block that read
`"VERTICALS_DATABASE_URL": "${VERTICALS_DATABASE_URL}"` would need no divergence at all.

**Where the token comes from — AC-161's own clause,** "`VERTICALS_TOKEN` exported from the generated
`.env` by the one documented command in the README's 'connect an agent' section". Both commands are
extracted from the README too, not typed here: the Configure section's generator block (the one
containing `secrets.token_urlsafe`) writes a real token into a `.env` this test makes by copying
`.env.example` — the effect of the README's own `cp .env.example .env` line, performed in a
temporary directory rather than over the developer's real `.env`, which is the one thing this
module refuses to touch — and the connect-an-agent section's `export VERTICALS_TOKEN=$(grep ...)`
line is then run, verbatim, to get that value into a shell environment. The token this test hands
to the client is whatever that pipeline printed. A README whose generator or whose grep line stops
working fails this scenario.

**The UI port, and how "the static server is never started" is proven.** A free loopback port is
reserved before step 1 and asserted closed after every one of steps 1-5. It is a port picked by the
kernel rather than the README's own 4173, deliberately: 4173 may legitimately be held by a
developer's own `npm run preview` on the same machine, which would make this scenario fail for a
reason that has nothing to do with the property under test. The port reserved here is one nothing
else on the machine is using, so "nothing is listening on it" isolates *this test's* behaviour —
and step 6 then starts the static server on that same port, which is what makes the assertion a
real before/after rather than a check against a port nobody was ever going to bind.

**Zone 1.** Nothing here touches `seed/`. F1 is the synthetic shipped sample; the row step 5 writes
is this module's own synthetic title. Both are safe to quote in a message.

Server plumbing (`_api_server`, `_static_server`, `_wait_http_ok`, `_shutdown`) is duplicated from
`tests/ui/conftest.py` rather than imported, following this suite's own stated convention (see
`tests/mcp/conftest.py`'s module docstring on `f2_dsn`, and `tests/uidiff/conftest.py`'s on the
same three helpers) of not crossing a suite boundary the harness does not otherwise cross. It lives
in this module rather than in `tests/mcp/conftest.py` because exactly one scenario in suite `mcp`
needs a browser at all, and putting a Playwright import in the shared conftest would make every
other `mcp` scenario depend on a browser binary it never drives.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anyio
import httpx2
import psycopg
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from playwright.sync_api import sync_playwright

from tests.mcp.test_tools import EXPECTED_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
F1_SQL = REPO_ROOT / "verticals" / "db" / "seed_sample.sql"
WEB_DIR = REPO_ROOT / "web"

CONNECT_SECTION = "Connect an agent over MCP"
PATH_PLACEHOLDER = "/absolute/path/to/verticals"
TOKEN_PLACEHOLDER = "${VERTICALS_TOKEN}"
PLACEHOLDER_TOKEN_VALUE = "REPLACE_ME_THIS_VALUE_NEVER_AUTHENTICATES"  # .env.example's own refusal

# The board's own anchor date, the same one `verticals/db/seed_sample.sql` anchors its week and day
# rows to (that file's own comment: "the product's own reference date, 2026-08-08") and the same
# date `docs/E2E.md` §1 pins every browser to. `board` requires the argument, so one has to be
# chosen; choosing this one is what makes all six sample rows fall on the board at once.
BOARD_DATE = "2026-08-08"
CREATED_TITLE = "S-118 stranger agent row"

_FENCE_RE = re.compile(r"^```(.*)$")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")


# --- README extraction (step 1: by reading the file, never from a copy held here) -----------------


def _fenced_blocks(markdown: str) -> list[tuple[str, str, str]]:
    """Every fenced block as `(info_string, body, enclosing_heading)`. A hand-rolled scanner rather
    than a markdown dependency: `pyproject.toml` pins six runtime choices and AC-086 asserts that
    set, so a parser library is not available to this repository for the sake of one test."""
    blocks: list[tuple[str, str, str]] = []
    heading = ""
    in_fence = False
    info = ""
    body: list[str] = []
    for line in markdown.splitlines():
        fence = _FENCE_RE.match(line)
        if fence:
            if in_fence:
                blocks.append((info.strip(), "\n".join(body), heading))
                in_fence, info, body = False, "", []
            else:
                in_fence, info, body = True, fence.group(1), []
            continue
        if in_fence:
            body.append(line)
            continue
        h = _HEADING_RE.match(line)
        if h:
            heading = h.group(1)
    assert not in_fence, "README.md has an unclosed code fence"
    return blocks


def _one(blocks: list[tuple[str, str, str]], what: str) -> tuple[str, str, str]:
    assert len(blocks) == 1, (
        f"expected exactly one {what} in README.md, found {len(blocks)} — this scenario executes "
        f"the block it finds, so an ambiguous README is a failure, not a choice to make here."
    )
    return blocks[0]


def _mcp_config_block(markdown: str) -> str:
    blocks = [
        b
        for b in _fenced_blocks(markdown)
        if b[0] == "json" and b[2] == CONNECT_SECTION and "mcpServers" in b[1]
    ]
    return _one(blocks, f"`json` MCP configuration block under '{CONNECT_SECTION}'")[1]


def _token_export_command(markdown: str) -> str:
    blocks = [
        b
        for b in _fenced_blocks(markdown)
        if b[2] == CONNECT_SECTION
        and b[0].startswith(("bash", "sh", "console"))
        and "VERTICALS_TOKEN=" in b[1]
    ]
    return _one(blocks, f"documented VERTICALS_TOKEN export command under '{CONNECT_SECTION}'")[1]


def _token_generator_command(markdown: str) -> str:
    blocks = [
        b
        for b in _fenced_blocks(markdown)
        if b[0].startswith(("bash", "sh", "console")) and "token_urlsafe" in b[1]
    ]
    return _one(blocks, "documented .env token generator block")[1]


def _sh(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", script], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def _token_from_readme(work_dir: Path) -> str:
    """AC-161's token clause, driven end to end through the README's own two commands. The `.env`
    is made in `work_dir` (never the repository's own) by copying `.env.example` — the effect of
    the README's `cp .env.example .env` line, which this module performs rather than executes so
    that no path in this test can ever resolve to the developer's real `.env`."""
    markdown = README.read_text()
    env_path = work_dir / ".env"
    shutil.copy(ENV_EXAMPLE, env_path)
    assert PLACEHOLDER_TOKEN_VALUE in env_path.read_text(), (
        ".env.example no longer ships the placeholder token this scenario generates over "
        "(docs/IMPLEMENTATION.md §6.3, S-113)"
    )

    generated = _sh(_token_generator_command(markdown), work_dir)
    assert generated.returncode == 0, (
        f"the README's own .env token generator block failed (exit {generated.returncode}): "
        f"{generated.stderr.strip()[-600:]}"
    )

    exported = _sh(f'{_token_export_command(markdown)}\nprintf %s "$VERTICALS_TOKEN"', work_dir)
    assert exported.returncode == 0, (
        f"the README's own VERTICALS_TOKEN export command failed (exit {exported.returncode}): "
        f"{exported.stderr.strip()[-600:]}"
    )
    token = exported.stdout
    assert token and token != PLACEHOLDER_TOKEN_VALUE, (
        "the README's documented export command produced no usable token "
        f"(got {token!r}) — a stranger following this section cannot authenticate."
    )
    return token


def _server_params_from_readme(token: str, dsn: str) -> tuple[StdioServerParameters, dict[str, str]]:
    """Step 2: the extracted block, turned into what a real `mcp` SDK client is handed. Every
    substitution is asserted to have been necessary — see the module docstring on what "verbatim"
    means against a block that documents its own placeholders."""
    raw = _mcp_config_block(README.read_text())
    config = json.loads(raw)  # a block that is not valid JSON fails right here, which is correct

    servers = config["mcpServers"]
    assert list(servers) == ["verticals"], f"expected one server named 'verticals', got {list(servers)}"
    entry = servers["verticals"]
    assert set(entry) == {"command", "args", "env"}, (
        f"the block's server entry carries {sorted(entry)} — this scenario executes command/args/"
        f"env and would silently ignore anything else a client is told to honour."
    )

    command = entry["command"]
    assert PATH_PLACEHOLDER in command, (
        f"the block's command no longer carries the {PATH_PLACEHOLDER!r} placeholder the README's "
        f"own prose tells a reader to replace: {command!r}"
    )
    command = command.replace(PATH_PLACEHOLDER, str(REPO_ROOT))
    assert Path(command).exists(), (
        f"the README's command resolves to {command!r}, which does not exist — a stranger "
        f"following this section would get 'no such file'. (The README's Prerequisites section "
        f"names `python3.12 -m venv .venv` as the setup that creates it.)"
    )

    args = list(entry["args"])
    assert args == ["-m", "verticals.mcp.server"], (
        f"the block no longer starts the shipped stdio entrypoint: {args}"
    )

    env = dict(entry["env"])
    assert env["VERTICALS_TOKEN"] == TOKEN_PLACEHOLDER, (
        f"the block no longer reads the token from the environment (AC-161: 'the block reads the "
        f"token from the environment and never inlines it'), it carries {env['VERTICALS_TOKEN']!r}"
    )
    env["VERTICALS_TOKEN"] = token

    readme_dsn = env["VERTICALS_DATABASE_URL"]
    assert readme_dsn.startswith("postgresql://"), (
        f"the block's VERTICALS_DATABASE_URL is not a libpq URL: {readme_dsn!r}"
    )
    env["VERTICALS_DATABASE_URL"] = dsn  # the one divergence; module docstring says why

    assert env["VERTICALS_OWNER"], "the block must name an owner for the transport to serve"
    return StdioServerParameters(command=command, args=args, env=env), env


# --- the fixture: F1 on an instance that has never held anything else ---------------------------


def _load_f1(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (before,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        assert before == 0, (
            f"S-118 requires a fresh instance that has never held F2 or F3; this clone already "
            f"carries {before} row(s)"
        )
        conn.execute(F1_SQL.read_text())
        conn.execute("ANALYZE goals")


def _sample_ids(dsn: str) -> set[str]:
    """F1's own row set, read from the database rather than typed — `docs/E2E.md` §2 rule 2."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT id FROM goals").fetchall()
    return {r[0] for r in rows}


# --- ports, and the proof that the UI never started ---------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _assert_ui_dark(port: int, step: str) -> None:
    assert not _listening(port), (
        f"something is listening on the UI port {port} at step {step} — the agent path must be "
        f"provable without a browser (AC-163), so steps 1-5 run with the static server down."
    )


# --- api + static server (duplicated from tests/ui/conftest.py; see module docstring) ------------


def _wait_http_ok(url: str, proc: subprocess.Popen, log_path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise RuntimeError(f"process exited early (code {proc.returncode}); tail of log:\n{tail}")
        try:
            with httpx2.Client(timeout=2.0) as probe:
                if probe.get(url).status_code == 200:
                    return
        except httpx2.HTTPError as exc:
            last_exc = exc
        time.sleep(0.1)
    raise TimeoutError(f"{url} never returned 200 within {timeout}s (last error: {last_exc})")


def _shutdown(proc: subprocess.Popen, port: int) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
    time.sleep(0.1)
    assert not _listening(port), f"port {port} still accepting connections after teardown"


@contextmanager
def _api_server(env_from_readme: dict[str, str], tmp_path: Path) -> Iterator[str]:
    """`python -m verticals.api.app`, configured from the *same* env dict the MCP block produced —
    one owner, one token, one database, exactly as a stranger who followed the README would have
    them. This is what makes step 6's HTTP read a read of the row the agent wrote."""
    port = _free_port()
    log_path = tmp_path / "api-server.log"
    env = dict(os.environ)
    env.update(env_from_readme)
    env.update(VERTICALS_BIND=f"127.0.0.1:{port}", VERTICALS_LOG_LEVEL="warning")
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, "-m", "verticals.api.app"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_http_ok(f"{base_url}/healthz", proc, log_path)
            yield base_url
        finally:
            _shutdown(proc, port)


def _build_web(token: str) -> None:
    """`npm run build` with the token baked in — `web/src/lib/api.ts` reads
    `import.meta.env.VITE_VERTICALS_TOKEN` and there is no runtime token entry, which is exactly
    what the README's own "Build the frontend" section says. Built per test rather than once per
    session (the `ui`/`uidiff` suites' pattern) because this scenario's token is generated fresh by
    the README's own command and a bundle carrying a different one would 401 every request."""
    env = dict(os.environ)
    env["VITE_VERTICALS_TOKEN"] = token
    proc = subprocess.run(
        ["npm", "--prefix", "web", "run", "build"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"npm run build failed (exit {proc.returncode}):\n{proc.stderr[-2000:]}"
    assert (WEB_DIR / "dist" / "index.html").exists(), "build reported success but dist/index.html is absent"


@contextmanager
def _static_server(api_base_url: str, port: int, tmp_path: Path) -> Iterator[str]:
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


# --- steps 2-5, over a real stdio session --------------------------------------------------------


async def _agent_session(params: StdioServerParameters, ui_port: int) -> dict[str, Any]:
    """Steps 2-5 in one live session, with the UI-port assertion re-run after each — the catalogue
    wants "the static server is never started for steps 1-5", not "was not running at the end"."""
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            _assert_ui_dark(ui_port, "3 (tools/list)")

            board = await session.call_tool("board", {"date": BOARD_DATE})
            _assert_ui_dark(ui_port, "4 (board)")

            created = await session.call_tool("create", {"title": CREATED_TITLE})
            _assert_ui_dark(ui_port, "5 (create)")

            return {
                "tool_names": {t.name for t in tools.tools},
                "board": board,
                "created": created,
            }


def _board_ids(board_structured: dict[str, Any]) -> set[str]:
    ids = {g["id"] for col in board_structured["columns"] for g in col["goals"]}
    for kids in board_structured.get("children", {}).values():
        ids |= {g["id"] for g in kids}
    return ids


# --- the scenario ---------------------------------------------------------------------------------


def test_s118_stranger_agent_configured_from_the_readme(db_dsn: str, tmp_path: Path) -> None:
    _load_f1(db_dsn)
    sample_ids = _sample_ids(db_dsn)
    assert len(sample_ids) == 6, f"F1 is the six-row sample board, this clone has {len(sample_ids)}"

    ui_port = _free_port()
    _assert_ui_dark(ui_port, "0 (before anything ran)")

    # --- steps 1-2: the README's own token pipeline, then the README's own config block ------------
    token = _token_from_readme(tmp_path)
    params, readme_env = _server_params_from_readme(token, db_dsn)
    _assert_ui_dark(ui_port, "2 (config extracted)")

    # --- steps 3-5 --------------------------------------------------------------------------------
    result = anyio.run(_agent_session, params, ui_port)

    assert result["tool_names"] == EXPECTED_TOOL_NAMES, (
        f"tools/list over the README's own configuration does not return the expected tool set: "
        f"{sorted(result['tool_names'])}"
    )

    board = result["board"]
    assert board.is_error is False, board.content[0].text if board.content else board
    board_ids = _board_ids(board.structured_content)
    assert board_ids == sample_ids, (
        f"board returned {sorted(board_ids)}, not F1's six sample rows {sorted(sample_ids)}"
    )

    created = result["created"]
    assert created.is_error is False, created.content[0].text if created.content else created
    new_goal = created.structured_content["goal"]
    new_id = new_goal["id"]
    assert new_goal["title"] == CREATED_TITLE
    assert new_id not in sample_ids, "create returned an id that already existed in F1"

    _assert_ui_dark(ui_port, "5 (after the whole agent path)")

    # --- step 6a: the row reads back over HTTP -----------------------------------------------------
    with _api_server(readme_env, tmp_path) as api_base_url:
        resp = httpx2.get(
            f"{api_base_url}/api/goals/{new_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        assert resp.status_code == 200, f"GET /api/goals/{new_id} -> {resp.status_code}: {resp.text[:400]}"
        detail = resp.json()
        assert detail["id"] == new_id and detail["title"] == CREATED_TITLE, detail

        # --- step 6b: and then in a browser --------------------------------------------------------
        _build_web(token)
        with _static_server(api_base_url, ui_port, tmp_path) as static_base_url:
            assert _listening(ui_port), "the static server did not take the UI port at step 6"
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1458, "height": 779})
                    # Console/network capture, same reason `tests/ui/conftest.py` installs it: a
                    # page that threw or 401'd renders nothing, and "the card is not there" is a
                    # useless message when the real cause is one line away in the console.
                    console: list[str] = []
                    responses: list[str] = []
                    page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"))
                    page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
                    page.on(
                        "response",
                        lambda r: responses.append(f"{r.status} {r.request.method} {r.url}")
                        if r.status >= 400
                        else None,
                    )
                    page.clock.set_fixed_time(f"{BOARD_DATE}T09:00:00+03:00")
                    page.goto(static_base_url)
                    # The agent called `create` with a title and nothing else, so the row it wrote
                    # is unverticaled — and since the owner ruling of 2026-08-09 removed the Maybe
                    # column from the board, an unverticaled goal is reached through the Inbox view
                    # rather than by scanning the seven dated columns. This is a detour to where
                    # the row now correctly lives, not a relaxation: the scenario's claim is that a
                    # stranger agent's write becomes visible to the human in a browser, and that
                    # claim is answered wherever the row legitimately renders. Same navigation the
                    # UI suite uses (`tests/ui/test_s66_schedule.py`).
                    page.click('[data-nav-item="inbox"]')
                    page.wait_for_selector('[data-cap="inbox"]', timeout=5_000)
                    card = page.locator(f'[data-cap="inbox"] [data-goal-id="{new_id}"]')
                    try:
                        card.wait_for(state="visible", timeout=15_000)
                    except Exception as exc:  # noqa: BLE001 — re-raised with the real cause attached
                        raise AssertionError(
                            f"the agent-written row {new_id} never appeared in the browser: {exc}\n"
                            f"console: {console}\nresponses >=400: {responses}"
                        ) from None
                    assert responses == [], f"the page saw >=400 response(s): {responses}"
                    assert CREATED_TITLE in card.inner_text(), (
                        f"the agent-written row rendered without its title: {card.inner_text()!r}"
                    )
                finally:
                    browser.close()
