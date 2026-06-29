"""Attach prediction bounding boxes to existing manual labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach bbox metadata from a run to labels.json."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels_path = args.data_dir / "labels.json"
    predictions_path = args.data_dir / "runs" / args.run_id / "predictions.json"
    labels = _read_json(labels_path)
    predictions = _read_json(predictions_path)

    updated = 0
    missing = 0
    for image_id, image_label in labels.get("images", {}).items():
        image_prediction = predictions.get("images", {}).get(image_id)
        if not image_prediction:
            continue
        predictions_by_face_id = {
            face["face_id"]: face
            for face in image_prediction.get("faces", [])
        }
        for label_id, label in image_label.get("faces", {}).items():
            face = predictions_by_face_id.get(label_id)
            if not face:
                missing += 1
                continue
            box = face.get("detection", {}).get("box")
            if not box:
                missing += 1
                continue
            label["box"] = _clean_box(box)
            label["box_source_run_id"] = args.run_id
            updated += 1

    labels_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Labels: {labels_path}")
    print(f"Updated boxes: {updated}")
    print(f"Missing predictions: {missing}")
    return 0


def _clean_box(box: dict[str, Any]) -> dict[str, float]:
    return {
        "x": float(box.get("x") or 0.0),
        "y": float(box.get("y") or 0.0),
        "width": float(box.get("width") or 0.0),
        "height": float(box.get("height") or 0.0),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
