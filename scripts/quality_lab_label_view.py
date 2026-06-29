"""Render one quality-lab image with simple face ids for manual labeling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2 as cv


DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render an image for manual face labeling.")
    parser.add_argument("image_id", nargs="?")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--next-unlabeled",
        action="store_true",
        help="Render the first image that still has unlabeled predicted faces.",
    )
    parser.add_argument(
        "--display-max-side",
        type=int,
        default=1200,
        help="Also write a resized *_display image for quick review. Use 0 to disable.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.data_dir / "runs" / args.run_id
    predictions_path = run_dir / "predictions.json"
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    labels = _load_labels(args.data_dir / "labels.json")
    image_id = args.image_id
    if args.next_unlabeled or image_id is None:
        image_id = _next_unlabeled_image_id(predictions, labels)
        if image_id is None:
            print("No unlabeled predicted faces found.")
            return 0

    image_record = predictions["images"][image_id]
    image = cv.imread(image_record["path"])
    if image is None:
        raise ValueError(f"Could not read image: {image_record['path']}")

    for face in image_record["faces"]:
        box = face["detection"]["box"]
        face_id = f"face{face['face_index']}"
        draw_box(image, box, face_id)

    output_path = run_dir / f"{image_id}_label_view.jpg"
    cv.imwrite(str(output_path), image)
    print(f"image_id: {image_id}")
    print(output_path)
    if args.display_max_side > 0:
        display_path = _write_display_image(output_path, args.display_max_side)
        print(f"display: {display_path}")
    for face in image_record["faces"]:
        print(f"face{face['face_index']}: {face['face_id']}")
    return 0


def _load_labels(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"people": {}, "images": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Labels file must contain a JSON object: {path}")
    return data


def _next_unlabeled_image_id(
    predictions: dict[str, object],
    labels: dict[str, object],
) -> str | None:
    labeled_images = labels.get("images", {})
    for image_id, image_record in predictions.get("images", {}).items():
        image_labels = labeled_images.get(image_id, {})
        face_labels = image_labels.get("faces", {})
        for face in image_record.get("faces", []):
            if face["face_id"] not in face_labels:
                return image_id
    return None


def _write_display_image(path: Path, max_side: int) -> Path:
    image = cv.imread(str(path))
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        image = cv.resize(
            image,
            (int(width * scale), int(height * scale)),
            interpolation=cv.INTER_AREA,
        )
    output_path = path.with_name(f"{path.stem}_display{path.suffix}")
    cv.imwrite(str(output_path), image)
    return output_path


def draw_box(image: object, box: dict[str, float], face_id: str) -> None:
    image_height, image_width = image.shape[:2]
    thickness = max(4, round(min(image_height, image_width) / 140))
    font_scale = max(0.9, min(image_height, image_width) / 900)
    label_thickness = max(2, thickness // 2)

    x1 = max(0, round(box["x"]))
    y1 = max(0, round(box["y"]))
    x2 = max(0, round(box["x"] + box["width"]))
    y2 = max(0, round(box["y"] + box["height"]))
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


if __name__ == "__main__":
    raise SystemExit(main())
