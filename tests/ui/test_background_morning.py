"""The desktop morning runs without a browser, through the real API and agent flow."""
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.ui.conftest import F2_OWNER, TEST_TOKEN, _backend
from tests.ui.test_morning_flow import Morning, RAW, DAY

ROOT = Path(__file__).resolve().parents[2]
SELECTION = {"provider": "claude", "permission": "board", "effort": "high", "model": "", "fast": False}


@pytest.fixture
def background(f2_dsn, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{ROOT / 'tests/ui/fake_agent'}:{os.environ['PATH']}")
    for key in ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        folder = tmp_path / key
        folder.mkdir()
        monkeypatch.setenv(key, str(folder))
    spec = importlib.util.spec_from_file_location("background_launcher", ROOT / "desktop/launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = launcher
    spec.loader.exec_module(launcher)
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        launcher.API_PORT = backend.port
        launcher.DIST = ROOT / "web/dist"
        state = tmp_path / "desktop-state"
        state.mkdir()
        chat = launcher.Chat(state, "http://127.0.0.1:9/mcp", TEST_TOKEN, api_url=backend.base_url, watch_every=0)
        (chat.workdir / "fake-agent.json").write_text(json.dumps({"api": backend.base_url, "token": TEST_TOKEN}))
        server = ThreadingHTTPServer(("127.0.0.1", 0), launcher.make_gateway(TEST_TOKEN, chat))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        launcher.UI_HOSTS.add(f"127.0.0.1:{server.server_port}")
        launcher.UI_ORIGINS.add(base)
        sample = Morning(backend, base, tmp_path)
        sample.sources()
        sample.last_report()
        sample.scenario(rows=[])
        try:
            yield sample, chat
        finally:
            chat.shutdown()
            sample.api.close()
            sample.gateway.close()
            server.shutdown()
            server.server_close()


def configure(sample, **changes):
    payload = {"settings": SELECTION, "timezone": "Europe/Berlin", **changes}
    response = sample.gateway.post("/__chat/morning", json=payload)
    assert response.status_code == 200, response.text


def at(chat, day=DAY, hour=7):
    chat.morning.now = lambda zone: datetime.fromisoformat(f"{day}T{hour:02}:00:00").replace(tzinfo=ZoneInfo(zone))


def test_without_a_window_the_background_loop_writes_and_checks_the_report(background):
    sample, chat = background
    configure(sample)
    at(chat)
    chat.start_background_morning(every=0.05)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if sample.report().startswith("Checked against the sources by a second agent: all 10 passed."):
                break
        except (KeyError, IndexError):
            pass
        time.sleep(0.05)
    assert sample.report().startswith("Checked against the sources by a second agent: all 10 passed.")
    goals = sample.gateway.get("/__chat/sessions").json()["goals"]
    assert sum(len(g["sessions"]) for g in goals.values()) == 1


def test_before_seven_and_while_an_agent_works_the_day_is_not_taken(background, monkeypatch):
    sample, chat = background
    configure(sample)
    at(chat, hour=6)
    assert chat.morning.tick() is None
    at(chat)
    monkeypatch.setattr(chat, "busy", lambda: True)
    assert chat.morning.tick() is None
    monkeypatch.setattr(chat, "busy", lambda: False)
    assert chat.morning.tick()["day"] == DAY


def test_restart_retains_the_chosen_settings_without_claiming_another_report(background):
    sample, chat = background
    configure(sample, settings={**SELECTION, "model": "synthetic-model", "permission": "bypassPermissions"})
    at(chat)
    first = chat.morning.tick()
    restarted = type(chat.morning)(chat)
    restarted.now = chat.morning.now
    assert restarted.tick() == first
    assert first["settings"]["permission"] == "bypassPermissions"
    assert first["settings"]["model"] == "synthetic-model"
    assert (chat.state_dir / "morning.json").stat().st_mode & 0o777 == 0o600


def test_a_day_taken_by_another_window_is_not_started_again(background):
    sample, chat = background
    configure(sample)
    at(chat)
    claimed = sample.api.post(f"/api/morning?date={DAY}").json()
    assert claimed["asked"] is True
    assert chat.morning.tick() is None
    assert not chat.load()


def test_missing_agent_and_a_failed_api_leave_the_day_available(background, monkeypatch):
    sample, chat = background
    configure(sample)
    at(chat)
    module = sys.modules[type(chat).__module__]
    real_which = module.which
    monkeypatch.setattr(module, "which", lambda _: None)
    assert chat.morning.tick() is None
    monkeypatch.setattr(module, "which", real_which)
    real_api = chat.api
    monkeypatch.setattr(chat, "api", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert chat.morning.tick() is None
    monkeypatch.setattr(chat, "api", real_api)
    assert chat.morning.tick()["day"] == DAY


def test_failed_dispatch_is_retained_and_retried_in_the_same_session(background, monkeypatch):
    sample, chat = background
    configure(sample)
    at(chat)
    real_send = chat.send
    monkeypatch.setattr(chat, "send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("temporary")))
    assert chat.morning.tick() is None
    pending = json.loads((chat.state_dir / "morning.json").read_text())["run"]
    monkeypatch.setattr(chat, "send", real_send)
    run = chat.morning.tick()
    assert run["session"] == pending["session"]
    assert sample.api.post(f"/api/morning?date={DAY}").json()["asked"] is False


def test_invalid_zone_cannot_replace_a_valid_schedule(background):
    sample, chat = background
    configure(sample)
    response = sample.gateway.post("/__chat/morning", json={"settings": SELECTION, "timezone": "Unknown/Zone"})
    assert response.status_code == 400
    at(chat)
    assert chat.morning.tick()["day"] == DAY


def test_two_simultaneous_timer_ticks_dispatch_only_once(background):
    from concurrent.futures import ThreadPoolExecutor
    sample, chat = background
    configure(sample)
    at(chat)
    with ThreadPoolExecutor(2) as pool:
        runs = list(pool.map(lambda _: chat.morning.tick(), range(2)))
    assert runs[0]["session"] == runs[1]["session"]
    assert len(chat.sessions) == 1


def test_local_day_and_recovery_after_sleep_use_the_saved_timezone(background):
    sample, chat = background
    configure(sample, timezone="Asia/Tokyo")
    zones = []
    def clock(zone):
        zones.append(zone)
        return datetime.fromisoformat("2026-08-09T23:30:00-03:00").astimezone(ZoneInfo(zone))
    chat.morning.now = clock
    run = chat.morning.tick()
    assert run["day"] == "2026-08-10"
    assert zones == ["Asia/Tokyo"]


def test_quitting_does_not_start_a_new_report(background):
    sample, chat = background
    configure(sample)
    at(chat)
    chat.stopping.set()
    assert chat.morning.tick() is None
    assert sample.api.post(f"/api/morning?date={DAY}").json()["asked"] is True


def test_quitting_during_the_claim_retains_dispatch_for_the_next_start(background, monkeypatch):
    sample, chat = background
    configure(sample)
    at(chat)
    real_api = chat.api
    def quit_after_claim(*args, **kwargs):
        result = real_api(*args, **kwargs)
        chat.stopping.set()
        return result
    monkeypatch.setattr(chat, "api", quit_after_claim)
    assert chat.morning.tick() is None
    assert not chat.sessions
    monkeypatch.setattr(chat, "api", real_api)
    chat.stopping.clear()
    assert chat.morning.tick()["day"] == DAY


def test_the_gateway_reports_the_background_timers_last_check(background):
    sample, chat = background
    configure(sample)
    response = sample.gateway.get("/__chat/morning")
    assert response.status_code == 200, response.text
    assert response.json()["last_checked"] is None
    at(chat, hour=6)
    chat.morning.tick()
    status = sample.gateway.get("/__chat/morning").json()
    assert status["configured"] is True
    assert status["timezone"] == "Europe/Berlin"
    assert status["last_checked"] == "2026-08-08T06:00:00+02:00"
