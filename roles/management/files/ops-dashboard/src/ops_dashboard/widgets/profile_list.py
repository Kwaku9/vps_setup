"""Expandable profile list widget — shows profiles with collapsible service lists."""

from textual.app import ComposeResult
from textual.widgets import Collapsible, Label, Static

from ..models import Profile, Service, ServiceStack
from .service_card import ServiceCard
from .stack_selector import StackSelector


class ProfilePanel(Static):
    """A single profile with expandable service list."""

    def __init__(
        self,
        profile: Profile,
        services: dict[str, Service],
        stacks: dict[str, ServiceStack] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.profile = profile
        self.services = services
        self.stacks = stacks or {}

    def compose(self) -> ComposeResult:
        enabled_count = len(self.profile.enabled_services)
        total_count = len(self.profile.services)
        cost_str = ""
        if self.profile.estimated_cost_per_hour:
            cost_str = f"  [yellow]~${self.profile.estimated_cost_per_hour:.2f}/hr[/]"

        # Build stack tier summary
        stack_str = ""
        if self.profile.stacks:
            stack_parts = []
            for stack_name, tier_name in self.profile.stacks.items():
                stack_parts.append(f"{stack_name}:[cyan]{tier_name}[/]")
            stack_str = "  " + " | ".join(stack_parts)

        title = (
            f"  {self.profile.name}  "
            f"[green]{enabled_count}[/]/[dim]{total_count}[/] services"
            f"{cost_str}{stack_str}"
        )

        # Collect services managed by stacks so we can group them
        stack_managed = set()
        for stack_name in self.profile.stacks:
            stack = self.stacks.get(stack_name)
            if stack:
                stack_managed.update(stack.all_services())

        with Collapsible(title=title, collapsed=True):
            yield Label(f"[dim italic]{self.profile.description}[/]")

            # Show stack selectors
            for stack_name, tier_name in self.profile.stacks.items():
                stack = self.stacks.get(stack_name)
                if stack:
                    yield StackSelector(
                        stack,
                        current_tier=tier_name,
                        id=f"stack-{self.profile.name}-{stack_name}",
                    )

            # Show non-stack services (sorted: enabled first)
            non_stack_services = {
                name: enabled
                for name, enabled in self.profile.services.items()
                if name not in stack_managed
            }
            if non_stack_services:
                yield Label("[bold]Services[/]", classes="services-subheader")
                for svc_name, enabled in sorted(
                    non_stack_services.items(), key=lambda x: (not x[1], x[0])
                ):
                    service = self.services.get(svc_name)
                    if service:
                        yield ServiceCard(
                            service,
                            enabled=enabled,
                            id=f"card-{self.profile.name}-{svc_name}",
                        )


class ProfileList(Static):
    """Container for all profile panels."""

    def __init__(
        self,
        profiles: dict[str, Profile],
        services: dict[str, Service],
        stacks: dict[str, ServiceStack] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.profiles = profiles
        self.services = services
        self.stacks = stacks or {}

    def compose(self) -> ComposeResult:
        yield Label("[bold]Operational Profiles[/]", classes="section-header")
        for name, profile in self.profiles.items():
            yield ProfilePanel(
                profile,
                self.services,
                stacks=self.stacks,
                id=f"profile-{name}",
                classes="profile-panel",
            )
