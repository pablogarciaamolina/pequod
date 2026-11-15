"""Channels: a mock and a live version of each, behind one interface."""

import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime

from pequod.channels.base import Channel
from pequod.channels.email import EmailLive, EmailMock
from pequod.channels.mock_hub import MockHub
from pequod.channels.sms import SmsLive, SmsMock
from pequod.channels.whatsapp import WhatsAppLive, WhatsAppMock
from pequod.types import ChannelRules

MOCKS = {c.name: c for c in (EmailMock, SmsMock, WhatsAppMock)}
LIVE = {c.name: c for c in (EmailLive, SmsLive, WhatsAppLive)}
NOT_SETTINGS = ("mode", "role", "credentials", "rules")  # `role` is for the agents' prompts, not for the channel


def placeholder(address: str) -> bool:
    """An address of the demo persona, of a template or of documentation: never a real recipient."""
    address = address.strip().lower()
    if "@" in address:
        return address.endswith((".example", ".invalid", "@example.com", "@example.org", "@example.net"))
    return not re.sub(r"[^1-9]", "", address)  # empty, or a phone number made of zeros


def same(address: str) -> str:
    """An address reduced to what identifies it: mail addresses lower-cased, phone numbers as digits."""
    return address.strip().lower() if "@" in address else re.sub(r"\D", "", address)


def build_channels(
    config: Mapping,
    addresses: Mapping[str, str],
    hub: MockHub | None,
    clock: Callable[[], datetime],
    env: Mapping[str, str] = os.environ,
) -> dict[str, Channel]:
    """One channel object per engagement channel (`addresses`: name -> the persona's address on it),
    mock or live as the config says. Live channels are checked before any is built: credentials
    present in `env`, and a real recipient address."""
    for name, address in addresses.items():
        if name not in config or name not in MOCKS:
            raise ValueError(f"Unknown channel '{name}'. Configured: {', '.join(config)}")
        if config[name].mode == "mock":
            continue
        missing = [variable for variable in config[name].credentials.values() if not env.get(variable, "").strip()]
        if missing:
            raise ValueError(f"Live {name} needs these variables in .env: {', '.join(missing)}")
        if placeholder(address):
            raise ValueError(f"Live {name}: '{address}' is a placeholder address. Use an engagement with real addresses.")
        ours = [env[variable] for variable in config[name].credentials.values()]
        if same(address) in map(same, ours):  # a message to ourselves would come back as the persona's reply
            raise ValueError(f"Live {name}: the persona's address '{address}' is the same as our own sender address.")

    channels = {}
    for name, address in addresses.items():
        channel = config[name]
        rules = ChannelRules.model_validate(dict(channel.rules))
        if channel.mode == "mock":
            channels[name] = MOCKS[name](rules, hub, clock)
        else:
            settings = {key: value for key, value in channel.items() if key not in NOT_SETTINGS}
            secrets = {key: env[variable] for key, variable in channel.credentials.items()}
            channels[name] = LIVE[name].from_config(rules, address, settings, secrets)
    return channels
