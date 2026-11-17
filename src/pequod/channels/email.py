"""EmailMock + EmailLive."""

import email
import email.policy
import imaplib
import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr, parsedate_to_datetime

from pequod.channels.base import Channel, ChannelError, MockChannel, text
from pequod.types import ChannelRules, Interaction, Reply

log = logging.getLogger(__name__)

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # IMAP wants English
QUOTE = re.compile(r">+( |$)")  # a quoted line; ">50%" is the persona's own text
ORIGINAL = re.compile(r"-+ ?(original message|mensaje original|ursprüngliche nachricht) ?-+", re.IGNORECASE)
FROM = ("from:", "de:", "von:")  # first line of the header block that Outlook puts above the original
SENT = ("sent:", "date:", "enviado", "fecha:", "gesendet:", "datum:")


class EmailMock(MockChannel):
    platform = "email"


def unquote(body: str) -> str:
    """The persona's own words, without the original message that mail programs add to a reply:
    quoted lines ("> ..."), the "On ... wrote:" line before them, and everything from an
    "Original Message" line or an Outlook header block (From: / Sent:) on."""
    lines = body.strip().splitlines()
    for i, line in enumerate(lines):
        low = line.strip().lower()
        block = low.startswith(FROM) and any(l.strip().lower().startswith(SENT) for l in lines[i + 1 : i + 4])
        if ORIGINAL.fullmatch(low) or block:
            lines = lines[:i]
            break
    first = next((i for i, line in enumerate(lines) if QUOTE.match(line)), None)
    if first is not None:
        before = lines[:first]
        while before and not before[-1].strip():
            before.pop()
        if before and before[-1].rstrip().endswith(":"):  # "On Mon, ... wrote:" / "El lun, ... escribió:"
            before.pop()
            if before and before[-1].rstrip().endswith("<"):  # ... split over two lines before a long address
                before.pop()
        lines = before + [line for line in lines[first:] if not QUOTE.match(line)]
    return "\n".join(lines).strip()


class EmailLive(Channel):
    """Real email through an SMTP server (send) and an IMAP mailbox (read), e.g. Gmail with an app password."""

    platform = "email"

    def __init__(
        self, name: str, rules: ChannelRules, address: str, user: str, password: str,
        smtp_host: str, smtp_port: int, imap_host: str, default_subject: str, timeout_s: float,
    ) -> None:
        super().__init__(name, rules)
        self.address = address  # the persona
        self.user, self.password = user, password  # our mailbox
        self.smtp_host, self.smtp_port, self.imap_host = smtp_host, smtp_port, imap_host
        self.default_subject = default_subject
        self.timeout_s = timeout_s

    @classmethod
    def from_config(cls, name: str, rules: ChannelRules, address: str, settings: dict, secrets: dict[str, str]) -> "EmailLive":
        return cls(name, rules, address, **secrets, **settings)

    def send(self, interaction: Interaction) -> str:
        self.accept(interaction)
        try:
            message = EmailMessage()
            message["From"], message["To"] = self.user, self.address
            message["Subject"] = " ".join((interaction.subject or self.default_subject).split())  # one line, always
            message["Message-ID"] = make_msgid(domain=self.user.split("@")[-1])
            message.set_content(text(interaction))
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout_s) as smtp:
                smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError, ValueError) as e:
            raise ChannelError(f"email: could not send to {self.address}: {type(e).__name__}: {e}") from e
        return message["Message-ID"]

    def fetch_replies(self, since: datetime) -> list[Reply]:
        day = since.astimezone(timezone.utc) - timedelta(days=1)  # IMAP searches by day in the server's zone
        replies = []
        try:
            with imaplib.IMAP4_SSL(self.imap_host, timeout=self.timeout_s) as imap:
                imap.login(self.user, self.password)
                imap.select("INBOX", readonly=True)
                _, found = imap.search(None, "FROM", f'"{self.address}"', "SINCE", f"{day.day}-{MONTHS[day.month - 1]}-{day.year}")
                for number in found[0].split():
                    _, parts = imap.fetch(number, "(RFC822)")
                    try:
                        reply = self._read(parts[0][1])
                    except (ValueError, LookupError, TypeError) as e:  # no date, no id, unknown charset, ...
                        log.warning("email: a mail from the persona could not be read and was skipped (%s)", type(e).__name__)
                        continue
                    if reply and reply.received_at >= since:
                        replies.append(reply)
        except (imaplib.IMAP4.error, OSError) as e:
            raise ChannelError(f"email: could not read replies: {type(e).__name__}: {e}") from e
        return sorted(replies, key=lambda r: r.received_at)

    def _read(self, raw: bytes) -> Reply | None:
        """One mail as a Reply; None when it is not from the persona or has no text of its own."""
        mail = email.message_from_bytes(raw, policy=email.policy.default)
        if parseaddr(mail["From"] or "")[1].lower() != self.address.lower():
            return None
        at = parsedate_to_datetime(mail["Date"])
        part = mail.get_body(preferencelist=("plain",))
        body = unquote(part.get_content()) if part else ""
        if not body:
            return None
        return Reply(
            id=mail["Message-ID"], channel=self.name, body=body,
            received_at=at if at.tzinfo else at.replace(tzinfo=timezone.utc),
        )
