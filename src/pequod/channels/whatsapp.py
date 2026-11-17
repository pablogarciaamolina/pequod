"""WhatsAppMock + WhatsAppLive."""

from pequod.channels.base import MockChannel
from pequod.channels.sms import TwilioChannel


class WhatsAppMock(MockChannel):
    platform = "whatsapp"


class WhatsAppLive(TwilioChannel):
    """WhatsApp through Twilio (sandbox or an approved sender)."""

    platform = "whatsapp"
    prefix = "whatsapp:"
