"""Tests for shared image loading helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from photo_distribution_utils.image_files import (
    HEIC_IMAGE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    ImageFileError,
    load_image_for_opencv,
)


VALID_IMAGE_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01"
    b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_image_extensions_include_heic_formats() -> None:
    assert {".heic", ".heif"} <= IMAGE_EXTENSIONS
    assert HEIC_IMAGE_EXTENSIONS == frozenset({".heic", ".heif"})


def test_load_image_for_opencv_reads_standard_image(tmp_path: Path) -> None:
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(VALID_IMAGE_BYTES)

    image = load_image_for_opencv(image_path)

    assert image.shape == (1, 1, 3)


def test_load_image_for_opencv_rejects_unreadable_image(tmp_path: Path) -> None:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"partial upload")

    with pytest.raises(ImageFileError, match="OpenCV could not read image file"):
        load_image_for_opencv(image_path)
