"""Privacy mode for the app: the covered ids to blur, and the mode switch behind the hotkey."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.core import privacy

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


class PrivacyModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: StrictBool


@router.get("/api/privacy")
def get_privacy(request: Request, response: Response) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        result = privacy.view(conn, owner=owner)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return result


@router.put("/api/privacy")
def put_privacy(request: Request, body: PrivacyModeBody) -> dict:
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        privacy.set_mode(conn, owner=owner, mode=body.mode)
        return privacy.view(conn, owner=owner)
