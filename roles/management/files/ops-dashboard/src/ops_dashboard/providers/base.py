"""Abstract base provider for service management."""

from abc import ABC, abstractmethod

from ..models import Service, ServiceStatus


class Provider(ABC):
    """Base class for infrastructure providers (VPS, Azure, etc.)."""

    @abstractmethod
    async def get_status(self, service: Service) -> ServiceStatus:
        """Query the live status of a service."""
        ...

    @abstractmethod
    async def start_service(self, service: Service) -> bool:
        """Start a service. Returns True on success."""
        ...

    @abstractmethod
    async def stop_service(self, service: Service) -> bool:
        """Stop a service. Returns True on success."""
        ...

    @abstractmethod
    async def get_metrics(self, service: Service) -> dict:
        """Get resource metrics (cpu, memory) for a running service."""
        ...
