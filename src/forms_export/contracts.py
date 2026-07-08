"""Shared imported-form contracts for all forms data sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportedReferenceImage:
    """Reference image downloaded or saved for one imported participant.

    Attributes:
        id: Run-local reference image id.
        participant_id: Run-local participant id that owns this reference.
        disk_path: Original Yandex Disk path when available, or an empty string
            for reference images sourced from email attachments.
        local_path: Local reference image path used by face analysis.
    """

    id: int
    participant_id: int
    disk_path: str
    local_path: Path


@dataclass(frozen=True)
class ImportedParticipant:
    """Participant imported from one forms data source.

    Attributes:
        id: Run-local participant id assigned in import order.
        email: Participant email from the form. Keep it out of logs.
        name: Display name from the form, used for output folders.
        policy_accepted: Consent value parsed from the form.
        reference_images: Local reference images submitted by this participant.
    """

    id: int
    email: str
    name: str
    policy_accepted: bool
    reference_images: tuple[ImportedReferenceImage, ...]


@dataclass(frozen=True)
class FormsIngestResult:
    """Imported participants and references from one forms data source.

    Attributes:
        json_disk_path: Yandex Disk path of the selected JSON export for the
            legacy JSON source, or an empty string for email-sourced imports.
        local_json_path: Local downloaded JSON export path for the legacy JSON
            source, or an empty path for email-sourced imports.
        participants: Participants and reference images imported from the
            source.
        participants_count: Number of participants parsed from the source.
        reference_images_count: Number of reference images available locally.
    """

    json_disk_path: str
    local_json_path: Path
    participants: tuple[ImportedParticipant, ...]
    participants_count: int
    reference_images_count: int

    @property
    def reference_images(self) -> tuple[ImportedReferenceImage, ...]:
        """Return all imported reference images in participant/import order."""

        return tuple(
            reference_image
            for participant in self.participants
            for reference_image in participant.reference_images
        )
