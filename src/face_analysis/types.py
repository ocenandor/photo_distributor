"""Public data types for face analysis results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class FaceLandmarks:
    right_eye: Point
    left_eye: Point
    nose_tip: Point
    right_mouth_corner: Point
    left_mouth_corner: Point


@dataclass(frozen=True)
class FaceDetection:
    box: BoundingBox
    landmarks: FaceLandmarks
    score: float
    yunet_row: tuple[float, ...]

    @classmethod
    def from_yunet_row(cls, row: Sequence[float]) -> "FaceDetection":
        """Build a detection from one YuNet output row."""

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
    detection: FaceDetection
    vector: tuple[float, ...]
