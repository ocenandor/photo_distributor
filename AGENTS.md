# Photo Distributor Project

## Goal

Build a local Python prototype that distributes event photos from a shared
Yandex Disk folder into per-person folders. Participants submit consent and a
reference photo through Yandex Forms, but in the current prototype the exported
form data and reference photos are stored locally and imported by a local
command.

Face detection and recognition will run on CPU using OpenCV YuNet and SFace.
Original photos on Yandex Disk must not be moved or deleted; the service copies
photos into output folders.

## Development Sequence

1. Implement minimal Yandex Disk API integration.
   - Authenticate through `YANDEX_DISK_TOKEN`.
   - List files in a folder.
   - Read file metadata.
   - Create folders.
   - Copy files.

2. Define the expected local Yandex Forms export format.
   - Export Yandex Forms answers manually to a Yandex Disk folder.
   - Store exported form answers locally, outside the event photo folder.
   - Store reference photos locally, outside the event photo folder.
   - Use the agreed format to let mock answers and reference photos be added
     before recognition work starts.

3. Build recognition on mock/local data.
   - Import participants and references into SQLite.
   - Compute and store reference embeddings.
   - Process mock event photos.
   - Store detected faces and recognition matches in the database.
   - Do not modify Yandex Disk during this step.

4. Connect database results back to Yandex Disk.
   - Read photo-to-person matches from SQLite.
   - Create per-person folders and a quarantine folder on Yandex Disk.
   - Copy photos into the correct folders.
   - Copy photos without recognized participants into quarantine.

## Current Decisions

- The first version is a local prototype without a web UI.
- The service entry point lives in `src/main.py`.
- Yandex Disk operations live in the `src/yandex_disk` module.
- Local Yandex Forms export parsing lives in the `src/forms_export` module.
- Low-level face detection and embedding extraction lives in the
  `src/face_analysis` module.
- End-to-end distribution workflow lives in the `src/photo_distribution`
  module and is orchestrated by `src/main.py`.
- Local environment variables are loaded from `.env`; keep real tokens out of
  git.
- Yandex Forms answers are read from a local export file.
- Reference photos are stored in a local folder.
- The shared Yandex Disk event folder contains event photos, not form exports.
- Source photos on Yandex Disk are copied only; they are not moved or deleted.
- Extra CLI options such as `--dry-run`, `--limit`, `--rebuild`, and `--config`
  will be added later only when requested.
- Automated tests are deferred until the implementation steps that need them.

## Initial Local Data Shape

Yandex Forms exports are expected on Yandex Disk at:

- `/Yandex.Forms/<form_id>/`

The importer takes the newest `.json` file from that folder. The JSON answer
fields are parsed by position, not by question text, because question text can
change. The single source of truth for field order is `FORM_FIELD_ORDER` in
`src/forms_export/schema.py`:

- `policy`
- `name`
- `email`
- `images`

Local folders and files created by the importer:

- `data/forms/exports/`
- `data/forms/references/`
- `data/photo_distributor.sqlite3`
- `data/cache/`

`images` should contain one to three Yandex Disk paths or Yandex Disk UI links.
Email is trusted as already validated by Yandex Forms. The form id is always
passed explicitly; tests use `test_form` as the Yandex Forms subfolder name.

## Face Analysis Module

`src/face_analysis` is intentionally limited to one-image computer vision:

- `FaceAnalyzer.detect(image)` returns YuNet face detections.
- `FaceAnalyzer.embed(image, detections=None)` returns SFace embeddings.
- The module does not read or write Yandex Disk, SQLite, form exports, or
  business workflow state.
- OpenCV model paths are passed explicitly by the caller.

## Distribution Workflow

`python src/main.py <event_folder> <form_id>` runs the current prototype:

- imports participants and reference images from `/Yandex.Forms/<form_id>/`;
- downloads event photos from `<event_folder>`;
- computes and stores reference/event face embeddings in SQLite;
- matches event faces to participants with cosine similarity threshold `0.45`;
- builds a local copied layout under `data/local_distribution/`;
- creates participant folders and `quarantine` in the event folder;
- copies matched photos to every matched participant folder and unmatched
  photos to `quarantine`.
- optional `--cleanup-local` removes local workflow artifacts after a
  successful run; probe-script artifacts are not affected.

## Code Design Style

- Public functions and non-trivial private helpers must have docstrings that
  explain what the function does, what each argument means, what it returns,
  and which side effects it performs.
- Dataclasses that cross module boundaries should document their fields in
  human language, especially when fields are counters, local paths, remote
  paths, database ids, copied artifacts, or workflow plans.
- Function names should make their role explicit: orchestration, SQLite
  mutation/query, Yandex Disk I/O, face analysis, matching, or pure data
  transformation.
- Workflow orchestration should not be hidden inside a block that looks like a
  persistence detail. For example, `with sqlite3.connect(...)` should not wrap
  the entire business workflow without a clearly named orchestration function.
- Face-embedding matching is a separate domain concern from CLI parsing,
  Yandex Disk I/O, SQLite persistence, and image embedding extraction. Keep
  matching logic in a dedicated module as it grows.

## Yandex Disk Publishing

`YandexDiskClient.publish_resource(path, emails=[...], rights="read")` uses
`PUT /resources/publish` with address access enabled. Current manual checks
live in `scripts/publish_yandex_disk_resource.py`.

## Quality Lab

`quality_lab/` is a local experiment workspace for face quality, matching, and
photo relevance. Private images, labels, predictions, and contact sheets live
under `quality_lab/data/`, which is ignored by git. Lab scripts live in
`scripts/quality_lab_*.py` and should not affect the production workflow.
