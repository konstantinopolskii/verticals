"""WP-A (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md) — the `/api/comments*` and
`/api/{goals,docs}/{id}/comments` routes end to end: a real uvicorn subprocess, real TCP
sockets, no mocks (same house rule `tests/http/test_docs.py` states).

Every write here must land `author: "human"` — there is no `author` field on the wire at all
(`api/schemas.py::CreateCommentRequest`/`AddCommentMessageRequest` carry none, and `extra=
"forbid"` refuses one a caller tries to add), so `test_author_field_is_refused_and_ignored`
below is the one scenario that proves the transport, not the caller, decides authorship.
"""

from __future__ import annotations

import httpx


def _create_goal(client: httpx.Client, *, title: str = "Has comments") -> dict:
    resp = client.post("/api/goals", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_doc(client: httpx.Client, *, path: str = "commented.md") -> dict:
    resp = client.post("/api/docs", json={"path": path, "title": "t", "body": ""})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- create + list, both target kinds ------------------------------------------------------------


def test_create_comment_on_goal_and_list_it(client: httpx.Client) -> None:
    goal = _create_goal(client)
    resp = client.post("/api/comments", json={"goal_id": goal["id"], "body": "left a note"})
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["goal_id"] == goal["id"]
    assert thread["doc_id"] is None
    assert thread["anchor"] is None
    assert thread["resolved_at"] is None
    assert len(thread["messages"]) == 1
    assert thread["messages"][0]["author"] == "human"
    assert thread["messages"][0]["body"] == "left a note"
    assert resp.headers["Location"] == f"/api/comments/{thread['id']}"

    listed = client.get(f"/api/goals/{goal['id']}/comments")
    assert listed.status_code == 200
    assert listed.json() == {"threads": [thread]}


def test_create_comment_on_doc_and_list_it(client: httpx.Client) -> None:
    doc = _create_doc(client)
    resp = client.post("/api/comments", json={"doc_id": doc["id"], "body": "doc note"})
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["doc_id"] == doc["id"] and thread["goal_id"] is None

    listed = client.get(f"/api/docs/{doc['id']}/comments")
    assert listed.status_code == 200
    assert listed.json() == {"threads": [thread]}


def test_create_comment_with_anchor_round_trips(client: httpx.Client) -> None:
    goal = _create_goal(client)
    resp = client.post(
        "/api/comments",
        json={
            "goal_id": goal["id"], "body": "about this bit",
            "anchor": {"quote": "the important text", "prefix": "before ", "suffix": " after"},
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["anchor"] == {"quote": "the important text", "prefix": "before ", "suffix": " after"}


# --- one-target rule, unknown target ---------------------------------------------------------------


def test_create_comment_requires_exactly_one_target(client: httpx.Client) -> None:
    goal = _create_goal(client)
    doc = _create_doc(client)
    neither = client.post("/api/comments", json={"body": "x"})
    assert neither.status_code == 422
    assert neither.json()["detail"][0]["field"] == "goal_id,doc_id"

    both = client.post("/api/comments", json={"goal_id": goal["id"], "doc_id": doc["id"], "body": "x"})
    assert both.status_code == 422
    assert both.json()["detail"][0]["field"] == "goal_id,doc_id"


def test_create_comment_unknown_goal_is_404(client: httpx.Client) -> None:
    resp = client.post("/api/comments", json={"goal_id": "ZZZZZZZZ", "body": "x"})
    assert resp.status_code == 404
    assert resp.json() == {"error": "not_found"}


def test_list_goal_comments_unknown_goal_is_404(client: httpx.Client) -> None:
    resp = client.get("/api/goals/ZZZZZZZZ/comments")
    assert resp.status_code == 404


def test_create_comment_rejects_unknown_field(client: httpx.Client) -> None:
    goal = _create_goal(client)
    resp = client.post("/api/comments", json={"goal_id": goal["id"], "body": "x", "nonsense": 1})
    assert resp.status_code == 422


def test_author_field_is_refused_and_ignored(client: httpx.Client) -> None:
    """There is no `author` field on the wire — a caller trying to set one is a 422
    (`extra="forbid"`), never a silently-accepted-and-ignored value and never a way to write
    `author='agent'` from the web (docs/COMMENTS_SPEC.md decision 4)."""
    goal = _create_goal(client)
    resp = client.post("/api/comments", json={"goal_id": goal["id"], "body": "x", "author": "agent"})
    assert resp.status_code == 422


# --- add message ---------------------------------------------------------------------------------


def test_add_message_appears_in_the_thread(client: httpx.Client) -> None:
    goal = _create_goal(client)
    created = client.post("/api/comments", json={"goal_id": goal["id"], "body": "first"}).json()

    resp = client.post(f"/api/comments/{created['id']}/messages", json={"body": "second"})
    assert resp.status_code == 201, resp.text
    message = resp.json()
    assert message["author"] == "human"
    assert message["body"] == "second"

    listed = client.get(f"/api/goals/{goal['id']}/comments").json()["threads"][0]
    assert [m["body"] for m in listed["messages"]] == ["first", "second"]


def test_add_message_unknown_thread_is_404(client: httpx.Client) -> None:
    resp = client.post("/api/comments/ZZZZZZZZ/messages", json={"body": "x"})
    assert resp.status_code == 404


def test_add_message_blank_body_is_422(client: httpx.Client) -> None:
    goal = _create_goal(client)
    created = client.post("/api/comments", json={"goal_id": goal["id"], "body": "first"}).json()
    resp = client.post(f"/api/comments/{created['id']}/messages", json={"body": "   "})
    assert resp.status_code == 422


# --- resolve / unresolve -------------------------------------------------------------------------


def test_resolve_and_unresolve_round_trip(client: httpx.Client) -> None:
    goal = _create_goal(client)
    created = client.post("/api/comments", json={"goal_id": goal["id"], "body": "x"}).json()

    resolved = client.post(f"/api/comments/{created['id']}/resolve", json={"resolved": True})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolved_at"] is not None

    reopened = client.post(f"/api/comments/{created['id']}/resolve", json={"resolved": False})
    assert reopened.status_code == 200
    assert reopened.json()["resolved_at"] is None


def test_resolve_unknown_thread_is_404(client: httpx.Client) -> None:
    resp = client.post("/api/comments/ZZZZZZZZ/resolve", json={"resolved": True})
    assert resp.status_code == 404


# --- auth refusal --------------------------------------------------------------------------------


def test_comments_routes_refuse_without_a_bearer_token(server) -> None:
    """Byte-for-byte `tests/http/test_docs.py::test_docs_routes_refuse_without_a_bearer_token`'s
    own steps and 30s transport-budget reasoning (D93), applied to a comments route — a real,
    existing GET endpoint, same as that scenario's own `anon.get("/api/docs")`."""
    with httpx.Client(base_url=server.base_url, timeout=30.0) as anon:
        no_header = anon.get("/api/goals/ZZZZZZZZ/comments")
        wrong_token = anon.get(
            "/api/goals/ZZZZZZZZ/comments", headers={"Authorization": "Bearer wrong-value"}
        )
        correct = anon.get(
            "/api/goals/ZZZZZZZZ/comments", headers={"Authorization": f"Bearer {server.token}"}
        )
    # `correct` reaches core with a valid token — ZZZZZZZZ is not a real goal, so 404, not 401;
    # the point of this branch is that authentication passed and a DIFFERENT refusal took over.
    assert (no_header.status_code, wrong_token.status_code, correct.status_code) == (401, 401, 404)
