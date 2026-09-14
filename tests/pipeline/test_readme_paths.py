"""S-116 and S-121 — the suite-E scenarios whose subject is `README.md` itself: the upgrade path
and the executable quickstart. (S-122, the third, outgrew this file the day the backup procedure
became real; it needs a database it is allowed to destroy and lives in
`tests/pipeline/test_s122_backup_readme.py`.)

Both follow the same rule, stated once in `docs/E2E.md` S-121 and repeated by S-116 and
S-122 ("extracted from the README, not typed into the test"): the commands under test are read
out of the file at run time by `tests/pipeline/readme_blocks.py`. A command this suite holds its
own copy of is a command that has already drifted (AC-162).

**What is green here and what is gated, and why the gates are honest.** All six of this file's
sibling scenarios are M2 criteria (`docs/ACCEPTANCE.md` §5), and M2's artifacts — a tagged
release, container packaging, a written backup procedure — do not exist in this tree yet. The
README says so in its own words, in its `Status` section and in the two sections that would
otherwise carry those procedures. So each scenario below splits into the half that can be proved
against what exists (and is proved, as a plain passing test) and the half that names a missing
artifact and calls `report.gate` — never `pytest.skip`, which `docs/E2E.md` §12 rule 4 and AC-089
(`skip == 0`) both forbid outright.

Every gate here first *asserts the precondition is genuinely absent* before gating on it. A gate
whose reason nobody checked is indistinguishable from a scenario quietly not running: this file
proves "no release tag exists" and "the README's Upgrading section documents no command" with
real assertions, and only then reports GATE. When those artifacts land, the assertions that hold
the gate open start failing, which is how the gate closes itself rather than waiting to be
noticed.

Run standalone:
    .venv/bin/python -m pytest tests/pipeline/test_readme_paths.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from verticals.db import runner
from tests.harness.report import gate
from tests.pipeline.readme_blocks import (
    README_PATH,
    Fence,
    read_fences,
    sections,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = runner.DEFAULT_MIGRATIONS_DIR

# The five questions AC-165 enumerates, mapped to the README heading each is answered under.
# Enumerated in the criterion itself ("install, connect an agent, back up, upgrade, export"),
# not chosen here.
_FIVE_QUESTIONS = {
    "install": "Running it from source",
    "connect an agent": "Connect an agent over MCP",
    "back up": "Backing up and restoring",
    "upgrade": "Upgrading",
    "get my data out": "Getting your data out",
}

# A section whose prose says the procedure does not exist yet. Matched as a substring of the
# section body; deliberately literal, so the gate closes the moment somebody writes the section
# for real and deletes the sentence.
_NOT_BUILT = "Not built yet"


def _readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )


def _admin_dsn(dbname: str = "postgres") -> str:
    """Same PGHOST/PGPORT/PGUSER/PGPASSWORD convention as `tests/pipeline/test_schema_parity.py`
    and `tests/core/test_migrations.py` — not `verticals.config.load()`, which is the application
    boot contract and additionally demands `VERTICALS_TOKEN`."""
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
def fresh_db() -> Iterator[str]:
    """One empty, unmigrated database in the shared compose cluster, dropped afterwards. The
    `verticals_t` prefix is the harness name guard (`docs/E2E.md` §2)."""
    name = f"verticals_t_s116_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _admin_dsn(name)
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


# ==================================================================================================
# S-116 — the upgrade path, from the previous release to head. Required by AC-167.
# ==================================================================================================


def test_s116a_upgrade_from_the_previous_release_tag() -> None:
    """S-116, the upgrade half: install the previous release tag, load F2, run the one documented
    upgrade command from `README.md`, re-read the digest.

    Two artifacts that half needs are absent, and both absences are asserted here rather than
    assumed. There is no tag to check out — AC-167 anticipates exactly this and offers a
    first-release substitution (install head at `up --to N-1`, then run *the documented upgrade
    command*), but that substitution needs the same second artifact this tree also lacks: the
    README's `Upgrading` section documents no command at all. It says the section is not built
    yet and explains why (no tagged release exists to upgrade from). With no command to extract,
    there is nothing to replay that would not be a command this test invented — which is the one
    thing S-116 forbids in the same sentence that names it ("extracted from the README, not typed
    into the test").
    """
    tags = [t for t in _git("tag", "--list").stdout.split() if t]
    assert tags == [], f"a release tag now exists ({tags}) — S-116's real path is runnable"

    upgrading = sections(_readme_text())["Upgrading"]
    assert _NOT_BUILT in upgrading, (
        "README's Upgrading section no longer says the procedure is unbuilt — extract the "
        "documented command and run the real S-116 path"
    )
    upgrade_fences = [f for f in read_fences() if f.section == "Upgrading"]
    assert upgrade_fences == [], "README's Upgrading section now carries a block — replay it"

    gate(
        "no release tag, and README 'Upgrading' documents no upgrade command "
        "(AC-167's first-release substitution needs the command too)"
    )


def test_s116b_the_runner_refuses_to_migrate_below_the_recorded_version(fresh_db: str) -> None:
    """S-116's closing clause — "the downgrade question, answered honestly" — which needs neither
    a release tag nor a README command, so it runs for real.

    Asserted rather than assumed, in S-116's own words: forward-only is a decision
    (`ARCHITECTURE.md` §3, `docs/IMPLEMENTATION.md` §6.4), and a decision nobody tests is a
    comment. The runner is invoked as a subprocess through its real CLI entrypoint, because the
    assertion is about an **exit code** (2) and a message on stderr, which only exist at that
    boundary — `run_up()` raises an exception and knows nothing about exit codes.
    """
    applied = runner.run_up(fresh_db)
    assert applied > 0
    head = max(m.version for m in runner.discover_migrations(MIGRATIONS_DIR))

    env = {**os.environ, "VERTICALS_DATABASE_URL": fresh_db}
    proc = subprocess.run(
        [sys.executable, "-m", "verticals.db.runner", "up", "--to", str(head - 1)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    message = proc.stderr.lower()
    assert "restore from a backup" in message, proc.stderr
    assert "forward-only" in message, proc.stderr

    # And it refused rather than half-doing it: the schema is still at head, and nothing about
    # the failed invocation touched `schema_version`.
    with psycopg.connect(fresh_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(version) FROM schema_version")
        (version,) = cur.fetchone()
    assert version == head

    # The neighbouring case is not a downgrade and must still work: `--to` *at* the recorded
    # version is a no-op that exits 0, the same shape S-02 asserts for a plain re-run.
    same = subprocess.run(
        [sys.executable, "-m", "verticals.db.runner", "up", "--to", str(head)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert same.returncode == 0, same.stderr
    assert "applied=0" in same.stdout


# ==================================================================================================
# S-121 — the README is executable, and it is executed. AC-155, AC-162, AC-164, AC-165.
# ==================================================================================================


def _executable_fences() -> list[Fence]:
    return [f for f in read_fences() if f.is_executable_language]


def test_s121a_no_unmarked_executable_block_exists() -> None:
    """S-121's central clause, and the one that needs no container: "zero unmarked executable
    blocks — every fence whose language is `bash`, `sh` or `console` is either marked `e2e` or
    marked `e2e-skip` with a one-line reason". AC-164's second half.

    This is the mechanism the scenario says it is: with it green, adding an untested command to
    the README is impossible by accident, because an unmarked `bash` fence fails this suite. It
    is asserted here even though the replay half (S-121b) is gated, and that ordering is
    deliberate — the marking discipline has to hold *before* the replay exists, or the replay
    lands on a file that already has untested commands in it.

    One documented divergence from the catalogue text. `docs/E2E.md` S-121 says the skip reason
    sits "on the preceding line"; `README.md` writes it on the info string itself
    (```` ```bash e2e-skip: <reason> ````), which keeps the reason attached to the fence when a
    section is moved. Both are accepted by `readme_blocks.Fence.skip_reason` and the assertion
    is that a reason exists in one of the two places. Reported as a catalogue-vs-file
    contradiction rather than silently resolved.
    """
    fences = _executable_fences()
    assert fences, "README has no executable fenced blocks at all — the parser is wrong"

    unmarked = [f for f in fences if not (f.is_marked_run or f.is_marked_skip)]
    assert unmarked == [], "unmarked executable fences at README.md lines " + ", ".join(
        f"{f.line_no} (```{f.info})" for f in unmarked
    )

    reasonless = [f for f in fences if f.is_marked_skip and not f.skip_reason]
    assert reasonless == [], "e2e-skip without a reason at README.md lines " + ", ".join(
        str(f.line_no) for f in reasonless
    )

    # The blocks the replay would run, in document order, are non-empty and are real commands —
    # a marked-but-empty fence would pass the marking audit while replaying nothing.
    marked = [f for f in fences if f.is_marked_run]
    assert marked, "no block is marked e2e — the replay half would have nothing to run"
    assert all(f.body.strip() for f in marked)
    assert [f.line_no for f in marked] == sorted(f.line_no for f in marked)


def test_s121b_marked_blocks_replay_in_order_on_a_clean_container() -> None:
    """S-121's replay half: run every marked block, in document order, in one clean container
    sharing shell state, and assert the last one leaves a working install.

    **The old gate is closed and this is a different one, narrower and measured.** Container
    packaging now exists — `Dockerfile`, `docker-compose.yml` and `docker/entrypoint.sh` all
    ship, and S-117 boots them for real (`tests/pipeline/test_release_tag.py`). So "there is no
    container" is no longer true and is no longer what holds this open.

    What holds it open is what the marked blocks actually are. They are the **source** path, not
    the packaged one, and replaying them needs a toolchain the shipped image deliberately does
    not carry: `npm`/`node` (three blocks), `psql` (one), `make` (three) and `curl` (three) —
    every one of them asserted below against the extracted block bodies, and asserted absent from
    the `Dockerfile`'s runtime stage, which installs `nginx-light` and nothing else. That is not
    an oversight to fix in this test: a runtime image that shipped a Node toolchain, a compiler
    and a Postgres client would be a bigger attack surface for every self-hoster, in exchange for
    a convenience only this suite wants.

    And the toolchain is the smaller half. `make db-up` runs `docker compose -f
    docker-compose.test.yml up -d`, so replaying these blocks *inside* a container requires a
    **nested Docker daemon** — privileged docker-in-docker — or else the host's own daemon, where
    `docker-compose.test.yml`'s fixed port 55432 is held by the cluster this very suite is using
    and the seed block would write into the database every other scenario reads. The repository
    ships no second image for this (asserted: no `docker/Dockerfile*`), and `docs/E2E.md` §1's
    infrastructure list names none.

    The half of S-121 that does not need any of this — the marking audit, which is the clause the
    scenario itself calls "the whole mechanism" — runs and passes in `test_s121a`.
    """
    packaging = [
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "docker" / "entrypoint.sh",
    ]
    missing = [p.name for p in packaging if not p.exists()]
    assert missing == [], f"container packaging is incomplete: {missing}"
    assert _NOT_BUILT not in sections(_readme_text())["Running it from source"]

    # What the marked blocks demand of whatever runs them, read off the blocks themselves.
    replay_text = "\n".join(f.body for f in read_fences() if f.is_marked_run)
    for tool in ("npm", "psql", "make", "curl"):
        assert tool in replay_text, (
            f"the marked blocks no longer call {tool!r} — re-derive what a replay host needs"
        )
    assert "make db-up" in replay_text, (
        "the marked blocks no longer start their own Postgres — the docker-in-docker half of "
        "this gate may be closable"
    )

    # What the shipped image carries. Read from the Dockerfile rather than by running it, so this
    # holds on a machine with no daemon and still flips the day somebody adds a build image.
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("AS runtime", 1)[1]
    for tool in ("nodejs", "npm", "postgresql-client", "make", "docker.io"):
        assert f"install -y --no-install-recommends {tool}" not in runtime_stage, (
            f"the runtime image now installs {tool} — re-check whether the replay can run in it"
        )
    assert not list((REPO_ROOT / "docker").glob("Dockerfile*")), (
        "a second image now exists under docker/ — if it carries the source toolchain and a "
        "nested daemon, this gate is closable"
    )

    gate(
        "S-121's replay needs a host with the source toolchain (npm, psql, make, curl) AND a "
        "Docker daemon of its own for `make db-up`; the shipped runtime image carries none of "
        "them by design and no docker-in-docker image exists in this tree"
    )


def test_s121c_the_five_self_hoster_questions_have_sections() -> None:
    """AC-165, which S-121 shares with S-116, S-117, S-118 and S-122: "five sections present,
    each with an executed block".

    The first half is proved: all five sections exist, under the headings named below, and each
    one is a real section with prose rather than a stub. The second half — an *executed* block
    under each — cannot hold today for two of the five, and this test proves which two and why
    rather than asserting a criterion the tree cannot meet. `Backing up and restoring` and
    `Upgrading` both say in their own text that the procedure is not built, and neither carries
    any fenced block at all, so there is nothing to execute. Those are S-122's and S-116's own
    gates; here they gate AC-165's execution clause, which is the same absence counted once more.
    """
    text = _readme_text()
    present = sections(text)
    missing = [h for h in _FIVE_QUESTIONS.values() if h not in present]
    assert missing == [], f"README is missing sections for self-hoster questions: {missing}"
    for heading in _FIVE_QUESTIONS.values():
        assert present[heading].strip(), f"section {heading!r} is empty"

    fences = read_fences()
    unbuilt = sorted(
        heading
        for heading in _FIVE_QUESTIONS.values()
        if _NOT_BUILT in present[heading]
        and not [f for f in fences if f.section == heading and f.is_marked_run]
    )
    assert unbuilt == ["Upgrading"], (
        f"the set of unbuilt self-hoster sections changed: {unbuilt}"
    )

    # `Backing up and restoring` left that set when S-122 landed: the section now documents a real
    # procedure and carries a `make backup` block marked `e2e`, which S-122 replays verbatim
    # against a private cluster (`tests/pipeline/test_s122_backup_readme.py`). Four of AC-165's
    # five questions are therefore answered by an executed block; only `Upgrading` is not, and it
    # cannot be until a release tag exists to upgrade from (S-116's own gate, same absence).
    backup_blocks = [
        f for f in fences if f.section == "Backing up and restoring" and f.is_marked_run
    ]
    assert backup_blocks, "the backup section lost its executed block"

    gate(
        "AC-165's executed-block clause: 'Upgrading' documents no procedure yet (no tagged "
        "release to upgrade from), so it carries no block to execute"
    )


# ==================================================================================================
# S-122 — backup and restore, performed the way the README says. AC-166.
#
# Was a gate here, on a README section that said "Not built yet". It is now a real scenario and
# lives in `tests/pipeline/test_s122_backup_readme.py`: the section documents a procedure, the
# `Makefile` carries `backup` and `restore`, and the blocks are replayed verbatim against a
# private throwaway cluster — including the corrupt-dump case and the concurrent-writer case.
# Nothing about it belongs in this file, which owns no database of its own.
# ==================================================================================================
