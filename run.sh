#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./run.sh <form_id> [cloud_event_folder] [start_event options]" >&2
  exit 2
fi

export MSYS2_ARG_CONV_EXCL="*"
exec .venv/Scripts/python.exe src/start_event.py "$@"

# ./run.sh 6a4ead19068ff048b6c4aca3 /test_pavel --form-poll-seconds 30 --event-poll-seconds 30 --debug-logs 