# TODO

## Done

- [x] Create project virtual environment in `.venv`.
- [x] Create minimal `pyproject.toml`.
- [x] Document the current architecture and development sequence in `AGENTS.md`.
- [x] Initialize the git repository.

## Current Roadmap

- [x] Step 1: Minimal Yandex Disk API integration.
- [ ] Step 2: Define the local Yandex Forms export format.
- [ ] Step 3: Build SQLite-backed recognition on mock/local data.
- [ ] Step 4: Copy photos on Yandex Disk from database results.

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
- [ ] Add YuNet/SFace recognition.
- [ ] Add database-to-Yandex-Disk copy workflow.
- [ ] Add tests when the corresponding implementation steps begin.
