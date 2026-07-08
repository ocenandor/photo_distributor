"""Tests for privacy-preserving console diagnostics."""

from __future__ import annotations

import ast
from pathlib import Path

from loguru import logger

from app_logging import configure_logging, safe_exception_message
from face_analysis import FaceAnalysisError
from forms_export import FormsExportError
from utils import redact_personal_data
from yandex_disk import DiskApiError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
PRODUCTION_FACING_SCRIPTS = (
    PROJECT_ROOT / "scripts" / "probe_yandex_disk_ui_access.py",
)
PRIVATE_ARTIFACT_ROOTS = (
    ".env",
    "data/",
    "quality_lab/data/",
    "tests/downloads/",
)


def test_redact_personal_data_masks_email_and_oauth_token() -> None:
    message = "OAuth abc123 failed for participant@example.com"

    redacted = redact_personal_data(message)

    assert redacted == "OAuth <redacted> failed for <email>"


def test_disk_api_error_sanitizes_its_own_message() -> None:
    error = DiskApiError("OAuth abc123 failed for participant@example.com", status_code=403)

    assert str(error) == "OAuth <redacted> failed for <email>"
    assert error.safe_message() == "OAuth <redacted> failed for <email>"


def test_safe_exception_message_uses_domain_safe_message() -> None:
    class DomainError(Exception):
        def safe_message(self) -> str:
            return "safe domain message"

    assert safe_exception_message(DomainError("raw domain message")) == "safe domain message"


def test_safe_exception_message_redacts_plain_exception_fallback() -> None:
    error = ValueError("OAuth abc123 failed for participant@example.com")

    assert safe_exception_message(error) == "OAuth <redacted> failed for <email>"


def test_forms_export_error_owns_path_safe_diagnostic() -> None:
    error = FormsExportError(
        "Forms JSON export is invalid: C:/Users/pavel/Downloads/private.json",
        safe_message="Forms JSON export is invalid.",
    )

    assert "Downloads/private.json" in str(error)
    assert safe_exception_message(error) == "Forms JSON export is invalid."


def test_face_analysis_error_owns_path_safe_diagnostic() -> None:
    error = FaceAnalysisError(
        "OpenCV could not read image file: C:/Users/pavel/private/photo.jpg",
        safe_message="OpenCV could not read image file.",
    )

    assert "private/photo.jpg" in str(error)
    assert safe_exception_message(error) == "OpenCV could not read image file."


def test_configured_logging_redacts_sensitive_messages(tmp_path: Path) -> None:
    configure_logging(debug=True, log_dir=tmp_path)

    logger.info("OAuth abc123 failed for participant@example.com")

    log_text = (tmp_path / "photo_distributor.log").read_text(encoding="utf-8")
    assert "abc123" not in log_text
    assert "participant@example.com" not in log_text
    assert "OAuth <redacted> failed for <email>" in log_text
    assert "test_privacy:test_configured_logging_redacts_sensitive_messages" in log_text
    assert "test_privacy.py" not in log_text


def test_private_artifact_roots_are_ignored_and_documented() -> None:
    gitignore = _repo_text(".gitignore")
    agents = _repo_text("AGENTS.md")

    for root in PRIVATE_ARTIFACT_ROOTS:
        assert root in gitignore
        assert root in agents


def test_production_code_uses_logging_instead_of_print_diagnostics() -> None:
    checked_paths = tuple(SRC_ROOT.rglob("*.py")) + PRODUCTION_FACING_SCRIPTS

    for path in checked_paths:
        assert not _has_print_call(path), f"Use shared logging instead of print(): {path}"


def test_production_facing_scripts_use_shared_logging_setup() -> None:
    for path in PRODUCTION_FACING_SCRIPTS:
        source = path.read_text(encoding="utf-8")
        assert "configure_logging" in source
        assert "safe_exception_message" in source


def _repo_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _has_print_call(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print":
                return True
    return False
