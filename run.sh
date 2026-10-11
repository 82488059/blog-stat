#!/usr/bin/env bash
# Blog stats API — bind 127.0.0.1 ONLY. Do NOT use 0.0.0.0.
# Expose publicly via nginx reverse proxy to /api/, never open port 3001.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export STAT_DATA_DIR="${STAT_DATA_DIR:-$PWD/data}"
# Optional:
#   export STAT_PAGES_TOKEN=...
#   export STAT_CORS_ORIGINS=https://www.xssl.online,https://82488059.github.io
#   export STAT_RATE_LIMIT_MAX=120

exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 3001
