"""Start/stop service action endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import DashboardState, get_state
from ..schemas import ActionResponse

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.post("/start/{service_name}", response_model=ActionResponse)
async def start_service(service_name: str, state: DashboardState = Depends(get_state)):
    svc = state.services.get(service_name)
    if not svc:
        raise HTTPException(404, f"Service '{service_name}' not found")

    if svc.platform.value == "vps":
        success = await state.vps_provider.start_service(svc)
    elif svc.platform.value == "azure":
        success = await state.azure_provider.start_service(svc)
    else:
        return ActionResponse(
            service=service_name, action="start", success=False,
            message=f"Cannot start host service '{service_name}' via API",
        )

    return ActionResponse(
        service=service_name,
        action="start",
        success=success,
        message=f"Started {service_name}" if success else f"Failed to start {service_name}",
    )


@router.post("/stop/{service_name}", response_model=ActionResponse)
async def stop_service(service_name: str, state: DashboardState = Depends(get_state)):
    svc = state.services.get(service_name)
    if not svc:
        raise HTTPException(404, f"Service '{service_name}' not found")

    if svc.platform.value == "vps":
        success = await state.vps_provider.stop_service(svc)
    elif svc.platform.value == "azure":
        success = await state.azure_provider.stop_service(svc)
    else:
        return ActionResponse(
            service=service_name, action="stop", success=False,
            message=f"Cannot stop host service '{service_name}' via API",
        )

    return ActionResponse(
        service=service_name,
        action="stop",
        success=success,
        message=f"Stopped {service_name}" if success else f"Failed to stop {service_name}",
    )
