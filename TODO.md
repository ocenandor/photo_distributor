# TODO

## Done

- [x] Create project virtual environment in `.venv`.
- [x] Create minimal `pyproject.toml`.
- [x] Document the current architecture and development sequence in `AGENTS.md`.
- [x] Initialize the git repository.

## Current Roadmap

- [ ] Step 1: Minimal Yandex Disk API integration.
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
- [x] Implement resource deletion method.
- [x] Add pytest integration tests for the Yandex Disk client.
- [x] Add a manual probe command: `python src/main.py "<yandex_event_folder>"`.
- [x] Move the service entry point to `src/main.py`.
- [x] Move Yandex Disk operations into the `src/yandex_disk` module.
- [ ] Manually verify against a real Yandex Disk folder.

## Later

- [ ] Add the expected local Yandex Forms CSV shape.
- [ ] Add local reference photo import.
- [ ] Add SQLite schema and migrations/bootstrap.
- [ ] Add YuNet/SFace recognition.
- [ ] Add database-to-Yandex-Disk copy workflow.
- [ ] Add tests when the corresponding implementation steps begin.
