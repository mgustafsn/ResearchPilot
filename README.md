# ResearchPilot

Phases 1–3: manage research projects, retrieve real scholarly papers from OpenAlex, and
deduplicate and relevance-rank them with deterministic algorithms. Python 3.12+, FastAPI,
SQLAlchemy, PostgreSQL, and a same-origin vanilla JavaScript frontend.

## Run locally

Install Python and [uv](https://docs.astral.sh/uv/getting-started/installation/), plus Docker Compose.
From the repository root:

```sh
uv sync --locked --extra dev
cp .env.example .env
docker compose up -d --wait
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/001_projects.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/002_scholarly_search.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/003_deduplication_relevance.sql
uv run --env-file .env uvicorn researchpilot.api:app --host 127.0.0.1 --reload
```

Open http://127.0.0.1:8000. API documentation is at `/docs`.
Apply each numbered SQL migration once, in order; rerunning one fails without
changing existing tables. If upgrading from Phase 1, apply `002` and `003`; from Phase 2,
apply only `003_deduplication_relevance.sql`. Database startup never silently creates tables.
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

The integration fixture applies all SQL migrations and drops the application tables for each test. Never
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
foreign keys to this UUID. The Phase 2 tables are described below; later-phase features remain unimplemented.

The existing files in `docs/` and `AGENTS.md` remain the source of truth. Scholarly
APIs provide facts; deterministic algorithms provide structure; LLMs provide
interpretation; users retain final control. Only the OpenAlex provider makes scholarly calls. No LLM is used.


## Phase 2: search scholarly papers

Open a saved project and click **Find papers**. The backend sends the saved research
question verbatim to OpenAlex, applies an inclusive publication-year range, and
retrieves up to the saved paper limit (100 when omitted, maximum 1000). Keywords
remain project notes in this phase; they are retained in the search snapshot but do
not silently change the query. OpenAlex returns results in its own order;
deduplication and relevance ranking are applied afterwards in Phase 3 (below).
ResearchPilot does not generate categories yet.

OpenAlex currently supports basic keyless requests. For a larger daily allowance,
get a free key from https://openalex.org/settings/api and add it to your local `.env`:

```dotenv
OPENALEX_API_KEY=your-key
OPENALEX_EMAIL=your-contact-email
```

Both are optional. Restart the server after changing configuration. Keys are sent
in the Authorization header, never in URLs or frontend configuration. Do not commit
`.env`. [OpenAlex authentication documentation](https://help.openalex.org/api/authentication/).

New endpoints:

- `POST /api/projects/{uuid}/search`: run a bounded search and return its completed
  search record (200). This request waits for retrieval, up to 60 seconds.
- `GET /api/projects/{uuid}/searches`: latest 20 attempts, newest first, including
  exact query, filters, original question, keywords, provider, timestamps, status,
  counts, and safe error information. Can be polled while POST is running.
- `GET /api/projects/{uuid}/papers`: normalized papers from the last successful run,
  ordered by descending Phase 3 relevance, each carrying a `relevanceScore`.

Successful searches atomically replace a project's paper associations, including
when there are zero matches. Failed searches leave the last successful papers
intact. Search records remain as history; old result sets are not versioned. Global
paper metadata is shared across projects and refreshed on retrieval. The UI marks
results whose query/filter snapshot differs from the current project details.

The `PaperProvider` protocol separates retrieval from business logic. OpenAlex's
adapter normalizes metadata, reconstructs supplied abstract indexes, and leaves
missing information null. `papers`, `project_papers`, and `search_runs` store shared
metadata, project associations, and search provenance. Stable provider identities
make repeat imports idempotent; cross-provider DOI and title deduplication is added
in Phase 3. Provider-reported open-access fields are stored, without a separate
resolver, full-text downloads, or access-status inference.

While searching, a project rejects another search, edits, and deletion with 409.
PostgreSQL row locks coordinate concurrent requests. Network requests run outside
database transactions. A 60-second timeout bounds retrieval; a 120-second lease
allows interrupted searches to recover when history is read or the project is
next searched/edited. Late workers cannot overwrite a newer attempt.

Timeouts return 504. Provider rate limits, authentication rejection, and unavailable
services return 503; rejected queries, invalid responses, or unexpected search errors
return 502. Retrying is manual to avoid repeated paid or rate-limited calls. Logs
contain provider/page, search IDs, counts, and safe error codes, not credentials or
arbitrary upstream response bodies.

Provider tests use HTTPX mock transports and a trimmed real OpenAlex response in
`backend/tests/fixtures/openalex_work.json`, retrieved September 10, 2026 from
`https://api.openalex.org/works?search=large%20language%20models%20software%20engineering&per_page=2&cursor=*`.
Normal test runs make no external requests. The PostgreSQL suite also checks
concurrent search exclusion. The SQLite suite skips that production-specific test.

Implementation details: [Phase 2](docs/phase-2.md).

## Phase 3: deduplicate and rank

After retrieval, every successful search deduplicates its papers and assigns each a
relevance score before persistence. Both steps are deterministic and use no LLM.
Nothing about the search request or the OpenAlex query changes.

Deduplication merges records by normalized DOI, then by provider identity, then by
normalized title, transitively. Conflicting explicit DOIs are never merged on a
matching title alone. Merges fill gaps only: authoritative values from the richer
record stay put. The completed search record reports `duplicateCount`; project paper
associations and shared `papers` metadata hold only the surviving records.

Relevance ranking scores each paper by weighted term coverage of the research
question and keywords, with a corpus IDF weight that rewards discriminating terms,
higher weight for title matches than abstract or venue matches, and a small bonus
for a verbatim question match in the title. Scores are in `[0, 1]`, stored on
`project_papers.relevanceScore`, and stable for a given input. `GET .../papers`
returns papers in descending score order; ties fall back to citation count, then
title, then identity. The frontend shows each paper's relevance percentage and, when
duplicates were merged, a note beneath the results.

The second and third columns are added by `003_deduplication_relevance.sql` without
rewriting existing rows; pre-Phase-3 associations read back as score `0`.

Deliberate omissions: no embeddings, clustering, subtopics, LLM query expansion or
reranking, semantic similarity, cross-provider identifier reconciliation beyond DOI,
or user relevance overrides. Ranking is lexical and explainable so results can be
verified now, ahead of the Phase 4 embedding pipeline.

Implementation details: [Phase 3](docs/phase-3.md).
