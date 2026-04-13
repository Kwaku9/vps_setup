"""Stack and tier management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from ...config import resolve_profile_stacks
from ..dependencies import DashboardState, get_state
from ..schemas import SetTierRequest, StackSchema, StackTierSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stacks", tags=["stacks"])


def _stack_to_schema(stack, current_tier: str | None = None) -> StackSchema:
    return StackSchema(
        name=stack.name,
        description=stack.description,
        tiers=[
            StackTierSchema(name=t.name, description=t.description, services=t.services)
            for t in stack.tiers
        ],
        tier_names=stack.tier_names,
        current_tier=current_tier,
    )


@router.get("", response_model=list[StackSchema])
async def list_stacks(state: DashboardState = Depends(get_state)):
    active = state.get_active_profile()
    return [
        _stack_to_schema(
            stack,
            current_tier=active.stacks.get(name) if active else None,
        )
        for name, stack in state.stacks.items()
    ]


@router.post("/{stack_name}/tier")
async def set_tier(stack_name: str, req: SetTierRequest, state: DashboardState = Depends(get_state)):
    stack = state.stacks.get(stack_name)
    if not stack:
        raise HTTPException(404, f"Stack '{stack_name}' not found")
    if req.tier not in stack.tier_names:
        raise HTTPException(400, f"Invalid tier '{req.tier}' for stack '{stack_name}'. Valid: {stack.tier_names}")

    active = state.get_active_profile()
    if not active:
        raise HTTPException(400, "No active profile. Switch to a profile first.")

    old_tier = active.stacks.get(stack_name, "off")
    old_services = stack.services_for_tier(old_tier)
    new_services = stack.services_for_tier(req.tier)

    to_start = new_services - old_services
    to_stop = old_services - new_services

    active.stacks[stack_name] = req.tier
    resolved = resolve_profile_stacks(active, state.stacks)
    state.profiles[state.active_profile_name] = resolved

    # Start/stop the diff
    errors = []
    for svc_name in to_stop:
        svc = state.services.get(svc_name)
        if svc and svc.platform.value == "vps":
            logger.info(f"Tier change: stopping {svc_name}")
            success = await state.vps_provider.stop_service(svc)
            if not success:
                errors.append(f"Failed to stop {svc_name}")

    for svc_name in to_start:
        svc = state.services.get(svc_name)
        if svc and svc.platform.value == "vps":
            logger.info(f"Tier change: starting {svc_name}")
            success = await state.vps_provider.start_service(svc)
            if not success:
                errors.append(f"Failed to start {svc_name}")

    message = f"{stack_name} set to {req.tier}"
    if to_start:
        message += f" — started {', '.join(sorted(to_start))}"
    if to_stop:
        message += f" — stopped {', '.join(sorted(to_stop))}"
    if errors:
        message += f" (errors: {', '.join(errors)})"

    return {
        "stack": stack_name,
        "tier": req.tier,
        "services_enabled": sorted(new_services),
        "started": sorted(to_start),
        "stopped": sorted(to_stop),
        "message": message,
    }
