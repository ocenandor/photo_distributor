"""Tests for distribution workflow helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from photo_distribution.workflow import DistributionResult, cleanup_local_artifacts


def result_with_artifacts(*paths: Path) -> DistributionResult:
    return DistributionResult(
        participants_count=0,
        reference_embeddings_count=0,
        event_photos_count=0,
        event_faces_count=0,
        face_matches_count=0,
        planned_copies_count=0,
        copied_to_disk_count=0,
        quarantined_photos_count=0,
        database_path=Path("data/photo_distributor.sqlite3"),
        local_distribution_path=Path("data/local_distribution/test"),
        local_artifact_paths=paths,
    )


def test_cleanup_local_artifacts_removes_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    forms_dir = data_dir / "forms"
    event_dir = data_dir / "event_photos" / "event"
    database_path = data_dir / "photo_distributor.sqlite3"
    forms_dir.mkdir(parents=True)
    event_dir.mkdir(parents=True)
    (forms_dir / "export.json").write_text("[]", encoding="utf-8")
    (event_dir / "photo.jpg").write_text("fake", encoding="utf-8")
    database_path.write_text("sqlite", encoding="utf-8")

    cleanup_local_artifacts(result_with_artifacts(forms_dir, event_dir, database_path))

    assert not forms_dir.exists()
    assert not event_dir.exists()
    assert not database_path.exists()
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
