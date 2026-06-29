# TODO

## 1. Current Status

The first local prototype works end to end: it imports Yandex Forms data,
downloads references and event photos, analyzes faces with YuNet/SFace, stores
matches in SQLite, builds a local distribution layout, and copies photos on
Yandex Disk into participant folders or `quarantine`.

## 2. Next Steps

### 2.1. Architecture Cleanup

- [ ] 2.1.1. Extract face-embedding matching into a dedicated module:
  keep cosine similarity, thresholding, top-k/reference aggregation,
  per-person diagnostics, and future matching heuristics outside `main` and
  outside the workflow wrapper.
- [ ] 2.1.2. Split `photo_distribution.workflow` into clearer orchestration,
  persistence, matching, local file layout, and Yandex Disk copy boundaries.
- [ ] 2.1.3. Make workflow functions read like the domain flow instead of hiding
  most business logic inside `with sqlite3.connect(...)`.
- [ ] 2.1.4. Add human-readable field descriptions for public dataclasses:
  document what each field means, whether it is a count, path, id, plan, or
  materialized artifact.

### 2.2. Logging And Privacy

- [ ] 2.2.1. Replace ad-hoc `print` diagnostics with `loguru`:
  define normal console output vs debug logs, add a proper log sink/rotation
  policy for local troubleshooting, and make sure debug logs stay
  privacy-safe by design.

### 2.3. Quality And Recognition

- [ ] 2.3.1. Run the current quality-lab metrics after architecture cleanup to
  confirm matching behavior did not change.

### 2.4. Data, Database, And Tests

- [ ] 2.4.1. Add focused tests for the extracted matching module.

### 2.5. Product Workflow

- [ ] 2.5.1. Keep automatic Yandex Disk access grants out of `main` until the
  matching/workflow boundaries are cleaner.

## 3. Next Priorities

### 3.1. Architecture Cleanup

- [ ] 3.1.1. Review result/config dataclasses and avoid objects that look like
  one thing while containing many unrelated workflow counters.
- [ ] 3.1.2. Add missing docstrings to public functions and non-trivial private
  helpers, following the `AGENTS.md` style.
- [ ] 3.1.3. Add focused tests for the extracted matching module.
- [ ] 3.1.4. Add focused tests for workflow orchestration after it is split into
  smaller modules.

### 3.2. Logging And Privacy

- [ ] 3.2.1. Rework privacy-safe logging and diagnostics:
  avoid relying on one global redaction helper; keep sensitive data out of
  object string representations, exceptions, and class-level diagnostic output
  close to the classes that own the data, similar to `YandexDiskClient.token`
  being hidden from `repr`.
- [ ] 3.2.2. Decide which local artifacts are allowed to contain personal data
  and document retention/cleanup rules for them.
- [ ] 3.2.3. Add tests for privacy-safe diagnostics and logging behavior.

### 3.3. Quality And Recognition

- [ ] 3.3.1. Evaluate reference-photo robustness separately from detector
  quality: measure per-person recall on labeled subject faces, especially
  masks, sunglasses, dark photos, profile poses, and other hard cases that
  currently fall into quarantine.
- [ ] 3.3.2. Add a face quality/filtering stage after detection:
  remove very small distant faces, faces not looking toward the camera, and
  false-positive non-face detections before embedding/matching.
- [ ] 3.3.3. Add a photo relevance classifier/filter:
  do not assign a photo just because a participant appears somewhere in the
  background; prefer photos where the participant is an intended subject of the
  shot, while still allowing valid group photos.
- [ ] 3.3.4. Revisit whether derived-reference enrollment should move into
  production after more labeled events and people are evaluated.
- [ ] 3.3.5. Evaluate additional free recognition backends such as MagFace or
  ONNX ArcFace variants if they can be installed cleanly on the local machine.
- [ ] 3.3.6. Expand the labeled quality dataset with more participants, events,
  masks, sunglasses, dark photos, profiles, and group photos.

### 3.4. Data, Database, And Tests

- [ ] 3.4.1. Add mock JSON export and reference photos that can be safely
  committed.
- [ ] 3.4.2. Replace ad-hoc SQLite bootstrap with explicit schema versioning or
  migrations.

### 3.5. Product Workflow

- [ ] 3.5.1. Decide whether `main` should grant Yandex Disk access to
  participant folders automatically using emails from the forms export.
- [ ] 3.5.2. Decide how distribution reruns should handle stale files that were
  copied by earlier runs but are no longer selected by the current
  threshold/model.

## 4. Done

### 4.1. Project Setup

- [x] 4.1.1. Create project virtual environment in `.venv`.
- [x] 4.1.2. Create minimal `pyproject.toml`.
- [x] 4.1.3. Initialize the git repository.
- [x] 4.1.4. Document the current architecture and development sequence in
  `AGENTS.md`.
- [x] 4.1.5. Move the service entry point to `src/main.py`.

### 4.2. Yandex Disk API

- [x] 4.2.1. Read OAuth token from `YANDEX_DISK_TOKEN`.
- [x] 4.2.2. Load local environment variables from `.env`.
- [x] 4.2.3. Implement resource metadata lookup.
- [x] 4.2.4. Implement top-level folder item listing.
- [x] 4.2.5. Implement folder creation.
- [x] 4.2.6. Implement resource copy.
- [x] 4.2.7. Implement local file upload.
- [x] 4.2.8. Implement file download.
- [x] 4.2.9. Implement resource deletion.
- [x] 4.2.10. Add pytest integration tests for the Yandex Disk client.
- [x] 4.2.11. Manually verify against real Yandex Disk folders.
- [x] 4.2.12. Add publishing/access method:
  `YandexDiskClient.publish_resource(path, emails=[...], rights="read")`.

### 4.3. Forms Export And Local Data

- [x] 4.3.1. Define the positional form field order in one place:
  `policy`, `name`, `email`, `images`.
- [x] 4.3.2. Support up to three files in `images`.
- [x] 4.3.3. Keep form id explicit; tests use `test_form`.
- [x] 4.3.4. Read manually exported Yandex Forms JSON from Yandex Disk.
- [x] 4.3.5. Keep form exports outside the Yandex Disk event photo folder.
- [x] 4.3.6. Keep reference photos in `data/forms/references/`.
- [x] 4.3.7. Add a parser for JSON answers exported by Yandex Forms.
- [x] 4.3.8. Add importer that downloads the newest JSON export and reference
  images.
- [x] 4.3.9. Add SQLite bootstrap for participants and reference images.

### 4.4. Face Analysis And Distribution

- [x] 4.4.1. Add low-level YuNet/SFace face analysis module.
- [x] 4.4.2. Add manual face probe script for boxes, embeddings, and similarity
  checks.
- [x] 4.4.3. Connect YuNet/SFace recognition to local references and SQLite.
- [x] 4.4.4. Add database-to-Yandex-Disk copy workflow.
- [x] 4.4.5. Add optional local workflow artifact cleanup for `main`.
- [x] 4.4.6. Add CLI override for similarity threshold.
- [x] 4.4.7. Manually run end-to-end distribution on test Yandex Disk folders.

### 4.5. Quality Lab

- [x] 4.5.1. Add a separate quality lab for annotation, experiments, and
  metrics.
- [x] 4.5.2. Build the first small labeled quality dataset in
  `quality_lab/data/` locally; private data is ignored by git.
- [x] 4.5.3. Add quality-lab model comparison path for multiple recognition
  backends, starting with SFace and optional InsightFace.
- [x] 4.5.4. Add and run AdaFace as an optional quality-lab recognition backend.
- [x] 4.5.5. Add quality-lab second-pass derived-reference enrollment
  experiments with candidate risk diagnostics.
- [x] 4.5.6. Freeze the current derived-reference parameters as a quality-lab
  baseline only, without moving them into production workflow.
- [x] 4.5.7. Compare initial thresholds and derived-reference heuristics on
  labeled quality metrics.
- [x] 4.5.8. Make quality-lab face labels less detector-run dependent by
  attaching boxes and matching predictions to labels by IoU when exact face ids
  are not available.

### 4.6. Project Conventions

- [x] 4.6.1. Add `AGENTS.md` guidelines for function/interface design.
- [x] 4.6.2. Add `AGENTS.md` requirement for docstrings that describe function
  behavior, arguments, return values, and side effects.
