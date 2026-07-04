"""Application logging setup."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING

from loguru import logger

from utils import redact_personal_data

if TYPE_CHECKING:
    from loguru import Record


DEFAULT_LOG_DIR = Path("data/logs")
DEFAULT_LOG_FILE = "photo_distributor.log"
CONSOLE_LOG_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{extra[source]}</cyan> | <level>{message}</level>"
)
FILE_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | "
    "{extra[source]} | {message}"
)


def configure_logging(*, debug: bool = False, log_dir: Path = DEFAULT_LOG_DIR) -> None:
    """Configure console and local-file logging for service commands.

    Args:
        debug: When true, console logging includes debug-level messages.
        log_dir: Local directory where rotating debug logs are written.

    Side effects:
        Removes default loguru sinks, creates `log_dir`, and adds one console
        sink plus one rotating local file sink. Messages are redacted before
        they are emitted.
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(patcher=_redact_record)
    logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        format=CONSOLE_LOG_FORMAT,
    )
    logger.add(
        log_dir / DEFAULT_LOG_FILE,
        level="DEBUG",
        rotation="1 MB",
        retention=5,
        encoding="utf-8",
        format=FILE_LOG_FORMAT,
    )


def safe_exception_message(exc: Exception) -> str:
    """Return an exception message intended for logs and console diagnostics.

    Args:
        exc: Exception raised by a command or workflow.

    Returns:
        A redacted `exc.safe_message()` when the exception type owns a
        privacy-safe diagnostic method, otherwise a redacted `str(exc)`. Log
        sinks still apply the last-resort redactor before emission.
    """

    safe_message = getattr(exc, "safe_message", None)
    if callable(safe_message):
        return redact_personal_data(safe_message())
    return redact_personal_data(exc)


def _redact_record(record: Record) -> None:
    """Apply source formatting and last-resort redaction before emission."""

    record["extra"]["source"] = _source_label(record)
    record["message"] = redact_personal_data(record["message"])


def _source_label(record: Record) -> str:
    """Return a compact package/module/function label for one log record."""

    name = record["name"] or record["module"]
    function = record["function"]
    parts = [part for part in name.split(".") if part]
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[-1]}:{function}"
    module = str(record["module"])
    return f"{module}:{function}"
