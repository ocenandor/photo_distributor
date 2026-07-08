"""Tests for applying output distribution plans to Yandex Disk."""

from __future__ import annotations

from photo_distribution_utils.apply_distribution_plan import apply_distribution_plan
from photo_distribution_utils.output_files_structure import CopyPlanRecord, DistributionOutputFolders


class FakeDiskClient:
    """In-memory Disk client used by copy-plan tests."""

    def __init__(self) -> None:
        self.created_folders: list[str] = []
        self.copied: list[tuple[str, str, bool]] = []
        self.deleted: list[tuple[str, bool]] = []

    def ensure_folder(self, path: str) -> None:
        self.created_folders.append(path)

    def copy_resource(self, from_path: str, to_path: str, *, overwrite: bool = False) -> dict[str, object]:
        self.copied.append((from_path, to_path, overwrite))
        return {}

    def delete_resource(self, path: str, *, permanently: bool = False) -> dict[str, object]:
        self.deleted.append((path, permanently))
        return {}


def test_apply_distribution_plan_creates_folders_and_copies_records() -> None:
    client = FakeDiskClient()

    result = apply_distribution_plan(
        (
            CopyPlanRecord(
                id=1,
                event_photo_id=1,
                participant_id=1,
                destination_kind="participant",
                source_disk_path="/event/photo.jpg",
                destination_disk_path="/event/Participant__output/photo.jpg",
            ),
        ),
        disk_client=client,
        output_folders=DistributionOutputFolders(
            participant_folders_by_id={1: "Participant__output"},
            quarantine_folder_name="quarantine",
        ),
        event_folder="/event",
    )

    assert result.copied_to_disk_count == 1
    assert result.removed_from_quarantine_count == 1
    assert client.created_folders == ["/event/Participant__output", "/event/quarantine"]
    assert client.copied == [("/event/photo.jpg", "/event/Participant__output/photo.jpg", True)]
    assert client.deleted == [("/event/quarantine/photo.jpg", False)]


def test_apply_distribution_plan_keeps_current_quarantine_records() -> None:
    client = FakeDiskClient()

    result = apply_distribution_plan(
        (
            CopyPlanRecord(
                id=1,
                event_photo_id=1,
                participant_id=None,
                destination_kind="quarantine",
                source_disk_path="/event/photo.jpg",
                destination_disk_path="/event/quarantine/photo.jpg",
            ),
        ),
        disk_client=client,
        output_folders=DistributionOutputFolders(
            participant_folders_by_id={},
            quarantine_folder_name="quarantine",
        ),
        event_folder="/event",
    )

    assert result.copied_to_disk_count == 1
    assert result.removed_from_quarantine_count == 0
    assert client.copied == [("/event/photo.jpg", "/event/quarantine/photo.jpg", True)]
    assert client.deleted == []
