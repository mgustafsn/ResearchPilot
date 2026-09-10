# ResearchPilot

Phase 1: save, browse, open, edit, and delete research projects. Python 3.12+, FastAPI,
SQLAlchemy, PostgreSQL, and a same-origin vanilla JavaScript frontend.

## Run locally

Install Python and [uv](https://docs.astral.sh/uv/getting-started/installation/), plus Docker Compose.
From the repository root:

```sh
uv sync --extra dev
cp .env.example .env
docker compose up -d --wait
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/001_projects.sql
uv run --env-file .env uvicorn researchpilot.api:app --host 127.0.0.1 --reload
```

Open http://127.0.0.1:8000. API documentation is at `/docs`.
The initial SQL migration is applied once to an empty database; rerunning it fails
without changing an existing schema. Database startup never silently creates tables.
Docker's named volume persists projects across restarts. The Compose password is
only a local development credential. This phase is a local single-user application;
authentication and public deployment are outside its scope.

## Validate

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
node --check frontend/app.js
uv build
```

Default tests use a temporary SQLite database for fast CRUD checks. To exercise the
actual PostgreSQL migration and persistence, create a separate **empty disposable**
database and run the same suite against it:

```sh
docker compose exec db createdb -U researchpilot researchpilot_test
TEST_DATABASE_URL=postgresql+psycopg://researchpilot:local-development@localhost:5432/researchpilot_test uv run pytest
```

The integration fixture creates and drops the project table for each test. Never
point `TEST_DATABASE_URL` at your application database.
Run the application from this checkout: the frontend is a sibling source directory,
not bundled inside the Python wheel.

## Design and API

`backend/researchpilot/domain.py` validates input. `service.py` owns project lifecycle
and timestamps. `persistence.py` owns SQLAlchemy records and database operations.
`api.py` maps HTTP requests, owns per-request transactions, and serves the frontend.
Configuration and connection URLs remain on the server.

- `POST /api/projects`: create (201, Location header).
- `GET /api/projects`: list, most recently updated first.
- `GET /api/projects/{uuid}`: retrieve.
- `PUT /api/projects/{uuid}`: replace all editable fields.
- `DELETE /api/projects/{uuid}`: delete (204).

Title (1–200 characters) and research question (1–5000) are required and trimmed.
Keywords default to an empty list, with at most 30 entries of 1–100 characters;
duplicates are removed case-insensitively. Years are optional integers from 1–9999
with start no later than end. Paper count is optional, from 1–1000. Omitting optional
fields during PUT clears them. Invalid input returns 422; absent projects return 404.
Database failures return a generic 503 without exposing connection information.

Each project has a UUID, editable fields, UTC creation/update timestamps, and a
server-controlled `CREATED` status. Later phases can attach queries, project-paper
relationships, relevance, embeddings, subtopics, overrides, and search runs through
foreign keys to this UUID. No future tables or provider stubs are included.

The existing files in `docs/` and `AGENTS.md` remain the source of truth. Scholarly
APIs provide facts; deterministic algorithms provide structure; LLMs provide
interpretation; users retain final control. Phase 1 makes no scholarly or LLM calls.
