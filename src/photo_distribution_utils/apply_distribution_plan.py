"""Apply the prepared output distribution plan and describe run results."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from forms_export.ingest import DEFAULT_DATA_DIR
from .output_files_structure import CopyPlanRecord, DistributionOutputFolders, join_disk_path
from yandex_disk import YandexDiskClient


DEFAULT_YUNET_MODEL_PATH = Path("data/models/face_detection_yunet_2023mar.onnx")
DEFAULT_SFACE_MODEL_PATH = Path("data/models/face_recognition_sface_2021dec.onnx")
DEFAULT_EVENT_PHOTOS_DIR = Path("data/event_photos")
DEFAULT_COPY_PLANS_DIR = Path("data/distribution_plans")
DEFAULT_SIMILARITY_THRESHOLD = 0.45
DEFAULT_QUARANTINE_FOLDER_NAME = "quarantine"


@dataclass(frozen=True, repr=False)
class DistributionConfig:
    """Configuration for one distribution workflow run.

    Attributes:
        forms_data_dir: Local root where forms exports and reference images are
            downloaded.
        event_photos_dir: Local root where source event photos are downloaded
            before face analysis.
        copy_plans_dir: Local root where distribution copy-plan JSON artifacts
            are written.
        yunet_model_path: OpenCV YuNet detector model path.
        sface_model_path: OpenCV SFace recognizer model path.
        similarity_threshold: Minimum embedding similarity required to accept a
            reference/event face match.
        quarantine_folder_name: Output folder name for photos without accepted
            participant matches.
    """

    forms_data_dir: Path = DEFAULT_DATA_DIR
    event_photos_dir: Path = DEFAULT_EVENT_PHOTOS_DIR
    copy_plans_dir: Path = DEFAULT_COPY_PLANS_DIR
    yunet_model_path: Path = DEFAULT_YUNET_MODEL_PATH
    sface_model_path: Path = DEFAULT_SFACE_MODEL_PATH
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    quarantine_folder_name: str = DEFAULT_QUARANTINE_FOLDER_NAME

    def safe_summary(self) -> dict[str, object]:
        """Return configuration fields that are safe to emit in logs.

        Full local paths are intentionally omitted because custom paths may
        contain user names or private event names.
        """

        return {
            "similarity_threshold": self.similarity_threshold,
            "quarantine_folder_name": self.quarantine_folder_name,
            "yunet_model_file": self.yunet_model_path.name,
            "sface_model_file": self.sface_model_path.name,
        }

    def __repr__(self) -> str:
        """Return a path-safe representation for accidental diagnostics."""

        return _safe_object_repr(type(self).__name__, self.safe_summary())


@dataclass(frozen=True, repr=False)
class DistributionCounters:
    """Numeric counters produced by one completed distribution workflow run.

    Attributes:
        participants_count: Number of consented participants imported from the
            forms export.
        reference_embeddings_count: Number of detected reference faces stored
            as embeddings.
        event_photos_count: Number of source event photos downloaded and
            processed.
        event_faces_count: Number of event faces detected across all event
            photos.
        face_matches_count: Number of accepted reference/event face matches.
            Multiple matches may belong to the same photo.
        planned_copies_count: Number of photo copy operations planned locally.
        copied_to_disk_count: Number of planned copy operations applied to
            Yandex Disk.
        quarantined_photos_count: Number of event photos with no accepted
            participant matches.
    """

    participants_count: int
    reference_embeddings_count: int
    event_photos_count: int
    event_faces_count: int
    face_matches_count: int
    planned_copies_count: int
    copied_to_disk_count: int
    quarantined_photos_count: int

    def safe_summary(self) -> dict[str, object]:
        """Return counters safe for logs and console summaries."""

        return {
            "participants_count": self.participants_count,
            "reference_embeddings_count": self.reference_embeddings_count,
            "event_photos_count": self.event_photos_count,
            "event_faces_count": self.event_faces_count,
            "face_matches_count": self.face_matches_count,
            "planned_copies_count": self.planned_copies_count,
            "copied_to_disk_count": self.copied_to_disk_count,
            "quarantined_photos_count": self.quarantined_photos_count,
        }

    def __repr__(self) -> str:
        """Return a representation made only from public counters."""

        return _safe_object_repr(type(self).__name__, self.safe_summary())


@dataclass(frozen=True, repr=False)
class DistributionArtifacts:
    """Local artifact paths produced by one distribution workflow run.

    Attributes:
        copy_plan_path: Local JSON file containing the planned remote Yandex
            Disk copy operations for the run.
        local_artifact_paths: Local files or directories created by the main
            workflow and eligible for removal by `cleanup_local_artifacts()`.
    """

    copy_plan_path: Path
    local_artifact_paths: tuple[Path, ...]

    def safe_summary(self) -> dict[str, object]:
        """Return non-path artifact diagnostics safe for logs."""

        return {
            "local_artifacts_count": len(self.local_artifact_paths),
        }

    def __repr__(self) -> str:
        """Return a path-safe representation for accidental diagnostics."""

        return _safe_object_repr(type(self).__name__, self.safe_summary())


@dataclass(frozen=True, repr=False)
class DistributionResult:
    """Grouped result of one completed distribution workflow run.

    Attributes:
        counts: Numeric workflow counters.
        artifacts: Local paths produced by the workflow.
    """

    counts: DistributionCounters
    artifacts: DistributionArtifacts

    def safe_summary(self) -> dict[str, object]:
        """Return path-safe counters and artifact diagnostics for logs."""

        return {
            **self.counts.safe_summary(),
            **self.artifacts.safe_summary(),
        }

    def __repr__(self) -> str:
        """Return a path-safe representation for accidental diagnostics."""

        return _safe_object_repr(type(self).__name__, self.safe_summary())


@dataclass(frozen=True)
class DistributionPlanApplyResult:
    """Summary of applying an output distribution plan on Yandex Disk.

    Attributes:
        copied_to_disk_count: Number of plan records successfully copied on
            Yandex Disk.
    """

    copied_to_disk_count: int


def cleanup_local_artifacts(result: DistributionResult) -> None:
    """Remove local files created by the main distribution workflow.

    Args:
        result: Distribution result containing artifact paths to remove.

    Raises:
        ValueError: If an artifact path is outside the project `data` folder.

    Side effects:
        Deletes local files/directories listed in
        `result.artifacts.local_artifact_paths`.
    """

    for path in result.artifacts.local_artifact_paths:
        _remove_local_artifact(path)


def apply_distribution_plan(
    distribution_plan: tuple[CopyPlanRecord, ...],
    *,
    disk_client: YandexDiskClient,
    output_folders: DistributionOutputFolders,
    event_folder: str,
) -> DistributionPlanApplyResult:
    """Create output folders and copy planned photos on Yandex Disk.

    Args:
        distribution_plan: Planned remote copy operations produced by copy-plan
            building.
        disk_client: Yandex Disk client used for folder creation and copying.
        output_folders: Output folder names to create on Yandex Disk.
        event_folder: Yandex Disk event folder that contains source photos and
            output folders.

    Returns:
        Count of distribution-plan records successfully copied to Yandex Disk.

    Side effects:
        Creates participant/quarantine folders on Yandex Disk and copies
        existing remote source photos to remote destination paths. Local
        downloaded photos are not uploaded.
    """

    for folder_name in output_folders.participant_folders_by_id.values():
        disk_client.ensure_folder(join_disk_path(event_folder, folder_name))
    disk_client.ensure_folder(join_disk_path(event_folder, output_folders.quarantine_folder_name))

    copied_count = 0
    for plan in distribution_plan:
        disk_client.copy_resource(
            plan.source_disk_path,
            plan.destination_disk_path,
            overwrite=True,
        )
        copied_count += 1
    return DistributionPlanApplyResult(copied_to_disk_count=copied_count)


def _remove_local_artifact(path: Path) -> None:
    """Remove one local artifact after proving it lives under project `data`."""

    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    data_root = (cwd / "data").resolve()
    if not _is_relative_to(resolved, data_root):
        raise ValueError(f"Refusing to remove local artifact outside data directory: {path}")

    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether `path` is inside `parent` without requiring Python 3.9 API."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_object_repr(class_name: str, values: dict[str, object]) -> str:
    """Build a compact repr from values already approved for diagnostics."""

    fields = ", ".join(f"{key}={value!r}" for key, value in values.items())
    return f"{class_name}({fields})"
