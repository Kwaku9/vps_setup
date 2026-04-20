"""Shared application state and dependency injection for FastAPI."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from ..config import load_config, load_profiles, load_services, load_stacks, compute_diff, resolve_profile_stacks
from ..models import EndpointType, Profile, Service, ServicePlatform, ServiceStack
from ..providers.vps import VpsProvider
from ..providers.azure import AzureProvider
from .schemas import MetricsSnapshot

logger = logging.getLogger(__name__)


@dataclass
class DashboardState:
    """Singleton holding all shared state for the dashboard."""

    config: dict = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    stacks: dict[str, ServiceStack] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    active_profile_name: str = "none"
    vps_provider: VpsProvider = field(default_factory=VpsProvider)
    azure_provider: AzureProvider = field(default_factory=AzureProvider)
    metrics_cache: dict[str, MetricsSnapshot] = field(default_factory=dict)
    ws_clients: list = field(default_factory=list)
    _poll_task: asyncio.Task | None = field(default=None, repr=False)

    @classmethod
    def from_config(cls) -> DashboardState:
        config = load_config()
        services = load_services(config)
        stacks = load_stacks(config)
        profiles = load_profiles(config, stacks)
        return cls(
            config=config,
            services=services,
            stacks=stacks,
            profiles=profiles,
            vps_provider=VpsProvider(),
            azure_provider=AzureProvider(),
        )

    def get_active_profile(self) -> Profile | None:
        return self.profiles.get(self.active_profile_name)

    def compute_switch_diff(self, target_name: str):
        target = self.profiles.get(target_name)
        if not target:
            return None
        current = self.get_active_profile()
        if not current:
            current = Profile(
                name="none",
                description="No active profile",
                services={name: False for name in self.services},
            )
        return compute_diff(current, target)


# Global singleton — initialized in lifespan
_state: DashboardState | None = None


def get_state() -> DashboardState:
    assert _state is not None, "DashboardState not initialized"
    return _state


def init_state() -> DashboardState:
    global _state
    _state = DashboardState.from_config()
    return _state


def _container_name(entry: dict) -> str | None:
    names = entry.get("Names")
    if isinstance(names, list) and names:
        return names[0]
    if isinstance(names, str):
        return names
    return None


def merge_live_containers(state: DashboardState, live: list[dict]) -> None:
    """Merge live `podman ps -a` output into state.services.

    Rules:
    - Managed services (from profiles.yaml) are never replaced — they stay.
    - Containers present on host but absent from profiles.yaml become synthetic
      unmanaged Service entries.
    - Unmanaged entries from a previous pass that have disappeared are removed.
    """
    live_names = {name for entry in live if (name := _container_name(entry))}
    # Drop unmanaged entries that no longer exist on host.
    for name in list(state.services):
        svc = state.services[name]
        if not svc.managed and name not in live_names:
            del state.services[name]
    # Add newly discovered unmanaged containers.
    for entry in live:
        name = _container_name(entry)
        if not name or name in state.services:
            continue
        pod = entry.get("Pod") or None
        state.services[name] = Service(
            name=name,
            platform=ServicePlatform.VPS,
            endpoint_type=EndpointType.POD,
            pod=pod,
            description="unclassified",
            managed=False,
        )


async def refresh_live_containers(state: DashboardState, interval_s: float = 30.0) -> None:
    """Background task that keeps `state.services` in sync with the VPS host."""
    if os.environ.get("FEATURE_LIVE_DISCOVERY", "true").lower() != "true":
        logger.info("Live discovery disabled by FEATURE_LIVE_DISCOVERY env")
        return
    while True:
        try:
            live = await state.vps_provider.list_containers()
            merge_live_containers(state, live)
        except Exception:
            logger.exception("Live container refresh failed")
        await asyncio.sleep(interval_s)
