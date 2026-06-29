"""Local tests for the face analysis module interface."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from face_analysis import FaceAnalysisError, FaceAnalyzer, FaceDetection, YuNetConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YUNET_MODEL_PATH = PROJECT_ROOT / "data" / "models" / "face_detection_yunet_2023mar.onnx"
DEFAULT_SFACE_MODEL_PATH = PROJECT_ROOT / "data" / "models" / "face_recognition_sface_2021dec.onnx"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def test_yunet_default_score_threshold_is_selected_from_manual_probe() -> None:
    assert YuNetConfig().score_threshold == 0.6


def test_detection_can_be_created_from_yunet_row() -> None:
    detection = FaceDetection.from_yunet_row(
        [10, 20, 30, 40, 15, 25, 35, 25, 25, 35, 18, 50, 32, 50, 0.95]
    )

    assert detection.box.x == 10
    assert detection.box.y == 20
    assert detection.box.width == 30
    assert detection.box.height == 40
    assert detection.landmarks.nose_tip.x == 25
    assert detection.score == 0.95
    assert len(detection.yunet_row) == 15


def test_detection_rejects_short_yunet_row() -> None:
    with pytest.raises(ValueError, match="at least 15 values"):
        FaceDetection.from_yunet_row([1, 2, 3])


def test_embed_requires_recognizer_model_path() -> None:
    analyzer = FaceAnalyzer("models/face_detection_yunet.onnx")

    with pytest.raises(FaceAnalysisError, match="SFace recognizer model path is required"):
        analyzer.embed("tests/mock_faces/person.jpg", detections=[])


def test_detects_faces_and_extracts_embeddings_from_real_image() -> None:
    detector_model_path = _model_path("YUNET_MODEL_PATH", DEFAULT_YUNET_MODEL_PATH)
    recognizer_model_path = _model_path("SFACE_MODEL_PATH", DEFAULT_SFACE_MODEL_PATH)
    analyzer = FaceAnalyzer(detector_model_path, recognizer_model_path)

    image_path, detections = _first_image_with_detections(analyzer)
    embeddings = analyzer.embed(image_path, detections)

    assert detections
    assert len(embeddings) == len(detections)
    assert all(embedding.vector for embedding in embeddings)


def _model_path(env_name: str, default_path: Path) -> Path:
    path = Path(os.environ.get(env_name, default_path))
    if not path.is_file():
        pytest.skip(f"Set {env_name} or add model file: {default_path}")
    return path


def _first_image_with_detections(
    analyzer: FaceAnalyzer,
) -> tuple[Path, list[FaceDetection]]:
    for image_path in _candidate_images():
        detections = analyzer.detect(image_path)
        if detections:
            return image_path, detections

    pytest.skip("Set FACE_TEST_IMAGE or add a local image with a detectable face.")


def _candidate_images() -> list[Path]:
    configured = os.environ.get("FACE_TEST_IMAGE")
    if configured:
        return [Path(configured)]

    image_roots = (
        PROJECT_ROOT / "quality_lab" / "data" / "images",
        PROJECT_ROOT / "data" / "event_photos",
    )
    images: list[Path] = []
    for root in image_roots:
        if not root.is_dir():
            continue
        images.extend(
            sorted(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            )
        )
    return images
