"""Students: grant or revoke mentee access by managing Authentik's students group.

Admin role only. Calls Authentik with the svc-ops-students token, whose role can
list users and change membership of the students group and nothing else
(roles/management/tasks/ops-students-token.yml). Every change is audited.
Joining students gives the account its student apps, MFA requirement, the
Grafana Students org and the Open WebUI student models at its next login.
"""
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit
from ..auth import require_role

router = APIRouter(prefix="/api/students", tags=["students"])

API = os.environ.get("AUTHENTIK_API_URL", "http://authentication-pod:9000/api/v3").rstrip("/")
GROUP = "students"


def _client() -> httpx.AsyncClient:
    token = os.environ.get("AUTHENTIK_STUDENTS_TOKEN", "")
    if not token:
        raise HTTPException(503, "The Students page is not configured (no Authentik token on this deploy).")
    return httpx.AsyncClient(base_url=API, timeout=15, headers={"Authorization": f"Bearer {token}"})


async def _group_pk(c: httpx.AsyncClient, name: str = GROUP) -> str:
    r = await c.get("/core/groups/", params={"search": name, "page_size": 100})
    r.raise_for_status()
    for g in r.json().get("results", []):
        if g.get("name") == name:
            return g["pk"]
    raise HTTPException(503, f"Authentik has no '{name}' group.")


def _person(u: dict) -> dict:
    return {
        "pk": u["pk"],
        "username": u.get("username", ""),
        "name": u.get("name", ""),
        "email": u.get("email", ""),
        "active": bool(u.get("is_active")),
        "last_login": u.get("last_login"),
        "groups": sorted(g.get("name", "") for g in u.get("groups_obj") or []),
    }


async def _all_people(c: httpx.AsyncClient) -> list[dict]:
    people, page = [], 1
    while True:
        r = await c.get("/core/users/", params={"page": page, "page_size": 200, "type": "internal"})
        r.raise_for_status()
        body = r.json()
        people += [_person(u) for u in body.get("results", [])]
        if not body.get("pagination", {}).get("next"):
            return people
        page += 1


@router.get("")
async def list_students(_: dict = Depends(require_role("admin"))):
    async with _client() as c:
        people = await _all_people(c)
    students = [p for p in people if GROUP in p["groups"]]
    # Anyone else with a real account can be made a student; admins already
    # have every app, so they are left out to keep the list short.
    candidates = [p for p in people if GROUP not in p["groups"] and "admins" not in p["groups"]]
    key = lambda p: (p["name"] or p["username"]).lower()
    return {"students": sorted(students, key=key), "candidates": sorted(candidates, key=key)}


async def _change(request: Request, user: dict, pk: int, add: bool) -> dict:
    action = "student_add" if add else "student_remove"
    async with _client() as c:
        gpk = await _group_pk(c)
        who = await c.get(f"/core/users/{pk}/")
        if who.status_code == 404:
            raise HTTPException(404, "No such account.")
        who.raise_for_status()
        target = who.json().get("username", str(pk))
        r = await c.post(f"/core/groups/{gpk}/{'add_user' if add else 'remove_user'}/", json={"pk": pk})
    ok = r.status_code in (200, 204)
    await audit.record(request.scope, user, action=action, target=target,
                       outcome="ok" if ok else "error", status=r.status_code,
                       detail={"group": GROUP, "authentik_status": r.status_code})
    if not ok:
        raise HTTPException(502, f"Authentik refused the change (HTTP {r.status_code}).")
    return {"ok": True, "username": target, "student": add}


@router.post("/{pk}")
async def add_student(pk: int, request: Request, user: dict = Depends(require_role("admin"))):
    return await _change(request, user, pk, add=True)


@router.delete("/{pk}")
async def remove_student(pk: int, request: Request, user: dict = Depends(require_role("admin"))):
    return await _change(request, user, pk, add=False)
