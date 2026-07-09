# Photo Distributor

Local Python prototype for distributing event photos from a shared Yandex Disk
folder into per-person output folders.

Participants submit consent, name, email, and reference photos through Yandex
Forms. The service imports form answers from the `Yandex.Forms` mail folder and
can also read the latest JSON export from `/Yandex.Forms/<form_id>/` on Yandex
Disk. It then runs local face detection and recognition with OpenCV YuNet and
SFace, builds a copy plan, and copies original event photos on Yandex Disk into
participant folders or `quarantine`.

## What It Does

- imports Yandex Forms answers from email and optional Disk JSON export;
- grants event-folder write access through Yandex Disk UI automation;
- downloads readable event photos into a local cache for analysis;
- matches event faces against participant reference photos locally;
- creates `__output` folders for matched participants;
- copies unmatched event photos into `quarantine`.

Source event photos are copied on Yandex Disk. They are not moved or deleted.

## Run

```powershell
python src/start_event.py <form_id> [cloud_event_folder]
```

If `cloud_event_folder` is omitted, the runner creates an event folder name. The
process keeps polling form sources and the event photo folder until `Ctrl+C`.

On Git Bash for Windows, the helper script forwards arguments to the same
production command:

```bash
./run.sh <form_id> [cloud_event_folder] [start_event options]
```

## Development

```powershell
python -m pytest
```

See [`PIPELINE.md`](PIPELINE.md) for the full runtime flow, module boundaries,
local artifacts, and Yandex Disk side effects.
