"""OpenCV-backed face detection and embedding extraction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2 as cv
import numpy as np

from utils import redact_personal_data

from .types import (
    EmbeddingReference,
    EventPhotoForAnalysis,
    EventFaceMatch,
    FaceAnalysisStepResult,
    FaceDetection,
    FaceEmbedding,
    ReferenceScore,
    ReferenceImageForAnalysis,
    ReferenceEmbeddingRecord,
)


class FaceAnalysisError(RuntimeError):
    """Raised when face detection or embedding extraction cannot run."""

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        """Create a face-analysis error with an optional log-safe message."""

        super().__init__(message)
        self._safe_message = safe_message

    def safe_message(self) -> str:
        """Return a message safe for logs and console diagnostics."""

        if self._safe_message is not None:
            return self._safe_message
        return redact_personal_data(self)


@dataclass(frozen=True)
class YuNetConfig:
    """Runtime parameters for OpenCV YuNet face detection.

    Attributes:
        score_threshold: Minimum detector confidence required for a face row.
        nms_threshold: Non-maximum suppression threshold used by YuNet.
        top_k: Maximum number of candidate detections returned by the model.
        max_input_side: Maximum image side passed to YuNet. Larger images are
            downscaled for detection, then detections are mapped back to the
            original image coordinates. `None` or a non-positive value disables
            resizing.
        backend_id: OpenCV DNN backend id. `0` means the default CPU backend.
        target_id: OpenCV DNN target id. `0` means the default CPU target.
    """

    score_threshold: float = 0.6
    nms_threshold: float = 0.3
    top_k: int = 5000
    max_input_side: int | None = 1600
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
        """Create a YuNet/SFace analyzer without loading models yet.

        Args:
            detector_model_path: Path to the YuNet ONNX detector model.
            recognizer_model_path: Optional path to the SFace ONNX recognizer
                model. It is required only for embedding/alignment calls.
            detector_config: Optional YuNet runtime configuration.
        """

        self.detector_model_path = Path(detector_model_path)
        self.recognizer_model_path = Path(recognizer_model_path) if recognizer_model_path else None
        self.detector_config = detector_config or YuNetConfig()
        self._detector: Any | None = None
        self._recognizer: Any | None = None

    def detect(self, image: str | Path | Any) -> list[FaceDetection]:
        """Return YuNet detections for a single image."""

        image_array = _load_image(image)
        detection_image, coordinate_scale = _resize_for_detection(
            image_array,
            self.detector_config.max_input_side,
        )
        height, width = detection_image.shape[:2]

        detector = self._get_detector(input_size=(width, height))
        result = detector.detect(detection_image)
        faces = result[1] if isinstance(result, tuple) else result
        if faces is None:
            return []

        return [
            FaceDetection.from_yunet_row(_scale_yunet_row(row, coordinate_scale))
            for row in faces
        ]

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

    def match_embedding(
        self,
        query_vector: Sequence[float],
        references: Sequence[EmbeddingReference],
        *,
        min_score: float | None = None,
    ) -> tuple[ReferenceScore, ...]:
        """Match one face embedding against known reference embeddings.

        Args:
            query_vector: Event face embedding to recognize.
            references: Known participant reference embeddings.
            min_score: Optional minimum similarity score for accepted
                reference-level matches.

        Returns:
            Reference scores sorted from high to low.
        """

        scores = [
            ReferenceScore(
                person_id=reference.person_id,
                reference_id=reference.reference_id,
                score=self.embedding_similarity(query_vector, reference.vector),
            )
            for reference in references
        ]
        if min_score is not None:
            scores = [score for score in scores if score.score >= min_score]
        return tuple(sorted(scores, key=lambda item: item.score, reverse=True))

    @staticmethod
    def embedding_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        """Return cosine similarity for two face embedding vectors.

        Args:
            left: First numeric embedding vector.
            right: Second numeric embedding vector.

        Returns:
            Cosine similarity. Returns `0.0` when either vector has zero norm.
        """

        dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def analyze_distribution(
        self,
        reference_images: Sequence[ReferenceImageForAnalysis],
        event_photos: Sequence[EventPhotoForAnalysis],
        similarity_threshold: float,
    ) -> FaceAnalysisStepResult:
        """Run reference embedding extraction, event detection, and matching.

        Args:
            reference_images: Local reference images imported from the forms
                export. Each item must expose `participant_id` and
                `local_path`.
            event_photos: Downloaded event photos for this run. Each item must
                expose `id` and `local_path`.
            similarity_threshold: Minimum score for accepting event/reference
                face matches.

        Returns:
            Reference embeddings, event face count, and accepted face matches.

        Side effects:
            Runs local model inference through this analyzer.
        """

        reference_embeddings = self._compute_reference_embeddings(reference_images)
        event_faces_count, face_matches = self._analyze_event_photos(
            event_photos,
            reference_embeddings,
            similarity_threshold,
        )

        return FaceAnalysisStepResult(
            reference_embeddings=tuple(reference_embeddings),
            event_photos_count=len(event_photos),
            event_faces_count=event_faces_count,
            face_matches=tuple(face_matches),
        )

    def _compute_reference_embeddings(
        self,
        reference_images: Sequence[ReferenceImageForAnalysis],
    ) -> list[ReferenceEmbeddingRecord]:
        """Analyze local reference images and return detected face embeddings."""

        records: list[ReferenceEmbeddingRecord] = []
        for reference_image in reference_images:
            embeddings = self.embed(reference_image.local_path)
            for embedding in embeddings:
                records.append(
                    ReferenceEmbeddingRecord(
                        id=len(records) + 1,
                        participant_id=reference_image.participant_id,
                        vector=embedding.vector,
                    )
                )
        return records

    def _analyze_event_photos(
        self,
        event_photos: Sequence[EventPhotoForAnalysis],
        reference_embeddings: list[ReferenceEmbeddingRecord],
        similarity_threshold: float,
    ) -> tuple[int, list[EventFaceMatch]]:
        """Detect event faces, compare them to references, and return matches."""

        event_faces_count = 0
        face_matches: list[EventFaceMatch] = []
        matching_references = [
            EmbeddingReference(
                person_id=reference_embedding.participant_id,
                reference_id=reference_embedding.id,
                vector=reference_embedding.vector,
            )
            for reference_embedding in reference_embeddings
        ]

        for photo in event_photos:
            embeddings = self.embed(photo.local_path)
            for embedding in embeddings:
                event_faces_count += 1

                for reference_score in self.match_embedding(
                    embedding.vector,
                    matching_references,
                    min_score=similarity_threshold,
                ):
                    face_matches.append(
                        EventFaceMatch(
                            event_photo_id=photo.id,
                            participant_id=int(reference_score.person_id),
                            reference_embedding_id=int(reference_score.reference_id),
                            similarity=reference_score.score,
                        )
                    )

        return event_faces_count, face_matches

    def _get_detector(self, *, input_size: tuple[int, int]) -> Any:
        """Return a cached YuNet detector configured for the current image size."""

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
        """Return a cached SFace recognizer, loading it on first use."""

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
    """Return an OpenCV image array from a path or already-loaded image."""

    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise FaceAnalysisError(
                f"Image file does not exist: {path}",
                safe_message="Image file does not exist.",
            )
        try:
            from photo_distribution_utils.image_files import ImageFileError, load_image_for_opencv

            return load_image_for_opencv(path)
        except ImageFileError as exc:
            raise FaceAnalysisError(
                f"OpenCV could not read image file: {path}",
                safe_message=exc.safe_message(),
            ) from exc

    if not hasattr(image, "shape"):
        raise FaceAnalysisError("Image must be a file path or an OpenCV/numpy image array.")
    return image


def _resize_for_detection(image: Any, max_input_side: int | None) -> tuple[Any, float]:
    """Return the YuNet input image and scale back to original coordinates.

    Args:
        image: Original OpenCV image array.
        max_input_side: Maximum side passed to YuNet. `None` or non-positive
            values keep the original image.

    Returns:
        A tuple with the image passed to YuNet and the multiplier that maps
        YuNet coordinates back to the original image.
    """

    if max_input_side is None or max_input_side <= 0:
        return image, 1.0

    height, width = image.shape[:2]
    largest_side = max(height, width)
    if largest_side <= max_input_side:
        return image, 1.0

    resize_scale = max_input_side / largest_side
    resized_width = max(1, round(width * resize_scale))
    resized_height = max(1, round(height * resize_scale))
    resized = cv.resize(image, (resized_width, resized_height), interpolation=cv.INTER_AREA)
    return resized, 1.0 / resize_scale


def _scale_yunet_row(row: Any, coordinate_scale: float) -> tuple[float, ...]:
    """Scale YuNet row coordinates while preserving the confidence score.

    Args:
        row: YuNet output row in detector-input coordinates.
        coordinate_scale: Multiplier that maps coordinates to the original
            image.

    Returns:
        YuNet row with box and landmark coordinates in original image
        coordinates.
    """

    values = [float(value) for value in row]
    if coordinate_scale == 1.0:
        return tuple(values)

    for index in range(min(14, len(values))):
        values[index] *= coordinate_scale
    return tuple(values)


def _ensure_file(path: Path, label: str) -> None:
    """Raise a face-analysis error when a required model/input file is absent."""

    if not path.is_file():
        raise FaceAnalysisError(
            f"{label} does not exist: {path}",
            safe_message=f"{label} does not exist.",
        )


def _as_cv_row(detection: FaceDetection) -> Any:
    """Convert one project detection into the row shape expected by OpenCV."""

    return np.array(detection.yunet_row, dtype=np.float32).reshape(1, -1)
