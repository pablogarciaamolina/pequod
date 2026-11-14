"""Channel interface."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime

from pequod.channels.mock_hub import MockHub
from pequod.types import ChannelRules, Interaction, Reply


class Channel(ABC):
    """One way to reach the client. Mock and live versions share this interface."""

    name: str

    def __init__(self, rules: ChannelRules) -> None:
        self.rules = rules

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
        if interaction.channel != self.name:
            raise ValueError(f"Interaction for '{interaction.channel}' cannot be sent on '{self.name}'")
        return self.hub.add_sent(interaction, self.clock())

    def fetch_replies(self, since: datetime) -> list[Reply]:
        return self.hub.replies(self.name, since)
