"""Workflow for matching event photos to participants and copying them on Disk."""

from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

from face_analysis import FaceAnalyzer, FaceEmbedding, YuNetConfig
from forms_export import ingest_forms_export
from forms_export.ingest import DEFAULT_DATA_DIR, DEFAULT_DATABASE_PATH
from yandex_disk import DiskApiError, YandexDiskClient


DEFAULT_YUNET_MODEL_PATH = Path("data/models/face_detection_yunet_2023mar.onnx")
DEFAULT_SFACE_MODEL_PATH = Path("data/models/face_recognition_sface_2021dec.onnx")
DEFAULT_EVENT_PHOTOS_DIR = Path("data/event_photos")
DEFAULT_LOCAL_DISTRIBUTION_DIR = Path("data/local_distribution")
DEFAULT_SIMILARITY_THRESHOLD = 0.45
DEFAULT_QUARANTINE_FOLDER_NAME = "quarantine"
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


@dataclass(frozen=True)
class DistributionConfig:
    database_path: Path = DEFAULT_DATABASE_PATH
    forms_data_dir: Path = DEFAULT_DATA_DIR
    event_photos_dir: Path = DEFAULT_EVENT_PHOTOS_DIR
    local_distribution_dir: Path = DEFAULT_LOCAL_DISTRIBUTION_DIR
    yunet_model_path: Path = DEFAULT_YUNET_MODEL_PATH
    sface_model_path: Path = DEFAULT_SFACE_MODEL_PATH
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    quarantine_folder_name: str = DEFAULT_QUARANTINE_FOLDER_NAME


@dataclass(frozen=True)
class DistributionResult:
    participants_count: int
    reference_embeddings_count: int
    event_photos_count: int
    event_faces_count: int
    face_matches_count: int
    planned_copies_count: int
    copied_to_disk_count: int
    quarantined_photos_count: int
    database_path: Path
    local_distribution_path: Path
    local_artifact_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ParticipantRecord:
    id: int
    email: str
    name: str


@dataclass(frozen=True)
class ReferenceImageRecord:
    id: int
    participant_id: int
    disk_path: str
    local_path: Path


@dataclass(frozen=True)
class ReferenceEmbeddingRecord:
    id: int
    participant_id: int
    vector: tuple[float, ...]


@dataclass(frozen=True)
class EventPhotoRecord:
    id: int
    name: str
    disk_path: str
    local_path: Path


T = TypeVar("T")


def run_distribution(
    disk_client: YandexDiskClient,
    event_folder: str,
    form_id: str,
    *,
    config: DistributionConfig | None = None,
) -> DistributionResult:
    """Run the full local-analysis and Yandex-Disk-copy workflow."""

    cfg = config or DistributionConfig()
    event_folder = event_folder.rstrip("/")
    event_slug = _safe_file_part(event_folder.strip("/") or "event")
    local_event_dir = cfg.event_photos_dir / event_slug
    local_output_root = cfg.local_distribution_dir / event_slug
    local_event_dir.mkdir(parents=True, exist_ok=True)
    local_output_root.mkdir(parents=True, exist_ok=True)

    _retry_disk(lambda: disk_client.get_resource(event_folder))
    ingest_forms_export(
        disk_client,
        form_id,
        data_dir=cfg.forms_data_dir,
        database_path=cfg.database_path,
    )

    analyzer = FaceAnalyzer(
        cfg.yunet_model_path,
        cfg.sface_model_path,
        detector_config=YuNetConfig(),
    )

    with sqlite3.connect(cfg.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_workflow_schema(connection)
        _clear_workflow_tables(connection)

        participants = _load_participants(connection)
        reference_images = _load_reference_images(connection)
        participant_folders = _store_participant_folders(
            connection,
            event_folder,
            participants,
        )

        reference_embeddings = _compute_reference_embeddings(
            connection,
            analyzer,
            reference_images,
        )
        event_photos = _download_event_photos(
            connection,
            disk_client,
            event_folder,
            local_event_dir,
        )
        event_faces_count, face_matches_count = _analyze_event_photos(
            connection,
            analyzer,
            event_photos,
            reference_embeddings,
            cfg.similarity_threshold,
        )
        planned_copies_count, quarantined_photos_count = _build_copy_plan(
            connection,
            event_photos,
            participant_folders,
            local_output_root,
            event_folder,
            cfg.quarantine_folder_name,
        )
        connection.commit()
        copied_to_disk_count = _apply_copy_plan(
            connection,
            disk_client,
            participant_folders,
            event_folder,
            cfg.quarantine_folder_name,
        )

    return DistributionResult(
        participants_count=len(participants),
        reference_embeddings_count=len(reference_embeddings),
        event_photos_count=len(event_photos),
        event_faces_count=event_faces_count,
        face_matches_count=face_matches_count,
        planned_copies_count=planned_copies_count,
        copied_to_disk_count=copied_to_disk_count,
        quarantined_photos_count=quarantined_photos_count,
        database_path=cfg.database_path,
        local_distribution_path=local_output_root,
        local_artifact_paths=(
            cfg.forms_data_dir,
            local_event_dir,
            local_output_root,
            cfg.database_path,
        ),
    )


def cleanup_local_artifacts(result: DistributionResult) -> None:
    """Remove local files created by the main distribution workflow."""

    for path in result.local_artifact_paths:
        _remove_local_artifact(path)


def _create_workflow_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reference_face_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_image_id INTEGER NOT NULL REFERENCES reference_images(id) ON DELETE CASCADE,
            participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
            face_index INTEGER NOT NULL,
            detection_score REAL NOT NULL,
            bbox_json TEXT NOT NULL,
            landmarks_json TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disk_path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            local_path TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_photo_id INTEGER NOT NULL REFERENCES event_photos(id) ON DELETE CASCADE,
            face_index INTEGER NOT NULL,
            detection_score REAL NOT NULL,
            bbox_json TEXT NOT NULL,
            landmarks_json TEXT NOT NULL,
            embedding_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS face_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_face_id INTEGER NOT NULL REFERENCES event_faces(id) ON DELETE CASCADE,
            participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
            reference_embedding_id INTEGER NOT NULL REFERENCES reference_face_embeddings(id) ON DELETE CASCADE,
            similarity REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS participant_output_folders (
            participant_id INTEGER PRIMARY KEY REFERENCES participants(id) ON DELETE CASCADE,
            folder_name TEXT NOT NULL,
            disk_path TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_copy_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_photo_id INTEGER NOT NULL REFERENCES event_photos(id) ON DELETE CASCADE,
            participant_id INTEGER REFERENCES participants(id) ON DELETE CASCADE,
            destination_kind TEXT NOT NULL,
            source_disk_path TEXT NOT NULL,
            destination_disk_path TEXT NOT NULL,
            local_destination_path TEXT NOT NULL,
            copied_to_disk INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


def _clear_workflow_tables(connection: sqlite3.Connection) -> None:
    for table in (
        "photo_copy_plan",
        "participant_output_folders",
        "face_matches",
        "event_faces",
        "event_photos",
        "reference_face_embeddings",
    ):
        connection.execute(f"DELETE FROM {table}")


def _load_participants(connection: sqlite3.Connection) -> list[ParticipantRecord]:
    rows = connection.execute(
        """
        SELECT id, email, name
        FROM participants
        WHERE policy_accepted = 1
        ORDER BY id
        """
    ).fetchall()
    return [ParticipantRecord(id=row[0], email=row[1], name=row[2]) for row in rows]


def _load_reference_images(connection: sqlite3.Connection) -> list[ReferenceImageRecord]:
    rows = connection.execute(
        """
        SELECT id, participant_id, disk_path, local_path
        FROM reference_images
        ORDER BY participant_id, id
        """
    ).fetchall()
    return [
        ReferenceImageRecord(
            id=row[0],
            participant_id=row[1],
            disk_path=row[2],
            local_path=Path(row[3]),
        )
        for row in rows
    ]


def _store_participant_folders(
    connection: sqlite3.Connection,
    event_folder: str,
    participants: list[ParticipantRecord],
) -> dict[int, str]:
    folder_names = _participant_folder_names(participants)
    for participant in participants:
        folder_name = folder_names[participant.id]
        connection.execute(
            """
            INSERT INTO participant_output_folders (participant_id, folder_name, disk_path)
            VALUES (?, ?, ?)
            """,
            (
                participant.id,
                folder_name,
                _join_disk_path(event_folder, folder_name),
            ),
        )
    return folder_names


def _compute_reference_embeddings(
    connection: sqlite3.Connection,
    analyzer: FaceAnalyzer,
    reference_images: list[ReferenceImageRecord],
) -> list[ReferenceEmbeddingRecord]:
    records: list[ReferenceEmbeddingRecord] = []
    for reference_image in reference_images:
        embeddings = analyzer.embed(reference_image.local_path)
        for face_index, embedding in enumerate(embeddings, start=1):
            row_id = _insert_reference_embedding(
                connection,
                reference_image,
                face_index,
                embedding,
            )
            records.append(
                ReferenceEmbeddingRecord(
                    id=row_id,
                    participant_id=reference_image.participant_id,
                    vector=embedding.vector,
                )
            )
    return records


def _insert_reference_embedding(
    connection: sqlite3.Connection,
    reference_image: ReferenceImageRecord,
    face_index: int,
    embedding: FaceEmbedding,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO reference_face_embeddings (
            reference_image_id,
            participant_id,
            face_index,
            detection_score,
            bbox_json,
            landmarks_json,
            embedding_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reference_image.id,
            reference_image.participant_id,
            face_index,
            embedding.detection.score,
            json.dumps(asdict(embedding.detection.box)),
            json.dumps(asdict(embedding.detection.landmarks)),
            json.dumps(list(embedding.vector)),
            _now(),
        ),
    )
    return int(cursor.lastrowid)


def _download_event_photos(
    connection: sqlite3.Connection,
    disk_client: YandexDiskClient,
    event_folder: str,
    local_event_dir: Path,
) -> list[EventPhotoRecord]:
    items = _retry_disk(lambda: disk_client.list_files(event_folder, limit=100))
    photo_items = [
        item
        for item in items
        if item.get("type") == "file"
        and Path(str(item.get("name", ""))).suffix.lower() in IMAGE_EXTENSIONS
    ]

    records: list[EventPhotoRecord] = []
    for item in photo_items:
        name = str(item.get("name"))
        disk_path = str(item.get("path")).removeprefix("disk:")
        local_path = local_event_dir / name
        _retry_disk(lambda: disk_client.download_file(disk_path, local_path, overwrite=True))
        cursor = connection.execute(
            """
            INSERT INTO event_photos (disk_path, name, local_path, processed_at)
            VALUES (?, ?, ?, ?)
            """,
            (disk_path, name, str(local_path), _now()),
        )
        records.append(
            EventPhotoRecord(
                id=int(cursor.lastrowid),
                name=name,
                disk_path=disk_path,
                local_path=local_path,
            )
        )
    return records


def _analyze_event_photos(
    connection: sqlite3.Connection,
    analyzer: FaceAnalyzer,
    event_photos: list[EventPhotoRecord],
    reference_embeddings: list[ReferenceEmbeddingRecord],
    similarity_threshold: float,
) -> tuple[int, int]:
    event_faces_count = 0
    face_matches_count = 0

    for photo in event_photos:
        embeddings = analyzer.embed(photo.local_path)
        for face_index, embedding in enumerate(embeddings, start=1):
            event_faces_count += 1
            event_face_id = _insert_event_face(connection, photo.id, face_index, embedding)

            for reference_embedding in reference_embeddings:
                similarity = cosine_similarity(embedding.vector, reference_embedding.vector)
                if similarity < similarity_threshold:
                    continue
                connection.execute(
                    """
                    INSERT INTO face_matches (
                        event_face_id,
                        participant_id,
                        reference_embedding_id,
                        similarity
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event_face_id,
                        reference_embedding.participant_id,
                        reference_embedding.id,
                        similarity,
                    ),
                )
                face_matches_count += 1

    return event_faces_count, face_matches_count


def _insert_event_face(
    connection: sqlite3.Connection,
    event_photo_id: int,
    face_index: int,
    embedding: FaceEmbedding,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO event_faces (
            event_photo_id,
            face_index,
            detection_score,
            bbox_json,
            landmarks_json,
            embedding_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_photo_id,
            face_index,
            embedding.detection.score,
            json.dumps(asdict(embedding.detection.box)),
            json.dumps(asdict(embedding.detection.landmarks)),
            json.dumps(list(embedding.vector)),
        ),
    )
    return int(cursor.lastrowid)


def _build_copy_plan(
    connection: sqlite3.Connection,
    event_photos: list[EventPhotoRecord],
    participant_folders: dict[int, str],
    local_output_root: Path,
    event_folder: str,
    quarantine_folder_name: str,
) -> tuple[int, int]:
    for folder_name in participant_folders.values():
        (local_output_root / folder_name).mkdir(parents=True, exist_ok=True)
    (local_output_root / quarantine_folder_name).mkdir(parents=True, exist_ok=True)

    participant_ids_by_photo = _matched_participant_ids_by_photo(connection)
    planned_count = 0
    quarantined_count = 0

    for photo in event_photos:
        participant_ids = sorted(participant_ids_by_photo.get(photo.id, set()))
        if participant_ids:
            for participant_id in participant_ids:
                folder_name = participant_folders[participant_id]
                local_destination_path = local_output_root / folder_name / photo.name
                shutil.copy2(photo.local_path, local_destination_path)
                _insert_copy_plan(
                    connection,
                    photo,
                    participant_id,
                    "participant",
                    _join_disk_path(event_folder, folder_name, photo.name),
                    local_destination_path,
                )
                planned_count += 1
        else:
            quarantined_count += 1
            local_destination_path = local_output_root / quarantine_folder_name / photo.name
            shutil.copy2(photo.local_path, local_destination_path)
            _insert_copy_plan(
                connection,
                photo,
                None,
                "quarantine",
                _join_disk_path(event_folder, quarantine_folder_name, photo.name),
                local_destination_path,
            )
            planned_count += 1

    return planned_count, quarantined_count


def _matched_participant_ids_by_photo(connection: sqlite3.Connection) -> dict[int, set[int]]:
    rows = connection.execute(
        """
        SELECT DISTINCT event_faces.event_photo_id, face_matches.participant_id
        FROM face_matches
        JOIN event_faces ON event_faces.id = face_matches.event_face_id
        ORDER BY event_faces.event_photo_id, face_matches.participant_id
        """
    ).fetchall()
    result: dict[int, set[int]] = {}
    for photo_id, participant_id in rows:
        result.setdefault(photo_id, set()).add(participant_id)
    return result


def _insert_copy_plan(
    connection: sqlite3.Connection,
    photo: EventPhotoRecord,
    participant_id: int | None,
    destination_kind: str,
    destination_disk_path: str,
    local_destination_path: Path,
) -> None:
    connection.execute(
        """
        INSERT INTO photo_copy_plan (
            event_photo_id,
            participant_id,
            destination_kind,
            source_disk_path,
            destination_disk_path,
            local_destination_path,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            photo.id,
            participant_id,
            destination_kind,
            photo.disk_path,
            destination_disk_path,
            str(local_destination_path),
            _now(),
        ),
    )


def _apply_copy_plan(
    connection: sqlite3.Connection,
    disk_client: YandexDiskClient,
    participant_folders: dict[int, str],
    event_folder: str,
    quarantine_folder_name: str,
) -> int:
    for folder_name in participant_folders.values():
        _ensure_disk_folder(disk_client, _join_disk_path(event_folder, folder_name))
    _ensure_disk_folder(disk_client, _join_disk_path(event_folder, quarantine_folder_name))

    rows = connection.execute(
        """
        SELECT id, source_disk_path, destination_disk_path
        FROM photo_copy_plan
        ORDER BY id
        """
    ).fetchall()

    copied_count = 0
    for plan_id, source_disk_path, destination_disk_path in rows:
        _retry_disk(
            lambda: disk_client.copy_resource(
                source_disk_path,
                destination_disk_path,
                overwrite=True,
            )
        )
        connection.execute(
            "UPDATE photo_copy_plan SET copied_to_disk = 1 WHERE id = ?",
            (plan_id,),
        )
        connection.commit()
        copied_count += 1
    return copied_count


def _ensure_disk_folder(disk_client: YandexDiskClient, path: str) -> None:
    try:
        _retry_disk(lambda: disk_client.create_folder(path))
    except DiskApiError as exc:
        if exc.status_code != 409:
            raise


def _participant_folder_names(participants: list[ParticipantRecord]) -> dict[int, str]:
    used: set[str] = set()
    result: dict[int, str] = {}
    for participant in participants:
        base = _safe_disk_name(participant.name) or _safe_disk_name(participant.email.split("@")[0])
        if not base:
            base = f"participant_{participant.id}"

        candidate = base
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{base}_{suffix}"
            suffix += 1

        used.add(candidate.lower())
        result[participant.id] = candidate
    return result


def _safe_disk_name(value: str) -> str:
    stripped = value.strip().replace("/", "_").replace("\\", "_")
    stripped = re.sub(r'[:*?"<>|\x00-\x1f]+', "_", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip(" ._")


def _safe_file_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "event"


def _join_disk_path(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part]
    return "/" + "/".join(cleaned)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _retry_disk(operation: Callable[[], T], *, attempts: int = 3) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except DiskApiError as exc:
            if exc.status_code is not None and exc.status_code < 500:
                raise
            if attempt == attempts:
                raise
            time.sleep(attempt)
        except OSError:
            if attempt == attempts:
                raise
            time.sleep(attempt)
    raise RuntimeError("Unreachable retry state.")


def _remove_local_artifact(path: Path) -> None:
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    data_root = (cwd / "data").resolve()
    if not _is_relative_to(resolved, data_root):
        raise ValueError(f"Refusing to remove local artifact outside data directory: {path}")

    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
