@echo off
REM One-command setup + launch (Windows). Dashboard: http://localhost:8000
cd /d %~dp0backend
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements-train.txt
if not exist data\daily.csv python -m pipeline.generate_data
if not exist artifacts\candidates.pkl python -m pipeline.train
if not exist ..\frontend\dist (cd ..\frontend && npm install && npm run build && cd ..\backend)
uvicorn app:app --port 8000
