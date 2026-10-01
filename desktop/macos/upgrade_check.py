#!/usr/bin/env python3
"""Check that data made by one Verticals.app survives the next one.

    python3 desktop/macos/upgrade_check.py OLD.app NEW.app                # on the sample board
    python3 desktop/macos/upgrade_check.py OLD.app NEW.app --state DIR    # on a copy of DIR

Runs OLD's launcher on a scratch state folder (fresh, so it loads the sample board, or a copy of
DIR with Verticals quit), counts the rows of every table and stops it. Then runs NEW on the same
folder, as an update does. NEW must come up healthy, serve the board and the docs, and keep at
least as many rows in every table. DIR is only read. Spare ports keep a running Verticals
undisturbed. The release workflow runs this against the previous release before publishing.
"""
from __future__ import annotations

import datetime
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORTS = {"UI": 18288, "API": 18299, "MCP": 18281, "PG": 55939}
UI = f"http://127.0.0.1:{PORTS['UI']}"
COUNT = """import json, sys, psycopg
with psycopg.connect(sys.argv[1]) as c:
    tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    print(json.dumps({"migration": c.execute("SELECT max(version) FROM schema_version").fetchone()[0],
                      "rows": {t: c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}}))
"""


def say(msg):
    print(f"[upgrade] {msg}", flush=True)


class App:
    def __init__(self, path, state, log):
        self.path, self.state, self.log, self.proc = Path(path).resolve(), state, log, None
        self.res = self.path / "Contents/Resources"
        self.version = plistlib.loads((self.path / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]

    def env(self):
        # What Verticals.swift hands the launcher, on spare ports.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("VERTICALS_", "PYTHON"))}
        env.update(VERTICALS_DESKTOP_STATE=str(self.state), VERTICALS_DESKTOP_PYTHONPATH=f"{self.res}:{self.res}/site",
                   VERTICALS_PG_BIN=str(self.res / "pg" / (self.res / "pg/BINDIR").read_text().strip()),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        env.update({f"VERTICALS_DESKTOP_{name}_PORT": str(port) for name, port in PORTS.items()})
        return env

    def start(self):
        self.proc = subprocess.Popen([self.res / "python/bin/python3", self.res / "desktop/launcher.py"],
                                     cwd=self.res, env=self.env(), stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 240
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise SystemExit(f"Verticals {self.version} exited with {self.proc.returncode}")
            try:
                with urllib.request.urlopen(f"{UI}/healthz", timeout=1) as r:
                    if json.load(r).get("db") == "ok":
                        return
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        raise SystemExit(f"Verticals {self.version} did not become healthy")

    def check(self):
        for path in (f"/api/board?date={datetime.date.today()}", "/api/docs"):
            with urllib.request.urlopen(UI + path, timeout=10) as r:
                json.load(r)
        password = json.loads((self.state / "config.json").read_text())["password"]
        dsn = f"postgresql://verticals:{password}@127.0.0.1:{PORTS['PG']}/verticals"
        out = subprocess.run([self.res / "python/bin/python3", "-c", COUNT, dsn], check=True, capture_output=True,
                             text=True, env={"PYTHONPATH": str(self.res / "site"), "PYTHONNOUSERSITE": "1"})
        return json.loads(out.stdout)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)  # the launcher stops PostgreSQL cleanly on SIGTERM
            self.proc.wait(timeout=60)
        if (self.state / "postgres/postmaster.pid").exists():
            raise SystemExit(f"Verticals {self.version} left PostgreSQL running")


def copy_state(source, state):
    pidfile = source / "postgres/postmaster.pid"
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text().split()[0]), 0)
            sys.exit(f"{source} is in use: quit Verticals first")
        except (ProcessLookupError, ValueError):
            pass
    shutil.copytree(source, state, symlinks=True, ignore=shutil.ignore_patterns("backups", "venv", "chat-workspace"))


def main():
    args = sys.argv[1:]
    if len(args) not in (2, 4) or (len(args) == 4 and args[2] != "--state"):
        sys.exit(__doc__)
    work = Path(tempfile.mkdtemp(prefix="verticals-upgrade-"))
    state = work / "state"
    if len(args) == 4:
        copy_state(Path(args[3]).expanduser().resolve(), state)
    log = open(work / "launcher.log", "ab")
    old, new = App(args[0], state, log), App(args[1], state, log)
    seen = {}
    try:
        for app in (old, new):
            say(f"starting {app.version}")
            app.start()
            seen[app] = app.check()
            app.stop()
    except BaseException:
        for app in (old, new):
            if app.proc and app.proc.poll() is None:
                app.proc.send_signal(signal.SIGTERM)
                app.proc.wait(timeout=60)
        log.flush()
        print((work / "launcher.log").read_text()[-4000:], file=sys.stderr)
        say(f"failed; launcher and database logs are in {work}")
        raise
    before, after = seen[old], seen[new]
    lost = {t: (n, after["rows"].get(t)) for t, n in before["rows"].items() if after["rows"].get(t, -1) < n}
    for table, (was, now) in sorted(lost.items()):
        say(f"{table}: {was} rows before, {'no table' if now is None else now} after")
    if lost:
        sys.exit(f"[upgrade] {new.version} lost data made by {old.version}; logs are in {work}")
    say(f"ok: {old.version} -> {new.version}, migration {before['migration']} -> {after['migration']}, "
        f"{sum(before['rows'].values())} -> {sum(after['rows'].values())} rows in {len(after['rows'])} tables")
    shutil.rmtree(work)


if __name__ == "__main__":
    main()
