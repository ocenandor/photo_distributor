"""Validate and download event files from Yandex Disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from yandex_disk import YandexDiskClient


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


@dataclass(frozen=True)
class EventPhotoRecord:
    """Downloaded event photo used by analysis and output file planning.

    Attributes:
        id: Run-local event photo id.
        name: Source photo file name on Yandex Disk.
        disk_path: Original Yandex Disk path of the event photo.
        local_path: Local downloaded file path used by face analysis.
    """

    id: int
    name: str
    disk_path: str
    local_path: Path


def validate_cloud_event_folder(
    disk_client: YandexDiskClient,
    event_folder: str,
) -> None:
    """Ensure that the Yandex Disk event path is canonical, exists, and is a folder.

    Args:
        disk_client: Concrete Yandex Disk client used to read folder metadata.
        event_folder: Canonical Yandex Disk event folder path.

    Raises:
        DiskApiError: If the resource does not exist or cannot be read.
        ValueError: If the path is not canonical or the resource is not a
            folder.
    """

    _validate_event_folder_path_format(event_folder)
    metadata = disk_client.get_resource(event_folder)
    if metadata.get("type") != "dir":
        raise ValueError("Yandex Disk event path must point to a folder.")


def download_event_photos(
    disk_client: YandexDiskClient,
    event_folder: str,
    local_event_dir: Path,
) -> list[EventPhotoRecord]:
    """Download top-level event image files and return run-local records.

    Args:
        disk_client: Yandex Disk client used for listing and downloading.
        event_folder: Yandex Disk folder with source event photos.
        local_event_dir: Local directory where source photos are downloaded.

    Returns:
        Event photo records for downloaded image files in top-level folder
        listing order.

    Side effects:
        Downloads image files into `local_event_dir`, overwriting same-named
        files from previous runs.
    """

    items = disk_client.list_files(event_folder, limit=100)
    photo_items = [
        item
        for item in items
        if item.get("type") == "file"
        and Path(str(item.get("name", ""))).suffix.lower() in IMAGE_EXTENSIONS
    ]
    total_photos = len(photo_items)
    logger.info("Event photos selected for download: {}", total_photos)

    records: list[EventPhotoRecord] = []
    for item in photo_items:
        name = str(item.get("name"))
        disk_path = str(item.get("path")).removeprefix("disk:")
        local_path = local_event_dir / name
        disk_client.download_file(disk_path, local_path, overwrite=True)
        records.append(
            EventPhotoRecord(
                id=len(records) + 1,
                name=name,
                disk_path=disk_path,
                local_path=local_path,
            )
        )
        downloaded_count = len(records)
        if downloaded_count % 10 == 0 or downloaded_count == total_photos:
            logger.info("Downloaded event photos: {}/{}", downloaded_count, total_photos)
    return records


def _validate_event_folder_path_format(event_folder: str) -> None:
    """Reject remote event paths that are not already in canonical form."""

    if not event_folder:
        raise ValueError("Yandex Disk event folder path is empty.")
    if event_folder != event_folder.strip():
        raise ValueError("Yandex Disk event folder path must not contain surrounding whitespace.")
    if event_folder == "/":
        raise ValueError("Yandex Disk event folder path must point to a named folder, not disk root.")
    if not event_folder.startswith("/"):
        raise ValueError("Yandex Disk event folder path must start with '/'.")
    if event_folder.endswith("/"):
        raise ValueError("Yandex Disk event folder path must not end with '/'.")
    if "//" in event_folder:
        raise ValueError("Yandex Disk event folder path must not contain empty path segments.")
