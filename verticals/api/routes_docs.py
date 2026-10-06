"""The `/api/docs*` routes (D250, KK 2026-08-20, WP-1) — documents as first-class residents,
mirroring `routes_goals.py`'s own conventions line for line: `verify_bearer_token` at the router
level (checked before any connection is touched), `owner` always read from
`request.app.state.config.owner`, never from the request, and `X-Query-Count` set from
`conn.query_count` on every response.

This module maps; it does not decide — every `ValidationError`/`NotFound`/`RevisionMismatch` a
`core.docs` call raises propagates straight out of the route body, and `api/errors.py`'s
registered handlers turn it into the right HTTP shape (422, 404, 409) before the caller ever sees
it. Nothing here re-checks a bound `core/` already enforces.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.api.schemas import (
    CreateDocRequest,
    RestoreDocRequest,
    SaveDocRequest,
    doc_revision_detail_to_json,
    doc_revision_to_json,
    doc_to_detail,
    doc_to_summary,
)
from verticals.core import docs as core_docs
from verticals.core import docs_desk as core_docs_desk

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


# --- create -----------------------------------------------------------------------------------


@router.post("/api/docs", status_code=201)
def create_doc(request: Request, response: Response, payload: CreateDocRequest) -> dict:
    """A duplicate `(owner, path)` surfaces as `core.docs.create()`'s own `ValidationError`
    naming `path` — a 422, not a silent overwrite and not a 409 (this is not a concurrency
    conflict, there is no prior revision the caller could have raced against)."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        created = core_docs.create(
            conn, owner=owner, path=payload.path, title=payload.title, body=payload.body
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    response.headers["Location"] = f"/api/docs/{created.doc.id}"
    return doc_to_detail(created.doc)


# --- tree (list) --------------------------------------------------------------------------------


@router.get("/api/docs")
def list_docs(request: Request, response: Response) -> dict:
    """The flat, path-ordered list `core.docs.tree()` returns — a client derives its own folder
    grouping from `path`'s own `/` separators (module docstring: no folder table, no server-side
    tree)."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        summaries = core_docs.tree(conn, owner=owner)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"docs": [doc_to_summary(d) for d in summaries]}


@router.get("/api/docs/desk")
def get_docs_desk(request: Request, response: Response) -> dict:
    """The Documents desk (`core/docs_desk.py`): stacks by goal under each value in the board's order, the documents
    no goal holds first, each document with the top of its body for its page. Declared before `/api/docs/{id}` so
    `desk` is never read as an id."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        result = core_docs_desk.desk(conn, owner=owner)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {
        "docs": {
            d.id: {"id": d.id, "path": d.path, "title": d.title, "excerpt": d.excerpt, "created_at": d.created_at,
                   "updated_at": d.updated_at, "revision": d.revision}
            for d in result.docs.values()
        },
        "no_goal": list(result.no_goal),
        "values": [
            {"id": v.id, "title": v.title, "color": v.color,
             "stacks": [{"goal_id": s.goal_id, "goal_title": s.goal_title, "docs": list(s.docs)} for s in v.stacks]}
            for v in result.values
        ],
    }


# --- read one -----------------------------------------------------------------------------------


@router.get("/api/docs/{id}")
def get_doc(request: Request, response: Response, id: str) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        doc = core_docs.get(conn, owner=owner, id=id)
        links = core_docs.links_for_doc(conn, owner=owner, doc_id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return doc_to_detail(doc, links=links)


# --- save (PATCH) -------------------------------------------------------------------------------


@router.patch("/api/docs/{id}")
def save_doc(request: Request, response: Response, id: str, payload: SaveDocRequest) -> dict:
    """`expected_revision` is required on the wire (`SaveDocRequest`'s own field, no default) —
    a `RevisionMismatch` from `core.docs.save()` maps to 409 (`api/errors.py`'s own table),
    carrying the CURRENT revision so the caller re-reads instead of guessing."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        updated = core_docs.save(
            conn,
            owner=owner,
            id=id,
            expected_revision=payload.expected_revision,
            title=payload.title,
            body=payload.body,
            path=payload.path,
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return doc_to_detail(updated.doc)


# --- history -------------------------------------------------------------------------------------


@router.get("/api/docs/{id}/history")
def get_doc_history(request: Request, response: Response, id: str) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        revisions = core_docs.history(conn, owner=owner, id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"revisions": [doc_revision_to_json(r) for r in revisions]}


@router.get("/api/docs/{id}/history/{revision}")
def get_doc_revision(request: Request, response: Response, id: str, revision: int) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        rev = core_docs.get_revision(conn, owner=owner, id=id, revision=revision)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return doc_revision_detail_to_json(rev)


# --- restore -----------------------------------------------------------------------------------


@router.post("/api/docs/{id}/restore")
def restore_doc(request: Request, response: Response, id: str, payload: RestoreDocRequest) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        updated = core_docs.restore(
            conn,
            owner=owner,
            id=id,
            revision=payload.revision,
            expected_revision=payload.expected_revision,
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return doc_to_detail(updated.doc)


# --- delete -----------------------------------------------------------------------------------


@router.delete("/api/docs/{id}", status_code=204)
def delete_doc(request: Request, response: Response, id: str) -> None:
    """Refused with `core.docs.delete()`'s own `ValidationError` (422, naming the linked goal
    ids) while any `goal_doc_links` row still references this doc — a caller removes the link(s)
    first, same as `core.goals.delete()`'s `HasChildren` refusal one route over."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        core_docs.delete(conn, owner=owner, id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return None
