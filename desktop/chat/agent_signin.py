"""When the agent is signed out, the field signs it back in (docs/design/agent-sign-in.md).

The owner's chat and morning report stopped one morning: Claude Code's own sign-in on the Mac had expired, every turn ended in
"Failed to authenticate: OAuth session expired and could not be refreshed", shown raw in the field once per message, and the only
fix was a terminal command the field never mentioned. Now a turn that fails because its agent's CLI is signed out ends with one
ask in the field instead, the field's form for "the app asks you to do something, with buttons", the same balloon and buttons as
"Allow Claude to use…":

  * the gateway knows it by the error's words and confirms it with the CLI's own status command;
  * Sign in runs the CLI's login from the app, under the app's config folder, and the ask says "Approve in the browser"; when the
    login prints the sign-in page's address, the ask offers to open it in the browser, for the case no browser came up;
  * the status is checked every two seconds, for five minutes after the last Sign in or Open in Terminal; signed in, the ask ends
    with "Signed in" and the message that failed goes again by itself, in the same conversation, with what it was sent with;
  * a login that ends without a sign-in, or five minutes without one, brings the ask back with Sign in and Open in Terminal, which
    runs the same command in Terminal (agent_sessions.terminal_script), for a sign-in that asks for a code to be typed;
  * while the ask is open, the conversation's other messages wait behind it and go after the one that failed, in order.

How a login command behaves with no terminal is not known: it is started with its stdin open and never closed, its output is read
for the first https:// address, and only the status command is taken as proof of a sign-in. One login runs on the Mac at a time
for each agent: a second conversation that fails meanwhile gets an ask of its own and shares that login. Codex takes the same path
with its own commands, which the agent table holds (`AGENTS` in chat.py). The log says what happened, never the page's address.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time

import agent_sessions

# The words of a CLI's error that say it is signed out (docs/design/agent-sign-in.md); the status command has the last word.
SIGNED_OUT_WORDS = ("failed to authenticate", "oauth", "not logged in", "/login", "invalid api key")
EVERY = 2          # seconds between two looks at the status while a sign-in is under way
LIMIT = 5 * 60     # how long a Sign in, or an Open in Terminal, is waited for
STATUS_LIMIT = 15  # the longest one look at the status may take
# What the owner reads, exactly as the design has it.
ASKED = "Sign in once and your message goes again."
WAITING = "Approve in the browser."
SIGNED_IN = "Signed in"
SIGN_IN, TERMINAL, PAGE = ("Sign in", "signin"), ("Open in Terminal", "terminal"), ("Open the sign-in page", "page")
# An address the login prints, ended by a space or a line's end; a terminal's colours and links are taken out first.
ADDRESS = re.compile(r"https://[^\s\"'<>]+(?=\s)")
ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def looks_signed_out(detail, words=()):
    said = " ".join(str(detail or "").split()).lower()
    return any(word in said for word in (*SIGNED_OUT_WORDS, *words))


def clip(text, limit=300):
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


class Login:
    """One run of an agent's login command. Its stdin stays open, as a CLI waiting for a code may read it and one that finds it
    closed may give up; its output is read for the sign-in page's address; `ended` hears when it stops by itself."""

    def __init__(self, argv, cwd, env, found, ended):
        self.address = None
        self.found, self.ended = found, ended
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
        self.readers = [threading.Thread(target=self._read, args=(stream,), daemon=True) for stream in (self.proc.stdout, self.proc.stderr)]
        for reader in self.readers:
            reader.start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _read(self, stream):
        seen = ""
        while True:
            try:
                chunk = os.read(stream.fileno(), 4096)
            except OSError:
                break
            if not chunk:
                break
            seen = (seen + chunk.decode("utf-8", "replace"))[-8000:]
            self._look(seen)
        self._look(seen + "\n")

    def _look(self, text):
        if self.address is not None:
            return
        found = ADDRESS.search(ESCAPES.sub("", text))
        if found:
            self.address = found.group(0).rstrip(".,;:)]")
            self.found(self)

    def _wait(self):
        code = self.proc.wait()
        for reader in self.readers:
            reader.join(1)
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.ended(self, code)

    def alive(self):
        return self.proc.poll() is None

    def stop(self, grace=0.0):
        """Ends it: at once, or after `grace` seconds for one that is finishing by itself (just signed in)."""
        try:
            self.proc.wait(grace)
            return
        except subprocess.TimeoutExpired:
            pass
        for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.killpg(self.proc.pid, sig)  # its own session: the CLI and whatever it started for the browser
                self.proc.wait(wait)
                return
            except (OSError, subprocess.TimeoutExpired):
                continue


class Waiting:
    """A conversation's ask for the sign-in, and the message that goes again once signed in."""

    def __init__(self, session, provider, message):
        self.session, self.provider, self.message = session, provider, message
        self.key = f"signin-{secrets.token_hex(4)}"
        self.state = "asked"  # "asked": Sign in; "waiting": Approve in the browser; "again": Sign in, Open in Terminal


class SignIn:
    """The sign-in asks of every conversation and the one login of each agent they share. `which(provider)` is where the agent's CLI
    is and `env()` what it runs with, the gateway's own (chat.which, chat.child_env): the app's config folder goes along."""

    def __init__(self, chat, agents, which, env):
        self.chat, self.agents, self.which, self.env = chat, agents, which, env
        self.every, self.limit = EVERY, LIMIT
        self.lock = threading.RLock()
        self.asks = {}      # conversation id -> Waiting
        self.logins = {}    # provider -> Login
        self.until = {}     # provider -> when its looks at the status stop
        self.looking = set()

    def spec(self, provider):
        return (self.agents.get(provider) or {}).get("signin")

    def status(self, provider):
        """True when the agent's CLI says it is signed in, False when it says it is not, None when it cannot say."""
        spec, exe = self.spec(provider), self.which(provider)
        if not spec or not exe:
            return None
        try:
            done = subprocess.run([exe, *spec["status"]], cwd=self.chat.workdir, env=self.env(), stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=STATUS_LIMIT)
        except (OSError, subprocess.SubprocessError):
            return None
        if "json" not in spec:
            return done.returncode == 0  # Codex: the exit code says it
        try:
            said = json.loads(done.stdout[done.stdout.index("{"):done.stdout.rindex("}") + 1])
        except ValueError:
            return None
        value = said.get(spec["json"]) if isinstance(said, dict) else None
        return value if isinstance(value, bool) else None

    # -- what a conversation asks of the sign-in

    def holds(self, session_id):
        """Whether the conversation waits for a sign-in: its messages then wait too."""
        with self.lock:
            return session_id in self.asks

    def signed_out(self, s, detail):
        """Whether the turn of `s` that failed with `detail` failed because its agent is signed out: the CLI's words say so and its
        status command agrees. Any other error shows as it did."""
        provider = (s.settings or {}).get("provider")
        spec = self.spec(provider)
        if not spec or s.turn is None or not looks_signed_out(detail, spec.get("words", ())) or self.status(provider) is not False:
            return False
        self.chat.log.info("signin_needed provider=%s session=%s detail=%s", provider, str(s.id)[:8], clip(detail))
        return True

    def hold(self, s):
        """The conversation waits for a sign-in from here: one ask, never two. Shown with `show` once the turn has ended."""
        with self.lock:
            if s.id not in self.asks:
                self.asks[s.id] = Waiting(s, s.settings["provider"], s.turn)
            return self.asks[s.id]

    def show(self, w):
        """The ask as it stands. The same key each time: the page draws it in place of the one it was."""
        label = self.agents[w.provider]["label"]
        if w.state == "waiting":
            login = self.logins.get(w.provider)
            note, options = WAITING, [PAGE] if login is not None and login.address else []
        else:
            note, options = ASKED, [SIGN_IN, TERMINAL] if w.state == "again" else [SIGN_IN]
        w.session.ask(self, w.key, f"{label} is signed out on this Mac", "", options, note=note)

    def decide(self, key, value):
        """A button of the ask (chat.Chat.decide). The ask stays open: it changes, or ends with "Signed in"."""
        with self.lock:
            w = next((w for w in self.asks.values() if w.key == key), None)
        if w is None:
            return
        w.session.asks[key] = self
        if value == SIGN_IN[1]:
            self._sign_in(w)
        elif value == TERMINAL[1]:
            self._terminal(w)
        elif value == PAGE[1]:
            self._page(w)

    def drop(self, s):
        """The conversation's ask goes with it (Stop, a closed conversation): its message does not go again, and a login nobody
        waits for any more is stopped."""
        with self.lock:
            w = self.asks.pop(s.id, None)
            if w is None:
                return
            alone = not any(other.provider == w.provider for other in self.asks.values())
            login = self.logins.pop(w.provider, None) if alone else None
        s.resolve(w.key, "Cancelled")
        if login is not None:
            login.stop()

    def close(self):
        with self.lock:
            logins, self.logins, self.asks = list(self.logins.values()), {}, {}
        for login in logins:
            login.stop()

    # -- the buttons

    def _sign_in(self, w):
        if self.status(w.provider) is True:
            return self._signed_in(w.provider)  # signed in meanwhile, elsewhere: nothing to wait for
        with self.lock:
            login = self.logins.get(w.provider)
            if login is None or not login.alive():
                login = self._start(w.provider)
            w.state = "waiting" if login is not None else "again"
            self._look_for(w.provider)
        self.show(w)

    def _start(self, provider):
        spec, exe = self.spec(provider), self.which(provider)
        if not exe:
            return None
        try:
            login = Login([exe, *spec["login"]], self.chat.workdir, self.env(), lambda found: self._found(provider, found),
                          lambda found, code: self._ended(provider, found, code))
        except OSError as e:
            self.chat.log.warning("signin login_failed provider=%s %s", provider, clip(e))
            return None
        self.logins[provider] = login
        self.chat.log.info("signin login provider=%s", provider)
        return login

    def _terminal(self, w):
        """The same login in Terminal, from a script of the app's own as a session opens there (chat.Chat.open_session), under the
        app's config folder: Terminal starts from the owner's shell, not the app."""
        spec = self.spec(w.provider)
        action = {"kind": "terminal", "cwd": None, "command": [self.agents[w.provider]["exe"], *spec["login"]]}
        folder = self.chat.state_dir / "open"
        folder.mkdir(mode=0o700, exist_ok=True)
        script = folder / f"{w.provider}-sign-in.command"
        script.write_text(agent_sessions.terminal_script(action, self.which(w.provider), os.environ.get(spec["home"]), spec["home"]))
        script.chmod(0o700)
        code = self._open(["-a", "Terminal", str(script)])
        self.chat.log.info("signin terminal provider=%s code=%s", w.provider, code)
        with self.lock:
            self._look_for(w.provider)  # the looks go on while Terminal is open

    def _page(self, w):
        login = self.logins.get(w.provider)
        if login is not None and login.address:
            code = self._open([login.address])
            self.chat.log.info("signin page provider=%s code=%s", w.provider, code)

    def _open(self, args):
        """macOS's `open`, as the gateway opens a session where it lives: the sign-in page in the browser, never in a window of the
        app, where the owner's browser sign-ins are not."""
        opener = shutil.which("open", path=self.env()["PATH"])
        if not opener:
            return None
        try:
            return subprocess.run([opener, *args], cwd=self.chat.workdir, env=self.env(), capture_output=True, text=True,
                                  timeout=15).returncode
        except (OSError, subprocess.SubprocessError):
            return None

    # -- the login and the looks at the status

    def _look_for(self, provider):
        """Look at the status every few moments for the next five minutes (called with the lock held)."""
        self.until[provider] = time.time() + self.limit
        if provider not in self.looking:
            self.looking.add(provider)
            threading.Thread(target=self._looks, args=(provider,), daemon=True).start()

    def _looks(self, provider):
        while not self.chat.stopping.wait(self.every):
            with self.lock:
                waiting = any(w.provider == provider for w in self.asks.values())
                over = time.time() >= self.until.get(provider, 0)
                if not waiting or over:
                    self.looking.discard(provider)
                    break
            if self.status(provider) is True:
                with self.lock:
                    self.looking.discard(provider)
                return self._signed_in(provider)
        else:
            return
        if waiting:
            self._time_up(provider)

    def _found(self, provider, login):
        with self.lock:
            shown = [w for w in self.asks.values() if w.provider == provider and w.state == "waiting"]
        self.chat.log.info("signin page_found provider=%s", provider)
        for w in shown:
            self.show(w)

    def _ended(self, provider, login, code):
        """The login stopped by itself: signed in, or the ask comes back with both buttons."""
        with self.lock:
            if self.logins.get(provider) is not login:
                return  # stopped here, or a newer one runs
            del self.logins[provider]
        self.chat.log.info("signin login_exit provider=%s code=%s", provider, code)
        if self.status(provider) is True:
            return self._signed_in(provider)
        self._again(provider)

    def _time_up(self, provider):
        with self.lock:
            login = self.logins.pop(provider, None)
        if login is not None:
            login.stop()
        self.chat.log.info("signin limit provider=%s", provider)
        self._again(provider)

    def _again(self, provider):
        with self.lock:
            shown = [w for w in self.asks.values() if w.provider == provider and w.state == "waiting"]
            for w in shown:
                w.state = "again"
        for w in shown:
            self.show(w)

    def _signed_in(self, provider):
        """Every conversation that waited for this agent: its ask ends with "Signed in", and its message goes again."""
        with self.lock:
            login = self.logins.pop(provider, None)
            done = [w for w in self.asks.values() if w.provider == provider]
            for w in done:
                del self.asks[w.session.id]
                # From here the message that failed is the conversation's turn: anything sent now waits behind it.
                w.session.running = True
        if login is not None:
            threading.Thread(target=login.stop, args=(3,), daemon=True).start()  # a moment to finish what follows a sign-in
        if done:
            self.chat.log.info("signin signed_in provider=%s conversations=%d", provider, len(done))
        for w in done:
            w.session.asks.pop(w.key, None)
            w.session.emit({"t": "permission_done", "requestId": w.key, "label": SIGNED_IN, "says": SIGNED_IN})
            threading.Thread(target=self._resend, args=(w,), daemon=True).start()

    def _resend(self, w):
        """The message that failed goes again with what it was sent with: its words, its context and its settings (the morning
        turn's, a Replan's). Its agent starts afresh, so it reads the new sign-in; a session the failed turn left no file of
        begins anew, told only what was said before that message."""
        s, chat = w.session, self.chat
        agent, s.agent = s.agent, None
        if agent is not None:
            agent.close()
        session_id = chat.load().get(s.id, {}).get("sessionId")
        if session_id and agent_sessions.session_file(w.provider, session_id) is None:
            chat.update(s.id, sessionId=None)
        text, context, settings = w.message
        chat.start_turn(s, text, context, settings)
