"""Live event workflow driven by Yandex Forms answer emails."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from uuid import uuid4

from face_analysis import EventPhotoForAnalysis, FaceAnalyzer, ReferenceImageForAnalysis, YuNetConfig
from forms_export import (
    EmailAnswer,
    EmailAttachment,
    FormsIngestResult,
    FormsExportError,
    ImportedParticipant,
    ImportedReferenceImage,
    email_answers_to_forms_ingest_result,
    find_latest_json_export,
    ingest_forms_export,
    parse_email_answer,
    parse_email_answer_subject,
)
from loguru import logger
from mail_client import MailClient, MailClientError, MailMessage
from yandex_disk import DiskApiError, YandexDiskClient, YandexDiskUiAccessGrantor, YandexDiskUiError

from .apply_distribution_plan import (
    DistributionArtifacts,
    DistributionConfig,
    DistributionCounters,
    DistributionResult,
    apply_distribution_plan,
    cleanup_local_artifacts,
)
from .cloud_files import (
    EventPhotoRecord,
    download_event_photos,
    validate_cloud_event_folder_path,
    validate_cloud_event_folder,
)
from .event_artifacts import EventArtifactPaths, prepare_event_artifact_paths
from .output_files_structure import (
    build_distribution_copy_plan,
    build_distribution_output_folders,
)


DEFAULT_EVENT_POLL_SECONDS = 1200
DEFAULT_FORM_POLL_SECONDS = 30
DEFAULT_EVENT_FOLDER_PREFIX = "event"
DEFAULT_ACCESS_GRANT_TIMEOUT_SECONDS = 240
DEFAULT_LIVE_STATUS_FILE = Path("data/live_status/live_event_status.json")
NO_FORMS_JSON_SAFE_MESSAGE = "No JSON export files found in the Yandex Forms folder."
PARTICIPANT_ACCESS_READY_SUBJECT = "Фотодистрибьютор: доступ к Яндекс Диску готов"
MANUAL_ACCESS_REQUIRED_SUBJECT = (
    "Фотодистрибьютор: требуется ручная выдача доступа к Яндекс Диску"
)
DUPLICATE_PARTICIPANT_EMAIL_SUBJECT = "Фотодистрибьютор: повторный email участника"


@dataclass(frozen=True, repr=False)
class LiveEventConfig:
    """Configuration for the live event runner.

    Attributes:
        event_poll_seconds: Seconds between Yandex Disk event-folder checks.
        form_poll_seconds: Seconds between form-source checks. One polling
            iteration reads both the forms mail folder and the optional
            `/Yandex.Forms/<form_id>/` JSON export folder.
        access_grant_timeout_seconds: Maximum seconds to wait for one Yandex
            Disk UI access-grant attempt before notifying the operator.
        status_file_path: Local JSON file overwritten with the current live
            runner state on every polling loop.
        cleanup_local: Whether the workflow removes live local artifacts when
            the runner stops.
        distribution_config: Shared model, threshold, and artifact-root config
            used by the live workflow.
    """

    event_poll_seconds: int = DEFAULT_EVENT_POLL_SECONDS
    form_poll_seconds: int = DEFAULT_FORM_POLL_SECONDS
    access_grant_timeout_seconds: float = DEFAULT_ACCESS_GRANT_TIMEOUT_SECONDS
    status_file_path: Path = DEFAULT_LIVE_STATUS_FILE
    cleanup_local: bool = False
    distribution_config: DistributionConfig = field(default_factory=DistributionConfig)

    def safe_summary(self) -> dict[str, object]:
        """Return values safe for logs."""

        return {
            "event_poll_seconds": self.event_poll_seconds,
            "form_poll_seconds": self.form_poll_seconds,
            "access_grant_timeout_seconds": self.access_grant_timeout_seconds,
            "status_file_enabled": True,
            "cleanup_local": self.cleanup_local,
            **self.distribution_config.safe_summary(),
        }


@dataclass
class LiveEventRuntime:
    """Mutable runtime state for one live event process.

    Attributes:
        form_id: Yandex Forms id accepted by this live runner.
        cloud_event_folder: Yandex Disk folder where event photos are uploaded.
        event_artifacts: Local artifact paths for the live event.
        reference_dir: Local directory where email reference attachments are
            saved.
        analyzer: Face analyzer used for reference/event embeddings and
            matching.
        answers: Accepted form answers parsed from email.
        processed_answer_ids: Form answer ids already processed by this runner.
        access_grant_alerted_source_ids: Form source ids for which the operator
            was already notified about a failed or timed-out UI access grant.
        duplicate_access_alerted_source_ids: Form source ids for which the
            operator was already notified about a duplicate access request for
            an email that was handled earlier.
        access_handled_participant_emails: Participant emails for which the
            live runner already attempted access and sent either a participant
            notification or an operator alert.
        disk_forms_ingest: Last imported JSON/Yandex Disk forms result, when
            the optional forms export folder exists.
        last_forms_json_disk_path: Last JSON export path imported from Yandex
            Disk forms export.
        known_event_photo_paths: Remote event photo paths already cached
            locally.
        event_photos: Current cached event photo records.
    """

    form_id: str
    cloud_event_folder: str
    event_artifacts: EventArtifactPaths
    reference_dir: Path
    analyzer: FaceAnalyzer
    answers: list[EmailAnswer] = field(default_factory=list)
    processed_answer_ids: set[str] = field(default_factory=set)
    access_grant_alerted_source_ids: set[str] = field(default_factory=set)
    duplicate_access_alerted_source_ids: set[str] = field(default_factory=set)
    access_handled_participant_emails: set[str] = field(default_factory=set)
    disk_forms_ingest: FormsIngestResult | None = None
    last_forms_json_disk_path: str = ""
    known_event_photo_paths: set[str] = field(default_factory=set)
    event_photos: list[EventPhotoRecord] = field(default_factory=list)


@dataclass(frozen=True, repr=False)
class LiveEventIterationResult:
    """Counters produced by one live workflow iteration.

    Attributes:
        new_answers_count: Number of new matching form emails processed.
        downloaded_event_photos_count: Number of event photos downloaded into
            the local cache during this iteration.
        access_grants_count: Number of new participants granted event folder
            write access during this iteration.
        access_grant_failures_count: Number of new participant access grants
            that could not be completed during this iteration.
        planned_copies_count: Number of remote copy operations planned.
        copied_to_disk_count: Number of planned copies applied on Yandex Disk.
        plan_rebuilt: Whether face analysis and copy-plan application ran.
    """

    new_answers_count: int
    downloaded_event_photos_count: int
    access_grants_count: int
    access_grant_failures_count: int
    planned_copies_count: int
    copied_to_disk_count: int
    plan_rebuilt: bool

    def safe_summary(self) -> dict[str, object]:
        """Return counters safe for logs."""

        return {
            "new_answers_count": self.new_answers_count,
            "downloaded_event_photos_count": self.downloaded_event_photos_count,
            "access_grants_count": self.access_grants_count,
            "access_grant_failures_count": self.access_grant_failures_count,
            "planned_copies_count": self.planned_copies_count,
            "copied_to_disk_count": self.copied_to_disk_count,
            "plan_rebuilt": self.plan_rebuilt,
        }


@dataclass(frozen=True, repr=False)
class LiveEventResult:
    """Summary returned when a live event runner stops.

    Attributes:
        iterations_count: Number of live iterations completed.
        participants_count: Number of currently imported participants.
        event_photos_count: Number of currently cached event photos.
        copied_to_disk_count: Copies applied during the last rebuilt plan.
        local_artifact_paths: Local artifact directories eligible for cleanup.
    """

    iterations_count: int
    participants_count: int
    event_photos_count: int
    copied_to_disk_count: int
    local_artifact_paths: tuple[Path, ...]

    def safe_summary(self) -> dict[str, object]:
        """Return a path-safe summary for logs."""

        return {
            "iterations_count": self.iterations_count,
            "participants_count": self.participants_count,
            "event_photos_count": self.event_photos_count,
            "copied_to_disk_count": self.copied_to_disk_count,
            "local_artifacts_count": len(self.local_artifact_paths),
        }


def run_live_event(
    form_id: str,
    cloud_event_folder: str | None,
    *,
    config: LiveEventConfig,
) -> LiveEventResult:
    """Create live services and run until interrupted.

    Args:
        form_id: Yandex Forms id expected in incoming email subjects.
        cloud_event_folder: Optional canonical Yandex Disk event folder path.
            When not provided, the workflow creates a unique absolute event
            folder path.
        config: Explicit live runner configuration from the CLI boundary.

    Returns:
        Safe counters and local artifacts when the runner stops.

    Side effects:
        Creates the event folder, reads the configured mail folder, grants
        participant write access through Yandex Disk UI automation, downloads
        new event photos, runs face analysis, writes copy-plan JSON, and copies
        existing remote photos into output folders.
    """

    disk_client = YandexDiskClient.from_env()
    mail_client = MailClient.from_env()
    access_grantor = YandexDiskUiAccessGrantor.from_env()

    if cloud_event_folder is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        selected_cloud_event_folder = f"/{DEFAULT_EVENT_FOLDER_PREFIX}_{timestamp}_{uuid4().hex[:8]}"
    else:
        selected_cloud_event_folder = cloud_event_folder
    validate_cloud_event_folder_path(selected_cloud_event_folder)
    disk_client.ensure_folder(selected_cloud_event_folder)
    validate_cloud_event_folder(disk_client, selected_cloud_event_folder)

    event_artifacts = prepare_event_artifact_paths(selected_cloud_event_folder, config.distribution_config)
    reference_dir = config.distribution_config.forms_data_dir / "email_references" / event_artifacts.local_event_key
    analyzer = FaceAnalyzer(
        config.distribution_config.yunet_model_path,
        config.distribution_config.sface_model_path,
        detector_config=YuNetConfig(),
    )
    runtime = LiveEventRuntime(
        form_id=form_id,
        cloud_event_folder=selected_cloud_event_folder,
        event_artifacts=event_artifacts,
        reference_dir=reference_dir,
        analyzer=analyzer,
    )
    status_reporter = LiveStatusReporter(config.status_file_path)

    iterations_count = 0
    copied_to_disk_count = 0
    next_event_poll_at = 0.0
    logger.info("Live event runner started.")
    logger.info("Live status heartbeat enabled.")

    try:
        while True:
            poll_event_photos = time.monotonic() >= next_event_poll_at
            status_reporter.write(
                state="polling_event_photos" if poll_event_photos else "polling_forms",
                iterations_count=iterations_count,
                runtime=runtime,
                last_iteration=None,
                seconds_until_event_poll=_seconds_until(next_event_poll_at),
            )
            iteration = run_live_event_once(
                disk_client,
                mail_client,
                access_grantor,
                runtime,
                config=config,
                poll_event_photos=poll_event_photos,
            )
            iterations_count += 1
            if iteration.plan_rebuilt:
                copied_to_disk_count = iteration.copied_to_disk_count
                logger.info("Live distribution plan rebuilt: {}", iteration.safe_summary())
            if poll_event_photos:
                next_event_poll_at = time.monotonic() + config.event_poll_seconds
            status_reporter.write(
                state="waiting",
                iterations_count=iterations_count,
                runtime=runtime,
                last_iteration=iteration,
                seconds_until_event_poll=_seconds_until(next_event_poll_at),
            )
            time.sleep(config.form_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Live event runner stopped by user.")
        status_reporter.write(
            state="stopped",
            iterations_count=iterations_count,
            runtime=runtime,
            last_iteration=None,
            seconds_until_event_poll=_seconds_until(next_event_poll_at),
        )

    result = LiveEventResult(
        iterations_count=iterations_count,
        participants_count=_runtime_participants_count(runtime),
        event_photos_count=len(runtime.event_photos),
        copied_to_disk_count=copied_to_disk_count,
        local_artifact_paths=(
            runtime.reference_dir,
            runtime.event_artifacts.local_event_photos_dir,
            runtime.event_artifacts.copy_plan_dir,
            config.status_file_path,
        ),
    )
    if config.cleanup_local:
        cleanup_live_local_artifacts(result)
        logger.info("Live local workflow artifacts removed.")
    return result


def run_live_event_once(
    disk_client: YandexDiskClient,
    mail_client: MailClient,
    access_grantor: YandexDiskUiAccessGrantor,
    runtime: LiveEventRuntime,
    *,
    config: LiveEventConfig,
    poll_event_photos: bool,
) -> LiveEventIterationResult:
    """Run one live mail/event-photo polling iteration.

    Args:
        disk_client: Yandex Disk client.
        mail_client: Mail client.
        access_grantor: Yandex Disk UI automation object that grants
            participant write access.
        runtime: Mutable live state for the current event.
        config: Live runner configuration.
        poll_event_photos: Whether this iteration should query the cloud event
            folder for new source photos.

    Returns:
        Iteration counters and whether the output plan was rebuilt.

    Side effects:
        May save reference attachments, grant folder access, download new
        event photos, write a copy-plan JSON, create output folders, and copy
        existing remote event photos.
    """

    new_answers = _collect_new_email_answers(mail_client, runtime)
    accepted_answers_count = _store_new_email_answers(runtime, new_answers)
    disk_forms_changed = _refresh_disk_forms_ingest(disk_client, runtime, config)

    email_forms_ingest = email_answers_to_forms_ingest_result(
        tuple(runtime.answers),
        reference_dir=runtime.reference_dir,
    )
    forms_ingest = _merge_forms_ingest_results(email_forms_ingest, runtime.disk_forms_ingest)
    access_grants_count, access_grant_failures_count = _grant_access_for_new_participants(
        mail_client,
        access_grantor,
        runtime,
        forms_ingest,
        config=config,
    )

    downloaded_count = 0
    if poll_event_photos:
        download_result = download_event_photos(
            disk_client,
            runtime.cloud_event_folder,
            runtime.event_artifacts.local_event_photos_dir,
            known_disk_paths=runtime.known_event_photo_paths,
        )
        runtime.known_event_photo_paths = set(download_result.known_disk_paths)
        runtime.event_photos = list(download_result.event_photos)
        downloaded_count = download_result.downloaded_count

    if not forms_ingest.participants or not runtime.event_photos:
        return LiveEventIterationResult(
            new_answers_count=accepted_answers_count,
            downloaded_event_photos_count=downloaded_count,
            access_grants_count=access_grants_count,
            access_grant_failures_count=access_grant_failures_count,
            planned_copies_count=0,
            copied_to_disk_count=0,
            plan_rebuilt=False,
        )

    if accepted_answers_count == 0 and downloaded_count == 0 and not disk_forms_changed:
        return LiveEventIterationResult(
            new_answers_count=0,
            downloaded_event_photos_count=0,
            access_grants_count=0,
            access_grant_failures_count=access_grant_failures_count,
            planned_copies_count=0,
            copied_to_disk_count=0,
            plan_rebuilt=False,
        )

    output_folders = build_distribution_output_folders(
        list(forms_ingest.participants),
        config.distribution_config.quarantine_folder_name,
    )
    analysis_result = runtime.analyzer.analyze_distribution(
        [
            ReferenceImageForAnalysis(
                participant_id=reference_image.participant_id,
                local_path=reference_image.local_path,
            )
            for reference_image in forms_ingest.reference_images
        ],
        [
            EventPhotoForAnalysis(
                id=event_photo.id,
                local_path=event_photo.local_path,
            )
            for event_photo in runtime.event_photos
        ],
        config.distribution_config.similarity_threshold,
    )
    copy_plan = build_distribution_copy_plan(
        event_photos=runtime.event_photos,
        face_matches=list(analysis_result.face_matches),
        output_folders=output_folders,
        event_folder=runtime.cloud_event_folder,
        copy_plan_path=runtime.event_artifacts.copy_plan_path,
    )
    apply_result = apply_distribution_plan(
        copy_plan.copy_plan,
        disk_client=disk_client,
        output_folders=output_folders,
        event_folder=runtime.cloud_event_folder,
    )
    return LiveEventIterationResult(
        new_answers_count=accepted_answers_count,
        downloaded_event_photos_count=downloaded_count,
        access_grants_count=access_grants_count,
        access_grant_failures_count=access_grant_failures_count,
        planned_copies_count=copy_plan.planned_copies_count,
        copied_to_disk_count=apply_result.copied_to_disk_count,
        plan_rebuilt=True,
    )


def _store_new_email_answers(runtime: LiveEventRuntime, new_answers: list[EmailAnswer]) -> int:
    """Store newly parsed email answers in the live runtime.

    Args:
        runtime: Mutable live event state.
        new_answers: Parsed email answers matching the current form id.

    Returns:
        Number of answers newly accepted into runtime state.

    Side effects:
        Appends answers to `runtime.answers` and records processed answer ids.
    """

    accepted_count = 0
    for answer in new_answers:
        answer_id = answer.metadata.answer_id
        if answer_id in runtime.processed_answer_ids:
            continue
        runtime.answers.append(answer)
        runtime.processed_answer_ids.add(answer_id)
        accepted_count += 1
    return accepted_count


def _refresh_disk_forms_ingest(
    disk_client: YandexDiskClient,
    runtime: LiveEventRuntime,
    config: LiveEventConfig,
) -> bool:
    """Import the optional Yandex Disk forms export when a new JSON appears.

    Args:
        disk_client: Yandex Disk client used to inspect and download exports.
        runtime: Mutable live event state.
        config: Live runner configuration containing forms artifact paths.

    Returns:
        `True` when a new JSON export was imported, otherwise `False`.

    Side effects:
        Downloads the newest JSON export and reference images when present.
        Missing forms folders and empty forms folders are treated as normal
        live states.
    """

    forms_folder = f"/Yandex.Forms/{runtime.form_id}"
    try:
        latest_json_disk_path = find_latest_json_export(disk_client, forms_folder)
    except DiskApiError as exc:
        if exc.status_code == 404:
            return False
        raise
    except FormsExportError as exc:
        if exc.safe_message() == NO_FORMS_JSON_SAFE_MESSAGE:
            return False
        raise

    if latest_json_disk_path == runtime.last_forms_json_disk_path:
        return False

    try:
        runtime.disk_forms_ingest = ingest_forms_export(
            disk_client,
            runtime.form_id,
            data_dir=config.distribution_config.forms_data_dir,
        )
    except FormsExportError as exc:
        logger.warning("Disk forms export skipped: {}", exc.safe_message())
        runtime.last_forms_json_disk_path = latest_json_disk_path
        return False

    runtime.last_forms_json_disk_path = latest_json_disk_path
    return True


def _merge_forms_ingest_results(
    email_forms_ingest: FormsIngestResult,
    disk_forms_ingest: FormsIngestResult | None,
) -> FormsIngestResult:
    """Merge email and JSON forms imports into one downstream contract.

    Args:
        email_forms_ingest: Current forms state built from parsed emails.
        disk_forms_ingest: Optional latest forms state imported from Yandex Disk
            JSON export.

    Returns:
        One `FormsIngestResult` with participants kept as separate people and
        re-numbered participant/reference ids.
    """

    source_participants: list[ImportedParticipant] = []
    for source in (email_forms_ingest, disk_forms_ingest):
        if source is None:
            continue
        source_participants.extend(source.participants)

    merged_participants: list[ImportedParticipant] = []
    reference_id = 1
    for participant in source_participants:
        participant_id = len(merged_participants) + 1
        reference_images: list[ImportedReferenceImage] = []
        for reference_image in participant.reference_images:
            reference_images.append(
                ImportedReferenceImage(
                    id=reference_id,
                    participant_id=participant_id,
                    disk_path=reference_image.disk_path,
                    local_path=reference_image.local_path,
                )
            )
            reference_id += 1
        merged_participants.append(
            ImportedParticipant(
                id=participant_id,
                email=participant.email,
                name=participant.name,
                policy_accepted=participant.policy_accepted,
                reference_images=tuple(reference_images),
            )
        )

    return FormsIngestResult(
        json_disk_path=disk_forms_ingest.json_disk_path if disk_forms_ingest is not None else "",
        local_json_path=disk_forms_ingest.local_json_path if disk_forms_ingest is not None else Path(),
        participants=tuple(merged_participants),
        participants_count=len(merged_participants),
        reference_images_count=sum(len(participant.reference_images) for participant in merged_participants),
    )


def _runtime_participants_count(runtime: LiveEventRuntime) -> int:
    """Return current unique participant count across live form sources.

    Args:
        runtime: Current live event state.

    Returns:
        Number of participant form answers seen from email answers and the
        optional JSON forms export.
    """

    count = len(runtime.answers)
    if runtime.disk_forms_ingest is not None:
        count += len(runtime.disk_forms_ingest.participants)
    return count


def _grant_access_for_new_participants(
    mail_client: MailClient,
    access_grantor: YandexDiskUiAccessGrantor,
    runtime: LiveEventRuntime,
    forms_ingest: FormsIngestResult,
    *,
    config: LiveEventConfig,
) -> tuple[int, int]:
    """Grant event-folder access for participants not handled before.

    Args:
        mail_client: SMTP-capable mail client.
        access_grantor: Yandex Disk UI automation object.
        runtime: Mutable live event state.
        forms_ingest: Merged participant/reference state from all form sources.
        config: Live runner configuration containing access timeout.

    Returns:
        Tuple of successful access grants and failed access grants.

    Side effects:
        Drives browser UI access automation and sends participant/admin emails.
    """

    access_grants_count = 0
    access_grant_failures_count = 0
    seen_emails_this_iteration: set[str] = set()
    for participant in forms_ingest.participants:
        email_key = participant.email.strip().lower()
        if not participant.policy_accepted:
            continue
        if email_key in seen_emails_this_iteration:
            _send_duplicate_access_request_alert(
                mail_client,
                runtime,
                participant.email,
                source_id=f"participant:{participant.id}",
            )
            continue
        seen_emails_this_iteration.add(email_key)
        if email_key in runtime.access_handled_participant_emails:
            continue
        try:
            _grant_write_access_with_timeout(
                access_grantor,
                runtime.cloud_event_folder,
                participant.email,
                timeout_seconds=config.access_grant_timeout_seconds,
            )
        except YandexDiskUiError as exc:
            access_grant_failures_count += 1
            logger.warning(
                "Participant access grant failed: {}",
                exc.safe_message(),
            )
            _send_manual_access_alert(
                mail_client,
                runtime,
                participant.email,
                source_id=f"participant:{participant.id}",
                exc=exc,
                event_folder_url=access_grantor.folder_url(runtime.cloud_event_folder),
            )
        else:
            access_grants_count += 1
            _send_participant_access_notification(
                mail_client,
                participant.email,
                event_folder_url=access_grantor.folder_url(runtime.cloud_event_folder),
            )
        runtime.access_handled_participant_emails.add(email_key)

    return access_grants_count, access_grant_failures_count


def cleanup_live_local_artifacts(result: LiveEventResult) -> None:
    """Remove local artifacts produced by the live event workflow.

    Args:
        result: Live runner result containing artifact paths.

    Raises:
        ValueError: If an artifact path is outside the project `data` folder.

    Side effects:
        Deletes local live-run artifact files or directories.
    """

    cleanup_local_artifacts(
        DistributionResult(
            counts=DistributionCounters(
                participants_count=result.participants_count,
                reference_embeddings_count=0,
                event_photos_count=result.event_photos_count,
                event_faces_count=0,
                face_matches_count=0,
                planned_copies_count=0,
                copied_to_disk_count=result.copied_to_disk_count,
                quarantined_photos_count=0,
            ),
            artifacts=DistributionArtifacts(
                copy_plan_path=Path(),
                local_artifact_paths=result.local_artifact_paths,
            ),
        )
    )


def _collect_new_email_answers(mail_client: MailClient, runtime: LiveEventRuntime) -> list[EmailAnswer]:
    """Fetch mail messages and parse only new answers for this form id.

    A temporary IMAP failure is treated as a skipped form-source poll, because
    the live runner must keep processing Disk form exports and event photos.
    """

    new_answers: list[EmailAnswer] = []
    try:
        messages = mail_client.fetch_messages(folder=mail_client.config.forms_folder)
    except MailClientError as exc:
        logger.warning("Mail form-source poll failed: {}", exc.safe_message())
        return new_answers

    for message in messages:
        try:
            metadata = parse_email_answer_subject(message.subject)
        except FormsExportError:
            continue
        if metadata.form_id != runtime.form_id:
            continue
        if metadata.answer_id in runtime.processed_answer_ids:
            continue
        answer = parse_email_answer(
            subject=message.subject,
            body=message.body,
            attachments=_form_attachments(message),
        )
        new_answers.append(answer)
    return new_answers


def _grant_write_access_with_timeout(
    access_grantor: YandexDiskUiAccessGrantor,
    folder_path: str,
    email: str,
    *,
    timeout_seconds: float,
) -> None:
    """Grant write access while enforcing the live workflow timeout.

    Args:
        access_grantor: UI automation object.
        folder_path: Canonical Yandex Disk event folder path.
        email: Participant email from the accepted form answer.
        timeout_seconds: Maximum seconds to wait for this grant attempt.

    Raises:
        YandexDiskUiError: If the UI grant fails or does not finish before the
            timeout.

    Side effects:
        Starts a daemon thread that drives browser UI automation.
    """

    if timeout_seconds <= 0:
        raise ValueError("Access grant timeout must be positive.")

    result_queue: Queue[Exception | None] = Queue(maxsize=1)

    def run_grant() -> None:
        try:
            access_grantor.grant_write_access(folder_path, email)
        except Exception as exc:
            result_queue.put(exc)
            return
        result_queue.put(None)

    thread = Thread(target=run_grant, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise YandexDiskUiError(
            "Yandex Disk UI access grant did not finish before timeout.",
            safe_message="Yandex Disk UI access grant did not finish before timeout.",
        )

    try:
        result = result_queue.get_nowait()
    except Empty as exc:
        raise YandexDiskUiError(
            "Yandex Disk UI access grant finished without a result.",
            safe_message="Yandex Disk UI access grant finished without a result.",
        ) from exc
    if result is None:
        return
    if isinstance(result, YandexDiskUiError):
        raise result
    raise YandexDiskUiError(
        "Yandex Disk UI access grant failed.",
        safe_message="Yandex Disk UI access grant failed.",
    ) from result


def _send_manual_access_alert(
    mail_client: MailClient,
    runtime: LiveEventRuntime,
    participant_email: str,
    source_id: str,
    exc: YandexDiskUiError,
    *,
    event_folder_url: str,
) -> None:
    """Notify the operator that access must be granted manually.

    Args:
        mail_client: SMTP-capable mail client.
        runtime: Current live event runtime state.
        participant_email: Participant email whose access failed.
        source_id: Forms source id for operator diagnostics.
        exc: Safe UI automation error.
        event_folder_url: Browser URL that opens the event folder for manual
            access setup.

    Side effects:
        Sends one plain-text operator alert per source id.
    """

    if source_id in runtime.access_grant_alerted_source_ids:
        return
    admin_email = getattr(mail_client.config, "admin_email", "")
    if not admin_email:
        logger.warning("Письмо оператору о ручной выдаче доступа пропущено: email администратора не настроен.")
        runtime.access_grant_alerted_source_ids.add(source_id)
        return

    subject = MANUAL_ACCESS_REQUIRED_SUBJECT
    body = (
        "Автоматическая выдача доступа на запись к папке события в Яндекс Диске "
        "не удалась или заняла слишком много времени.\n\n"
        f"ID формы: {runtime.form_id}\n"
        f"ID источника: {source_id}\n"
        f"Ссылка на папку события: {event_folder_url}\n"
        f"Email участника: {participant_email}\n"
        f"Безопасное описание ошибки: {exc.safe_message()}\n\n"
        "Пожалуйста, выдайте доступ на редактирование вручную в Яндекс Диске."
    )
    try:
        mail_client.send_message(
            to_email=admin_email,
            subject=subject,
            body=body,
        )
        runtime.access_grant_alerted_source_ids.add(source_id)
        logger.warning("Письмо оператору о ручной выдаче доступа отправлено.")
    except Exception:
        logger.warning("Не удалось отправить письмо оператору о ручной выдаче доступа.")


def _send_duplicate_access_request_alert(
    mail_client: MailClient,
    runtime: LiveEventRuntime,
    participant_email: str,
    *,
    source_id: str,
) -> None:
    """Notify the operator about a duplicate access request for one email.

    Args:
        mail_client: SMTP-capable mail client.
        runtime: Current live event runtime state.
        participant_email: Duplicate participant email. It is sent only inside
            the private operator email body.
        source_id: Forms source id for deduplicating this alert.

    Side effects:
        Sends one plain-text operator alert per source id.
    """

    if source_id in runtime.duplicate_access_alerted_source_ids:
        return
    admin_email = getattr(mail_client.config, "admin_email", "")
    if not admin_email:
        logger.warning("Письмо оператору о повторном email пропущено: email администратора не настроен.")
        runtime.duplicate_access_alerted_source_ids.add(source_id)
        return

    subject = DUPLICATE_PARTICIPANT_EMAIL_SUBJECT
    body = (
        "В ответе формы указан email, для которого уже была попытка выдачи доступа.\n\n"
        f"ID формы: {runtime.form_id}\n"
        f"ID источника: {source_id}\n"
        f"Email участника: {participant_email}\n\n"
        "Повторная выдача доступа через UI Яндекс Диска для этого email пропущена. "
        "Учитывайте эту заявку как отдельного участника только для распознавания и референсов."
    )
    try:
        mail_client.send_message(
            to_email=admin_email,
            subject=subject,
            body=body,
        )
        runtime.duplicate_access_alerted_source_ids.add(source_id)
        logger.warning("Письмо оператору о повторном email отправлено.")
    except Exception:
        logger.warning("Не удалось отправить письмо оператору о повторном email.")


def _send_participant_access_notification(
    mail_client: MailClient,
    participant_email: str,
    *,
    event_folder_url: str,
) -> None:
    """Notify a participant that event folder write access was granted.

    Args:
        mail_client: SMTP-capable mail client.
        participant_email: Participant email whose access was granted.
        event_folder_url: Browser URL that opens the shared event folder.

    Side effects:
        Sends one plain-text participant notification email.
    """

    subject = PARTICIPANT_ACCESS_READY_SUBJECT
    body = (
        "Вам открыт доступ на запись к общей папке события.\n\n"
        f"Ссылка на папку события: {event_folder_url}\n\n"
        "Теперь вы можете открыть ссылку и загрузить фотографии события в общую папку."
    )
    try:
        mail_client.send_message(
            to_email=participant_email,
            subject=subject,
            body=body,
        )
        logger.info("Письмо участнику о доступе отправлено.")
    except Exception:
        logger.warning("Не удалось отправить письмо участнику о доступе.")


def _form_attachments(message: MailMessage) -> tuple[EmailAttachment, ...]:
    """Convert transport attachments to forms-parser attachments."""

    return tuple(
        EmailAttachment(
            filename=attachment.filename,
            content=attachment.content,
            content_type=attachment.content_type,
        )
        for attachment in message.attachments
    )


@dataclass(frozen=True)
class LiveStatusReporter:
    """Write the current live runner heartbeat into one local JSON file.

    Args:
        status_file_path: Local private JSON file that is overwritten
            atomically on every status update.

    Side effects:
        Creates the parent directory and replaces the status JSON file.
    """

    status_file_path: Path

    def write(
        self,
        *,
        state: str,
        iterations_count: int,
        runtime: LiveEventRuntime,
        last_iteration: LiveEventIterationResult | None,
        seconds_until_event_poll: int,
    ) -> None:
        """Persist one privacy-safe live runner heartbeat.

        Args:
            state: Short current runner state, for example `waiting`.
            iterations_count: Number of completed polling loops.
            runtime: Current live event state used only for public counters.
            last_iteration: Most recent iteration counters when available.
            seconds_until_event_poll: Approximate seconds before the next Disk
                event-photo poll.

        Side effects:
            Overwrites `status_file_path` via a temporary sibling file.
        """

        payload: dict[str, object] = {
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "state": state,
            "iterations_count": iterations_count,
            "participants_count": _runtime_participants_count(runtime),
            "event_photos_count": len(runtime.event_photos),
            "processed_answers_count": len(runtime.processed_answer_ids),
            "next_event_photo_poll_in_seconds": seconds_until_event_poll,
        }
        if last_iteration is not None:
            payload["last_iteration"] = last_iteration.safe_summary()

        self.status_file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.status_file_path.with_suffix(f"{self.status_file_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.status_file_path)


def _seconds_until(monotonic_deadline: float) -> int:
    """Return approximate whole seconds until a monotonic deadline.

    Args:
        monotonic_deadline: Deadline expressed in `time.monotonic()` seconds.

    Returns:
        Non-negative integer seconds until the deadline.
    """

    return max(0, int(monotonic_deadline - time.monotonic()))
