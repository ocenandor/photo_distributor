"""Shared utility helpers for service diagnostics."""

from __future__ import annotations

import re


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
OAUTH_PATTERN = re.compile(r"\bOAuth\s+[A-Za-z0-9._~+/=-]+\b")


def redact_personal_data(value: object) -> str:
    """Return a conservatively redacted logging/diagnostic string.

    Args:
        value: Diagnostic value that may contain personal data or credentials.

    Returns:
        Text with obvious email addresses and OAuth token strings replaced.
    """

    text = str(value)
    text = EMAIL_PATTERN.sub("<email>", text)
    return OAUTH_PATTERN.sub("OAuth <redacted>", text)
