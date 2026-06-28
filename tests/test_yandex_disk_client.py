"""Integration tests for the Yandex Disk client.

Run from the repository root:

    pytest tests/test_yandex_disk_client.py
    pytest tests/test_yandex_disk_client.py --yandex-folder=/event_001

The tests use `YANDEX_DISK_TOKEN` from `.env`, create
`/test_event_folder/test` by default, upload `tests/client_upload_test.txt`,
and verify copied files.
"""

from __future__ import annotations

from typing import Any

import pytest

from yandex_disk_helpers import DiskTestPaths, wait_for_resource_state


def test_existing_folder_exists(yandex_client: Any, disk_test_paths: DiskTestPaths) -> None:
    assert yandex_client.resource_exists(disk_test_paths.base_folder)


def test_create_test_subfolder(
    yandex_client: Any,
    disk_test_paths: DiskTestPaths,
) -> None:
    if yandex_client.resource_exists(disk_test_paths.test_folder):
        pytest.fail(
            "Test folder already exists, refusing to delete user data: "
            f"{disk_test_paths.test_folder}"
        )

    yandex_client.create_folder(disk_test_paths.test_folder)
    wait_for_resource_state(yandex_client, disk_test_paths.test_folder, exists=True)


def test_upload_local_file_to_test_subfolder(
    yandex_client: Any,
    disk_test_paths: DiskTestPaths,
) -> None:
    assert disk_test_paths.local_file.is_file()
    assert yandex_client.resource_exists(disk_test_paths.test_folder)

    yandex_client.upload_file(
        disk_test_paths.local_file,
        disk_test_paths.test_file,
        overwrite=True,
    )
    wait_for_resource_state(yandex_client, disk_test_paths.test_file, exists=True)


def test_copy_disk_file_to_test_subfolder(
    yandex_client: Any,
    disk_test_paths: DiskTestPaths,
) -> None:
    assert yandex_client.resource_exists(disk_test_paths.test_folder)
    assert yandex_client.resource_exists(disk_test_paths.copy_source_file)

    yandex_client.copy_resource(
        disk_test_paths.copy_source_file,
        disk_test_paths.copy_destination_file,
        overwrite=True,
    )
    wait_for_resource_state(
        yandex_client,
        disk_test_paths.copy_destination_file,
        exists=True,
    )
    assert yandex_client.resource_exists(disk_test_paths.copy_source_file)
