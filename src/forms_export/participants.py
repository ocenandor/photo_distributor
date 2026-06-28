"""Parser for manually exported Yandex Forms JSON answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .schema import FORM_FIELD_ORDER, MAX_REFERENCE_IMAGES, TRUTHY_POLICY_VALUES


class FormsExportError(ValueError):
    """Raised when the local forms export is missing required data."""


@dataclass(frozen=True)
class Participant:
    """A participant imported from the local Yandex Forms JSON export."""

    policy_accepted: bool
    name: str
    email: str
    image_disk_paths: tuple[str, ...]


def load_participants(json_path: str | Path) -> list[Participant]:
    """Load participants from a manually exported Yandex Forms JSON file."""

    path = Path(json_path)
    if not path.is_file():
        raise FormsExportError(f"Forms JSON export does not exist: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise FormsExportError(f"Forms JSON export is invalid: {path}") from exc

    if not isinstance(data, list):
        raise FormsExportError("Forms JSON export must contain a list of answers.")

    participants = [
        _parse_answer(answer, answer_number=index)
        for index, answer in enumerate(data, start=1)
    ]
    if not participants:
        raise FormsExportError(f"Forms JSON export is empty: {path}")

    _validate_unique_emails(participants)
    return participants


def _parse_answer(answer: object, *, answer_number: int) -> Participant:
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
    stripped = value.strip()
    if not stripped:
        raise FormsExportError(f"Answer {answer_number} is missing required field: {field}")
    return stripped


def _parse_policy(value: str) -> bool:
    return value.strip().lower() in TRUTHY_POLICY_VALUES


def _parse_image_disk_paths(value: str, answer_number: int) -> tuple[str, ...]:
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
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("disk.yandex.ru"):
        query = parse_qs(parsed.query)
        id_dialog = query.get("idDialog", [""])[0]
        if id_dialog:
            return _path_from_disk_ui_path(unquote(id_dialog))
        return _path_from_disk_ui_path(unquote(parsed.path))

    if value.startswith("disk:"):
        return value.removeprefix("disk:")
    if value.startswith("/"):
        return value

    raise FormsExportError(f"Unsupported image path format: {value}")


def _path_from_disk_ui_path(value: str) -> str:
    if value.startswith("/client/disk/"):
        return "/" + value.removeprefix("/client/disk/")
    if value.startswith("/disk/"):
        return "/" + value.removeprefix("/disk/")
    if value.startswith("/"):
        return value
    raise FormsExportError(f"Unsupported Yandex Disk UI path: {value}")


def _validate_unique_emails(participants: list[Participant]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for participant in participants:
        if participant.email in seen:
            duplicates.add(participant.email)
        seen.add(participant.email)

    if duplicates:
        duplicate_text = ", ".join(sorted(duplicates))
        raise FormsExportError(f"Duplicate email values: {duplicate_text}")
