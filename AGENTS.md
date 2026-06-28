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
