"""Parser for manually exported Yandex Forms JSON answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from utils import redact_personal_data

from .schema import FORM_FIELD_ORDER, MAX_REFERENCE_IMAGES, TRUTHY_POLICY_VALUES


class FormsExportError(ValueError):
    """Raised when the local forms export is missing required data."""

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        """Create a forms-export error with an optional log-safe message."""

        super().__init__(message)
        self._safe_message = safe_message

    def safe_message(self) -> str:
        """Return a message safe for logs and console diagnostics."""

        if self._safe_message is not None:
            return self._safe_message
        return redact_personal_data(self)


@dataclass(frozen=True)
class Participant:
    """A participant imported from the local Yandex Forms JSON export.

    Attributes:
        policy_accepted: Whether the participant accepted the consent policy.
        name: Display name from the form, later used for output folder naming.
        email: Yandex email from the form. It is trusted as form-validated and
            should not be printed in diagnostics.
        image_disk_paths: One to three Yandex Disk paths for reference photos.
    """

    policy_accepted: bool
    name: str
    email: str
    image_disk_paths: tuple[str, ...]


def load_participants(json_path: str | Path) -> list[Participant]:
    """Load participants from a manually exported Yandex Forms JSON file.

    Args:
        json_path: Local path to the downloaded JSON export.

    Returns:
        Parsed participants in export order.

    Raises:
        FormsExportError: If the file is missing, invalid, empty, or does not
            match the expected positional form shape.
    """

    path = Path(json_path)
    if not path.is_file():
        raise FormsExportError(
            f"Forms JSON export does not exist: {path}",
            safe_message="Forms JSON export does not exist.",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise FormsExportError(
            f"Forms JSON export is invalid: {path}",
            safe_message="Forms JSON export is invalid.",
        ) from exc

    if not isinstance(data, list):
        raise FormsExportError("Forms JSON export must contain a list of answers.")

    participants = [
        _parse_answer(answer, answer_number=index)
        for index, answer in enumerate(data, start=1)
    ]
    if not participants:
        raise FormsExportError(
            f"Forms JSON export is empty: {path}",
            safe_message="Forms JSON export is empty.",
        )

    return participants


def _parse_answer(answer: object, *, answer_number: int) -> Participant:
    """Parse one exported answer using positional field order."""

    values = _extract_answer_values(answer)
    if len(values) < len(FORM_FIELD_ORDER):
        raise FormsExportError(
            f"Answer {answer_number} has fewer fields than expected: "
            f"{len(FORM_FIELD_ORDER)}"
        )

    field_values = dict(zip(FORM_FIELD_ORDER, values[-len(FORM_FIELD_ORDER) :]))
    policy = _required_value(field_values["policy"], "policy", answer_number)
    name = _required_value(field_values["name"], "name", answer_number)
    email = _required_value(field_values["email"], "email", answer_number)
    images = _parse_image_disk_paths(
        _required_value(field_values["images"], "images", answer_number),
        answer_number,
    )

    return Participant(
        policy_accepted=_parse_policy(policy),
        name=name,
        email=email,
        image_disk_paths=images,
    )


def _extract_answer_values(answer: object) -> list[str]:
    """Extract raw answer values while ignoring mutable question text."""

    if not isinstance(answer, list):
        raise FormsExportError("Each answer must be a list of question/value pairs.")

    values: list[str] = []
    for item in answer:
        pair = item.get("value") if isinstance(item, dict) else item
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise FormsExportError("Answer item must contain a question/value pair.")
        values.append(str(pair[1]).strip())
    return values


def _required_value(value: str, field: str, answer_number: int) -> str:
    """Return a stripped required value or raise a forms export error."""

    stripped = value.strip()
    if not stripped:
        raise FormsExportError(f"Answer {answer_number} is missing required field: {field}")
    return stripped


def _parse_policy(value: str) -> bool:
    """Convert the policy answer into a boolean acceptance flag."""

    return value.strip().lower() in TRUTHY_POLICY_VALUES


def _parse_image_disk_paths(value: str, answer_number: int) -> tuple[str, ...]:
    """Parse one to three reference image paths from the form answer."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    for separator in ("\n", ";", "|"):
        normalized = normalized.replace(separator, ",")

    paths = tuple(
        _normalize_disk_path(item.strip())
        for item in normalized.split(",")
        if item.strip()
    )
    if not paths:
        raise FormsExportError(f"Answer {answer_number} has no image files.")
    if len(paths) > MAX_REFERENCE_IMAGES:
        raise FormsExportError(
            f"Answer {answer_number} has more than {MAX_REFERENCE_IMAGES} image files."
        )
    return paths


def _normalize_disk_path(value: str) -> str:
    """Normalize Yandex Disk UI links, `disk:` paths, and absolute disk paths."""

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("disk.yandex.ru"):
        query = parse_qs(parsed.query)
        id_dialog = query.get("idDialog", [""])[0]
        if id_dialog:
            return _path_from_disk_ui_path(unquote(id_dialog))
        return _path_from_disk_ui_path(unquote(parsed.path))

    if parsed.scheme in {"http", "https"} and parsed.netloc == "forms.yandex.ru":
        query = parse_qs(parsed.query)
        uploaded_file_path = query.get("path", [""])[0]
        if uploaded_file_path:
            return _path_from_forms_upload_path(unquote(uploaded_file_path))

    if value.startswith("disk:"):
        return value.removeprefix("disk:")
    if value.startswith("/"):
        return value

    raise FormsExportError("Unsupported image path format in images field.")


def _path_from_disk_ui_path(value: str) -> str:
    """Extract an absolute disk path from a Yandex Disk UI path fragment."""

    if value.startswith("/client/disk/"):
        return "/" + value.removeprefix("/client/disk/")
    if value.startswith("/disk/"):
        return "/" + value.removeprefix("/disk/")
    if value.startswith("/"):
        return value
    raise FormsExportError("Unsupported Yandex Disk UI path in images field.")


def _path_from_forms_upload_path(value: str) -> str:
    """Convert a Yandex Forms uploaded-file URL path into a Disk file path."""

    parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) >= 3:
        form_id = parts[-2]
        filename = parts[-1]
        return f"/Yandex.Forms/{form_id}/{filename}"
    raise FormsExportError("Unsupported Yandex Forms file path in images field.")
