"""S-112, S-113, S-114 — docs/E2E.md, and WP-21's own scenarios to claim (mirrors
`test_health_auth.py`'s note about S-113: WP-15 built the mechanism, WP-21 owns the assertion).
Everything shipped in `verticals/api/deps.py`, `verticals/api/app.py` and `verticals/config.py`
stays exactly as it landed — this file is the outside view: real subprocesses, real sockets,
real timing, real captured stdout/stderr, grepped after the fact. No fixture stands in for what
an assertion is actually about (E2E.md §1's house rule, same one `conftest.py` states for this
whole suite).

Three claiming tests, one per scenario id, each doing in full what `E2E.md`'s own "Steps:" list
for that id says — the naming law (`tests/harness/report.py::scenario_id_of`) makes the test
name the acceptance claim, so a test that does more or less than the catalogued steps does not
get to use the id. Everything beyond the catalogued steps — the empirical timing proof, the
401-body-length check — runs too, and still counts toward the suite's pass/fail, but under
`test_security_*` names that claim nothing (`IMPLEMENTATION.md` §4.1's WP-21 adversarial-review
row is where those two ideas come from, not S-113's own step list).
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import shutil
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.harness.report import FailDetail, artifact, fail, gate
from tests.http.conftest import REPO_ROOT, TEST_OWNER, TEST_TOKEN

DEPS_PY = REPO_ROOT / "verticals" / "api" / "deps.py"
THIS_FILE = Path(__file__).relative_to(REPO_ROOT)
_PLACEHOLDER_TOKEN = "REPLACE_ME_THIS_VALUE_NEVER_AUTHENTICATES"  # verticals/config.py's own


def _free_port() -> int:
    """Same TOCTOU-tolerant technique as `conftest.py`'s own — duplicated, not imported, on the
    same reasoning `test_availability.py` gives for doing the same: this file owns its whole
    stack independently."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# =================================================================================================
# S-113 — token refusal is real, the comparison is compare_digest, and nothing leaks
# =================================================================================================


def _assert_no_dotenv_above(path: Path) -> None:
    """`config.py::load()`'s bare `load_dotenv()` walks up from **`config.py`'s own file
    location** (python-dotenv 1.2.2's `find_dotenv()`, read from source, not assumed) — never
    from a subprocess's `cwd`, gated by no env var. This repo's real dev `.env` sits one hop
    above `verticals/config.py` with a real working token (docs/PENDING_DOC_FIXES.md row 52), so
    nothing passed as `env=` can make an unset `VERTICALS_TOKEN` stay unset unless the copy below
    is verified clear of `.env` first — a fix nobody checks is a hope, not a guarantee.
    `gate()`, not `assert`: an environment precondition failing here is not the same defect as
    the scenario itself failing, and the caller needs to tell the two apart."""
    for ancestor in (path, *path.parents):
        if (ancestor / ".env").exists():
            gate(
                f"a .env exists at {ancestor / '.env'} — the unset-token isolation this test "
                f"needs does not hold on this machine"
            )
        if ancestor == REPO_ROOT.parent:
            break


def _isolated_verticals_copy(tmp_path: Path) -> Path:
    """A private copy of `verticals/` under `tmp_path`, so `find_dotenv()`'s upward walk from the
    copy's `config.py` terminates before it ever reaches this repo's real `.env`. Read-only
    against the real tree (copies *from* it, never writes back) — safe under any concurrency,
    unlike moving the shared file itself (raised, and correctly refused: a `.env` rename is a
    mutation of shared, real-secret state on a box four agents are using right now, and a
    `finally` block is not a guarantee against SIGKILL, an OOM, or a timeout leaving it moved)."""
    pkg_root = tmp_path / "isolated"
    shutil.copytree(
        REPO_ROOT / "verticals",
        pkg_root / "verticals",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _assert_no_dotenv_above(pkg_root)
    return pkg_root


def _boot_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL="postgresql://verticals:verticals@127.0.0.1:55432/verticals",
        VERTICALS_BIND=f"127.0.0.1:{_free_port()}",
    )
    env.update(overrides)
    return env


def _boot_refused(cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """One boot attempt, entrypoint bypassed (`python -m verticals.api.app` directly, AC-081's
    own wording) — never `uvicorn.run(...)` or the container script."""
    port = int(env["VERTICALS_BIND"].rsplit(":", 1)[1])
    result = subprocess.run(
        [sys.executable, "-m", "verticals.api.app"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1, (
        f"expected boot refusal (exit 1), got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "VERTICALS_TOKEN" in result.stderr, f"variable not named in stderr: {result.stderr!r}"
    assert not _port_is_open(port), "boot-refusal path must never open a socket"
    return result


def test_s113_token_refusal_is_real_compare_digest_and_nothing_leaks(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """E2E.md's own five steps, in order: (1) unset, (2) empty, (3) placeholder, (4) static-read
    `deps.py`, (5) grep the three captured runs. Steps 2 and 3 run directly against the real
    repo tree, exactly like the two non-claiming tests already in `test_health_auth.py` (this
    scenario's underlying behaviour, built by WP-15 under non-claiming names on purpose — see
    that file's own docstring) — `load_dotenv(override=False)` never overwrites a key already
    present in `os.environ`, even an empty one, so a real `.env` on disk cannot rewrite what
    those two subprocesses see. Step 1 is the one case that needs the isolated copy."""
    artifacts_dir = REPO_ROOT / "artifacts" / "http" / "S-113"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # --- step 1: unset, entrypoint bypassed, isolated from the real repo .env -------------------
    pkg_root = _isolated_verticals_copy(tmp_path)
    env_unset = _boot_env()
    env_unset.pop("VERTICALS_TOKEN", None)
    r_unset = _boot_refused(pkg_root, env_unset)

    # --- step 2: empty, explicitly set (never omitted — omitting it on the real repo tree would
    # let that real .env fill in a working token, testing "unset" a second time under the wrong
    # name; test_health_auth.py's own test_app_boot_refuses_empty_token docstring makes the same
    # point) ---------------------------------------------------------------------------------
    r_empty = _boot_refused(REPO_ROOT, _boot_env(VERTICALS_TOKEN=""))

    # --- step 3: the literal .env.example placeholder --------------------------------------------
    r_placeholder = _boot_refused(REPO_ROOT, _boot_env(VERTICALS_TOKEN=_PLACEHOLDER_TOKEN))

    # --- step 4: static-read deps.py -------------------------------------------------------------
    deps_src = DEPS_PY.read_text()
    m = re.search(r"def verify_bearer_token\b.*?(?=\ndef |\Z)", deps_src, re.DOTALL)
    if m is None:
        fail(
            FailDetail(
                scenario_id="S-113",
                suite="http",
                name="token_refusal_is_real_compare_digest_and_nothing_leaks",
                file=str(DEPS_PY),
                assert_expr="verify_bearer_token is defined in deps.py",
                expected="a matching function definition",
                actual="none found",
                detail="deps.py no longer defines verify_bearer_token under that name",
            )
        )
    body = m.group(0)
    if "hmac.compare_digest(" not in body:
        fail(
            FailDetail(
                scenario_id="S-113",
                suite="http",
                name="token_refusal_is_real_compare_digest_and_nothing_leaks",
                file=str(DEPS_PY),
                assert_expr='"hmac.compare_digest(" in verify_bearer_token source',
                expected="present",
                actual="absent",
                detail=f"verify_bearer_token body:\n{body}",
            )
        )
    # A composite bypass ("presented == expected or hmac.compare_digest(...)") would still match
    # the check above; refuse any bare equality against the two variable names this function
    # actually uses for the token, on ANY line — including one that also calls compare_digest,
    # which is exactly the shape a composite bypass takes. (An earlier version of this check
    # skipped any line containing the substring "compare_digest" and so blanket-exempted that
    # exact composite line; falsifying this rule against a planted `presented == expected or
    # hmac.compare_digest(...)` caught the gap before this file shipped. `compare_digest(...)`
    # itself is a call, not an equality — it contains no `==` — so no exemption is needed for it
    # to pass cleanly on its own line.)
    for line in body.splitlines():
        if re.search(r"\bpresented\s*==|==\s*expected\b", line):
            fail(
                FailDetail(
                    scenario_id="S-113",
                    suite="http",
                    name="token_refusal_is_real_compare_digest_and_nothing_leaks",
                    file=str(DEPS_PY),
                    assert_expr="no bare == between presented/expected outside compare_digest",
                    expected="0 matches",
                    actual=f"matched line: {line.strip()!r}",
                    detail="a second, unsafe comparison path alongside compare_digest",
                )
            )

    # --- step 5: grep the three captured runs, persisted as artifacts ----------------------------
    logs = {
        "unset": (r_unset, artifacts_dir / "boot_unset.log"),
        "empty": (r_empty, artifacts_dir / "boot_empty.log"),
        "placeholder": (r_placeholder, artifacts_dir / "boot_placeholder.log"),
    }
    _success_markers = ('"status":"ok"', '"status": "ok"', '"queries"', "Application startup complete")
    for variant, (result, path) in logs.items():
        combined = f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
        path.write_text(combined)
        artifact(request, str(path.relative_to(REPO_ROOT)))
        assert "VERTICALS_TOKEN" in combined, f"{variant}: variable not named anywhere in the run"
        for marker in _success_markers:
            assert marker not in combined, (
                f"{variant}: found {marker!r} in captured output — this run must never look live"
            )
        assert "Traceback" not in combined, f"{variant}: a traceback reached the captured output"


# =================================================================================================
# S-112 — the server opens no socket it was not configured to open
# =================================================================================================

_NESTED_ENV = "_VERTICALS_S112_NESTED_RUN"


def _ps_table() -> dict[int, int]:
    """`pid -> ppid` for every process this user can see. Plain BSD `ps`, no `sudo`."""
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=False
    ).stdout
    table: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            table[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return table


def _descendants(root_pid: int, ppid_of: dict[int, int]) -> set[int]:
    """Every descendant of `root_pid`, root included — the process-tree scope that keeps this
    sampler from ever looking at some *other* agent's concurrently-running server on the same
    box, which four agents are sharing right now."""
    children: dict[int, list[int]] = {}
    for pid, ppid in ppid_of.items():
        children.setdefault(ppid, []).append(pid)
    seen: set[int] = set()
    frontier = [root_pid]
    while frontier:
        pid = frontier.pop()
        if pid in seen:
            continue
        seen.add(pid)
        frontier.extend(children.get(pid, ()))
    return seen


def _lsof_pcn(pid_csv: str, extra: list[str]) -> list[tuple[int, str]]:
    """`(pid, socket-name)` pairs from `lsof -F pcn`. Checked by hand against this exact
    machine's lsof before relying on it: a pid list mixing a live process with an already-exited
    one still returns real rows for the live one, under a *nonzero* exit code — exit status is
    never treated as "no results", only stdout content is."""
    result = subprocess.run(
        ["lsof", "-a", "-p", pid_csv, *extra, "-n", "-P", "-F", "pcn"],
        capture_output=True,
        text=True,
        check=False,
    )
    pid: int | None = None
    out: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            try:
                pid = int(val)
            except ValueError:
                pid = None
        elif tag == "n" and pid is not None:
            out.append((pid, val))
    return out


def test_s112_server_opens_no_socket_it_was_not_configured_to_open(
    request: pytest.FixtureRequest,
) -> None:
    """"Run the entire http suite with a sampler..." — literally: spawns a fresh, separate
    `pytest tests/http` subprocess (every sibling, including this file — the nested copy of this
    same test sees `_NESTED_ENV` and returns immediately, which is what stops real recursion) and
    samples `lsof` against its whole process tree every 250ms for as long as it runs. Not routed
    through `tests.harness.runner` — a second, nested copy of that plugin would overwrite
    `artifacts/results.jsonl` mid-run; this test only needs the nested run's exit code and log
    tail, which plain pytest already gives it.

    "The API's own port" is read from `lsof`'s own LISTEN report per pid, not guessed from
    `VERTICALS_BIND` — holds for every server the run boots, including `server_factory`'s
    fresh ephemeral port each call. "The configured PGHOST:PGPORT" comes from this process's own
    environment, `tests/conftest.py`'s own defaults. S-45's private cluster never shows up here
    at all — it binds `-h ''` (`test_availability.py`'s own docstring) and is reached over a unix
    socket, invisible to `-iTCP`/`-iUDP` — so "the same holds during S-45's outage window" is
    true by construction, not a special case this test has to add.
    """
    if os.environ.get(_NESTED_ENV):
        return

    pg_port = os.environ.get("PGPORT", "55432")

    artifacts_dir = REPO_ROOT / "artifacts" / "http" / "S-112"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / "nested_suite_run.log"

    env = dict(os.environ)
    env[_NESTED_ENV] = "1"
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", "tests/http", "-q", "-n", "auto"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )

    samples: list[tuple[int, str, str]] = []  # (pid, "est" | "listen" | "udp", socket-name)
    try:
        while proc.poll() is None:
            table = _ps_table()
            pids = _descendants(proc.pid, table)
            pids.discard(0)
            if pids:
                pid_csv = ",".join(str(p) for p in pids)
                samples += [
                    (pid, "est", name)
                    for pid, name in _lsof_pcn(pid_csv, ["-iTCP", "-sTCP:ESTABLISHED"])
                ]
                samples += [
                    (pid, "listen", name)
                    for pid, name in _lsof_pcn(pid_csv, ["-iTCP", "-sTCP:LISTEN"])
                ]
                samples += [(pid, "udp", name) for pid, name in _lsof_pcn(pid_csv, ["-iUDP"])]
            time.sleep(0.25)
    finally:
        proc.wait(timeout=60)

    artifact(request, str(log_path.relative_to(REPO_ROOT)))
    nested_log = log_path.read_text()

    if proc.returncode not in (0, 1):
        gate(
            f"nested http-suite run exited {proc.returncode} (expected 0 or 1) — sampling "
            f"cannot be trusted as a full-suite observation; tail:\n{nested_log[-2000:]}"
        )
    if proc.returncode == 1:
        fail(
            FailDetail(
                scenario_id="S-112",
                suite="http",
                name="server_opens_no_socket_it_was_not_configured_to_open",
                file=str(log_path.relative_to(REPO_ROOT)),
                assert_expr="nested `pytest tests/http` returncode == 0",
                expected="0",
                actual="1",
                detail=(
                    "a scenario failed inside the sampled run — the socket observation this "
                    f"test makes is only trustworthy against a clean pass; log tail:\n"
                    f"{nested_log[-2000:]}"
                ),
            )
        )

    # --- pass 1: which pids are servers, and what is each one's own listen port -----------------
    listen_ports: dict[int, set[int]] = {}
    for pid, kind, name in samples:
        if kind != "listen":
            continue
        _, _, port_s = name.rpartition(":")
        if port_s.isdigit():
            listen_ports.setdefault(pid, set()).add(int(port_s))

    multi_listen = {pid: ports for pid, ports in listen_ports.items() if len(ports) > 1}
    udp_hits = sorted({(pid, name) for pid, kind, name in samples if kind == "udp"})

    # --- pass 2: every established connection on a server pid is either inbound (local port ==
    # that pid's own listen port) or a genuine outbound socket, which must land on PGHOST:PGPORT
    violations: list[str] = []
    for pid, kind, name in samples:
        if kind != "est":
            continue
        own_ports = listen_ports.get(pid)
        if not own_ports:
            continue  # not a server pid (never observed listening) — out of this scenario's scope
        local, sep, remote = name.partition("->")
        if not sep:
            continue  # defensive: -sTCP:ESTABLISHED should always carry an arrow
        _, _, local_port_s = local.rpartition(":")
        remote_host, _, remote_port = remote.rpartition(":")
        if local_port_s.isdigit() and int(local_port_s) in own_ports:
            continue  # inbound: a client of this pid's own listen socket
        if remote_host not in ("127.0.0.1", "::1") or remote_port != pg_port:
            violations.append(f"pid={pid} {name} (own listen ports: {sorted(own_ports)})")

    detail_lines = []
    if violations:
        detail_lines.append(f"{len(violations)} outbound connection(s) not to PGHOST:PGPORT:")
        detail_lines.extend(sorted(set(violations)))
    if multi_listen:
        detail_lines.append(f"pid(s) with more than one listening port: {multi_listen}")
    if udp_hits:
        detail_lines.append(f"UDP socket(s) observed (proxy for a DNS lookup): {udp_hits}")

    if detail_lines:
        fail(
            FailDetail(
                scenario_id="S-112",
                suite="http",
                name="server_opens_no_socket_it_was_not_configured_to_open",
                file=str(log_path.relative_to(REPO_ROOT)),
                assert_expr="every outbound socket -> PGHOST:PGPORT; 1 listen port per server; 0 UDP",
                expected="no violations",
                actual=f"{len(detail_lines)} finding group(s)",
                detail="\n".join(detail_lines),
                artifact=str(log_path.relative_to(REPO_ROOT)),
            )
        )

    assert listen_ports, "sampler observed zero server processes — the nested run may not have booted one"


# =================================================================================================
# S-114 — CORS is closed, and the app does not need it open
# =================================================================================================

_CORS_HEADERS = (
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-allow-methods",
    "access-control-allow-headers",
)


def test_s114_cross_origin_preflight_and_requests_are_refused(server) -> None:
    """The four requests E2E.md's Steps list names, no more: `GET /api/board` and
    `POST /api/goals` carrying a foreign `Origin` (no token — the two 4xx cases), one preflight
    `OPTIONS /api/goals` with `Access-Control-Request-Method: POST`, and one `GET /api/board`
    with both a valid token and the foreign origin (the 200 case — proves it is the origin policy
    refusing a browser, not an auth accident). No separate 500 case: `app.py` registers no
    `CORSMiddleware` at all (verified against the file), so Starlette never emits an
    `Access-Control-Allow-*` header on *any* response regardless of status — a structural
    guarantee, not something that needs re-proving per status code, so the 200/4xx spread these
    four requests already produce is sufficient.
    """
    evil = "https://evil.example"
    raw = httpx.Client(base_url=server.base_url, timeout=10.0)
    try:
        responses = [
            ("GET /api/board, foreign origin, no token", raw.get(
                "/api/board", params={"date": "2026-08-08"}, headers={"Origin": evil}
            )),
            ("POST /api/goals, foreign origin, no token", raw.post(
                "/api/goals", json={"title": "cors probe"}, headers={"Origin": evil}
            )),
            ("OPTIONS preflight /api/goals, foreign origin", raw.options(
                "/api/goals",
                headers={"Origin": evil, "Access-Control-Request-Method": "POST"},
            )),
            ("GET /api/board, foreign origin, valid token", raw.get(
                "/api/board",
                params={"date": "2026-08-08"},
                headers={"Origin": evil, "Authorization": f"Bearer {server.token}"},
            )),
        ]
    finally:
        raw.close()

    leaks = [
        f"{label}: {h}={resp.headers[h]!r} (status {resp.status_code})"
        for label, resp in responses
        for h in _CORS_HEADERS
        if h in resp.headers
    ]
    if leaks:
        fail(
            FailDetail(
                scenario_id="S-114",
                suite="http",
                name="cross_origin_preflight_and_requests_are_refused",
                file=str(THIS_FILE),
                assert_expr="no Access-Control-* header on any of the 4 responses",
                expected="0 headers found",
                actual=f"{len(leaks)} found",
                detail="; ".join(leaks),
            )
        )

    labels_and_expected = (
        (responses[0], (401, 422)),
        (responses[1], (401, 422)),
        (responses[2], (404, 405)),
    )
    for (label, resp), expected_codes in labels_and_expected:
        assert resp.status_code in expected_codes, f"{label}: got {resp.status_code}"
    assert responses[3][1].status_code == 200, f"{responses[3][0]}: got {responses[3][1].status_code}"
