"""Service listing and status endpoints."""

from fastapi import APIRouter, Depends

from ..dependencies import DashboardState, get_state
from ..schemas import ServiceSchema

router = APIRouter(prefix="/api/services", tags=["services"])


def _service_to_schema(state: DashboardState, name: str) -> ServiceSchema:
    svc = state.services[name]
    metrics = state.metrics_cache.get(name)
    return ServiceSchema(
        name=svc.name,
        platform=svc.platform.value,
        endpoint_type=svc.endpoint_type.value,
        pod=svc.pod,
        description=svc.description,
        status=metrics.status if metrics else svc.status.value,
        cpu_shares=svc.cpu_shares,
        memory_mb=svc.memory_mb,
        cost_per_hour=svc.cost_per_hour,
        ansible_tag=svc.ansible_tag,
        azure_endpoint=svc.azure_endpoint,
        dependencies=svc.dependencies,
        cpu_percent=metrics.cpu_percent if metrics else None,
        memory_percent=metrics.memory_percent if metrics else None,
        managed=svc.managed,
    )


@router.get("", response_model=list[ServiceSchema])
async def list_services(state: DashboardState = Depends(get_state)):
    return [_service_to_schema(state, name) for name in sorted(state.services)]


@router.get("/{name}", response_model=ServiceSchema)
async def get_service(name: str, state: DashboardState = Depends(get_state)):
    if name not in state.services:
        from fastapi import HTTPException
        raise HTTPException(404, f"Service '{name}' not found")
    return _service_to_schema(state, name)
