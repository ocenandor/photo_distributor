"""Local tests for the face analysis module interface."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from face_analysis import EmbeddingReference, FaceAnalysisError, FaceAnalyzer, FaceDetection, YuNetConfig
from photo_distribution_utils.image_files import IMAGE_EXTENSIONS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YUNET_MODEL_PATH = PROJECT_ROOT / "data" / "models" / "face_detection_yunet_2023mar.onnx"
DEFAULT_SFACE_MODEL_PATH = PROJECT_ROOT / "data" / "models" / "face_recognition_sface_2021dec.onnx"


def test_yunet_default_score_threshold_is_selected_from_manual_probe() -> None:
    assert YuNetConfig().score_threshold == 0.6
    assert YuNetConfig().max_input_side == 1600


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


def test_embedding_similarity_handles_identical_and_zero_vectors() -> None:
    assert FaceAnalyzer.embedding_similarity((1.0, 0.0), (1.0, 0.0)) == 1.0
    assert FaceAnalyzer.embedding_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0


def test_match_embedding_scores_references_without_loading_models() -> None:
    analyzer = FaceAnalyzer("models/face_detection_yunet.onnx")

    scores = analyzer.match_embedding(
        (1.0, 0.0),
        (
            EmbeddingReference(person_id=1, reference_id=10, vector=(1.0, 0.0)),
            EmbeddingReference(person_id=2, reference_id=20, vector=(0.0, 1.0)),
        ),
        min_score=0.5,
    )

    assert len(scores) == 1
    assert scores[0].person_id == 1
    assert scores[0].reference_id == 10
    assert scores[0].score == 1.0


def test_detect_resizes_large_images_and_restores_original_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = FaceAnalyzer(
        "models/face_detection_yunet.onnx",
        detector_config=YuNetConfig(max_input_side=100),
    )
    image = np.zeros((200, 400, 3), dtype=np.uint8)
    seen_input_sizes: list[tuple[int, int]] = []
    seen_shapes: list[tuple[int, int]] = []

    class FakeDetector:
        def detect(self, input_image: object) -> tuple[None, np.ndarray]:
            seen_shapes.append(input_image.shape[:2])
            return (
                None,
                np.array(
                    [[10, 20, 30, 40, 15, 25, 35, 25, 25, 35, 18, 50, 32, 50, 0.95]],
                    dtype=np.float32,
                ),
            )

    def fake_get_detector(input_size: tuple[int, int]) -> FakeDetector:
        seen_input_sizes.append(input_size)
        return FakeDetector()

    monkeypatch.setattr(analyzer, "_get_detector", fake_get_detector)

    detections = analyzer.detect(image)

    assert seen_input_sizes == [(100, 50)]
    assert seen_shapes == [(50, 100)]
    assert len(detections) == 1
    assert detections[0].box.x == 40
    assert detections[0].box.y == 80
    assert detections[0].box.width == 120
    assert detections[0].box.height == 160
    assert detections[0].landmarks.nose_tip.x == 100
    assert detections[0].landmarks.nose_tip.y == 140
    assert detections[0].score == pytest.approx(0.95)


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
    configured = os.environ.get("FACE_TEST_IMAGE")
    if configured:
        image_path = Path(configured)
        assert image_path.is_file(), f"FACE_TEST_IMAGE does not point to a file: {image_path}"
        detections = analyzer.detect(image_path)
        assert detections, f"YuNet did not detect faces in FACE_TEST_IMAGE: {image_path}"
        return image_path, detections

    checked_paths: list[Path] = []
    for image_path in _candidate_images():
        checked_paths.append(image_path)
        if not image_path.is_file():
            continue

        detections = analyzer.detect(image_path)
        if detections:
            return image_path, detections

    checked = ", ".join(str(path) for path in checked_paths[:5])
    if len(checked_paths) > 5:
        checked = f"{checked}, ..."
    pytest.skip(
        "Set FACE_TEST_IMAGE or add a local image with a detectable face. "
        f"Checked {len(checked_paths)} candidate(s): {checked or 'none'}"
    )


def _candidate_images() -> list[Path]:
    images: list[Path] = []
    image_roots = (
        PROJECT_ROOT / "quality_lab" / "data" / "images",
        PROJECT_ROOT / "data" / "event_photos",
    )
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
