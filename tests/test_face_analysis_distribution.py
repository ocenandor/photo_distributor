"""Tests for FaceAnalyzer distribution analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from face_analysis import (
    EventPhotoForAnalysis,
    FaceAnalyzer,
    FaceDetection,
    FaceEmbedding,
    ReferenceImageForAnalysis,
)


def test_analyze_distribution_extracts_references_and_matches_event_faces(
    tmp_path: Path,
) -> None:
    reference_images = _reference_images(tmp_path)
    event_photos = _event_photos(tmp_path)

    result = FakeAnalyzer("models/face_detection_yunet.onnx").analyze_distribution(
        reference_images,
        event_photos,
        0.5,
    )

    assert result.reference_embeddings_count == 1
    assert result.event_photos_count == 2
    assert result.event_faces_count == 2
    assert result.face_matches_count == 1
    assert result.reference_embeddings[0].participant_id == 1
    assert result.face_matches[0].event_photo_id == 1
    assert result.face_matches[0].participant_id == 1


def test_analyze_distribution_logs_matching_input_counts(tmp_path: Path) -> None:
    reference_images = _reference_images(tmp_path)
    event_photos = _event_photos(tmp_path)
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), format="{message}")

    try:
        FakeAnalyzer("models/face_detection_yunet.onnx").analyze_distribution(
            reference_images,
            event_photos,
            0.5,
        )
    finally:
        logger.remove(sink_id)

    assert "Start matching: references=1, photos=2" in messages


def test_analyze_distribution_logs_matching_result_counts(tmp_path: Path) -> None:
    reference_images = _reference_images(tmp_path)
    event_photos = _event_photos(tmp_path)
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), format="{message}")

    try:
        FakeAnalyzer("models/face_detection_yunet.onnx").analyze_distribution(
            reference_images,
            event_photos,
            0.5,
        )
    finally:
        logger.remove(sink_id)

    assert "Finish matching: reference_embeddings=1, photos=2, faces=2, matches=1" in messages


def test_analyze_distribution_respects_similarity_threshold(
    tmp_path: Path,
) -> None:
    reference_images = _reference_images(tmp_path)
    event_photos = _event_photos(tmp_path)

    result = FakeAnalyzer("models/face_detection_yunet.onnx").analyze_distribution(
        reference_images,
        event_photos,
        1.1,
    )

    assert result.event_faces_count == 2
    assert result.face_matches_count == 0


class FakeAnalyzer(FaceAnalyzer):
    """Deterministic analyzer that returns embeddings by file name."""

    def embed(self, image: str | Path | Any) -> list[FaceEmbedding]:
        image_name = Path(str(image)).name
        if image_name == "reference.jpg":
            return [_embedding((1.0, 0.0, 0.0))]
        if image_name == "matched.jpg":
            return [_embedding((1.0, 0.0, 0.0))]
        if image_name == "quarantine.jpg":
            return [_embedding((0.0, 1.0, 0.0))]
        return []

def _event_photos(tmp_path: Path) -> list[EventPhotoForAnalysis]:
    """Create downloaded event photo records for analyzer workflow tests."""

    event_dir = tmp_path / "event_photos"
    event_dir.mkdir()
    records = [
        EventPhotoForAnalysis(
            id=1,
            local_path=event_dir / "matched.jpg",
        ),
        EventPhotoForAnalysis(
            id=2,
            local_path=event_dir / "quarantine.jpg",
        ),
    ]
    for record in records:
        record.local_path.write_text(record.local_path.name, encoding="utf-8")
    return records


def _reference_images(tmp_path: Path) -> list[ReferenceImageForAnalysis]:
    """Build in-memory reference image state with one participant reference."""

    reference_path = tmp_path / "reference.jpg"
    reference_path.write_text("reference", encoding="utf-8")
    return [
        ReferenceImageForAnalysis(
            participant_id=1,
            local_path=reference_path,
        )
    ]


def _embedding(vector: tuple[float, ...]) -> FaceEmbedding:
    detection = FaceDetection.from_yunet_row(
        [10, 20, 30, 40, 15, 25, 35, 25, 25, 35, 18, 50, 32, 50, 0.95]
    )
    return FaceEmbedding(detection=detection, vector=vector)
