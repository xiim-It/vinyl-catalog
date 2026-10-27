#!/usr/bin/env bash
# Vinyl Catalog v3 — start script (macOS / Linux / Raspberry Pi)
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
VENV=".venv"
if [ ! -d "$VENV" ]; then
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
echo "Launching Vinyl Catalog on http://127.0.0.1:8501 (LAN: http://<host-ip>:8501) ..."
"$VENV/bin/python" -m app.api.server
