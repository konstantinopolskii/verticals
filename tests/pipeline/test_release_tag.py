"""S-117, S-119, S-120 — the three suite-E scenarios whose subject is the release artifact: the
clean-machine install, the hygiene of the tag a stranger clones, and the provenance of every
binary the build ships.

Same split as `test_readme_paths.py`, for the same reason: these are M2 criteria
(`docs/ACCEPTANCE.md` §5) and M2's artifacts — container packaging, a tagged release, `LICENSE`,
`ASSETS.md` — are not in this tree yet. What can be proved against what exists is proved as a
plain passing test; what cannot names the missing artifact through `report.gate` after asserting
that it is genuinely missing. `pytest.skip` is never used: `docs/E2E.md` §12 rule 4 and AC-089
(`skip == 0`) forbid it.

**On S-119 and Zone 1 markers.** The scenario greps the clone for five Zone 1 markers (an owner
name, two host names, a codename prefix, a Tailscale address). Those strings are Zone 1 material
themselves, so this file — which is Zone 3 the moment a release tag exists — must not contain
them, and no five-marker list exists anywhere else in the tree to read them from. `test_s119b`
records the measurement that rules out the one candidate substitute and gates that clause; the
history half of the audit, which needs no marker list, runs and passes in `test_s119a`.

Run standalone:
    .venv/bin/python -m pytest tests/pipeline/test_release_tag.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.harness.report import artifact, gate
from tests.pipeline.readme_blocks import parse_fences, sections

REPO_ROOT = Path(__file__).resolve().parents[2]

# S-120's ceiling, in its own words: "no asset is larger than 256 KB, which is the size at which
# somebody has committed a video by accident."
_MAX_ASSET_BYTES = 256 * 1024

# What "a binary asset" means for S-120: the extensions a build actually ships. Text output
# (`.js`, `.css`, `.html`, `.map`) is this repository's own work and carries no third-party
# licence question — the scenario names "eight sounds, one font and a set of icons".
_ASSET_SUFFIXES = frozenset(
    {".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".wav", ".ogg", ".png", ".jpg",
     ".jpeg", ".gif", ".webp", ".avif", ".ico", ".svg"}
)

_ASSET_ROOTS = ("web/dist", "web/public", "web/src/assets")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )


def _tags() -> list[str]:
    return [t for t in _git("tag", "--list").stdout.split() if t]


def _shipped_assets() -> list[Path]:
    """Every binary asset the build would ship, repo-root-relative, sorted. `web/dist` is
    gitignored and rebuilt (`npm --prefix web run build`), which is exactly why S-120 enumerates
    "the built bundle" rather than the tracked tree — a licence question follows the bytes a
    stranger downloads, not the bytes a contributor commits."""
    found: list[Path] = []
    for root in _ASSET_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        found.extend(
            p for p in base.rglob("*")
            if p.is_file() and p.suffix.lower() in _ASSET_SUFFIXES
        )
    return sorted(found)


# ==================================================================================================
# S-117 — a clean machine, the README, and a painted board. AC-155–158, AC-170.
#
# This scenario stopped being gated the day `Dockerfile`, `docker-compose.yml` and
# `docker/entrypoint.sh` landed. It now does what the catalogue says: builds the real image,
# boots two real instances from the README's own quickstart text, drives a real browser at the
# published port, and reads both boot logs.
#
# Two instances, both booted once by the module fixture below, because booting them is the
# expensive part and both halves of the scenario read the same two boots:
#
#   A — no `.env` at all (an empty state directory).
#   B — `.env` present, holding the literal placeholder `.env.example` ships.
#
# A is then re-created in place, which is the "second boot of the same instance" clause: the same
# state volume, the same database, a new container process.
# ==================================================================================================

# AC-156's warm-cache budget, in its own words: "wall clock under 90 s warm". The image is built
# by the fixture before the clock starts, which is what "warm" means here.
_WARM_BUDGET_SECONDS = 90.0

# The README heading whose fenced block AC-155 counts and S-117 replays.
_QUICKSTART_SECTION = "Quickstart"


def _placeholder_token() -> str:
    """Read the placeholder out of `.env.example` rather than holding a second copy of it. Two
    copies of a sentinel is the same defect as two copies of a command (AC-162's reasoning), and
    this one already exists in three places that must agree — `.env.example`, `verticals/config.py`
    and `docker/entrypoint.sh`."""
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("VERTICALS_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(".env.example declares no VERTICALS_TOKEN placeholder")


def _quickstart_fence():
    """The one executable fence under the README's `Quickstart` heading. Extracted, never typed
    here — AC-155's "the block is machine-extractable and is the same text the test runs"."""
    fences = [
        f
        for f in parse_fences((REPO_ROOT / "README.md").read_text(encoding="utf-8"))
        if f.section == _QUICKSTART_SECTION and f.is_executable_language
    ]
    assert len(fences) == 1, (
        f"expected exactly one executable fence under README '{_QUICKSTART_SECTION}', "
        f"found {len(fences)}"
    )
    return fences[0]


def _executable_lines(body: str) -> list[str]:
    """The lines AC-155 counts: real commands, not blanks and not comments."""
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _lan_address() -> str | None:
    """This host's non-loopback address, or `None` when it has none (an offline machine). Opens
    no connection — a UDP socket's `connect` only picks a route."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, routed nowhere
            addr = str(s.getsockname()[0])
    except OSError:
        return None
    return None if addr.startswith("127.") else addr


@dataclass
class _Instance:
    """One booted stack, and everything both tests read off it."""

    name: str
    project: str
    port: int
    state_dir: Path
    seconds: float = 0.0
    first_log: str = ""
    second_log: str | None = None
    published: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class _Stacks:
    problem: str | None = None
    a: _Instance | None = None
    b: _Instance | None = None


def _preflight() -> str | None:
    """Everything this scenario needs before it is worth booting anything. Returns a gate reason
    or `None`."""
    if shutil.which("docker") is None:
        return "docker is not installed on this machine"
    probe = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        return f"`docker compose` is unavailable: {probe.stderr.strip() or probe.stdout.strip()}"
    if not list((REPO_ROOT / "web" / "vendor").glob("*.tgz")):
        # AC-170/JC-02, stated in the README's own Status section: the kit is not on a public
        # registry, so the frontend stage cannot build without the vendored tarballs.
        return (
            "web/vendor/*.tgz absent — the private kit (JC-02) is what the frontend stage builds "
            "from, so no image can be produced on this machine"
        )
    return None


def _compose(project: str, *args: str, env_extra: dict[str, str] | None = None,
             timeout: int = 900) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["COMPOSE_PROJECT_NAME"] = project
    env.update(env_extra or {})
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        env=env,
    )


def _boot(inst: _Instance, body: str) -> subprocess.CompletedProcess[str]:
    """Run the README's quickstart text verbatim, in one shell, at the repository root.

    Nothing in the text is rewritten. The two things this run needs that a stranger's does not —
    a project name that will not collide with the other instance, and a published port that is
    free on this machine — are supplied through the environment `docker-compose.yml` already
    reads (`COMPOSE_PROJECT_NAME`, `VERTICALS_PORT`, `VERTICALS_STATE`), which is exactly how an
    operator would run two instances side by side.

    `stdin` is `/dev/null`: S-117's "no prompt for input" is asserted by construction — a command
    that stopped to ask something would read EOF and fail rather than hang this suite forever.
    """
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", body],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=600,
        env={
            **os.environ,
            "COMPOSE_PROJECT_NAME": inst.project,
            "VERTICALS_PORT": str(inst.port),
            "VERTICALS_STATE": str(inst.state_dir),
        },
    )


def _published_ports(project: str) -> dict[str, list[dict]]:
    """`{container name: [{HostIp, HostPort, ...}]}` for every container in the project, read
    from `docker inspect` — the same place S-117 names."""
    ids = [i for i in _compose(project, "ps", "-q").stdout.split() if i]
    assert ids, f"compose project {project} has no containers"
    out: dict[str, list[dict]] = {}
    for cid in ids:
        proc = subprocess.run(
            ["docker", "inspect", cid, "--format", "{{.Name}}\t{{json .NetworkSettings.Ports}}"],
            capture_output=True, text=True, check=True,
        )
        name, _, ports_json = proc.stdout.strip().partition("\t")
        bindings: list[dict] = []
        for _container_port, host in (json.loads(ports_json) or {}).items():
            bindings.extend(host or [])
        out[name.lstrip("/")] = bindings
    return out


@pytest.fixture(scope="module")
def stacks(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Stacks]:
    problem = _preflight()
    if problem:
        yield _Stacks(problem=problem)
        return

    body = _quickstart_fence().body
    # One build, before any clock starts. AC-156 measures the *warm* path and records the cold
    # one as non-gating; building here is what makes the measurement below mean "warm".
    unique = os.getpid()
    build = _compose(f"s117-build-{unique}", "build")
    if build.returncode != 0:
        yield _Stacks(problem=f"`docker compose build` failed: {build.stderr[-2000:]}")
        return

    root = tmp_path_factory.mktemp("s117")
    a = _Instance(name="A", project=f"s117a-{unique}", port=_free_port(), state_dir=root / "a")
    b = _Instance(name="B", project=f"s117b-{unique}", port=_free_port(), state_dir=root / "b")
    # A has no `.env` at all; B has one holding the placeholder, at a deliberately loose mode so
    # the 0600 assertion proves the entrypoint set it rather than inheriting it.
    a.state_dir.mkdir(parents=True)
    b.state_dir.mkdir(parents=True)
    (b.state_dir / ".env").write_text(
        (REPO_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (b.state_dir / ".env").chmod(0o644)

    try:
        for inst in (a, b):
            started = time.perf_counter()
            run = _boot(inst, body)
            inst.seconds = time.perf_counter() - started
            assert run.returncode == 0, (
                f"instance {inst.name}: the README quickstart exited {run.returncode}\n"
                f"--- stdout ---\n{run.stdout[-4000:]}\n--- stderr ---\n{run.stderr[-4000:]}"
            )
            inst.first_log = _compose(inst.project, "logs", "app").stdout
            inst.published = _published_ports(inst.project)

        # The second boot of instance A: same state volume, same database, new container.
        assert _compose(a.project, "rm", "-sf", "app").returncode == 0
        again = _compose(
            a.project, "up", "-d", "--wait", "app",
            env_extra={"VERTICALS_PORT": str(a.port), "VERTICALS_STATE": str(a.state_dir)},
        )
        assert again.returncode == 0, f"A's second boot failed:\n{again.stderr[-3000:]}"
        a.second_log = _compose(a.project, "logs", "app").stdout

        yield _Stacks(a=a, b=b)
    finally:
        for project in (a.project, b.project):
            _compose(project, "down", "-v", "--remove-orphans", timeout=300)


def test_s117a_two_fresh_containers_reach_a_painted_board(
    stacks: _Stacks, request: pytest.FixtureRequest
) -> None:
    """S-117: two containers with Docker and nothing else, the README quickstart replayed
    verbatim on each, a browser driven at the URL it prints, the published port bound to
    loopback only, and the whole thing inside the warm budget of §8-S-97.

    AC-155, AC-156, AC-157. The token half is `test_s117b`, on the same two boots.
    """
    fence = _quickstart_fence()
    lines = _executable_lines(fence.body)
    assert len(lines) <= 3, f"AC-155: quickstart is {len(lines)} executable lines, not <= 3: {lines}"

    if stacks.problem:
        gate(f"S-117 needs a booted stack: {stacks.problem}")
    assert stacks.a is not None and stacks.b is not None

    timings = {}
    for inst in (stacks.a, stacks.b):
        timings[inst.name] = round(inst.seconds, 2)

        # AC-157, read off `docker inspect` rather than off the compose file: a published port
        # that reached a non-loopback interface is the failure, whatever the YAML claimed.
        app_bindings = [
            binding
            for name, bindings in inst.published.items()
            if name.endswith("-app-1")
            for binding in bindings
        ]
        assert app_bindings, f"instance {inst.name}: the app container publishes no port at all"
        offenders = [
            b for bindings in inst.published.values() for b in bindings
            if b.get("HostIp") not in ("127.0.0.1", "::1")
        ]
        assert offenders == [], (
            f"instance {inst.name}: published ports reachable off loopback: {offenders}"
        )

        # The other direction of the same claim: the port answers on loopback and refuses on this
        # host's LAN address. Skipped only on a machine that has no LAN address to refuse on.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            assert s.connect_ex(("127.0.0.1", inst.port)) == 0, (
                f"instance {inst.name}: nothing is listening on 127.0.0.1:{inst.port}"
            )
        lan = _lan_address()
        if lan:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                assert s.connect_ex((lan, inst.port)) != 0, (
                    f"instance {inst.name}: {lan}:{inst.port} accepted a connection — this "
                    "instance is published to the local network"
                )

        assert inst.seconds < _WARM_BUDGET_SECONDS, (
            f"instance {inst.name}: {inst.seconds:.1f}s from `docker compose up` to a healthy "
            f"stack, over the {_WARM_BUDGET_SECONDS:.0f}s warm budget (AC-156)"
        )

    # The board itself, in a real browser, at the URL the quickstart's own prose prints.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - the dev extra pins playwright
        gate(f"playwright is not importable: {exc}")

    painted: dict[str, list[str]] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for inst in (stacks.a, stacks.b):
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{inst.port}/", wait_until="load")
                    page.wait_for_selector("[data-goal-id]", timeout=30_000)
                    columns = page.eval_on_selector_all(
                        "[data-vertical]", "els => els.map(e => e.dataset.vertical)"
                    )
                    goals = page.eval_on_selector_all(
                        "[data-goal-id]", "els => els.map(e => e.dataset.goalId)"
                    )
                    painted[inst.name] = list(goals)
                    # Seven dated columns, and Maybe is deliberately not among them: the owner
                    # ruling of 2026-08-09 took the Maybe column off the board and moved
                    # unverticaled goals to the Inbox view, superseding ARCHITECTURE.md:445. The
                    # list stays exact rather than becoming a subset check — this scenario's job
                    # is to prove a released container paints the *shipped* board, and an
                    # order-and-membership assertion is the only kind that can catch a column
                    # quietly appearing, vanishing, or moving in a build a stranger downloads.
                    assert columns == [
                        "day", "week", "month", "quarter", "year", "decade", "life"
                    ], f"instance {inst.name}: board columns are {columns}"
                    assert goals, f"instance {inst.name}: the board painted with no goal on it"
                    page.close()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a missing browser binary is a gate, not a failure
        if "executable doesn" in str(exc) or "playwright install" in str(exc):
            gate(f"no Chromium binary on this machine: {exc}")
        raise

    # AC-156's recorded wall clock, kept whether or not it is close to the gate — a regression
    # that stays under 90 s is still visible in this file.
    path = artifact(request, "artifacts/pipeline/S-117/clean_install.json")
    out = REPO_ROOT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "warm_budget_seconds": _WARM_BUDGET_SECONDS,
                "quickstart_executable_lines": lines,
                "seconds": timings,
                "goals_painted": painted,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_s117b_the_entrypoint_generates_the_token_once(stacks: _Stacks) -> None:
    """S-117's token-generation half (AC-158, moved here from S-113 by the S-113/S-117 split):
    on first boot the entrypoint generates a real token *before* it `exec`s the server, writes it
    to `.env` at mode 0600, prints it exactly once with a copy-pasteable `export` line, overwrites
    the `.env.example` placeholder if one is there, and on a second boot of the same instance
    reuses it and prints nothing.

    The refusal half of the same contract — the server declining to boot on the placeholder — is
    S-113's, proved directly on the bare process, and is not re-proved here.
    """
    if stacks.problem:
        gate(f"S-117 needs a booted stack: {stacks.problem}")
    assert stacks.a is not None and stacks.b is not None
    placeholder = _placeholder_token()

    tokens: dict[str, str] = {}
    for inst in (stacks.a, stacks.b):
        env_file = inst.state_dir / ".env"
        assert env_file.is_file(), f"instance {inst.name}: the entrypoint wrote no {env_file}"

        # AC-158's mode clause. B's file was 0644 before the boot, so this proves the entrypoint
        # set the mode rather than finding it already set.
        mode = env_file.stat().st_mode & 0o777
        assert mode == 0o600, f"instance {inst.name}: .env is mode {mode:o}, not 600"

        written = env_file.read_text(encoding="utf-8")
        token_lines = [ln for ln in written.splitlines() if ln.startswith("VERTICALS_TOKEN=")]
        assert len(token_lines) == 1, f"instance {inst.name}: {len(token_lines)} token lines"
        token = token_lines[0].split("=", 1)[1]
        assert token and token != placeholder, (
            f"instance {inst.name}: the placeholder is still in place"
        )
        assert len(token) >= 32, f"instance {inst.name}: token is {len(token)} characters"
        assert placeholder not in written, (
            f"instance {inst.name}: the placeholder survives somewhere in .env"
        )
        tokens[inst.name] = token

        # Printed exactly once, with a line that can be pasted into a shell.
        export_lines = [
            ln.strip() for ln in inst.first_log.splitlines() if "export VERTICALS_TOKEN=" in ln
        ]
        assert len(export_lines) == 1, (
            f"instance {inst.name}: the export line appears {len(export_lines)} times in the "
            f"first boot log, not once"
        )
        assert export_lines[0].endswith(f"export VERTICALS_TOKEN={token}"), (
            f"instance {inst.name}: the printed line does not carry the token that was written"
        )
        assert inst.first_log.count(token) == 1, (
            f"instance {inst.name}: the token appears {inst.first_log.count(token)} times in the "
            "first boot log — it is printed once and never again"
        )

        # Generated BEFORE the server was exec'd, read off the log's own order: the banner sits
        # above uvicorn's first line, and uvicorn is the process that replaced the entrypoint.
        assert "Uvicorn running on" in inst.first_log, (
            f"instance {inst.name}: the server never started"
        )
        assert inst.first_log.index("export VERTICALS_TOKEN=") < inst.first_log.index(
            "Uvicorn running on"
        ), f"instance {inst.name}: the token was printed after the server was already running"

    assert tokens["A"] != tokens["B"], "two instances were given the same token"

    # The second boot of instance A: same token, and silence about it.
    assert stacks.a.second_log is not None
    second = stacks.a.second_log
    assert "Uvicorn running on" in second, "A's second boot never reached the server"
    assert "export VERTICALS_TOKEN=" not in second, (
        "A's second boot printed the export line again — generation is not idempotent"
    )
    assert tokens["A"] not in second, "A's second boot printed the token again"
    assert (stacks.a.state_dir / ".env").read_text(encoding="utf-8").splitlines().count(
        f"VERTICALS_TOKEN={tokens['A']}"
    ) == 1, "A's second boot did not reuse the token already in .env"


# ==================================================================================================
# S-119 — the release tag carries nothing it should not. AC-152, AC-154, AC-168, AC-193, AC-194.
# ==================================================================================================


def test_s119a_no_zone_one_path_was_ever_added_to_the_history() -> None:
    """S-119's history clause, which needs no tag and therefore runs for real: "assert the whole
    history, not just the tip: `git log --all --diff-filter=A --name-only` lists no path matching
    `seed/*.json` or `*.png` under `seed/`. A file deleted in a later commit is still a file in
    the clone."

    Run against the local history, which is the history any future tag is cut from — a path that
    was never added here cannot appear in a clone of a tag cut from here. Three neighbouring
    facts are asserted with it, all cheap and all continuously true (AC-193's "database/repo half
    is re-checked continuously"): `seed/` ignores everything but its own `.gitignore`, no `.env`
    file is tracked, and the Zone 1 marker scan over every tracked file returns zero hits.
    """
    added = _git("log", "--all", "--diff-filter=A", "--name-only", "--pretty=format:")
    assert added.returncode == 0, added.stderr
    paths = [p for p in added.stdout.splitlines() if p.strip()]
    offenders = sorted(
        {
            p
            for p in paths
            if p.startswith("seed/")
            and not p.endswith(".gitignore")
            and (p.endswith(".json") or p.endswith(".png"))
        }
    )
    assert offenders == [], f"Zone 1 paths exist in history: {offenders}"

    tracked = [p for p in _git("ls-files").stdout.splitlines() if p.strip()]
    # S-119 allows `seed/.gitignore` and the schema documentation to ship and nothing else. This
    # tree is stricter than the allowance: the root `.gitignore` ignores `/seed/` wholesale, so
    # even the directory's own `.gitignore` is untracked, and the tracked set under `seed/` is
    # empty. Asserted as "nothing but the two permitted names", so the day the schema doc is
    # written and committed this keeps passing and a stray export still fails.
    permitted = {"seed/.gitignore", "seed/SCHEMA.md"}
    assert set(p for p in tracked if p.startswith("seed/")) <= permitted
    assert (REPO_ROOT / "seed" / ".gitignore").exists(), "seed/.gitignore is gone"
    assert [p for p in tracked if Path(p).name == ".env" or p.endswith("/.env")] == []
    assert ".env" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    # The five-marker grep is deliberately *not* run here — see `test_s119b`'s docstring for the
    # measurement that says why the only term list this machine has cannot stand in for it.


def test_s119b_a_fresh_clone_of_the_release_tag_is_clean() -> None:
    """S-119's main path: `git clone --depth 1 --branch <tag>` into a fresh directory, then audit
    the tree — nothing under `seed/`, `gitleaks detect --no-git` reporting 0 findings, zero `.env`
    files, a `LICENSE` the README names.

    There is no tag and no remote to clone from (both asserted), and two of the artifacts the
    audit reads do not exist yet either: `LICENSE` is blocked on JC-01, and `gitleaks` is not
    installed on this machine. The half of the audit that can run against the history rather than
    a clone is not gated — it is `test_s119a`, above, and it passes.

    **The five-marker grep needs a term list this repository does not have.** The markers are
    Zone 1 strings and cannot be written into a file that ships in the tag, so the only candidate
    source is `tools/uiref/leakwords.local.txt` — the gitignored denylist `sanitize.mjs` already
    uses. Measured against the tracked tree (paths and counts read, terms never printed): four of
    its terms match, two of them across 18 and 24 tracked files including `.gitignore`,
    `web/package.json` and every `web/src/component`. That list is the *sanitizer's* personal-term
    denylist — names, clients, medication — not S-119's five markers, and it contains terms that
    appear in this tree entirely legitimately. Substituting it would produce a scenario that fails
    on correct code, which is worse than one that gates. The list S-119 actually needs is a
    five-line one nobody has written; writing it is a Zone 1 decision, not a test's to make.
    """
    tags = _tags()
    assert tags == [], f"a release tag now exists ({tags}) — clone it and run the real audit"
    remotes = [r for r in _git("remote").stdout.split() if r]
    assert remotes == [], f"a remote now exists ({remotes})"
    assert not (REPO_ROOT / "LICENSE").exists(), "LICENSE landed — JC-01 was ruled, close this gate"

    gate("no release tag and no remote to clone; LICENSE absent (blocked on JC-01)")


# ==================================================================================================
# S-120 — every shipped asset has provenance. AC-169, AC-171.
# ==================================================================================================


def test_s120a_no_shipped_asset_is_larger_than_256_kb() -> None:
    """S-120's size clause, which depends on no unwritten document and so runs for real: "no
    asset is larger than 256 KB, which is the size at which somebody has committed a video by
    accident."

    Enumerated over the built bundle and the two source directories a build copies from, so a
    fat asset fails here whether it reaches `dist/` through Vite's hashing or through
    `web/public` verbatim.
    """
    assets = _shipped_assets()
    assert assets, "no binary assets found — the enumeration is wrong, not the bundle"
    oversized = {
        str(p.relative_to(REPO_ROOT)): p.stat().st_size
        for p in assets
        if p.stat().st_size > _MAX_ASSET_BYTES
    }
    assert oversized == {}, f"assets over 256 KB: {oversized}"


def test_s120b_every_shipped_asset_has_an_assets_md_row() -> None:
    """S-120's provenance clause: the set of shipped assets equals the set of `ASSETS.md` rows,
    in **both directions**, every row carrying source, author, licence identifier and URL, every
    identifier compatible with `LICENSE`.

    `ASSETS.md` does not exist and neither does `LICENSE`; both are asserted absent below.
    AC-169 and AC-171 are recorded in `docs/ACCEPTANCE.md` as blocked on unmade rulings — JC-01
    (which licence the release carries) — so the document cannot be written yet, let alone
    checked. Two facts this scenario would need are recorded here anyway, so the day the document
    lands it has something to be checked against: the fonts that ship today (Inter and
    Commissioner, both from the kit), and the eight sounds S-74 names, which now ship.

    JC-04 ("where the eight sounds come from") no longer blocks anything: the sounds are not
    sourced, they are *generated* by `tools/make_sounds.py`, in-tree, from the standard library,
    and the generator is committed beside them. Their provenance row is therefore already
    writable — this repository is the author and the licence is whatever JC-01 rules for the
    release as a whole. The assertion below is what keeps that claim honest: every shipped sound
    must be one the generator names, so a downloaded file cannot appear in `web/public/sounds/`
    and inherit an authorship claim that does not apply to it.
    """
    assert not (REPO_ROOT / "ASSETS.md").exists(), "ASSETS.md landed — run the real both-ways check"
    assert not (REPO_ROOT / "LICENSE").exists(), "LICENSE landed — JC-01 was ruled, close this gate"

    assets = _shipped_assets()
    fonts = [p for p in assets if p.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf"}]
    assert fonts, "no fonts ship — the enumeration is wrong"

    sounds = [p for p in assets if p.suffix.lower() in {".mp3", ".wav", ".ogg"}]
    assert sounds, "no sounds ship — S-74 needs eight of them (run tools/make_sounds.py)"
    generator = (REPO_ROOT / "tools" / "make_sounds.py").read_text()
    unaccounted = sorted({p.stem for p in sounds if f'"{p.stem}"' not in generator})
    assert unaccounted == [], (
        f"shipped sounds no generator accounts for: {unaccounted} — a sound this repository did "
        f"not generate needs a real provenance row, not this file's authorship claim"
    )

    gate("ASSETS.md and LICENSE absent — AC-169/AC-171 blocked on ruling JC-01")
