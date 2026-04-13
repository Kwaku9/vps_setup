"""Ops Dashboard — Terminal UI for managing operational profiles."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, Static

from .config import compute_diff, load_config, load_profiles, load_services, load_stacks, resolve_profile_stacks
from .models import Profile, ProfileDiff
from .widgets.profile_list import ProfileList
from .widgets.stack_selector import StackTierChanged
from .widgets.status_bar import StatusBar


class DiffScreen(ModalScreen[bool]):
    """Confirmation screen showing what will change when switching profiles."""

    def __init__(self, diff: ProfileDiff, target_name: str, **kwargs):
        super().__init__(**kwargs)
        self.diff = diff
        self.target_name = target_name

    def compose(self) -> ComposeResult:
        with Vertical(classes="diff-modal"):
            yield Label(f"[bold]Switch to profile: {self.target_name}[/]", classes="diff-title")
            yield Label("")
            if self.diff.starting:
                yield Label("[green]Starting:[/]")
                for svc in self.diff.starting:
                    yield Label(f"  [green]+[/] {svc}")
            if self.diff.stopping:
                yield Label("[red]Stopping:[/]")
                for svc in self.diff.stopping:
                    yield Label(f"  [red]-[/] {svc}")
            if not self.diff.starting and not self.diff.stopping:
                yield Label("[dim]No changes[/]")
            yield Label("")
            yield Label("[dim]Press [bold]y[/bold] to confirm, [bold]n[/bold] to cancel[/]")

    def key_y(self) -> None:
        self.dismiss(True)

    def key_n(self) -> None:
        self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)


class OpsDashboard(App):
    """Operational Profiles Dashboard."""

    CSS = """
    Screen {
        background: $surface;
    }

    .status-bar {
        dock: top;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }

    .status-item {
        width: auto;
        margin: 0 2 0 0;
    }

    .status-item-right {
        width: auto;
        dock: right;
    }

    .section-header {
        padding: 1 1 0 1;
        text-style: bold;
        color: $text;
    }

    .profile-panel {
        margin: 0 1;
        padding: 0;
    }

    .service-row {
        height: 1;
        padding: 0 2;
    }

    .status-icon {
        width: 2;
    }

    .platform-badge {
        width: 5;
    }

    .service-name {
        width: 20;
    }

    .service-desc {
        width: 1fr;
    }

    .service-cost {
        width: 12;
    }

    .diff-modal {
        align: center middle;
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    .diff-title {
        text-align: center;
        padding: 0 0 1 0;
    }

    Collapsible {
        margin: 0 0 0 0;
        padding: 0;
    }

    .stack-header {
        padding: 1 2 0 2;
    }

    .stack-tiers {
        padding: 0 2;
        height: auto;
    }

    .stack-tier-detail {
        padding: 0 4;
        color: $text-muted;
    }

    .services-subheader {
        padding: 1 2 0 2;
    }

    RadioSet {
        layout: horizontal;
        height: auto;
        width: auto;
    }

    RadioButton {
        width: auto;
        margin: 0 1 0 0;
        height: 1;
    }
    """

    TITLE = "Ops Dashboard"
    SUB_TITLE = "Operational Profiles Manager"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh Status"),
        Binding("1", "switch_profile('minimal')", "Minimal"),
        Binding("2", "switch_profile('chat-only')", "Chat Only"),
        Binding("3", "switch_profile('full-stack')", "Full Stack"),
        Binding("4", "switch_profile('inference-heavy')", "Inference"),
        Binding("5", "switch_profile('media-production')", "Media"),
        Binding("?", "help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        config = load_config()
        self.services = load_services(config)
        self.stacks = load_stacks(config)
        self.profiles = load_profiles(config, self.stacks)
        self.active_profile_name = "none"

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(id="status-bar")
        with ScrollableContainer():
            yield ProfileList(self.profiles, self.services, stacks=self.stacks)
        yield Footer()

    def on_mount(self) -> None:
        status = self.query_one(StatusBar)
        status.active_profile = "none (detecting...)"
        status.running_count = 0
        status.stopped_count = len(self.services)
        status.estimated_cost = 0.0

    def action_switch_profile(self, profile_name: str) -> None:
        if profile_name not in self.profiles:
            self.notify(f"Unknown profile: {profile_name}", severity="error")
            return

        target = self.profiles[profile_name]

        if self.active_profile_name in self.profiles:
            current = self.profiles[self.active_profile_name]
        else:
            # Build a "current" profile from all-off state
            current = Profile(
                name="none",
                description="No active profile",
                services={name: False for name in self.services},
            )

        diff = compute_diff(current, target)

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._apply_profile(profile_name, target)

        self.push_screen(DiffScreen(diff, profile_name), on_confirm)

    def _apply_profile(self, name: str, profile: Profile) -> None:
        self.active_profile_name = name
        status = self.query_one(StatusBar)
        status.active_profile = name
        status.running_count = len(profile.enabled_services)
        status.stopped_count = len(profile.disabled_services)
        status.estimated_cost = profile.estimated_cost_per_hour or 0.0
        self.notify(f"Switched to profile: {name}", severity="information")

    def action_refresh(self) -> None:
        self.notify("Refreshing service status...", severity="information")
        # TODO: Query providers for live status

    def on_stack_tier_changed(self, event: StackTierChanged) -> None:
        """Handle monitoring/stack tier toggle from within a profile."""
        if self.active_profile_name not in self.profiles:
            self.notify("Select a profile first (keys 1-5)", severity="warning")
            return

        profile = self.profiles[self.active_profile_name]
        stack = self.stacks.get(event.stack_name)
        if not stack:
            return

        # Update the profile's stack tier and re-resolve services
        profile.stacks[event.stack_name] = event.tier_name
        resolved = resolve_profile_stacks(profile, self.stacks)
        self.profiles[self.active_profile_name] = resolved

        # Update status bar
        status = self.query_one(StatusBar)
        status.running_count = len(resolved.enabled_services)
        status.stopped_count = len(resolved.disabled_services)

        tier_services = stack.services_for_tier(event.tier_name)
        if event.tier_name == "off":
            self.notify(
                f"{event.stack_name} stack: OFF — all monitoring disabled",
                severity="warning",
            )
        else:
            self.notify(
                f"{event.stack_name} stack: {event.tier_name} — {', '.join(sorted(tier_services))}",
                severity="information",
            )

    def action_help(self) -> None:
        self.notify(
            "Keys: 1-5 switch profiles | r refresh | q quit",
            severity="information",
        )


def main():
    app = OpsDashboard()
    app.run()


if __name__ == "__main__":
    main()
