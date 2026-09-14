"""D250 (KK, 2026-08-20), WP-1 — the `/api/docs*` routes end to end: a real uvicorn subprocess,
real TCP sockets, no mocks (same house rule every other file in this suite states). Auth
refusal, the revision-conflict status code, and the goal detail's `docs` field.

D251 (KK, 2026-08-20) widened that `docs` field: every entry now carries `inherited_from`
(`null` for a doc the goal links directly, `{id, title}` for one "ghosted" down from an
ancestor's own link) — `test_goal_detail_carries_linked_docs` is updated for the new key
(sanctioned test edit, same shape D250's own tests took when a field was added), and
`test_goal_detail_carries_inherited_docs_from_an_ancestor` below is the new scenario.
"""

from __future__ import annotations

import httpx


def _create(client: httpx.Client, *, path: str, title: str | None = "t", body: str = "") -> dict:
    resp = client.post("/api/docs", json={"path": path, "title": title, "body": body})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- create, read, tree --------------------------------------------------------------------------


def test_create_and_get_doc(client: httpx.Client) -> None:
    created = _create(client, path="strategy/ai-native.md", title="AI-native", body="hello world")
    assert created["path"] == "strategy/ai-native.md"
    assert created["title"] == "AI-native"
    assert created["body"] == "hello world"
    assert created["revision"] == 1
    assert created["linked_goals"] == []

    got = client.get(f"/api/docs/{created['id']}")
    assert got.status_code == 200
    assert got.json() == created


def test_create_duplicate_path_is_422(client: httpx.Client) -> None:
    _create(client, path="dup.md")
    resp = client.post("/api/docs", json={"path": "dup.md", "title": "again", "body": ""})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "path"


def test_create_rejects_unknown_field(client: httpx.Client) -> None:
    resp = client.post("/api/docs", json={"path": "a.md", "title": "t", "body": "", "nonsense": 1})
    assert resp.status_code == 422


def test_create_rejects_a_path_with_no_md_extension(client: httpx.Client) -> None:
    resp = client.post("/api/docs", json={"path": "no-extension", "title": "t", "body": ""})
    assert resp.status_code == 422


def test_get_unknown_doc_is_404(client: httpx.Client) -> None:
    resp = client.get("/api/docs/ZZZZZZZZ")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not_found"}


def test_list_docs_is_the_flat_path_ordered_tree(client: httpx.Client) -> None:
    _create(client, path="z-last.md")
    _create(client, path="a-first.md")
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    body = resp.json()
    paths = [d["path"] for d in body["docs"]]
    assert paths == sorted(paths)
    assert "a-first.md" in paths and "z-last.md" in paths
    for entry in body["docs"]:
        assert "body" not in entry, "the tree listing must never carry body (S-33's own law, mirrored)"


# --- save: revision conflict, success ------------------------------------------------------------


def test_save_updates_and_bumps_revision(client: httpx.Client) -> None:
    created = _create(client, path="edit-me.md", body="v1")
    resp = client.patch(
        f"/api/docs/{created['id']}", json={"expected_revision": 1, "body": "v2"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == 2
    assert body["body"] == "v2"
    assert body["title"] == created["title"], "omitted field stays unchanged"


def test_save_stale_revision_is_409(client: httpx.Client) -> None:
    created = _create(client, path="conflict.md", body="v1")
    first = client.patch(f"/api/docs/{created['id']}", json={"expected_revision": 1, "body": "v2"})
    assert first.status_code == 200

    stale = client.patch(f"/api/docs/{created['id']}", json={"expected_revision": 1, "body": "v3"})
    assert stale.status_code == 409
    body = stale.json()
    assert body["error"] == "revision_mismatch"
    assert body["detail"]["revision"] == 2


def test_save_missing_expected_revision_is_422(client: httpx.Client) -> None:
    created = _create(client, path="needs-rev.md")
    resp = client.patch(f"/api/docs/{created['id']}", json={"body": "no revision sent"})
    assert resp.status_code == 422


# --- history / revision read ----------------------------------------------------------------------


def test_history_and_revision_endpoints(client: httpx.Client) -> None:
    created = _create(client, path="hist.md", body="v1")
    client.patch(f"/api/docs/{created['id']}", json={"expected_revision": 1, "body": "v2"})

    history = client.get(f"/api/docs/{created['id']}/history")
    assert history.status_code == 200
    revisions = history.json()["revisions"]
    assert [r["revision"] for r in revisions] == [1, 2]
    assert all("body" not in r for r in revisions)

    rev1 = client.get(f"/api/docs/{created['id']}/history/1")
    assert rev1.status_code == 200
    assert rev1.json()["body"] == "v1"

    missing = client.get(f"/api/docs/{created['id']}/history/99")
    assert missing.status_code == 404


# --- restore -----------------------------------------------------------------------------------


def test_restore_creates_a_new_revision_with_old_text(client: httpx.Client) -> None:
    created = _create(client, path="restore-me.md", body="v1")
    client.patch(f"/api/docs/{created['id']}", json={"expected_revision": 1, "body": "v2"})

    resp = client.post(
        f"/api/docs/{created['id']}/restore", json={"revision": 1, "expected_revision": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == 3
    assert body["body"] == "v1"


# --- delete ------------------------------------------------------------------------------------


def test_delete_refused_while_linked_then_allowed(client: httpx.Client) -> None:
    doc = _create(client, path="linked-http.md")
    goal_resp = client.post("/api/goals", json={"title": "Linker"})
    assert goal_resp.status_code == 201
    goal_id = goal_resp.json()["id"]

    patched = client.patch(f"/api/goals/{goal_id}", json={"body": f"[see](doc:{doc['path']})"})
    assert patched.status_code == 200

    refused = client.delete(f"/api/docs/{doc['id']}")
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["linked_goal_ids"] == [goal_id]

    client.patch(f"/api/goals/{goal_id}", json={"body": "no link anymore"})
    allowed = client.delete(f"/api/docs/{doc['id']}")
    assert allowed.status_code == 204

    assert client.get(f"/api/docs/{doc['id']}").status_code == 404


def test_delete_unknown_doc_is_404(client: httpx.Client) -> None:
    resp = client.delete("/api/docs/ZZZZZZZZ")
    assert resp.status_code == 404


# --- goal detail carries linked docs --------------------------------------------------------------


def test_goal_detail_carries_linked_docs(client: httpx.Client) -> None:
    doc = _create(client, path="from-doc-side.md", body="")
    goal_resp = client.post("/api/goals", json={"title": "Has docs"})
    goal_id = goal_resp.json()["id"]

    client.patch(f"/api/goals/{goal_id}", json={"body": f"[link](doc:{doc['path']})"})
    detail = client.get(f"/api/goals/{goal_id}")
    assert detail.status_code == 200
    docs_field = detail.json()["docs"]
    assert docs_field == [
        {
            "id": doc["id"], "path": doc["path"], "title": doc["title"], "source": "goal",
            "inherited_from": None,
        }
    ]

    # the doc's own body linking the goal shows up as the OTHER source, both listed
    client.patch(f"/api/docs/{doc['id']}", json={"expected_revision": 1, "body": f"[g](goal:{goal_id})"})
    detail2 = client.get(f"/api/goals/{goal_id}")
    sources = {d["source"] for d in detail2.json()["docs"]}
    assert sources == {"doc", "goal"}
    assert all(d["inherited_from"] is None for d in detail2.json()["docs"])


# --- D251: docs "ghost" down from an ancestor's own link -------------------------------------


def test_goal_detail_carries_inherited_docs_from_an_ancestor(client: httpx.Client) -> None:
    doc = _create(client, path="inherited-http.md", body="")
    parent_resp = client.post("/api/goals", json={"title": "Inherit Parent"})
    parent_id = parent_resp.json()["id"]
    client.patch(f"/api/goals/{parent_id}", json={"body": f"[link](doc:{doc['path']})"})

    child_resp = client.post("/api/goals", json={"title": "Inherit Child", "parent_id": parent_id})
    child_id = child_resp.json()["id"]

    detail = client.get(f"/api/goals/{child_id}")
    assert detail.status_code == 200
    assert detail.json()["docs"] == [
        {
            "id": doc["id"], "path": doc["path"], "title": doc["title"], "source": "goal",
            "inherited_from": {"id": parent_id, "title": "Inherit Parent"},
        }
    ]

    # own wins: once the child links the same doc directly, the ghost disappears — one entry,
    # not two, and it is no longer inherited.
    client.patch(f"/api/goals/{child_id}", json={"body": f"[own](doc:{doc['path']})"})
    detail2 = client.get(f"/api/goals/{child_id}")
    assert detail2.json()["docs"] == [
        {
            "id": doc["id"], "path": doc["path"], "title": doc["title"], "source": "goal",
            "inherited_from": None,
        }
    ]


# --- auth refusal --------------------------------------------------------------------------------


def test_docs_routes_refuse_without_a_bearer_token(server) -> None:
    # 30 s, not 10 — the same transport-budget reasoning `tests/http/conftest.py`'s own `client`
    # fixture states (D93): S-112 runs this whole suite a second time INSIDE the first, so this
    # scenario can execute under roughly double load in a full run.
    with httpx.Client(base_url=server.base_url, timeout=30.0) as anon:
        no_header = anon.get("/api/docs")
        wrong_token = anon.get("/api/docs", headers={"Authorization": "Bearer wrong-value"})
        correct = anon.get("/api/docs", headers={"Authorization": f"Bearer {server.token}"})
    assert (no_header.status_code, wrong_token.status_code, correct.status_code) == (401, 401, 200)
