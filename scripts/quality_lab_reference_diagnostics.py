"""Diagnose reference photos and reference-to-subject matching in quality lab."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2 as cv


DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose quality lab references.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        help="Override the run's matching threshold.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels_path = args.data_dir / "labels.json"
    run_dir = args.data_dir / "runs" / args.run_id
    predictions_path = run_dir / "predictions.json"
    labels = _read_json(labels_path)
    predictions = _read_json(predictions_path)
    threshold = (
        args.match_threshold
        if args.match_threshold is not None
        else float(predictions.get("match_threshold", 0.45))
    )

    reference_rows = _build_reference_rows(predictions)
    subject_rows = _build_subject_rows(labels, predictions, threshold)
    detail_rows = _build_reference_score_rows(labels, predictions, threshold)
    slice_rows = _build_subject_slices(subject_rows)

    _write_csv(run_dir / "reference_image_diagnostics.csv", reference_rows)
    _write_csv(run_dir / "reference_subject_diagnostics.csv", subject_rows)
    _write_csv(run_dir / "reference_score_details.csv", detail_rows)
    _write_csv(run_dir / "reference_subject_slices.csv", slice_rows)

    _print_summary(reference_rows, subject_rows, threshold, run_dir)
    return 0


def _build_reference_rows(predictions: dict[str, Any]) -> list[dict[str, Any]]:
    records_by_person = predictions.get("reference_records", {})
    image_counts = Counter()
    for records in records_by_person.values():
        for record in records:
            image_counts[str(record.get("path", ""))] += 1

    rows = []
    for person_id, records in sorted(records_by_person.items()):
        for record in records:
            reference_kind = record.get("reference_kind", "seed")
            path = str(record.get("path", ""))
            image_size = _image_size(path) if path else None
            detection = record.get("detection") or {}
            box = detection.get("box") or {}
            width = float(box.get("width") or 0.0)
            height = float(box.get("height") or 0.0)
            area_ratio = None
            height_ratio = None
            if image_size:
                image_width, image_height = image_size
                area_ratio = width * height / (image_width * image_height)
                height_ratio = height / image_height
            if reference_kind == "derived":
                issues = []
            else:
                issues = _reference_issues(
                    detections_in_image=image_counts[path],
                    detection_score=float(record.get("detection_score") or 0.0),
                    height_ratio=height_ratio,
                    area_ratio=area_ratio,
                )
            rows.append(
                {
                    "person_id": person_id,
                    "reference_id": record.get("reference_id"),
                    "reference_kind": reference_kind,
                    "path": path,
                    "source_image_id": record.get("source_image_id"),
                    "source_face_id": record.get("source_face_id"),
                    "face_index": record.get("face_index"),
                    "detections_in_image": image_counts[path],
                    "detection_score": _round(record.get("detection_score")),
                    "box_height_ratio": _round(height_ratio),
                    "box_area_ratio": _round(area_ratio),
                    "issues": ";".join(issues),
                }
            )
    return rows


def _build_subject_rows(
    labels: dict[str, Any],
    predictions: dict[str, Any],
    threshold: float,
) -> list[dict[str, Any]]:
    rows = []
    references = {
        person_id
        for person_id, count in predictions.get("references", {}).items()
        if count
    }
    for image_id, image_prediction in predictions.get("images", {}).items():
        image_label = labels.get("images", {}).get(image_id, {})
        face_labels = image_label.get("faces", {})
        for face in image_prediction.get("faces", []):
            label = face_labels.get(face["face_id"])
            if not _is_subject_face(label):
                continue
            person_id = label.get("person_id")
            match = _match_for_person(face, person_id)
            score = float(match.get("score") or 0.0) if match else None
            reference_scores = match.get("reference_scores", []) if match else []
            best_reference = reference_scores[0] if reference_scores else match or {}
            has_reference = person_id in references
            status = "no_reference"
            if has_reference and score is not None:
                status = "accepted" if score >= threshold else "missed"
            rows.append(
                {
                    "image_id": image_id,
                    "face_id": face["face_id"],
                    "person_id": person_id,
                    "has_reference": has_reference,
                    "status": status,
                    "match_threshold": threshold,
                    "score": _round(score),
                    "gap_to_threshold": _round(score - threshold if score is not None else None),
                    "best_reference_id": best_reference.get("reference_id"),
                    "best_reference_path": best_reference.get("reference_path"),
                    "quality": label.get("quality"),
                    "occlusion": label.get("occlusion"),
                    "pose": label.get("pose"),
                    "notes": label.get("notes", ""),
                }
            )
    return rows


def _build_reference_score_rows(
    labels: dict[str, Any],
    predictions: dict[str, Any],
    threshold: float,
) -> list[dict[str, Any]]:
    rows = []
    for image_id, image_prediction in predictions.get("images", {}).items():
        image_label = labels.get("images", {}).get(image_id, {})
        face_labels = image_label.get("faces", {})
        for face in image_prediction.get("faces", []):
            label = face_labels.get(face["face_id"])
            if not _is_subject_face(label):
                continue
            person_id = label.get("person_id")
            match = _match_for_person(face, person_id)
            if not match:
                rows.append(
                    {
                        "image_id": image_id,
                        "face_id": face["face_id"],
                        "person_id": person_id,
                        "reference_id": "",
                        "reference_path": "",
                        "score": "",
                        "accepted": False,
                        "quality": label.get("quality"),
                        "occlusion": label.get("occlusion"),
                        "pose": label.get("pose"),
                    }
                )
                continue
            for reference_score in match.get("reference_scores", []):
                score = float(reference_score.get("score") or 0.0)
                rows.append(
                    {
                        "image_id": image_id,
                        "face_id": face["face_id"],
                        "person_id": person_id,
                        "reference_id": reference_score.get("reference_id"),
                        "reference_path": reference_score.get("reference_path"),
                        "score": _round(score),
                        "accepted": score >= threshold,
                        "quality": label.get("quality"),
                        "occlusion": label.get("occlusion"),
                        "pose": label.get("pose"),
                    }
                )
    return rows


def _build_subject_slices(subject_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("all", []),
        ("person", ["person_id"]),
        ("occlusion", ["occlusion"]),
        ("pose", ["pose"]),
        ("person_occlusion", ["person_id", "occlusion"]),
        ("person_pose", ["person_id", "pose"]),
    ]
    rows = []
    for slice_name, fields in specs:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in subject_rows:
            groups.setdefault(tuple(row.get(field) for field in fields), []).append(row)
        for key, items in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
            with_reference = [item for item in items if item["has_reference"]]
            accepted = [item for item in with_reference if item["status"] == "accepted"]
            missed = [item for item in with_reference if item["status"] == "missed"]
            scores = [
                float(item["score"])
                for item in with_reference
                if item.get("score") not in (None, "")
            ]
            rows.append(
                {
                    "slice": slice_name,
                    "key": _slice_key(fields, key),
                    "subject_faces": len(items),
                    "with_reference": len(with_reference),
                    "without_reference": len(items) - len(with_reference),
                    "accepted": len(accepted),
                    "missed": len(missed),
                    "recall": _safe_div(len(accepted), len(with_reference)),
                    "min_score": _round(min(scores)) if scores else None,
                    "mean_score": _round(sum(scores) / len(scores)) if scores else None,
                    "max_score": _round(max(scores)) if scores else None,
                }
            )
    return rows


def _reference_issues(
    *,
    detections_in_image: int,
    detection_score: float,
    height_ratio: float | None,
    area_ratio: float | None,
) -> list[str]:
    issues = []
    if detections_in_image != 1:
        issues.append("not_exactly_one_face")
    if detection_score < 0.8:
        issues.append("low_detection_score")
    if height_ratio is not None and height_ratio < 0.15:
        issues.append("small_face_height")
    if area_ratio is not None and area_ratio < 0.02:
        issues.append("small_face_area")
    return issues


def _match_for_person(face: dict[str, Any], person_id: str | None) -> dict[str, Any] | None:
    if not person_id:
        return None
    for match in face.get("matches") or []:
        if match.get("person_id") == person_id:
            return match
    return None


def _is_subject_face(label: dict[str, Any] | None) -> bool:
    if not label:
        return False
    if not label.get("is_face", True):
        return False
    if "should_keep" in label:
        return bool(label["should_keep"])
    return bool(label.get("is_subject", False))


def _image_size(path: str) -> tuple[int, int] | None:
    image = cv.imread(path)
    if image is None:
        return None
    height, width = image.shape[:2]
    return width, height


def _print_summary(
    reference_rows: list[dict[str, Any]],
    subject_rows: list[dict[str, Any]],
    threshold: float,
    run_dir: Path,
) -> None:
    reference_issues = [row for row in reference_rows if row.get("issues")]
    with_reference = [row for row in subject_rows if row["has_reference"]]
    accepted = [row for row in with_reference if row["status"] == "accepted"]
    missed = [row for row in with_reference if row["status"] == "missed"]
    print(f"Match threshold: {threshold:.3f}")
    print(f"Reference embeddings: {len(reference_rows)}")
    print(f"Reference rows with issues: {len(reference_issues)}")
    print(
        "Subject faces with references: "
        f"{len(with_reference)}; accepted {len(accepted)}; missed {len(missed)}"
    )
    if missed:
        print(f"Missed subject faces: {len(missed)}")
    print()
    print(f"Wrote: {run_dir / 'reference_image_diagnostics.csv'}")
    print(f"Wrote: {run_dir / 'reference_subject_diagnostics.csv'}")
    print(f"Wrote: {run_dir / 'reference_score_details.csv'}")
    print(f"Wrote: {run_dir / 'reference_subject_slices.csv'}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _slice_key(fields: list[str], values: tuple[Any, ...]) -> str:
    if not fields:
        return "all"
    return ";".join(
        f"{field}={value if value is not None else ''}"
        for field, value in zip(fields, values, strict=True)
    )


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


if __name__ == "__main__":
    raise SystemExit(main())
