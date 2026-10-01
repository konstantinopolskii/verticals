"""S-57 (cross-transport idempotency and visibility), S-58 (concurrent HTTP+MCP writes), S-59
(capability parity, F5) — `docs/E2E.md` lines 1373-1434. Real MCP stdio session, real
`python -m verticals.api.app` HTTP subprocess, same F2 database underneath both, no mocks.

`verticals/api/**` is WP-15's own territory (read-only reference for this work package): every
HTTP call below goes through its shipped, unmodified entrypoint — `tests/mcp/conftest.py::
api_server` runs it exactly the way `tests/http/conftest.py`'s own `server_factory` already does.
`jsonschema` (used only in this file, for S-59's assertion (a)) is not one of `pyproject.toml`'s
six declared runtime dependencies, but it is not a new risk either: it is `mcp==2.0.0`'s own
transitive dependency (`pip show jsonschema` → `Required-by: mcp`), the exact same standing this
suite's own `conftest.py` already relies on for `httpx2` (also transitive-via-`mcp`, not
separately declared) — see that file's own module docstring for the precedent.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import anyio
import httpx2
import jsonschema
import psycopg
import pytest

from verticals.core import idem as core_idem
from tests.mcp.conftest import (
    TEST_OWNER,
    TEST_TOKEN,
    api_server,
    open_mcp_stdio,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _call(f2_dsn: str, tmp_path: Path, name: str, args: dict[str, object], label: str):
    async with open_mcp_stdio(f2_dsn, tmp_path, label=label) as (session, streams):
        result = await session.call_tool(name, args)
        streams.assert_hygiene(token=TEST_TOKEN)
    return result


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        return count


# =================================================================================================
# S-57 — cross-transport idempotency and cross-transport visibility
# =================================================================================================

_CT_TOKEN = "ct-x-1"
_CT_TITLE = "Cross-transport idempotency probe"


def _resolved_create_payload(owner: str, title: str) -> dict:
    """Mirrors `core/goals.py::create()`'s own payload construction (that function's lines
    ~469-479) for the "title only" call this scenario uses — every other field then takes
    `create()`'s own documented default (`body=""`, not `None` — confirmed by reading the
    signature and `_validate_body`, not assumed), so the resolved payload is fixed and knowable
    without touching `core/` or the database."""
    return {
        "owner": owner,
        "title": title,
        "vertical": None,
        "anchor_date": None,
        "parent_id": None,
        "body": "",
        "color": None,
        "tags": [],
        "children": [],
    }


def _stored_digest(dsn: str, *, owner: str, client_token: str) -> str:
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT request_digest FROM idempotency WHERE owner = %s AND client_token = %s",
            (owner, client_token),
        ).fetchone()
        assert row is not None, f"no idempotency row for owner={owner!r} client_token={client_token!r}"
        return row[0]


def test_s57_cross_transport_idempotency_and_visibility(f2_dsn: str, tmp_path: Path) -> None:
    before = _row_count(f2_dsn)

    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(base_url=api.base_url, headers={"Authorization": f"Bearer {api.token}"}, timeout=10.0) as http:
            # Step 1: POST /api/goals, Idempotency-Key: ct-x-1.
            resp1 = http.post("/api/goals", json={"title": _CT_TITLE}, headers={"Idempotency-Key": _CT_TOKEN})
            assert resp1.status_code == 201, resp1.text
            body1 = resp1.json()
            http_id = body1["id"]
            assert "Idempotent-Replay" not in resp1.headers
            assert body1["origin"] == "human", "created over HTTP must stamp origin human"

            # §10-D8 pre-check, computed and asserted *before* step 2 ever fires (E2E.md's own
            # words: "so the scenario is testing replay and not accidentally testing the
            # normaliser"). `stored` is the real digest step 1 just wrote; `mine` is this test's
            # own independent reconstruction of what step 2's MCP call is about to resolve to. If
            # this suite's understanding of the resolved-payload shape were wrong, this assertion
            # — not a confusing IdempotencyConflict three lines later — is what would say so.
            stored = _stored_digest(f2_dsn, owner=TEST_OWNER, client_token=_CT_TOKEN)
            mine = core_idem.digest(_resolved_create_payload(TEST_OWNER, _CT_TITLE))
            assert mine == stored, (
                f"reconstructed digest does not match the real stored one for step 1's own "
                f"request — got {mine}, stored {stored}"
            )

            # Step 2: MCP create, same client_token, arguments that resolve to the same payload.
            step2 = anyio.run(_call, f2_dsn, tmp_path, "create", {"title": _CT_TITLE, "client_token": _CT_TOKEN}, "s57-2")
            assert step2.is_error is False, step2.content[0].text if step2.content else step2
            sc2 = step2.structured_content
            assert sc2["replayed"] is True, f"step 2 must be a replay of step 1's own row: {sc2}"
            assert sc2["goal"]["id"] == http_id, "a replay must hand back the HTTP-created row's own id, not mint a new one"

            after_step2 = _row_count(f2_dsn)
            assert after_step2 - before == 1, f"expected +1 total (not +2) across both transports, got +{after_step2 - before}"

            # Step 3: MCP update on the row HTTP created.
            step3 = anyio.run(_call, f2_dsn, tmp_path, "update", {"id": http_id, "body": "touched over mcp"}, "s57-3")
            assert step3.is_error is False, step3.content[0].text if step3.content else step3

            # Step 4: GET /api/goals/{id}.
            resp4 = http.get(f"/api/goals/{http_id}")
            assert resp4.status_code == 200, resp4.text
            body4 = resp4.json()
            assert body4["body"] == "touched over mcp", "HTTP read must reflect the MCP write"
            assert body4["origin"] == "human", (
                "origin records who created the row (over HTTP), never who wrote it last "
                f"(§10-D4) — got {body4['origin']!r}"
            )


# =================================================================================================
# S-58 — concurrent writes from HTTP and MCP to the same goal
# =================================================================================================

_ITERATIONS = 200
_TARGET_ID = "SYNQ1R01"


def _structural_snapshot(dsn: str, goal_id: str) -> tuple:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(
            "SELECT path, depth, parent_id, position FROM goals WHERE id = %s", (goal_id,)
        ).fetchone()


def _deadlocks(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (value,) = conn.execute("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()").fetchone()
        return value


def _title(dsn: str, goal_id: str) -> str:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (value,) = conn.execute("SELECT title FROM goals WHERE id = %s", (goal_id,)).fetchone()
        return value


def _http_worker(
    base_url: str, token: str, barrier: threading.Barrier, results: list[int], errors: list[BaseException]
) -> None:
    try:
        with httpx2.Client(base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0) as client:
            barrier.wait(timeout=30)
            for i in range(_ITERATIONS):
                resp = client.patch(f"/api/goals/{_TARGET_ID}", json={"title": f"H{i}"})
                results.append(resp.status_code)
    except BaseException as exc:  # a worker thread's own exception must reach the joining thread, never vanish silently
        errors.append(exc)


def _mcp_worker(
    f2_dsn: str, tmp_path: Path, barrier: threading.Barrier, results: list[bool], errors: list[BaseException]
) -> None:
    async def _run() -> None:
        async with open_mcp_stdio(f2_dsn, tmp_path, label="s58-mcp") as (session, streams):
            barrier.wait(timeout=30)
            for i in range(_ITERATIONS):
                result = await session.call_tool("update", {"id": _TARGET_ID, "title": f"M{i}"})
                results.append(result.is_error)
            streams.assert_hygiene(token=TEST_TOKEN)

    try:
        anyio.run(_run)
    except BaseException as exc:
        errors.append(exc)


def test_s58_concurrent_http_and_mcp_writes_to_the_same_goal(f2_dsn: str, tmp_path: Path) -> None:
    with api_server(f2_dsn, tmp_path) as api:
        before_struct = _structural_snapshot(f2_dsn, _TARGET_ID)
        before_deadlocks = _deadlocks(f2_dsn)

        barrier = threading.Barrier(2)
        http_results: list[int] = []
        mcp_results: list[bool] = []
        errors: list[BaseException] = []

        http_thread = threading.Thread(target=_http_worker, args=(api.base_url, api.token, barrier, http_results, errors))
        mcp_thread = threading.Thread(target=_mcp_worker, args=(f2_dsn, tmp_path, barrier, mcp_results, errors))

        # A third, independent connection samples `updated_at` from the main thread while both
        # workers hammer the row — "monotonically non-decreasing across a sampled read stream" is
        # a claim about what a concurrent *reader* observes, so this has to be a real reader
        # running concurrently with the writers, not a before/after pair.
        sampler = psycopg.connect(f2_dsn, autocommit=True)
        samples: list = []
        start = time.monotonic()
        http_thread.start()
        mcp_thread.start()
        try:
            while http_thread.is_alive() or mcp_thread.is_alive():
                (value,) = sampler.execute("SELECT updated_at FROM goals WHERE id = %s", (_TARGET_ID,)).fetchone()
                samples.append(value)
                time.sleep(0.02)
        finally:
            http_thread.join()
            mcp_thread.join()
            sampler.close()
        elapsed = time.monotonic() - start

        after_struct = _structural_snapshot(f2_dsn, _TARGET_ID)
        after_deadlocks = _deadlocks(f2_dsn)
        final_title = _title(f2_dsn, _TARGET_ID)

    assert not errors, f"a worker thread raised: {errors!r}"
    assert len(http_results) == _ITERATIONS, f"HTTP thread only completed {len(http_results)}/{_ITERATIONS}"
    assert len(mcp_results) == _ITERATIONS, f"MCP thread only completed {len(mcp_results)}/{_ITERATIONS}"

    bad_http = [c for c in http_results if c >= 500]
    assert not bad_http, f"HTTP 5xx returned during concurrent writes: {bad_http}"
    assert not any(mcp_results), "an MCP call returned isError:true during concurrent writes"

    assert after_deadlocks - before_deadlocks == 0, f"pg_stat_database.deadlocks moved: {before_deadlocks} -> {after_deadlocks}"

    assert final_title in (f"H{_ITERATIONS - 1}", f"M{_ITERATIONS - 1}"), (
        f"final title must be the last write of one of the two threads, got {final_title!r}"
    )

    assert samples == sorted(samples), (
        f"updated_at went backwards somewhere in the sampled stream: {samples}"
    )

    assert after_struct == before_struct, f"path/depth/parent_id/position must be untouched by a title-only patch: {before_struct} -> {after_struct}"

    assert elapsed < 20.0, f"{_ITERATIONS}+{_ITERATIONS} concurrent writes took {elapsed:.1f}s, over the 20s budget"


# =================================================================================================
# D108 — schedule cascade result parity
# =================================================================================================


def test_schedule_descendants_clamped_has_cross_transport_parity(
    f2_dsn: str, tmp_path: Path,
) -> None:
    def create_chain(http: httpx2.Client, label: str) -> tuple[str, str]:
        parent = http.post(
            "/api/goals",
            json={
                "title": f"{label} parent",
                "vertical": "week",
                "anchor_date": "2026-08-08",
            },
        )
        assert parent.status_code == 201, parent.text
        parent_id = parent.json()["id"]
        child = http.post(
            "/api/goals",
            json={
                "title": f"{label} child",
                "parent_id": parent_id,
                "vertical": "week",
                "anchor_date": "2026-08-08",
            },
        )
        assert child.status_code == 201, child.text
        return parent_id, child.json()["id"]

    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(
            base_url=api.base_url,
            headers={"Authorization": f"Bearer {api.token}"},
            timeout=10.0,
        ) as http:
            http_parent, _ = create_chain(http, "HTTP cascade parity")
            mcp_parent, _ = create_chain(http, "MCP cascade parity")

            http_down = http.put(
                f"/api/goals/{http_parent}/schedule",
                json={"vertical": "day", "anchor_date": "2026-08-08"},
            )
            assert http_down.status_code == 200, http_down.text
            mcp_down = anyio.run(
                _call,
                f2_dsn,
                tmp_path,
                "schedule",
                {"id": mcp_parent, "vertical": "day", "anchor_date": "2026-08-08"},
                "schedule-parity-down",
            )
            assert mcp_down.is_error is False
            assert http_down.json()["descendants_clamped"] == 1
            assert mcp_down.structured_content["descendants_clamped"] == 1
            assert http_down.json()["vertical"] == mcp_down.structured_content["goal"]["vertical"]

            http_up = http.put(
                f"/api/goals/{http_parent}/schedule",
                json={"vertical": "week", "anchor_date": "2026-08-08"},
            )
            assert http_up.status_code == 200, http_up.text
            mcp_up = anyio.run(
                _call,
                f2_dsn,
                tmp_path,
                "schedule",
                {"id": mcp_parent, "vertical": "week", "anchor_date": "2026-08-08"},
                "schedule-parity-up",
            )
            assert mcp_up.is_error is False
            # D109: the child was clamped onto the parent's day card, so it is old-group family
            # now and travels back UP with the parent — the count reports it on both transports.
            assert http_up.json()["descendants_clamped"] == 1
            assert mcp_up.structured_content["descendants_clamped"] == 1


# =================================================================================================
# S-59 — capability parity (F5)
# =================================================================================================

_F5_PATH = REPO_ROOT / "tests" / "fixtures" / "capabilities.json"

# §4's own route table (docs/E2E.md lines 907-918), transcribed once here as the second half of
# assertion (b) — query strings stripped, matching how a path *template* is compared (openapi.json
# itself never carries a query string in a path key; `?cascade=true` is a `parameters` entry, not
# part of the path).
_E2E_SECTION_4_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/board"),
    ("GET", "/api/search"),
    ("GET", "/api/tags"),
    ("POST", "/api/goals"),
    ("GET", "/api/goals/{id}"),
    ("PATCH", "/api/goals/{id}"),
    ("PATCH", "/api/goals"),
    ("PUT", "/api/goals/{id}/schedule"),
    ("PUT", "/api/goals/{id}/parent"),
    ("POST", "/api/goals/{id}/park"),
    ("POST", "/api/goals/{id}/due_ack"),
    ("DELETE", "/api/goals/{id}"),
    # D250 WP-1's `/api/docs*` routes (`verticals/api/routes_docs.py`) — §4 itself predates WP-1
    # and has not been re-transcribed here yet (docs/E2E.md is outside WP-2's own file scope);
    # only the four mutating routes WP-2's manifest rows below actually need are added, so
    # assertion (b) still holds for every row this suite adds.
    ("POST", "/api/docs"),
    ("PATCH", "/api/docs/{id}"),
    ("POST", "/api/docs/{id}/restore"),
    ("DELETE", "/api/docs/{id}"),
    # WP-A (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md)'s `/api/comments*` routes
    # (`verticals/api/routes_comments.py`) — same "not in §4, added here for this suite's own
    # need" carve-out the docs routes above already took.
    ("POST", "/api/comments"),
    ("POST", "/api/comments/{thread_id}/messages"),
    ("POST", "/api/comments/{thread_id}/resolve"),
}

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# The four board-shaped read tools of S-47, plus WP-33's `evidence_due` — a keyset-paginated
# read (worklist), writes nothing (tests/mcp/test_evidence_tools.py exercises it as such).
# D250 WP-2 adds the document family's own four reads (`verticals/mcp/docs.py`) — `doc_get`,
# `doc_tree`, `doc_history`, `doc_revision` write nothing, same reasoning.
# WP-A adds `comments` (`verticals/mcp/comments.py`) — the worklist/scoped-list read, writes
# nothing, same reasoning as every other read tool in this set.
_READ_TOOLS = {"board", "goal", "outline", "search", "evidence_due", "tags", "doc_get", "doc_tree", "doc_history", "doc_revision", "comments"}
# WP-33's deliberate single-surface write (docs/EVIDENCE.md §6/§9, verticals/mcp/evidence.py's
# module note): evidence is written by the agent over MCP only — the UI reads evidence off the
# board payload (`board_to_json`'s `evidence` map, already on HTTP) and never writes it, so
# there is no HTTP write route and no F5 capability row (F5's `ui_selector` column has nothing
# to name). A second entry here without a spec section like §6 backing it should be treated as
# suspicious — this set exists for capabilities that are agent tooling, not user capabilities.
_AGENT_ONLY_TOOLS = {"evidence_update", "tag_mark", "size_report"}
# The mirror image on HTTP (docs/design-handoff S4.P1.017): the app's own daily carry-over into
# the Replan task. The app calls it on start and when its day turns; nobody asks for it, so it is
# housekeeping, not a capability, and the task it writes is a usual goal both surfaces read.
_APP_ONLY_ROUTES = {("POST", "/api/replan")}

# capabilities.json's `mcp_args` values are placeholders (`"<title>"`, `"<id>"`, ...), not literal
# values a real caller would send — most placeholders are plain strings and validate as-is against
# a bare `{"type": "string"}` property, but `vertical` and `color` are closed `enum`s in the real
# schema (`tools.py::_VERTICAL_ENUM`/`_COLOR_ENUM`) and a literal `"<vertical>"` is not a member of
# either enum. Substituting one real, valid representative value per placeholder token is what
# makes assertion (a) test the honest claim — "a real call shaped like this row would be accepted"
# — instead of either rejecting three of sixteen rows for a fixture-authoring convention, or
# loosening the check until it stops meaning anything.
_PLACEHOLDER_VALUES = {
    "<title>": "Capability parity probe",
    "<id>": "SYNQ1R01",
    "<parent_id>": "SYNLIF01",
    "<after_id>": "SYNORD01",
    "<vertical>": "week",
    "<anchor_date>": "2026-08-10",
    "<color>": "#278dea",
    "<tag>": "probe",
    "<body>": "probe body",
    "<date>": "2026-08-10",
    # D254: `doc_link`/`doc_unlink`'s `doc` argument accepts an id or a path — either substitutes
    # cleanly against the plain-string schema property, no enum involved.
    "<doc>": "strategy/capability-probe.md",
    # WP-A: `comment_add`'s reply mode and `comment_resolve` both key off `thread_id` — a plain
    # string property, no enum, so any representative 8-char value substitutes cleanly.
    "<thread_id>": "cmtThrd1",
}


def _substitute(value: object) -> object:
    if isinstance(value, str):
        return _PLACEHOLDER_VALUES.get(value, value)
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    return value


def _strip_query(path: str) -> str:
    return path.split("?", 1)[0]


def _manifest_route(row: dict) -> tuple[str, str]:
    return (row["http_method"].upper(), _strip_query(row["http_path"]))


async def _tools_list(f2_dsn: str, tmp_path: Path):
    async with open_mcp_stdio(f2_dsn, tmp_path, label="s59-tools") as (session, streams):
        result = await session.list_tools()
        streams.assert_hygiene(token=TEST_TOKEN)
        return result.tools


def test_s59_capability_parity_holds_in_both_directions(f2_dsn: str, tmp_path: Path) -> None:
    # Step 1: read capabilities.json by reading the file (S-118's own house rule against a copy
    # held in the test) — `tests/fixtures/capabilities.json`. D250 WP-2 adds the four mutating
    # document capabilities (create_doc/save_doc/restore_doc/delete_doc), 20 -> 24 rows. D254
    # adds link_doc/unlink_doc — MCP-only conveniences over the SAME existing HTTP capability
    # (`PATCH /api/goals/{id}`, the goal-body write `doc_link`/`doc_unlink` perform under the
    # hood) rather than a new HTTP route of their own — 24 -> 26 rows. WP-A adds
    # create_comment/reply_comment/resolve_comment (`verticals/mcp/comments.py`,
    # `verticals/api/routes_comments.py`) — 26 -> 29 rows; `ui_selector: null` on all three, same
    # as every doc row above, because WP-B's own UI has not landed yet (out of this WP's scope).
    manifest = json.loads(_F5_PATH.read_text())
    assert len(manifest) == 29, f"F5 should carry 29 rows, found {len(manifest)}"
    park_rows = [row for row in manifest if row["cap"] == "park"]
    # "Remove from vertical" left the goal's menu with its systematic order (docs/design-handoff S5.P5.007): park is
    # HTTP/MCP only now, the same shape as every other null-selector row.
    assert park_rows == [{
        "cap": "park",
        "ui_selector": None,
        "http_method": "POST",
        "http_path": "/api/goals/{id}/park",
        "mcp_tool": "park",
        "mcp_args": {"id": "<id>"},
    }], "F5's new row must be the two-transport park capability"

    # Step 2: tools/list over MCP.
    tools = anyio.run(_tools_list, f2_dsn, tmp_path)
    tool_schemas = {t.name: t.input_schema for t in tools}
    all_tool_names = set(tool_schemas)

    # Step 3: GET /openapi.json.
    with api_server(f2_dsn, tmp_path) as api:
        with httpx2.Client(timeout=10.0) as http:
            resp = http.get(f"{api.base_url}/openapi.json")
    assert resp.status_code == 200, resp.text
    openapi = resp.json()
    openapi_routes: set[tuple[str, str]] = {
        (method.upper(), path) for path, methods in openapi.get("paths", {}).items() for method in methods
    }
    assert ("POST", "/api/goals/{id}/park") in openapi_routes
    assert "park" in tool_schemas

    # Step 4a / assertion (a): every row's mcp_tool is real, and (placeholders substituted with
    # one representative real value each) its mcp_args validates against that tool's own schema.
    for row in manifest:
        tool_name = row["mcp_tool"]
        assert tool_name in tool_schemas, f"{row['cap']}: mcp_tool {tool_name!r} not in tools/list {sorted(all_tool_names)}"
        real_args = _substitute(row["mcp_args"])
        try:
            jsonschema.validate(instance=real_args, schema=tool_schemas[tool_name])
        except jsonschema.ValidationError as exc:
            pytest.fail(f"{row['cap']}: substituted mcp_args {real_args} fails {tool_name}'s schema: {exc.message}")

    # Assertion (b): every row's (http_method, http_path) exists in openapi.json and in §4.
    for row in manifest:
        route = _manifest_route(row)
        assert route in openapi_routes, f"{row['cap']}: {route} missing from the live openapi.json ({sorted(openapi_routes)})"
        assert route in _E2E_SECTION_4_ROUTES, f"{row['cap']}: {route} missing from §4's own route table"

    # Assertion (c), the reverse direction: every mutating route in openapi.json and every
    # mutating tool in tools/list is reachable from at least one manifest row — "a capability
    # shipped on one surface and not the other fails this scenario."
    manifest_routes = {_manifest_route(row) for row in manifest}
    mutating_openapi_routes = {(m, p) for m, p in openapi_routes if m in _MUTATING_METHODS and p.startswith("/api/")}
    missing_routes = mutating_openapi_routes - manifest_routes - _APP_ONLY_ROUTES
    assert not missing_routes, f"mutating route(s) with no manifest row at all: {missing_routes}"
    assert _APP_ONLY_ROUTES <= mutating_openapi_routes, f"stale app-only carve-out: {_APP_ONLY_ROUTES - mutating_openapi_routes}"

    manifest_tools = {row["mcp_tool"] for row in manifest}
    mutating_tools = all_tool_names - _READ_TOOLS
    # `_AGENT_ONLY_TOOLS` is the one sanctioned exemption from two-surface parity — see its
    # own comment above; everything else mutating must appear in F5.
    missing_tools = mutating_tools - manifest_tools - _AGENT_ONLY_TOOLS
    assert not missing_tools, f"mutating tool(s) with no manifest row at all: {missing_tools}"
    # The carve-out may only ever exempt tools that really exist and really are mutating —
    # a stale entry here (tool renamed or turned into a read) fails loudly, not silently.
    assert _AGENT_ONLY_TOOLS <= mutating_tools, f"stale agent-only carve-out: {_AGENT_ONLY_TOOLS - mutating_tools}"

    # Self-check on this file's own hardcoded read-tool set, so a twelfth tool added later fails
    # loudly here instead of silently inflating "mutating_tools" with something unreviewed.
    assert all_tool_names == _READ_TOOLS | mutating_tools
