"""SmsMock + SmsLive."""

import logging
import re
from datetime import datetime, timezone

from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from pequod.channels.base import Channel, ChannelError, MockChannel, text
from pequod.types import ChannelRules, Interaction, Reply


# At INFO the library logs every request: the URL (with the account id) and both phone numbers.
logging.getLogger("twilio.http_client").setLevel(logging.WARNING)


def number(phone: str) -> str:
    """Twilio wants +34600111222: no spaces, dashes or brackets."""
    return re.sub(r"[^\d+]", "", phone)


def reason(error: Exception) -> str:
    """Why Twilio failed, without the request URL: the library's own text contains the account id."""
    if isinstance(error, TwilioRestException):
        return f"HTTP {error.status}, Twilio code {error.code}: {error.msg}"
    return f"{type(error).__name__}: {error}"


class SmsMock(MockChannel):
    platform = "sms"


class TwilioChannel(Channel):
    """A real channel through Twilio. `prefix` is put in front of both phone numbers."""

    prefix = ""

    def __init__(self, name: str, rules: ChannelRules, address: str, sender: str, client: Client) -> None:
        super().__init__(name, rules)
        self.address = number(address)  # the client
        self.sender = number(sender)  # our Twilio number
        self.client = client

    @classmethod
    def from_config(cls, name: str, rules: ChannelRules, address: str, settings: dict, secrets: dict[str, str]) -> "TwilioChannel":
        http = TwilioHttpClient(timeout=settings["timeout_s"])  # give up on a network that does not answer
        return cls(name, rules, address, secrets["sender"], Client(secrets["sid"], secrets["token"], http_client=http))

    def send(self, interaction: Interaction) -> str:
        self.accept(interaction)
        try:
            message = self.client.messages.create(
                from_=self.prefix + self.sender, to=self.prefix + self.address, body=text(interaction)
            )
        except (TwilioException, OSError) as e:
            raise ChannelError(f"{self.name}: could not send to {self.address}: {reason(e)}") from None
        return message.sid

    def fetch_replies(self, since: datetime) -> list[Reply]:
        try:  # only what the client sent to our number: our own messages are never listed
            found = self.client.messages.list(
                from_=self.prefix + self.address, to=self.prefix + self.sender, date_sent_after=since
            )
        except (TwilioException, OSError) as e:
            raise ChannelError(f"{self.name}: could not read replies: {reason(e)}") from None
        replies = []
        for m in found:
            if not m.date_sent or not m.body:  # not delivered yet, or a picture without text
                continue
            at = m.date_sent if m.date_sent.tzinfo else m.date_sent.replace(tzinfo=timezone.utc)
            if at >= since:  # Twilio's own date filter may work by day
                replies.append(Reply(id=m.sid, channel=self.name, body=m.body, received_at=at))
        return sorted(replies, key=lambda r: r.received_at)


class SmsLive(TwilioChannel):
    platform = "sms"
