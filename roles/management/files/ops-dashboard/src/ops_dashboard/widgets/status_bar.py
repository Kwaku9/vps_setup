"""Top-level status bar showing active profile and live counts."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label, Static


class StatusBar(Static):
    """Shows active profile, running/stopped counts, and estimated cost."""

    active_profile = reactive("none")
    running_count = reactive(0)
    stopped_count = reactive(0)
    estimated_cost = reactive(0.0)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="status-bar"):
            yield Label("", id="status-profile", classes="status-item")
            yield Label("", id="status-running", classes="status-item")
            yield Label("", id="status-stopped", classes="status-item")
            yield Label("", id="status-cost", classes="status-item")
            yield Label("[dim]Press [bold]?[/bold] for help[/]", id="status-help", classes="status-item-right")

    def watch_active_profile(self, value: str) -> None:
        self.query_one("#status-profile", Label).update(
            f"[bold cyan]Profile:[/] {value}"
        )

    def watch_running_count(self, value: int) -> None:
        self.query_one("#status-running", Label).update(
            f"[green]Running:[/] {value}"
        )

    def watch_stopped_count(self, value: int) -> None:
        self.query_one("#status-stopped", Label).update(
            f"[red]Stopped:[/] {value}"
        )

    def watch_estimated_cost(self, value: float) -> None:
        self.query_one("#status-cost", Label).update(
            f"[yellow]Cost:[/] ${value:.2f}/hr"
        )
