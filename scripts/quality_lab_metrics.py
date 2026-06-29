"""Evaluate a quality lab run against manual labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2 as cv


DEFAULT_DATA_DIR = Path("quality_lab/data")
DEFAULT_SWEEP_START = 0.0
DEFAULT_SWEEP_STOP = 1.0
DEFAULT_SWEEP_STEP = 0.05


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate quality lab metrics.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        help="Override the run's matching threshold.",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="Comma-separated thresholds for the sweep, for example 0.35,0.4,0.45.",
    )
    parser.add_argument("--sweep-start", type=float, default=DEFAULT_SWEEP_START)
    parser.add_argument("--sweep-stop", type=float, default=DEFAULT_SWEEP_STOP)
    parser.add_argument("--sweep-step", type=float, default=DEFAULT_SWEEP_STEP)
    parser.add_argument(
        "--label-iou-threshold",
        type=float,
        default=0.4,
        help="Use bbox IoU to match labels when exact face ids are unavailable.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print metrics without writing report files.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels_path = args.data_dir / "labels.json"
    predictions_path = args.data_dir / "runs" / args.run_id / "predictions.json"
    labels = _read_json(labels_path)
    predictions = _read_json(predictions_path)
    threshold = (
        args.match_threshold
        if args.match_threshold is not None
        else float(predictions.get("match_threshold", 0.45))
    )

    report = evaluate(labels, predictions, threshold, label_iou_threshold=args.label_iou_threshold)
    sweep = [
        evaluate(labels, predictions, item, label_iou_threshold=args.label_iou_threshold)["summary"]
        for item in _build_thresholds(args, threshold)
    ]

    run_dir = predictions_path.parent
    if not args.no_write:
        _write_json(run_dir / "metrics.json", report["summary"])
        _write_csv(run_dir / "face_decisions.csv", report["face_rows"])
        _write_csv(run_dir / "photo_decisions.csv", report["photo_rows"])
        _write_csv(run_dir / "reference_cases.csv", report["reference_rows"])
        _write_csv(
            run_dir / "reference_slices.csv",
            _build_reference_slices(report["reference_rows"]),
        )
        _write_threshold_sweep(run_dir / "threshold_sweep.csv", sweep)

    _print_summary(report["summary"], run_dir, write_files=not args.no_write)
    return 0


def evaluate(
    labels: dict[str, Any],
    predictions: dict[str, Any],
    match_threshold: float,
    *,
    label_iou_threshold: float = 0.4,
) -> dict[str, Any]:
    references = {
        person_id
        for person_id, count in predictions.get("references", {}).items()
        if count
    }
    counters: Counter[str] = Counter()
    face_rows: list[dict[str, Any]] = []
    photo_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    image_size_cache: dict[str, tuple[int, int] | None] = {}

    images = predictions.get("images", {})
    labels_by_image = labels.get("images", {})
    counters["images_total"] = len(images)
    counters["labeled_images"] = sum(
        1 for image in labels_by_image.values() if image.get("faces")
    )

    for image_id, image_prediction in images.items():
        image_label = labels_by_image.get(image_id, {})
        face_labels = image_label.get("faces", {})
        used_label_ids: set[str] = set()
        photo_subjects = set(image_label.get("photo_subjects", []))
        expected_actionable = photo_subjects & references
        expected_unavailable = photo_subjects - references
        predicted_recipients: set[str] = set()
        true_subjects_seen: set[str] = set()

        image_path = str(image_prediction.get("path", ""))
        image_size = _image_size(image_path, image_size_cache)
        for face in image_prediction.get("faces", []):
            counters["predicted_faces"] += 1
            face_id = face["face_id"]
            label_id, label = _match_label(
                face_id=face_id,
                face=face,
                face_labels=face_labels,
                used_label_ids=used_label_ids,
                iou_threshold=label_iou_threshold,
            )
            if label_id:
                used_label_ids.add(label_id)
            predicted_person, best_score = _predicted_person(face, match_threshold)
            if predicted_person is not None:
                predicted_recipients.add(predicted_person)

            row = _build_face_row(
                image_id=image_id,
                face=face,
                label_id=label_id,
                label=label,
                references=references,
                predicted_person=predicted_person,
                best_score=best_score,
                image_size=image_size,
            )
            face_rows.append(row)

            if label is None:
                counters["unlabeled_predicted_faces"] += 1
                continue

            counters["labeled_faces"] += 1
            is_face = bool(label.get("is_face", True))
            person_id = label.get("person_id")
            is_subject = bool(label.get("is_subject", False))
            should_keep = _should_keep(label)
            if person_id and is_subject and should_keep:
                reference_rows.append(
                    _build_reference_row(
                        face_row=row,
                        label=label,
                        references=references,
                        match_threshold=match_threshold,
                    )
                )

            if is_face:
                counters["real_faces"] += 1
            else:
                counters["false_nonface_detections"] += 1

            if is_face and should_keep:
                counters["distribution_relevant_faces"] += 1
                if person_id:
                    true_subjects_seen.add(person_id)
            elif is_face:
                counters["background_real_faces"] += 1
            else:
                counters["nonface_noise"] += 1

            if predicted_person is not None:
                counters["accepted_faces"] += 1

            if is_face and should_keep and person_id in references:
                counters["reference_person_faces"] += 1
                if predicted_person == person_id:
                    counters["reference_person_correct"] += 1
                    counters["accepted_correct"] += 1
                elif predicted_person is None:
                    counters["reference_person_missed"] += 1
                else:
                    counters["reference_person_wrong"] += 1
            elif is_face and should_keep and person_id:
                counters["non_reference_subject_faces"] += 1
                if predicted_person is None:
                    counters["non_reference_rejections"] += 1
                else:
                    counters["non_reference_false_accepts"] += 1
            else:
                counters["noise_faces"] += 1
                if predicted_person is None:
                    counters["noise_rejections"] += 1
                else:
                    counters["noise_false_accepts"] += 1

        counters["photo_subject_pairs"] += len(photo_subjects)
        counters["photo_subject_pairs_with_references"] += len(expected_actionable)
        counters["photo_subject_pairs_without_references"] += len(expected_unavailable)
        counters["photo_subject_pairs_seen"] += len(photo_subjects & true_subjects_seen)
        counters["photo_subject_pairs_missing_labels"] += len(
            photo_subjects - true_subjects_seen
        )

        true_recipients = predicted_recipients & expected_actionable
        false_recipients = predicted_recipients - expected_actionable
        missed_recipients = expected_actionable - predicted_recipients
        expected_quarantine = not expected_actionable
        predicted_quarantine = not predicted_recipients

        counters["photo_true_recipients"] += len(true_recipients)
        counters["photo_false_recipients"] += len(false_recipients)
        counters["photo_missed_recipients"] += len(missed_recipients)
        if not false_recipients and not missed_recipients:
            counters["photo_exact"] += 1
        if expected_quarantine == predicted_quarantine:
            counters["quarantine_correct"] += 1

        photo_rows.append(
            {
                "image_id": image_id,
                "expected_recipients_with_refs": _join(expected_actionable),
                "expected_subjects_without_refs": _join(expected_unavailable),
                "predicted_recipients": _join(predicted_recipients),
                "true_recipients": _join(true_recipients),
                "false_recipients": _join(false_recipients),
                "missed_recipients": _join(missed_recipients),
                "expected_quarantine": expected_quarantine,
                "predicted_quarantine": predicted_quarantine,
                "exact": not false_recipients and not missed_recipients,
            }
        )

    summary = _build_summary(
        counters=counters,
        labels=labels,
        predictions=predictions,
        references=references,
        match_threshold=match_threshold,
    )
    return {
        "summary": summary,
        "face_rows": face_rows,
        "photo_rows": photo_rows,
        "reference_rows": reference_rows,
    }


def _build_summary(
    counters: Counter[str],
    labels: dict[str, Any],
    predictions: dict[str, Any],
    references: set[str],
    match_threshold: float,
) -> dict[str, Any]:
    labeled_people = sorted(labels.get("people", {}).keys())
    accepted_wrong = counters["accepted_faces"] - counters["accepted_correct"]
    photo_recipient_precision = _safe_div(
        counters["photo_true_recipients"],
        counters["photo_true_recipients"] + counters["photo_false_recipients"],
    )
    photo_recipient_recall = _safe_div(
        counters["photo_true_recipients"],
        counters["photo_true_recipients"] + counters["photo_missed_recipients"],
    )

    return {
        "run_id": predictions.get("run_id"),
        "match_threshold": match_threshold,
        "detection_score_threshold": predictions.get("score_threshold"),
        "reference_people": sorted(references),
        "labeled_people": labeled_people,
        "people_without_references": sorted(set(labeled_people) - references),
        "dataset": {
            "images_total": counters["images_total"],
            "labeled_images": counters["labeled_images"],
            "predicted_faces": counters["predicted_faces"],
            "labeled_faces": counters["labeled_faces"],
            "unlabeled_predicted_faces": counters["unlabeled_predicted_faces"],
        },
        "detection": {
            "real_faces": counters["real_faces"],
            "false_nonface_detections": counters["false_nonface_detections"],
            "background_real_faces": counters["background_real_faces"],
            "distribution_relevant_faces": counters["distribution_relevant_faces"],
            "false_nonface_rate": _safe_div(
                counters["false_nonface_detections"],
                counters["labeled_faces"],
            ),
            "background_real_face_rate": _safe_div(
                counters["background_real_faces"],
                counters["labeled_faces"],
            ),
            "relevant_face_rate": _safe_div(
                counters["distribution_relevant_faces"],
                counters["labeled_faces"],
            ),
            "subject_label_coverage": _safe_div(
                counters["photo_subject_pairs_seen"],
                counters["photo_subject_pairs"],
            ),
            "subject_pairs_missing_labels": counters[
                "photo_subject_pairs_missing_labels"
            ],
        },
        "recognition": {
            "reference_person_faces": counters["reference_person_faces"],
            "reference_person_correct": counters["reference_person_correct"],
            "reference_person_missed": counters["reference_person_missed"],
            "reference_person_wrong": counters["reference_person_wrong"],
            "reference_person_recall": _safe_div(
                counters["reference_person_correct"],
                counters["reference_person_faces"],
            ),
            "accepted_faces": counters["accepted_faces"],
            "accepted_correct": counters["accepted_correct"],
            "accepted_wrong": accepted_wrong,
            "face_accept_precision": _safe_div(
                counters["accepted_correct"],
                counters["accepted_faces"],
            ),
            "non_reference_subject_faces": counters["non_reference_subject_faces"],
            "non_reference_rejections": counters["non_reference_rejections"],
            "non_reference_false_accepts": counters["non_reference_false_accepts"],
            "non_reference_rejection_rate": _safe_div(
                counters["non_reference_rejections"],
                counters["non_reference_subject_faces"],
            ),
            "noise_faces": counters["noise_faces"],
            "noise_rejections": counters["noise_rejections"],
            "noise_false_accepts": counters["noise_false_accepts"],
            "noise_rejection_rate": _safe_div(
                counters["noise_rejections"],
                counters["noise_faces"],
            ),
        },
        "distribution": {
            "photos_total": counters["images_total"],
            "photo_exact": counters["photo_exact"],
            "photo_exact_rate": _safe_div(
                counters["photo_exact"],
                counters["images_total"],
            ),
            "true_recipients": counters["photo_true_recipients"],
            "false_recipients": counters["photo_false_recipients"],
            "missed_recipients": counters["photo_missed_recipients"],
            "recipient_precision": photo_recipient_precision,
            "recipient_recall": photo_recipient_recall,
            "recipient_f1": _f1(photo_recipient_precision, photo_recipient_recall),
            "quarantine_correct": counters["quarantine_correct"],
            "quarantine_accuracy": _safe_div(
                counters["quarantine_correct"],
                counters["images_total"],
            ),
            "subject_pairs_with_references": counters[
                "photo_subject_pairs_with_references"
            ],
            "subject_pairs_without_references": counters[
                "photo_subject_pairs_without_references"
            ],
        },
    }


def _build_face_row(
    image_id: str,
    face: dict[str, Any],
    label_id: str | None,
    label: dict[str, Any] | None,
    references: set[str],
    predicted_person: str | None,
    best_score: float,
    image_size: tuple[int, int] | None,
) -> dict[str, Any]:
    detection = face.get("detection", {})
    box = detection.get("box", {})
    expected_person = label.get("person_id") if label else None
    is_face = label.get("is_face") if label else None
    is_subject = label.get("is_subject") if label else None
    should_keep = _should_keep(label) if label else None
    expected_score = _score_for_person(face, expected_person)
    outcome = _face_outcome(
        label=label,
        references=references,
        predicted_person=predicted_person,
    )

    width = float(box.get("width") or 0.0)
    height = float(box.get("height") or 0.0)
    image_width = image_size[0] if image_size else None
    image_height = image_size[1] if image_size else None
    area_ratio = None
    height_ratio = None
    if image_width and image_height:
        area_ratio = width * height / (image_width * image_height)
        height_ratio = height / image_height

    return {
        "image_id": image_id,
        "face_id": face.get("face_id"),
        "label_id": label_id,
        "face_index": face.get("face_index"),
        "outcome": outcome,
        "expected_person": expected_person,
        "predicted_person": predicted_person,
        "best_score": _round(best_score),
        "expected_score": _round(expected_score),
        "has_reference": expected_person in references if expected_person else False,
        "is_face": is_face,
        "is_subject": is_subject,
        "should_keep": should_keep,
        "quality": label.get("quality") if label else None,
        "occlusion": label.get("occlusion") if label else None,
        "pose": label.get("pose") if label else None,
        "detection_score": _round(detection.get("score")),
        "box_width": _round(width),
        "box_height": _round(height),
        "box_area_ratio": _round(area_ratio),
        "box_height_ratio": _round(height_ratio),
        "notes": label.get("notes") if label else "",
    }


def _match_label(
    *,
    face_id: str,
    face: dict[str, Any],
    face_labels: dict[str, dict[str, Any]],
    used_label_ids: set[str],
    iou_threshold: float,
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

    if best_label_id is not None and best_iou >= iou_threshold:
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
    intersection_width = max(0.0, intersection_x2 - intersection_x1)
    intersection_height = max(0.0, intersection_y2 - intersection_y1)
    intersection_area = intersection_width * intersection_height
    left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
    right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
    union_area = left_area + right_area - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _build_reference_row(
    face_row: dict[str, Any],
    label: dict[str, Any],
    references: set[str],
    match_threshold: float,
) -> dict[str, Any]:
    expected_score = face_row["expected_score"]
    has_reference = bool(face_row["has_reference"])
    accepted_as_expected = face_row["outcome"] == "correct"
    gap_to_threshold = None
    if expected_score is not None:
        gap_to_threshold = round(expected_score - match_threshold, 6)
    if not has_reference:
        status = "no_reference"
    elif accepted_as_expected:
        status = "accepted"
    else:
        status = "missed"

    return {
        "image_id": face_row["image_id"],
        "face_id": face_row["face_id"],
        "person_id": face_row["expected_person"],
        "has_reference": has_reference,
        "status": status,
        "outcome": face_row["outcome"],
        "predicted_person": face_row["predicted_person"],
        "match_threshold": match_threshold,
        "expected_score": expected_score,
        "best_score": face_row["best_score"],
        "gap_to_threshold": gap_to_threshold,
        "quality": face_row["quality"],
        "occlusion": face_row["occlusion"],
        "pose": face_row["pose"],
        "box_height_ratio": face_row["box_height_ratio"],
        "detection_score": face_row["detection_score"],
        "notes": label.get("notes", ""),
    }


def _build_reference_slices(reference_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("all", []),
        ("person", ["person_id"]),
        ("occlusion", ["occlusion"]),
        ("pose", ["pose"]),
        ("quality", ["quality"]),
        ("person_occlusion", ["person_id", "occlusion"]),
        ("person_pose", ["person_id", "pose"]),
        ("person_quality", ["person_id", "quality"]),
    ]
    rows: list[dict[str, Any]] = []
    for slice_name, fields in specs:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in reference_rows:
            key = tuple(row.get(field) for field in fields)
            groups.setdefault(key, []).append(row)

        for key, items in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
            with_reference = [item for item in items if item["has_reference"]]
            scores = [
                float(item["expected_score"])
                for item in with_reference
                if item["expected_score"] is not None
            ]
            accepted = sum(1 for item in with_reference if item["status"] == "accepted")
            missed = sum(1 for item in with_reference if item["status"] == "missed")
            rows.append(
                {
                    "slice": slice_name,
                    "key": _slice_key(fields, key),
                    "subject_faces": len(items),
                    "with_reference": len(with_reference),
                    "without_reference": len(items) - len(with_reference),
                    "accepted": accepted,
                    "missed": missed,
                    "reference_recall": _safe_div(accepted, len(with_reference)),
                    "min_expected_score": _round(min(scores)) if scores else None,
                    "mean_expected_score": _round(sum(scores) / len(scores)) if scores else None,
                    "max_expected_score": _round(max(scores)) if scores else None,
                }
            )
    return rows


def _slice_key(fields: list[str], values: tuple[Any, ...]) -> str:
    if not fields:
        return "all"
    return ";".join(
        f"{field}={value if value is not None else ''}"
        for field, value in zip(fields, values, strict=True)
    )


def _face_outcome(
    label: dict[str, Any] | None,
    references: set[str],
    predicted_person: str | None,
) -> str:
    if label is None:
        return "unlabeled_prediction"
    is_face = bool(label.get("is_face", True))
    should_keep = _should_keep(label)
    expected_person = label.get("person_id")

    if not is_face:
        return "false_accept_nonface" if predicted_person else "rejected_nonface"
    if not should_keep:
        return "false_accept_irrelevant" if predicted_person else "rejected_irrelevant"
    if not expected_person:
        return "accepted_unknown" if predicted_person else "rejected_unknown"
    if expected_person not in references:
        return (
            "false_accept_no_reference"
            if predicted_person
            else "rejected_no_reference"
        )
    if predicted_person == expected_person:
        return "correct"
    if predicted_person is None:
        return "missed_known_person"
    return "wrong_identity"


def _predicted_person(face: dict[str, Any], threshold: float) -> tuple[str | None, float]:
    best_match = face.get("best_match") or {}
    score = float(best_match.get("score") or 0.0)
    person_id = best_match.get("person_id")
    if person_id and score >= threshold:
        return str(person_id), score
    return None, score


def _score_for_person(face: dict[str, Any], person_id: str | None) -> float | None:
    if not person_id:
        return None
    for match in face.get("matches") or []:
        if match.get("person_id") == person_id:
            return float(match.get("score") or 0.0)
    return None


def _should_keep(label: dict[str, Any]) -> bool:
    if "should_keep" in label:
        return bool(label["should_keep"])
    return bool(label.get("is_face", True)) and bool(label.get("is_subject", False))


def _image_size(
    path: str,
    cache: dict[str, tuple[int, int] | None],
) -> tuple[int, int] | None:
    if path in cache:
        return cache[path]
    image = cv.imread(path)
    if image is None:
        cache[path] = None
        return None
    height, width = image.shape[:2]
    cache[path] = (width, height)
    return cache[path]


def _build_thresholds(args: argparse.Namespace, default_threshold: float) -> list[float]:
    if args.thresholds:
        result = sorted({round(float(item.strip()), 6) for item in args.thresholds.split(",")})
        return result

    values = {round(default_threshold, 6)}
    current = args.sweep_start
    while current <= args.sweep_stop + args.sweep_step / 10:
        values.add(round(current, 6))
        current += args.sweep_step
    return sorted(values)


def _write_threshold_sweep(path: Path, summaries: list[dict[str, Any]]) -> None:
    rows = []
    for summary in summaries:
        recognition = summary["recognition"]
        distribution = summary["distribution"]
        rows.append(
            {
                "match_threshold": summary["match_threshold"],
                "reference_person_recall": recognition["reference_person_recall"],
                "face_accept_precision": recognition["face_accept_precision"],
                "non_reference_false_accepts": recognition[
                    "non_reference_false_accepts"
                ],
                "noise_false_accepts": recognition["noise_false_accepts"],
                "photo_exact_rate": distribution["photo_exact_rate"],
                "recipient_precision": distribution["recipient_precision"],
                "recipient_recall": distribution["recipient_recall"],
                "recipient_f1": distribution["recipient_f1"],
                "false_recipients": distribution["false_recipients"],
                "missed_recipients": distribution["missed_recipients"],
                "quarantine_accuracy": distribution["quarantine_accuracy"],
            }
        )
    _write_csv(path, rows)


def _print_summary(summary: dict[str, Any], run_dir: Path, write_files: bool) -> None:
    dataset = summary["dataset"]
    detection = summary["detection"]
    recognition = summary["recognition"]
    distribution = summary["distribution"]

    print(f"Run: {summary['run_id']}")
    print(f"Match threshold: {summary['match_threshold']:.3f}")
    print(f"Reference people: {len(summary['reference_people'])}")
    print(f"People without references: {len(summary['people_without_references'])}")
    print()
    print(
        "Dataset: "
        f"{dataset['labeled_images']}/{dataset['images_total']} labeled images, "
        f"{dataset['labeled_faces']}/{dataset['predicted_faces']} labeled faces"
    )
    print(
        "Detection: "
        f"{detection['distribution_relevant_faces']} relevant, "
        f"{detection['background_real_faces']} background faces, "
        f"{detection['false_nonface_detections']} non-face detections"
    )
    print(
        "Recognition: "
        f"known-person recall {recognition['reference_person_correct']}/"
        f"{recognition['reference_person_faces']} = "
        f"{_percent(recognition['reference_person_recall'])}; "
        f"accepted precision {_percent(recognition['face_accept_precision'])}"
    )
    print(
        "Distribution: "
        f"precision {_percent(distribution['recipient_precision'])}, "
        f"recall {_percent(distribution['recipient_recall'])}, "
        f"F1 {_percent(distribution['recipient_f1'])}, "
        f"exact photos {distribution['photo_exact']}/{distribution['photos_total']}"
    )
    if write_files:
        print()
        print(f"Wrote: {run_dir / 'metrics.json'}")
        print(f"Wrote: {run_dir / 'face_decisions.csv'}")
        print(f"Wrote: {run_dir / 'photo_decisions.csv'}")
        print(f"Wrote: {run_dir / 'reference_cases.csv'}")
        print(f"Wrote: {run_dir / 'reference_slices.csv'}")
        print(f"Wrote: {run_dir / 'threshold_sweep.csv'}")


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


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _join(values: set[str]) -> str:
    return ",".join(sorted(values))


if __name__ == "__main__":
    raise SystemExit(main())
