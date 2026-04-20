"""Start/stop service action endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import DashboardState, get_state
from ..schemas import ActionResponse

router = APIRouter(prefix="/api/actions", tags=["actions"])


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


@router.post("/start/{service_name}", response_model=ActionResponse)
async def start_service(service_name: str, state: DashboardState = Depends(get_state)):
    return await _run_action("start", service_name, state)


@router.post("/stop/{service_name}", response_model=ActionResponse)
async def stop_service(service_name: str, state: DashboardState = Depends(get_state)):
    return await _run_action("stop", service_name, state)
