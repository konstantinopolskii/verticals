"""AC-139 / the mcp-suite intro's "stream rule, corrected" (`docs/E2E.md` lines 1255-1261) — a
dedicated both-directions probe, not tied to one catalogue scenario id (every `test_sNN_*` test
in this suite already exercises the *pass* direction once per call via `StdioStreams.
assert_hygiene()`; this file is what proves the *fail* direction actually fires instead of
passing by construction).

Real stdio session, real F2 fixture, no mocks. The plant never touches shipped source: it points
`server_args` at a `-c` inline script that prints stray, non-protocol text to stdout before
handing off to the real, unmodified `verticals.mcp.server:main()` — `tests/mcp/conftest.py`'s own
`server_args` parameter exists for exactly this one caller."""

from __future__ import annotations

import functools
from pathlib import Path

import anyio
import pytest

from tests.mcp.conftest import StdioStreams, TEST_TOKEN, open_mcp_stdio

# Prints one line of plain, non-JSON-RPC noise on stdout, then hands off to the real, unmodified
# entrypoint exactly as `python -m verticals.mcp.server` would run it — the plant is entirely in
# *what argv looks like*, never in shipped source.
_STRAY_NOISE_SCRIPT = (
    "import sys; "
    "print('BOOT NOISE NOT PROTOCOL', flush=True); "
    "sys.argv = ['verticals.mcp.server']; "
    "import runpy; "
    "runpy.run_module('verticals.mcp.server', run_name='__main__')"
)
_STRAY_NOISE_ARGS = ("-c", _STRAY_NOISE_SCRIPT)


async def _try_open_and_call_board(f2_dsn: str, tmp_path: Path, *, server_args: tuple[str, ...], label: str):
    """Best-effort: a stray first line may or may not be enough to break the SDK's own line
    parser outright. Report whichever happens rather than assuming one — the property under
    test is the *file-level* hygiene check below, which is reachable either way since `tee`
    writes bytes to disk regardless of what the client does with them."""
    try:
        async with open_mcp_stdio(f2_dsn, tmp_path, server_args=server_args, label=label) as (session, _streams):
            result = await session.call_tool("board", {"date": "2026-08-08"})
            return "ok", result.is_error
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: reporting *whatever* failure, not asserting one shape
        return "raised", f"{type(exc).__name__}: {exc}"


def test_stream_hygiene_stray_stdout_is_caught_both_directions(f2_dsn: str, tmp_path: Path) -> None:
    # --- direction 1: plant the violation, observe it fail ------------------------------------
    fn = functools.partial(
        _try_open_and_call_board, f2_dsn, tmp_path, server_args=_STRAY_NOISE_ARGS, label="hygiene-bad"
    )
    outcome, detail = anyio.run(fn)
    print(f"planted run outcome: {outcome} / {detail}")

    poisoned = StdioStreams(
        stdout_path=tmp_path / "hygiene-bad.stdout.raw", stderr_path=tmp_path / "hygiene-bad.stderr.log"
    )
    with pytest.raises(AssertionError) as excinfo:
        poisoned.assert_hygiene(token=TEST_TOKEN)
    observed_failure_text = str(excinfo.value)
    print(f"observed failure text: {observed_failure_text}")
    assert "BOOT NOISE NOT PROTOCOL" in observed_failure_text or "jsonrpc" in observed_failure_text.lower(), (
        f"the failure should point at the stray line, got: {observed_failure_text!r}"
    )

    # --- direction 2: restore the normal invocation, observe it pass --------------------------
    fn2 = functools.partial(_try_open_and_call_board, f2_dsn, tmp_path, server_args=(), label="hygiene-good")
    outcome2, detail2 = anyio.run(fn2)
    assert outcome2 == "ok", f"the unmodified entrypoint must boot cleanly: {detail2}"
    assert detail2 is False, "board must succeed on the clean run"

    clean = StdioStreams(
        stdout_path=tmp_path / "hygiene-good.stdout.raw", stderr_path=tmp_path / "hygiene-good.stderr.log"
    )
    clean.assert_hygiene(token=TEST_TOKEN)  # must not raise
