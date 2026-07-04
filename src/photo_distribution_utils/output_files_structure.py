"""Build the target Yandex Disk folder/file structure for one event run."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from face_analysis import EventFaceMatch
from forms_export import ImportedParticipant

from .cloud_files import EventPhotoRecord


@dataclass(frozen=True)
class DistributionOutputFolders:
    """Output folder names for one distribution run.

    Attributes:
        participant_folders_by_id: Mapping from participant id to the
            Disk-safe output folder name for that participant.
        quarantine_folder_name: Folder name for photos without accepted
            participant matches.
    """

    participant_folders_by_id: dict[int, str]
    quarantine_folder_name: str


@dataclass(frozen=True)
class CopyPlanRecord:
    """One planned Yandex Disk copy operation.

    Attributes:
        id: Run-local copy-plan id.
        event_photo_id: Run-local source event photo id.
        participant_id: Run-local participant id for participant copies, or
            `None` for quarantine copies.
        destination_kind: Either `participant` or `quarantine`.
        source_disk_path: Original Yandex Disk photo path to copy from.
        destination_disk_path: Yandex Disk participant/quarantine path to copy
            into.
    """

    id: int
    event_photo_id: int
    participant_id: int | None
    destination_kind: str
    source_disk_path: str
    destination_disk_path: str


@dataclass(frozen=True)
class CopyPlanBuildResult:
    """Summary of remote cloud file-structure plan creation.

    Attributes:
        copy_plan: Planned Yandex Disk copy operations. One source photo can
            produce several planned copies when several participants are
            recognized.
        copy_plan_path: Local JSON artifact containing the persisted plan.
        planned_copies_count: Number of copy-plan records created. One source
            photo can produce several planned copies when several participants
            are recognized.
        quarantined_photos_count: Number of source photos routed to quarantine
            because no participant was matched.
    """

    copy_plan: tuple[CopyPlanRecord, ...]
    copy_plan_path: Path
    planned_copies_count: int
    quarantined_photos_count: int


def build_distribution_output_folders(
    participants: list[ImportedParticipant],
    quarantine_folder_name: str,
) -> DistributionOutputFolders:
    """Build participant/quarantine output folder names for the current run.

    Args:
        participants: Participants imported from the forms export.
        quarantine_folder_name: Quarantine folder name for unmatched photos.

    Returns:
        Output folder metadata used by copy-plan building and Disk copying.

    Side effects:
        None. This function does not create local or remote folders.
    """

    return DistributionOutputFolders(
        participant_folders_by_id=_participant_output_folder_names(participants),
        quarantine_folder_name=quarantine_folder_name,
    )


def build_distribution_copy_plan(
    event_photos: list[EventPhotoRecord],
    face_matches: list[EventFaceMatch],
    output_folders: DistributionOutputFolders,
    event_folder: str,
    copy_plan_path: Path,
) -> CopyPlanBuildResult:
    """Build and persist the target cloud file structure as a remote copy plan.

    Args:
        event_photos: Downloaded event photo records used by analysis.
        face_matches: Accepted event/reference matches for those photos.
        output_folders: Output folder names for participant/quarantine copies.
        event_folder: Yandex Disk event folder that will receive output folders.
        copy_plan_path: Local JSON file path where the plan is written.

    Returns:
        In-memory copy plan, persisted JSON path, and plan counters.

    Side effects:
        Overwrites `copy_plan_path` with the current run's plan. The plan uses
        Yandex Disk source and destination paths; local photo files are not
        copied or uploaded.
    """

    participant_ids_by_photo = _matched_participant_ids_by_photo(face_matches)
    copy_plan: list[CopyPlanRecord] = []
    planned_count = 0
    quarantined_count = 0

    for photo in event_photos:
        participant_ids = sorted(participant_ids_by_photo.get(photo.id, set()))
        if participant_ids:
            for participant_id in participant_ids:
                folder_name = output_folders.participant_folders_by_id[participant_id]
                copy_plan.append(
                    _copy_plan_record(
                        copy_plan_id=len(copy_plan) + 1,
                        photo=photo,
                        participant_id=participant_id,
                        destination_kind="participant",
                        destination_disk_path=join_disk_path(event_folder, folder_name, photo.name),
                    )
                )
                planned_count += 1
        else:
            quarantined_count += 1
            copy_plan.append(
                _copy_plan_record(
                    copy_plan_id=len(copy_plan) + 1,
                    photo=photo,
                    participant_id=None,
                    destination_kind="quarantine",
                    destination_disk_path=join_disk_path(
                        event_folder,
                        output_folders.quarantine_folder_name,
                        photo.name,
                    ),
                )
            )
            planned_count += 1

    result = CopyPlanBuildResult(
        copy_plan=tuple(copy_plan),
        copy_plan_path=copy_plan_path,
        planned_copies_count=planned_count,
        quarantined_photos_count=quarantined_count,
    )
    payload = {
        "version": 1,
        "planned_copies_count": result.planned_copies_count,
        "quarantined_photos_count": result.quarantined_photos_count,
        "copies": [asdict(record) for record in result.copy_plan],
    }
    result.copy_plan_path.parent.mkdir(parents=True, exist_ok=True)
    result.copy_plan_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def join_disk_path(*parts: str) -> str:
    """Join Yandex Disk path fragments using a leading slash."""

    cleaned = [part.strip("/") for part in parts if part]
    return "/" + "/".join(cleaned)


def _participant_output_folder_names(participants: list[ImportedParticipant]) -> dict[int, str]:
    """Return unique, Disk-safe output folder names keyed by participant id."""

    used: set[str] = set()
    result: dict[int, str] = {}
    for participant in participants:
        base = _safe_disk_name(participant.name) or _safe_disk_name(participant.email.split("@")[0])
        if not base:
            base = f"participant_{participant.id}"

        candidate = base
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{base}_{suffix}"
            suffix += 1

        used.add(candidate.lower())
        result[participant.id] = candidate
    return result


def _safe_disk_name(value: str) -> str:
    """Return a Yandex Disk folder-safe version of a user-facing name."""

    stripped = value.strip().replace("/", "_").replace("\\", "_")
    stripped = re.sub(r'[:*?"<>|\x00-\x1f]+', "_", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip(" ._")


def _copy_plan_record(
    *,
    copy_plan_id: int,
    photo: EventPhotoRecord,
    participant_id: int | None,
    destination_kind: str,
    destination_disk_path: str,
) -> CopyPlanRecord:
    """Return one remote Yandex Disk copy-plan record."""

    return CopyPlanRecord(
        id=copy_plan_id,
        event_photo_id=photo.id,
        participant_id=participant_id,
        destination_kind=destination_kind,
        source_disk_path=photo.disk_path,
        destination_disk_path=destination_disk_path,
    )


def _matched_participant_ids_by_photo(
    face_matches: list[EventFaceMatch],
) -> dict[int, set[int]]:
    """Return accepted participant ids grouped by event photo id."""

    result: dict[int, set[int]] = {}
    for match in face_matches:
        result.setdefault(match.event_photo_id, set()).add(match.participant_id)
    return result
