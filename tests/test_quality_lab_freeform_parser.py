"""Tests for freeform quality-lab labeling parser."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from quality_lab_parse_freeform_labels import parse_freeform_labels  # noqa: E402
from quality_lab_prepare_labeling_session import select_labeling_session_images  # noqa: E402
from quality_lab_merge_freeform_labels import merge_parsed_labels  # noqa: E402
from quality_lab_report import print_report  # noqa: E402
from quality_lab_start_labeling import build_parser, run_labeling_pipeline  # noqa: E402


def test_print_report_aligns_quality_lab_summary_rows(capsys) -> None:
    print_report(
        "Freeform labels parsed",
        [
            ("Images", 2),
            ("Faces", 3),
        ],
    )

    assert capsys.readouterr().out == (
        "Freeform labels parsed\n"
        "Images: 2\n"
        "Faces : 3\n"
    )


def test_start_labeling_pipeline_runs_predictions_then_prepares_session(tmp_path: Path) -> None:
    commands = []
    args = build_parser().parse_args(
        [
            "--data-dir",
            str(tmp_path),
            "--run-id",
            "run_1",
            "--session-id",
            "session_1",
            "--limit",
            "5",
            "--unlabeled-only",
        ]
    )

    result = run_labeling_pipeline(args, run_command=lambda command, check: commands.append(command))

    assert result.run_id == "run_1"
    assert result.session_id == "session_1"
    assert result.predictions_path == tmp_path / "runs" / "run_1" / "predictions.json"
    assert result.freeform_labels_path == tmp_path / "labeling_sessions" / "session_1" / "freeform_labels.md"
    assert len(commands) == 2
    assert "quality_lab_run.py" in commands[0][1]
    assert "quality_lab_prepare_labeling_session.py" in commands[1][1]
    assert "--limit" in commands[1]
    assert "--unlabeled-only" in commands[1]


def test_start_labeling_pipeline_can_prepare_accepted_only_session(tmp_path: Path) -> None:
    commands = []
    args = build_parser().parse_args(
        [
            "--data-dir",
            str(tmp_path),
            "--run-id",
            "run_1",
            "--skip-run",
            "--accepted-only",
            "--match-threshold",
            "0.18",
        ]
    )

    run_labeling_pipeline(args, run_command=lambda command, check: commands.append(command))

    assert len(commands) == 1
    assert "--accepted-only" in commands[0]
    assert "--match-threshold" in commands[0]
    assert "0.18" in commands[0]


def test_select_labeling_session_images_can_focus_on_unlabeled_accepted_faces() -> None:
    predictions = {
        "images": {
            "accepted_unlabeled": {
                "faces": [
                    {
                        "face_id": "accepted_unlabeled:face1",
                        "best_match": {"person_id": "pavel", "score": 0.19},
                    }
                ]
            },
            "accepted_labeled": {
                "faces": [
                    {
                        "face_id": "accepted_labeled:face1",
                        "best_match": {"person_id": "pavel", "score": 0.2},
                    }
                ]
            },
            "rejected_unlabeled": {
                "faces": [
                    {
                        "face_id": "rejected_unlabeled:face1",
                        "best_match": {"person_id": "pavel", "score": 0.17},
                    }
                ]
            },
        }
    }
    labels = {
        "images": {
            "accepted_labeled": {
                "faces": {
                    "accepted_labeled:face1": {
                        "is_face": True,
                        "person_id": "pavel",
                    }
                }
            }
        }
    }

    selected = select_labeling_session_images(
        predictions=predictions,
        labels=labels,
        unlabeled_only=True,
        accepted_only=True,
        match_threshold=0.18,
        limit=None,
    )

    assert [image_id for image_id, _ in selected] == ["accepted_unlabeled"]


def test_select_labeling_session_images_can_follow_image_id_order() -> None:
    predictions = {
        "images": {
            "medium_risk": {"faces": []},
            "high_risk": {"faces": []},
            "unused": {"faces": []},
        }
    }
    labels = {"images": {}}

    selected = select_labeling_session_images(
        predictions=predictions,
        labels=labels,
        unlabeled_only=False,
        accepted_only=False,
        match_threshold=0.18,
        image_ids=["high_risk", "missing", "medium_risk"],
    )

    assert [image_id for image_id, _ in selected] == ["high_risk", "medium_risk"]


def test_start_labeling_pipeline_can_reuse_existing_predictions(tmp_path: Path) -> None:
    commands = []
    args = build_parser().parse_args(
        [
            "--data-dir",
            str(tmp_path),
            "--run-id",
            "run_1",
            "--skip-run",
        ]
    )

    run_labeling_pipeline(args, run_command=lambda command, check: commands.append(command))

    assert len(commands) == 1
    assert "quality_lab_prepare_labeling_session.py" in commands[0][1]


def test_parse_freeform_labels_maps_face_labels_to_stable_face_ids() -> None:
    manifest = {
        "session_id": "session_1",
        "run_id": "run_1",
        "images": [
            {
                "image_id": "photo_1",
                "faces": [
                    {"face_label": "face1", "face_id": "photo_1:face1"},
                    {"face_label": "face2", "face_id": "photo_1:face2"},
                ],
            }
        ],
    }
    markdown = """
## photo_1

```text
photo_subjects = person_a, person_b
face1 = person_a, good, frontal, glasses
face2 = background/not_face
notes = keep this group photo
```
"""

    parsed = parse_freeform_labels(markdown, manifest)

    image = parsed["images"]["photo_1"]
    assert image["photo_subjects"] == ["person_a", "person_b"]
    assert image["notes"] == "keep this group photo"
    assert image["faces"]["photo_1:face1"]["person_id"] == "person_a"
    assert image["faces"]["photo_1:face1"]["is_face"] is True
    assert image["faces"]["photo_1:face1"]["quality"] == "good"
    assert image["faces"]["photo_1:face1"]["pose"] == "frontal"
    assert image["faces"]["photo_1:face1"]["occlusion"] == "glasses"
    assert image["faces"]["photo_1:face2"]["is_face"] is False
    assert image["faces"]["photo_1:face2"]["person_id"] is None


def test_merge_parsed_labels_adds_missing_labels_without_overwriting_existing() -> None:
    labels = {
        "people": {"person_a": {"display_name": "Person A"}},
        "images": {
            "photo_1": {
                "path": "quality_lab/data/images/photo_1.jpg",
                "photo_subjects": [],
                "notes": "",
                "faces": {
                    "photo_1:face1": {
                        "is_face": True,
                        "person_id": "person_a",
                        "is_subject": True,
                        "quality": "good",
                    }
                },
            }
        },
    }
    parsed = {
        "images": {
            "photo_1": {
                "photo_subjects": ["person_b"],
                "notes": "new note",
                "faces": {
                    "photo_1:face1": {
                        "is_face": True,
                        "person_id": "person_b",
                        "is_subject": True,
                        "quality": "ok",
                    },
                    "photo_1:face2": {
                        "is_face": False,
                        "person_id": None,
                        "is_subject": False,
                        "raw": "background/not_face",
                    },
                },
            }
        }
    }

    summary = merge_parsed_labels(labels, parsed)

    image = labels["images"]["photo_1"]
    assert image["photo_subjects"] == ["person_b"]
    assert image["notes"] == "new note"
    assert image["faces"]["photo_1:face1"]["person_id"] == "person_a"
    assert image["faces"]["photo_1:face2"]["is_face"] is False
    assert image["faces"]["photo_1:face2"]["notes"] == ""
    assert labels["people"]["person_b"]["display_name"] == "person_b"
    assert summary["face_labels_added"] == 1
    assert summary["face_labels_skipped"] == 1
    assert summary["people_added"] == 1


def test_merge_parsed_labels_can_overwrite_existing_labels() -> None:
    labels = {
        "people": {},
        "images": {
            "photo_1": {
                "path": "quality_lab/data/images/photo_1.jpg",
                "photo_subjects": ["person_a"],
                "notes": "old note",
                "faces": {
                    "photo_1:face1": {
                        "is_face": True,
                        "person_id": "person_a",
                        "is_subject": True,
                    }
                },
            }
        },
    }
    parsed = {
        "images": {
            "photo_1": {
                "photo_subjects": ["person_b"],
                "notes": "new note",
                "faces": {
                    "photo_1:face1": {
                        "is_face": True,
                        "person_id": "person_b",
                        "is_subject": True,
                    }
                },
            }
        }
    }

    summary = merge_parsed_labels(labels, parsed, overwrite=True)

    image = labels["images"]["photo_1"]
    assert image["photo_subjects"] == ["person_b"]
    assert image["notes"] == "new note"
    assert image["faces"]["photo_1:face1"]["person_id"] == "person_b"
    assert labels["people"]["person_b"]["display_name"] == "person_b"
    assert summary["face_labels_updated"] == 1
