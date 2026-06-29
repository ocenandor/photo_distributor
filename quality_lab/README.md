# Face Quality Lab

Local workspace for experiments with face detection quality, face matching, and
photo relevance. This lab is intentionally separate from the production
workflow so we can try thresholds and heuristics without changing `main`.

## Goals

- Measure face detection and matching quality on real event photos.
- Mark which detected faces are valid, which person they are, and whether the
  photo is actually about that person.
- Compare free/local approaches before changing the production workflow.
- Study hard cases: masks, sunglasses, dark images, small distant faces, profile
  faces, occlusions, and false positive non-faces.

## Folder Layout

```text
quality_lab/
  README.md
  DATASET_SCHEMA.md
  data/
    images/
    references/
    labels.json
    runs/
```

`quality_lab/data/` is ignored by git. Put private photos and experiment output
there.

## Labeling Model

The lab uses a semi-automatic flow:

1. Put event photos into `quality_lab/data/images/`.
2. Put reference photos into `quality_lab/data/references/<person_id>/`.
3. Run `scripts/quality_lab_init_labels.py` to create a draft `labels.json`.
4. Run `scripts/quality_lab_run.py` to detect faces and compute embeddings.
5. Open the generated contact sheets in `quality_lab/data/runs/<run_id>/`.
6. Edit `labels.json` manually:
   - mark whether each detected face is real;
   - assign a `person_id` if known;
   - mark whether the person is an intended subject of the photo.
7. Run `scripts/quality_lab_metrics.py` to get metrics for the current run.

## Quick Start

Copy or place images:

```powershell
New-Item -ItemType Directory -Force quality_lab\data\images
New-Item -ItemType Directory -Force quality_lab\data\references\person_a
```

Then initialize labels:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_init_labels.py
```

Run the current baseline:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id baseline_0_6
```

After editing `quality_lab/data/labels.json`, compute metrics:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_metrics.py --run-id baseline_0_6
```

## Adding More Photos Later

The annotation source of truth is always one file:

```text
quality_lab/data/labels.json
```

To extend the dataset:

1. Add new event photos to `quality_lab/data/images/`.
2. Add new reference photos, if any, to
   `quality_lab/data/references/<person_id>/`.
3. Run:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_init_labels.py
```

This command is incremental. It keeps existing labels and only adds missing
people/images.

Run or rerun an experiment:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id interactive_baseline_0_6
```

Render the next image that still has unlabeled detected faces:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_label_view.py --run-id interactive_baseline_0_6 --next-unlabeled
```

You can also render a specific image:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_label_view.py IMG_20250714_134132 --run-id interactive_baseline_0_6
```

Keep image file stems unique, because the stem is used as `image_id`.

Fixed lab baselines are documented in:

```text
quality_lab/EXPERIMENT_BASELINES.md
quality_lab/experiment_baselines.json
```

These baselines are for experiments only. They are not production defaults.

## Comparing Recognition Backends

The default backend is OpenCV YuNet + SFace:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id sface_baseline --recognizer sface
```

Before comparing another detector/recognizer, attach current run boxes to
manual labels. This lets the evaluator match future detections to labels by
bbox IoU instead of only by `faceN` order:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_attach_label_boxes.py --run-id sface_baseline
```

Optional InsightFace backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[experiment-insightface]"
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id insightface_buffalo_l_cpu --recognizer insightface --device cpu
```

If GPU runtime is available and compatible:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[experiment-insightface-gpu]"
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id insightface_buffalo_l_cuda --recognizer insightface --device cuda
```

Compare all runs:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_compare_runs.py
```

The comparison writes `quality_lab/data/model_comparison.csv` and prints a
compact table with reference recall, accepted precision, distribution F1, false
recipients, missed recipients, and same-person score statistics.

## Derived References

Derived references are a quality-lab simulation of second-pass enrollment. They
do not require extra user uploads. The script selects high-confidence first-pass
matches as temporary references, writes a new run, and reports whether selected
candidates are safe according to manual labels.

Strict experiment:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_derived_references.py --source-run-id sface_baseline --run-id sface_derived_strict_0_65 --min-score 0.65
```

Less strict experiment with more candidates:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_derived_references.py --source-run-id sface_baseline --run-id sface_derived_0_50_det_0_75 --min-score 0.50 --min-detection-score 0.75 --max-per-person 4
```

Then evaluate as a normal run:

```powershell
.\.venv\Scripts\python.exe scripts\quality_lab_metrics.py --run-id sface_derived_0_50_det_0_75 --match-threshold 0.35
```

Optional AdaFace backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[experiment-adaface]"
git clone https://github.com/mk-minchul/AdaFace data\models\adaface\repo
.\.venv\Scripts\python.exe -m gdown 1eUaSHG4pGlIZK7hBkqjyp2fc2epKoBvI -O data\models\adaface\adaface_ir50_ms1mv2.ckpt
.\.venv\Scripts\python.exe scripts\quality_lab_run.py --run-id adaface_ir50_ms1mv2_cpu --recognizer adaface --device cpu
```

AdaFace uses the same YuNet detections and SFace `alignCrop` alignment as the
baseline, then extracts embeddings with the official AdaFace PyTorch model.

## Current Baseline

- Detector: OpenCV YuNet on CPU.
- Recognizer: OpenCV SFace on CPU.
- Detection threshold: `0.6`.
- Matching score: cosine similarity.
- Production matching threshold: `0.45`.

## Experiment Ideas

- Filter small faces by face box area relative to image area.
- Filter distant/background faces by box height and centrality.
- Filter low-quality faces by detection score and landmark geometry.
- Estimate frontalness from landmark symmetry and eye/nose/mouth layout.
- Try image preprocessing for dark images: CLAHE or gamma correction.
- Try running detection at multiple image scales for small faces.
- Use multiple reference photos per person and aggregate max/mean similarity.
- Keep a separate photo relevance classifier:
  "is this person an intended subject of the photo?".

## Hard Cases to Collect

- Masked faces.
- Sunglasses and regular glasses.
- Dark photos and backlit photos.
- Side/profile faces.
- Tiny background faces.
- Group photos where several people are intended subjects.
- Photos where a participant is visible but clearly not the subject.
- False positives where YuNet detects a non-face.
