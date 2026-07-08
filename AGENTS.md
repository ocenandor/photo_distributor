# Photo Distributor Project

## 1. Service Goal

Build a local Python prototype that distributes event photos from a shared
Yandex Disk folder into per-person folders.

Participants submit consent, display name, email, and one to three reference
photos through Yandex Forms. The live prototype imports Yandex Forms answer
emails from the mail folder `Yandex.Forms` and can also consume the optional
JSON export folder on Yandex Disk. Both sources must normalize to the same
imported-forms contract before downstream processing.

Face detection and recognition run locally with OpenCV YuNet and SFace. The
service copies original event photos on Yandex Disk into output folders. It must
not move or delete original event photos.

The current production command is:

```powershell
python src/start_event.py <form_id> [cloud_event_folder]
```

## 2. Architecture Decisions

### 2.1. Module Ownership

- `src/start_event.py` is the production CLI and logging boundary only.
- Runtime service construction and live orchestration live in
  `src/photo_distribution_utils/live_workflow.py`.
- Yandex Disk API operations live in `src/yandex_disk`.
- Yandex Disk UI automation for participant write-access grants lives in
  `src/yandex_disk/ui_access_grantor.py` and must stay outside
  `YandexDiskClient`.
- IMAP/SMTP transport operations live in `src/mail_client`.
- Local Yandex Forms export parsing and reference download live in
  `src/forms_export`.
- Email answer parsing and attachment normalization live in
  `src/forms_export/email_answers.py`.
- Low-level face detection, embedding extraction, and distribution face-analysis
  orchestration live in `src/face_analysis`.
- Face-embedding matching decisions live behind `FaceAnalyzer.match_embedding()`;
  do not reintroduce a separate production `face_matching` module unless the
  production matching boundary is explicitly redesigned.
- End-to-end live distribution workflow lives in
  `src/photo_distribution_utils/live_workflow.py`.
- Yandex Disk event folder validation and source event photo downloading live
  in `src/photo_distribution_utils/cloud_files.py`.
- Local artifact path derivation lives in
  `src/photo_distribution_utils/event_artifacts.py`.
- Distribution configuration, result objects, counters, artifact summaries, and
  local artifact cleanup live in
  `src/photo_distribution_utils/apply_distribution_plan.py`.
- Target Yandex Disk folder names and remote copy-plan creation live in
  `src/photo_distribution_utils/output_files_structure.py`.
- Applying a prepared distribution plan to Yandex Disk lives in
  `src/photo_distribution_utils/apply_distribution_plan.py`.
- Yandex Disk retry behavior is applied explicitly with
  `@retry_yandex_disk_operation` on selected `YandexDiskClient` methods.
- Shared diagnostic redaction helpers live in `src/utils.py`; logging setup and
  CLI-safe exception formatting live in `src/app_logging.py`.

### 2.2. Runtime Flow

The current workflow is described in `PIPELINE.md`. Update `PIPELINE.md` when
module ownership, call order, workflow inputs, workflow outputs, local artifacts,
or Yandex Disk side effects change.

The production live flow is:

1. `start_event` parses CLI arguments and configures logging.
2. `live_workflow.run_live_event(...)` creates `YandexDiskClient` and
   `MailClient`, plus the Yandex Disk UI access grantor.
3. The workflow accepts an already-canonical optional cloud event folder path,
   or generates one when omitted, creates it with
   `YandexDiskClient.ensure_folder(...)`, and validates that it exists.
4. The workflow prepares local artifact paths for this live event.
5. The workflow polls email answers from the configured forms mail folder.
6. The workflow also checks optional `/Yandex.Forms/<form_id>/` on Yandex Disk
   for a newer JSON export. A missing forms folder or missing JSON export is a
   normal live state.
7. A temporarily unavailable mail source or invalid/unavailable Disk JSON export
   is logged safely and retried on later polling loops.
8. Email answers and JSON exports both normalize to `FormsIngestResult`; the
   live workflow keeps each accepted answer as a separate participant and keeps
   all downloaded reference images. Duplicate emails are allowed in the forms
   contract because two different people may submit references for the same
   contact email.
9. For every new participant email from either source, the workflow grants
   participant write access to the event folder through
   `src/yandex_disk/ui_access_grantor.py`. A failed grant is logged safely, one
   operator alert is sent to `MAIL_ADMIN_EMAIL`, and the participant still
   enters the downstream forms contract so manual access granting by the
   operator does not block reference ingestion or matching.
10. If another participant uses an email that already had access handled in the
   current live run, the workflow skips the repeated UI invite and sends one
   operator duplicate-email alert.
11. The workflow incrementally downloads only new readable event photos into
    the local cache. Unreadable or partially uploaded images are left out of the
    known-file cache so later event-folder polls retry them.
12. The workflow runs face analysis, output folder planning, copy-plan creation,
    and remote copy application.
13. The workflow runs until `Ctrl+C`.

Live runner polling is split by source family:

- `--form-poll-seconds` controls how often the runner checks both form sources:
  the forms mail folder and optional `/Yandex.Forms/<form_id>/` JSON export.
- `--event-poll-seconds` controls how often the runner checks the event photo
  folder.

Runtime state is passed explicitly between steps. SQLite is not used as hidden
temporary transport in the service flow. A future debug/history database must
be a separate persistence layer, not a dependency of the runtime pipeline.

### 2.3. Forms Data Contract

JSON Yandex Forms exports are expected on Yandex Disk at:

- `/Yandex.Forms/<form_id>/`

The importer takes the newest `.json` file from that folder. JSON answer fields
are parsed by position, not by question text, because question text can change.
The single source of truth for field order is `FORM_FIELD_ORDER` in
`src/forms_export/schema.py`:

- `policy`
- `name`
- `email`
- `images`

`images` contains one to three reference image values. The JSON importer accepts
absolute Yandex Disk paths, `disk:` paths, Yandex Disk UI links, and
`https://forms.yandex.ru/u/files?path=...` links. Email is trusted as already
validated by Yandex Forms. Duplicate email values are allowed in the imported
forms contract. The form id is always passed explicitly; tests use `test_form`
as the Yandex Forms subfolder name.

All forms sources must return the shared domain contract from
`src/forms_export/contracts.py`:

- `ImportedReferenceImage`
- `ImportedParticipant`
- `FormsIngestResult`

JSON import and email import must both expose:

- `forms_ingest.participants`
- `forms_ingest.reference_images`
- `forms_ingest.participants_count`
- `forms_ingest.reference_images_count`

Downstream workflow code must not care whether the source was JSON export or
email answers.

JSON import must skip unavailable reference images from a Disk export instead
of stopping the live runner. If none of a participant's JSON reference images
can be downloaded, that participant is skipped from the current imported forms
result and may enter later through a corrected JSON export or email answer.

Email answers are parsed from subjects shaped as
`Ответ_на_форму__Название__ID формы__ID ответа`. The email parser reads body
fields `Accept`, `Name`, and `Email`, parses policy acceptance through
`TRUTHY_POLICY_VALUES`, and saves up to three attachments as local reference
images.

### 2.4. Face Analysis Contract

`src/face_analysis` is intentionally limited to computer vision and matching
work for already-provided images:

- `FaceAnalyzer.detect(image)` returns YuNet face detections.
- `FaceAnalyzer.embed(image, detections=None)` returns SFace embeddings.
- `FaceAnalyzer.match_embedding(query_vector, references, min_score=None)`
  compares one event embedding with known reference embeddings and returns
  sorted scores.
- `FaceAnalyzer.analyze_distribution(reference_images, event_photos,
  similarity_threshold)` runs the distribution face-analysis sequence using the
  analyzer's own embedding and matching methods.
- `YuNetConfig.max_input_side` limits the image side passed to YuNet. Large
  images are downscaled for detection and returned detections are mapped back to
  original image coordinates before SFace alignment.

`FaceAnalyzer` must not read or write Yandex Disk, parse form exports, perform
CLI parsing, or persist workflow state.

### 2.5. Yandex Disk Output Contract

- Source photos on Yandex Disk are copied only.
- Participant folders and `quarantine` are created under the event folder.
- Participant output folders always use the `__output` suffix, for example
  `pavel__output` and `pavel_2__output`.
- If an event photo matches at least one participant, it is copied into every
  matched participant folder.
- If an event photo matches no participant, it is copied into `quarantine`.
- The workflow applies `copy_plan.json` by copying existing remote files on
  Yandex Disk, not by uploading local downloaded photos back to Disk.
- Idempotent output folder creation goes through
  `YandexDiskClient.ensure_folder(path)`, which treats the Yandex Disk
  "already exists" conflict as success.
- The live workflow creates the event upload folder through
  `YandexDiskClient.ensure_folder(...)`.
- Participant write access is granted through the Yandex Disk UI automation
  module, because the public Disk API does not reliably create the required
  shared write-access folder for this product flow.
- The live UI access flow opens the event folder page, uses the header
  three-dots menu, chooses `Настроить доступ`, switches `Просмотр` to
  `Редактирование`, selects the suggested Yandex user for the participant
  email, and clicks `Пригласить`.
- A completed invite click is treated as a successful access-grant attempt.
  The live workflow applies a default 240-second timeout per participant email
  and sends one `MAIL_ADMIN_EMAIL` alert when manual access granting is needed.
- The live workflow grants UI access once per participant email in a live run.
  Later participants with the same email stay in `FormsIngestResult`, skip the
  repeated UI invite, and trigger one operator duplicate-email alert.
- A successful access grant sends a participant notification email. A failed
  access grant does not block the answer from entering `FormsIngestResult`,
  because the operator can grant Disk access manually after the alert.
- Failed participant/admin notification emails are logged safely and do not
  stop the live runner.
- The Yandex Disk UI automation must keep browser/session artifacts out of logs
  and commits.
- The Yandex Disk API publishing helper was removed from `YandexDiskClient`
  because it is not the product access mechanism for participant write-access
  folders.

### 2.6. Quality Lab

`quality_lab/` is the local experiment workspace for face quality, matching, and
photo relevance. Private images, labels, predictions, and contact sheets live
under `quality_lab/data/`, which is ignored by git.

Quality-lab scripts live in `scripts/quality_lab_*.py`. They must not change the
production workflow unless a separate production task explicitly promotes an
experiment.

## 3. Code Rules

### 3.1. Boundaries And Data Flow

- Put domain logic in focused modules, not directly in `src/start_event.py`.
- Keep `start_event` limited to CLI parsing, logging setup, calling workflow,
  logging safe summaries, and returning process exit codes.
- Keep top-level packages grouped by real responsibility:
  `yandex_disk` for the remote API client, `forms_export` for imported form
  data, `face_analysis` for local model work, `photo_distribution_utils` for
  workflow helper steps, `app_logging` for logging setup, and `utils` for small
  shared helpers.
- Keep Yandex Disk API calls in `src/yandex_disk` or explicit Disk-facing
  workflow modules.
- Keep browser UI automation separate from API clients. A Yandex Disk UI
  clicker may grant folder access, but `YandexDiskClient` must remain a pure
  API client.
- Keep face detection, embedding extraction, and embedding matching independent
  from forms, persistence, Yandex Disk, and CLI parsing.
- Keep target cloud file-structure planning, face analysis/matching, copy-plan
  JSON persistence, and Yandex Disk copy application as explicit workflow
  steps.
- Keep IMAP/SMTP transport separate from Yandex Forms semantics: `mail_client`
  fetches and sends messages, while `forms_export/email_answers.py` parses
  form-specific subjects, fields, and attachments.
- Keep forms adapters interchangeable by making them return
  `FormsIngestResult`; downstream code must use only the shared contract
  fields.
- Treat participant email as an access/notification contact, not as a unique
  person identity. Do not merge participants by email in recognition or output
  planning.
- Keep target output folder naming and target copy-plan construction together
  when they describe one final cloud file structure.
- Keep validation/downloading of source cloud files together when both concern
  the same Yandex Disk resource family.
- Keep final copy-plan application, final run counters, cleanup, and run config
  together when they belong to the final production command boundary.
- Put orchestration on the class that owns the lower-level methods when the
  orchestration is just sequencing those methods, as with
  `FaceAnalyzer.analyze_distribution(...)`.
- Pass runtime state explicitly between workflow steps.
- Do not use SQLite or another persistence layer as hidden temporary transport
  inside the service flow.
- Keep any future debug/history database persistence in an explicit persistence
  module, separate from orchestration and runtime state passing.

### 3.2. Internal Contracts

- This is product code with controlled internal callers, not a general-purpose
  open source library.
- Do not add fallback/default branches for impossible internal states between
  project-owned functions.
- Do not make optional arguments for values that our own call graph always
  provides.
- Validate at boundaries with CLI/user input, external APIs, filesystem state,
  model execution, and imported data.
- Keep live source checks fail-soft when the source is expected to be
  temporarily unavailable: mail fetches, optional Disk JSON exports, SMTP
  notifications, and partially uploaded event photos should log safe diagnostics
  and allow the next polling loop to retry or continue.
- Inside our own call graph, prefer required arguments, explicit data objects,
  and simple failure behavior.
- If a private helper becomes important enough to test directly, move it behind
  a public boundary or document why it remains private.
- Do not introduce `Protocol`, `interfaces.py`, or wrapper classes for
  project-owned dependencies unless there is a real external/plugin boundary.
  Use concrete contracts for internal services.
- Put retry behavior on the concrete method that performs the external call.
  Do not wrap whole workflow modules in retry helpers.
- Put idempotent API semantics that are native to a remote resource into the
  client itself, such as `YandexDiskClient.ensure_folder(...)` handling an
  already-existing folder.

### 3.3. Naming And Interfaces

- Function names must make the role explicit: CLI boundary, orchestration,
  runtime state transformation, Yandex Disk I/O, forms import, face analysis,
  matching, copy-plan creation, copy-plan application, debug/history
  persistence, or pure data transformation.
- Avoid generic workflow names when the function is doing a concrete operation.
  Prefer names that state the object being prepared, validated, loaded, built,
  persisted, or applied.
- Avoid generic module names such as `state.py`, `interfaces.py`,
  `results.py`, `orchestration.py`, and `disk_operations.py` when the file has
  a concrete owner. Prefer names like `cloud_files.py`,
  `output_files_structure.py`, `event_artifacts.py`, and
  `apply_distribution_plan.py`.
- If a module split forces a reader to jump between two files to understand one
  business object, merge the files under the name of that object.
- If a file name says `utils`, it must contain cross-step helper code, not core
  domain logic that deserves its own package.
- Avoid generic catch-all dataclasses when the fields mix different concepts.
  Separate counters, local paths/artifacts, remote paths, ids, and plans when
  those concepts can be confused.
- Prefer explicit grouped dataclasses over convenience proxy properties. Access
  grouped state as `result.counts...` and `result.artifacts...` instead of
  flattening fields with pass-through `@property` methods.
- Public functions, public classes, and non-trivial private helpers must have
  docstrings that explain what the function/class does, what each argument
  means, what it returns, and which side effects it performs.
- Dataclasses that cross module boundaries must document their fields in human
  language, especially counters, local paths, remote paths, run-local ids,
  copied artifacts, and workflow plans.
- Result/config objects that may appear in logs must provide path-safe
  `repr`, `safe_summary()`, or an equivalent explicit diagnostic method.

### 3.4. Logging And Output

- Production-facing CLI commands use `loguru` through `src/app_logging.py`.
- Production log records include source metadata as
  `package:module:function` for package modules, for example
  `photo_distribution_utils:cloud_files:download_event_photos`.
- Production code and production-facing scripts must not use `print()` for
  diagnostics.
- Domain exceptions that may carry sensitive data must expose `safe_message()`.
- CLI error logging must use `safe_exception_message()`.
- `safe_message()` should omit local paths, remote photo paths, emails, tokens,
  embeddings, and raw form rows.
- Console tables and `print()` output are acceptable for quality-lab reports
  when they are intentional user-facing experiment results, not hidden service
  diagnostics.
- Debug logs are still private local artifacts.

### 3.5. Tests And Documentation

- Add focused tests near the boundary that changed.
- Prefer fake Disk/analyzer services for orchestration tests instead of live
  Yandex Disk or OpenCV model execution.
- Use live Yandex Disk tests only for explicit integration checks.
- Update `PIPELINE.md` when the runtime flow or module ownership changes.
- Update `quality_lab/README.md` when adding or changing experiment tools.
- Update `TODO.md` so completed work moves to Done and remaining work stays
  specific.
- When adding a new private artifact root, update `.gitignore` and the privacy
  guardrail test.
- Before finishing architecture changes, verify that `AGENTS.md`, `PIPELINE.md`,
  and relevant tests describe the same call boundaries.

## 4. Privacy And Data Rules

### 4.1. Private Data

This project processes private event photos, participant names, participant
emails, reference photos, face detections, face embeddings, generated labels,
and Yandex Disk links. Treat every file under `data/` and `quality_lab/data/` as
private by default.

Do not commit real tokens, form exports, participant emails, event photos,
reference photos, face embeddings, debug databases, logs, quality-lab labels, or
generated public links.

Commit only code, tests, documentation, and safe synthetic fixtures.

### 4.2. Ignored Private Roots

The repository intentionally ignores:

- `.env`
- `.venv/`
- `data/`
- `quality_lab/data/`
- `tests/downloads/`

Current private service artifacts under `data/`:

- `data/forms/exports/`: downloaded Yandex Forms JSON exports with participant
  names, emails, consent answers, and reference photo links.
- `data/forms/references/`: downloaded participant reference photos.
- `data/forms/email_references/`: reference images saved from live email
  attachments.
- `data/event_photos/`: downloaded source event photos.
- `data/distribution_plans/`: copy-plan JSON artifacts with remote source and
  destination photo paths.
- `data/logs/photo_distributor.log`: service logs.
- `data/live_status/live_event_status.json`: overwritten live-runner heartbeat
  state with event-level counters and timing.
- `data/models/`: downloaded model files.
- `data/browser/`: persistent browser profiles for Yandex Disk UI automation.
- `data/face_probe/`: manual face-probe outputs.
- `data/mock_faces/`: local scratch fixtures or manual samples.

Quality-lab private artifacts under `quality_lab/data/` may include event
photos, reference photos, `labels.json`, `predictions.json`, review images,
contact sheets, freeform labeling sessions, CSV reports, and metrics.

### 4.3. Cleanup And Retention

When `python src/start_event.py ... --cleanup-local` is used, the live workflow
removes live local artifacts after the runner stops. This includes the
event-specific forms data folder, email reference folder, event photo cache
folder, copy-plan folder, and live status file.

The cleanup routine must refuse to delete paths outside the project `data/`
folder.

Artifacts intentionally not removed by live workflow cleanup:

- `data/models/`
- `data/logs/`
- `data/face_probe/`
- `data/mock_faces/`
- `quality_lab/data/`
- future debug/history databases until their retention rules are documented

For a normal manual run, use `--cleanup-local` when only the Yandex Disk output
is needed. Keep logs, quality-lab data, and old local event folders only while
debugging or running experiments.

### 4.4. Logging Privacy

Default logs must not contain:

- participant names;
- participant emails;
- original event photo paths;
- reference image paths;
- raw Yandex Forms rows;
- OAuth tokens;
- generated public links;
- face embeddings;
- local private file paths.

Current logging guarantees:

- obvious email addresses are redacted before logs are emitted;
- OAuth token strings are redacted before logs are emitted;
- logs include package, module, and function source metadata without local
  source file paths;
- `safe_exception_message()` redacts fallback messages for plain exceptions;
- `DiskApiError`, `FormsExportError`, and `FaceAnalysisError` expose
  `safe_message()` for CLI diagnostics;
- path-bearing domain errors should return path-free safe messages;
- `DistributionConfig`, `DistributionCounters`, `DistributionArtifacts`, and
  `DistributionResult` expose path-safe summaries and `repr` output.

Current logging limits:

- logs are private local artifacts;
- logs may contain event-level counts, model file names, status text, and
  high-level error messages.

Before sharing the repository, run `git status --short` and confirm only code,
tests, documentation, and safe config metadata are present.
