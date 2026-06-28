"""Pytest configuration for integration tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from yandex_disk_helpers import (
    TEST_COPY_FILE_NAME,
    TEST_FILE_NAME,
    TEST_FOLDER_NAME,
    DiskTestPaths,
    join_disk_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DEFAULT_YANDEX_FOLDER = "/test_event_folder"
sys.path.insert(0, str(SRC_DIR))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--yandex-folder",
        action="store",
        default=DEFAULT_YANDEX_FOLDER,
        help="Existing Yandex Disk folder path used by integration tests.",
    )


@pytest.fixture(scope="session")
def yandex_folder(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption("--yandex-folder"))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="module")
def disk_test_paths(yandex_folder: str, project_root: Path) -> DiskTestPaths:
    test_folder = join_disk_path(yandex_folder, TEST_FOLDER_NAME)
    return DiskTestPaths(
        base_folder=yandex_folder,
        test_folder=test_folder,
        test_file=join_disk_path(test_folder, TEST_FILE_NAME),
        copy_source_file=join_disk_path(yandex_folder, TEST_COPY_FILE_NAME),
        copy_destination_file=join_disk_path(test_folder, TEST_COPY_FILE_NAME),
        local_file=project_root / "tests" / TEST_FILE_NAME,
        downloaded_file=project_root / "tests" / "downloads" / TEST_COPY_FILE_NAME,
    )


@pytest.fixture(scope="session")
def yandex_client() -> Any:
    from yandex_disk import YandexDiskClient

    return YandexDiskClient.from_env()
