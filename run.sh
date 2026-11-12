#!/usr/bin/env bash
# One-command setup + launch (macOS / Linux). Dashboard: http://localhost:8000
set -e
cd "$(dirname "$0")/backend"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f data/daily.csv ] || python -m pipeline.generate_data
[ -f artifacts/candidates.pkl ] || python -m pipeline.train
if [ ! -d ../frontend/dist ]; then (cd ../frontend && npm install && npm run build); fi
uvicorn app:app --port 8000
