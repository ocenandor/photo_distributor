"""Validate and download event files from Yandex Disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from yandex_disk import DiskApiError, YandexDiskClient

from .image_files import IMAGE_EXTENSIONS, is_readable_image


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


@dataclass(frozen=True)
class EventPhotoDownloadResult:
    """Result of syncing event photos into a local cache.

    Attributes:
        event_photos: Current top-level cloud event photos with local paths.
        known_disk_paths: Updated remote photo paths that have local cache
            records for this run.
        downloaded_count: Number of remote photos downloaded during this call.
    """

    event_photos: tuple[EventPhotoRecord, ...]
    known_disk_paths: frozenset[str]
    downloaded_count: int


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

    validate_cloud_event_folder_path(event_folder)
    metadata = disk_client.get_resource(event_folder)
    if metadata.get("type") != "dir":
        raise ValueError("Yandex Disk event path must point to a folder.")


def validate_cloud_event_folder_path(event_folder: str) -> None:
    """Reject remote event paths that are not already in canonical form.

    Args:
        event_folder: Canonical Yandex Disk event folder path.

    Raises:
        ValueError: If `event_folder` is not an absolute canonical folder path.
    """

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


def download_event_photos(
    disk_client: YandexDiskClient,
    event_folder: str,
    local_event_dir: Path,
    *,
    known_disk_paths: set[str] | None = None,
) -> EventPhotoDownloadResult:
    """Download event image files and return current local cache records.

    Args:
        disk_client: Yandex Disk client used for listing and downloading.
        event_folder: Yandex Disk folder with source event photos.
        local_event_dir: Local cache directory where source photos are stored.
        known_disk_paths: Remote photo paths already seen by this run. When
            omitted, every listed image is downloaded and overwritten. When
            provided, only missing, unknown, or invalid cached photos are
            downloaded.

    Returns:
        Current readable event photo records, updated known remote paths, and
        the number of files downloaded during this call.

    Side effects:
        Downloads image files into `local_event_dir`. Invalid downloads are
        removed and left out of `known_disk_paths` so a later call retries them.
    """

    photo_items = _top_level_image_items(disk_client, event_folder)
    total_photos = len(photo_items)
    logger.info("Event photos selected for download: {}", total_photos)

    records: list[EventPhotoRecord] = []
    updated_known = set(known_disk_paths or ())
    force_download = known_disk_paths is None
    downloaded_count = 0

    for item in photo_items:
        name = str(item.get("name"))
        disk_path = str(item.get("path")).removeprefix("disk:")
        local_path = local_event_dir / name
        should_download = force_download or disk_path not in updated_known or not local_path.is_file()
        if should_download:
            if not _download_valid_event_photo(disk_client, disk_path, local_path):
                continue
            downloaded_count += 1
            if downloaded_count % 10 == 0 or downloaded_count == total_photos:
                logger.info("Downloaded event photos: {}/{}", downloaded_count, total_photos)
        elif not is_readable_image(local_path):
            updated_known.discard(disk_path)
            _remove_invalid_local_file(local_path)
            logger.warning("Cached event photo is unreadable; it will be retried later.")
            continue

        updated_known.add(disk_path)
        records.append(
            EventPhotoRecord(
                id=len(records) + 1,
                name=name,
                disk_path=disk_path,
                local_path=local_path,
            )
        )

    return EventPhotoDownloadResult(
        event_photos=tuple(records),
        known_disk_paths=frozenset(updated_known),
        downloaded_count=downloaded_count,
    )


def _download_valid_event_photo(
    disk_client: YandexDiskClient,
    disk_path: str,
    local_path: Path,
) -> bool:
    """Download one event photo and verify OpenCV can read it.

    Args:
        disk_client: Yandex Disk client used for downloading.
        disk_path: Remote source photo path.
        local_path: Local cache destination.

    Returns:
        `True` when the file was downloaded and can be read as an image,
        otherwise `False`.

    Side effects:
        Writes `local_path` on success. Removes a downloaded invalid local file
        so the next live poll can retry the same remote path.
    """

    try:
        disk_client.download_file(disk_path, local_path, overwrite=True)
    except (DiskApiError, OSError, ValueError):
        logger.warning("Event photo download skipped; it will be retried later.")
        return False

    if is_readable_image(local_path):
        return True

    _remove_invalid_local_file(local_path)
    logger.warning("Unreadable event photo skipped; it will be retried later.")
    return False


def _remove_invalid_local_file(local_path: Path) -> None:
    """Remove an invalid downloaded image file if it exists.

    Args:
        local_path: Local file path produced by a failed download attempt.

    Side effects:
        Deletes `local_path` when present.
    """

    try:
        local_path.unlink(missing_ok=True)
    except OSError:
        return


def _top_level_image_items(
    disk_client: YandexDiskClient,
    event_folder: str,
) -> list[dict[str, object]]:
    """Return direct child image files from an event folder listing."""

    items = disk_client.list_files(event_folder, limit=100)
    return [
        item
        for item in items
        if item.get("type") == "file"
        and Path(str(item.get("name", ""))).suffix.lower() in IMAGE_EXTENSIONS
    ]
