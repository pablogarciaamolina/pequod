"""Channels: a mock and a live version of each, behind one interface."""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime

from pequod.channels.base import Channel
from pequod.channels.email import EmailMock
from pequod.channels.mock_hub import MockHub
from pequod.channels.sms import SmsMock
from pequod.channels.whatsapp import WhatsAppMock
from pequod.types import ChannelRules

MOCKS = {c.name: c for c in (EmailMock, SmsMock, WhatsAppMock)}


def build_channels(
    config: Mapping, names: Iterable[str], hub: MockHub, clock: Callable[[], datetime]
) -> dict[str, Channel]:
    """One channel object per engagement channel, mock or live as the config says."""
    channels = {}
    for name in names:
        if name not in config or name not in MOCKS:
            raise ValueError(f"Unknown channel '{name}'. Configured: {', '.join(config)}")
        if config[name].mode != "mock":
            raise NotImplementedError("Live channels arrive in Stage 6. Run with channels=mock.")
        channels[name] = MOCKS[name](ChannelRules.model_validate(dict(config[name].rules)), hub, clock)
    return channels
