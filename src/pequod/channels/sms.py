"""SmsMock + SmsLive."""

from pequod.channels.base import MockChannel


class SmsMock(MockChannel):
    name = "sms"


# SmsLive: Stage 6
