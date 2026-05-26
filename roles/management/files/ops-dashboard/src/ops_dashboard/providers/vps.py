"""VPS provider — manages services via SSH + Podman."""

import asyncio
import json
import logging
import os

from ..models import Service, ServiceStatus
from .base import Provider

logger = logging.getLogger(__name__)


class VpsProvider(Provider):
    """Manages VPS pod/container services via SSH."""

    def __init__(self, ssh_host: str | None = None, ssh_user: str | None = None):
        self.ssh_host = ssh_host or os.environ.get("SSH_HOST", "alpine-vps")
        self.ssh_user = ssh_user or os.environ.get("SSH_USER", "root")

    async def _ssh_command(self, cmd: str, timeout: int = 30) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5",
            f"{self.ssh_user}@{self.ssh_host}", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning(f"SSH command timed out after {timeout}s: {cmd}")
            return "", 1
        if proc.returncode != 0 and stderr:
            logger.warning(f"SSH command failed (rc={proc.returncode}): {stderr.decode().strip()}")
        return stdout.decode().strip(), proc.returncode

    async def get_status(self, service: Service) -> ServiceStatus:
        if service.pod:
            cmd = f"podman ps --filter name=^{service.name}$ --format '{{{{.Status}}}}'"
        else:
            cmd = f"rc-service {service.name} status 2>/dev/null || systemctl is-active {service.name} 2>/dev/null"

        output, rc = await self._ssh_command(cmd)
        if rc != 0 or not output:
            return ServiceStatus.STOPPED
        if "Up" in output or "active" in output or "started" in output:
            return ServiceStatus.RUNNING
        return ServiceStatus.STOPPED

    async def _poll_until(
        self,
        service: Service,
        target: ServiceStatus,
        attempts: int = 10,
        interval_s: float = 0.5,
    ) -> bool:
        for _ in range(attempts):
            await asyncio.sleep(interval_s)
            if await self.get_status(service) == target:
                return True
        return False

    async def _pod_has_restart_policy(self, pod: str) -> bool:
        out, rc = await self._ssh_command(
            f"podman pod inspect {pod} --format '{{{{.InfraConfig.RestartPolicy}}}}'",
            timeout=5,
        )
        if rc != 0:
            return False
        # podman values: "no" | "on-failure" | "always"
        return out.strip() in {"always", "on-failure"}

    async def start_service(self, service: Service) -> tuple[bool, str]:
        logger.info(f"Starting service: {service.name}")
        _, rc = await self._ssh_command(f"podman start {service.name}", timeout=10)
        if rc != 0:
            return False, "podman start failed"
        if await self._poll_until(service, ServiceStatus.RUNNING):
            return True, "started"
        return False, "podman start returned 0 but container did not enter running state"

    async def stop_service(self, service: Service) -> tuple[bool, str]:
        logger.info(f"Stopping service: {service.name}")
        pod_restart = await self._pod_has_restart_policy(service.pod) if service.pod else False

        _, rc = await self._ssh_command(f"podman stop -t 2 {service.name}", timeout=10)
        if rc != 0:
            return False, "podman stop failed"

        if await self._poll_until(service, ServiceStatus.STOPPED):
            return True, "stopped"

        if pod_restart:
            return False, (
                f"Container stopped but pod '{service.pod}' restarted it. "
                f"Use `podman pod stop {service.pod}` or remove restart policy."
            )
        return False, "stop command returned 0 but container is still running"

    async def list_containers(self) -> list[dict]:
        """Enumerate every podman container on the VPS host (running or stopped)."""
        out, rc = await self._ssh_command(
            "podman ps -a --format json", timeout=10,
        )
        if rc != 0 or not out:
            return []
        try:
            data = json.loads(out)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            logger.warning("podman ps returned non-JSON output")
            return []

    async def inspect_container(self, name: str) -> dict | None:
        """Return a small projection of `podman inspect <name>`. None on failure."""
        out, rc = await self._ssh_command(
            f"podman inspect {name} --format json", timeout=10,
        )
        if rc != 0 or not out:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list) or not data:
            return None
        c = data[0]
        cfg = c.get("Config", {}) or {}
        state = c.get("State", {}) or {}
        host = c.get("HostConfig", {}) or {}
        netinfo = c.get("NetworkSettings", {}) or {}
        # IP from the enterprise_network (default) or first network
        ip = ""
        networks = netinfo.get("Networks", {}) or {}
        if "enterprise_network" in networks:
            ip = networks["enterprise_network"].get("IPAddress", "")
        elif networks:
            first = next(iter(networks.values()))
            ip = first.get("IPAddress", "") if isinstance(first, dict) else ""

        # Redact secrets in env
        SECRET_HINTS = ("PASSWORD", "TOKEN", "SECRET", "KEY", "API_KEY", "VAULT")
        env_pairs: list[tuple[str, str]] = []
        for entry in cfg.get("Env", []) or []:
            if "=" not in entry:
                continue
            k, v = entry.split("=", 1)
            if any(hint in k.upper() for hint in SECRET_HINTS):
                v = "***REDACTED***"
            env_pairs.append((k, v))

        return {
            "name": name,
            "image": cfg.get("Image", ""),
            "command": cfg.get("Cmd") or cfg.get("Entrypoint") or [],
            "created": c.get("Created", ""),
            "started_at": state.get("StartedAt", ""),
            "status": state.get("Status", ""),
            "exit_code": state.get("ExitCode"),
            "restart_policy": (host.get("RestartPolicy") or {}).get("Name", "no"),
            "restart_count": state.get("RestartCount", 0),
            "ip_address": ip,
            "ports": cfg.get("ExposedPorts", {}) or {},
            "port_bindings": host.get("PortBindings", {}) or {},
            "mounts": [
                {"source": m.get("Source") or "", "destination": m.get("Destination") or "", "mode": m.get("Mode", "rw")}
                for m in (c.get("Mounts") or [])
            ],
            "env": env_pairs,
            "labels": cfg.get("Labels", {}) or {},
            "pod": c.get("Pod") or None,
        }

    async def get_metrics(self, service: Service) -> dict:
        name = service.name
        cmd = f"podman stats --no-stream --format json {name} 2>/dev/null"
        output, rc = await self._ssh_command(cmd)
        if rc != 0 or not output:
            return {}
        try:
            stats = json.loads(output)
            if isinstance(stats, list) and stats:
                s = stats[0]
                return {
                    "cpu_percent": s.get("cpu_percent", s.get("CPU", "0%")),
                    "memory_usage": s.get("mem_usage", s.get("MemUsage", "0")),
                    "memory_percent": s.get("mem_percent", s.get("MemPerc", "0%")),
                }
        except json.JSONDecodeError:
            pass
        return {}
