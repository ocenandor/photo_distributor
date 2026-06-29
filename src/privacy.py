"""Helpers for keeping console output free of personal data."""

from __future__ import annotations

import re


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
OAUTH_PATTERN = re.compile(r"\bOAuth\s+[A-Za-z0-9._~+/=-]+\b")


def redact_personal_data(value: object) -> str:
    """Return a string safe enough for console diagnostics."""

    text = str(value)
    text = EMAIL_PATTERN.sub("<email>", text)
    return OAUTH_PATTERN.sub("OAuth <redacted>", text)
