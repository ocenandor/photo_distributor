"""OpenCV-backed face detection and embedding extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2 as cv
import numpy as np

from .types import FaceDetection, FaceEmbedding


class FaceAnalysisError(RuntimeError):
    """Raised when face detection or embedding extraction cannot run."""


@dataclass(frozen=True)
class YuNetConfig:
    score_threshold: float = 0.6
    nms_threshold: float = 0.3
    top_k: int = 5000
    backend_id: int = 0
    target_id: int = 0


class FaceAnalyzer:
    """Detect faces with YuNet and extract SFace embeddings for one image."""

    def __init__(
        self,
        detector_model_path: str | Path,
        recognizer_model_path: str | Path | None = None,
        *,
        detector_config: YuNetConfig | None = None,
    ) -> None:
        self.detector_model_path = Path(detector_model_path)
        self.recognizer_model_path = Path(recognizer_model_path) if recognizer_model_path else None
        self.detector_config = detector_config or YuNetConfig()
        self._detector: Any | None = None
        self._recognizer: Any | None = None

    def detect(self, image: str | Path | Any) -> list[FaceDetection]:
        """Return YuNet detections for a single image."""

        image_array = _load_image(image)
        height, width = image_array.shape[:2]

        detector = self._get_detector(input_size=(width, height))
        result = detector.detect(image_array)
        faces = result[1] if isinstance(result, tuple) else result
        if faces is None:
            return []

        return [FaceDetection.from_yunet_row(row) for row in faces]

    def embed(
        self,
        image: str | Path | Any,
        detections: list[FaceDetection] | None = None,
    ) -> list[FaceEmbedding]:
        """Return SFace embeddings for the given detections or for newly detected faces."""

        if self.recognizer_model_path is None:
            raise FaceAnalysisError("SFace recognizer model path is required to extract embeddings.")

        image_array = _load_image(image)
        face_detections = detections if detections is not None else self.detect(image_array)
        recognizer = self._get_recognizer()

        embeddings: list[FaceEmbedding] = []
        for detection in face_detections:
            aligned_face = recognizer.alignCrop(image_array, _as_cv_row(detection))
            feature = recognizer.feature(aligned_face)
            embeddings.append(
                FaceEmbedding(
                    detection=detection,
                    vector=tuple(float(value) for value in feature.reshape(-1)),
                )
            )
        return embeddings

    def align(self, image: str | Path | Any, detection: FaceDetection) -> Any:
        """Return an aligned face crop for one detection using SFace alignment."""

        if self.recognizer_model_path is None:
            raise FaceAnalysisError("SFace recognizer model path is required to align faces.")

        image_array = _load_image(image)
        recognizer = self._get_recognizer()
        return recognizer.alignCrop(image_array, _as_cv_row(detection))

    def _get_detector(self, *, input_size: tuple[int, int]) -> Any:
        _ensure_file(self.detector_model_path, "YuNet detector model")
        if self._detector is None:
            config = self.detector_config
            self._detector = cv.FaceDetectorYN.create(
                str(self.detector_model_path),
                "",
                input_size,
                config.score_threshold,
                config.nms_threshold,
                config.top_k,
                config.backend_id,
                config.target_id,
            )
        else:
            self._detector.setInputSize(input_size)
        return self._detector

    def _get_recognizer(self) -> Any:
        if self.recognizer_model_path is None:
            raise FaceAnalysisError("SFace recognizer model path is required to extract embeddings.")
        _ensure_file(self.recognizer_model_path, "SFace recognizer model")
        if self._recognizer is None:
            self._recognizer = cv.FaceRecognizerSF.create(
                str(self.recognizer_model_path),
                "",
                self.detector_config.backend_id,
                self.detector_config.target_id,
            )
        return self._recognizer


def _load_image(image: str | Path | Any) -> Any:
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise FaceAnalysisError(f"Image file does not exist: {path}")
        image_array = cv.imread(str(path))
        if image_array is None:
            raise FaceAnalysisError(f"OpenCV could not read image file: {path}")
        return image_array

    if not hasattr(image, "shape"):
        raise FaceAnalysisError("Image must be a file path or an OpenCV/numpy image array.")
    return image


def _ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FaceAnalysisError(f"{label} does not exist: {path}")


def _as_cv_row(detection: FaceDetection) -> Any:
    return np.array(detection.yunet_row, dtype=np.float32).reshape(1, -1)
