"""Build a second-pass quality-lab run with derived references."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2 as cv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from photo_distribution.workflow import cosine_similarity  # noqa: E402


DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a derived-reference second-pass quality lab run."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--min-score", type=float, default=0.65)
    parser.add_argument("--min-margin", type=float, default=0.0)
    parser.add_argument("--min-detection-score", type=float, default=0.8)
    parser.add_argument("--min-box-height-ratio", type=float, default=0.12)
    parser.add_argument("--min-box-area-ratio", type=float, default=0.01)
    parser.add_argument("--max-per-person", type=int, default=3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_run_dir = args.data_dir / "runs" / args.source_run_id
    labels = _read_json(args.data_dir / "labels.json")
    source_predictions = _read_json(source_run_dir / "predictions.json")

    run_id = args.run_id or f"{args.source_run_id}_derived_{_score_id(args.min_score)}"
    run_dir = args.data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    audit_rows, selected = _select_candidates(labels, source_predictions, args)
    selected = _limit_candidates(selected, args.max_per_person)
    selected_ids = {candidate["derived_reference_id"] for candidate in selected}
    for row in audit_rows:
        if row["selected"] and row["derived_reference_id"] not in selected_ids:
            row["selected"] = False
            row["reject_reason"] = "max_per_person"

    derived_predictions = _build_derived_predictions(
        source_predictions=source_predictions,
        source_run_id=args.source_run_id,
        run_id=run_id,
        selected=selected,
        args=args,
    )

    _write_json(run_dir / "predictions.json", derived_predictions)
    _write_csv(run_dir / "derived_reference_selection_audit.csv", audit_rows)
    _write_csv(
        run_dir / "derived_reference_candidates.csv",
        [_public_candidate(candidate) for candidate in selected],
    )

    _print_summary(run_dir, audit_rows, selected)
    return 0


def _select_candidates(
    labels: dict[str, Any],
    predictions: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit_rows = []
    selected = []
    images = predictions.get("images", {})
    label_images = labels.get("images", {})
    for image_id, image_prediction in images.items():
        image_label = label_images.get(image_id, {})
        face_labels = image_label.get("faces", {})
        image_size = _image_size(str(image_prediction.get("path", "")))
        used_label_ids: set[str] = set()

        for face in image_prediction.get("faces", []):
            label_id, label = _match_label(
                face_id=face["face_id"],
                face=face,
                face_labels=face_labels,
                used_label_ids=used_label_ids,
            )
            if label_id:
                used_label_ids.add(label_id)
            row = _candidate_audit_row(
                image_id=image_id,
                face=face,
                label_id=label_id,
                label=label,
                image_size=image_size,
                args=args,
            )
            audit_rows.append(row)
            if not row["selected"]:
                continue
            selected.append(
                {
                    **row,
                    "vector": tuple(float(value) for value in face["embedding"]),
                    "source_face_id": face["face_id"],
                    "source_image_id": image_id,
                }
            )

    return audit_rows, selected


def _candidate_audit_row(
    *,
    image_id: str,
    face: dict[str, Any],
    label_id: str | None,
    label: dict[str, Any] | None,
    image_size: tuple[int, int] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    best_match = face.get("best_match") or {}
    predicted_person = best_match.get("person_id")
    predicted_score = float(best_match.get("score") or 0.0)
    detection = face.get("detection") or {}
    detection_score = float(detection.get("score") or 0.0)
    box_height_ratio, box_area_ratio = _box_ratios(detection.get("box"), image_size)
    margin = _top_margin(face.get("matches") or [])
    expected_person = label.get("person_id") if label else None
    is_safe = (
        bool(label)
        and bool(label.get("is_face", True))
        and _should_keep(label)
        and expected_person == predicted_person
    )

    reject_reason = ""
    if not predicted_person:
        reject_reason = "no_predicted_person"
    elif predicted_score < args.min_score:
        reject_reason = "low_score"
    elif detection_score < args.min_detection_score:
        reject_reason = "low_detection_score"
    elif box_height_ratio is not None and box_height_ratio < args.min_box_height_ratio:
        reject_reason = "small_face_height"
    elif box_area_ratio is not None and box_area_ratio < args.min_box_area_ratio:
        reject_reason = "small_face_area"
    elif margin is not None and margin < args.min_margin:
        reject_reason = "low_margin"

    selected = reject_reason == ""
    derived_reference_id = f"derived:{image_id}:{face['face_index']}"
    return {
        "derived_reference_id": derived_reference_id,
        "image_id": image_id,
        "face_id": face["face_id"],
        "face_index": face["face_index"],
        "label_id": label_id,
        "predicted_person": predicted_person,
        "expected_person": expected_person,
        "predicted_score": round(predicted_score, 6),
        "margin": _round(margin),
        "detection_score": round(detection_score, 6),
        "box_height_ratio": _round(box_height_ratio),
        "box_area_ratio": _round(box_area_ratio),
        "quality": label.get("quality") if label else None,
        "occlusion": label.get("occlusion") if label else None,
        "pose": label.get("pose") if label else None,
        "is_safe_by_labels": is_safe,
        "selected": selected,
        "reject_reason": reject_reason,
    }


def _limit_candidates(
    candidates: list[dict[str, Any]],
    max_per_person: int,
) -> list[dict[str, Any]]:
    if max_per_person <= 0:
        return candidates

    result = []
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_person[str(candidate["predicted_person"])].append(candidate)
    for person_candidates in by_person.values():
        person_candidates.sort(key=lambda item: float(item["predicted_score"]), reverse=True)
        result.extend(person_candidates[:max_per_person])
    return sorted(result, key=lambda item: (str(item["predicted_person"]), -float(item["predicted_score"])))


def _build_derived_predictions(
    *,
    source_predictions: dict[str, Any],
    source_run_id: str,
    run_id: str,
    selected: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    derived = copy.deepcopy(source_predictions)
    derived["run_id"] = run_id
    derived["created_at"] = datetime.now(UTC).isoformat()
    derived["parent_run_id"] = source_run_id
    derived["derived_enrollment"] = {
        "source_run_id": source_run_id,
        "min_score": args.min_score,
        "min_margin": args.min_margin,
        "min_detection_score": args.min_detection_score,
        "min_box_height_ratio": args.min_box_height_ratio,
        "min_box_area_ratio": args.min_box_area_ratio,
        "max_per_person": args.max_per_person,
        "selected_count": len(selected),
    }

    selected_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in selected:
        selected_by_person[str(candidate["predicted_person"])].append(candidate)

    for person_id, candidates in selected_by_person.items():
        derived.setdefault("references", {})[person_id] = (
            int(derived.get("references", {}).get(person_id, 0)) + len(candidates)
        )
        public_records = derived.setdefault("reference_records", {}).setdefault(person_id, [])
        for candidate in candidates:
            public_records.append(_public_candidate(candidate))

    for image_prediction in derived.get("images", {}).values():
        for face in image_prediction.get("faces", []):
            _augment_face_matches(face, selected_by_person)
    return derived


def _augment_face_matches(
    face: dict[str, Any],
    selected_by_person: dict[str, list[dict[str, Any]]],
) -> None:
    face_vector = tuple(float(value) for value in face.get("embedding", []))
    matches = [copy.deepcopy(match) for match in face.get("matches", [])]
    matches_by_person = {match.get("person_id"): match for match in matches}

    for person_id, candidates in selected_by_person.items():
        match = matches_by_person.get(person_id)
        if match is None:
            match = {
                "person_id": person_id,
                "score": -1.0,
                "reference_id": None,
                "reference_path": None,
                "reference_scores": [],
            }
            matches_by_person[person_id] = match
            matches.append(match)

        reference_scores = list(match.get("reference_scores") or [])
        best_score = float(match.get("score") or -1.0)
        best_reference_id = match.get("reference_id")
        best_reference_path = match.get("reference_path")
        best_kind = match.get("reference_kind", "seed")

        for candidate in candidates:
            if candidate["source_face_id"] == face.get("face_id"):
                continue
            score = cosine_similarity(face_vector, candidate["vector"])
            reference_score = {
                "reference_id": candidate["derived_reference_id"],
                "reference_path": f"derived://{candidate['source_face_id']}",
                "reference_kind": "derived",
                "source_face_id": candidate["source_face_id"],
                "source_image_id": candidate["source_image_id"],
                "score": score,
            }
            reference_scores.append(reference_score)
            if score > best_score:
                best_score = score
                best_reference_id = candidate["derived_reference_id"]
                best_reference_path = reference_score["reference_path"]
                best_kind = "derived"

        reference_scores.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        match["score"] = best_score
        match["reference_id"] = best_reference_id
        match["reference_path"] = best_reference_path
        match["reference_kind"] = best_kind
        match["reference_scores"] = reference_scores

    matches.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    face["matches"] = matches
    face["best_match"] = matches[0] if matches else None


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_id": candidate["derived_reference_id"],
        "reference_kind": "derived",
        "person_id": candidate["predicted_person"],
        "source_image_id": candidate["source_image_id"],
        "source_face_id": candidate["source_face_id"],
        "score_when_selected": candidate["predicted_score"],
        "is_safe_by_labels": candidate["is_safe_by_labels"],
        "quality": candidate["quality"],
        "occlusion": candidate["occlusion"],
        "pose": candidate["pose"],
    }


def _match_label(
    *,
    face_id: str,
    face: dict[str, Any],
    face_labels: dict[str, dict[str, Any]],
    used_label_ids: set[str],
) -> tuple[str | None, dict[str, Any] | None]:
    if face_id in face_labels and face_id not in used_label_ids:
        return face_id, face_labels[face_id]

    prediction_box = face.get("detection", {}).get("box")
    if not prediction_box:
        return None, None

    best_label_id = None
    best_label = None
    best_iou = 0.0
    for label_id, label in face_labels.items():
        if label_id in used_label_ids:
            continue
        label_box = label.get("box")
        if not label_box:
            continue
        overlap = _box_iou(prediction_box, label_box)
        if overlap > best_iou:
            best_iou = overlap
            best_label_id = label_id
            best_label = label

    if best_iou >= 0.4:
        return best_label_id, best_label
    return None, None


def _box_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_x1 = float(left.get("x") or 0.0)
    left_y1 = float(left.get("y") or 0.0)
    left_x2 = left_x1 + float(left.get("width") or 0.0)
    left_y2 = left_y1 + float(left.get("height") or 0.0)
    right_x1 = float(right.get("x") or 0.0)
    right_y1 = float(right.get("y") or 0.0)
    right_x2 = right_x1 + float(right.get("width") or 0.0)
    right_y2 = right_y1 + float(right.get("height") or 0.0)
    intersection_x1 = max(left_x1, right_x1)
    intersection_y1 = max(left_y1, right_y1)
    intersection_x2 = min(left_x2, right_x2)
    intersection_y2 = min(left_y2, right_y2)
    intersection_area = max(0.0, intersection_x2 - intersection_x1) * max(
        0.0,
        intersection_y2 - intersection_y1,
    )
    left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
    right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
    union_area = left_area + right_area - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _box_ratios(
    box: dict[str, Any] | None,
    image_size: tuple[int, int] | None,
) -> tuple[float | None, float | None]:
    if not box or not image_size:
        return None, None
    image_width, image_height = image_size
    width = float(box.get("width") or 0.0)
    height = float(box.get("height") or 0.0)
    return height / image_height, width * height / (image_width * image_height)


def _top_margin(matches: list[dict[str, Any]]) -> float | None:
    if len(matches) < 2:
        return None
    scores = sorted((float(match.get("score") or 0.0) for match in matches), reverse=True)
    return scores[0] - scores[1]


def _should_keep(label: dict[str, Any]) -> bool:
    if "should_keep" in label:
        return bool(label["should_keep"])
    return bool(label.get("is_face", True)) and bool(label.get("is_subject", False))


def _image_size(path: str) -> tuple[int, int] | None:
    image = cv.imread(path)
    if image is None:
        return None
    height, width = image.shape[:2]
    return width, height


def _print_summary(
    run_dir: Path,
    audit_rows: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> None:
    selected_rows = [row for row in audit_rows if row["selected"]]
    risk_counts = Counter(str(candidate["is_safe_by_labels"]) for candidate in selected)
    print(f"Selected derived references: {len(selected)}")
    print(f"Selected before max-per-person limit: {len(selected_rows)}")
    print(f"Safe by labels: {risk_counts.get('True', 0)}")
    print(f"Unsafe/unknown by labels: {len(selected) - risk_counts.get('True', 0)}")
    print(f"Wrote: {run_dir / 'predictions.json'}")
    print(f"Wrote: {run_dir / 'derived_reference_selection_audit.csv'}")
    print(f"Wrote: {run_dir / 'derived_reference_candidates.csv'}")


def _score_id(score: float) -> str:
    return str(score).replace(".", "_")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


if __name__ == "__main__":
    raise SystemExit(main())
