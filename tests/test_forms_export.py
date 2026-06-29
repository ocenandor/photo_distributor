"""Tests for manually exported Yandex Forms JSON answers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from forms_export import find_latest_json_export, load_participants


TEST_FORM_ID = "test_form"
TEST_FORMS_FOLDER = f"/Yandex.Forms/{TEST_FORM_ID}"
EXPECTED_NAME = "Example Participant"
EXPECTED_EMAIL = "participant@example.com"
EXPECTED_IMAGE_PATH = "/Yandex.Forms/test_form/Files/reference.jpg"
EXPECTED_IMAGE_URL = (
    "https://disk.yandex.ru/client/disk/Yandex.Forms/test_form/Files"
    "?idApp=client&dialog=slider"
    "&idDialog=%2Fdisk%2FYandex.Forms%2Ftest_form%2FFiles%2Freference.jpg"
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
