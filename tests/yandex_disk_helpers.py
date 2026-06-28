"""Shared helpers for Yandex Disk integration tests."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


TEST_FOLDER_NAME = "test"
TEST_FILE_NAME = "client_upload_test.txt"
TEST_COPY_FILE_NAME = "test_copy_file.docx"


@dataclass(frozen=True)
class DiskTestPaths:
    base_folder: str
    test_folder: str
    test_file: str
    copy_source_file: str
    copy_destination_file: str
    local_file: Path
    downloaded_file: Path


def join_disk_path(parent: str, child: str) -> str:
    return f"{parent.rstrip('/')}/{child}"


def wait_for_resource_state(
    client: Any,
    path: str,
    *,
    exists: bool,
    timeout_seconds: int = 30,
    interval_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if client.resource_exists(path) is exists:
            return
        time.sleep(interval_seconds)

    expected = "exist" if exists else "be absent"
    pytest.fail(f"Expected resource to {expected}: {path}")
