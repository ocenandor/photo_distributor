"""Tests for privacy-preserving console diagnostics."""

from __future__ import annotations

from privacy import redact_personal_data


def test_redact_personal_data_masks_email_and_oauth_token() -> None:
    message = "OAuth abc123 failed for participant@example.com"

    redacted = redact_personal_data(message)

    assert redacted == "OAuth <redacted> failed for <email>"
