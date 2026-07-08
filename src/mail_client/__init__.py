"""Mail integration module."""

from .client import MailAttachment, MailClient, MailClientConfig, MailClientError, MailMessage

__all__ = [
    "MailAttachment",
    "MailClient",
    "MailClientConfig",
    "MailClientError",
    "MailMessage",
]
