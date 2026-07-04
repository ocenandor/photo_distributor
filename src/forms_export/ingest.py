"""Import manually exported Yandex Forms answers from Yandex Disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yandex_disk import YandexDiskClient

from .participants import FormsExportError, Participant, load_participants


DEFAULT_FORMS_FOLDER = "/Yandex.Forms"
DEFAULT_DATA_DIR = Path("data/forms")


@dataclass(frozen=True)
class ImportedReferenceImage:
    """Reference image downloaded for one imported participant.

    Attributes:
        id: Run-local reference image id.
        participant_id: Run-local participant id that owns this reference.
        disk_path: Original Yandex Disk path of the reference image.
        local_path: Local downloaded file path used by face analysis.
    """

    id: int
    participant_id: int
    disk_path: str
    local_path: Path


@dataclass(frozen=True)
class ImportedParticipant:
    """Participant imported from the latest Yandex Forms export.

    Attributes:
        id: Run-local participant id assigned in export order.
        email: Participant email from the form. Keep it out of logs.
        name: Display name from the form, used for output folders.
        policy_accepted: Consent value parsed from the form.
        reference_images: Downloaded reference images submitted by this
            participant.
    """

    id: int
    email: str
    name: str
    policy_accepted: bool
    reference_images: tuple[ImportedReferenceImage, ...]


@dataclass(frozen=True)
class FormsIngestResult:
    """Summary of one Yandex Forms export import.

    Attributes:
        json_disk_path: Yandex Disk path of the selected newest export file.
        local_json_path: Local downloaded copy of that JSON export.
        participants: Participants and reference images imported from the
            current export.
        participants_count: Number of participants parsed from the export.
        reference_images_count: Number of reference images downloaded locally.
    """

    json_disk_path: str
    local_json_path: Path
    participants: tuple[ImportedParticipant, ...]
    participants_count: int
    reference_images_count: int

    @property
    def reference_images(self) -> tuple[ImportedReferenceImage, ...]:
        """Return all imported reference images in participant/export order."""

        return tuple(
            reference_image
            for participant in self.participants
            for reference_image in participant.reference_images
        )


def ingest_forms_export(
    disk_client: YandexDiskClient,
    form_id: str,
    *,
    forms_root: str = DEFAULT_FORMS_FOLDER,
    data_dir: str | Path = DEFAULT_DATA_DIR,
) -> FormsIngestResult:
    """Download the latest forms JSON export and participant reference images.

    Args:
        disk_client: Yandex Disk client used for listing and downloads.
        form_id: Explicit Yandex Forms subfolder name under `forms_root`.
        forms_root: Yandex Disk root containing form export folders.
        data_dir: Local root for downloaded exports and references.

    Returns:
        Imported participants, downloaded reference paths, and import counters.

    Side effects:
        Downloads the newest JSON export and participant reference images under
        `data_dir`.
    """

    data_root = Path(data_dir)
    export_dir = data_root / "exports"
    references_dir = data_root / "references"
    export_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)

    forms_folder = _join_disk_path(forms_root, form_id)
    json_disk_path = find_latest_json_export(disk_client, forms_folder)
    local_json_path = export_dir / Path(json_disk_path).name
    disk_client.download_file(json_disk_path, local_json_path, overwrite=True)

    participants = load_participants(local_json_path)
    imported_participants = _download_reference_images(
        disk_client,
        participants,
        references_dir,
    )

    return FormsIngestResult(
        json_disk_path=json_disk_path,
        local_json_path=local_json_path,
        participants=imported_participants,
        participants_count=len(imported_participants),
        reference_images_count=sum(
            len(participant.reference_images) for participant in imported_participants
        ),
    )


def find_latest_json_export(
    disk_client: YandexDiskClient,
    forms_folder: str,
) -> str:
    """Return the newest JSON file path from a Yandex Forms folder."""

    items = [
        item
        for item in disk_client.list_files(forms_folder)
        if item.get("type") == "file" and str(item.get("name", "")).lower().endswith(".json")
    ]
    if not items:
        raise FormsExportError(
            f"No JSON export files found in Yandex Disk folder: {forms_folder}",
            safe_message="No JSON export files found in the Yandex Forms folder.",
        )

    latest = max(items, key=_resource_sort_key)
    path = latest.get("path")
    if not isinstance(path, str) or not path:
        raise FormsExportError("Latest JSON export does not contain a path.")
    return path.removeprefix("disk:")


def _download_reference_images(
    disk_client: YandexDiskClient,
    participants: list[Participant],
    references_dir: Path,
) -> tuple[ImportedParticipant, ...]:
    """Download participant reference images and return run-local import state."""

    imported_participants: list[ImportedParticipant] = []
    reference_id = 1
    for participant_index, participant in enumerate(participants, start=1):
        participant_dir = references_dir / f"participant_{participant_index:03d}"
        participant_dir.mkdir(parents=True, exist_ok=True)
        reference_images: list[ImportedReferenceImage] = []

        for index, disk_path in enumerate(participant.image_disk_paths, start=1):
            suffix = Path(disk_path).suffix
            local_name = f"{index:02d}{suffix}" if suffix else f"{index:02d}"
            local_path = participant_dir / local_name
            disk_client.download_file(disk_path, local_path, overwrite=True)
            reference_images.append(
                ImportedReferenceImage(
                    id=reference_id,
                    participant_id=participant_index,
                    disk_path=disk_path,
                    local_path=local_path,
                )
            )
            reference_id += 1
        imported_participants.append(
            ImportedParticipant(
                id=participant_index,
                email=participant.email,
                name=participant.name,
                policy_accepted=participant.policy_accepted,
                reference_images=tuple(reference_images),
            )
        )
    return tuple(imported_participants)


def _resource_sort_key(resource: dict[str, object]) -> str:
    """Return a stable string key for choosing the newest export resource."""

    value = resource.get("created") or resource.get("modified") or resource.get("name") or ""
    return str(value)


def _join_disk_path(parent: str, child: str) -> str:
    """Join two Yandex Disk path fragments."""

    return f"{parent.rstrip('/')}/{child.lstrip('/')}"
