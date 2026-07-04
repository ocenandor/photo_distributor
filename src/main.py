"""Command-line entry point for the photo distributor prototype."""

from __future__ import annotations

import argparse
from pathlib import Path

from app_logging import configure_logging, safe_exception_message
from face_analysis import FaceAnalysisError
from forms_export import FormsExportError
from loguru import logger
from photo_distribution_utils import (
    DEFAULT_SFACE_MODEL_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_YUNET_MODEL_PATH,
    DistributionConfig,
    cleanup_local_artifacts,
    run_distribution,
)
from yandex_disk import DiskApiError


RESULT_SUMMARY_LABELS = {
    "participants_count": "Participants",
    "reference_embeddings_count": "Reference embeddings",
    "event_photos_count": "Event photos",
    "event_faces_count": "Event faces",
    "face_matches_count": "Face matches",
    "planned_copies_count": "Planned copies",
    "copied_to_disk_count": "Copied to Yandex Disk",
    "quarantined_photos_count": "Quarantined photos",
    "local_artifacts_count": "Local artifacts",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the local distribution prototype.

    Returns:
        Parser configured with required Yandex Disk/form arguments plus model,
        threshold, cleanup, and logging options.
    """

    parser = argparse.ArgumentParser(
        prog="python src/main.py",
        description="Distribute Yandex Disk event photos by recognized participants.",
    )
    parser.add_argument(
        "event_folder",
        help="Yandex Disk path to the shared event photo folder.",
    )
    parser.add_argument(
        "form_id",
        help="Yandex Forms export folder id under /Yandex.Forms.",
    )
    parser.add_argument(
        "--yunet",
        type=Path,
        default=DEFAULT_YUNET_MODEL_PATH,
        help="Path to YuNet .onnx model.",
    )
    parser.add_argument(
        "--sface",
        type=Path,
        default=DEFAULT_SFACE_MODEL_PATH,
        help="Path to SFace .onnx model.",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help="Cosine similarity threshold for accepting face matches.",
    )
    parser.add_argument(
        "--cleanup-local",
        action="store_true",
        help="Remove local artifacts created by the distribution workflow after a successful run.",
    )
    parser.add_argument(
        "--debug-logs",
        action="store_true",
        help="Show debug logs in the console. Debug logs are always written to data/logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the photo distribution CLI.

    Args:
        argv: Optional command-line arguments. When `None`, argparse reads
            process arguments.

    Returns:
        Process exit code: `0` for success, `1` for runtime/API/data errors,
        and `2` for configuration errors.

    Side effects:
        Configures logging, reads environment variables, downloads/analyzes
        files, writes local artifacts, and copies photos on Yandex Disk.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(debug=args.debug_logs)

    try:
        logger.info("Starting photo distribution workflow.")
        result = run_distribution(
            args.event_folder,
            args.form_id,
            config=DistributionConfig(
                yunet_model_path=args.yunet,
                sface_model_path=args.sface,
                similarity_threshold=args.similarity_threshold,
            ),
        )
    except FormsExportError as exc:
        _log_error("Forms export error", exc)
        return 1
    except FaceAnalysisError as exc:
        _log_error("Face analysis error", exc)
        return 1
    except DiskApiError as exc:
        _log_error("Yandex Disk API error", exc)
        return 1
    except ValueError as exc:
        _log_error("Configuration error", exc)
        return 2

    logger.success("Distribution complete.")
    _log_result_summary(result.safe_summary())
    if args.cleanup_local:
        cleanup_local_artifacts(result)
        logger.info("Local workflow artifacts removed.")

    return 0


def _log_error(label: str, exc: Exception) -> None:
    """Log one command error through the safe exception-message contract."""

    logger.error("{}: {}", label, safe_exception_message(exc))


def _log_result_summary(summary: dict[str, object]) -> None:
    """Log public result counters without emitting local artifact paths."""

    for key, label in RESULT_SUMMARY_LABELS.items():
        if key in summary:
            logger.info("{}: {}", label, summary[key])


if __name__ == "__main__":
    raise SystemExit(main())
