"""The desktop gateway for the UI suite's conversation scenarios: the built app, `/api` onto the test backend and the
real `/__chat/*` server, whose agent is `tests/ui/fake_agent/claude` (docs/design-handoff S2.P1).

    python tests/ui/agent_gateway.py <ui_port> <api_port> <state_dir> <token> [<mcp_url>]

The agents' own homes are inside the state folder (`claude-config`, `codex-home`, `home`): the sessions of tasks are files there
(docs/design/task-sessions.md), samples a scenario writes, and the owner's own `~/.claude` and `~/.codex` never come into it. The
gateway looks at those files every 0.2 s instead of every two seconds.

With an MCP server's url the fake agent's `[tool:NAME {json}]` marks are real calls to it, and the gateway marks each answer
there (docs/design/agent-answer-undo.md). Without one the url is a closed port: no tool is called and no answer is kept.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def main() -> None:
    ui_port, api_port, state, token = sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4]
    mcp_url = sys.argv[5] if len(sys.argv) > 5 else "http://127.0.0.1:9/mcp"
    os.environ["VERTICALS_DESKTOP_UI_PORT"] = ui_port
    os.environ["VERTICALS_DESKTOP_API_PORT"] = api_port
    os.environ["VERTICALS_DESKTOP_STATE"] = str(state)
    os.environ["PATH"] = f"{HERE / 'fake_agent'}:{os.environ.get('PATH', '')}"
    # What the fake agent writes the board through, as the real one does through Verticals' MCP tools.
    os.environ["FAKE_AGENT_API"] = f"http://127.0.0.1:{api_port}"
    os.environ["FAKE_AGENT_TOKEN"] = token
    state.mkdir(parents=True, exist_ok=True)
    os.environ.update(HOME=str(state / "home"), CLAUDE_CONFIG_DIR=str(state / "claude-config"),
                      CODEX_HOME=str(state / "codex-home"), VERTICALS_WATCH_SECONDS="0.2")
    for name in ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        Path(os.environ[name]).mkdir(exist_ok=True)
    sys.path.insert(0, str(REPO / "desktop"))
    import launcher  # noqa: E402  (reads the ports above at import)

    launcher.DIST = REPO / "web" / "dist"
    chat = launcher.Chat(state, mcp_url, token, api_url=f"http://127.0.0.1:{api_port}")
    # What the fake agent needs to play the morning report against the real server (tests/ui/fake_agent/fake_morning.py).
    (chat.workdir / "fake-agent.json").write_text(json.dumps({"api": f"http://127.0.0.1:{api_port}", "token": token}))
    # A test that waits for a second agent that never answers does not wait forty-five minutes.
    if os.environ.get("VERTICALS_TEST_CHECK_LIMIT"):
        import morning_flow
        morning_flow.CHECK_LIMIT = float(os.environ["VERTICALS_TEST_CHECK_LIMIT"])
    # Nor for an ask of the morning turn nobody answers.
    if os.environ.get("VERTICALS_TEST_ASK_LIMIT"):
        sys.modules["chat"].MORNING_PERMISSION_TIMEOUT = float(os.environ["VERTICALS_TEST_ASK_LIMIT"])
    server = ThreadingHTTPServer(("127.0.0.1", int(ui_port)), launcher.make_gateway(token, chat))
    print("ready", flush=True)
    try:
        server.serve_forever()
    finally:
        chat.shutdown()


if __name__ == "__main__":
    main()
