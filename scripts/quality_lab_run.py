"""Run a local face-analysis experiment for the quality lab."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import cv2 as cv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from face_analysis import FaceAnalyzer, YuNetConfig  # noqa: E402
from photo_distribution.workflow import cosine_similarity  # noqa: E402


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_DATA_DIR = Path("quality_lab/data")
DEFAULT_YUNET = Path("data/models/face_detection_yunet_2023mar.onnx")
DEFAULT_SFACE = Path("data/models/face_recognition_sface_2021dec.onnx")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run quality lab detection/matching.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--recognizer",
        choices=["sface", "insightface", "adaface"],
        default="sface",
        help="Face embedding backend to evaluate.",
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Execution device for optional model backends.",
    )
    parser.add_argument("--yunet", type=Path, default=DEFAULT_YUNET)
    parser.add_argument("--sface", type=Path, default=DEFAULT_SFACE)
    parser.add_argument("--score-threshold", type=float, default=0.6)
    parser.add_argument("--match-threshold", type=float, default=0.45)
    parser.add_argument("--insightface-model", default="buffalo_l")
    parser.add_argument(
        "--insightface-root",
        type=Path,
        default=Path("data/models/insightface"),
    )
    parser.add_argument(
        "--insightface-det-size",
        default="640,640",
        help="InsightFace detection size, for example 640,640.",
    )
    parser.add_argument("--adaface-architecture", default="ir_50")
    parser.add_argument(
        "--adaface-repo",
        type=Path,
        default=Path("data/models/adaface/repo"),
        help="Local checkout of https://github.com/mk-minchul/AdaFace.",
    )
    parser.add_argument(
        "--adaface-checkpoint",
        type=Path,
        default=Path("data/models/adaface/adaface_ir50_ms1mv2.ckpt"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    data_dir = args.data_dir
    run_dir = data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        path
        for path in (data_dir / "images").iterdir()
        if path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if args.recognizer == "sface":
        analyzer = FaceAnalyzer(
            args.yunet,
            args.sface,
            detector_config=YuNetConfig(score_threshold=args.score_threshold),
        )
        references = _load_sface_reference_embeddings(analyzer, data_dir / "references")
        image_records = _run_sface_images(analyzer, references, images, run_dir)
        recognizer_config = {
            "name": "sface",
            "detector": "yunet",
            "device": "cpu",
            "yunet": str(args.yunet),
            "sface": str(args.sface),
        }
    elif args.recognizer == "insightface":
        app = _create_insightface_app(args)
        references = _load_insightface_reference_embeddings(app, data_dir / "references")
        image_records = _run_insightface_images(app, references, images, run_dir)
        recognizer_config = {
            "name": "insightface",
            "model": args.insightface_model,
            "device": args.device,
            "root": str(args.insightface_root),
            "det_size": args.insightface_det_size,
        }
    elif args.recognizer == "adaface":
        analyzer = FaceAnalyzer(
            args.yunet,
            args.sface,
            detector_config=YuNetConfig(score_threshold=args.score_threshold),
        )
        model = _create_adaface_model(args)
        references = _load_adaface_reference_embeddings(
            analyzer,
            model,
            data_dir / "references",
        )
        image_records = _run_adaface_images(analyzer, model, references, images, run_dir)
        recognizer_config = {
            "name": "adaface",
            "architecture": args.adaface_architecture,
            "device": args.device,
            "repo": str(args.adaface_repo),
            "checkpoint": str(args.adaface_checkpoint),
            "detector": "yunet",
            "aligner": "sface_alignCrop",
        }
    else:
        raise ValueError(f"Unsupported recognizer: {args.recognizer}")

    predictions = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "score_threshold": args.score_threshold,
        "match_threshold": args.match_threshold,
        "recognizer": recognizer_config,
        "references": {
            person_id: len(records)
            for person_id, records in references.items()
        },
        "reference_records": _public_reference_records(references),
        "images": image_records,
    }

    predictions_path = run_dir / "predictions.json"
    predictions_path.write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Run: {run_id}")
    print(f"Predictions: {predictions_path}")
    print(f"Images: {len(images)}")
    return 0


def _load_sface_reference_embeddings(
    analyzer: FaceAnalyzer,
    references_dir: Path,
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    if not references_dir.is_dir():
        return result
    for person_dir in sorted(path for path in references_dir.iterdir() if path.is_dir()):
        records = []
        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            embeddings = analyzer.embed(image_path)
            for face_index, embedding in enumerate(embeddings, start=1):
                records.append(
                    {
                        "reference_id": f"{person_dir.name}:{image_path.stem}:face{face_index}",
                        "path": str(image_path),
                        "face_index": face_index,
                        "vector": embedding.vector,
                        "detection": asdict(embedding.detection),
                        "detection_score": embedding.detection.score,
                    }
                )
        result[person_dir.name] = records
    return result


def _run_sface_images(
    analyzer: FaceAnalyzer,
    references: dict[str, list[dict[str, object]]],
    images: list[Path],
    run_dir: Path,
) -> dict[str, dict[str, object]]:
    records = {}
    for image_path in images:
        image = cv.imread(str(image_path))
        if image is None:
            continue
        embeddings = analyzer.embed(image)
        image_predictions = []
        for face_index, embedding in enumerate(embeddings, start=1):
            face_id = f"{image_path.stem}:face{face_index}"
            matches = _rank_matches(embedding.vector, references)
            image_predictions.append(
                {
                    "face_id": face_id,
                    "face_index": face_index,
                    "detection": asdict(embedding.detection),
                    "best_match": matches[0] if matches else None,
                    "matches": matches,
                    "embedding": list(embedding.vector),
                }
            )

        annotated_path = run_dir / f"{image_path.stem}_faces{image_path.suffix}"
        _write_annotated_image(image, image_predictions, annotated_path)
        records[image_path.stem] = {
            "path": str(image_path),
            "annotated_path": str(annotated_path),
            "faces": image_predictions,
        }
    return records


def _create_insightface_app(args: argparse.Namespace) -> object:
    try:
        from insightface.app import FaceAnalysis
    except ImportError as error:
        raise SystemExit(
            "InsightFace backend is not installed. Install optional experiment "
            "dependencies first, for example: "
            ".\\.venv\\Scripts\\python.exe -m pip install insightface onnxruntime"
        ) from error

    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if args.device == "cuda"
        else ["CPUExecutionProvider"]
    )
    det_size = _parse_size(args.insightface_det_size)
    app = FaceAnalysis(
        name=args.insightface_model,
        root=str(args.insightface_root),
        providers=providers,
    )
    app.prepare(ctx_id=0 if args.device == "cuda" else -1, det_size=det_size)
    return app


def _load_insightface_reference_embeddings(
    app: object,
    references_dir: Path,
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    if not references_dir.is_dir():
        return result
    for person_dir in sorted(path for path in references_dir.iterdir() if path.is_dir()):
        records = []
        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image = cv.imread(str(image_path))
            if image is None:
                continue
            faces = _sorted_insightface_faces(app.get(image))
            for face_index, face in enumerate(faces, start=1):
                detection = _insightface_detection(face)
                records.append(
                    {
                        "reference_id": f"{person_dir.name}:{image_path.stem}:face{face_index}",
                        "path": str(image_path),
                        "face_index": face_index,
                        "vector": _insightface_vector(face),
                        "detection": detection,
                        "detection_score": detection["score"],
                    }
                )
        result[person_dir.name] = records
    return result


def _run_insightface_images(
    app: object,
    references: dict[str, list[dict[str, object]]],
    images: list[Path],
    run_dir: Path,
) -> dict[str, dict[str, object]]:
    records = {}
    for image_path in images:
        image = cv.imread(str(image_path))
        if image is None:
            continue
        faces = _sorted_insightface_faces(app.get(image))
        image_predictions = []
        for face_index, face in enumerate(faces, start=1):
            vector = _insightface_vector(face)
            face_id = f"{image_path.stem}:face{face_index}"
            matches = _rank_matches(vector, references)
            image_predictions.append(
                {
                    "face_id": face_id,
                    "face_index": face_index,
                    "detection": _insightface_detection(face),
                    "best_match": matches[0] if matches else None,
                    "matches": matches,
                    "embedding": list(vector),
                }
            )

        annotated_path = run_dir / f"{image_path.stem}_faces{image_path.suffix}"
        _write_annotated_image(image, image_predictions, annotated_path)
        records[image_path.stem] = {
            "path": str(image_path),
            "annotated_path": str(annotated_path),
            "faces": image_predictions,
        }
    return records


def _create_adaface_model(args: argparse.Namespace) -> object:
    if not args.adaface_repo.is_dir():
        raise SystemExit(
            "AdaFace repository is missing. Clone it first:\n"
            f"git clone https://github.com/mk-minchul/AdaFace {args.adaface_repo}"
        )
    if not args.adaface_checkpoint.is_file():
        raise SystemExit(
            "AdaFace checkpoint is missing. Download "
            "adaface_ir50_ms1mv2.ckpt into "
            f"{args.adaface_checkpoint}"
        )
    sys.path.insert(0, str(args.adaface_repo.resolve()))
    try:
        import torch
        import net
    except ImportError as error:
        raise SystemExit(
            "AdaFace backend dependencies are not installed. Run: "
            ".\\.venv\\Scripts\\python.exe -m pip install -e \".[experiment-adaface]\""
        ) from error

    device = torch.device("cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu")
    model = net.build_model(args.adaface_architecture)
    state = torch.load(
        str(args.adaface_checkpoint),
        map_location=device,
        weights_only=False,
    )
    state_dict = state.get("state_dict", state)
    cleaned_state_dict = {
        key.removeprefix("model."): value
        for key, value in state_dict.items()
    }
    model.load_state_dict(cleaned_state_dict, strict=False)
    model.to(device)
    model.eval()
    return {"model": model, "torch": torch, "device": device}


def _load_adaface_reference_embeddings(
    analyzer: FaceAnalyzer,
    model: dict[str, object],
    references_dir: Path,
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    if not references_dir.is_dir():
        return result
    for person_dir in sorted(path for path in references_dir.iterdir() if path.is_dir()):
        records = []
        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image = cv.imread(str(image_path))
            if image is None:
                continue
            embeddings = analyzer.embed(image)
            for face_index, embedding in enumerate(embeddings, start=1):
                aligned = analyzer.align(image, embedding.detection)
                vector = _adaface_embedding(model, aligned)
                records.append(
                    {
                        "reference_id": f"{person_dir.name}:{image_path.stem}:face{face_index}",
                        "path": str(image_path),
                        "face_index": face_index,
                        "vector": vector,
                        "detection": asdict(embedding.detection),
                        "detection_score": embedding.detection.score,
                    }
                )
        result[person_dir.name] = records
    return result


def _run_adaface_images(
    analyzer: FaceAnalyzer,
    model: dict[str, object],
    references: dict[str, list[dict[str, object]]],
    images: list[Path],
    run_dir: Path,
) -> dict[str, dict[str, object]]:
    records = {}
    for image_path in images:
        image = cv.imread(str(image_path))
        if image is None:
            continue
        embeddings = analyzer.embed(image)
        image_predictions = []
        for face_index, embedding in enumerate(embeddings, start=1):
            aligned = analyzer.align(image, embedding.detection)
            vector = _adaface_embedding(model, aligned)
            face_id = f"{image_path.stem}:face{face_index}"
            matches = _rank_matches(vector, references)
            image_predictions.append(
                {
                    "face_id": face_id,
                    "face_index": face_index,
                    "detection": asdict(embedding.detection),
                    "best_match": matches[0] if matches else None,
                    "matches": matches,
                    "embedding": list(vector),
                }
            )

        annotated_path = run_dir / f"{image_path.stem}_faces{image_path.suffix}"
        _write_annotated_image(image, image_predictions, annotated_path)
        records[image_path.stem] = {
            "path": str(image_path),
            "annotated_path": str(annotated_path),
            "faces": image_predictions,
        }
    return records


def _adaface_embedding(model: dict[str, object], aligned_bgr: object) -> tuple[float, ...]:
    torch = model["torch"]
    device = model["device"]
    image = cv.resize(aligned_bgr, (112, 112), interpolation=cv.INTER_AREA)
    tensor = torch.from_numpy(image).permute(2, 0, 1).float()
    tensor = tensor.div(255.0).sub(0.5).div(0.5).unsqueeze(0).to(device)
    with torch.no_grad():
        result = model["model"](tensor)
        if isinstance(result, tuple):
            feature = result[0]
        else:
            feature = result
        feature = torch.nn.functional.normalize(feature, dim=1)
    return tuple(float(value) for value in feature.detach().cpu().reshape(-1))


def _sorted_insightface_faces(faces: list[object]) -> list[object]:
    return sorted(
        faces,
        key=lambda face: (
            float(face.bbox[1]),
            float(face.bbox[0]),
            -float(getattr(face, "det_score", 0.0)),
        ),
    )


def _insightface_vector(face: object) -> tuple[float, ...]:
    return tuple(float(value) for value in face.embedding.reshape(-1))


def _insightface_detection(face: object) -> dict[str, object]:
    x1, y1, x2, y2 = (float(value) for value in face.bbox)
    width = x2 - x1
    height = y2 - y1
    score = float(getattr(face, "det_score", 0.0))
    landmarks = _insightface_landmarks(face)
    return {
        "box": {
            "x": x1,
            "y": y1,
            "width": width,
            "height": height,
        },
        "landmarks": landmarks,
        "score": score,
        "yunet_row": [
            x1,
            y1,
            width,
            height,
            landmarks["right_eye"]["x"],
            landmarks["right_eye"]["y"],
            landmarks["left_eye"]["x"],
            landmarks["left_eye"]["y"],
            landmarks["nose_tip"]["x"],
            landmarks["nose_tip"]["y"],
            landmarks["right_mouth_corner"]["x"],
            landmarks["right_mouth_corner"]["y"],
            landmarks["left_mouth_corner"]["x"],
            landmarks["left_mouth_corner"]["y"],
            score,
        ],
    }


def _insightface_landmarks(face: object) -> dict[str, dict[str, float]]:
    kps = getattr(face, "kps", None)
    if kps is None or len(kps) < 5:
        x1, y1, x2, y2 = (float(value) for value in face.bbox)
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        return {
            "right_eye": {"x": center_x, "y": center_y},
            "left_eye": {"x": center_x, "y": center_y},
            "nose_tip": {"x": center_x, "y": center_y},
            "right_mouth_corner": {"x": center_x, "y": center_y},
            "left_mouth_corner": {"x": center_x, "y": center_y},
        }

    # InsightFace keypoints are left_eye, right_eye, nose, left_mouth, right_mouth.
    left_eye, right_eye, nose, left_mouth, right_mouth = kps[:5]
    return {
        "right_eye": {"x": float(right_eye[0]), "y": float(right_eye[1])},
        "left_eye": {"x": float(left_eye[0]), "y": float(left_eye[1])},
        "nose_tip": {"x": float(nose[0]), "y": float(nose[1])},
        "right_mouth_corner": {
            "x": float(right_mouth[0]),
            "y": float(right_mouth[1]),
        },
        "left_mouth_corner": {
            "x": float(left_mouth[0]),
            "y": float(left_mouth[1]),
        },
    }


def _parse_size(value: str) -> tuple[int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Size must look like 640,640, got: {value}")
    return int(parts[0]), int(parts[1])


def _public_reference_records(
    references: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for person_id, records in references.items():
        result[person_id] = [
            {
                "reference_id": record["reference_id"],
                "path": record["path"],
                "face_index": record["face_index"],
                "detection": record["detection"],
                "detection_score": record["detection_score"],
            }
            for record in records
        ]
    return result


def _rank_matches(
    embedding: tuple[float, ...],
    references: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    matches = []
    for person_id, records in references.items():
        best_score = None
        best_reference = None
        reference_scores = []
        for record in records:
            score = cosine_similarity(embedding, record["vector"])
            reference_scores.append(
                {
                    "reference_id": record["reference_id"],
                    "reference_path": record["path"],
                    "score": score,
                }
            )
            if best_score is None or score > best_score:
                best_score = score
                best_reference = record
        if best_score is not None:
            reference_scores.sort(key=lambda item: item["score"], reverse=True)
            matches.append(
                {
                    "person_id": person_id,
                    "score": best_score,
                    "reference_id": best_reference["reference_id"] if best_reference else None,
                    "reference_path": best_reference["path"] if best_reference else None,
                    "reference_scores": reference_scores,
                }
            )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches


def _write_annotated_image(
    image: object,
    faces: list[dict[str, object]],
    output_path: Path,
) -> None:
    annotated = image.copy()
    image_height, image_width = annotated.shape[:2]
    thickness = max(4, round(min(image_height, image_width) / 140))
    font_scale = max(0.9, min(image_height, image_width) / 900)

    for face in faces:
        detection = face["detection"]
        box = detection["box"]
        x1 = max(0, round(box["x"]))
        y1 = max(0, round(box["y"]))
        x2 = max(0, round(box["x"] + box["width"]))
        y2 = max(0, round(box["y"] + box["height"]))
        best = face["best_match"] or {}
        label = f"{face['face_index']} {best.get('person_id', 'unknown')} {best.get('score', 0):.2f}"
        cv.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 0), thickness + 4)
        cv.rectangle(annotated, (x1, y1), (x2, y2), (40, 255, 80), thickness)
        cv.putText(
            annotated,
            label,
            (x1, max(24, y1 - 8)),
            cv.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (40, 255, 80),
            max(2, thickness // 2),
            cv.LINE_AA,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv.imwrite(str(output_path), annotated)


if __name__ == "__main__":
    raise SystemExit(main())
