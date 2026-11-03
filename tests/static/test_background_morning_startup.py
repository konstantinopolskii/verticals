"""The desktop starts both background reporting and Quick Entry on its live chat."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_startup_gives_the_same_chat_to_the_timer_and_quick_entry(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("morning_startup_launcher", root / "desktop/launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    events = []
    chat = Mock()
    chat.start_background_morning.side_effect = lambda: events.append("timer")
    quick_entry = Mock()
    quick_entry.onboard.side_effect = lambda: events.append("onboard")
    constructor = Mock(return_value=quick_entry)
    monkeypatch.setitem(sys.modules, "quick_entry", SimpleNamespace(QuickEntry=constructor))
    monkeypatch.setattr(launcher, "Chat", Mock(return_value=chat))
    gateway = Mock()
    monkeypatch.setattr(launcher, "Gateway", Mock(return_value=gateway))
    handler = Mock()
    monkeypatch.setattr(launcher, "make_gateway", handler)
    monkeypatch.setattr(launcher.threading, "Thread", Mock())
    monkeypatch.setattr(launcher.signal, "signal", Mock())
    monkeypatch.setattr(launcher, "STATE", tmp_path / "state")
    monkeypatch.setattr(launcher, "PGDATA", tmp_path / "postgres")
    monkeypatch.setattr(launcher, "settings", lambda: {"token": "sample-token"})
    monkeypatch.setattr(launcher, "environment", lambda cfg: {})
    monkeypatch.setattr(launcher, "pg_bin", lambda: tmp_path / "bin")
    monkeypatch.setattr(launcher, "mcp_instructions", lambda: "sample connection")
    monkeypatch.setattr(launcher, "host", SimpleNamespace(
        on_close=Mock(), spawn_service=Mock(return_value=Mock(poll=lambda: None)),
        stop_tree=Mock(), pg_env=lambda: {},
    ))
    for name in ("build_ui", "port_free", "setup_venv", "start_database", "prepare_database",
                 "write_mcp_config", "run"):
        monkeypatch.setattr(launcher, name, Mock())
    monkeypatch.setattr(launcher, "wait_healthy", lambda: events.append("ready"))
    monkeypatch.setattr(launcher.sys, "argv", ["launcher.py"])

    def stop_after_startup(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher.time, "sleep", stop_after_startup)
    launcher.main()

    assert events == ["ready", "timer", "onboard"]
    launcher.Chat.assert_called_once()
    handler.assert_called_once_with("sample-token", chat)
    constructor.assert_called_once_with(launcher.STATE, chat)
    chat.shutdown.assert_called_once_with()
