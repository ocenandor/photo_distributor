"""Import manually exported Yandex Forms answers from Yandex Disk."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from yandex_disk import YandexDiskClient

from .participants import Participant, load_participants


DEFAULT_FORMS_FOLDER = "/Yandex.Forms"
DEFAULT_DATA_DIR = Path("data/forms")
DEFAULT_DATABASE_PATH = Path("data/photo_distributor.sqlite3")


@dataclass(frozen=True)
class FormsIngestResult:
    json_disk_path: str
    local_json_path: Path
    database_path: Path
    participants_count: int
    reference_images_count: int


def ingest_forms_export(
    disk_client: YandexDiskClient,
    form_id: str,
    *,
    forms_root: str = DEFAULT_FORMS_FOLDER,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> FormsIngestResult:
    """Download the latest forms JSON export, reference images, and write SQLite."""

    data_root = Path(data_dir)
    db_path = Path(database_path)
    export_dir = data_root / "exports"
    references_dir = data_root / "references"
    export_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)

    forms_folder = _join_disk_path(forms_root, form_id)
    json_disk_path = find_latest_json_export(disk_client, forms_folder)
    local_json_path = export_dir / Path(json_disk_path).name
    disk_client.download_file(json_disk_path, local_json_path, overwrite=True)

    participants = load_participants(local_json_path)
    downloaded_images = _download_reference_images(
        disk_client,
        participants,
        references_dir,
    )
    _write_database(db_path, participants, downloaded_images)

    return FormsIngestResult(
        json_disk_path=json_disk_path,
        local_json_path=local_json_path,
        database_path=db_path,
        participants_count=len(participants),
        reference_images_count=sum(len(paths) for paths in downloaded_images.values()),
    )


def find_latest_json_export(disk_client: YandexDiskClient, forms_folder: str) -> str:
    """Return the newest JSON file path from a Yandex Forms folder."""

    items = [
        item
        for item in disk_client.list_files(forms_folder)
        if item.get("type") == "file" and str(item.get("name", "")).lower().endswith(".json")
    ]
    if not items:
        raise ValueError(f"No JSON export files found in Yandex Disk folder: {forms_folder}")

    latest = max(items, key=_resource_sort_key)
    path = latest.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("Latest JSON export does not contain a path.")
    return path.removeprefix("disk:")


def _download_reference_images(
    disk_client: YandexDiskClient,
    participants: list[Participant],
    references_dir: Path,
) -> dict[str, list[Path]]:
    downloaded: dict[str, list[Path]] = {}
    for participant_index, participant in enumerate(participants, start=1):
        participant_dir = references_dir / f"participant_{participant_index:03d}"
        participant_dir.mkdir(parents=True, exist_ok=True)
        downloaded[participant.email] = []

        for index, disk_path in enumerate(participant.image_disk_paths, start=1):
            suffix = Path(disk_path).suffix
            local_name = f"{index:02d}{suffix}" if suffix else f"{index:02d}"
            local_path = participant_dir / local_name
            disk_client.download_file(disk_path, local_path, overwrite=True)
            downloaded[participant.email].append(local_path)
    return downloaded


def _write_database(
    database_path: Path,
    participants: list[Participant],
    downloaded_images: dict[str, list[Path]],
) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        _delete_participants_missing_from_export(connection, participants)

        for participant in participants:
            connection.execute(
                """
                INSERT INTO participants (email, name, policy_accepted, imported_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    name = excluded.name,
                    policy_accepted = excluded.policy_accepted,
                    imported_at = excluded.imported_at
                """,
                (
                    participant.email,
                    participant.name,
                    int(participant.policy_accepted),
                    datetime.now(UTC).isoformat(),
                ),
            )
            participant_id = connection.execute(
                "SELECT id FROM participants WHERE email = ?",
                (participant.email,),
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM reference_images WHERE participant_id = ?",
                (participant_id,),
            )

            local_paths = downloaded_images[participant.email]
            for disk_path, local_path in zip(participant.image_disk_paths, local_paths):
                connection.execute(
                    """
                    INSERT INTO reference_images (participant_id, disk_path, local_path)
                    VALUES (?, ?, ?)
                    """,
                    (participant_id, disk_path, str(local_path)),
                )


def _delete_participants_missing_from_export(
    connection: sqlite3.Connection,
    participants: list[Participant],
) -> None:
    emails = [participant.email for participant in participants]
    if not emails:
        connection.execute("DELETE FROM participants")
        return

    placeholders = ", ".join("?" for _ in emails)
    connection.execute(
        f"DELETE FROM participants WHERE email NOT IN ({placeholders})",
        emails,
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            policy_accepted INTEGER NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reference_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
            disk_path TEXT NOT NULL,
            local_path TEXT NOT NULL
        )
        """
    )


def _resource_sort_key(resource: dict[str, object]) -> str:
    value = resource.get("created") or resource.get("modified") or resource.get("name") or ""
    return str(value)


def _join_disk_path(parent: str, child: str) -> str:
    return f"{parent.rstrip('/')}/{child.lstrip('/')}"

