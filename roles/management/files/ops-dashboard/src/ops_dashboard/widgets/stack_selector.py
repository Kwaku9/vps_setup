"""Stack tier selector widget — lets users pick observability/monitoring level."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Label, RadioButton, RadioSet, Static

from ..models import ServiceStack

TIER_ICONS = {
    "off": "[red]○[/]",
    "logs": "[yellow]◐[/]",
    "metrics": "[green]◑[/]",
    "full": "[bright_green]●[/]",
}


class StackTierChanged(Message):
    """Posted when a stack tier selection changes."""

    def __init__(self, stack_name: str, tier_name: str) -> None:
        self.stack_name = stack_name
        self.tier_name = tier_name
        super().__init__()


class StackSelector(Static):
    """Displays a service stack with selectable tiers."""

    current_tier = reactive("off")

    def __init__(self, stack: ServiceStack, current_tier: str = "off", **kwargs):
        super().__init__(**kwargs)
        self.stack = stack
        self.current_tier = current_tier

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold cyan]{self.stack.name.upper()}[/]  [dim]{self.stack.description}[/]",
            classes="stack-header",
        )
        with Horizontal(classes="stack-tiers"):
            with RadioSet(id=f"stack-radio-{self.stack.name}"):
                for tier_name in self.stack.tier_names:
                    icon = TIER_ICONS.get(tier_name, "[dim]?[/]")
                    if tier_name == "off":
                        label = f"{icon} Off"
                        svc_list = ""
                    else:
                        tier = next(t for t in self.stack.tiers if t.name == tier_name)
                        label = f"{icon} {tier_name.capitalize()}"
                        svc_list = ", ".join(tier.services)
                    yield RadioButton(
                        label,
                        value=tier_name == self.current_tier,
                        id=f"tier-{self.stack.name}-{tier_name}",
                    )
        # Show services for each tier
        for tier in self.stack.tiers:
            svc_names = ", ".join(tier.services)
            yield Label(
                f"  [dim]{tier.name}:[/] {svc_names}",
                classes="stack-tier-detail",
            )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        tier_name = self.stack.tier_names[event.index]
        self.current_tier = tier_name
        self.post_message(StackTierChanged(self.stack.name, tier_name))
