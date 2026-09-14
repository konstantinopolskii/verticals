"""S-60 — The same suite passes over streamable-http, `docs/E2E.md` lines 1436-1440. Real
`--transport http` subprocess, real F2 fixture, no mocks.

S-60's own steps are literally "re-run S-48, S-52, S-54" against a second wire, so this file
re-executes the same tool calls and the same assertions `tests/mcp/test_reads.py::test_s48_*`,
`tests/mcp/test_create.py::test_s52_*` and `tests/mcp/test_mutate.py::test_s54_*` already prove
over stdio, swapping only the transport underneath (`mcp_http_subprocess` +
`open_mcp_http_session` instead of `open_mcp_stdio`). "Identical structured results" is read as
"the same fields hold the same kind of values under the same invariants" rather than byte-
identical response objects — S-52 mints a fresh id on every run regardless of transport, so a
literal diff of two independent runs would never be identical by construction even with a
correct server.

The one check with no stdio equivalent at all: a request carrying no bearer token (or the wrong
one) must be refused by `_BearerAuthMiddleware` (`verticals/mcp/server.py`) before the MCP session
— and therefore any tool call, and therefore any database statement — is ever reached.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import httpx2

from tests.mcp.conftest import (
    TEST_TOKEN,
    full_table_digest,
    mcp_http_subprocess,
    open_mcp_http_session,
)

BOARD_VERTICAL_KEYS = {"maybe", "day", "week", "month", "quarter", "year", "decade", "life"}

# S-52's own literal (test_create.py), duplicated rather than imported across a suite-internal
# module boundary this project does not otherwise cross for test bodies.
_S52_BODY = ("The retro surfaced three carry-forward items. " * 9)[:400]
assert len(_S52_BODY) == 400, len(_S52_BODY)


async def _call(server, name: str, args: dict[str, object]):
    async with open_mcp_http_session(server) as session:
        return await session.call_tool(name, args)


async def _call_twice(server, first: tuple[str, dict], second: tuple[str, dict]):
    """One session, two calls — S-54's own "the refusal did not take the server down" shape."""
    async with open_mcp_http_session(server) as session:
        r1 = await session.call_tool(*first)
        r2 = await session.call_tool(*second)
    return r1, r2


# --- S-48 replayed over http --------------------------------------------------------------------


def test_s60_board_over_http_matches_s48(f2_dsn: str, tmp_path: Path) -> None:
    with mcp_http_subprocess(f2_dsn, tmp_path) as server:
        result = anyio.run(_call, server, "board", {"date": "2026-08-08"})

    assert result.is_error is False
    sc = result.structured_content
    assert sc is not None, "board must return structured content, not text alone"
    columns = sc["columns"]
    keys = {c["vertical"] or "maybe" for c in columns}
    assert keys == BOARD_VERTICAL_KEYS, f"column vertical set mismatch over http: {keys}"

    day_column = next(c for c in columns if c["vertical"] == "day")
    day_ids = {g["id"] for g in day_column["goals"]}
    assert "SYNDAY01" in day_ids, f"SYNDAY01 missing from the day column over http: {day_ids}"

    payload_bytes = len(json.dumps(sc).encode("utf-8"))
    assert payload_bytes < 128 * 1024, f"board payload is {payload_bytes} bytes, over the 128KB budget"


# --- S-52 replayed over http -------------------------------------------------------------------


def test_s60_nested_create_over_http_matches_s52(f2_dsn: str, tmp_path: Path) -> None:
    args = {
        "title": "Retro carry-forward",
        "tags": ["retro"],
        "vertical": "week",
        "anchor_date": "2026-08-10",
        "body": _S52_BODY,
        "children": [
            {
                "title": "Write up the sources",
                "vertical": "day",
                "anchor_date": "2026-08-10",
                "children": [
                    {"title": "Pull the raw notes"},
                    {"title": "Tag the quotes"},
                ],
            },
            {"title": "Fold into tomorrow's plan", "vertical": "day", "anchor_date": "2026-08-10"},
            {"title": "Someday, no promise", "vertical": None},
        ],
    }

    with mcp_http_subprocess(f2_dsn, tmp_path) as server:
        result = anyio.run(_call, server, "create", args)
        board_result = anyio.run(_call, server, "board", {"date": "2026-08-10"})
        search_result = anyio.run(_call, server, "search", {"tag": "retro"})

    assert result.is_error is False, result.content[0].text if result.content else result
    sc = result.structured_content
    root = sc["goal"]
    children = sc["children"]

    assert root["period_key"] == "2026-W33", root["period_key"]
    assert root["origin"] == "agent", root["origin"]
    assert len(children) == 5, f"expected every descendant flattened (5), got {len(children)}: {children}"

    depths = sorted(c["depth"] for c in children)
    assert depths == [1, 1, 1, 2, 2], depths

    null_vertical_children = [c for c in children if c["vertical"] is None and c["depth"] == 1]
    assert len(null_vertical_children) == 1, [c for c in children if c["vertical"] is None]
    leaf = null_vertical_children[0]
    assert leaf["parent_id"] == root["id"]

    maybe_column = next(c for c in board_result.structured_content["columns"] if c["vertical"] is None)
    maybe_ids = {g["id"] for g in maybe_column["goals"]}
    assert leaf["id"] not in maybe_ids, f"{leaf['id']} (vertical:null, has a parent) leaked into Maybe over http: {maybe_ids}"

    assert len(search_result.structured_content["goals"]) == 3, search_result.structured_content["goals"]


# --- S-54 replayed over http -------------------------------------------------------------------


def test_s60_reparent_cycle_refusal_over_http_matches_s54(f2_dsn: str, tmp_path: Path) -> None:
    digest_before = full_table_digest(f2_dsn)

    with mcp_http_subprocess(f2_dsn, tmp_path) as server:
        reparent, board = anyio.run(
            _call_twice,
            server,
            ("reparent", {"id": "SYNLIF01", "parent_id": "SYNSUB01"}),
            ("board", {"date": "2026-08-08"}),
        )

    assert reparent.is_error is True
    text = reparent.content[0].text
    assert len(text) < 200, f"error text must be under 200 characters, got {len(text)}: {text!r}"
    assert "SYNLIF01" in text and "SYNSUB01" in text, f"error text must name both ids: {text!r}"

    assert board.is_error is False, "the server must still answer a call after the refusal, over http"

    digest_after = full_table_digest(f2_dsn)
    assert digest_after == digest_before, "a refused reparent must not change a single row, over http"


# --- bearer auth, http-only --------------------------------------------------------------------


def test_s60_missing_or_wrong_bearer_token_is_refused_before_any_database_statement(
    f2_dsn: str, tmp_path: Path
) -> None:
    digest_before = full_table_digest(f2_dsn)

    with mcp_http_subprocess(f2_dsn, tmp_path) as server:
        init_body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        with httpx2.Client(timeout=5.0) as raw:
            no_auth = raw.post(server.url, json=init_body)
            wrong_auth = raw.post(server.url, json=init_body, headers={"Authorization": "Bearer not-the-real-token"})
        # Positive control, same server, same fixture: proves the middleware is a gate a real
        # token still opens, not a blanket refusal that would make the two checks above vacuous.
        positive = anyio.run(_call, server, "board", {"date": "2026-08-08"})

    assert no_auth.status_code == 401, f"expected 401 with no Authorization header, got {no_auth.status_code}: {no_auth.text}"
    assert wrong_auth.status_code == 401, f"expected 401 with a wrong token, got {wrong_auth.status_code}: {wrong_auth.text}"
    assert "not-the-real-token" not in wrong_auth.text, "the presented (wrong) token must never be echoed back"
    assert TEST_TOKEN not in no_auth.text and TEST_TOKEN not in wrong_auth.text, "the real token must never appear in a 401 body"

    assert positive.is_error is False, "the real token must still work against the same server"

    digest_after = full_table_digest(f2_dsn)
    assert digest_after == digest_before, "a 401 must never reach a database statement"
