"""Tests for Yandex Disk event folder validation and photo downloads."""

from __future__ import annotations

from pathlib import Path

import pytest
from loguru import logger

from photo_distribution_utils.cloud_files import (
    download_event_photos,
    validate_cloud_event_folder_path,
)


VALID_IMAGE_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01"
    b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeDiskClient:
    """Disk client test double for event photo downloads."""

    def __init__(self) -> None:
        self.downloads: list[tuple[str, Path, bool]] = []

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        assert path == "/event"
        assert limit == 100
        return [
            {"type": "file", "name": "first.jpg", "path": "disk:/event/first.jpg"},
            {"type": "file", "name": "notes.txt", "path": "disk:/event/notes.txt"},
            {"type": "dir", "name": "nested", "path": "disk:/event/nested"},
            {"type": "file", "name": "second.PNG", "path": "disk:/event/second.PNG"},
        ]

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        self.downloads.append((disk_path, local_path, overwrite))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path


def test_download_event_photos_downloads_top_level_images(tmp_path: Path) -> None:
    client = FakeDiskClient()

    result = download_event_photos(client, "/event", tmp_path / "event_photos")
    photos = result.event_photos

    assert [photo.name for photo in photos] == ["first.jpg", "second.PNG"]
    assert [photo.id for photo in photos] == [1, 2]
    assert result.downloaded_count == 2
    assert result.known_disk_paths == frozenset({"/event/first.jpg", "/event/second.PNG"})
    assert [photo.disk_path for photo in photos] == ["/event/first.jpg", "/event/second.PNG"]
    assert [download[0] for download in client.downloads] == [
        "/event/first.jpg",
        "/event/second.PNG",
    ]
    assert all(download[2] is True for download in client.downloads)
    assert (tmp_path / "event_photos" / "first.jpg").read_bytes() == VALID_IMAGE_BYTES


def test_download_event_photos_logs_progress_every_ten(tmp_path: Path) -> None:
    client = ManyImageFakeDiskClient(total=21)
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), format="{message}")

    try:
        result = download_event_photos(client, "/event", tmp_path / "event_photos")
    finally:
        logger.remove(sink_id)

    assert len(result.event_photos) == 21
    assert "Event photos selected for download: 21" in messages
    assert "Downloaded event photos: 10/21" in messages
    assert "Downloaded event photos: 20/21" in messages
    assert "Downloaded event photos: 21/21" in messages


def test_download_event_photos_uses_local_cache(tmp_path: Path) -> None:
    client = FakeDiskClient()
    local_dir = tmp_path / "event_photos"
    local_dir.mkdir()
    (local_dir / "first.jpg").write_bytes(VALID_IMAGE_BYTES)

    result = download_event_photos(
        client,
        "/event",
        local_dir,
        known_disk_paths={"/event/first.jpg"},
    )

    assert [photo.name for photo in result.event_photos] == ["first.jpg", "second.PNG"]
    assert result.downloaded_count == 1
    assert result.known_disk_paths == frozenset({"/event/first.jpg", "/event/second.PNG"})
    assert [download[0] for download in client.downloads] == ["/event/second.PNG"]
    assert (local_dir / "first.jpg").read_bytes() == VALID_IMAGE_BYTES
    assert (local_dir / "second.PNG").read_bytes() == VALID_IMAGE_BYTES


def test_download_event_photos_skips_unreadable_new_photo_for_retry(tmp_path: Path) -> None:
    client = BrokenImageFakeDiskClient()
    local_dir = tmp_path / "event_photos"

    result = download_event_photos(
        client,
        "/event",
        local_dir,
        known_disk_paths=set(),
    )

    assert [photo.name for photo in result.event_photos] == ["good.jpg"]
    assert result.downloaded_count == 1
    assert result.known_disk_paths == frozenset({"/event/good.jpg"})
    assert [download[0] for download in client.downloads] == [
        "/event/broken.jpg",
        "/event/good.jpg",
    ]
    assert not (local_dir / "broken.jpg").exists()


def test_download_event_photos_retries_unreadable_cached_photo(tmp_path: Path) -> None:
    client = FakeDiskClient()
    local_dir = tmp_path / "event_photos"
    local_dir.mkdir()
    (local_dir / "first.jpg").write_bytes(b"partial upload")

    result = download_event_photos(
        client,
        "/event",
        local_dir,
        known_disk_paths={"/event/first.jpg"},
    )

    assert [photo.name for photo in result.event_photos] == ["second.PNG"]
    assert result.known_disk_paths == frozenset({"/event/second.PNG"})
    assert [download[0] for download in client.downloads] == ["/event/second.PNG"]
    assert not (local_dir / "first.jpg").exists()


def test_validate_cloud_event_folder_path_accepts_canonical_path() -> None:
    validate_cloud_event_folder_path("/event/folder")


def test_validate_cloud_event_folder_path_rejects_plain_name() -> None:
    with pytest.raises(ValueError, match="must start with '/'"):
        validate_cloud_event_folder_path("event folder")


class ManyImageFakeDiskClient:
    """Disk client test double with many image files for progress logging."""

    def __init__(self, total: int) -> None:
        self.total = total

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        assert path == "/event"
        assert limit == 100
        return [
            {
                "type": "file",
                "name": f"photo_{index:02d}.jpg",
                "path": f"disk:/event/photo_{index:02d}.jpg",
            }
            for index in range(1, self.total + 1)
        ]

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path


class BrokenImageFakeDiskClient(FakeDiskClient):
    """Disk client that writes one unreadable image and one readable image."""

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        assert path == "/event"
        assert limit == 100
        return [
            {"type": "file", "name": "broken.jpg", "path": "disk:/event/broken.jpg"},
            {"type": "file", "name": "good.jpg", "path": "disk:/event/good.jpg"},
        ]

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        self.downloads.append((disk_path, local_path, overwrite))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if disk_path.endswith("broken.jpg"):
            local_path.write_bytes(b"partial upload")
        else:
            local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path
