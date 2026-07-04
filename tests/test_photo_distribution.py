"""Tests for distribution workflow helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from photo_distribution_utils import (
    DistributionArtifacts,
    DistributionConfig,
    DistributionCounters,
    DistributionResult,
    cleanup_local_artifacts,
    local_event_key_from_folder,
    prepare_event_artifact_paths,
    validate_cloud_event_folder,
)


def result_with_artifacts(*paths: Path) -> DistributionResult:
    return DistributionResult(
        counts=DistributionCounters(
            participants_count=0,
            reference_embeddings_count=0,
            event_photos_count=0,
            event_faces_count=0,
            face_matches_count=0,
            planned_copies_count=0,
            copied_to_disk_count=0,
            quarantined_photos_count=0,
        ),
        artifacts=DistributionArtifacts(
            copy_plan_path=Path("data/distribution_plans/test/copy_plan.json"),
            local_artifact_paths=paths,
        ),
    )


def test_cleanup_local_artifacts_removes_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    forms_dir = data_dir / "forms"
    event_dir = data_dir / "event_photos" / "event"
    forms_dir.mkdir(parents=True)
    event_dir.mkdir(parents=True)
    (forms_dir / "export.json").write_text("[]", encoding="utf-8")
    (event_dir / "photo.jpg").write_text("fake", encoding="utf-8")

    cleanup_local_artifacts(result_with_artifacts(forms_dir, event_dir))

    assert not forms_dir.exists()
    assert not event_dir.exists()
    assert data_dir.exists()


def test_cleanup_local_artifacts_refuses_paths_outside_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="outside data directory"):
        cleanup_local_artifacts(result_with_artifacts(outside))

    assert outside.is_file()


def test_distribution_result_safe_summary_excludes_local_paths() -> None:
    sensitive_path = Path("C:/Users/pavel/private_event/forms")
    result = result_with_artifacts(sensitive_path)

    summary = result.safe_summary()
    representation = repr(result)

    assert summary["local_artifacts_count"] == 1
    assert summary["participants_count"] == 0
    assert "private_event" not in str(summary)
    assert "private_event" not in representation
    assert "local_artifacts_count=1" in representation


def test_distribution_result_keeps_grouped_state() -> None:
    result = DistributionResult(
        counts=DistributionCounters(
            participants_count=1,
            reference_embeddings_count=2,
            event_photos_count=3,
            event_faces_count=4,
            face_matches_count=5,
            planned_copies_count=6,
            copied_to_disk_count=7,
            quarantined_photos_count=8,
        ),
        artifacts=DistributionArtifacts(
            copy_plan_path=Path("data/distribution_plans/test/copy_plan.json"),
            local_artifact_paths=(Path("data/forms"),),
        ),
    )

    assert result.counts.participants_count == 1
    assert result.counts.copied_to_disk_count == 7
    assert result.artifacts.copy_plan_path == Path("data/distribution_plans/test/copy_plan.json")
    assert result.artifacts.local_artifact_paths == (Path("data/forms"),)


def test_distribution_config_safe_summary_excludes_local_paths() -> None:
    config = DistributionConfig(
        forms_data_dir=Path("C:/Users/pavel/private_event/forms"),
        event_photos_dir=Path("C:/Users/pavel/private_event/photos"),
        copy_plans_dir=Path("C:/Users/pavel/private_event/plans"),
    )

    summary = config.safe_summary()
    representation = repr(config)

    assert summary["similarity_threshold"] == config.similarity_threshold
    assert "private_event" not in str(summary)
    assert "private_event" not in representation
    assert "similarity_threshold=" in representation


@pytest.mark.parametrize(
    ("event_folder", "message"),
    [
        ("", "empty"),
        (" /event/folder", "surrounding whitespace"),
        ("/event/folder ", "surrounding whitespace"),
        ("event/folder", "must start"),
        ("/", "named folder"),
        ("/event/folder/", "must not end"),
        ("/event//folder", "empty path segments"),
    ],
)
def test_validate_cloud_event_folder_rejects_noncanonical_path_before_api(
    event_folder: str,
    message: str,
) -> None:
    client = _UnexpectedMetadataClient()

    with pytest.raises(ValueError, match=message):
        validate_cloud_event_folder(client, event_folder)


def test_local_event_key_is_filesystem_safe() -> None:
    assert local_event_key_from_folder("/events/test event 001") == "events_test_event_001"


def test_prepare_event_artifact_paths_creates_event_photo_directory(tmp_path: Path) -> None:
    config = DistributionConfig(
        event_photos_dir=tmp_path / "event_photos",
        copy_plans_dir=tmp_path / "distribution_plans",
    )

    paths = prepare_event_artifact_paths("/event/folder", config)

    assert paths.event_folder == "/event/folder"
    assert paths.local_event_key == "event_folder"
    assert paths.local_event_photos_dir == tmp_path / "event_photos" / "event_folder"
    assert paths.copy_plan_dir == tmp_path / "distribution_plans" / "event_folder"
    assert paths.copy_plan_path == tmp_path / "distribution_plans" / "event_folder" / "copy_plan.json"
    assert paths.local_event_photos_dir.is_dir()
    assert not paths.copy_plan_dir.exists()


def test_validate_cloud_event_folder_rejects_non_folder_resource() -> None:
    client = _FakeMetadataClient({"type": "file"})

    with pytest.raises(ValueError, match="must point to a folder"):
        validate_cloud_event_folder(client, "/event/file.jpg")


class _FakeMetadataClient:
    """Tiny metadata client test double for event folder validation."""

    def __init__(self, metadata: dict[str, object]) -> None:
        self.metadata = metadata

    def get_resource(self, path: str) -> dict[str, object]:
        assert path == "/event/file.jpg"
        return self.metadata


class _UnexpectedMetadataClient:
    """Metadata client that fails if format validation reaches the API layer."""

    def get_resource(self, path: str) -> dict[str, object]:
        raise AssertionError(f"Unexpected metadata request: {path}")
