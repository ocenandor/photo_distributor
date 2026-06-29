"""Local tests for the face analysis module interface."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from face_analysis import FaceAnalysisError, FaceAnalyzer, FaceDetection, YuNetConfig


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


@pytest.mark.skipif(
    not all(
        os.environ.get(name)
        for name in ("YUNET_MODEL_PATH", "SFACE_MODEL_PATH", "FACE_TEST_IMAGE")
    ),
    reason="Set YUNET_MODEL_PATH, SFACE_MODEL_PATH, and FACE_TEST_IMAGE to run the OpenCV integration test.",
)
def test_detects_faces_and_extracts_embeddings_from_real_image() -> None:
    analyzer = FaceAnalyzer(
        Path(os.environ["YUNET_MODEL_PATH"]),
        Path(os.environ["SFACE_MODEL_PATH"]),
    )

    detections = analyzer.detect(Path(os.environ["FACE_TEST_IMAGE"]))
    embeddings = analyzer.embed(Path(os.environ["FACE_TEST_IMAGE"]), detections)

    assert detections
    assert len(embeddings) == len(detections)
    assert all(embedding.vector for embedding in embeddings)
