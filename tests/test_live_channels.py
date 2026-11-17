"""Live channels against fake mail and Twilio servers. No network, no real credentials, nothing is sent."""

import imaplib
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest
from conftest import NOW, interaction, load, personas
from omegaconf import OmegaConf

from pequod.channels import build_channels
from pequod.channels.base import ChannelError
from pequod.channels.email import EmailLive, EmailMock
from pequod.channels.sms import SmsLive
from pequod.channels.whatsapp import WhatsAppLive
from pequod.types import ChannelRules, Interaction

RULES = ChannelRules(max_length=2000, subject=True, links_ok=True)
CLIENT, US, PASSWORD = "client@customer.test", "us@gmail.test", "app-password-123"
ENV = {
    "EMAIL_ADDRESS": US, "EMAIL_APP_PASSWORD": PASSWORD,
    "TWILIO_ACCOUNT_SID": "ACsid", "TWILIO_AUTH_TOKEN": "twilio-token-456",
    "TWILIO_SMS_FROM": "+15550001111", "TWILIO_WHATSAPP_FROM": "+15550002222",
}
PERSONA = {"work_email": {"platform": "email", "address": CLIENT},
           "company_sms": {"platform": "sms", "address": "+34 600 111 222"},
           "personal_whatsapp": {"platform": "whatsapp", "address": "+34 600 111 222"}}


def clock():
    return NOW


@pytest.fixture
def live():
    return load(["channels=live"]).channels


# ---------- building channels from config ----------


def test_live_channels_are_built_with_address_and_credentials(live, monkeypatch):
    made = []
    monkeypatch.setattr(
        "pequod.channels.sms.Client",
        lambda sid, token, http_client: made.append((sid, token, http_client.timeout)) or "client",
    )
    channels = build_channels(live, PERSONA, None, clock, ENV)
    assert {name: type(c) for name, c in channels.items()} == {"pepe": EmailLive, "stephan": SmsLive, "melina": WhatsAppLive}
    email = channels["pepe"]
    assert (email.address, email.user, email.password) == (CLIENT, US, PASSWORD)
    assert (email.smtp_host, email.smtp_port, email.imap_host, email.timeout_s) == ("smtp.gmail.com", 465, "imap.gmail.com", 30)
    assert (channels["stephan"].address, channels["stephan"].sender) == ("+34600111222", "+15550001111")
    assert channels["melina"].sender == "+15550002222" and channels["stephan"].client == "client"
    assert made == [("ACsid", "twilio-token-456", 30)] * 2  # a stalled network must not hang the run
    assert email.rules == ChannelRules.model_validate(dict(live.pepe.rules))


def test_missing_credentials_are_named(live):
    env = {k: v for k, v in ENV.items() if k != "EMAIL_APP_PASSWORD"}
    with pytest.raises(ValueError, match="pepe.*EMAIL_APP_PASSWORD") as e:
        build_channels(live, PERSONA, None, clock, env)
    assert US not in str(e.value) and "EMAIL_ADDRESS" not in str(e.value)  # only what is missing, and no values


@pytest.mark.parametrize("sysname, pname, address", [("pepe", "work_email", "x@example.com"), ("stephan", "company_sms", "+00 000 000"), ("melina", "personal_whatsapp", "+00 000 000")])
def test_placeholder_address_is_rejected_in_live_mode(live, sysname, pname, address):
    config = OmegaConf.create({sysname: live[sysname]})
    persona = {pname: {"platform": PERSONA[pname]["platform"], "address": address}}
    with pytest.raises(ValueError, match="placeholder"):
        build_channels(config, persona, None, clock, ENV)


def test_mock_mode_needs_no_credentials(cfg, tmp_path):
    from pequod.channels.mock_hub import MockHub

    channels = build_channels(cfg.channels, personas(cfg), MockHub(tmp_path / "hub.db"), clock, {})
    assert type(channels["pepe"]) is EmailMock


def test_only_the_given_system_channels_are_built(live):
    env = {"EMAIL_ADDRESS": US, "EMAIL_APP_PASSWORD": PASSWORD}  # no Twilio variables at all
    config = OmegaConf.create({"pepe": live.pepe})
    persona = {"work_email": {"platform": "email", "address": CLIENT}}
    assert list(build_channels(config, persona, None, clock, env)) == ["pepe"]


class FakeSMTP:
    sent, logins, made, fail = [], [], [], None

    def __init__(self, host, port, timeout=None):
        FakeSMTP.made.append((host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.logins.append((user, password))

    def send_message(self, message):
        FakeSMTP.sent.append(message)


class FakeIMAP:
    mails, calls = [], []

    def __init__(self, host, timeout=None):
        FakeIMAP.calls.append(("connect", host, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        FakeIMAP.calls.append(("login", user, password))

    def select(self, mailbox, readonly=False):
        FakeIMAP.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        FakeIMAP.calls.append(("search", criteria))
        return "OK", [" ".join(str(i + 1) for i in range(len(FakeIMAP.mails))).encode()]

    def fetch(self, number, parts):
        return "OK", [(b"header", FakeIMAP.mails[int(number) - 1].as_bytes())]


@pytest.fixture
def email(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.made, FakeSMTP.fail = [], [], [], None
    FakeIMAP.mails, FakeIMAP.calls = [], []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    return EmailLive("email", RULES, CLIENT, US, PASSWORD, "smtp.host.test", 465, "imap.host.test", "A quick question", 30)


def mail(sender, at, body, message_id="<r1@customer.test>", html=None):
    message = EmailMessage()
    message["From"], message["To"], message["Date"], message["Message-ID"] = sender, US, format_datetime(at), message_id
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def test_send_logs_in_and_sends_one_mail(email):
    sent_id = email.send(Interaction(**interaction("email"), subject="Your reports"))
    assert FakeSMTP.made == [("smtp.host.test", 465, 30)] and FakeSMTP.logins == [(US, PASSWORD)]
    (message,) = FakeSMTP.sent
    assert (message["From"], message["To"], message["Subject"]) == (US, CLIENT, "Your reports")
    assert message.get_content().strip() == "Hi Alex, which report is slowest?"
    assert sent_id == message["Message-ID"] and sent_id.endswith("@gmail.test>")  # our domain, not this PC's name


def test_send_without_subject_uses_the_default_subject(email):
    email.send(Interaction(**interaction("email")))
    assert FakeSMTP.sent[0]["Subject"] == "A quick question"


def test_payload_link_is_appended_once(email):
    link = {"url": "https://kb.example/erp-sync"}
    email.send(Interaction(**interaction("email", "Read this."), payload=link))
    email.send(Interaction(**interaction("email", "Read this: https://kb.example/erp-sync"), payload=link))
    first, second = [m.get_content().strip() for m in FakeSMTP.sent]
    assert first == "Read this.\nhttps://kb.example/erp-sync"
    assert second == "Read this: https://kb.example/erp-sync"


def test_email_rejects_another_channels_interaction(email):
    with pytest.raises(ValueError, match="sms.*email"):
        email.send(Interaction(**interaction("sms")))
    assert FakeSMTP.sent == []


def test_fetch_returns_replies_from_the_client_since(email):
    FakeIMAP.mails = [
        mail(CLIENT, NOW - timedelta(hours=1), "too early", "<old@customer.test>"),
        mail(f"Alex Carter <{CLIENT}>", NOW + timedelta(minutes=5), "Daily, mostly.", "<r1@customer.test>"),
        mail("someone@else.test", NOW + timedelta(minutes=6), "not the client", "<x@else.test>"),
    ]
    (reply,) = email.fetch_replies(NOW)
    assert (reply.id, reply.channel, reply.body) == ("<r1@customer.test>", "email", "Daily, mostly.")
    assert reply.received_at == NOW + timedelta(minutes=5)
    assert ("login", US, PASSWORD) in FakeIMAP.calls and ("select", "INBOX", True) in FakeIMAP.calls
    criteria = next(c[1] for c in FakeIMAP.calls if c[0] == "search")
    assert criteria[:2] == ("FROM", f'"{CLIENT}"') and criteria[2] == "SINCE" and criteria[3] == "15-Nov-2026"


def test_replies_come_back_oldest_first(email):
    FakeIMAP.mails = [mail(CLIENT, NOW + timedelta(minutes=9), "second", "<b@c.test>"),
                      mail(CLIENT, NOW + timedelta(minutes=2), "first", "<a@c.test>")]
    assert [r.body for r in email.fetch_replies(NOW)] == ["first", "second"]


@pytest.mark.parametrize("body", [
    "Daily, mostly.\n\nOn Mon, 16 Nov 2026 at 09:00, Assistant <us@gmail.test> wrote:\n> Hi Alex, which report is slowest?\n> Thanks",
    "Daily, mostly.\n\nEl lun, 16 nov 2026 a las 9:00, Assistant (<us@gmail.test>) escribió:\n> Hi Alex, which report is slowest?",
    "Daily, mostly.\n> Hi Alex, which report is slowest?",
])
def test_quoted_text_is_removed(email, body):
    FakeIMAP.mails = [mail(CLIENT, NOW, body)]
    assert [r.body for r in email.fetch_replies(NOW)] == ["Daily, mostly."]


def test_a_colon_at_the_end_of_the_clients_own_text_is_kept(email):
    FakeIMAP.mails = [mail(CLIENT, NOW, "These are slow:\n- stock report\n- weekly sales")]
    assert email.fetch_replies(NOW)[0].body == "These are slow:\n- stock report\n- weekly sales"


def test_plain_part_of_a_multipart_mail_and_non_ascii(email):
    FakeIMAP.mails = [mail(CLIENT, NOW, "Grüße 👍", html="<p>Gr&uuml;&szlig;e</p>")]
    assert email.fetch_replies(NOW)[0].body == "Grüße 👍"


def test_mail_without_text_is_skipped(email):
    empty = mail(CLIENT, NOW, "> only the quote of our own mail")
    FakeIMAP.mails = [empty]
    assert email.fetch_replies(NOW) == []


def test_login_failure_names_the_channel_not_the_password(email):
    FakeSMTP.fail = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    with pytest.raises(ChannelError, match="email") as e:
        email.send(Interaction(**interaction("email")))
    assert PASSWORD not in str(e.value)


def test_network_failure_while_reading_is_a_channel_error(email, monkeypatch):
    def down(host, timeout=None):
        raise OSError("network is unreachable")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", down)
    with pytest.raises(ChannelError, match="email.*replies"):
        email.fetch_replies(NOW)


# ---------- Twilio: SMS and WhatsApp ----------


class Sent:
    def __init__(self, sid, body="", date_sent=None):
        self.sid, self.body, self.date_sent = sid, body, date_sent


class FakeMessages:
    def __init__(self):
        self.created, self.listed, self.inbox, self.fail = [], [], [], None

    def create(self, **kwargs):
        if self.fail:
            raise self.fail
        self.created.append(kwargs)
        return Sent("SM123")

    def list(self, **kwargs):
        if self.fail:
            raise self.fail
        self.listed.append(kwargs)
        return self.inbox


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


SMS_RULES = ChannelRules(max_length=160, subject=False, links_ok=True)


def test_sms_send_calls_twilio():
    client = FakeClient()
    sid = SmsLive("sms", SMS_RULES, "+34 600 111 222", "+15550001111", client).send(Interaction(**interaction("sms", "Quick one, Alex")))
    assert sid == "SM123"
    assert client.messages.created == [{"from_": "+15550001111", "to": "+34600111222", "body": "Quick one, Alex"}]


def test_phone_numbers_keep_only_plus_and_digits():
    channel = SmsLive("sms", SMS_RULES, "+34-600 111.222", "+1 (555) 000-1111", FakeClient())
    assert (channel.address, channel.sender) == ("+34600111222", "+15550001111")


def test_whatsapp_adds_the_prefix_to_both_numbers():
    client = FakeClient()
    channel = WhatsAppLive("whatsapp", SMS_RULES, "+34 600 111 222", "+15550002222", client)
    channel.send(Interaction(**interaction("whatsapp", "Hi")))
    channel.fetch_replies(NOW)
    assert client.messages.created[0]["from_"] == "whatsapp:+15550002222"
    assert client.messages.created[0]["to"] == "whatsapp:+34600111222"
    assert client.messages.listed == [{"from_": "whatsapp:+34600111222", "to": "whatsapp:+15550002222", "date_sent_after": NOW}]


def test_twilio_payload_link_is_appended_once():
    client = FakeClient()
    channel = SmsLive("sms", SMS_RULES, "+34600111222", "+15550001111", client)
    link = {"url": "https://cal.example/alex"}
    channel.send(Interaction(**interaction("sms", "Call?"), payload=link))
    channel.send(Interaction(**interaction("sms", "Call? https://cal.example/alex"), payload=link))
    assert [c["body"] for c in client.messages.created] == ["Call?\nhttps://cal.example/alex", "Call? https://cal.example/alex"]


def test_fetch_asks_only_for_the_clients_messages():
    client = FakeClient()
    client.messages.inbox = [Sent("SM2", "second", NOW + timedelta(minutes=9)), Sent("SM1", "first", NOW + timedelta(minutes=2))]
    replies = SmsLive("sms", SMS_RULES, "+34600111222", "+15550001111", client).fetch_replies(NOW)
    assert client.messages.listed == [{"from_": "+34600111222", "to": "+15550001111", "date_sent_after": NOW}]
    assert [(r.id, r.channel, r.body, r.received_at) for r in replies] == [
        ("SM1", "sms", "first", NOW + timedelta(minutes=2)), ("SM2", "sms", "second", NOW + timedelta(minutes=9)),
    ]


def test_twilio_time_without_timezone_is_read_as_utc():
    client = FakeClient()
    client.messages.inbox = [Sent("SM1", "hi", (NOW + timedelta(minutes=2)).replace(tzinfo=None))]
    assert SmsLive("sms", SMS_RULES, "+34600111222", "+15550001111", client).fetch_replies(NOW)[0].received_at == NOW + timedelta(minutes=2)


def test_twilio_rejects_another_channels_interaction():
    client = FakeClient()
    with pytest.raises(ValueError, match="email.*sms"):
        SmsLive("sms", SMS_RULES, "+34600111222", "+15550001111", client).send(Interaction(**interaction("email")))
    assert client.messages.created == []


@pytest.mark.parametrize("action", ["send", "fetch"])
def test_twilio_error_names_the_channel_not_the_token_or_account(action, monkeypatch):
    from twilio.base.exceptions import TwilioRestException

    import sys

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)  # Twilio prints the URL then
    client = FakeClient()
    uri = "/2010-04-01/Accounts/ACsid/Messages.json"
    client.messages.fail = TwilioRestException(401, uri, "Authenticate", code=20003, method="POST")
    assert "ACsid" in str(client.messages.fail)  # the library's own text holds the account id
    channel = WhatsAppLive("whatsapp", SMS_RULES, "+34600111222", "+15550002222", client)
    with pytest.raises(ChannelError, match="whatsapp.*401.*20003.*Authenticate") as e:
        channel.send(Interaction(**interaction("whatsapp"))) if action == "send" else channel.fetch_replies(NOW)
    assert all(secret not in str(e.value) for secret in ("twilio-token-456", "ACsid", "\033"))


# ---------- review findings ----------


@pytest.mark.parametrize("body, expected", [
    # bottom-posting: the answer comes after the quote
    ("On Mon, 16 Nov 2026 at 09:00, Assistant <us@gmail.test> wrote:\n> Hi Alex, which report is slowest?\n\nDaily, mostly.", "Daily, mostly."),
    # inline: answers between quoted lines
    ("> How often?\nDaily.\n> Which report?\nSales.", "Daily.\nSales."),
    # Gmail splits a long attribution over two lines
    ("Daily, mostly.\n\nOn Mon, 16 Nov 2026 at 09:00, Pequod Test Account <\nus@gmail.test> wrote:\n\n> Hi Alex", "Daily, mostly."),
    # Outlook: no ">" at all
    ("Daily, mostly.\n\n-----Original Message-----\nFrom: Assistant <us@gmail.test>\nSent: Monday\nSubject: Reports\n\nHi Alex, which report is slowest?", "Daily, mostly."),
    ("Daily, mostly.\n\nFrom: Assistant <us@gmail.test>\nSent: Monday, 16 November 2026 09:00\nTo: Alex\nSubject: Reports\n\nHi Alex, which report is slowest?", "Daily, mostly."),
    ("Daily, mostly.\n\nDe: Assistant <us@gmail.test>\nEnviado el: lunes, 16 de noviembre de 2026 9:00\nPara: Alex\n\nHi Alex", "Daily, mostly."),
    # the client's own text
    ("Numbers below:\n>50% of the reports are late", "Numbers below:\n>50% of the reports are late"),
    ("From: the warehouse team we get the data late.", "From: the warehouse team we get the data late."),
])
def test_unquote_keeps_only_the_clients_words(body, expected):
    from pequod.channels.email import unquote

    assert unquote(body) == expected


def test_a_subject_with_line_breaks_is_sent_on_one_line(email):
    email.send(Interaction(**interaction("email"), subject="Your reports\nBcc: someone@else.test\n"))
    assert FakeSMTP.sent[0]["Subject"] == "Your reports Bcc: someone@else.test" and FakeSMTP.sent[0]["Bcc"] is None


def test_a_mail_that_cannot_be_read_is_skipped_not_fatal(email, caplog):
    no_date = mail(CLIENT, NOW, "no date")
    del no_date["Date"]
    no_id = mail(CLIENT, NOW, "no id")
    del no_id["Message-ID"]
    FakeIMAP.mails = [no_date, no_id, mail(CLIENT, NOW + timedelta(minutes=1), "fine", "<ok@c.test>")]
    assert [r.body for r in email.fetch_replies(NOW)] == ["fine"]
    assert caplog.text.count("skipped") == 2


def test_our_own_address_as_the_client_is_rejected(live):
    """A mail we send to ourselves lands in our inbox and would be read as the client's reply."""
    with pytest.raises(ValueError, match="pepe.*same"):
        build_channels(OmegaConf.create({"pepe": live.pepe}), {"work_email": {"platform": "email", "address": US.upper()}}, None, clock, ENV)
    with pytest.raises(ValueError, match="stephan.*same"):
        build_channels(OmegaConf.create({"stephan": live.stephan}), {"company_sms": {"platform": "sms", "address": "+1 555 000 1111"}}, None, clock, ENV)


def test_blank_credentials_count_as_missing(live):
    with pytest.raises(ValueError, match="EMAIL_APP_PASSWORD"):
        build_channels(live, PERSONA, None, clock, {**ENV, "EMAIL_APP_PASSWORD": "   "})


@pytest.mark.parametrize("address", ["x@example.com", "x@example.org", "someone@host.invalid", "+00-000-000", "+000 000 0000", ""])
def test_more_placeholder_addresses(address):
    from pequod.channels import placeholder

    assert placeholder(address)


@pytest.mark.parametrize("address", [CLIENT, "+34 600 111 222", "+1 555 010 0100", "a@northwind-labs.com"])
def test_real_looking_addresses_are_not_placeholders(address):
    from pequod.channels import placeholder

    assert not placeholder(address)


def test_twilio_messages_from_before_the_run_or_without_text_are_dropped():
    """Twilio's date filter may work by day; a media-only message has an empty body; a queued one has no date."""
    client = FakeClient()
    client.messages.inbox = [
        Sent("SM0", "join sandbox-code", NOW - timedelta(hours=2)),
        Sent("SM1", "", NOW + timedelta(minutes=1)),
        Sent("SM2", "not delivered yet", None),
        Sent("SM3", "the real reply", NOW + timedelta(minutes=2)),
    ]
    replies = SmsLive("sms", SMS_RULES, "+34600111222", "+15550001111", client).fetch_replies(NOW)
    assert [r.id for r in replies] == ["SM3"]


def test_a_link_that_is_only_the_start_of_another_link_is_still_added():
    from pequod.channels.base import text

    link = {"url": "https://x.co/a"}
    assert text(Interaction(**interaction("sms", "See https://x.co/abc"), payload=link)) == "See https://x.co/abc\nhttps://x.co/a"
    assert text(Interaction(**interaction("sms", "See https://x.co/a."), payload=link)) == "See https://x.co/a."
    assert text(Interaction(**interaction("sms", "See (https://x.co/a)"), payload=link)) == "See (https://x.co/a)"


def test_twilio_http_logging_is_quiet():
    """At INFO the library logs every URL (with the account id) and both phone numbers."""
    import logging

    import pequod.channels.sms  # noqa: F401

    assert logging.getLogger("twilio.http_client").level == logging.WARNING
