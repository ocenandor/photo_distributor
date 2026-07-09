"""Tests for the live email-driven event workflow."""

from __future__ import annotations

import json
import time
from pathlib import Path

from face_analysis import EventFaceMatch, FaceAnalysisStepResult, ReferenceEmbeddingRecord
from forms_export import FormsIngestResult, ImportedParticipant, ImportedReferenceImage
from mail_client import MailAttachment, MailClientError, MailMessage
import photo_distribution_utils.live_workflow as live_workflow_module
from photo_distribution_utils.apply_distribution_plan import DistributionConfig
from photo_distribution_utils.event_artifacts import EventArtifactPaths
from photo_distribution_utils.live_workflow import (
    LiveEventConfig,
    LiveEventRuntime,
    run_live_event_once,
)
from yandex_disk import YandexDiskUiError


FORM_ID = "live_form"
FORMS_FOLDER = f"/Yandex.Forms/{FORM_ID}"
SUBJECT = (
    "\u041e\u0442\u0432\u0435\u0442_\u043d\u0430_\u0444\u043e\u0440\u043c\u0443"
    f"__Photo event__{FORM_ID}__answer_001"
)
VALID_IMAGE_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01"
    b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)
PARTICIPANT_ACCESS_READY_SUBJECT = "Фотодистрибьютор: доступ к Яндекс Диску готов"
MANUAL_ACCESS_REQUIRED_SUBJECT = (
    "Фотодистрибьютор: требуется ручная выдача доступа к Яндекс Диску"
)
DUPLICATE_PARTICIPANT_EMAIL_SUBJECT = "Фотодистрибьютор: повторный email участника"


def test_run_live_event_creates_event_folder_before_polling(monkeypatch, tmp_path: Path) -> None:
    disk_client = _EmptyEventFolderDiskClient()
    mail_client = _EmptyMailClient()
    access_grantor = _FakeAccessGrantor()

    monkeypatch.setattr(
        live_workflow_module.YandexDiskClient,
        "from_env",
        classmethod(lambda cls: disk_client),
    )
    monkeypatch.setattr(
        live_workflow_module.MailClient,
        "from_env",
        classmethod(lambda cls: mail_client),
    )
    monkeypatch.setattr(
        live_workflow_module.YandexDiskUiAccessGrantor,
        "from_env",
        classmethod(lambda cls: access_grantor),
    )
    monkeypatch.setattr(live_workflow_module, "FaceAnalyzer", _FakeAnalyzer)
    monkeypatch.setattr(
        live_workflow_module.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    result = live_workflow_module.run_live_event(
        FORM_ID,
        "/event",
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            ),
            status_file_path=tmp_path / "status.json",
        ),
    )

    assert result.iterations_count == 1
    assert disk_client.created_folders == ["/event"]
    status_payload = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status_payload["state"] == "stopped"
    assert status_payload["iterations_count"] == 1


def test_run_live_event_once_processes_email_and_new_event_photo(tmp_path: Path) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.downloaded_event_photos_count == 1
    assert result.access_grants_count == 1
    assert result.access_grant_failures_count == 0
    assert result.planned_copies_count == 1
    assert result.copied_to_disk_count == 1
    assert result.plan_rebuilt is True
    assert access_grantor.grants == [("/event", "participant@example.com")]
    assert mail_client.sent_messages == [
        (
            "participant@example.com",
            PARTICIPANT_ACCESS_READY_SUBJECT,
        )
    ]
    assert "Вам открыт доступ на запись к общей папке события." in mail_client.sent_bodies[0]
    assert "https://disk.yandex.ru/client/disk/event" in mail_client.sent_bodies[0]
    assert disk_client.created_folders == ["/event/Pavel__output", "/event/quarantine"]
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]
    assert disk_client.deleted == [("/event/quarantine/photo.jpg", False)]

    payload = json.loads((tmp_path / "plans" / "copy_plan.json").read_text(encoding="utf-8"))
    assert payload["copies"][0]["destination_disk_path"] == "/event/Pavel__output/photo.jpg"


def test_run_live_event_once_ignores_other_form_id(tmp_path: Path) -> None:
    other_subject = (
        "\u041e\u0442\u0432\u0435\u0442_\u043d\u0430_\u0444\u043e\u0440\u043c\u0443"
        "__Photo event__other_form__answer_001"
    )
    disk_client = _FakeDiskClient()
    mail_client = _FakeMailClient(_message(other_subject))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(distribution_config=DistributionConfig()),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 0
    assert result.plan_rebuilt is False
    assert access_grantor.grants == []


def test_run_live_event_once_processes_disk_forms_export(tmp_path: Path) -> None:
    disk_client = _FormsExportDiskClient()
    mail_client = _EmptyMailClient()
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 0
    assert result.downloaded_event_photos_count == 1
    assert result.access_grants_count == 1
    assert result.plan_rebuilt is True
    assert runtime.last_forms_json_disk_path == f"{FORMS_FOLDER}/forms-export.json"
    assert access_grantor.grants == [("/event", "diskparticipant@example.com")]
    assert mail_client.sent_messages == [
        (
            "diskparticipant@example.com",
            PARTICIPANT_ACCESS_READY_SUBJECT,
        )
    ]
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]


def test_run_live_event_once_continues_when_mail_fetch_fails(tmp_path: Path) -> None:
    disk_client = _FormsExportDiskClient()
    mail_client = _FetchFailingMailClient()
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 0
    assert result.access_grants_count == 1
    assert result.plan_rebuilt is True
    assert runtime.processed_answer_ids == set()
    assert runtime.last_forms_json_disk_path == f"{FORMS_FOLDER}/forms-export.json"
    assert mail_client.sent_messages == [
        (
            "diskparticipant@example.com",
            PARTICIPANT_ACCESS_READY_SUBJECT,
        )
    ]


def test_run_live_event_once_skips_invalid_disk_forms_export(tmp_path: Path) -> None:
    disk_client = _InvalidFormsExportDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.access_grants_count == 1
    assert result.plan_rebuilt is True
    assert runtime.disk_forms_ingest is None
    assert runtime.last_forms_json_disk_path == f"{FORMS_FOLDER}/forms-export.json"
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]


def test_run_live_event_once_saves_references_before_event_photos_exist(tmp_path: Path) -> None:
    disk_client = _EmptyEventFolderDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(distribution_config=DistributionConfig()),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.access_grants_count == 1
    assert result.downloaded_event_photos_count == 0
    assert result.plan_rebuilt is False
    assert (tmp_path / "references" / "participant_001" / "01_reference.jpg").read_bytes() == b"reference image"


def test_run_live_event_once_deduplicates_processed_answer_and_cached_photo(tmp_path: Path) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)
    config = LiveEventConfig(distribution_config=DistributionConfig())

    run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=config,
        poll_event_photos=True,
    )
    disk_client.downloads.clear()

    second_result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=config,
        poll_event_photos=True,
    )

    assert second_result.new_answers_count == 0
    assert second_result.downloaded_event_photos_count == 0
    assert second_result.plan_rebuilt is False
    assert disk_client.downloads == []
    assert access_grantor.grants == [("/event", "participant@example.com")]
    assert mail_client.sent_messages == [
        (
            "participant@example.com",
            PARTICIPANT_ACCESS_READY_SUBJECT,
        )
    ]


def test_run_live_event_once_retries_when_access_grant_fails(tmp_path: Path) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FailingAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.access_grants_count == 0
    assert result.access_grant_failures_count == 1
    assert result.plan_rebuilt is True
    assert runtime.processed_answer_ids == {"answer_001"}
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]
    assert mail_client.sent_messages == [
        (
            "admin@example.com",
            MANUAL_ACCESS_REQUIRED_SUBJECT,
        )
    ]
    assert "Пожалуйста, выдайте доступ на редактирование вручную" in mail_client.sent_bodies[0]
    assert "https://disk.yandex.ru/client/disk/event" in mail_client.sent_bodies[0]


def test_run_live_event_once_sends_manual_alert_when_access_grant_times_out(
    tmp_path: Path,
) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _SlowAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            access_grant_timeout_seconds=0.01,
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            ),
        ),
        poll_event_photos=True,
    )

    assert result.access_grant_failures_count == 1
    assert result.access_grants_count == 0
    assert result.plan_rebuilt is True
    assert runtime.processed_answer_ids == {"answer_001"}
    assert runtime.access_grant_alerted_source_ids == {"participant:1"}
    assert mail_client.sent_messages == [
        (
            "admin@example.com",
            MANUAL_ACCESS_REQUIRED_SUBJECT,
        )
    ]


def test_run_live_event_once_continues_when_participant_notification_fails(
    tmp_path: Path,
) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FailingMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.access_grants_count == 1
    assert result.access_grant_failures_count == 0
    assert result.plan_rebuilt is True
    assert runtime.processed_answer_ids == {"answer_001"}
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]


def test_run_live_event_once_continues_when_admin_alert_fails(tmp_path: Path) -> None:
    disk_client = _FakeDiskClient()
    mail_client = _FailingMailClient(_message(SUBJECT))
    access_grantor = _FailingAccessGrantor()
    runtime = _runtime(tmp_path)

    result = run_live_event_once(
        disk_client,
        mail_client,
        access_grantor,
        runtime,
        config=LiveEventConfig(
            distribution_config=DistributionConfig(
                forms_data_dir=tmp_path / "forms",
                event_photos_dir=tmp_path / "event_photos",
                copy_plans_dir=tmp_path / "plans",
            )
        ),
        poll_event_photos=True,
    )

    assert result.new_answers_count == 1
    assert result.access_grants_count == 0
    assert result.access_grant_failures_count == 1
    assert result.plan_rebuilt is True
    assert runtime.processed_answer_ids == {"answer_001"}
    assert disk_client.copied == [("/event/photo.jpg", "/event/Pavel__output/photo.jpg", True)]


def test_merge_forms_ingest_keeps_duplicate_email_as_separate_participants(tmp_path: Path) -> None:
    source = FormsIngestResult(
        json_disk_path="/Yandex.Forms/live_form/forms-export.json",
        local_json_path=tmp_path / "forms-export.json",
        participants=(
            _imported_participant(
                1,
                "First Person",
                "shared@example.com",
                tmp_path / "first.jpg",
            ),
            _imported_participant(
                2,
                "Second Person",
                "shared@example.com",
                tmp_path / "second.jpg",
            ),
        ),
        participants_count=2,
        reference_images_count=2,
    )
    empty_email_source = FormsIngestResult(
        json_disk_path="",
        local_json_path=Path(),
        participants=(),
        participants_count=0,
        reference_images_count=0,
    )

    merged = live_workflow_module._merge_forms_ingest_results(empty_email_source, source)

    assert merged.participants_count == 2
    assert [participant.name for participant in merged.participants] == [
        "First Person",
        "Second Person",
    ]
    assert [participant.email for participant in merged.participants] == [
        "shared@example.com",
        "shared@example.com",
    ]
    assert [participant.id for participant in merged.participants] == [1, 2]
    assert [image.participant_id for image in merged.reference_images] == [1, 2]


def test_grant_access_skips_duplicate_email_and_alerts_admin(tmp_path: Path) -> None:
    forms_ingest = FormsIngestResult(
        json_disk_path="/Yandex.Forms/live_form/forms-export.json",
        local_json_path=tmp_path / "forms-export.json",
        participants=(
            _imported_participant(
                1,
                "First Person",
                "shared@example.com",
                tmp_path / "first.jpg",
            ),
            _imported_participant(
                2,
                "Second Person",
                "shared@example.com",
                tmp_path / "second.jpg",
            ),
        ),
        participants_count=2,
        reference_images_count=2,
    )
    mail_client = _FakeMailClient(_message(SUBJECT))
    access_grantor = _FakeAccessGrantor()
    runtime = _runtime(tmp_path)

    grants_count, failures_count = live_workflow_module._grant_access_for_new_participants(
        mail_client,
        access_grantor,
        runtime,
        forms_ingest,
        config=LiveEventConfig(distribution_config=DistributionConfig()),
    )

    assert grants_count == 1
    assert failures_count == 0
    assert access_grantor.grants == [("/event", "shared@example.com")]
    assert mail_client.sent_messages == [
        (
            "shared@example.com",
            PARTICIPANT_ACCESS_READY_SUBJECT,
        ),
        (
            "admin@example.com",
            DUPLICATE_PARTICIPANT_EMAIL_SUBJECT,
        ),
    ]
    assert "уже была попытка выдачи доступа" in mail_client.sent_bodies[1]
    assert runtime.access_handled_participant_emails == {"shared@example.com"}
    assert runtime.duplicate_access_alerted_source_ids == {"participant:2"}


class _FakeDiskClient:
    """Fake Yandex Disk client for one live event iteration."""

    def __init__(self) -> None:
        self.created_folders: list[str] = []
        self.copied: list[tuple[str, str, bool]] = []
        self.deleted: list[tuple[str, bool]] = []
        self.downloads: list[str] = []

    def get_resource(self, path: str) -> dict[str, object]:
        assert path == "/event"
        return {"type": "dir", "public_url": "https://disk.yandex.ru/d/event"}

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        if path == FORMS_FOLDER:
            return []
        assert path == "/event"
        assert limit == 100
        return [
            {
                "type": "file",
                "name": "photo.jpg",
                "path": "disk:/event/photo.jpg",
            }
        ]

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        self.downloads.append(disk_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path

    def ensure_folder(self, path: str) -> None:
        self.created_folders.append(path)

    def copy_resource(self, from_path: str, to_path: str, *, overwrite: bool = False) -> dict[str, object]:
        self.copied.append((from_path, to_path, overwrite))
        return {}

    def delete_resource(self, path: str, *, permanently: bool = False) -> dict[str, object]:
        self.deleted.append((path, permanently))
        return {}


class _EmptyEventFolderDiskClient(_FakeDiskClient):
    """Fake Disk client with no event photos yet."""

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        if path == FORMS_FOLDER:
            return []
        assert path == "/event"
        assert limit == 100
        return []


class _FormsExportDiskClient(_FakeDiskClient):
    """Fake Disk client with one optional JSON forms export."""

    def list_files(self, path: str, limit: int = 1000) -> list[dict[str, object]]:
        if path == FORMS_FOLDER:
            return [
                {
                    "type": "file",
                    "name": "forms-export.json",
                    "path": f"disk:{FORMS_FOLDER}/forms-export.json",
                    "created": "2026-07-08T10:00:00+03:00",
                }
            ]
        return super().list_files(path, limit=limit)

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        self.downloads.append(disk_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if disk_path == f"{FORMS_FOLDER}/forms-export.json":
            local_path.write_text(_forms_export_json(), encoding="utf-8")
        elif disk_path == f"{FORMS_FOLDER}/Files/reference.jpg":
            local_path.write_bytes(b"reference image")
        else:
            local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path


class _InvalidFormsExportDiskClient(_FormsExportDiskClient):
    """Fake Disk client with a malformed JSON forms export."""

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        self.downloads.append(disk_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if disk_path == f"{FORMS_FOLDER}/forms-export.json":
            local_path.write_text(_forms_export_json_without_images(), encoding="utf-8")
        else:
            local_path.write_bytes(VALID_IMAGE_BYTES)
        return local_path


class _FakeMailConfig:
    """Fake mail config exposing only the forms folder contract."""

    forms_folder = "Yandex.Forms"
    admin_email = "admin@example.com"


class _FakeMailClient:
    """Fake mail client with one forms folder."""

    def __init__(self, message: MailMessage) -> None:
        self.config = _FakeMailConfig()
        self.message = message
        self.sent_messages: list[tuple[str, str]] = []
        self.sent_bodies: list[str] = []

    def fetch_messages(self, *, folder: str | None = None) -> tuple[MailMessage, ...]:
        assert folder == "Yandex.Forms"
        return (self.message,)

    def send_message(self, *, to_email: str, subject: str, body: str) -> None:
        assert body
        self.sent_messages.append((to_email, subject))
        self.sent_bodies.append(body)


class _FailingMailClient(_FakeMailClient):
    """Fake mail client whose SMTP send always fails."""

    def send_message(self, *, to_email: str, subject: str, body: str) -> None:
        raise RuntimeError("SMTP failed.")


class _EmptyMailClient:
    """Fake mail client without new messages."""

    def __init__(self) -> None:
        self.config = _FakeMailConfig()
        self.sent_messages: list[tuple[str, str]] = []
        self.sent_bodies: list[str] = []

    def fetch_messages(self, *, folder: str | None = None) -> tuple[MailMessage, ...]:
        assert folder == "Yandex.Forms"
        return ()

    def send_message(self, *, to_email: str, subject: str, body: str) -> None:
        assert body
        self.sent_messages.append((to_email, subject))
        self.sent_bodies.append(body)


class _FetchFailingMailClient(_EmptyMailClient):
    """Fake mail client whose IMAP fetch fails for one iteration."""

    def fetch_messages(self, *, folder: str | None = None) -> tuple[MailMessage, ...]:
        assert folder == "Yandex.Forms"
        raise MailClientError("IMAP failed.", safe_message="Mail IMAP request failed.")


class _FakeAccessGrantor:
    """Fake UI access grantor that records folder/email pairs."""

    def __init__(self) -> None:
        self.grants: list[tuple[str, str]] = []

    def grant_write_access(self, folder_path: str, email: str) -> None:
        self.grants.append((folder_path, email))

    def folder_url(self, folder_path: str) -> str:
        return f"https://disk.yandex.ru/client/disk/{folder_path.strip('/')}"


class _FailingAccessGrantor(_FakeAccessGrantor):
    """Fake UI access grantor that fails for every access request."""

    def grant_write_access(self, folder_path: str, email: str) -> None:
        raise YandexDiskUiError("UI failed.", safe_message="UI failed.")


class _SlowAccessGrantor(_FakeAccessGrantor):
    """Fake UI access grantor that does not finish before the workflow timeout."""

    def grant_write_access(self, folder_path: str, email: str) -> None:
        time.sleep(1)


class _FakeAnalyzer:
    """Fake analyzer that always matches the single participant."""

    def __init__(self, *args, **kwargs) -> None:
        """Accept production constructor arguments."""

    def analyze_distribution(self, reference_images, event_photos, similarity_threshold):
        assert len(reference_images) == 1
        assert len(event_photos) == 1
        return FaceAnalysisStepResult(
            reference_embeddings=(
                ReferenceEmbeddingRecord(id=1, participant_id=1, vector=(1.0, 0.0)),
            ),
            event_photos_count=1,
            event_faces_count=1,
            face_matches=(
                EventFaceMatch(
                    event_photo_id=1,
                    participant_id=1,
                    reference_embedding_id=1,
                    similarity=0.9,
                ),
            ),
        )


def _runtime(tmp_path: Path) -> LiveEventRuntime:
    """Build live runtime state for tests."""

    return LiveEventRuntime(
        form_id=FORM_ID,
        cloud_event_folder="/event",
        event_artifacts=EventArtifactPaths(
            event_folder="/event",
            local_event_key="event",
            local_event_photos_dir=tmp_path / "event_photos",
            copy_plan_dir=tmp_path / "plans",
            copy_plan_path=tmp_path / "plans" / "copy_plan.json",
        ),
        reference_dir=tmp_path / "references",
        analyzer=_FakeAnalyzer(),
    )


def _imported_participant(
    participant_id: int,
    name: str,
    email: str,
    reference_path: Path,
) -> ImportedParticipant:
    """Build one imported participant with one reference image."""

    return ImportedParticipant(
        id=participant_id,
        email=email,
        name=name,
        policy_accepted=True,
        reference_images=(
            ImportedReferenceImage(
                id=participant_id,
                participant_id=participant_id,
                disk_path=f"/references/{reference_path.name}",
                local_path=reference_path,
            ),
        ),
    )


def _message(subject: str) -> MailMessage:
    """Return one form answer mail message."""

    return MailMessage(
        uid="1",
        subject=subject,
        body=(
            "Accept: \u0414\u0430\n"
            "Name: Pavel\n"
            "Email: participant@example.com\n"
        ),
        sender="forms@example.com",
        attachments=(
            MailAttachment(
                filename="reference.jpg",
                content=b"reference image",
                content_type="image/jpeg",
            ),
        ),
    )


def _forms_export_json() -> str:
    """Return one fake Yandex Forms JSON export."""

    return json.dumps(
        [
            [
                ["ID", "answer-2"],
                ["Created", "2026-07-08 10:00:00"],
                ["Policy", "\u0414\u0430"],
                ["Display name", "Pavel"],
                ["Email", "diskparticipant@example.com"],
                ["Reference images", f"{FORMS_FOLDER}/Files/reference.jpg"],
            ]
        ]
    )


def _forms_export_json_without_images() -> str:
    """Return one fake Yandex Forms JSON export without reference images."""

    return json.dumps(
        [
            [
                ["ID", "answer-2"],
                ["Created", "2026-07-08 10:00:00"],
                ["Policy", "\u0414\u0430"],
                ["Display name", "Pavel"],
                ["Email", "diskparticipant@example.com"],
            ]
        ]
    )
