"""Command-line entry point for the live event runner."""

from __future__ import annotations

import argparse

from app_logging import configure_logging, safe_exception_message
from face_analysis import FaceAnalysisError
from forms_export import FormsExportError
from loguru import logger
from mail_client import MailClientError
from photo_distribution_utils import (
    DEFAULT_EVENT_POLL_SECONDS,
    DEFAULT_FORM_POLL_SECONDS,
    DistributionConfig,
    LiveEventConfig,
    run_live_event,
)
from yandex_disk import DiskApiError, YandexDiskUiError


LIVE_RESULT_SUMMARY_LABELS = {
    "iterations_count": "Iterations",
    "participants_count": "Participants",
    "event_photos_count": "Event photos",
    "copied_to_disk_count": "Copied to Yandex Disk",
    "local_artifacts_count": "Local artifacts",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the live event runner.

    Returns:
        Parser configured with form id, optional cloud event folder path, polling,
        cleanup,
        and logging options.
    """

    parser = argparse.ArgumentParser(
        prog="python src/start_event.py",
        description="Start a live Yandex Disk event photo distribution runner.",
    )
    parser.add_argument(
        "form_id",
        help="Yandex Forms id expected in answer email subjects.",
    )
    parser.add_argument(
        "cloud_event_folder",
        nargs="?",
        help=(
            "Optional canonical Yandex Disk event folder path, for example "
            "`/event_001`. A unique path is generated when omitted."
        ),
    )
    parser.add_argument(
        "--event-poll-seconds",
        type=int,
        default=DEFAULT_EVENT_POLL_SECONDS,
        help="Seconds between Yandex Disk event-folder checks.",
    )
    parser.add_argument(
        "--form-poll-seconds",
        type=int,
        default=DEFAULT_FORM_POLL_SECONDS,
        help=(
            "Seconds between form-source checks. Each check reads the forms "
            "mail folder and the optional Yandex Disk JSON export folder."
        ),
    )
    parser.add_argument(
        "--cleanup-local",
        action="store_true",
        help="Remove local artifacts created by the live workflow when the runner stops.",
    )
    parser.add_argument(
        "--debug-logs",
        action="store_true",
        help="Show debug logs in the console. Debug logs are always written to data/logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the live event CLI.

    Args:
        argv: Optional command-line arguments. When `None`, argparse reads
            process arguments.

    Returns:
        Process exit code: `0` for normal stop, `1` for runtime/API/data
        errors, and `2` for configuration errors.

    Side effects:
        Configures logging, starts the live mail/Yandex Disk workflow, and logs
        only privacy-safe summaries.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(debug=args.debug_logs)

    try:
        logger.info("Starting live event workflow.")
        result = run_live_event(
            args.form_id,
            args.cloud_event_folder,
            config=LiveEventConfig(
                event_poll_seconds=args.event_poll_seconds,
                form_poll_seconds=args.form_poll_seconds,
                cleanup_local=args.cleanup_local,
                distribution_config=DistributionConfig(),
            ),
        )
    except FormsExportError as exc:
        _log_error("Forms email error", exc)
        return 1
    except FaceAnalysisError as exc:
        _log_error("Face analysis error", exc)
        return 1
    except DiskApiError as exc:
        _log_error("Yandex Disk API error", exc)
        return 1
    except MailClientError as exc:
        _log_error("Mail client error", exc)
        return 1
    except YandexDiskUiError as exc:
        _log_error("Yandex Disk UI automation error", exc)
        return 1
    except ValueError as exc:
        _log_error("Configuration error", exc)
        return 2

    logger.success("Live event workflow stopped.")
    _log_result_summary(result.safe_summary())
    return 0


def _log_error(label: str, exc: Exception) -> None:
    """Log one command error through the safe exception-message contract."""

    logger.error("{}: {}", label, safe_exception_message(exc))


def _log_result_summary(summary: dict[str, object]) -> None:
    """Log public live runner counters without emitting local paths."""

    for key, label in LIVE_RESULT_SUMMARY_LABELS.items():
        if key in summary:
            logger.info("{}: {}", label, summary[key])


if __name__ == "__main__":
    raise SystemExit(main())
