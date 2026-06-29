# TODO

## Done

- [x] Create project virtual environment in `.venv`.
- [x] Create minimal `pyproject.toml`.
- [x] Document the current architecture and development sequence in `AGENTS.md`.
- [x] Initialize the git repository.

## Current Roadmap

- [x] Step 1: Minimal Yandex Disk API integration.
- [ ] Step 2: Define the local Yandex Forms export format.
- [x] Step 3: Build SQLite-backed recognition on mock/local data.
- [x] Step 4: Copy photos on Yandex Disk from database results.

## Step 1: Yandex Disk API Integration

- [x] Read OAuth token from `YANDEX_DISK_TOKEN`.
- [x] Load local environment variables from `.env`.
- [x] Implement resource metadata lookup.
- [x] Implement top-level folder item listing.
- [x] Implement folder creation method.
- [x] Implement resource copy method.
- [x] Implement local file upload method.
- [x] Implement file download method.
- [x] Implement resource deletion method.
- [x] Add pytest integration tests for the Yandex Disk client.
- [x] Add a manual probe command: `python src/main.py "<yandex_event_folder>"`.
- [x] Move the service entry point to `src/main.py`.
- [x] Move Yandex Disk operations into the `src/yandex_disk` module.
- [x] Manually verify against a real Yandex Disk folder.

## Step 2: Local Yandex Forms Export

- [x] Define the positional form field order in one place:
  `policy`, `name`, `email`, `images`.
- [x] Support up to three files in `images`.
- [x] Read manually exported Yandex Forms JSON from Yandex Disk.
- [x] Keep form id explicit; tests use `test_form`.
- [x] Keep form exports outside the Yandex Disk event photo folder.
- [x] Keep reference photos in `data/forms/references/`.
- [x] Add a parser for JSON answers exported by Yandex Forms.
- [x] Add importer that downloads the newest JSON export and reference images.
- [x] Add SQLite bootstrap for participants and reference images.
- [ ] Add mock JSON export and reference photos.

## Later

- [ ] Add SQLite schema and migrations/bootstrap.
- [x] Add low-level YuNet/SFace face analysis module.
- [x] Add manual face probe script for boxes, embeddings, and similarity checks.
- [x] Add a separate quality lab for annotation, experiments, and metrics.
- [ ] Build the first labeled quality dataset in `quality_lab/data/`.
- [ ] Compare baseline thresholds and heuristics on labeled quality metrics.
- [x] Add a quality-lab model comparison path for multiple recognition
  backends, starting with SFace and optional InsightFace.
- [x] Add and run AdaFace as an optional quality-lab recognition backend.
- [x] Add quality-lab second-pass derived-reference enrollment experiments with
  candidate risk diagnostics.
- [x] Freeze the current derived-reference parameters as a quality-lab baseline
  only, without moving them into production workflow.
- [ ] Revisit whether derived-reference enrollment should move into production
  after more labeled events and people are evaluated.
- [ ] Evaluate additional free recognition backends such as MagFace or ONNX
  ArcFace variants if they can be installed cleanly on the local machine.
- [ ] Evaluate reference-photo robustness separately from detector quality:
  measure per-person recall on labeled subject faces, especially masks,
  sunglasses, dark photos, profile poses, and other hard cases that currently
  fall into quarantine.
- [ ] Make quality-lab face labels detector-run independent:
  match predictions to manual labels by bounding-box IoU or stable box ids
  instead of relying only on `<image_id>:faceN`, so different thresholds/models
  can be compared safely.
- [ ] Add a face quality/filtering stage after detection:
  remove very small distant faces, faces not looking toward the camera, and
  false-positive non-face detections before embedding/matching.
- [ ] Add a photo relevance classifier/filter:
  do not assign a photo just because a participant appears somewhere in the
  background; prefer photos where the participant is an intended subject of the
  shot, while still allowing valid group photos.
- [ ] Extract face-embedding matching into a dedicated module:
  keep cosine similarity, thresholding, top-k/reference aggregation,
  per-person diagnostics, and future matching heuristics outside `main` and
  outside the workflow wrapper.
- [ ] Rework privacy-safe logging and diagnostics:
  avoid relying on one global redaction helper; keep sensitive data out of
  object string representations, exceptions, and class-level diagnostic output
  close to the classes that own the data, similar to `YandexDiskClient.token`
  being hidden from `repr`.
- [ ] Replace ad-hoc `print` diagnostics with `loguru`:
  define normal console output vs debug logs, add a proper log sink/rotation
  policy for local troubleshooting, and make sure debug logs stay
  privacy-safe by design.
- [ ] Add human-readable field descriptions for public dataclasses:
  document what each field means, whether it is a count, path, id, plan, or
  materialized artifact, and avoid result objects that look like one thing
  while containing many unrelated workflow counters.
- [ ] Update `AGENTS.md` with function/interface design guidelines:
  functions should have a clear single responsibility, names should reveal
  whether they orchestrate workflow, mutate SQLite, call Yandex Disk, or only
  transform data, and large blocks such as `with sqlite3.connect(...)` should
  not hide the whole business workflow behind a persistence-looking wrapper.
- [x] Connect YuNet/SFace recognition to local references and SQLite.
- [x] Add database-to-Yandex-Disk copy workflow.
- [x] Add optional local workflow artifact cleanup for `main`.
- [ ] Add tests when the corresponding implementation steps begin.
