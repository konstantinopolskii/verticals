#!/usr/bin/env bash
# The ONE way to run the E2E suite (docs/parity/PROTOCOL.md, "E2E serialisation").
#
# Why it exists: the app stack and the test Postgres share the container name
# `verticals-postgres-1` — with the app up, the test DB (127.0.0.1:55432) cannot start and the
# whole suite fails with a bogus "postgres unreachable". This wrapper is the only sanctioned
# holder of that swap, and it serialises: exactly one suite run at a time, machine-wide, via an
# exclusive lock on measure/.e2e.lock (fcntl — macOS ships no flock binary). Parallel Lunas
# build freely in their worktrees and QUEUE here for suite runs.
#
# Usage: scripts/e2e-run.sh [make-args...]     e.g. scripts/e2e-run.sh SUITE=ui
#        PYTEST="tests/parity -q" scripts/e2e-run.sh   -> runs that pytest instead of make test
#        Runs from any worktree: the lock file is anchored at this script's own repo, so every
#        worktree of the family contends on the same lock.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$ROOT/measure/.e2e.lock"
mkdir -p "$ROOT/measure"

exec "$ROOT/.venv/bin/python" - "$ROOT" "$LOCK" "$@" <<'EOF'
import fcntl, os, subprocess, sys, time

root, lock_path, *make_args = sys.argv[1:]
workdir = os.getcwd()  # the caller's worktree — the suite runs THERE, only the lock is shared

# The preview slot (127.0.0.1:8080) belongs to the MAIN checkout, always. A linked worktree
# carries `.git` as a FILE pointing at the main repo; the main checkout has a `.git` DIRECTORY.
# Both the pre-suite swap-down and the post-suite restore act on the main checkout's stack, so
# a worktree run can never evict the real preview and park its own stale image on the port
# (that happened twice: W9's failed restore, and W10 serving a pre-burst bundle to the owner).
if os.path.isdir(os.path.join(root, ".git")):
    main_root = root
else:
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    main_root = os.path.dirname(os.path.abspath(os.path.join(root, common)))

fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
t0 = time.monotonic()
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print(f"[e2e-run] lock busy ({lock_path}) — queueing...", flush=True)
    fcntl.flock(fd, fcntl.LOCK_EX)
print(f"[e2e-run] lock held after {time.monotonic() - t0:.0f}s", flush=True)


def sh(args, cwd, check=True):
    print(f"[e2e-run] $ {' '.join(args)}  (cwd={cwd})", flush=True)
    return subprocess.run(args, cwd=cwd, check=check)


rc = 1
try:
    # The swap. App data survives in the named volume; `down` here never touches volumes.
    # Down the caller's own stack too (worktree runs), then the canonical preview stack.
    if main_root != root:
        sh(["docker", "compose", "down"], cwd=root, check=False)
    sh(["docker", "compose", "down"], cwd=main_root, check=False)
    sh(["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d", "--wait"], cwd=root)
    pytest_args = os.environ.get("PYTEST", "").split()
    if pytest_args:
        cmd = [os.path.join(workdir, ".venv/bin/python"), "-m", "pytest", *pytest_args]
    else:
        cmd = ["make", "test", *make_args]
    rc = sh(cmd, cwd=workdir, check=False).returncode
finally:
    sh(["docker", "compose", "-f", "docker-compose.test.yml", "down"], cwd=root, check=False)
    # Restore the MAIN checkout's app stack (never the worktree's); one retry — the network
    # teardown is occasionally still in flight.
    if sh(["docker", "compose", "up", "-d", "--wait"], cwd=main_root, check=False).returncode != 0:
        time.sleep(5)
        sh(["docker", "compose", "up", "-d", "--wait"], cwd=main_root, check=False)
    fcntl.flock(fd, fcntl.LOCK_UN)
sys.exit(rc)
EOF
