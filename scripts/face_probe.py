"""Manual face-analysis probe for local images.

Example:
    python scripts/face_probe.py \
        --yunet data/models/face_detection_yunet_2023mar.onnx \
        --sface data/models/face_recognition_sface_2021dec.onnx \
        data/mock_faces/person1.jpg data/mock_faces/person2.jpg
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

import cv2 as cv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from face_analysis import FaceAnalysisError, FaceAnalyzer, FaceEmbedding, YuNetConfig  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect faces, draw boxes, save embeddings, and compare similarities.",
    )
    parser.add_argument("images", nargs="+", type=Path, help="Local image paths to analyze.")
    parser.add_argument("--yunet", required=True, type=Path, help="Path to YuNet .onnx model.")
    parser.add_argument("--sface", required=True, type=Path, help="Path to SFace .onnx model.")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.6,
        help="YuNet face detection confidence threshold.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/face_probe"),
        help="Directory for annotated images and embeddings JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    analyzer = FaceAnalyzer(
        args.yunet,
        args.sface,
        detector_config=YuNetConfig(score_threshold=args.score_threshold),
    )
    all_rows: list[dict[str, object]] = []

    try:
        for image_index, image_path in enumerate(args.images, start=1):
            rows = analyze_image(
                analyzer=analyzer,
                image_path=image_path,
                image_index=image_index,
                output_dir=args.output_dir,
            )
            all_rows.extend(rows)
    except FaceAnalysisError as exc:
        print(f"Face analysis error: {exc}", file=sys.stderr)
        return 1

    embeddings_path = args.output_dir / "embeddings.json"
    embeddings_path.write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Embeddings: {embeddings_path}")

    if len(all_rows) >= 2:
        print_similarity_table(all_rows)
    else:
        print("Similarity table skipped: need at least two detected faces.")

    return 0


def analyze_image(
    *,
    analyzer: FaceAnalyzer,
    image_path: Path,
    image_index: int,
    output_dir: Path,
) -> list[dict[str, object]]:
    image = cv.imread(str(image_path))
    if image is None:
        raise FaceAnalysisError(f"OpenCV could not read image file: {image_path}")

    detections = analyzer.detect(image)
    embeddings = analyzer.embed(image, detections)
    rows = [
        _embedding_row(image_path, image_index, face_index, embedding)
        for face_index, embedding in enumerate(embeddings, start=1)
    ]

    annotated = image.copy()
    for row, embedding in zip(rows, embeddings):
        draw_detection(annotated, str(row["face_id"]), embedding)

    output_path = output_dir / f"{image_path.stem}_faces{image_path.suffix}"
    cv.imwrite(str(output_path), annotated)
    print(f"{image_path.name}: {len(rows)} faces -> {output_path}")
    return rows


def _embedding_row(
    image_path: Path,
    image_index: int,
    face_index: int,
    embedding: FaceEmbedding,
) -> dict[str, object]:
    face_id = f"img{image_index}_face{face_index}"
    return {
        "face_id": face_id,
        "image_path": str(image_path),
        "detection": asdict(embedding.detection),
        "embedding": list(embedding.vector),
    }


def draw_detection(image: object, face_id: str, embedding: FaceEmbedding) -> None:
    image_height, image_width = image.shape[:2]
    thickness = max(4, round(min(image_height, image_width) / 140))
    font_scale = max(0.9, min(image_height, image_width) / 900)
    label_thickness = max(2, thickness // 2)

    box = embedding.detection.box
    x1 = max(0, round(box.x))
    y1 = max(0, round(box.y))
    x2 = max(0, round(box.x + box.width))
    y2 = max(0, round(box.y + box.height))

    cv.rectangle(image, (x1, y1), (x2, y2), (0, 0, 0), thickness + 4)
    cv.rectangle(image, (x1, y1), (x2, y2), (40, 255, 80), thickness)

    label_size, baseline = cv.getTextSize(
        face_id,
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        label_thickness,
    )
    label_width, label_height = label_size
    label_y1 = max(0, y1 - label_height - baseline - thickness)
    label_y2 = label_y1 + label_height + baseline + thickness
    label_x2 = min(image_width - 1, x1 + label_width + thickness * 2)
    cv.rectangle(image, (x1, label_y1), (label_x2, label_y2), (0, 0, 0), -1)
    cv.putText(
        image,
        face_id,
        (x1 + thickness, label_y2 - baseline),
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (40, 255, 80),
        label_thickness,
        cv.LINE_AA,
    )


def print_similarity_table(rows: list[dict[str, object]]) -> None:
    print()
    print("Cosine similarity:")
    print(f"{'face_a':<16} {'face_b':<16} {'similarity':>10}")
    print("-" * 44)

    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            similarity = cosine_similarity(
                _embedding_vector(left),
                _embedding_vector(right),
            )
            print(f"{str(left['face_id']):<16} {str(right['face_id']):<16} {similarity:>10.4f}")


def _embedding_vector(row: dict[str, object]) -> list[float]:
    values = row["embedding"]
    if not isinstance(values, list):
        raise TypeError("Embedding row must contain a list.")
    return [float(value) for value in values]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


if __name__ == "__main__":
    raise SystemExit(main())
