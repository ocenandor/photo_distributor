"""Parse Yandex Forms answer emails into the shared forms contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import FormsIngestResult, ImportedParticipant, ImportedReferenceImage
from .participants import FormsExportError
from .schema import MAX_REFERENCE_IMAGES, TRUTHY_POLICY_VALUES


SUBJECT_SEPARATOR = "__"
SUBJECT_PREFIX = "\u041e\u0442\u0432\u0435\u0442_\u043d\u0430_\u0444\u043e\u0440\u043c\u0443"


@dataclass(frozen=True)
class EmailAttachment:
    """Email attachment supplied to the forms email parser.

    Attributes:
        filename: Original attachment file name from the email.
        content: Raw attachment bytes.
        content_type: MIME content type, used only for diagnostics/future
            filtering. File extension filtering is intentionally not done here.
    """

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class EmailAnswerMetadata:
    """Metadata parsed from a Yandex Forms answer email subject.

    Attributes:
        form_title: Human-readable form title from the subject.
        form_id: Yandex Forms id parsed from the subject.
        answer_id: Yandex Forms answer id parsed from the subject.
    """

    form_title: str
    form_id: str
    answer_id: str


@dataclass(frozen=True)
class EmailAnswer:
    """One parsed Yandex Forms email answer before contract normalization.

    Attributes:
        metadata: Form and answer ids parsed from the email subject.
        policy_accepted: Whether the participant accepted the policy.
        name: Display name from the email body.
        email: Participant email from the email body.
        attachments: Reference image attachments from the message.
    """

    metadata: EmailAnswerMetadata
    policy_accepted: bool
    name: str
    email: str
    attachments: tuple[EmailAttachment, ...]


def parse_email_answer(
    *,
    subject: str,
    body: str,
    attachments: tuple[EmailAttachment, ...],
) -> EmailAnswer:
    """Parse one Yandex Forms answer email.

    Args:
        subject: Email subject in the expected Yandex Forms format.
        body: Plain text body with `Accept`, `Name`, and `Email` fields.
        attachments: Reference image attachments from the email.

    Returns:
        Parsed email answer.

    Raises:
        FormsExportError: If required subject/body fields are absent or the
            attachment count is outside the supported range.
    """

    metadata = parse_email_answer_subject(subject)
    fields = _parse_body_fields(body)
    policy = _required_body_value(fields, "accept")
    name = _required_body_value(fields, "name")
    email = _required_body_value(fields, "email")
    if not attachments:
        raise FormsExportError("Email answer does not contain reference image attachments.")
    if len(attachments) > MAX_REFERENCE_IMAGES:
        raise FormsExportError(
            f"Email answer contains more than {MAX_REFERENCE_IMAGES} reference attachments."
        )
    return EmailAnswer(
        metadata=metadata,
        policy_accepted=policy.strip().lower() in TRUTHY_POLICY_VALUES,
        name=name,
        email=email,
        attachments=attachments,
    )


def parse_email_answer_subject(subject: str) -> EmailAnswerMetadata:
    """Parse the Yandex Forms answer subject with form and answer ids."""

    parts = subject.strip().split(SUBJECT_SEPARATOR)
    if len(parts) != 4 or parts[0] != SUBJECT_PREFIX:
        raise FormsExportError("Email answer subject has an unsupported format.")
    form_title, form_id, answer_id = (part.strip() for part in parts[1:])
    if not form_title or not form_id or not answer_id:
        raise FormsExportError("Email answer subject is missing required ids.")
    return EmailAnswerMetadata(form_title=form_title, form_id=form_id, answer_id=answer_id)


def email_answers_to_forms_ingest_result(
    answers: tuple[EmailAnswer, ...],
    *,
    reference_dir: Path,
) -> FormsIngestResult:
    """Normalize parsed email answers into the shared forms ingest contract.

    Args:
        answers: Parsed email answers in processing order.
        reference_dir: Local directory where reference attachments are saved.

    Returns:
        `FormsIngestResult` with the same participant/reference shape as the
        JSON importer.

    Side effects:
        Writes reference attachments under `reference_dir`.
    """

    reference_dir.mkdir(parents=True, exist_ok=True)
    participants: list[ImportedParticipant] = []
    reference_id = 1

    for participant_id, answer in enumerate(answers, start=1):
        participant_dir = reference_dir / f"participant_{participant_id:03d}"
        participant_dir.mkdir(parents=True, exist_ok=True)
        reference_images: list[ImportedReferenceImage] = []
        for attachment_index, attachment in enumerate(answer.attachments, start=1):
            local_path = participant_dir / _attachment_local_name(attachment.filename, attachment_index)
            local_path.write_bytes(attachment.content)
            reference_images.append(
                ImportedReferenceImage(
                    id=reference_id,
                    participant_id=participant_id,
                    disk_path="",
                    local_path=local_path,
                )
            )
            reference_id += 1
        participants.append(
            ImportedParticipant(
                id=participant_id,
                email=answer.email,
                name=answer.name,
                policy_accepted=answer.policy_accepted,
                reference_images=tuple(reference_images),
            )
        )

    return FormsIngestResult(
        json_disk_path="",
        local_json_path=Path(),
        participants=tuple(participants),
        participants_count=len(participants),
        reference_images_count=sum(len(participant.reference_images) for participant in participants),
    )


def _parse_body_fields(body: str) -> dict[str, str]:
    """Return normalized body fields keyed by lowercase field name."""

    fields: dict[str, str] = {}
    for raw_line in body.splitlines():
        field, separator, value = raw_line.partition(":")
        if not separator:
            continue
        key = field.strip().lower()
        if key in {"accept", "name", "email"}:
            fields[key] = value.strip()
    return fields


def _required_body_value(fields: dict[str, str], key: str) -> str:
    """Return one required body field or raise a forms export error."""

    value = fields.get(key, "").strip()
    if not value:
        raise FormsExportError(f"Email answer is missing required field: {key}")
    return value


def _attachment_local_name(filename: str, index: int) -> str:
    """Return a stable local file name for one email attachment."""

    suffix = Path(filename).suffix
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).stem).strip("._")
    if not safe_stem:
        safe_stem = f"reference_{index:02d}"
    if not suffix:
        return f"{index:02d}_{safe_stem}"
    return f"{index:02d}_{safe_stem}{suffix}"
