"""Tests for building the target output folder/file structure."""

from __future__ import annotations

import json
from pathlib import Path

from face_analysis import EventFaceMatch
from forms_export import ImportedParticipant
from photo_distribution_utils.cloud_files import EventPhotoRecord
from photo_distribution_utils.output_files_structure import (
    DistributionOutputFolders,
    build_distribution_copy_plan,
    build_distribution_output_folders,
    join_disk_path,
)


def test_join_disk_path_normalizes_slashes() -> None:
    assert join_disk_path("/event/", "/person/", "photo.jpg") == "/event/person/photo.jpg"


def test_build_distribution_output_folders_returns_safe_unique_names() -> None:
    result = build_distribution_output_folders(
        [
            _participant(1, "Participant", "first@example.com"),
            _participant(2, "Participant", "second@example.com"),
            _participant(3, "Bad/Name:*?", "third@example.com"),
        ],
        "quarantine",
    )

    assert result.participant_folders_by_id == {
        1: "Participant",
        2: "Participant_2",
        3: "Bad_Name",
    }
    assert result.quarantine_folder_name == "quarantine"


def test_build_distribution_output_folders_falls_back_to_email_or_id() -> None:
    result = build_distribution_output_folders(
        [
            _participant(1, "", "first@example.com"),
            _participant(2, "///", "@example.com"),
        ],
        "quarantine",
    )

    assert result.participant_folders_by_id == {
        1: "first",
        2: "participant_2",
    }


def test_build_distribution_copy_plan_creates_participant_and_quarantine_records(
    tmp_path: Path,
) -> None:
    matched_photo = EventPhotoRecord(
        id=1,
        name="matched.jpg",
        disk_path="/event/matched.jpg",
        local_path=tmp_path / "matched.jpg",
    )
    quarantine_photo = EventPhotoRecord(
        id=2,
        name="quarantine.jpg",
        disk_path="/event/quarantine.jpg",
        local_path=tmp_path / "quarantine.jpg",
    )

    result = build_distribution_copy_plan(
        event_photos=[matched_photo, quarantine_photo],
        face_matches=[
            EventFaceMatch(
                event_photo_id=1,
                participant_id=1,
                reference_embedding_id=10,
                similarity=0.9,
            )
        ],
        output_folders=_output_folders(),
        event_folder="/event",
        copy_plan_path=tmp_path / "plans" / "copy_plan.json",
    )

    assert result.planned_copies_count == 2
    assert result.quarantined_photos_count == 1
    assert [
        (plan.destination_kind, plan.source_disk_path, plan.destination_disk_path)
        for plan in result.copy_plan
    ] == [
        ("participant", "/event/matched.jpg", "/event/Participant/matched.jpg"),
        ("quarantine", "/event/quarantine.jpg", "/event/quarantine/quarantine.jpg"),
    ]


def test_build_distribution_copy_plan_writes_json_with_remote_paths(tmp_path: Path) -> None:
    source_photo = EventPhotoRecord(
        id=1,
        name="photo.jpg",
        disk_path="/event/photo.jpg",
        local_path=tmp_path / "photo.jpg",
    )
    result = build_distribution_copy_plan(
        event_photos=[source_photo],
        face_matches=[],
        output_folders=_output_folders(),
        event_folder="/event",
        copy_plan_path=tmp_path / "plans" / "copy_plan.json",
    )

    payload = json.loads(result.copy_plan_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "planned_copies_count": 1,
        "quarantined_photos_count": 1,
        "copies": [
            {
                "id": 1,
                "event_photo_id": 1,
                "participant_id": None,
                "destination_kind": "quarantine",
                "source_disk_path": "/event/photo.jpg",
                "destination_disk_path": "/event/quarantine/photo.jpg",
            }
        ],
    }


def _participant(participant_id: int, name: str, email: str) -> ImportedParticipant:
    """Return a participant with no reference images for folder-name tests."""

    return ImportedParticipant(
        id=participant_id,
        email=email,
        name=name,
        policy_accepted=True,
        reference_images=(),
    )


def _output_folders() -> DistributionOutputFolders:
    """Return output folder names for copy-plan tests."""

    return DistributionOutputFolders(
        participant_folders_by_id={1: "Participant"},
        quarantine_folder_name="quarantine",
    )
