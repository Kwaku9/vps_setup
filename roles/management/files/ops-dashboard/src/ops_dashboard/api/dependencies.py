"""Shared application state and dependency injection for FastAPI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import load_config, load_profiles, load_services, load_stacks, compute_diff, resolve_profile_stacks
from ..models import Profile, Service, ServiceStack
from ..providers.vps import VpsProvider
from ..providers.azure import AzureProvider
from .schemas import MetricsSnapshot


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
