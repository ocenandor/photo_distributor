"""Tests for the generic IMAP/SMTP mail client."""

from __future__ import annotations

from email.message import EmailMessage

import mail_client.client as client_module
from mail_client import MailClient, MailClientConfig


def test_fetch_messages_selects_forms_folder_and_extracts_attachments(monkeypatch) -> None:
    fake_imap = _FakeIMAP(_raw_message())
    monkeypatch.setattr(client_module.imaplib, "IMAP4_SSL", lambda host, port, timeout=None: fake_imap)

    mail = MailClient(_config())

    messages = mail.fetch_messages()

    assert fake_imap.selected_folder == "Yandex.Forms"
    assert len(messages) == 1
    assert messages[0].uid == "1"
    assert messages[0].subject == "Answer subject"
    assert "Accept: Да" in messages[0].body
    assert messages[0].attachments[0].filename == "reference.jpg"
    assert messages[0].attachments[0].content == b"image-bytes"


def test_fetch_messages_extracts_html_only_forms_body(monkeypatch) -> None:
    fake_imap = _FakeIMAP(_raw_html_message())
    monkeypatch.setattr(client_module.imaplib, "IMAP4_SSL", lambda host, port, timeout=None: fake_imap)

    mail = MailClient(_config())

    messages = mail.fetch_messages()

    assert "Accept: Да" in messages[0].body
    assert "Name: Test" in messages[0].body
    assert "Email: participant@example.com" in messages[0].body


def test_send_message_uses_smtp_transport(monkeypatch) -> None:
    fake_smtp = _FakeSMTP()
    monkeypatch.setattr(client_module.smtplib, "SMTP_SSL", lambda host, port, timeout=None: fake_smtp)
    mail = MailClient(_config())

    mail.send_message(
        to_email="participant@example.com",
        subject="Access",
        body="Folder link",
    )

    assert fake_smtp.logged_in == ("user@example.com", "secret")
    assert len(fake_smtp.sent_messages) == 1
    assert fake_smtp.sent_messages[0]["To"] == "participant@example.com"
    assert fake_smtp.sent_messages[0]["Subject"] == "Access"


def test_mail_client_config_reads_forms_folder_override(monkeypatch) -> None:
    monkeypatch.setenv("MAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("MAIL_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_FROM", "")
    monkeypatch.setenv("MAIL_ADMIN_EMAIL", "")
    monkeypatch.setenv("MAIL_FORMS_FOLDER", "Custom.Forms")

    config = MailClientConfig.from_env()

    assert config.forms_folder == "Custom.Forms"
    assert config.admin_email == "user@example.com"


def test_mail_client_config_reads_admin_email_override(monkeypatch) -> None:
    monkeypatch.setenv("MAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("MAIL_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_FROM", "user@example.com")
    monkeypatch.setenv("MAIL_ADMIN_EMAIL", "admin@example.com")

    config = MailClientConfig.from_env()

    assert config.admin_email == "admin@example.com"


class _FakeIMAP:
    """Small context-manager fake for IMAP reads."""

    def __init__(self, raw_message: bytes) -> None:
        self.raw_message = raw_message
        self.selected_folder = ""

    def __enter__(self) -> "_FakeIMAP":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        assert username == "user@example.com"
        assert password == "secret"

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        assert readonly is True
        self.selected_folder = folder
        return "OK", []

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        if command == "search":
            assert args == ("ALL",)
            return "OK", [b"1"]
        if command == "fetch":
            return "OK", [(b"1 (RFC822)", self.raw_message)]
        raise AssertionError(f"Unexpected IMAP command: {command}")


class _FakeSMTP:
    """Small context-manager fake for SMTP sends."""

    def __init__(self) -> None:
        self.logged_in: tuple[str, str] | None = None
        self.sent_messages: list[EmailMessage] = []

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent_messages.append(message)


def _config() -> MailClientConfig:
    """Return a deterministic mail-client config."""

    return MailClientConfig(
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="user@example.com",
        password="secret",
        mail_from="user@example.com",
        admin_email="admin@example.com",
        forms_folder="Yandex.Forms",
    )


def _raw_message() -> bytes:
    """Return one MIME message with a text body and image attachment."""

    message = EmailMessage()
    message["From"] = "forms@example.com"
    message["To"] = "user@example.com"
    message["Subject"] = "Answer subject"
    message.set_content("Accept: Да\nName: Test\nEmail: participant@example.com\n")
    message.add_attachment(
        b"image-bytes",
        maintype="image",
        subtype="jpeg",
        filename="reference.jpg",
    )
    return message.as_bytes()


def _raw_html_message() -> bytes:
    """Return one MIME message with only a text/html form-answer body."""

    message = EmailMessage()
    message["From"] = "forms@example.com"
    message["To"] = "user@example.com"
    message["Subject"] = "Answer subject"
    message.set_content(
        "<html><body><pre>Accept: Да\nName: Test\nEmail: participant@example.com</pre></body></html>",
        subtype="html",
    )
    message.add_attachment(
        b"image-bytes",
        maintype="image",
        subtype="jpeg",
        filename="reference.jpg",
    )
    return message.as_bytes()
