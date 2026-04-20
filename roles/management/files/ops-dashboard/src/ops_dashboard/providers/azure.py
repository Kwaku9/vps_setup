"""Azure provider — manages Azure ML endpoints and serverless deployments."""

import asyncio
import json

from ..models import Service, ServiceStatus
from .base import Provider


class AzureProvider(Provider):
    """Manages Azure ML endpoints via Azure CLI."""

    def __init__(self, resource_group: str = "rg-ai-ml-prod", workspace: str = "mlw-ai-prod"):
        self.resource_group = resource_group
        self.workspace = workspace

    async def _az_command(self, cmd: str) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip(), proc.returncode

    async def get_status(self, service: Service) -> ServiceStatus:
        if not service.azure_endpoint:
            return ServiceStatus.UNKNOWN
        cmd = (
            f"az ml online-endpoint show --name {service.azure_endpoint} "
            f"--resource-group {self.resource_group} "
            f"--workspace-name {self.workspace} "
            f"--output json 2>/dev/null"
        )
        output, rc = await self._az_command(cmd)
        if rc != 0:
            return ServiceStatus.UNKNOWN
        try:
            data = json.loads(output)
            state = data.get("provisioning_state", "").lower()
            if state == "succeeded":
                return ServiceStatus.RUNNING
            elif state in ("creating", "updating"):
                return ServiceStatus.SCALING
            elif state == "deleting":
                return ServiceStatus.STOPPED
        except json.JSONDecodeError:
            pass
        return ServiceStatus.UNKNOWN

    async def start_service(self, service: Service) -> tuple[bool, str]:
        if not service.azure_endpoint:
            return False, "service has no azure_endpoint configured"
        # Scale min_replicas from 0 to 1
        cmd = (
            f"az ml online-deployment update "
            f"--endpoint-name {service.azure_endpoint} "
            f"--name default "
            f"--resource-group {self.resource_group} "
            f"--workspace-name {self.workspace} "
            f"--set instance_count=1 "
            f"--output none 2>/dev/null"
        )
        _, rc = await self._az_command(cmd)
        if rc == 0:
            return True, "started"
        return False, "az ml online-deployment update (instance_count=1) failed"

    async def stop_service(self, service: Service) -> tuple[bool, str]:
        if not service.azure_endpoint:
            return False, "service has no azure_endpoint configured"
        # Scale down to 0
        cmd = (
            f"az ml online-deployment update "
            f"--endpoint-name {service.azure_endpoint} "
            f"--name default "
            f"--resource-group {self.resource_group} "
            f"--workspace-name {self.workspace} "
            f"--set instance_count=0 "
            f"--output none 2>/dev/null"
        )
        _, rc = await self._az_command(cmd)
        if rc == 0:
            return True, "stopped"
        return False, "az ml online-deployment update (instance_count=0) failed"

    async def get_metrics(self, service: Service) -> dict:
        if not service.azure_endpoint:
            return {}
        cmd = (
            f"az ml online-endpoint get-logs "
            f"--name {service.azure_endpoint} "
            f"--resource-group {self.resource_group} "
            f"--workspace-name {self.workspace} "
            f"--output json 2>/dev/null"
        )
        output, rc = await self._az_command(cmd)
        if rc != 0:
            return {}
        return {"logs_available": True}
