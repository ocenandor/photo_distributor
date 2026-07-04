"""Tests for quality-lab metric evaluation."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from quality_lab_acceptance_audit import (  # noqa: E402
    accepted_match,
    box_iou,
    build_acceptance_audit_rows,
    center_distance,
    face_geometry_columns,
    face_area_ranks,
    high_medium_image_ids,
)
from quality_lab_apply_acceptance_policy import apply_comparison_other_veto  # noqa: E402
from quality_lab_apply_acceptance_policy import should_veto_small_low_score_face  # noqa: E402
from quality_lab_apply_acceptance_policy import should_veto_small_crowd_unconfirmed_face  # noqa: E402
from quality_lab_apply_acceptance_policy import should_veto_low_score_unconfirmed_face  # noqa: E402
from quality_lab_audit_contact_sheet import audit_caption, select_audit_rows  # noqa: E402
from quality_lab_consensus_audit import (  # noqa: E402
    build_consensus_rows,
    review_image_ids,
)
from quality_lab_metrics import evaluate  # noqa: E402
from quality_lab_person_risk_summary import build_person_risk_summary_rows  # noqa: E402
from quality_lab_policy_sweep import (  # noqa: E402
    best_safe_threshold,
    build_policy_sweep_rows,
    parse_thresholds,
)
from quality_lab_refresh_goal_reports import (  # noqa: E402
    RefreshConfig,
    build_refresh_commands,
    run_refresh_reports,
)
from quality_lab_review_pack import expanded_box, select_review_rows  # noqa: E402
from quality_lab_goal_audit import build_goal_audit_report  # noqa: E402
from quality_lab_candidate_resolutions import (  # noqa: E402
    apply_candidate_resolutions,
    build_resolution_template_rows,
)


def test_distribution_metrics_ignore_unlabeled_images() -> None:
    """Unlabeled photos are candidates for annotation, not false recipients."""

    labels = {
        "people": {"person_a": {"display_name": "Person A"}},
        "images": {
            "labeled_photo": {
                "photo_subjects": ["person_a"],
                "faces": {
                    "labeled_photo:face1": {
                        "is_face": True,
                        "person_id": "person_a",
                        "is_subject": True,
                        "quality": "good",
                    }
                },
            }
        },
    }
    predictions = {
        "run_id": "test_run",
        "references": {"person_a": 1},
        "images": {
            "labeled_photo": {
                "path": "missing_labeled_photo.jpg",
                "faces": [
                    {
                        "face_id": "labeled_photo:face1",
                        "best_match": {"person_id": "person_a", "score": 0.9},
                        "matches": [{"person_id": "person_a", "score": 0.9}],
                        "detection": {"box": {}, "score": 0.9},
                    }
                ],
            },
            "unlabeled_photo": {
                "path": "missing_unlabeled_photo.jpg",
                "faces": [
                    {
                        "face_id": "unlabeled_photo:face1",
                        "best_match": {"person_id": "person_a", "score": 0.95},
                        "matches": [{"person_id": "person_a", "score": 0.95}],
                        "detection": {"box": {}, "score": 0.9},
                    }
                ],
            },
        },
    }

    report = evaluate(labels, predictions, 0.45)
    summary = report["summary"]

    assert summary["dataset"]["images_total"] == 2
    assert summary["dataset"]["labeled_images"] == 1
    assert summary["dataset"]["unlabeled_predicted_faces"] == 1
    assert summary["distribution"]["photos_total"] == 1
    assert summary["distribution"]["false_recipients"] == 0
    assert summary["distribution"]["recipient_precision"] == 1.0
    assert summary["distribution"]["recipient_recall"] == 1.0


def test_min_accepted_box_height_ratio_filters_small_false_recipient(
    tmp_path: Path,
) -> None:
    """Small accepted faces can be excluded from distribution decisions."""

    image_path = tmp_path / "photo.ppm"
    image_path.write_bytes(b"P6\n100 100\n255\n" + b"\0" * 100 * 100 * 3)
    labels = {
        "people": {
            "person_a": {"display_name": "Person A"},
            "person_b": {"display_name": "Person B"},
        },
        "images": {
            "photo": {
                "photo_subjects": ["person_a"],
                "faces": {
                    "photo:face1": {
                        "is_face": True,
                        "person_id": "person_a",
                        "is_subject": True,
                        "quality": "good",
                    }
                },
            }
        },
    }
    predictions = {
        "run_id": "test_run",
        "references": {"person_a": 1, "person_b": 1},
        "images": {
            "photo": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "photo:face1",
                        "best_match": {"person_id": "person_b", "score": 0.5},
                        "matches": [
                            {"person_id": "person_a", "score": 0.1},
                            {"person_id": "person_b", "score": 0.5},
                        ],
                        "detection": {
                            "box": {"x": 0, "y": 0, "width": 10, "height": 2},
                            "score": 0.9,
                        },
                    }
                ],
            }
        },
    }

    unfiltered = evaluate(labels, predictions, 0.45)
    filtered = evaluate(
        labels,
        predictions,
        0.45,
        min_accepted_box_height_ratio=0.03,
    )

    assert unfiltered["summary"]["distribution"]["false_recipients"] == 1
    assert filtered["summary"]["distribution"]["false_recipients"] == 0


def test_label_matching_prefers_saved_box_iou_over_stale_face_id(
    tmp_path: Path,
) -> None:
    """Changed detector face numbering should not attach labels to stale ids."""

    image_path = tmp_path / "photo.ppm"
    image_path.write_bytes(b"P6\n100 100\n255\n" + b"\0" * 100 * 100 * 3)
    labels = {
        "people": {"person_a": {"display_name": "Person A"}},
        "images": {
            "photo": {
                "photo_subjects": ["person_a"],
                "faces": {
                    "photo:face1": {
                        "is_face": True,
                        "person_id": "person_a",
                        "is_subject": True,
                        "quality": "good",
                        "box": {"x": 10, "y": 10, "width": 30, "height": 30},
                    },
                    "photo:face2": {
                        "is_face": False,
                        "person_id": None,
                        "is_subject": False,
                        "quality": "bad",
                        "box": {"x": 70, "y": 70, "width": 10, "height": 10},
                    },
                },
            }
        },
    }
    predictions = {
        "run_id": "test_run",
        "references": {"person_a": 1},
        "images": {
            "photo": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "photo:face2",
                        "best_match": {"person_id": "person_a", "score": 0.9},
                        "matches": [{"person_id": "person_a", "score": 0.9}],
                        "detection": {
                            "box": {"x": 12, "y": 12, "width": 30, "height": 30},
                            "score": 0.9,
                        },
                    }
                ],
            }
        },
    }

    report = evaluate(labels, predictions, 0.45)

    assert report["face_rows"][0]["label_id"] == "photo:face1"
    assert report["face_rows"][0]["outcome"] == "correct"


def test_person_thresholds_calibrate_people_independently() -> None:
    labels = {
        "people": {
            "misha": {"display_name": "Misha"},
            "pavel": {"display_name": "Pavel"},
            "sonya": {"display_name": "Sonya"},
        },
        "images": {
            "sonya_photo": {
                "photo_subjects": ["sonya"],
                "faces": {
                    "sonya_photo:face1": {
                        "is_face": True,
                        "person_id": "sonya",
                        "is_subject": True,
                    }
                },
            },
            "misha_photo": {
                "photo_subjects": ["misha"],
                "faces": {
                    "misha_photo:face1": {
                        "is_face": True,
                        "person_id": "misha",
                        "is_subject": True,
                    }
                },
            },
        },
    }
    predictions = {
        "run_id": "test_run",
        "references": {"pavel": 1, "sonya": 1},
        "images": {
            "sonya_photo": {
                "path": "missing_sonya.jpg",
                "faces": [
                    {
                        "face_id": "sonya_photo:face1",
                        "best_match": {"person_id": "sonya", "score": 0.244},
                        "matches": [{"person_id": "sonya", "score": 0.244}],
                        "detection": {"box": {}, "score": 0.9},
                    }
                ],
            },
            "misha_photo": {
                "path": "missing_misha.jpg",
                "faces": [
                    {
                        "face_id": "misha_photo:face1",
                        "best_match": {"person_id": "pavel", "score": 0.282},
                        "matches": [{"person_id": "pavel", "score": 0.282}],
                        "detection": {"box": {}, "score": 0.9},
                    }
                ],
            },
        },
    }

    calibrated = evaluate(
        labels,
        predictions,
        0.45,
        person_thresholds={"pavel": 0.3, "sonya": 0.24},
    )
    distribution = calibrated["summary"]["distribution"]

    assert distribution["true_recipients"] == 1
    assert distribution["false_recipients"] == 0
    assert distribution["missed_recipients"] == 0


def test_acceptance_audit_prioritizes_unlabeled_disagreements() -> None:
    labels = {"images": {"labeled_photo": {"faces": {}}}}
    primary = {
        "images": {
            "risky_photo": {
                "annotated_path": "risky_review.jpg",
                "faces": [
                    {
                        "face_id": "risky_photo:face1",
                        "matches": [
                            {"person_id": "pavel", "score": 0.19},
                            {"person_id": "sonya", "score": 0.18},
                        ],
                        "detection": {
                            "box": {"x": 0, "y": 0, "width": 10, "height": 10},
                        },
                    }
                ],
            },
            "labeled_photo": {
                "faces": [
                    {
                        "face_id": "labeled_photo:face1",
                        "matches": [{"person_id": "pavel", "score": 0.9}],
                        "detection": {
                            "box": {"x": 0, "y": 0, "width": 10, "height": 10},
                        },
                    }
                ],
            },
        }
    }
    comparison = {
        "images": {
            "risky_photo": {
                "faces": [
                    {
                        "face_id": "risky_photo:face1",
                        "matches": [{"person_id": "sonya", "score": 0.5}],
                        "detection": {
                            "box": {"x": 1, "y": 1, "width": 10, "height": 10},
                        },
                    }
                ],
            }
        }
    }

    rows = build_acceptance_audit_rows(
        labels=labels,
        primary=primary,
        comparison=comparison,
        primary_threshold=0.18,
        comparison_threshold=0.45,
        unlabeled_only=True,
    )

    assert len(rows) == 1
    assert rows[0]["image_id"] == "risky_photo"
    assert rows[0]["risk_level"] == "high"
    assert rows[0]["risk_reason"] == "comparison_accepted_other"
    assert rows[0]["primary_margin"] == 0.01
    assert high_medium_image_ids(rows) == ["risky_photo"]


def test_box_iou_returns_overlap_fraction() -> None:
    first = {"x": 0, "y": 0, "width": 10, "height": 10}
    second = {"x": 5, "y": 0, "width": 10, "height": 10}

    assert round(box_iou(first, second), 6) == 0.333333


def test_face_geometry_columns_include_relative_size() -> None:
    face = {
        "detection": {
            "score": 0.9,
            "box": {"x": 0, "y": 0, "width": 20, "height": 10},
        }
    }

    columns = face_geometry_columns(face, (100, 100))

    assert columns["primary_detection_score"] == 0.9
    assert columns["primary_box_height_ratio"] == 0.1
    assert columns["primary_box_area_ratio"] == 0.02
    assert columns["primary_center_x_ratio"] == 0.1
    assert columns["primary_center_y_ratio"] == 0.05


def test_face_area_ranks_largest_box_first() -> None:
    faces = [
        {
            "face_id": "photo:small",
            "detection": {"box": {"width": 10, "height": 10}},
        },
        {
            "face_id": "photo:large",
            "detection": {"box": {"width": 20, "height": 20}},
        },
    ]

    assert face_area_ranks(faces) == {"photo:large": 1, "photo:small": 2}


def test_center_distance_uses_normalized_image_coordinates() -> None:
    centered = {"x": 40, "y": 40}
    off_center = {"x": 90, "y": 40}

    assert center_distance(centered, 20, 20, (100, 100)) == 0
    assert round(center_distance(off_center, 20, 20, (100, 100)), 6) == 0.5


def test_acceptance_audit_respects_policy_vetoed_best_match() -> None:
    face = {
        "best_match": None,
        "matches": [{"person_id": "pavel", "score": 0.9}],
    }

    decision = accepted_match(face, 0.18)

    assert decision["person_id"] is None
    assert decision["score"] == 0.0


def test_comparison_other_veto_removes_conflicting_acceptance() -> None:
    primary = {
        "run_id": "primary",
        "images": {
            "photo": {
                "faces": [
                    {
                        "face_id": "photo:face1",
                        "best_match": {"person_id": "pavel", "score": 0.19},
                        "matches": [{"person_id": "pavel", "score": 0.19}],
                        "detection": {
                            "box": {"x": 0, "y": 0, "width": 10, "height": 10},
                        },
                    },
                    {
                        "face_id": "photo:face2",
                        "best_match": {"person_id": "sonya", "score": 0.7},
                        "matches": [{"person_id": "sonya", "score": 0.7}],
                        "detection": {
                            "box": {"x": 100, "y": 0, "width": 10, "height": 10},
                        },
                    },
                ]
            }
        },
    }
    comparison = {
        "images": {
            "photo": {
                "faces": [
                    {
                        "face_id": "photo:face1",
                        "matches": [{"person_id": "sonya", "score": 0.5}],
                        "detection": {
                            "box": {"x": 1, "y": 1, "width": 10, "height": 10},
                        },
                    },
                    {
                        "face_id": "photo:face2",
                        "matches": [{"person_id": "sonya", "score": 0.8}],
                        "detection": {
                            "box": {"x": 100, "y": 0, "width": 10, "height": 10},
                        },
                    },
                ]
            }
        }
    }

    derived, summary = apply_comparison_other_veto(
        primary=primary,
        comparison=comparison,
        primary_run_id="primary",
        comparison_run_id="comparison",
        output_run_id="derived",
        primary_threshold=0.18,
        comparison_threshold=0.45,
        primary_person_thresholds={},
        comparison_person_thresholds={},
    )

    faces = derived["images"]["photo"]["faces"]
    assert summary == {
        "accepted_faces": 2,
        "vetoed_faces": 1,
        "comparison_other_vetoed_faces": 1,
        "small_low_score_vetoed_faces": 0,
        "small_crowd_unconfirmed_vetoed_faces": 0,
        "low_score_unconfirmed_vetoed_faces": 0,
    }
    assert faces[0]["best_match"] is None
    assert faces[0]["best_match_before_policy"] == {"person_id": "pavel", "score": 0.19}
    assert faces[1]["best_match"] == {"person_id": "sonya", "score": 0.7}


def test_small_low_score_veto_keeps_large_hard_face() -> None:
    assert should_veto_small_low_score_face(
        score=0.19,
        box_height_ratio=0.05,
        score_threshold=0.26,
        height_ratio_threshold=0.12,
    )
    assert not should_veto_small_low_score_face(
        score=0.19,
        box_height_ratio=0.68,
        score_threshold=0.26,
        height_ratio_threshold=0.12,
    )
    assert not should_veto_small_low_score_face(
        score=0.55,
        box_height_ratio=0.05,
        score_threshold=0.26,
        height_ratio_threshold=0.12,
    )


def test_small_crowd_unconfirmed_veto_targets_background_like_faces() -> None:
    assert should_veto_small_crowd_unconfirmed_face(
        primary_person="pavel",
        comparison_person=None,
        box_height_ratio=0.05,
        face_count=7,
        box_area_rank=5,
        height_ratio_threshold=0.08,
        face_count_threshold=4,
        rank_threshold=4,
    )
    assert not should_veto_small_crowd_unconfirmed_face(
        primary_person="pavel",
        comparison_person="pavel",
        box_height_ratio=0.05,
        face_count=7,
        box_area_rank=5,
        height_ratio_threshold=0.08,
        face_count_threshold=4,
        rank_threshold=4,
    )
    assert not should_veto_small_crowd_unconfirmed_face(
        primary_person="pavel",
        comparison_person=None,
        box_height_ratio=0.14,
        face_count=1,
        box_area_rank=1,
        height_ratio_threshold=0.08,
        face_count_threshold=4,
        rank_threshold=4,
    )


def test_low_score_unconfirmed_veto_targets_medium_small_unconfirmed_faces() -> None:
    assert should_veto_low_score_unconfirmed_face(
        primary_person="pavel",
        comparison_person=None,
        score=0.37,
        box_height_ratio=0.13,
        score_threshold=0.4,
        height_ratio_threshold=0.16,
    )
    assert not should_veto_low_score_unconfirmed_face(
        primary_person="pavel",
        comparison_person="pavel",
        score=0.37,
        box_height_ratio=0.13,
        score_threshold=0.4,
        height_ratio_threshold=0.16,
    )
    assert not should_veto_low_score_unconfirmed_face(
        primary_person="pavel",
        comparison_person=None,
        score=0.18,
        box_height_ratio=0.68,
        score_threshold=0.4,
        height_ratio_threshold=0.16,
    )


def test_small_crowd_unconfirmed_policy_vetoes_only_matching_geometry(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.ppm"
    image_path.write_bytes(b"P6\n100 100\n255\n" + b"\0" * 100 * 100 * 3)
    primary = {
        "run_id": "primary",
        "images": {
            "crowd": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "crowd:face1",
                        "best_match": {"person_id": "pavel", "score": 0.74},
                        "matches": [{"person_id": "pavel", "score": 0.74}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 10, "height": 5}},
                    },
                    {
                        "face_id": "crowd:face2",
                        "best_match": {"person_id": "sonya", "score": 0.8},
                        "matches": [{"person_id": "sonya", "score": 0.8}],
                        "detection": {"box": {"x": 20, "y": 0, "width": 50, "height": 50}},
                    },
                    {
                        "face_id": "crowd:face3",
                        "best_match": None,
                        "matches": [],
                        "detection": {"box": {"x": 80, "y": 0, "width": 40, "height": 40}},
                    },
                    {
                        "face_id": "crowd:face4",
                        "best_match": None,
                        "matches": [],
                        "detection": {"box": {"x": 130, "y": 0, "width": 30, "height": 30}},
                    },
                ],
            },
            "single": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "single:face1",
                        "best_match": {"person_id": "pavel", "score": 0.37},
                        "matches": [{"person_id": "pavel", "score": 0.37}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 50, "height": 14}},
                    }
                ],
            },
        },
    }
    comparison = {"images": {"crowd": {"faces": []}, "single": {"faces": []}}}

    derived, summary = apply_comparison_other_veto(
        primary=primary,
        comparison=comparison,
        primary_run_id="primary",
        comparison_run_id="comparison",
        output_run_id="derived",
        primary_threshold=0.18,
        comparison_threshold=0.45,
        primary_person_thresholds={},
        comparison_person_thresholds={},
        policy_name="comparison-other-small-low-score-and-small-crowd-veto",
        crowd_face_height_ratio=0.08,
        crowd_face_count_threshold=4,
        crowd_face_rank_threshold=4,
    )

    crowd_face = derived["images"]["crowd"]["faces"][0]
    single_face = derived["images"]["single"]["faces"][0]
    assert summary["small_crowd_unconfirmed_vetoed_faces"] == 1
    assert crowd_face["best_match"] is None
    assert crowd_face["acceptance_policy_decision"]["reason"] == (
        "small_crowd_unconfirmed_face"
    )
    assert single_face["best_match"] == {"person_id": "pavel", "score": 0.37}


def test_low_score_unconfirmed_policy_vetoes_medium_small_rejected_face(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.ppm"
    image_path.write_bytes(b"P6\n100 100\n255\n" + b"\0" * 100 * 100 * 3)
    primary = {
        "run_id": "primary",
        "images": {
            "medium_small": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "medium_small:face1",
                        "best_match": {"person_id": "pavel", "score": 0.37},
                        "matches": [{"person_id": "pavel", "score": 0.37}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 25, "height": 14}},
                    }
                ],
            },
            "large_hard": {
                "path": str(image_path),
                "faces": [
                    {
                        "face_id": "large_hard:face1",
                        "best_match": {"person_id": "pavel", "score": 0.19},
                        "matches": [{"person_id": "pavel", "score": 0.19}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 60, "height": 60}},
                    }
                ],
            },
        },
    }
    comparison = {"images": {"medium_small": {"faces": []}, "large_hard": {"faces": []}}}

    derived, summary = apply_comparison_other_veto(
        primary=primary,
        comparison=comparison,
        primary_run_id="primary",
        comparison_run_id="comparison",
        output_run_id="derived",
        primary_threshold=0.18,
        comparison_threshold=0.45,
        primary_person_thresholds={},
        comparison_person_thresholds={},
        policy_name="comparison-other-geometric-unconfirmed-veto",
        unconfirmed_face_score_threshold=0.4,
        unconfirmed_face_height_ratio=0.16,
    )

    medium_small = derived["images"]["medium_small"]["faces"][0]
    large_hard = derived["images"]["large_hard"]["faces"][0]
    assert summary["low_score_unconfirmed_vetoed_faces"] == 1
    assert medium_small["best_match"] is None
    assert medium_small["acceptance_policy_decision"]["reason"] == (
        "low_score_unconfirmed_face"
    )
    assert large_hard["best_match"] == {"person_id": "pavel", "score": 0.19}


def test_audit_contact_sheet_selects_requested_risk_levels() -> None:
    rows = [
        {"risk_level": "low", "image_id": "low"},
        {"risk_level": "medium", "image_id": "medium"},
        {"risk_level": "high", "image_id": "high"},
    ]

    selected = select_audit_rows(rows, risk_levels=("high", "medium"), limit=1)

    assert [row["image_id"] for row in selected] == ["medium"]


def test_audit_contact_sheet_can_filter_consensus_level() -> None:
    rows = [
        {"consensus_level": "confirmed", "image_id": "confirmed"},
        {"consensus_level": "unconfirmed", "image_id": "unconfirmed"},
    ]

    selected = select_audit_rows(
        rows,
        risk_levels=("unconfirmed",),
        level_column="consensus_level",
        limit=None,
    )

    assert [row["image_id"] for row in selected] == ["unconfirmed"]


def test_audit_caption_includes_review_diagnostics() -> None:
    row = {
        "risk_level": "medium",
        "risk_reason": "comparison_rejected",
        "primary_person": "pavel",
        "primary_score": "0.37",
        "primary_box_area_rank": "1",
        "primary_face_count": "3",
        "primary_box_height_ratio": "0.13",
        "primary_center_distance": "0.18",
        "image_id": "IMG_1",
    }

    caption = audit_caption(row)

    assert "medium comparison_rejected" in caption[0]
    assert "pavel 0.37" in caption[0]
    assert "rank 1/3" in caption[1]
    assert caption[2] == "IMG_1"


def test_policy_sweep_reports_labeled_metrics_and_unlabeled_audit() -> None:
    labels = {
        "people": {"pavel": {"display_name": "Pavel"}},
        "images": {
            "labeled": {
                "photo_subjects": ["pavel"],
                "faces": {
                    "labeled:face1": {
                        "is_face": True,
                        "person_id": "pavel",
                        "is_subject": True,
                    }
                },
            }
        },
    }
    primary = {
        "run_id": "primary",
        "references": {"pavel": 1},
        "images": {
            "labeled": {
                "path": "missing_labeled.jpg",
                "faces": [
                    {
                        "face_id": "labeled:face1",
                        "best_match": {"person_id": "pavel", "score": 0.9},
                        "matches": [{"person_id": "pavel", "score": 0.9}],
                        "detection": {"box": {"width": 10, "height": 10}},
                    }
                ],
            },
            "unlabeled": {
                "path": "missing_unlabeled.jpg",
                "faces": [
                    {
                        "face_id": "unlabeled:face1",
                        "best_match": {"person_id": "pavel", "score": 0.19},
                        "matches": [{"person_id": "pavel", "score": 0.19}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 10, "height": 10}},
                    }
                ],
            },
        },
    }
    comparison = {
        "images": {
            "unlabeled": {
                "faces": [
                    {
                        "face_id": "unlabeled:face1",
                        "best_match": None,
                        "matches": [{"person_id": "pavel", "score": 0.1}],
                        "detection": {"box": {"x": 0, "y": 0, "width": 10, "height": 10}},
                    }
                ]
            }
        }
    }

    rows = build_policy_sweep_rows(
        labels=labels,
        primary=primary,
        comparison=comparison,
        source_run_id="primary",
        comparison_run_id="comparison",
        thresholds=[0.18],
        comparison_threshold=0.45,
        primary_person_thresholds={},
        comparison_person_thresholds={},
        policy_name="comparison-other-and-small-low-score-veto",
        small_face_score_threshold=0.26,
        small_face_height_ratio=0.12,
    )

    assert rows[0]["recipient_recall"] == 1.0
    assert rows[0]["false_recipients"] == 0
    assert rows[0]["audit_medium_risk"] == 1


def test_parse_thresholds_sorts_and_deduplicates_values() -> None:
    assert parse_thresholds("0.20,0.18,0.20") == [0.18, 0.2]


def test_policy_sweep_best_safe_threshold_respects_miss_allowance() -> None:
    rows = [
        {
            "match_threshold": 0.18,
            "recipient_precision": 1.0,
            "recipient_recall": 0.9,
            "false_recipients": 0,
            "missed_recipients": 1,
            "audit_high_risk": 0,
            "audit_medium_risk": 2,
        },
        {
            "match_threshold": 0.17,
            "recipient_precision": 0.9,
            "recipient_recall": 1.0,
            "false_recipients": 1,
            "missed_recipients": 0,
            "audit_high_risk": 0,
            "audit_medium_risk": 0,
        },
    ]

    assert best_safe_threshold(rows, allowed_missed_recipients=0) == "n/a"
    assert best_safe_threshold(rows, allowed_missed_recipients=1) == "0.18"


def test_consensus_audit_prioritizes_conflict_and_unconfirmed_rows() -> None:
    first_audit = [
        {
            "image_id": "conflict",
            "primary_face_id": "conflict:face1",
            "primary_person": "pavel",
            "primary_score": "0.3",
            "primary_margin": "0.2",
            "risk_level": "high",
            "risk_reason": "comparison_accepted_other",
        },
        {
            "image_id": "unconfirmed",
            "primary_face_id": "unconfirmed:face1",
            "primary_person": "pavel",
            "primary_score": "0.4",
            "primary_margin": "0.3",
            "risk_level": "medium",
            "risk_reason": "comparison_rejected",
        },
        {
            "image_id": "confirmed",
            "primary_face_id": "confirmed:face1",
            "primary_person": "pavel",
            "primary_score": "0.5",
            "primary_margin": "0.4",
            "risk_level": "low",
            "risk_reason": "comparison_accepted_same",
        },
    ]
    second_audit = [
        {
            "image_id": "conflict",
            "primary_face_id": "conflict:face1",
            "primary_person": "pavel",
            "primary_score": "0.3",
            "primary_margin": "0.2",
            "risk_level": "low",
            "risk_reason": "comparison_accepted_same",
        },
        {
            "image_id": "unconfirmed",
            "primary_face_id": "unconfirmed:face1",
            "primary_person": "pavel",
            "primary_score": "0.4",
            "primary_margin": "0.3",
            "risk_level": "medium",
            "risk_reason": "comparison_rejected",
        },
        {
            "image_id": "confirmed",
            "primary_face_id": "confirmed:face1",
            "primary_person": "pavel",
            "primary_score": "0.5",
            "primary_margin": "0.4",
            "risk_level": "low",
            "risk_reason": "comparison_accepted_same",
        },
    ]

    rows = build_consensus_rows([first_audit, second_audit])

    assert [row["consensus_level"] for row in rows] == [
        "conflict",
        "unconfirmed",
        "confirmed",
    ]
    assert review_image_ids(rows) == ["conflict", "unconfirmed"]


def test_person_risk_summary_combines_labeled_recall_and_consensus_risk() -> None:
    reference_rows = [
        {
            "slice": "person",
            "key": "person_id=pavel",
            "subject_faces": "6",
            "with_reference": "6",
            "accepted": "6",
            "missed": "0",
            "reference_recall": "1.0",
            "min_expected_score": "0.18",
            "mean_expected_score": "0.56",
            "max_expected_score": "1.0",
        },
        {
            "slice": "person",
            "key": "person_id=sonya",
            "subject_faces": "4",
            "with_reference": "4",
            "accepted": "4",
            "missed": "0",
            "reference_recall": "1.0",
            "min_expected_score": "0.46",
            "mean_expected_score": "0.56",
            "max_expected_score": "0.65",
        },
    ]
    consensus_rows = [
        {
            "primary_person": "pavel",
            "consensus_level": "unconfirmed",
            "image_id": "pavel_review",
        },
        {
            "primary_person": "sonya",
            "consensus_level": "confirmed",
            "image_id": "sonya_ok",
        },
    ]

    rows = build_person_risk_summary_rows(
        reference_rows=reference_rows,
        consensus_rows=consensus_rows,
    )

    assert rows[0]["person_id"] == "pavel"
    assert rows[0]["labeled_reference_recall"] == "1.0"
    assert rows[0]["consensus_unconfirmed"] == 1
    assert rows[0]["priority_review_image_ids"] == "pavel_review"
    assert rows[1]["person_id"] == "sonya"
    assert rows[1]["consensus_unconfirmed"] == 0


def test_review_pack_selects_person_and_consensus_level() -> None:
    rows = [
        {
            "image_id": "pavel_review",
            "primary_person": "pavel",
            "consensus_level": "unconfirmed",
        },
        {
            "image_id": "sonya_ok",
            "primary_person": "sonya",
            "consensus_level": "confirmed",
        },
    ]

    selected = select_review_rows(
        rows,
        person_id="pavel",
        consensus_levels=("unconfirmed",),
    )

    assert [row["image_id"] for row in selected] == ["pavel_review"]


def test_review_pack_expanded_box_clamps_to_image_bounds() -> None:
    assert expanded_box(
        x=5,
        y=5,
        width=10,
        height=10,
        padding=1.0,
        image_width=20,
        image_height=20,
    ) == (0, 0, 20, 20)


def test_goal_audit_requires_no_target_unconfirmed_candidates() -> None:
    metrics = {
        "run_id": "run",
        "distribution": {
            "recipient_precision": 1.0,
            "recipient_recall": 1.0,
            "false_recipients": 0,
            "missed_recipients": 0,
        },
    }
    person_rows = [
        {
            "person_id": "pavel",
            "labeled_with_reference": "6",
            "labeled_accepted": "6",
            "labeled_missed": "0",
            "labeled_reference_recall": "1.0",
            "consensus_total": "49",
            "consensus_conflict": "0",
            "consensus_unconfirmed": "2",
            "consensus_partially_confirmed": "1",
            "consensus_confirmed": "46",
            "priority_review_image_ids": "photo_a;photo_b",
        },
        {
            "person_id": "sonya",
            "labeled_with_reference": "4",
            "labeled_accepted": "4",
            "labeled_missed": "0",
            "labeled_reference_recall": "1.0",
            "consensus_total": "0",
            "consensus_conflict": "0",
            "consensus_unconfirmed": "0",
            "consensus_partially_confirmed": "0",
            "consensus_confirmed": "0",
            "priority_review_image_ids": "",
        },
    ]

    report = build_goal_audit_report(
        metrics=metrics,
        person_rows=person_rows,
        target_people=("pavel", "sonya"),
    )

    assert report["status"] == "not_proven"
    assert report["targets_proven"] == 1
    assert report["people"][0]["person_id"] == "pavel"
    assert report["people"][0]["blockers"] == [
        "unconfirmed_consensus_candidates_present"
    ]
    assert report["people"][0]["priority_review_image_ids"] == ["photo_a", "photo_b"]
    assert report["people"][1]["person_id"] == "sonya"
    assert report["people"][1]["status"] == "proven"


def test_goal_audit_allows_one_target_miss_when_configured() -> None:
    metrics = {
        "run_id": "run",
        "distribution": {
            "recipient_precision": 1.0,
            "recipient_recall": 0.9,
            "false_recipients": 0,
            "missed_recipients": 1,
        },
        "acceptance_filters": {"person_thresholds": {}},
    }
    predictions = {"acceptance_policy": {"comparison_person_thresholds": {}}}
    person_rows = [
        {
            "person_id": "pavel",
            "labeled_with_reference": "6",
            "labeled_accepted": "5",
            "labeled_missed": "1",
            "labeled_reference_recall": "0.8333333333333334",
            "consensus_conflict": "0",
            "consensus_unconfirmed": "0",
        },
        {
            "person_id": "sonya",
            "labeled_with_reference": "4",
            "labeled_accepted": "4",
            "labeled_missed": "0",
            "labeled_reference_recall": "1.0",
            "consensus_conflict": "0",
            "consensus_unconfirmed": "0",
        },
    ]

    report = build_goal_audit_report(
        metrics=metrics,
        predictions=predictions,
        person_rows=person_rows,
        target_people=("pavel", "sonya"),
        allowed_missed_recipients=1,
    )

    assert report["status"] == "proven"
    assert report["target_labeled_misses"] == 1
    assert report["people"][0]["labeled_misses_within_goal_allowance"] is True


def test_goal_audit_blocks_person_specific_thresholds() -> None:
    metrics = {
        "run_id": "run",
        "distribution": {
            "recipient_precision": 1.0,
            "recipient_recall": 1.0,
            "false_recipients": 0,
            "missed_recipients": 0,
        },
        "acceptance_filters": {"person_thresholds": {"pavel": 0.3}},
    }
    predictions = {
        "acceptance_policy": {
            "comparison_person_thresholds": {"sonya": 0.24},
        }
    }
    person_rows = [
        {
            "person_id": "pavel",
            "labeled_with_reference": "1",
            "labeled_accepted": "1",
            "labeled_missed": "0",
            "labeled_reference_recall": "1.0",
            "consensus_conflict": "0",
            "consensus_unconfirmed": "0",
        },
    ]

    report = build_goal_audit_report(
        metrics=metrics,
        predictions=predictions,
        person_rows=person_rows,
        target_people=("pavel",),
    )

    assert report["status"] == "not_proven"
    assert report["generalization"]["blockers"] == [
        "metrics_person_thresholds_present",
        "comparison_person_thresholds_present",
    ]


def test_candidate_resolution_template_filters_person_and_level() -> None:
    consensus_rows = [
        {
            "image_id": "pavel_review",
            "primary_face_id": "pavel_review:face1",
            "primary_person": "pavel",
            "consensus_level": "unconfirmed",
            "primary_score": "0.7",
            "primary_margin": "0.6",
            "review_image": "review.jpg",
        },
        {
            "image_id": "sonya_ok",
            "primary_face_id": "sonya_ok:face1",
            "primary_person": "sonya",
            "consensus_level": "confirmed",
        },
    ]

    rows = build_resolution_template_rows(
        consensus_rows=consensus_rows,
        person_id="pavel",
        consensus_levels=("unconfirmed",),
    )

    assert len(rows) == 1
    assert rows[0]["image_id"] == "pavel_review"
    assert rows[0]["face_id"] == "pavel_review:face1"
    assert rows[0]["reviewed_person_id"] == ""


def test_apply_candidate_resolutions_adds_face_label_and_subject() -> None:
    labels = {"people": {"pavel": {"display_name": "Pavel"}}, "images": {}}
    predictions = {
        "images": {
            "photo": {
                "path": "quality_lab/data/images/photo.jpg",
                "faces": [
                    {
                        "face_id": "photo:face1",
                        "detection": {
                            "box": {"x": 1, "y": 2, "width": 3, "height": 4},
                        },
                    }
                ],
            }
        }
    }
    rows = [
        {
            "image_id": "photo",
            "face_id": "photo:face1",
            "reviewed_person_id": "pavel",
            "is_face": "true",
            "is_subject": "true",
            "quality": "good",
            "pose": "frontal",
            "occlusion": "none",
            "notes": "manual review",
        }
    ]

    summary = apply_candidate_resolutions(
        labels=labels,
        predictions=predictions,
        resolution_rows=rows,
        run_id="run_1",
        overwrite=False,
    )

    image = labels["images"]["photo"]
    face = image["faces"]["photo:face1"]
    assert summary["rows_applied"] == 1
    assert image["photo_subjects"] == ["pavel"]
    assert face["person_id"] == "pavel"
    assert face["is_subject"] is True
    assert face["box"] == {"x": 1, "y": 2, "width": 3, "height": 4}
    assert face["box_source_run_id"] == "run_1"


def test_refresh_goal_reports_builds_expected_command_order() -> None:
    config = RefreshConfig(skip_visuals=True)

    commands = build_refresh_commands("python", config)
    script_names = [Path(command[1]).name for command in commands]

    assert script_names == [
        "quality_lab_apply_acceptance_policy.py",
        "quality_lab_metrics.py",
        "quality_lab_policy_sweep.py",
        "quality_lab_acceptance_audit.py",
        "quality_lab_acceptance_audit.py",
        "quality_lab_consensus_audit.py",
        "quality_lab_person_risk_summary.py",
        "quality_lab_goal_audit.py",
    ]
    assert "--output-run-id" in commands[0]
    assert config.output_run_id in commands[0]
    assert "--target-person" in commands[-1]
    assert "--allowed-missed-recipients" in commands[-1]
    assert commands[-1][-1] == "1"


def test_refresh_goal_reports_can_build_crowd_policy_commands() -> None:
    config = RefreshConfig(
        output_run_id="crowd_run",
        policy_name="comparison-other-small-low-score-and-small-crowd-veto",
        crowd_face_height_ratio=0.08,
        crowd_face_count_threshold=4,
        crowd_face_rank_threshold=4,
        unconfirmed_face_score_threshold=0.4,
        unconfirmed_face_height_ratio=0.16,
        skip_visuals=True,
    )

    commands = build_refresh_commands("python", config)
    policy_command = commands[0]
    sweep_command = commands[2]

    assert "--policy" in policy_command
    assert config.policy_name in policy_command
    assert "--crowd-face-height-ratio" in policy_command
    assert "--crowd-face-count-threshold" in sweep_command
    assert "--unconfirmed-face-score-threshold" in policy_command
    assert "policy_sweep_sface_small_low_score_crowd_veto.csv" in sweep_command[-1]


def test_refresh_goal_reports_uses_injected_runner() -> None:
    config = RefreshConfig(skip_visuals=True)
    seen_commands: list[list[str]] = []

    commands = run_refresh_reports(
        config=config,
        python_executable="python",
        command_runner=lambda command: seen_commands.append(list(command)),
    )

    assert seen_commands == commands
    assert Path(seen_commands[0][1]).name == "quality_lab_apply_acceptance_policy.py"


def _tiny_jpeg_bytes() -> bytes:
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        "080606070605080707070909080a0c140d0c0b0b0c1912130f"
        "141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c3031"
        "3434341f27393d38323c2e333432ffdb0043010909090c0b0c"
        "180d0d1832211c213232323232323232323232323232323232"
        "32323232323232323232323232323232323232323232323232"
        "323232323232323232ffc0001108006400640301220002110103"
        "1101ffc4001f0000010501010101010100000000000000000001"
        "02030405060708090a0bffc400b5100002010303020403050504"
        "040000017d010203000411051221314106135161072271143281"
        "91a1082342b1c11552d1f02433627282090a161718191a252627"
        "28292a3435363738393a434445464748494a535455565758595a"
        "636465666768696a737475767778797a838485868788898a9293"
        "9495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9ba"
        "c2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6"
        "e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f01000301010101"
        "0101010101010000000000000102030405060708090a0bffc400"
        "b511000201020404030407050404000102770001020311040521"
        "31061241510761711322328108144291a1b1c109233352f01562"
        "72d10a162434e125f11718191a262728292a35363738393a4344"
        "45464748494a535455565758595a636465666768696a73747576"
        "7778797a82838485868788898a92939495969798999aa2a3a4a5"
        "a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3"
        "d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa"
        "ffda000c03010002110311003f00f7fa28a2803fffd9"
    )
