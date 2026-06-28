"""Manual cleanup test for Yandex Disk integration tests.

This file is intentionally separate from `test_yandex_disk_client.py` so running
all client tests from VS Code does not delete the `/test` folder. Run this test
directly when cleanup is intended.
"""

from __future__ import annotations

from typing import Any

from yandex_disk_helpers import DiskTestPaths, wait_for_resource_state


def test_delete_test_subfolder(
    yandex_client: Any,
    disk_test_paths: DiskTestPaths,
) -> None:
    assert yandex_client.resource_exists(disk_test_paths.test_folder)
    assert yandex_client.resource_exists(disk_test_paths.test_file)
    assert yandex_client.resource_exists(disk_test_paths.copy_destination_file)

    yandex_client.delete_resource(disk_test_paths.test_folder, permanently=True)
    wait_for_resource_state(yandex_client, disk_test_paths.test_folder, exists=False)
    assert yandex_client.resource_exists(disk_test_paths.copy_source_file)
