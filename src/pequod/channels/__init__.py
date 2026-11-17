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

MOCKS = {c.platform: c for c in (EmailMock, SmsMock, WhatsAppMock)}
LIVE = {c.platform: c for c in (EmailLive, SmsLive, WhatsAppLive)}
# engine/pairing metadata, not constructor arguments of a live channel
NOT_SETTINGS = ("mode", "role", "angle", "platform", "target", "credentials", "rules")


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
    persona_channels: Mapping[str, Mapping[str, str]],
    hub: MockHub | None,
    clock: Callable[[], datetime],
    env: Mapping[str, str] = os.environ,
) -> dict[str, Channel]:
    """One channel object per *system* channel (our accounts, keyed by system-channel name). Each
    system channel in `config` names a `target` persona channel (from `persona_channels`, mapping
    persona-channel name -> {platform, address}) and must share its platform; the built channel is
    addressed to the target. Live channels are checked before any is built: a known platform, an
    existing target of the same platform, credentials present in `env`, and a real recipient address."""
    def target_address(name: str, channel: Mapping) -> str:
        platform = channel.get("platform")
        registry = MOCKS if channel.mode == "mock" else LIVE
        if platform not in registry:
            raise ValueError(f"Unknown channel platform '{platform}' for '{name}'. Known platforms: {', '.join(registry)}")
        target = channel.get("target")
        if target not in persona_channels:
            raise ValueError(
                f"Channel '{name}' targets persona channel '{target}', which does not exist. "
                f"Persona channels: {', '.join(persona_channels)}"
            )
        if persona_channels[target]["platform"] != platform:
            raise ValueError(
                f"Channel '{name}' is {platform} but its target '{target}' is "
                f"{persona_channels[target]['platform']}; a channel can only reach a target of the same platform."
            )
        return persona_channels[target]["address"]

    for name, channel in config.items():
        address = target_address(name, channel)
        if channel.mode == "mock":
            continue
        missing = [variable for variable in channel.credentials.values() if not env.get(variable, "").strip()]
        if missing:
            raise ValueError(f"Live {name} needs these variables in .env: {', '.join(missing)}")
        if placeholder(address):
            raise ValueError(f"Live {name}: '{address}' is a placeholder address. Use an engagement with real addresses.")
        ours = [env[variable] for variable in channel.credentials.values()]
        if same(address) in map(same, ours):  # a message to ourselves would come back as the persona's reply
            raise ValueError(f"Live {name}: the persona's address '{address}' is the same as our own sender address.")

    channels = {}
    for name, channel in config.items():
        platform = channel.platform
        address = persona_channels[channel.target]["address"]
        rules = ChannelRules.model_validate(dict(channel.rules))
        if channel.mode == "mock":
            channels[name] = MOCKS[platform](name, rules, hub, clock)
        else:
            settings = {key: value for key, value in channel.items() if key not in NOT_SETTINGS}
            secrets = {key: env[variable] for key, variable in channel.credentials.items()}
            channels[name] = LIVE[platform].from_config(name, rules, address, settings, secrets)
    return channels
