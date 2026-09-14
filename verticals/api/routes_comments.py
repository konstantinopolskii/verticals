"""The `/api/comments*` routes (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md, WP-A) —
mirroring `routes_docs.py`'s own conventions line for line: `verify_bearer_token` at the router
level, `owner` always read from `request.app.state.config.owner`, never from the request, and
`X-Query-Count` set from `conn.query_count` on every response.

This module maps; it does not decide — every `ValidationError`/`NotFound` a `core.comments`
call raises propagates straight out of the route body, and `api/errors.py`'s registered
handlers turn it into the right HTTP shape (422, 404) before the caller ever sees it.

**Every write here sets `author='human'`, never a request field** (docs/COMMENTS_SPEC.md
decision 4: "Web writes are `author='human'`, MCP writes are `author='agent'`. Transport decides
authorship; no new auth."). This is the one line in this file that IS a decision rather than a
mapping, and it is the whole reason `CreateCommentRequest`/`AddCommentMessageRequest`
(`api/schemas.py`) carry no `author` field for a caller to set."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.api.schemas import (
    AddCommentMessageRequest,
    CreateCommentRequest,
    ResolveCommentRequest,
    comment_message_to_json,
    comment_thread_to_json,
)
from verticals.core import comments as core_comments

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


# --- read: per-goal, per-doc --------------------------------------------------------------------


@router.get("/api/goals/{id}/comments")
def list_goal_comments(request: Request, response: Response, id: str) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        threads = core_comments.list_for_goal(conn, owner=owner, goal_id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"threads": [comment_thread_to_json(t) for t in threads]}


@router.get("/api/docs/{id}/comments")
def list_doc_comments(request: Request, response: Response, id: str) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        threads = core_comments.list_for_doc(conn, owner=owner, doc_id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"threads": [comment_thread_to_json(t) for t in threads]}


# --- write: create thread, reply, resolve -------------------------------------------------------


@router.post("/api/comments", status_code=201)
def create_comment(request: Request, response: Response, payload: CreateCommentRequest) -> dict:
    """`core.comments.create_thread`'s own refusal covers everything this route does not:
    zero/both of `goal_id`/`doc_id` (422, field `goal_id,doc_id`), an unknown target (404)."""
    owner = request.app.state.config.owner
    anchor = payload.anchor.model_dump() if payload.anchor is not None else None
    with get_conn(request) as conn:
        created = core_comments.create_thread(
            conn,
            owner=owner,
            goal_id=payload.goal_id,
            doc_id=payload.doc_id,
            body=payload.body,
            author="human",
            anchor=anchor,
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    response.headers["Location"] = f"/api/comments/{created.thread.id}"
    return comment_thread_to_json(created.thread)


@router.post("/api/comments/{thread_id}/messages", status_code=201)
def add_comment_message(request: Request, response: Response, thread_id: str, payload: AddCommentMessageRequest) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        added = core_comments.add_message(
            conn, owner=owner, thread_id=thread_id, body=payload.body, author="human"
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return comment_message_to_json(added.message)


@router.post("/api/comments/{thread_id}/resolve")
def resolve_comment(request: Request, response: Response, thread_id: str, payload: ResolveCommentRequest) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        thread = core_comments.set_resolved(
            conn, owner=owner, thread_id=thread_id, resolved=payload.resolved
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return comment_thread_to_json(thread)
