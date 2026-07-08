"""IMAP/SMTP mail client used by live event workflows."""

from __future__ import annotations

import imaplib
import html
import os
import re
import smtplib
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from typing import cast

from dotenv import load_dotenv

from utils import redact_personal_data


DEFAULT_FORMS_MAIL_FOLDER = "Yandex.Forms"


class MailClientError(RuntimeError):
    """Raised when mail transport configuration or I/O fails."""

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        """Create a mail error with a privacy-safe message override."""

        super().__init__(redact_personal_data(message))
        self._safe_message = safe_message

    def safe_message(self) -> str:
        """Return a message safe for logs and console diagnostics."""

        return self._safe_message or str(self)


@dataclass(frozen=True)
class MailAttachment:
    """Generic email attachment returned by the mail client.

    Attributes:
        filename: Attachment file name, generated when the message omits one.
        content: Raw attachment bytes.
        content_type: Attachment MIME content type.
    """

    filename: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class MailMessage:
    """Generic email message returned by the mail client.

    Attributes:
        uid: IMAP uid used for run-local deduplication.
        subject: Decoded email subject.
        body: Plain text body extracted from the message.
        sender: Sender header value when present.
        attachments: Generic attachments from the message.
    """

    uid: str
    subject: str
    body: str
    sender: str
    attachments: tuple[MailAttachment, ...]


@dataclass(frozen=True, repr=False)
class MailClientConfig:
    """Configuration for IMAP/SMTP access.

    Attributes:
        imap_host: IMAP server host.
        imap_port: IMAP SSL port.
        smtp_host: SMTP server host.
        smtp_port: SMTP SSL or STARTTLS port.
        username: Mailbox login.
        password: Mailbox app password. Hidden from `repr`.
        mail_from: Sender address for notifications.
        admin_email: Recipient address for local operator alerts.
        forms_folder: IMAP folder that contains Yandex Forms emails.
        timeout_seconds: Network timeout for IMAP/SMTP operations.
    """

    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password: str = field(repr=False)
    mail_from: str
    admin_email: str
    forms_folder: str = DEFAULT_FORMS_MAIL_FOLDER
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "MailClientConfig":
        """Build mail configuration from `.env` and process environment."""

        load_dotenv()
        values = {
            "imap_host": os.environ.get("MAIL_IMAP_HOST", ""),
            "imap_port": _env_int("MAIL_IMAP_PORT", 993),
            "smtp_host": os.environ.get("MAIL_SMTP_HOST", ""),
            "smtp_port": _env_int("MAIL_SMTP_PORT", 465),
            "username": os.environ.get("MAIL_USERNAME", ""),
            "password": os.environ.get("MAIL_PASSWORD", ""),
            "mail_from": os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME", ""),
            "admin_email": (
                os.environ.get("MAIL_ADMIN_EMAIL")
                or os.environ.get("MAIL_FROM")
                or os.environ.get("MAIL_USERNAME", "")
            ),
            "forms_folder": os.environ.get("MAIL_FORMS_FOLDER", DEFAULT_FORMS_MAIL_FOLDER),
            "timeout_seconds": _env_int("MAIL_TIMEOUT_SECONDS", 30),
        }
        missing = [
            name
            for name in (
                "imap_host",
                "smtp_host",
                "username",
                "password",
                "mail_from",
                "admin_email",
            )
            if not values[name]
        ]
        if missing:
            raise MailClientError(
                f"Missing mail configuration values: {', '.join(missing)}",
                safe_message="Mail client configuration is incomplete.",
            )
        return cls(**values)


class MailClient:
    """Small IMAP/SMTP client for reading form emails and sending notices."""

    def __init__(self, config: MailClientConfig) -> None:
        """Create a mail client from explicit configuration."""

        self.config = config

    @classmethod
    def from_env(cls) -> "MailClient":
        """Create a mail client from environment variables."""

        return cls(MailClientConfig.from_env())

    def fetch_messages(self, *, folder: str | None = None) -> tuple[MailMessage, ...]:
        """Read messages from one IMAP folder.

        Args:
            folder: IMAP folder to select. Defaults to configured forms folder.

        Returns:
            Messages from the selected folder in IMAP uid order.

        Raises:
            MailClientError: If IMAP login, folder selection, search, or fetch
                fails.
        """

        selected_folder = folder or self.config.forms_folder
        try:
            with imaplib.IMAP4_SSL(
                self.config.imap_host,
                self.config.imap_port,
                timeout=self.config.timeout_seconds,
            ) as imap:
                imap.login(self.config.username, self.config.password)
                status, _ = imap.select(selected_folder, readonly=True)
                if status != "OK":
                    raise MailClientError("Could not select forms mail folder.")
                status, search_data = imap.uid("search", "ALL")
                if status != "OK":
                    raise MailClientError("Could not search forms mail folder.")
                uids = search_data[0].split() if search_data and search_data[0] else []
                return tuple(self._fetch_one(imap, uid.decode("ascii")) for uid in uids)
        except MailClientError:
            raise
        except OSError as exc:
            raise MailClientError("Mail IMAP request failed.") from exc
        except imaplib.IMAP4.error as exc:
            raise MailClientError("Mail IMAP request failed.") from exc

    def send_message(self, *, to_email: str, subject: str, body: str) -> None:
        """Send one plain-text notification email.

        Args:
            to_email: Recipient email address.
            subject: Notification subject.
            body: Plain text notification body.

        Side effects:
            Sends one email through configured SMTP.
        """

        message = EmailMessage()
        message["From"] = self.config.mail_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        try:
            if self.config.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    self.config.smtp_host,
                    self.config.smtp_port,
                    timeout=self.config.timeout_seconds,
                ) as smtp:
                    smtp.login(self.config.username, self.config.password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(
                    self.config.smtp_host,
                    self.config.smtp_port,
                    timeout=self.config.timeout_seconds,
                ) as smtp:
                    smtp.starttls()
                    smtp.login(self.config.username, self.config.password)
                    smtp.send_message(message)
        except smtplib.SMTPException as exc:
            raise MailClientError("Mail SMTP request failed.") from exc
        except OSError as exc:
            raise MailClientError("Mail SMTP request failed.") from exc

    def _fetch_one(self, imap: imaplib.IMAP4_SSL, uid: str) -> MailMessage:
        """Fetch and parse one message by IMAP uid."""

        status, fetch_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK":
            raise MailClientError("Could not fetch forms mail message.")
        raw = _raw_message_bytes(fetch_data)
        parsed = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(raw))
        return MailMessage(
            uid=uid,
            subject=str(parsed.get("subject", "")),
            body=_plain_text_body(parsed),
            sender=str(parsed.get("from", "")),
            attachments=_attachments(parsed),
        )


def _env_int(name: str, default: int) -> int:
    """Read one integer environment value."""

    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise MailClientError(
            f"Mail configuration value must be an integer: {name}",
            safe_message="Mail client configuration is invalid.",
        ) from exc


def _raw_message_bytes(fetch_data: list[object]) -> bytes:
    """Extract RFC822 bytes from an IMAP fetch response."""

    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise MailClientError("Mail message fetch response did not contain RFC822 bytes.")


def _plain_text_body(message: Message) -> str:
    """Extract the best plain-text body from an email message."""

    html_body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/html" and not html_body:
                html_body = _decoded_text_payload(part)
        if html_body:
            return _html_to_text(html_body)
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if message.get_content_type() == "text/html":
            return _html_to_text(text)
        return text
    raw_payload = message.get_payload()
    if not isinstance(raw_payload, str):
        return ""
    if message.get_content_type() == "text/html":
        return _html_to_text(raw_payload)
    return raw_payload


def _attachments(message: EmailMessage) -> tuple[MailAttachment, ...]:
    """Return generic attachment records from a parsed email message."""

    attachments: list[MailAttachment] = []
    for index, part in enumerate(message.iter_attachments(), start=1):
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        filename = part.get_filename() or f"attachment_{index:02d}"
        attachments.append(
            MailAttachment(
                filename=filename,
                content=payload,
                content_type=part.get_content_type(),
            )
        )
    return tuple(attachments)


def _decoded_text_payload(part: Message) -> str:
    """Decode a text MIME part into Unicode."""

    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    raw_payload = part.get_payload()
    return raw_payload if isinstance(raw_payload, str) else ""


def _html_to_text(value: str) -> str:
    """Convert simple HTML email bodies into text for form-field parsing."""

    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\r\n", "\n").replace("\r", "\n").strip()
