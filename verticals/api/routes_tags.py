"""Read-only HTTP surface for literal tags and project metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.core import tag_meta

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


@router.get("/api/tags")
def get_tags(request: Request, response: Response) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        tags = tag_meta.list_tags(conn, owner=owner)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"tags": list(tags)}
