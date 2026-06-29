"""Compare quality-lab runs produced by different recognition backends."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from quality_lab_metrics import evaluate  # noqa: E402


DEFAULT_DATA_DIR = Path("quality_lab/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare quality lab runs.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--runs",
        nargs="*",
        default=None,
        help="Run ids to compare. Defaults to every run with predictions.json.",
    )
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        help="Override each run's matching threshold.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional CSV output path. Defaults to quality_lab/data/model_comparison.csv.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels = _read_json(args.data_dir / "labels.json")
    run_ids = args.runs or _discover_runs(args.data_dir)
    rows = []
    for run_id in run_ids:
        predictions_path = args.data_dir / "runs" / run_id / "predictions.json"
        if not predictions_path.is_file():
            print(f"Skipping {run_id}: missing {predictions_path}")
            continue
        predictions = _read_json(predictions_path)
        threshold = (
            args.match_threshold
            if args.match_threshold is not None
            else float(predictions.get("match_threshold", 0.45))
        )
        report = evaluate(labels, predictions, threshold)
        rows.append(_build_row(run_id, predictions, report["summary"], report["reference_rows"]))

    output_path = args.output or args.data_dir / "model_comparison.csv"
    _write_csv(output_path, rows)
    _print_rows(rows)
    print()
    print(f"Wrote: {output_path}")
    return 0


def _discover_runs(data_dir: Path) -> list[str]:
    runs_dir = data_dir / "runs"
    if not runs_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in runs_dir.iterdir()
        if (path / "predictions.json").is_file()
    )


def _build_row(
    run_id: str,
    predictions: dict[str, Any],
    summary: dict[str, Any],
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    recognizer = predictions.get("recognizer") or {"name": "sface"}
    recognition = summary["recognition"]
    distribution = summary["distribution"]
    detection = summary["detection"]
    scores = [
        float(row["expected_score"])
        for row in reference_rows
        if row.get("has_reference") and row.get("expected_score") is not None
    ]
    missed = [
        row
        for row in reference_rows
        if row.get("has_reference") and row.get("status") == "missed"
    ]
    return {
        "run_id": run_id,
        "recognizer": recognizer.get("name"),
        "model": recognizer.get("model") or recognizer.get("sface") or "",
        "device": recognizer.get("device") or "",
        "derived_refs": (predictions.get("derived_enrollment") or {}).get(
            "selected_count",
            0,
        ),
        "match_threshold": summary["match_threshold"],
        "reference_people": ",".join(summary["reference_people"]),
        "predicted_faces": summary["dataset"]["predicted_faces"],
        "false_nonface_detections": detection["false_nonface_detections"],
        "background_real_faces": detection["background_real_faces"],
        "known_subject_faces": recognition["reference_person_faces"],
        "known_recall": recognition["reference_person_recall"],
        "accepted_precision": recognition["face_accept_precision"],
        "recipient_precision": distribution["recipient_precision"],
        "recipient_recall": distribution["recipient_recall"],
        "recipient_f1": distribution["recipient_f1"],
        "false_recipients": distribution["false_recipients"],
        "missed_recipients": distribution["missed_recipients"],
        "noise_false_accepts": recognition["noise_false_accepts"],
        "non_reference_false_accepts": recognition["non_reference_false_accepts"],
        "same_person_min_score": _safe_min(scores),
        "same_person_mean_score": _safe_mean(scores),
        "same_person_max_score": _safe_max(scores),
        "missed_cases": "; ".join(
            f"{row['image_id']}:{row['expected_score']}" for row in missed
        ),
    }


def _print_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No runs to compare.")
        return
    columns = [
        "run_id",
        "recognizer",
        "device",
        "derived_refs",
        "known_recall",
        "accepted_precision",
        "recipient_f1",
        "false_recipients",
        "missed_recipients",
        "same_person_mean_score",
    ]
    widths = {
        column: max(len(column), *(len(_format(row.get(column))) for row in rows))
        for column in columns
    }
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in rows:
        print(
            " | ".join(
                _format(row.get(column)).ljust(widths[column])
                for column in columns
            )
        )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _format(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return ""
    return str(value)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_min(values: list[float]) -> float | None:
    if not values:
        return None
    return min(values)


def _safe_max(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values)


if __name__ == "__main__":
    raise SystemExit(main())
