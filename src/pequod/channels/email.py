"""EmailMock + EmailLive."""

from pequod.channels.base import MockChannel


class EmailMock(MockChannel):
    name = "email"


# EmailLive: Stage 6
