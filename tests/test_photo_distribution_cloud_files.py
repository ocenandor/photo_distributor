"""Tests for Yandex Disk event folder validation and photo downloads."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from photo_distribution_utils.cloud_files import download_event_photos


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
        local_path.write_text(Path(disk_path).name, encoding="utf-8")
        return local_path


def test_download_event_photos_downloads_top_level_images(tmp_path: Path) -> None:
    client = FakeDiskClient()

    photos = download_event_photos(client, "/event", tmp_path / "event_photos")

    assert [photo.name for photo in photos] == ["first.jpg", "second.PNG"]
    assert [photo.id for photo in photos] == [1, 2]
    assert [photo.disk_path for photo in photos] == ["/event/first.jpg", "/event/second.PNG"]
    assert [download[0] for download in client.downloads] == [
        "/event/first.jpg",
        "/event/second.PNG",
    ]
    assert all(download[2] is True for download in client.downloads)
    assert (tmp_path / "event_photos" / "first.jpg").read_text(encoding="utf-8") == "first.jpg"


def test_download_event_photos_logs_progress_every_ten(tmp_path: Path) -> None:
    client = ManyImageFakeDiskClient(total=21)
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), format="{message}")

    try:
        photos = download_event_photos(client, "/event", tmp_path / "event_photos")
    finally:
        logger.remove(sink_id)

    assert len(photos) == 21
    assert "Event photos selected for download: 21" in messages
    assert "Downloaded event photos: 10/21" in messages
    assert "Downloaded event photos: 20/21" in messages
    assert "Downloaded event photos: 21/21" in messages


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
        local_path.write_text(Path(disk_path).name, encoding="utf-8")
        return local_path
