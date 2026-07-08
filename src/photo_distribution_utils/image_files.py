"""Image file loading helpers shared by download validation and face analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2 as cv
import numpy as np

from utils import redact_personal_data


OPENCV_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
HEIC_IMAGE_EXTENSIONS = frozenset({".heic", ".heif"})
IMAGE_EXTENSIONS = OPENCV_IMAGE_EXTENSIONS | HEIC_IMAGE_EXTENSIONS


class ImageFileError(RuntimeError):
    """Raised when an image file cannot be decoded for OpenCV processing."""

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        """Create an image file error with an optional log-safe message.

        Args:
            message: Internal diagnostic message.
            safe_message: Optional message safe for logs and CLI output.
        """

        super().__init__(redact_personal_data(message))
        self._safe_message = safe_message

    def safe_message(self) -> str:
        """Return a message safe for logs and console diagnostics."""

        if self._safe_message is not None:
            return self._safe_message
        return redact_personal_data(self)


def load_image_for_opencv(path: str | Path) -> Any:
    """Load an image file into an OpenCV BGR image array.

    Args:
        path: Local image file path. `.heic` and `.heif` files require the
            `pillow-heif` dependency.

    Returns:
        OpenCV-compatible BGR image array.

    Raises:
        ImageFileError: If the file does not exist or cannot be decoded.
    """

    image_path = Path(path)
    if not image_path.is_file():
        raise ImageFileError(
            f"Image file does not exist: {image_path}",
            safe_message="Image file does not exist.",
        )

    suffix = image_path.suffix.lower()
    if suffix in HEIC_IMAGE_EXTENSIONS:
        return _load_heic_for_opencv(image_path)

    image_array = cv.imread(str(image_path))
    if image_array is None:
        raise ImageFileError(
            f"OpenCV could not read image file: {image_path}",
            safe_message="OpenCV could not read image file.",
        )
    return image_array


def is_readable_image(path: str | Path) -> bool:
    """Return whether an image file can be decoded for OpenCV processing.

    Args:
        path: Local image file path.

    Returns:
        `True` when the image can be loaded, otherwise `False`.
    """

    try:
        load_image_for_opencv(path)
    except ImageFileError:
        return False
    return True


def _load_heic_for_opencv(path: Path) -> Any:
    """Decode a HEIC/HEIF image into OpenCV BGR format.

    Args:
        path: Local HEIC/HEIF image path.

    Returns:
        OpenCV-compatible BGR image array.

    Raises:
        ImageFileError: If HEIC dependencies are missing or decoding fails.
    """

    try:
        from PIL import Image
        import pillow_heif
    except ImportError as exc:
        raise ImageFileError(
            "HEIC image support dependencies are not installed.",
            safe_message="HEIC image support dependencies are not installed.",
        ) from exc

    try:
        pillow_heif.register_heif_opener()
        with Image.open(path) as image:
            rgb_image = image.convert("RGB")
            rgb_array = np.asarray(rgb_image)
    except Exception as exc:
        raise ImageFileError(
            f"Could not decode HEIC image file: {path}",
            safe_message="Could not decode HEIC image file.",
        ) from exc

    return cv.cvtColor(rgb_array, cv.COLOR_RGB2BGR)
