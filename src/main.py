"""Command-line entry point for the photo distributor prototype."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from face_analysis import FaceAnalysisError
from forms_export import FormsExportError
from photo_distribution import DistributionConfig, cleanup_local_artifacts, run_distribution
from photo_distribution.workflow import (
    DEFAULT_SFACE_MODEL_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_YUNET_MODEL_PATH,
)
from privacy import redact_personal_data
from yandex_disk import DiskApiError, YandexDiskClient


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        client = YandexDiskClient.from_env()
        result = run_distribution(
            client,
            args.event_folder,
            args.form_id,
            config=DistributionConfig(
                yunet_model_path=args.yunet,
                sface_model_path=args.sface,
                similarity_threshold=args.similarity_threshold,
            ),
        )
    except ValueError as exc:
        _print_error("Configuration error", exc)
        return 2
    except FormsExportError as exc:
        _print_error("Forms export error", exc)
        return 1
    except FaceAnalysisError as exc:
        _print_error("Face analysis error", exc)
        return 1
    except DiskApiError as exc:
        _print_error("Yandex Disk API error", exc)
        return 1

    print("Distribution complete.")
    print(f"Participants: {result.participants_count}")
    print(f"Reference embeddings: {result.reference_embeddings_count}")
    print(f"Event photos: {result.event_photos_count}")
    print(f"Event faces: {result.event_faces_count}")
    print(f"Face matches: {result.face_matches_count}")
    print(f"Planned copies: {result.planned_copies_count}")
    print(f"Copied to Yandex Disk: {result.copied_to_disk_count}")
    print(f"Quarantined photos: {result.quarantined_photos_count}")
    print(f"Database: {result.database_path}")
    print(f"Local distribution: {result.local_distribution_path}")
    if args.cleanup_local:
        cleanup_local_artifacts(result)
        print("Local workflow artifacts removed.")

    return 0


def _print_error(label: str, exc: Exception) -> None:
    print(f"{label}: {redact_personal_data(exc)}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
