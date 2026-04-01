#!/usr/bin/env sh
cd "$(dirname "$0")"
exec uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
