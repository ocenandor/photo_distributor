# TODO

## 1. Current Status

The first local prototype works end to end: it imports Yandex Forms data,
downloads references and event photos, analyzes faces with YuNet/SFace, keeps
run state in explicit dataclasses, writes a remote copy-plan JSON artifact, and
remote-copies photos on Yandex Disk into participant folders or `quarantine`.
Face embedding matching now lives behind `FaceAnalyzer.match_embedding()`;
target output folder/file planning lives in `output_files_structure.py`, Yandex
Disk event-file operations live in `cloud_files.py`, and distribution plan
application lives in a dedicated Disk-facing module.
Workflow config/result/cleanup objects now live with final plan application in
`src/photo_distribution_utils/apply_distribution_plan.py`, leaving `workflow.py`
focused on high-level setup and result assembly. Event folder path preparation
and remote validation now live in explicit modules, and `main` no longer
initializes the Yandex Disk client directly. Production-facing diagnostics now
use `loguru`, domain-owned safe error messages, `utils.py` redaction helpers,
tests that guard against accidental `print()` diagnostics in service code, and
one consolidated `AGENTS.md` file for service goals, architecture decisions,
code rules, and privacy/data rules.

## 2. Next Steps

### 2.1. Architecture Cleanup

- [ ] 2.1.1. Rename remaining production-facing `distribution` wording to
  `matching` where the code is specifically about face matching decisions, not
  the whole photo distribution workflow.
- [ ] 2.1.2. Revisit `forms_export/ingest.py` naming: use clearer form-import
  terminology instead of generic `ingest` where it describes downloading and
  parsing a Yandex Forms export.
- [ ] 2.1.3. Move participant loading into the form-import module boundary so
  workflow receives imported participants directly from the Yandex Forms import
  step.
### 2.2. Logging And Privacy

- [ ] 2.2.1. If quality-lab reports keep growing, consider moving larger metric
  tables to the same shared report-output style used by the freeform labeling
  tools.

### 2.3. Quality And Recognition

- [ ] 2.3.1. Run the current quality-lab metrics after architecture cleanup to
  confirm matching behavior did not change.

### 2.4. Data, Database, And Tests

- [ ] 2.4.1. Decide whether reruns should remove stale files previously copied
  to Yandex Disk when the current threshold/model no longer selects them.

### 2.5. Product Workflow

- [ ] 2.5.1. Keep automatic Yandex Disk access grants out of `main` until the
  matching/workflow boundaries are cleaner.

## 3. Next Priorities

### 3.1. Architecture Cleanup

- [ ] 3.1.1. Review remaining config/result objects outside
  `photo_distribution_utils` and avoid shapes that mix unrelated concerns.
- [ ] 3.1.2. Keep auditing docstrings when new modules/scripts are added; the
  current `src` tree has no missing function/class docstrings by AST audit.

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

### 3.4. Data, Debug Persistence, And Tests

- [ ] 3.4.1. Add mock JSON export and reference photos that can be safely
  committed.
- [ ] 3.4.2. Design a separate debug/history persistence layer if we need to
  inspect long-term runs; it must not be used as temporary state transport in
  the main runtime pipeline.

### 3.5. Product Workflow

- [ ] 3.5.1. Decide whether `main` should grant Yandex Disk access to
  participant folders automatically using emails from the forms export.
- [ ] 3.5.2. Decide how distribution reruns should handle stale files that were
  copied to Yandex Disk by earlier runs but are no longer selected by the
  current threshold/model.

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
- [x] 4.3.9. Replace the temporary SQLite forms handoff with explicit
  `FormsIngestResult` runtime state.

### 4.4. Face Analysis And Distribution

- [x] 4.4.1. Add low-level YuNet/SFace face analysis module.
- [x] 4.4.2. Add manual face probe script for boxes, embeddings, and similarity
  checks.
- [x] 4.4.3. Connect YuNet/SFace recognition to local references and runtime
  state.
- [x] 4.4.4. Add runtime copy-plan-to-Yandex-Disk workflow.
- [x] 4.4.5. Add optional local workflow artifact cleanup for `main`.
- [x] 4.4.6. Add CLI override for similarity threshold.
- [x] 4.4.7. Manually run end-to-end distribution on test Yandex Disk folders.
- [x] 4.4.8. Move face-embedding matching behind
  `FaceAnalyzer.match_embedding()` and remove the obsolete `src/face_matching`
  production module.
- [x] 4.4.9. Add focused tests for the matching module.
- [x] 4.4.10. Add initial `loguru` logging setup for `main`.
- [x] 4.4.11. Keep in-memory run records next to the workflow step that owns
  them: event photo records in `cloud_files.py` and copy-plan records in
  `output_files_structure.py`.
- [x] 4.4.12. Add focused tests for runtime state based copy-plan creation,
  disk copy, and face-analysis workflow helpers.
- [x] 4.4.13. Extract distribution copy-plan creation into a dedicated
  workflow boundary.
- [x] 4.4.14. Extract Yandex Disk distribution-plan application into
  `src/photo_distribution_utils/apply_distribution_plan.py`.
- [x] 4.4.15. Add focused tests for copy-plan and disk copy modules.
- [x] 4.4.16. Split the workflow body into named steps with explicit state
  handoff between them.
- [x] 4.4.17. Add focused tests for the distribution face-analysis boundary with
  a fake analyzer subclass.
- [x] 4.4.18. Promote the tested face-analysis workflow into
  `FaceAnalyzer.analyze_distribution(...)`.
- [x] 4.4.19. Extract distribution config/result/cleanup objects out of
  `workflow.py` so `workflow.py` stays focused on top-level setup and result
  assembly.
- [x] 4.4.20. Define and test local rerun behavior: runtime state and copy-plan
  are rebuilt, and the current copy-plan JSON overwrites the previous one for
  the same event.
- [x] 4.4.21. Move Yandex Disk client initialization from `main` into
  `run_distribution()`, leaving `main` as a CLI/logging boundary.
- [x] 4.4.22. Extract strict Yandex Disk event folder path validation into the
  cloud-file module and local artifact path derivation into
  `src/photo_distribution_utils/event_artifacts.py`.
- [x] 4.4.23. Remove SQLite from the current runtime pipeline; forms ingest now
  returns explicit state, distribution passes dataclasses between steps, and
  debug/history persistence is deferred as a separate future layer.
- [x] 4.4.24. Move event photo downloading out of face analysis:
  workflow now imports forms/reference data, downloads event photos, creates
  `FaceAnalyzer`, and then runs analysis/matching/copy-plan/copy steps.
- [x] 4.4.25. Expose embedding matching through `FaceAnalyzer.match_embedding()`
  so distribution analysis no longer calls the low-level matching helper
  directly.
- [x] 4.4.26. Split distribution workflow into explicit output-folder name
  building, face analysis/matching, copy-plan JSON persistence, and Yandex Disk
  copy application.
- [x] 4.4.27. Remove local materialized participant/quarantine photo layout from
  the main workflow; persist `copy_plan.json` and apply it by remote-copying
  existing Yandex Disk photos.
- [x] 4.4.28. Move distribution face-analysis orchestration into
  `FaceAnalyzer.analyze_distribution(...)` and remove
  `src/photo_distribution_utils/orchestration.py`.
- [x] 4.4.29. Add YuNet max-side preprocessing in `FaceAnalyzer`: large images
  are downscaled for detection, then detections are mapped back to original
  coordinates before SFace alignment.
- [x] 4.4.30. Merge target output folder naming and remote copy-plan creation
  into `src/photo_distribution_utils/output_files_structure.py`.
- [x] 4.4.31. Remove protocol-style Disk interfaces and use the concrete
  `YandexDiskClient` contract inside product-owned workflow modules.
- [x] 4.4.32. Merge cloud event-folder validation and event photo downloading
  into `src/photo_distribution_utils/cloud_files.py`.
- [x] 4.4.33. Move Yandex Disk retry behavior into the
  `@retry_yandex_disk_operation` decorator on `YandexDiskClient` methods and
  remove the loose `photo_distribution_utils/disk_operations.py` helper; keep
  idempotent folder creation in `YandexDiskClient.ensure_folder(...)`.

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
- [x] 4.5.9. Add a batch freeform labeling-session generator for larger
  quality-lab review batches.
- [x] 4.5.10. Add a parser that converts edited freeform labeling sessions into
  machine-readable `parsed_labels.json`.
- [x] 4.5.11. Add a conservative merge tool that applies reviewed
  `parsed_labels.json` into the main `quality_lab/data/labels.json` without
  overwriting existing face labels by default.
- [x] 4.5.12. Add a shared quality-lab console report helper and use it for the
  freeform labeling prepare/parse/merge summaries.
- [x] 4.5.13. Add `scripts/quality_lab_start_labeling.py`, a one-command local
  semi-automatic labeling wrapper that runs the current detector/matcher and
  prepares a freeform labeling session for later parse/merge postprocessing.

### 4.6. Project Conventions

- [x] 4.6.1. Add `AGENTS.md` guidelines for function/interface design.
- [x] 4.6.2. Add `AGENTS.md` requirement for docstrings that describe function
  behavior, arguments, return values, and side effects.
- [x] 4.6.3. Add `PIPELINE.md` with the service flow, modules, classes,
  artifacts, Yandex Disk outputs, and logging locations.
- [x] 4.6.4. Add human-readable field descriptions to public service
  dataclasses across Yandex Disk, forms import, face analysis, matching, and
  distribution modules.
- [x] 4.6.5. Move the Yandex Disk publishing helper script from ad-hoc prints
  to the shared `loguru` logging setup.
- [x] 4.6.6. Add class-owned safe diagnostic messages for domain exceptions and
  route CLI error logging through that contract instead of explicitly
  redacting exceptions at each call site.
- [x] 4.6.7. Add path-safe `safe_summary()` and `repr` behavior for
  `DistributionConfig` and `DistributionResult`, and log workflow result
  counters through that summary instead of logging local artifact paths.
- [x] 4.6.8. Split `DistributionResult` into grouped
  `DistributionCounters` and `DistributionArtifacts` and keep access explicit
  through `result.counts` and `result.artifacts`.
- [x] 4.6.9. Complete an AST-based docstring audit for `src` and add missing
  docstrings to remaining public functions and non-trivial private helpers.
- [x] 4.6.10. Document private local artifact roots, retention rules, cleanup
  behavior, and logging limits in `AGENTS.md`.
- [x] 4.6.11. Add a privacy guardrail test that checks private artifact roots
  are both ignored by git and documented in `AGENTS.md`.
- [x] 4.6.12. Consolidate development rules for modules, scripts, local
  artifacts, logging output, docs, and tests into `AGENTS.md`.
- [x] 4.6.13. Add privacy/logging tests that verify domain safe diagnostic
  messages, log redaction, private artifact documentation, and the absence of
  `print()` diagnostics in `src` plus production-facing scripts.
- [x] 4.6.14. Add a lightweight convention check that production-facing scripts
  use the shared logging setup and `safe_exception_message()`.
- [x] 4.6.15. Remove protocol-style distribution interfaces from product code;
  keep strict concrete contracts for `YandexDiskClient` and explicit
  dataclasses for face-analysis inputs.
- [x] 4.6.16. Tighten privacy-safe diagnostics so `safe_exception_message()`
  redacts plain exception fallbacks, `FormsExportError` and
  `FaceAnalysisError` can expose path-safe class-owned messages, and forms
  ingest reports missing exports as a domain error instead of a generic
  `ValueError`.
- [x] 4.6.17. Document the product-code rule: avoid fallback branches for
  impossible internal states between controlled project functions, and keep
  validation/fallbacks at external data, API, filesystem, model, and CLI
  boundaries.
- [x] 4.6.18. Remove duplicate `DEVELOPMENT.md` and `PRIVACY.md` instruction
  files so `AGENTS.md` is the single source for project coding, architecture,
  and privacy rules.
- [x] 4.6.19. Replace the standalone `privacy.py` module with `utils.py`
  redaction helpers used by logging and domain safe-message code.
- [x] 4.6.20. Merge the obsolete `photo_distribution_utils/results.py` contents into
  `photo_distribution_utils/apply_distribution_plan.py` and remove flat
  `DistributionResult` proxy properties.
