"""Service status widget — shows a single service with status indicator."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label, Static, Switch

from ..models import Service, ServiceStatus

STATUS_COLORS = {
    ServiceStatus.RUNNING: "green",
    ServiceStatus.STOPPED: "red",
    ServiceStatus.WARMING: "yellow",
    ServiceStatus.SCALING: "yellow",
    ServiceStatus.UNKNOWN: "dim",
    ServiceStatus.ERROR: "bright_red",
}

STATUS_ICONS = {
    ServiceStatus.RUNNING: "[green]●[/]",
    ServiceStatus.STOPPED: "[red]○[/]",
    ServiceStatus.WARMING: "[yellow]◐[/]",
    ServiceStatus.SCALING: "[yellow]◑[/]",
    ServiceStatus.UNKNOWN: "[dim]?[/]",
    ServiceStatus.ERROR: "[bright_red]✗[/]",
}

PLATFORM_BADGES = {
    "vps": "[cyan]VPS[/]",
    "azure": "[blue]AZR[/]",
    "host": "[magenta]HST[/]",
}


class ServiceCard(Static):
    """Displays a single service with status, toggle, and metadata."""

    enabled = reactive(False)

    def __init__(self, service: Service, enabled: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.service = service
        self.enabled = enabled

    def compose(self) -> ComposeResult:
        with Horizontal(classes="service-row"):
            yield Label(STATUS_ICONS.get(self.service.status, "[dim]?[/]"), classes="status-icon")
            yield Label(
                f"{PLATFORM_BADGES.get(self.service.platform.value, '')} ",
                classes="platform-badge",
            )
            yield Label(self.service.name, classes="service-name")
            yield Label(f"[dim]{self.service.description}[/]", classes="service-desc")
            if self.service.cost_per_hour and self.service.cost_per_hour > 0:
                yield Label(
                    f"[yellow]${self.service.cost_per_hour:.2f}/hr[/]",
                    classes="service-cost",
                )
            yield Switch(value=self.enabled, id=f"switch-{self.service.name}")

    def update_status(self, status: ServiceStatus) -> None:
        self.service.status = status
        icon_label = self.query_one(".status-icon", Label)
        icon_label.update(STATUS_ICONS.get(status, "[dim]?[/]"))
