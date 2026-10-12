"""Start/stop service action endpoints.

Every action is role-checked, audited with the exact host command, and sent to
Telegram. An action that could not be audited (no DB pool) is refused.
"""
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit
from ..auth import require_role
from ..dependencies import DashboardState, get_state
from ..schemas import ActionResponse
from ...providers.vps import VpsProvider

router = APIRouter(prefix="/api/actions", tags=["actions"])

COMMANDS = {"start": VpsProvider.START_CMD, "stop": VpsProvider.STOP_CMD}


async def _run_action(
    action: str,
    service_name: str,
    state: DashboardState,
) -> ActionResponse:
    svc = state.services.get(service_name)
    if not svc:
        raise HTTPException(404, f"Service '{service_name}' not found")
    if svc.name.endswith("-infra"):
        raise HTTPException(
            400,
            f"Service '{service_name}' is a pod infrastructure container. "
            "Stopping it would stop the whole pod — use `podman pod stop <pod>` instead.",
        )

    if svc.platform.value == "vps":
        provider = state.vps_provider
    elif svc.platform.value == "azure":
        provider = state.azure_provider
    else:
        return ActionResponse(
            service=service_name, action=action, success=False,
            message=f"Cannot {action} host service '{service_name}' via API",
        )

    fn = provider.start_service if action == "start" else provider.stop_service
    ok, msg = await fn(svc)
    return ActionResponse(service=service_name, action=action, success=ok, message=msg)


async def _audited(request: Request, user: dict, action: str, service_name: str,
                   state: DashboardState) -> ActionResponse:
    if not audit.audit_ready(request.app):
        raise HTTPException(503, "The audit log is unavailable, so actions are paused.")
    command = COMMANDS[action].format(name=service_name)
    try:
        result = await _run_action(action, service_name, state)
    except HTTPException as exc:
        await audit.record(request.scope, user, action=action, target=service_name, outcome="refused",
                           status=exc.status_code, detail={"reason": exc.detail})
        raise
    await audit.record(request.scope, user, action=action, target=service_name,
                       outcome="ok" if result.success else "failed", status=200,
                       detail={"command": command, "message": result.message})
    audit.notify(state.vps_provider,
                 f"🔧 <b>ops</b> {escape(user['username'])} ran <code>{escape(command)}</code> → "
                 f"{'ok' if result.success else 'FAILED: ' + escape(result.message)} ({escape(user.get('via', '?'))})")
    return result


@router.post("/start/{service_name}", response_model=ActionResponse)
async def start_service(service_name: str, request: Request, state: DashboardState = Depends(get_state),
                        user: dict = Depends(require_role("operator"))):
    return await _audited(request, user, "start", service_name, state)


# Stopping is admin-only until destructive actions go through Telegram approval
# (phase 4 of docs/superpowers/specs/2026-06-29-ops-dashboard-hardening-design.md).
@router.post("/stop/{service_name}", response_model=ActionResponse)
async def stop_service(service_name: str, request: Request, state: DashboardState = Depends(get_state),
                       user: dict = Depends(require_role("admin"))):
    return await _audited(request, user, "stop", service_name, state)
