"""Profile listing and switching endpoints."""

from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit
from ..auth import require_role
from ..dependencies import DashboardState, get_state
from ..schemas import ProfileDiffSchema, ProfileSchema, SwitchProfileRequest, SwitchProfileResponse

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _profile_to_schema(profile) -> ProfileSchema:
    return ProfileSchema(
        name=profile.name,
        description=profile.description,
        services=profile.services,
        stacks=profile.stacks,
        estimated_cost_per_hour=profile.estimated_cost_per_hour,
        enabled_count=len(profile.enabled_services),
        disabled_count=len(profile.disabled_services),
    )


@router.get("", response_model=list[ProfileSchema])
async def list_profiles(state: DashboardState = Depends(get_state)):
    return [_profile_to_schema(p) for p in state.profiles.values()]


@router.get("/active")
async def get_active_profile(state: DashboardState = Depends(get_state)):
    return {"active_profile": state.active_profile_name}


@router.get("/{name}", response_model=ProfileSchema)
async def get_profile(name: str, state: DashboardState = Depends(get_state)):
    if name not in state.profiles:
        raise HTTPException(404, f"Profile '{name}' not found")
    return _profile_to_schema(state.profiles[name])


@router.post("/switch", response_model=SwitchProfileResponse)
async def switch_profile(req: SwitchProfileRequest, request: Request,
                         state: DashboardState = Depends(get_state),
                         user: dict = Depends(require_role("admin"))):
    if req.target_profile not in state.profiles:
        raise HTTPException(404, f"Profile '{req.target_profile}' not found")

    diff = state.compute_switch_diff(req.target_profile)
    diff_schema = ProfileDiffSchema(
        starting=diff.starting,
        stopping=diff.stopping,
        unchanged=diff.unchanged,
    )

    if req.confirm and not audit.audit_ready(request.app):
        raise HTTPException(503, "The audit log is unavailable, so actions are paused.")
    if not req.confirm:
        return SwitchProfileResponse(
            diff=diff_schema,
            executed=False,
            message=f"Preview: {len(diff.starting)} to start, {len(diff.stopping)} to stop",
        )

    # Execute the switch
    target = state.profiles[req.target_profile]
    errors = []

    # Stop services
    for svc_name in diff.stopping:
        svc = state.services.get(svc_name)
        if svc and svc.platform.value == "vps":
            ok, msg = await state.vps_provider.stop_service(svc)
            if not ok:
                errors.append(f"Failed to stop {svc_name}: {msg}")

    # Start services
    for svc_name in diff.starting:
        svc = state.services.get(svc_name)
        if svc and svc.platform.value == "vps":
            ok, msg = await state.vps_provider.start_service(svc)
            if not ok:
                errors.append(f"Failed to start {svc_name}: {msg}")

    state.active_profile_name = req.target_profile

    message = f"Switched to {req.target_profile}"
    if errors:
        message += f" (with {len(errors)} errors: {', '.join(errors)})"
    await audit.record(request.scope, user, action="profile-switch", target=req.target_profile,
                       outcome="failed" if errors else "ok", status=200,
                       detail={"started": diff.starting, "stopped": diff.stopping, "errors": errors})
    audit.notify(state.vps_provider,
                 f"🔧 <b>ops</b> {escape(user['username'])} switched profile to <b>{escape(req.target_profile)}</b>: "
                 f"stopped {len(diff.stopping)}, started {len(diff.starting)}"
                 + (f", {len(errors)} errors" if errors else ""))

    return SwitchProfileResponse(
        diff=diff_schema,
        executed=True,
        message=message,
    )
