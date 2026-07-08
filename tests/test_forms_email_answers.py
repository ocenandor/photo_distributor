"""Tests for Yandex Forms answer email parsing."""

from __future__ import annotations

import json
from pathlib import Path

from forms_export import (
    EmailAttachment,
    FormsIngestResult,
    email_answers_to_forms_ingest_result,
    ingest_forms_export,
    parse_email_answer,
    parse_email_answer_subject,
)


FORM_ID = "test_form"
ANSWER_ID = "answer_001"
SUBJECT = (
    "\u041e\u0442\u0432\u0435\u0442_\u043d\u0430_\u0444\u043e\u0440\u043c\u0443"
    f"__Photo event__{FORM_ID}__{ANSWER_ID}"
)


def test_parse_email_answer_subject_returns_form_and_answer_ids() -> None:
    metadata = parse_email_answer_subject(SUBJECT)

    assert metadata.form_title == "Photo event"
    assert metadata.form_id == FORM_ID
    assert metadata.answer_id == ANSWER_ID


def test_parse_email_answer_normalizes_body_and_attachments() -> None:
    answer = parse_email_answer(
        subject=SUBJECT,
        body=(
            "Accept: \u0414\u0430\n"
            "Name: Test Participant\n"
            "Email: participant@example.com\n"
        ),
        attachments=(
            EmailAttachment(
                filename="reference.jpg",
                content=b"image-bytes",
                content_type="image/jpeg",
            ),
        ),
    )

    assert answer.metadata.form_id == FORM_ID
    assert answer.metadata.answer_id == ANSWER_ID
    assert answer.policy_accepted is True
    assert answer.name == "Test Participant"
    assert answer.email == "participant@example.com"
    assert answer.attachments[0].filename == "reference.jpg"


def test_email_answers_to_forms_ingest_result_matches_shared_contract(tmp_path: Path) -> None:
    answer = parse_email_answer(
        subject=SUBJECT,
        body=(
            "Accept: \u0414\u0430\n"
            "Name: Test Participant\n"
            "Email: participant@example.com\n"
        ),
        attachments=(
            EmailAttachment(filename="reference.jpg", content=b"image-bytes", content_type="image/jpeg"),
        ),
    )

    result = email_answers_to_forms_ingest_result(
        (answer,),
        reference_dir=tmp_path / "references",
    )

    assert _fake_downstream(result) == {
        "participants_count": 1,
        "reference_images_count": 1,
    }
    assert result.participants[0].id == 1
    assert result.participants[0].email == "participant@example.com"
    assert result.participants[0].name == "Test Participant"
    assert result.participants[0].policy_accepted is True
    assert result.participants[0].reference_images[0].participant_id == 1
    assert result.participants[0].reference_images[0].local_path.read_bytes() == b"image-bytes"


def test_json_and_email_importers_return_same_downstream_shape(tmp_path: Path) -> None:
    json_client = _FakeJsonDiskClient()
    json_result = ingest_forms_export(json_client, FORM_ID, data_dir=tmp_path / "json_forms")
    email_result = email_answers_to_forms_ingest_result(
        (
            parse_email_answer(
                subject=SUBJECT,
                body=(
                    "Accept: \u0414\u0430\n"
                    "Name: Test Participant\n"
                    "Email: participant@example.com\n"
                ),
                attachments=(
                    EmailAttachment(filename="reference.jpg", content=b"image-bytes", content_type="image/jpeg"),
                ),
            ),
        ),
        reference_dir=tmp_path / "email_references",
    )

    assert _fake_downstream(json_result) == _fake_downstream(email_result)


def _fake_downstream(forms_ingest: FormsIngestResult) -> dict[str, int]:
    """Use only the shared forms ingest contract expected by downstream code."""

    assert forms_ingest.participants
    assert forms_ingest.reference_images
    return {
        "participants_count": forms_ingest.participants_count,
        "reference_images_count": forms_ingest.reference_images_count,
    }


class _FakeJsonDiskClient:
    """Fake Yandex Disk client that serves one JSON export and reference file."""

    def list_files(self, path: str) -> list[dict[str, object]]:
        assert path == f"/Yandex.Forms/{FORM_ID}"
        return [
            {
                "type": "file",
                "name": "forms-export.json",
                "path": f"disk:/Yandex.Forms/{FORM_ID}/forms-export.json",
                "created": "2026-06-28T18:38:40+03:00",
            }
        ]

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if disk_path.endswith("forms-export.json"):
            local_path.write_text(_forms_export_json(), encoding="utf-8")
        else:
            local_path.write_bytes(b"image-bytes")
        return local_path


def _forms_export_json() -> str:
    """Return one fake JSON export row in the positional forms contract."""

    return json.dumps(
        [
            [
                ["ID", ANSWER_ID],
                ["Created", "2026-06-28 18:38:40"],
                ["Policy", "\u0414\u0430"],
                ["Display name", "Test Participant"],
                ["Email", "participant@example.com"],
                ["Reference images", f"/Yandex.Forms/{FORM_ID}/Files/reference.jpg"],
            ]
        ]
    )
