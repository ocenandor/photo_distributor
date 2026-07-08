# Pipeline

Production architecture has one entry point:

```powershell
python src/start_event.py <form_id> [cloud_event_folder]
```

The live workflow accepts two form-data sources:

- Yandex Forms answer emails from the mail folder `Yandex.Forms`.
- Optional JSON exports under `/Yandex.Forms/<form_id>/` on Yandex Disk.

## 1. CLI Boundary

### 1.1. `start_event.main()`

File: [`src/start_event.py`](src/start_event.py)

Receives:

- `form_id`: Yandex Forms id expected in email subjects and optional Disk JSON
  export path.
- optional canonical Yandex Disk event folder path, for example
  `/test_event_3`; when omitted, the workflow generates a unique absolute path.
- `--event-poll-seconds`, default `1200`.
- `--form-poll-seconds`, default `30`.
- `--cleanup-local`.
- `--debug-logs`.

Does:

1. Parses CLI arguments.
2. Configures logging.
3. Builds `LiveEventConfig`.
4. Calls `run_live_event(form_id, cloud_event_folder, config=...)`.
5. Logs `LiveEventResult.safe_summary()`.

## 2. Live Workflow

### 2.1. `run_live_event(...)`

File: [`src/photo_distribution_utils/live_workflow.py`](src/photo_distribution_utils/live_workflow.py)

Receives:

- `form_id`.
- optional canonical cloud event folder path.
- explicit `LiveEventConfig`.

Does:

1. Creates `YandexDiskClient` from environment.
2. Creates `MailClient` from environment.
3. Creates `YandexDiskUiAccessGrantor` from environment.
4. Uses the already-canonical Yandex Disk event folder path from the CLI, or
   generates a unique absolute folder path when it is omitted.
5. Calls `disk_client.ensure_folder(...)` to create the event upload folder.
6. Calls `validate_cloud_event_folder(...)` to confirm the folder exists and
   is readable through the Yandex Disk API.
7. Prepares local artifact paths for forms data, references, event photo cache,
   copy plans, and live status.
8. Creates `FaceAnalyzer`.
9. Builds `LiveEventRuntime`.
10. Creates a live status reporter that overwrites
    `data/live_status/live_event_status.json` on each polling loop.
11. Repeats `run_live_event_once(...)` until `Ctrl+C`.
12. Cleans local live artifacts when `--cleanup-local` is enabled.
13. Returns `LiveEventResult`.

### 2.2. `run_live_event_once(...)`

File: [`src/photo_distribution_utils/live_workflow.py`](src/photo_distribution_utils/live_workflow.py)

Receives:

- concrete Disk client.
- concrete Mail client.
- concrete Yandex Disk UI access grantor.
- mutable `LiveEventRuntime`.
- explicit `LiveEventConfig`.
- `poll_event_photos` decision from the live loop.

Does:

1. Reads messages from the configured forms mail folder.
2. Parses only subjects matching the configured `form_id`.
3. Deduplicates email answers by `answer_id`.
4. Parses `Accept`, `Name`, `Email`, and up to three attachments.
5. Checks optional `/Yandex.Forms/<form_id>/` on Yandex Disk for the newest
   JSON export. Missing folder or missing JSON is treated as a normal live
   state.
6. Imports a new JSON export only when its Disk path changes.
7. Treats an unavailable or unparsable Disk JSON export as a skipped source for
   the current iteration, logs the safe warning, and waits for a later export.
8. Merges email answers and JSON export participants into one
   `FormsIngestResult`, keeping each accepted answer as a separate participant
   and preserving all downloaded reference images. Duplicate participant emails
   are allowed in the forms contract because two different people may submit
   different references for the same contact email.
9. Grants participant write access to the event folder through the Yandex Disk
   UI access grantor for participant emails not handled before, with a default
   240-second timeout per email.
10. Sends a participant notification email with the event folder web link when
   automatic access is granted.
11. Sends one operator alert email to `MAIL_ADMIN_EMAIL` when the UI access
    grant fails or times out, including the event folder web link so access can
    be granted manually.
12. Sends one operator alert email to `MAIL_ADMIN_EMAIL` when a duplicate
    participant email appears after access for that email was already handled.
    The duplicate participant still remains in the downstream forms contract.
13. Treats participant/admin notification send failures as non-fatal warnings;
    the live iteration continues.
14. When scheduled, calls `download_event_photos(..., known_disk_paths=...)`
    to update the local event photo cache.
15. Rebuilds face analysis and the copy plan when new form data or new event
    photos arrived.
16. Applies the copy plan on Yandex Disk, including stale quarantine cleanup
    for photos that now have participant matches.
17. Returns `LiveEventIterationResult`.

## 3. Forms Adapters

### 3.1. JSON Adapter

File: [`src/forms_export/ingest.py`](src/forms_export/ingest.py)

Does:

1. Finds the newest `.json` export under `/Yandex.Forms/<form_id>/`.
2. Downloads the JSON export locally.
3. Parses answers by positional field order from `FORM_FIELD_ORDER`.
4. Parses one to three reference image values from absolute Disk paths,
   `disk:` paths, Yandex Disk UI links, and
   `https://forms.yandex.ru/u/files?path=...` links.
5. Allows duplicate participant emails in the imported forms contract.
6. Downloads reference images from Yandex Disk.
7. Skips unavailable reference images from a JSON export and keeps the live
   runner alive.
8. Skips a participant from the JSON export when none of that participant's
   reference images could be downloaded.
9. Returns `FormsIngestResult`.

### 3.2. Email Adapter

File: [`src/forms_export/email_answers.py`](src/forms_export/email_answers.py)

Does:

1. Parses subject into form title, form id, and answer id.
2. Parses body fields `Accept`, `Name`, and `Email`.
3. Parses policy acceptance through `TRUTHY_POLICY_VALUES`.
4. Saves up to three email attachments as local reference images.
5. Returns `FormsIngestResult`.

## 4. Mail Client

File: [`src/mail_client/client.py`](src/mail_client/client.py)

Does:

1. Reads IMAP/SMTP configuration from `.env`.
2. Selects the configured forms mail folder, default `Yandex.Forms`.
3. Fetches plain-text messages and attachments.
4. Sends plain-text notification emails, including operator alerts to
   `MAIL_ADMIN_EMAIL`.

Yandex Forms semantics are parsed by `src/forms_export/email_answers.py`.

## 5. Yandex Disk UI

File: [`src/yandex_disk/ui_access_grantor.py`](src/yandex_disk/ui_access_grantor.py)

Does:

1. Reads browser automation configuration from `.env`.
2. Opens a persistent browser profile for Yandex Disk UI automation.
3. Opens the event folder page in Yandex Disk.
4. Opens the folder header three-dots menu.
5. Opens the access settings dialog.
6. Switches permissions from view to edit.
7. Enters the participant email, selects the suggested Yandex account, and
   clicks invite.
8. Treats a completed invite click as a successful access-grant attempt.
9. Runs once per participant email per live run; later participants with the
   same email trigger an operator duplicate-email alert instead of another UI
   invite.
10. Keeps participant emails, browser profile paths, and session details out of
   safe diagnostic messages.

## 6. Cloud Files

File: [`src/photo_distribution_utils/cloud_files.py`](src/photo_distribution_utils/cloud_files.py)

Does:

1. Validates live event folder paths.
2. Downloads top-level image files from the event folder.
3. Uses `known_disk_paths` to skip already cached remote files.
4. Verifies that downloaded event photos are readable images before passing
   them to face analysis.
5. Leaves unreadable or failed downloads out of the known-file cache so the
   next event-folder poll retries them.
6. Supports `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.heic`, and `.heif`
   event photo files.
7. Returns `EventPhotoRecord` objects with remote source paths and local cache
   paths.

## 7. Face Analysis

File: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py)

Does:

1. Detects faces with YuNet.
2. Loads standard images through OpenCV and HEIC/HEIF images through
   `src/photo_distribution_utils/image_files.py` before model inference.
3. Aligns detected faces with SFace.
4. Extracts SFace embeddings.
5. Compares event embeddings with reference embeddings through
   `FaceAnalyzer.match_embedding(...)`.
6. Returns accepted matches through `FaceAnalyzer.analyze_distribution(...)`.

## 8. Output Files

File: [`src/photo_distribution_utils/output_files_structure.py`](src/photo_distribution_utils/output_files_structure.py)

Does:

1. Builds participant output folder names with `__output` suffix.
2. Deduplicates names as `name__output`, `name_2__output`, and so on.
3. Keeps unmatched photos routed to `quarantine`.
4. Writes `copy_plan.json` with remote source and destination paths.

## 9. Apply Plan

File: [`src/photo_distribution_utils/apply_distribution_plan.py`](src/photo_distribution_utils/apply_distribution_plan.py)

Does:

1. Creates participant output folders and `quarantine` on Yandex Disk.
2. Copies existing remote event photos into planned destination folders.
3. Removes stale quarantine copies for photos that are now matched to one or
   more participant folders.
4. Keeps original event photos untouched.
5. Provides result/config/counter dataclasses and local artifact cleanup.

## 10. Runtime Scheduling And Parallelism

Files:

- [`src/photo_distribution_utils/live_workflow.py`](src/photo_distribution_utils/live_workflow.py)
- [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py)

Does:

1. Runs the live workflow in one Python process.
2. Uses a polling loop in `run_live_event(...)`:
   - form sources are checked every `LiveEventConfig.form_poll_seconds`,
     currently 30 seconds. One form-source check reads both the forms mail
     folder and the optional `/Yandex.Forms/<form_id>/` JSON export folder;
   - the Yandex Disk event folder is checked when `time.monotonic()` reaches
     the next scheduled event poll, default 1200 seconds.
3. Uses one daemon `threading.Thread` only for Yandex Disk UI access grants.
   The thread result is returned through `queue.Queue`, and the live workflow
   treats an unfinished grant after 240 seconds as a timeout.
4. Runs mail parsing, optional JSON import, event photo downloading, face
   analysis, copy-plan creation, and Yandex Disk copy application sequentially
   inside each live iteration.
5. Runs `FaceAnalyzer.analyze_distribution(...)` sequentially over references
   and event photos. Project-level orchestration is a simple sequential loop
   plus the dedicated UI-access thread.
6. Lets OpenCV use its own native execution internals during model inference.
7. Keeps SMTP notification failures fail-soft: failed participant or admin
   emails are logged and the live runner continues.
8. Keeps mail-fetch and optional Disk JSON forms checks fail-soft: temporary
   source failures are logged and the next polling loop tries again.
9. Writes a compact live status JSON file on each polling loop so a long wait
   can be monitored without filling the main log with heartbeat records.
