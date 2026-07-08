# TODO

## 1. Current Status

The live prototype is the production path. `start_event.py` starts a
long-running runner, creates or reuses the event upload folder, reads
form-answer emails, optionally imports the latest JSON export from
`/Yandex.Forms/<form_id>/`, keeps every accepted answer as a separate
participant, grants participant write access once per email through Yandex Disk
UI automation, downloads newly uploaded event photos incrementally, analyzes
faces with YuNet/SFace, and remote-copies photos on Yandex Disk into
participant `__output` folders or `quarantine`.

The production flow is documented in `PIPELINE.md`. Development, architecture,
logging, and privacy rules are consolidated in `AGENTS.md`.

## 2. Next Steps

### 2.1. Architecture And Naming

- [ ] 2.1.1. Rename remaining production-facing `distribution` wording to
  `matching` where the code is specifically about face matching decisions, not
  the whole photo distribution workflow.
- [ ] 2.1.2. Rename `forms_export/ingest.py` to clearer form-import
  terminology, because the module downloads and parses Yandex Forms exports.
- [ ] 2.1.3. Move participant loading fully inside the form-import module
  boundary so callers receive imported participants through one public form
  import contract.
- [ ] 2.1.4. Review remaining config/result objects outside
  `photo_distribution_utils` and avoid shapes that mix unrelated concepts.

### 2.2. Live Product Workflow

- [ ] 2.2.1. Add a manual integration checklist for first-time browser profile
  login, Playwright browser installation, and live access-grant verification.
- [ ] 2.2.2. Decide whether processed form `answer_id` values and handled
  access emails should persist across process restarts.
- [ ] 2.2.3. Decide how reruns should handle stale participant-output files on
  Yandex Disk when the current threshold/model no longer selects them.
- [ ] 2.2.4. Add a planned stop/control mechanism if `Ctrl+C` is not enough for
  real event operation.
- [ ] 2.2.5. Decide whether participant output folders should ever get their
  own share links, or whether delivery stays inside the shared event folder.

### 2.3. Quality And Recognition

- [ ] 2.3.1. Run current quality-lab metrics after architecture cleanup to
  confirm matching behavior did not change.
- [ ] 2.3.2. Evaluate reference-photo robustness separately from detector
  quality: measure per-person recall on labeled subject faces, especially
  masks, sunglasses, dark photos, profile poses, and other hard cases that
  currently fall into quarantine.
- [ ] 2.3.3. Add a face quality/filtering stage after detection: remove very
  small distant faces, faces not looking toward the camera, and false-positive
  non-face detections before embedding/matching.
- [ ] 2.3.4. Add a photo relevance classifier/filter: do not assign a photo just
  because a participant appears somewhere in the background; prefer photos
  where the participant is an intended subject, while still allowing valid
  group photos.
- [ ] 2.3.5. Revisit whether derived-reference enrollment should move into
  production after more labeled events and people are evaluated.
- [ ] 2.3.6. Evaluate additional free recognition backends such as MagFace or
  ONNX ArcFace variants if they can be installed cleanly on the local machine.
- [ ] 2.3.7. Expand the labeled quality dataset with more participants, events,
  masks, sunglasses, dark photos, profiles, and group photos.

### 2.4. Data, Debug Persistence, And Tests

- [ ] 2.4.1. Add safe mock JSON exports and reference photos that can be
  committed.
- [ ] 2.4.2. Design a separate debug/history persistence layer if we need to
  inspect long-term runs; it must not be used as temporary state transport in
  the runtime pipeline.
- [ ] 2.4.3. Keep auditing docstrings when new modules/scripts are added.
- [ ] 2.4.4. If quality-lab reports keep growing, move larger metric tables to
  the same shared report-output style used by the freeform labeling tools.

### 2.5. Longer-Term Product Options

- [ ] 2.5.1. Investigate a proper backend/Yandex 360 alternative to the UI
  clicker if Yandex exposes a reliable API path for shared write folders.
