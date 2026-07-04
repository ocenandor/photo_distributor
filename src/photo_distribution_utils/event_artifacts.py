"""Prepare local artifact paths for one event."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .apply_distribution_plan import DistributionConfig


@dataclass(frozen=True)
class EventArtifactPaths:
    """Remote event path and local artifact paths for one event.

    Attributes:
        event_folder: Normalized Yandex Disk event folder path.
        local_event_key: Filesystem-safe local name derived from
            `event_folder`; used only for local artifact folders.
        local_event_photos_dir: Local directory for downloaded source photos.
        copy_plan_dir: Local directory for copy-plan artifacts.
        copy_plan_path: Local JSON file path for the current run's remote copy
            plan.
    """

    event_folder: str
    local_event_key: str
    local_event_photos_dir: Path
    copy_plan_dir: Path
    copy_plan_path: Path


def prepare_event_artifact_paths(
    event_folder: str,
    config: DistributionConfig,
) -> EventArtifactPaths:
    """Build event artifact paths and create the photo cache directory.

    Args:
        event_folder: Canonical Yandex Disk event folder path that has already
            passed remote validation.
        config: Distribution workflow configuration with local artifact roots.

    Returns:
        Remote event path and local artifact paths for the event.

    Side effects:
        Creates the local directory used for downloaded event photos. The
        copy-plan directory is created later when the JSON plan is written.
    """

    local_event_key = local_event_key_from_folder(event_folder)
    paths = EventArtifactPaths(
        event_folder=event_folder,
        local_event_key=local_event_key,
        local_event_photos_dir=config.event_photos_dir / local_event_key,
        copy_plan_dir=config.copy_plans_dir / local_event_key,
        copy_plan_path=config.copy_plans_dir / local_event_key / "copy_plan.json",
    )
    paths.local_event_photos_dir.mkdir(parents=True, exist_ok=True)
    return paths


def local_event_key_from_folder(event_folder: str) -> str:
    """Return a filesystem-safe local artifact folder name for an event path."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", event_folder.strip("/") or "event").strip("._") or "event"
