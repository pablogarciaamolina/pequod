"""WhatsAppMock + WhatsAppLive."""

from pequod.channels.base import MockChannel
from pequod.channels.sms import TwilioChannel


class WhatsAppMock(MockChannel):
    name = "whatsapp"


class WhatsAppLive(TwilioChannel):
    """WhatsApp through Twilio (sandbox or an approved sender)."""

    name = "whatsapp"
    prefix = "whatsapp:"
