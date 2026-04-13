"""Load and manage profile/service configuration from YAML."""

from pathlib import Path

import yaml

from .models import (
    EndpointType,
    Profile,
    ProfileDiff,
    Service,
    ServicePlatform,
    ServiceStack,
    StackTier,
)

DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "profiles.yaml"


def load_config(path: Path | None = None) -> dict:
    config_path = path or DEFAULT_CONFIG
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_services(config: dict) -> dict[str, Service]:
    services = {}
    for name, svc in config.get("services", {}).items():
        services[name] = Service(
            name=name,
            platform=ServicePlatform(svc["platform"]),
            endpoint_type=EndpointType(svc["endpoint_type"]),
            pod=svc.get("pod"),
            description=svc.get("description", ""),
            cpu_shares=svc.get("cpu_shares"),
            memory_mb=svc.get("memory_mb"),
            cost_per_hour=svc.get("cost_per_hour"),
            ansible_tag=svc.get("ansible_tag"),
            azure_endpoint=svc.get("azure_endpoint"),
            dependencies=svc.get("dependencies", []),
        )
    return services


def load_stacks(config: dict) -> dict[str, ServiceStack]:
    stacks = {}
    for name, stack_def in config.get("stacks", {}).items():
        tiers = []
        for tier_def in stack_def.get("tiers", []):
            tiers.append(StackTier(
                name=tier_def["name"],
                description=tier_def.get("description", ""),
                services=tier_def.get("services", []),
            ))
        stacks[name] = ServiceStack(
            name=name,
            description=stack_def.get("description", ""),
            tiers=tiers,
        )
    return stacks


def resolve_profile_stacks(
    profile: Profile,
    stacks: dict[str, ServiceStack],
) -> Profile:
    """Expand stack tier selections into concrete service toggles."""
    services = dict(profile.services)
    for stack_name, tier_name in profile.stacks.items():
        stack = stacks.get(stack_name)
        if not stack:
            continue
        enabled = stack.services_for_tier(tier_name)
        all_stack = stack.all_services()
        for svc in all_stack:
            services[svc] = svc in enabled
    return Profile(
        name=profile.name,
        description=profile.description,
        services=services,
        stacks=profile.stacks,
        estimated_cost_per_hour=profile.estimated_cost_per_hour,
    )


def load_profiles(config: dict, stacks: dict[str, ServiceStack] | None = None) -> dict[str, Profile]:
    profiles = {}
    for name, prof in config.get("profiles", {}).items():
        profile = Profile(
            name=name,
            description=prof.get("description", ""),
            services=prof.get("services", {}),
            stacks=prof.get("stacks", {}),
            estimated_cost_per_hour=prof.get("estimated_cost_per_hour"),
        )
        if stacks:
            profile = resolve_profile_stacks(profile, stacks)
        profiles[name] = profile
    return profiles


def compute_diff(current: Profile, target: Profile) -> ProfileDiff:
    all_services = set(current.services) | set(target.services)
    starting = []
    stopping = []
    unchanged = []
    for svc in sorted(all_services):
        cur = current.services.get(svc, False)
        tgt = target.services.get(svc, False)
        if not cur and tgt:
            starting.append(svc)
        elif cur and not tgt:
            stopping.append(svc)
        else:
            unchanged.append(svc)
    return ProfileDiff(starting=starting, stopping=stopping, unchanged=unchanged)
