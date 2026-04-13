"""Data models for services, profiles, and status."""

from dataclasses import dataclass, field
from enum import Enum


class ServiceStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    WARMING = "warming"
    SCALING = "scaling"
    UNKNOWN = "unknown"
    ERROR = "error"


class ServicePlatform(Enum):
    VPS = "vps"
    AZURE = "azure"
    HOST = "host"  # bare-metal host services (node-exporter, fail2ban, etc.)


class EndpointType(Enum):
    SERVERLESS = "serverless"
    MANAGED_GPU = "managed_gpu"
    LOCAL = "local"
    POD = "pod"
    HOST_SERVICE = "host_service"


@dataclass
class Service:
    name: str
    platform: ServicePlatform
    endpoint_type: EndpointType
    pod: str | None = None  # VPS pod name (e.g., "security-infra-pod")
    description: str = ""
    status: ServiceStatus = ServiceStatus.UNKNOWN
    cpu_shares: int | None = None
    memory_mb: int | None = None
    cost_per_hour: float | None = None  # estimated USD/hr when running
    ansible_tag: str | None = None  # tag to start/stop via Ansible
    azure_endpoint: str | None = None  # Azure endpoint name
    dependencies: list[str] = field(default_factory=list)  # service names this depends on


@dataclass
class Profile:
    name: str
    description: str
    services: dict[str, bool]  # service_name -> enabled (True/False)
    stacks: dict[str, str] = field(default_factory=dict)  # stack_name -> tier_name
    estimated_cost_per_hour: float | None = None

    @property
    def enabled_services(self) -> list[str]:
        return [s for s, enabled in self.services.items() if enabled]

    @property
    def disabled_services(self) -> list[str]:
        return [s for s, enabled in self.services.items() if not enabled]


@dataclass
class StackTier:
    """A single tier within a service stack (e.g., 'logs' within monitoring)."""
    name: str
    description: str
    services: list[str]  # services enabled at this tier (cumulative with lower tiers)


@dataclass
class ServiceStack:
    """A group of related services with selectable tiers (e.g., monitoring: off/logs/metrics/full)."""
    name: str
    description: str
    tiers: list[StackTier]  # ordered from lowest to highest (tier N includes all services from tiers 0..N)

    @property
    def tier_names(self) -> list[str]:
        return ["off"] + [t.name for t in self.tiers]

    def services_for_tier(self, tier_name: str) -> set[str]:
        """Get all services that should be enabled for a given tier (cumulative)."""
        if tier_name == "off":
            return set()
        result = set()
        for tier in self.tiers:
            result.update(tier.services)
            if tier.name == tier_name:
                break
        return result

    def all_services(self) -> set[str]:
        """All services managed by this stack across all tiers."""
        result = set()
        for tier in self.tiers:
            result.update(tier.services)
        return result

    def tier_for_services(self, enabled_services: set[str]) -> str:
        """Detect which tier is active based on which services are enabled."""
        stack_services = self.all_services()
        active = enabled_services & stack_services
        if not active:
            return "off"
        # Find the highest tier whose services are all present
        matched_tier = "off"
        cumulative = set()
        for tier in self.tiers:
            cumulative.update(tier.services)
            if cumulative <= enabled_services:
                matched_tier = tier.name
        return matched_tier


@dataclass
class ProfileDiff:
    """What changes when switching from one profile to another."""
    starting: list[str]  # services that will be started
    stopping: list[str]  # services that will be stopped
    unchanged: list[str]  # services that stay in their current state
