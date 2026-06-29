"""Create or update a draft quality-lab labels file from local images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize quality lab labels.json.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data_dir = args.data_dir
    images_dir = data_dir / "images"
    references_dir = data_dir / "references"
    labels_path = data_dir / "labels.json"
    images_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)

    labels = _load_labels(labels_path)
    people = labels.setdefault("people", {})
    images = labels.setdefault("images", {})
    added_people = 0
    added_images = 0

    for person_dir in sorted(path for path in references_dir.iterdir() if path.is_dir()):
        if person_dir.name not in people:
            people[person_dir.name] = {"display_name": person_dir.name}
            added_people += 1

    for image_path in sorted(images_dir.iterdir()):
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        image_id = image_path.stem
        if image_id not in images:
            images[image_id] = {
                "path": str(image_path),
                "photo_subjects": [],
                "notes": "",
                "faces": {},
            }
            added_images += 1

    labels_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Labels: {labels_path}")
    print(f"People: {len(people)}")
    print(f"Added people: {added_people}")
    print(f"Images: {len(images)}")
    print(f"Added images: {added_images}")
    return 0


def _load_labels(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"people": {}, "images": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Labels file must contain a JSON object: {path}")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
