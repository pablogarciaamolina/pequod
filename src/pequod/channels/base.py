"""Channel interface."""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime

from pequod.channels.mock_hub import MockHub
from pequod.types import ChannelRules, Interaction, Reply


class ChannelError(RuntimeError):
    """A real platform refused or could not be reached. The message names the channel, never a credential."""


def text(interaction: Interaction) -> str:
    """The body as it goes out on a platform without a payload field: a payload link that the body
    does not already contain is added as a last line."""
    extra = [
        value for value in (interaction.payload or {}).values()
        if value and not re.search(re.escape(value) + r"(?![\w/-])", interaction.body)  # the whole link, not its start
    ]
    return "\n".join([interaction.body, *extra])


class Channel(ABC):
    """One way to reach the client. Mock and live versions share this interface."""

    name: str

    def __init__(self, rules: ChannelRules) -> None:
        self.rules = rules

    def accept(self, interaction: Interaction) -> None:
        if interaction.channel != self.name:
            raise ValueError(f"Interaction for '{interaction.channel}' cannot be sent on '{self.name}'")

    @abstractmethod
    def send(self, interaction: Interaction) -> str:
        """Send it and return the platform's message id."""

    @abstractmethod
    def fetch_replies(self, since: datetime) -> list[Reply]:
        """Replies received at or after `since`, oldest first."""


class MockChannel(Channel):
    """Reads and writes the mock hub instead of a real platform."""

    def __init__(self, rules: ChannelRules, hub: MockHub, clock: Callable[[], datetime]) -> None:
        super().__init__(rules)
        self.hub = hub
        self.clock = clock

    def send(self, interaction: Interaction) -> str:
        self.accept(interaction)
        return self.hub.add_sent(interaction, self.clock())

    def fetch_replies(self, since: datetime) -> list[Reply]:
        return self.hub.replies(self.name, since)
