"""Tests for manually exported Yandex Forms JSON answers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from forms_export import FormsExportError, find_latest_json_export, ingest_forms_export, load_participants
from yandex_disk import DiskApiError


TEST_FORM_ID = "test_form"
TEST_FORMS_FOLDER = f"/Yandex.Forms/{TEST_FORM_ID}"
EXPECTED_NAME = "Example Participant"
EXPECTED_EMAIL = "participant@example.com"
EXPECTED_IMAGE_PATH = "/Yandex.Forms/test_form/Files/reference.jpg"
EXPECTED_FORMS_UPLOAD_IMAGE_PATH = "/Yandex.Forms/test_form/reference.jpg"
EXPECTED_IMAGE_URL = (
    "https://disk.yandex.ru/client/disk/Yandex.Forms/test_form/Files"
    "?idApp=client&dialog=slider"
    "&idDialog=%2Fdisk%2FYandex.Forms%2Ftest_form%2FFiles%2Freference.jpg"
)
EXPECTED_FORMS_UPLOAD_URL = (
    "https://forms.yandex.ru/u/files"
    "?path=%2F558417971%2Ftest_form%2Freference.jpg"
)


def test_load_participants_parses_expected_fields_from_json(tmp_path: Path) -> None:
    json_path = tmp_path / "forms-export.json"
    json_path.write_text(
        json.dumps(
            [
                [
                    ["ID", "answer-1"],
                    ["Created", "2026-06-28 18:38:40"],
                    ["Policy", "\u0414\u0430"],
                    ["Display name", EXPECTED_NAME],
                    ["Email", EXPECTED_EMAIL],
                    ["Reference images", EXPECTED_IMAGE_URL],
                ]
            ]
        ),
        encoding="utf-8",
    )

    participants = load_participants(json_path)

    assert len(participants) == 1
    assert participants[0].name == EXPECTED_NAME
    assert participants[0].email == EXPECTED_EMAIL
    assert participants[0].image_disk_paths == (EXPECTED_IMAGE_PATH,)


def test_load_participants_parses_forms_upload_file_link(tmp_path: Path) -> None:
    json_path = tmp_path / "forms-export.json"
    json_path.write_text(
        json.dumps(
            [
                [
                    ["ID", "answer-1"],
                    ["Created", "2026-06-28 18:38:40"],
                    ["Policy", "\u0414\u0430"],
                    ["Display name", EXPECTED_NAME],
                    ["Email", EXPECTED_EMAIL],
                    ["Reference images", EXPECTED_FORMS_UPLOAD_URL],
                ]
            ]
        ),
        encoding="utf-8",
    )

    participants = load_participants(json_path)

    assert participants[0].image_disk_paths == (EXPECTED_FORMS_UPLOAD_IMAGE_PATH,)


def test_load_participants_allows_duplicate_email_values(tmp_path: Path) -> None:
    json_path = tmp_path / "forms-export.json"
    json_path.write_text(
        json.dumps(
            [
                [
                    ["ID", "answer-1"],
                    ["Created", "2026-06-28 18:38:40"],
                    ["Policy", "\u0414\u0430"],
                    ["Display name", "First Person"],
                    ["Email", EXPECTED_EMAIL],
                    ["Reference images", EXPECTED_IMAGE_URL],
                ],
                [
                    ["ID", "answer-2"],
                    ["Created", "2026-06-28 18:39:40"],
                    ["Policy", "\u0414\u0430"],
                    ["Display name", "Second Person"],
                    ["Email", EXPECTED_EMAIL],
                    ["Reference images", EXPECTED_FORMS_UPLOAD_URL],
                ],
            ]
        ),
        encoding="utf-8",
    )

    participants = load_participants(json_path)

    assert [participant.name for participant in participants] == ["First Person", "Second Person"]
    assert [participant.email for participant in participants] == [EXPECTED_EMAIL, EXPECTED_EMAIL]
    assert [len(participant.image_disk_paths) for participant in participants] == [1, 1]


def test_downloads_latest_forms_json_and_loads_participant(
    yandex_client: Any,
    tmp_path: Path,
) -> None:
    json_disk_path = find_latest_json_export(yandex_client, TEST_FORMS_FOLDER)
    local_json_path = tmp_path / Path(json_disk_path).name

    yandex_client.download_file(json_disk_path, local_json_path, overwrite=True)

    participants = load_participants(local_json_path)

    assert participants
    assert participants[0].name
    assert participants[0].email
    assert participants[0].image_disk_paths

    expected_name = os.environ.get("YANDEX_FORMS_EXPECTED_NAME")
    expected_email = os.environ.get("YANDEX_FORMS_EXPECTED_EMAIL")
    expected_image_path = os.environ.get("YANDEX_FORMS_EXPECTED_IMAGE_PATH")
    if expected_name:
        assert participants[0].name == expected_name
    if expected_email:
        assert participants[0].email == expected_email
    if expected_image_path:
        assert participants[0].image_disk_paths == (expected_image_path,)


def test_find_latest_json_export_reports_domain_error_for_missing_export() -> None:
    client = _FakeFormsDiskClient(files=[])

    with pytest.raises(FormsExportError) as error_info:
        find_latest_json_export(client, TEST_FORMS_FOLDER)

    assert error_info.value.safe_message() == "No JSON export files found in the Yandex Forms folder."


def test_ingest_forms_export_returns_runtime_state_without_database(tmp_path: Path) -> None:
    client = _FakeFormsDiskClient(
        files=[
            {
                "type": "file",
                "name": "forms-export.json",
                "path": f"disk:{TEST_FORMS_FOLDER}/forms-export.json",
                "created": "2026-06-28T18:38:40+03:00",
            }
        ]
    )

    result = ingest_forms_export(client, TEST_FORM_ID, data_dir=tmp_path / "forms")

    assert result.participants_count == 1
    assert result.reference_images_count == 1
    assert result.local_json_path.is_file()
    assert len(result.participants) == 1
    participant = result.participants[0]
    assert participant.id == 1
    assert participant.name == EXPECTED_NAME
    assert participant.email == EXPECTED_EMAIL
    assert participant.policy_accepted is True
    assert len(participant.reference_images) == 1
    reference_image = participant.reference_images[0]
    assert reference_image.id == 1
    assert reference_image.participant_id == participant.id
    assert reference_image.disk_path == EXPECTED_IMAGE_PATH
    assert reference_image.local_path.is_file()
    assert result.reference_images == (reference_image,)
    assert not (tmp_path / "photo_distributor.sqlite3").exists()


def test_ingest_forms_export_skips_missing_reference_images(tmp_path: Path) -> None:
    client = _FakeFormsDiskClient(
        files=[
            {
                "type": "file",
                "name": "forms-export.json",
                "path": f"disk:{TEST_FORMS_FOLDER}/forms-export.json",
                "created": "2026-06-28T18:38:40+03:00",
            }
        ],
        missing_downloads={EXPECTED_IMAGE_PATH},
    )

    result = ingest_forms_export(client, TEST_FORM_ID, data_dir=tmp_path / "forms")

    assert result.participants_count == 0
    assert result.reference_images_count == 0
    assert result.participants == ()


class _FakeFormsDiskClient:
    """Small test double for forms export folder listing."""

    def __init__(
        self,
        files: list[dict[str, object]],
        missing_downloads: set[str] | None = None,
    ) -> None:
        self.files = files
        self.missing_downloads = missing_downloads or set()

    def list_files(self, path: str) -> list[dict[str, object]]:
        assert path == TEST_FORMS_FOLDER
        return self.files

    def download_file(self, disk_path: str, local_path: Path, *, overwrite: bool = False) -> Path:
        if disk_path in self.missing_downloads:
            raise DiskApiError("Resource not found.", status_code=404)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if disk_path.endswith("forms-export.json"):
            local_path.write_text(_forms_export_json(), encoding="utf-8")
        elif disk_path == EXPECTED_IMAGE_PATH:
            local_path.write_text("reference image", encoding="utf-8")
        else:
            raise AssertionError(f"Unexpected download path: {disk_path}")
        return local_path


def _forms_export_json() -> str:
    """Return one fake Yandex Forms JSON export."""

    return json.dumps(
        [
            [
                ["ID", "answer-1"],
                ["Created", "2026-06-28 18:38:40"],
                ["Policy", "\u0414\u0430"],
                ["Display name", EXPECTED_NAME],
                ["Email", EXPECTED_EMAIL],
                ["Reference images", EXPECTED_IMAGE_URL],
            ]
        ]
    )
