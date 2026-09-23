#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop or Docker Engine with Compose." >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Add OPENAI_API_KEY before running a search."
fi

echo "Starting PostgreSQL..."
docker compose up -d --wait db

echo "Applying database migrations..."
uv run --env-file .env python scripts/migrate.py

if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
  echo "ResearchPilot is already running at http://127.0.0.1:8000"
  exit 0
fi

echo "Starting ResearchPilot at http://127.0.0.1:8000"
exec uv run --env-file .env uvicorn researchpilot.api:app --host 127.0.0.1 --port 8000 --reload
