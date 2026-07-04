"""Public data types for face analysis results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

Identifier = int | str


@dataclass(frozen=True)
class Point:
    """A two-dimensional image coordinate.

    Attributes:
        x: Horizontal image coordinate in pixels.
        y: Vertical image coordinate in pixels.
    """

    x: float
    y: float


@dataclass(frozen=True)
class BoundingBox:
    """A rectangular face bounding box in image pixel coordinates.

    Attributes:
        x: Left edge of the box.
        y: Top edge of the box.
        width: Box width in pixels.
        height: Box height in pixels.
    """

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class FaceLandmarks:
    """Five face landmarks returned by YuNet and required by SFace alignment.

    Attributes:
        right_eye: Detected right eye point from the model output.
        left_eye: Detected left eye point from the model output.
        nose_tip: Detected nose tip point.
        right_mouth_corner: Detected right mouth corner point.
        left_mouth_corner: Detected left mouth corner point.
    """

    right_eye: Point
    left_eye: Point
    nose_tip: Point
    right_mouth_corner: Point
    left_mouth_corner: Point


@dataclass(frozen=True)
class FaceDetection:
    """One YuNet face detection converted into project-native fields.

    Attributes:
        box: Face bounding box in image coordinates.
        landmarks: Five face landmarks used for aligned embedding extraction.
        score: YuNet detection confidence score.
        yunet_row: Original numeric YuNet row preserved for OpenCV SFace APIs.
    """

    box: BoundingBox
    landmarks: FaceLandmarks
    score: float
    yunet_row: tuple[float, ...]

    @classmethod
    def from_yunet_row(cls, row: Sequence[float]) -> "FaceDetection":
        """Build a detection from one YuNet output row.

        Args:
            row: YuNet output row containing box, landmarks, and confidence.

        Returns:
            A normalized `FaceDetection` object.

        Raises:
            ValueError: If the row does not contain enough values.
        """

        values = tuple(float(value) for value in row)
        if len(values) < 15:
            raise ValueError(f"YuNet detection row must contain at least 15 values, got {len(values)}.")

        return cls(
            box=BoundingBox(
                x=values[0],
                y=values[1],
                width=values[2],
                height=values[3],
            ),
            landmarks=FaceLandmarks(
                right_eye=Point(values[4], values[5]),
                left_eye=Point(values[6], values[7]),
                nose_tip=Point(values[8], values[9]),
                right_mouth_corner=Point(values[10], values[11]),
                left_mouth_corner=Point(values[12], values[13]),
            ),
            score=values[14],
            yunet_row=values,
        )


@dataclass(frozen=True)
class FaceEmbedding:
    """One SFace embedding tied to the detection that produced it.

    Attributes:
        detection: Face detection used to align and crop the face.
        vector: Numeric embedding vector returned by SFace.
    """

    detection: FaceDetection
    vector: tuple[float, ...]


@dataclass(frozen=True)
class ReferenceEmbeddingRecord:
    """Computed reference face embedding for one participant.

    Attributes:
        id: Run-local reference embedding id.
        participant_id: Run-local participant id from the forms import state.
        vector: Numeric face embedding produced from one detected reference
            face.
    """

    id: int
    participant_id: int
    vector: tuple[float, ...]


@dataclass(frozen=True)
class ReferenceImageForAnalysis:
    """Local reference image passed into face analysis.

    Attributes:
        participant_id: Run-local participant id that owns this reference.
        local_path: Local reference image file path.
    """

    participant_id: int
    local_path: Path


@dataclass(frozen=True)
class EventPhotoForAnalysis:
    """Local event photo passed into face analysis.

    Attributes:
        id: Run-local event photo id used to connect matches back to the
            downloaded source photo record.
        local_path: Local event photo file path.
    """

    id: int
    local_path: Path


@dataclass(frozen=True)
class EmbeddingReference:
    """One reference embedding that belongs to one known person.

    Attributes:
        person_id: Stable participant/person identifier used by the caller.
        reference_id: Stable identifier for this particular reference vector.
        vector: Numeric face embedding vector.
    """

    person_id: Identifier
    reference_id: Identifier
    vector: tuple[float, ...]


@dataclass(frozen=True)
class ReferenceScore:
    """Similarity score between one query embedding and one reference.

    Attributes:
        person_id: Person identifier copied from the scored reference.
        reference_id: Reference embedding identifier copied from the scored
            reference.
        score: Cosine similarity between the query and reference vectors.
    """

    person_id: Identifier
    reference_id: Identifier
    score: float


@dataclass(frozen=True)
class EventFaceMatch:
    """Accepted match between one detected event face and one reference.

    Attributes:
        event_photo_id: Run-local id of the event photo containing the face.
        participant_id: Run-local participant id matched to the event face.
        reference_embedding_id: Run-local reference embedding id that produced
            the accepted score.
        similarity: Face embedding similarity score.
    """

    event_photo_id: int
    participant_id: int
    reference_embedding_id: int
    similarity: float


@dataclass(frozen=True)
class FaceAnalysisStepResult:
    """Face-analysis state produced for one distribution run.

    Attributes:
        reference_embeddings: Reference face embeddings computed from imported
            participant reference images.
        event_photos_count: Number of downloaded event photos processed.
        event_faces_count: Number of faces detected in event photos.
        face_matches: Accepted event/reference matches produced by embedding
            similarity.
    """

    reference_embeddings: tuple[ReferenceEmbeddingRecord, ...]
    event_photos_count: int
    event_faces_count: int
    face_matches: tuple[EventFaceMatch, ...]

    @property
    def reference_embeddings_count(self) -> int:
        """Number of reference embeddings computed for this run."""

        return len(self.reference_embeddings)

    @property
    def face_matches_count(self) -> int:
        """Number of accepted event/reference matches."""

        return len(self.face_matches)
