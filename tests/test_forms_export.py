"""Integration test for manually exported Yandex Forms JSON answers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forms_export import find_latest_json_export, load_participants


TEST_FORM_ID = "test_form"
TEST_FORMS_FOLDER = f"/Yandex.Forms/{TEST_FORM_ID}"
EXPECTED_NAME = "Pavel"
EXPECTED_EMAIL = "pt.megamozg123@yandex.ru"
EXPECTED_IMAGE_PATH = (
    "/Yandex.Forms/6a413b8495add5fa055916e3/Files/"
    "6a413ffb4936391fe5f7ca04_photo2023_07_1522_17_30.jpg"
)


def test_downloads_latest_forms_json_and_loads_participant(
    yandex_client: Any,
    tmp_path: Path,
) -> None:
    json_disk_path = find_latest_json_export(yandex_client, TEST_FORMS_FOLDER)
    local_json_path = tmp_path / Path(json_disk_path).name

    yandex_client.download_file(json_disk_path, local_json_path, overwrite=True)

    participants = load_participants(local_json_path)

    assert len(participants) == 1
    assert participants[0].name == EXPECTED_NAME
    assert participants[0].email == EXPECTED_EMAIL
    assert participants[0].image_disk_paths == (EXPECTED_IMAGE_PATH,)
