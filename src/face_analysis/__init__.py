"""Face detection and embedding extraction using OpenCV YuNet and SFace."""

from .analyzer import FaceAnalysisError, FaceAnalyzer, YuNetConfig
from .types import (
    BoundingBox,
    EmbeddingReference,
    EventFaceMatch,
    EventPhotoForAnalysis,
    FaceAnalysisStepResult,
    FaceDetection,
    FaceEmbedding,
    FaceLandmarks,
    Point,
    ReferenceScore,
    ReferenceEmbeddingRecord,
    ReferenceImageForAnalysis,
)

__all__ = [
    "BoundingBox",
    "EmbeddingReference",
    "EventFaceMatch",
    "EventPhotoForAnalysis",
    "FaceAnalysisError",
    "FaceAnalysisStepResult",
    "FaceAnalyzer",
    "FaceDetection",
    "FaceEmbedding",
    "FaceLandmarks",
    "Point",
    "ReferenceScore",
    "ReferenceEmbeddingRecord",
    "ReferenceImageForAnalysis",
    "YuNetConfig",
]
