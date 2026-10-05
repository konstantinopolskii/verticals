#!/usr/bin/env python3
"""Verticals desktop launcher: PostgreSQL, the API, the MCP server and the UI (with the agent chat)
in one process tree, on loopback only.

    python3 desktop/launcher.py          # run from the repository (first run sets up state)
    python3 desktop/launcher.py mcp      # print how to connect an agent to the MCP server

Independent of tools/local.py: own ports, own database and state directory
(.local-verticals-desktop/, or ~/Library/Application Support/Verticals inside the app), and its own
UI build in desktop/build/web made with an empty token — the gateway below adds the bearer
header on its way to the API, like the Docker image's nginx does. The web variant is untouched.
Inside Verticals.app the same file runs from a bundle that mirrors the repository layout.
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "chat"))
from chat import Chat, ChatError  # noqa: E402

ROOT = Path(__file__).resolve().parent          # desktop/
APP = ROOT.parent                               # repository root (or its mirror inside the app)
DIST = ROOT / "build" / "web"
# Inside Verticals.app the code is read-only and state lives in Application Support.
STATE = Path(os.environ.get("VERTICALS_DESKTOP_STATE") or APP / ".local-verticals-desktop")
PGDATA = STATE / "postgres"
# Bundled mode: the app ships Python with every dependency on this path; no venv to build.
BUNDLED_PATH = os.environ.get("VERTICALS_DESKTOP_PYTHONPATH", "")
VENV = STATE / "venv"
PYTHON = Path(sys.executable) if BUNDLED_PATH else VENV / "bin" / "python"

def _port(name, default):
    return int(os.environ.get(f"VERTICALS_DESKTOP_{name}_PORT", default))


# Overridable to run a second copy side by side (the app window always uses 8288).
UI_PORT, API_PORT, MCP_PORT, PG_PORT = _port("UI", 8288), _port("API", 8299), _port("MCP", 8281), _port("PG", 55539)
UI_ORIGINS = {f"http://127.0.0.1:{UI_PORT}", f"http://localhost:{UI_PORT}"}
UI_HOSTS = {f"127.0.0.1:{UI_PORT}", f"localhost:{UI_PORT}"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
         ".woff2": "font/woff2", ".woff": "font/woff", ".mp3": "audio/mpeg", ".wav": "audio/wav",
         ".ogg": "audio/ogg", ".webmanifest": "application/manifest+json", ".txt": "text/plain"}
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
       "proxy-authorization", "proxy-authenticate", "host", "content-length", "authorization"}


def log(msg):
    print(f"[desktop] {msg}", flush=True)


def run(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, cwd=kw.pop("cwd", ROOT), **kw)


# ---------------------------------------------------------------- prerequisites

def pg_bin():
    candidates = [os.environ.get("VERTICALS_PG_BIN", ""), "/opt/homebrew/opt/postgresql@16/bin",
                  "/usr/local/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin"]
    if shutil.which("pg_ctl"):
        candidates.append(str(Path(shutil.which("pg_ctl")).parent))
    for c in candidates:
        ctl = Path(c) / "pg_ctl"
        if c and ctl.is_file() and " 16." in subprocess.check_output([str(ctl), "--version"], text=True):
            return Path(c)
    sys.exit("PostgreSQL 16 is required (brew install postgresql@16), or set VERTICALS_PG_BIN.")


def python312():
    if os.environ.get("VERTICALS_PYTHON"):
        return os.environ["VERTICALS_PYTHON"]
    if shutil.which("python3.12"):
        return shutil.which("python3.12")
    if shutil.which("uv"):
        out = subprocess.run(["uv", "python", "find", "3.12"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    sys.exit("Python 3.12 is required (uv python install 3.12), or set VERTICALS_PYTHON.")


def port_free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Port {port} is busy. Stop whatever uses it; nothing was killed.")


def settings():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = STATE / "config.json"
    if not path.exists():
        with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
            json.dump({"token": secrets.token_urlsafe(32), "password": secrets.token_urlsafe(32)}, f)
    return json.loads(path.read_text())


def environment(cfg):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VERTICALS_", "VITE_"))}
    # Explicit values: python-dotenv must never pick up some other database from a stray .env.
    env.update(VERTICALS_DATABASE_URL=f"postgresql://verticals:{cfg['password']}@127.0.0.1:{PG_PORT}/verticals",
               # The shipped sample board belongs to the single-owner default, "local".
               VERTICALS_TOKEN=cfg["token"], VERTICALS_OWNER="local",
               VERTICALS_BIND=f"127.0.0.1:{API_PORT}", VERTICALS_MCP_BIND=f"127.0.0.1:{MCP_PORT}",
               VERTICALS_POOL_MIN="1", VERTICALS_POOL_MAX="4", VERTICALS_LOG_LEVEL="warning")
    if BUNDLED_PATH:
        # Code is precompiled and signed inside the bundle: never write .pyc into it.
        env.update(PYTHONPATH=BUNDLED_PATH, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    else:
        env["PYTHONPATH"] = str(APP)
    return env


def setup_venv():
    if BUNDLED_PATH or PYTHON.exists():
        return
    interpreter = python312()
    log(f"creating the Python environment ({interpreter})")
    # Dependencies only: verticals itself runs from the source tree, so nothing is built in the repo.
    if shutil.which("uv"):
        run(["uv", "venv", "--python", interpreter, VENV])
        run(["uv", "pip", "install", "--python", PYTHON, "-r", APP / "pyproject.toml"])
    else:
        run([interpreter, "-m", "venv", VENV])
        deps = json.loads(subprocess.check_output([interpreter, "-c",
            "import tomllib, json; print(json.dumps(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))"],
            cwd=APP, text=True))
        run([PYTHON, "-m", "pip", "install", "--quiet", *deps])


# ---------------------------------------------------------------- database

def pg_env():
    # On macOS the postmaster refuses to start without a valid locale in the environment
    # ("postmaster became multithreaded during startup"); apps opened from Finder have none.
    env = os.environ.copy()
    if not env.get("LC_ALL"):
        env["LC_ALL"] = "en_US.UTF-8"
    return env


def start_database(pg, cfg, env):
    port_free(PG_PORT)
    if not PGDATA.exists():
        log("initialising the database")
        pwfile = STATE / "pg-password"
        try:
            with open(pwfile, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
                f.write(cfg["password"])
            run([pg / "initdb", "-D", PGDATA, "-U", "verticals", "--auth=scram-sha-256",
                 "--pwfile", pwfile, "--encoding=UTF8", "--no-locale"], stdout=subprocess.DEVNULL, env=pg_env())
        finally:
            pwfile.unlink(missing_ok=True)
    run([pg / "pg_ctl", "-D", PGDATA, "-l", STATE / "postgres.log", "-w", "start", "-o",
         f"-h 127.0.0.1 -p {PG_PORT} -k '' -c shared_buffers=32MB -c max_connections=30"],
        stdout=subprocess.DEVNULL, env=pg_env())
    run([PYTHON, "-c", """import os, psycopg
from psycopg.conninfo import make_conninfo
with psycopg.connect(make_conninfo(os.environ['VERTICALS_DATABASE_URL'], dbname='postgres'), autocommit=True) as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname='verticals'").fetchone():
        c.execute('CREATE DATABASE verticals')
"""], env=env, cwd=APP)
    run([PYTHON, "-m", "verticals.db.runner", "up"], env=env, cwd=APP, stdout=subprocess.DEVNULL)
    if not (STATE / "seeded").exists():
        log("loading the sample board")
        run([PYTHON, "-c", """import os, pathlib, psycopg
with psycopg.connect(os.environ['VERTICALS_DATABASE_URL']) as c:
    if not c.execute('SELECT 1 FROM goals LIMIT 1').fetchone():
        c.execute(pathlib.Path('verticals/db/seed_sample.sql').read_text())
"""], env=env, cwd=APP)
        (STATE / "seeded").touch()


# ---------------------------------------------------------------- UI gateway

CHAT_UI = ROOT / "chat" / "ui"  # the agents' marks; the conversation itself is the app's (web/src/lib/agentChat.ts)
BOOT = secrets.token_hex(8)  # tells chat clients the event log restarted


_FRAMES: dict[str, bool] = {}


def framable(url):
    """Whether a web page can open in a window (docs/design-handoff S3.P4.026): fetched once, following redirects, it
    must end in a 2xx with no X-Frame-Options and no frame-ancestors that leaves the app out. Remembered per address."""
    if url in _FRAMES:
        return _FRAMES[url]
    answer = False
    if url.startswith(("https://", "http://")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) Verticals"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                ok = 200 <= resp.status < 300
                policy = resp.headers.get("Content-Security-Policy", "")
                ancestors = next((d.strip().split()[1:] for d in policy.split(";") if d.strip().startswith("frame-ancestors")), None)
                allowed = ancestors is None or "*" in ancestors or any(o in ancestors for o in UI_ORIGINS)
                answer = ok and not resp.headers.get("X-Frame-Options") and allowed
        except (OSError, ValueError):
            answer = False
    _FRAMES[url] = answer
    return answer


def make_gateway(token, chat):
    class Gateway(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def deny(self, code, msg):
            # An unread request body would be parsed as the next request on a kept-alive socket.
            self.close_connection = True
            body = json.dumps({"error": msg}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            # The gateway holds the API token, so only this UI may use it: block DNS rebinding
            # (Host) and cross-site requests from other pages (Origin / Sec-Fetch-Site).
            if self.headers.get("Host") not in UI_HOSTS:
                return self.deny(403, "bad host")
            origin = self.headers.get("Origin")
            if origin and origin not in UI_ORIGINS:
                return self.deny(403, "bad origin")
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return self.deny(403, "cross-site request")
            return True

        def proxy(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            if not self.allowed():
                return
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            if self.path.startswith("/api"):
                headers["Authorization"] = f"Bearer {token}"
            conn = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=3600)
            try:
                conn.request(self.command, self.path, body=body, headers=headers)
                resp = conn.getresponse()
            except OSError:
                return self.deny(502, "API unavailable")
            streaming = "text/event-stream" in (resp.getheader("Content-Type") or "")
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            if streaming:
                # Server-sent events: pass bytes through as they arrive, then close.
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    while chunk := resp.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (OSError, http.client.HTTPException):
                    pass  # either side closed the stream, e.g. the API stopping
            else:
                try:
                    data = resp.read()
                except http.client.HTTPException:
                    return self.deny(502, "API closed the connection")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            conn.close()

        def json_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def chat_route(self):
            from urllib.parse import parse_qs, urlparse
            path = self.path.split("?", 1)[0]
            if self.command == "GET" and path.startswith("/__chat/assets/"):
                asset = (CHAT_UI / "assets" / path.removeprefix("/__chat/assets/")).resolve()
                if asset.parent != (CHAT_UI / "assets").resolve() or not asset.is_file():
                    return self.deny(404, "not found")
                return self.static(asset)
            if not self.allowed():
                return
            if self.command == "GET" and path == "/__chat/events":
                return self.chat_events()
            if self.command == "GET" and path == "/__chat/agents":
                return self.send_json({"agents": chat.agents()})
            if self.command == "GET" and path == "/__chat/busy":
                return self.send_json({"busy": chat.busy()})
            if self.command == "GET" and path == "/__chat/frame":
                page = parse_qs(urlparse(self.path).query).get("url", [""])[0]
                return self.send_json({"framable": framable(page)})
            if self.command == "GET" and path == "/__chat/goal":
                goal = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                return self.send_json({"conversations": chat.goal_conversations(goal)})
            if self.command == "GET" and path == "/__chat/probe":
                try:
                    return self.send_json(chat.probe(parse_qs(urlparse(self.path).query).get("provider", [""])[0]))
                except ChatError as e:
                    return self.deny(400, str(e))
            if self.command != "POST":
                return self.deny(405, "method not allowed")
            try:
                body = self.json_body()
                action = path.removeprefix("/__chat/")
                if action == "send":
                    chat.send(body.get("session"), body.get("text"), body.get("context"), body.get("settings"),
                              "now" if body.get("mode") == "now" else "send")
                elif action == "permission":
                    chat.decide(body.get("session"), body.get("requestId"), body.get("value"))
                elif action == "stop":
                    chat.stop(body.get("session"))
                elif action == "reset":
                    chat.reset(body.get("session"))
                else:
                    return self.deny(404, "not found")
            except (ChatError, ValueError) as e:
                return self.deny(400, str(e))
            self.send_json({"ok": True})

        def send_json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def chat_events(self):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            try:
                session = chat.session(query.get("session", [""])[0])
            except ChatError as e:
                return self.deny(400, str(e))
            since = int(query.get("since", ["0"])[0] or 0) if query.get("boot", [""])[0] == BOOT else 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(f"event: hello\ndata: {json.dumps({'boot': BOOT})}\n\n".encode())
                self.wfile.flush()
                while True:
                    batch = session.since(since, timeout=15)
                    for seq, event in batch:
                        self.wfile.write(f"data: {json.dumps({'seq': seq, 'event': event})}\n\n".encode())
                        since = seq
                    if not batch:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except OSError:
                pass

        def static(self, path=None):
            if self.headers.get("Host") not in UI_HOSTS:
                return self.deny(403, "bad host")
            if path is None:
                rel = self.path.split("?", 1)[0].lstrip("/")
                path = (DIST / rel).resolve()
                if not rel or not path.is_file() or DIST not in path.parents:
                    path = DIST / "index.html"  # single-page app fallback
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store" if path.name == "index.html"
                             else "public, max-age=31536000, immutable")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def route(self):
            if self.path.startswith("/__chat/"):
                return self.chat_route()
            if self.path.startswith(("/api", "/healthz")):
                return self.proxy()
            if self.command in ("GET", "HEAD"):
                return self.static()
            self.deny(405, "method not allowed")

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = route

    return Gateway


# ---------------------------------------------------------------- run

def mcp_instructions():
    url = f"http://127.0.0.1:{MCP_PORT}/mcp"
    return (f"MCP (streamable HTTP): {url}\n"
            f"  Private JSON config: {STATE / 'mcp.json'}\n"
            "  Authentication stays in that owner-only file; do not share it.")


def write_mcp_config(token):
    path = STATE / "mcp.json"
    config = {"mcpServers": {"verticals-desktop": {"type": "http", "url": f"http://127.0.0.1:{MCP_PORT}/mcp",
                                               "headers": {"Authorization": f"Bearer {token}"}}}}
    path.unlink(missing_ok=True)
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump(config, f, indent=2)
    # Claude Code's headersHelper reads this (Connect Claude Code in the menu bar icon).
    path = STATE / "mcp-headers.json"
    path.unlink(missing_ok=True)
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump({"Authorization": f"Bearer {token}"}, f)


def wait_healthy():
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{UI_PORT}/healthz", timeout=1) as r:
                if json.load(r).get("db") == "ok":
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"the API did not become healthy; see {STATE}/*.log")


def stop_on_signal(signum, frame):
    # SIGTERM shuts down like Ctrl-C: services stop, the database stops cleanly, data stays.
    raise KeyboardInterrupt


def main():
    if not (DIST / "index.html").exists():
        sys.exit("desktop/build/web is missing. Build the UI first (see desktop/README.md):\n"
                 "  VITE_VERTICALS_TOKEN= npm --prefix web run build -- --outDir ../desktop/build/web --emptyOutDir")
    cfg = settings()
    if sys.argv[1:] == ["mcp"]:
        write_mcp_config(cfg["token"])
        print(mcp_instructions())
        return
    pg = pg_bin()
    for port in (UI_PORT, API_PORT, MCP_PORT):
        port_free(port)
    setup_venv()
    env = environment(cfg)
    signal.signal(signal.SIGTERM, stop_on_signal)
    procs, db_started, gateway, chat = [], False, None, None
    try:
        start_database(pg, cfg, env)
        db_started = True
        for name, argv in (("api", [PYTHON, "-m", "verticals.api.app"]),
                           ("mcp", [PYTHON, "-m", "verticals.mcp.server", "--transport", "http"])):
            logfile = open(STATE / f"{name}.log", "ab")
            procs.append(subprocess.Popen([str(a) for a in argv], cwd=APP, env=env, stdout=logfile,
                                          stderr=subprocess.STDOUT, start_new_session=True))
        chat = Chat(STATE, f"http://127.0.0.1:{MCP_PORT}/mcp", cfg["token"])
        gateway = ThreadingHTTPServer(("127.0.0.1", UI_PORT), make_gateway(cfg["token"], chat))
        gateway.daemon_threads = True
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        wait_healthy()
        write_mcp_config(cfg["token"])
        print(f"\nVerticals desktop is up\n  UI:  http://127.0.0.1:{UI_PORT}/\n  {mcp_instructions()}\n"
              f"Ctrl-C stops everything; data stays in {STATE}.\n", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        raise RuntimeError(f"a service exited; see {STATE}/api.log and {STATE}/mcp.log")
    except KeyboardInterrupt:
        log("stopping")
    finally:
        if gateway:
            gateway.shutdown()
        if chat:
            chat.shutdown()
        for p in reversed(procs):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        if db_started:
            run([pg / "pg_ctl", "-D", PGDATA, "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL, env=pg_env())


if __name__ == "__main__":
    main()
