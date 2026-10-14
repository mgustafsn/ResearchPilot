# ResearchPilot

Manage research projects, retrieve real scholarly papers from OpenAlex or Scopus,
deduplicate them, score relevance by embedding similarity to the research question,
cluster them into groups, have an LLM name each cluster and explain why a paper belongs in
it, browse the result as a research map with staged search progress and a
paper-detail drawer, manually rename subtopics, move papers, and set papers aside,
and see each paper's open-access status and links. Python 3.12+, FastAPI, SQLAlchemy,
PostgreSQL, NumPy, OpenAI (embeddings + a chat model), and a same-origin vanilla
JavaScript frontend.

## Run locally

Install Python and [uv](https://docs.astral.sh/uv/getting-started/installation/), plus Docker Compose.
From the repository root:

```sh
./scripts/start-local.sh
```

Open http://127.0.0.1:8000. API documentation is at `/docs`.
The launcher creates `.env` from `.env.example` on first run, waits for the database,
applies pending migrations, and starts the backend. Add `OPENAI_API_KEY` to `.env`
before running a literature search. Docker's named volume persists projects across
restarts. The Compose password is deliberately for local development only.
This phase is a single-user application; multi-user accounts are outside its scope.

## Prepare a private Heroku deployment

The root `Procfile` starts one web process and applies database migrations during each
Heroku release. The Python buildpack installs dependencies from `uv.lock` and
`pyproject.toml`; `.python-version` selects Python 3.12. Heroku supplies `DATABASE_URL`
when Heroku Postgres is attached. The app converts that URL for psycopg and requires TLS
on a Heroku dyno.

1. Redeem the GitHub Student Developer Pack Heroku offer, create a Heroku app, and
   attach Heroku Postgres (Essential-0 is sufficient to start). Set the app to use the
   Python buildpack if Heroku does not detect it automatically.
2. In Heroku's Config Vars, set `RESEARCHPILOT_PASSWORD` to a unique password of at
   least 16 characters. Set `OPENAI_API_KEY` there before searching. Set optional
   provider keys only when needed. Never commit these values or set `DATABASE_URL`
   yourself on Heroku.
3. Deploy the repository. The release process creates or upgrades the schema before
   the web process starts. Check the release logs and open `https://YOUR_APP.herokuapp.com`.
   The browser prompts for username `researchpilot` and the password from step 2.
4. Schedule daily Postgres backups: `heroku pg:backups:schedule DATABASE_URL --at
   '02:00 Europe/Helsinki' --app YOUR_APP`. Check the schedule and occasionally
   download and restore a backup to verify it.

The hosted app redirects HTTP to HTTPS and requires the password for pages, static
files, API calls, and API documentation. This is single-user HTTP Basic access, so
use a strong, unique password and access the site only over HTTPS. Heroku's Basic
dyno stays on; Eco dynos sleep when idle. Hosted literature searches return `202`
immediately and continue on the web dyno while the page polls their saved status.
A dyno restart can interrupt a search; its database lease expires after four minutes,
after which it can be retried. Run only one web dyno for this setup.

Deployment creates a new, empty database; it does not copy projects from your desktop.
Before switching to the hosted app, export your local PostgreSQL database and import
it using [Heroku's Postgres import/export guide](https://devcenter.heroku.com/articles/heroku-postgres-import-export).
Keep a local backup until you verify your projects and references on Heroku. Thereafter,
use the hosted app from both computers so there is only one database to update.

## Validate

```sh
uv run playwright install chromium
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

## Local GitHub issue agent

The optional issue agent runs a local Ollama model through Aider in a separate Git
worktree, then validates the diff and repository checks before pushing a draft PR.
It is manually started for one open issue at a time. It does not merge PRs.

Install Ollama and Aider outside the project environment, then pull the starter model:

```sh
uv tool install aider-chat --python 3.12
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
gh auth login
```

Start `ollama serve` if Ollama is not already running, and run from this checkout:

```sh
uv run python scripts/issue_agent.py 123
```

The runner only accepts changes to `README.md`, `docs/`, `backend/researchpilot/`,
`backend/tests/`, and `frontend/`, with a limit of five files and 250 changed lines.
It rejects config, migration, script, and CI changes. It runs pytest, Ruff, the
frontend JavaScript syntax check, and `uv build`. Failed runs leave their worktree at
`.agent-worktrees/issue-<number>` for inspection; successful runs leave it there too.
Review the draft PR before marking it ready or merging it.

## Current behavior

The demo implements project CRUD, OpenAlex or Scopus retrieval, deterministic DOI/identity/title
deduplication, embedding-based relevance scoring and clustering, structured
LLM subtopic naming, a research map, paper details, on-demand explanations, manual
organization, and provider-derived open-access labels and links.

The research description is never searched directly. The LLM turns it and the keywords
into 3–6 short keyword queries; if that fails, keywords (or the project name) are used.
Every query used is saved with the search run and shown in the search panel. Retrieval
divides the paper limit across the enabled queries before deduplication and ranking.
Relevance is the cosine similarity between the embedded research description (plus
keywords) and each paper's title/abstract embedding, calibrated linearly
so cosine 0.25 is 0% and 0.60 is 100%. Stopword-filtered lexical overlap only breaks ties.
Papers below 40% are filtered before clustering; the count is shown in the search
summary.
Users can set retained papers aside and restore them.
The paper list can be ordered by relevance, citation count, publication date, or title;
sorting applies within every subtopic and keeps the selected order when filters refresh.
The References tab stores selected search papers and manually entered citations,
including unlinked drafts. Notes belong to the project and remain available after later
searches. Add or edit notes inline on any reference with explicit Save and Cancel; unsaved
drafts survive filtering, tab switches, and refreshes, and leaving the page with an unsaved
draft asks for confirmation. A reference can be marked as cited, optionally with a unique citation number;
unciting keeps the old number so it can be restored. References are listed by title.
Each saved reference has a separate reading status: To read, Reading, or Read. Change it
directly in the References tab and filter the list by status. New and existing
references default to To read; progress belongs to each project and survives later
searches. The filter resets to All when reopening a project. Apply migrations
`016_reference_reading_status.sql` through `018_reference_citation_tracking.sql` before
starting this version (the local launcher applies pending migrations automatically).

Scholarly metadata comes only from `PaperProvider` implementations. Embeddings and
LLM interpretation use separate interfaces. OpenAI supplies title/abstract embeddings
and structured cluster names and explanations; it never supplies authoritative paper
metadata. Configuration and API keys stay on the server in environment variables.
Set `OPENAI_API_KEY` before searching. OpenAlex remains the default scholarly source.
To use Scopus, set `SCHOLARLY_PROVIDER=scopus` and `ELSEVIER_API_KEY` in `.env`.
Set `SCHOLARLY_PROVIDER=openalex,scopus` to search both; duplicates merge, and if one
source fails the search completes with the other and says so.
Scopus access also depends on your institution's API entitlement and network or VPN.
The Scopus adapter uses the STANDARD search view, which can be available even when
abstract access is not granted. Relevance and clustering then use titles when Scopus
does not provide abstracts. Its API key is sent only from the backend. Optional `OPENAI_BASE_URL`,
`OPENALEX_API_KEY`, and `OPENALEX_EMAIL` configure the other adapters.

Successful searches atomically replace paper associations and subtopics. Failed
searches preserve previous results and manual edits. Shared paper metadata is
refreshed across projects; historical result sets are not versioned. Apply migration
010–012 before using query expansion or relevance filtering with an existing database.
Embeddings are
reused only when paper identity, provider, model, dimension, and normalized input
hash match. Vectors and their cache metadata are saved together, including reused
vectors. Legacy cache entries without hashes are regenerated on demand.

### Progress, timeouts, and editing

`POST /api/projects/{id}/search` waits for the pipeline to finish. The UI polls
`GET .../searches` alongside that request and displays retrieval, analysis, embedding,
clustering, and naming stages. Transient polling errors are retried. Controls stay
locked until the pending request settles, even if an early history response still
shows an earlier completed run.

Retrieval and embedding each have a 60-second deadline. Cluster naming runs
concurrently with a 30-second deadline per cluster and is best-effort: naming failure
leaves numeric cluster labels. A 240-second search lease releases interrupted workers
on the next history read, search, or edit. Late workers cannot replace newer results.
These are stage deadlines, not a one-minute deadline for the whole search.

Project edits, deletion, renames, moves, and relevance changes return 409 during an
active search. The UI disables organization controls, including an already-open
drawer. A new search over manual edits requires explicit **Run anyway** confirmation
(`force=true`). Unconfirmed operations preserve those edits.

Saved named categories remain available when empty, with rename controls. Move
choices use all saved categories and all papers, independent of filters, and always
include Uncategorized. Filters change displayed papers and counts only. Renaming
without a description preserves it. Relevance patches require a boolean when present;
`clusterId: null` moves a paper to Uncategorized.

Explanations are requested when a named paper's drawer opens. Cached text is reused
only for the same search run, question, title/abstract, and category identity/name/
description. Moves and category edits clear affected explanations. Context changes
during generation return 409 and the UI refreshes before another request. Concurrent
requests for identical context return the first valid stored result. Explanation
provider timeouts and the 30-second outer deadline return 504 with code
`EXPLANATION_TIMEOUT`; Retry is manual. Other provider errors return 502 or 503.

### API

- `/api/projects`: GET list, POST create.
- `/api/projects/{id}`: GET, PUT project fields, DELETE.
- `/api/projects/{id}/search`: POST; optional `force=true` confirms replacement.
- `/api/projects/{id}/searches`: GET latest 20 attempts and progress.
- `/api/projects/{id}/papers` and `/subtopics`: GET saved results.
- `/api/projects/{id}/queries`: GET the saved list; POST to regenerate suggestions
  (keeps user queries); POST `/custom` to add one. PATCH `/{queryId}` with a JSON body
  (`query` and/or `enabled`) edits it; DELETE `/{queryId}` removes it.
- `/api/projects/{id}/papers/{paperId}`: PATCH `clusterId` and/or `isRelevant`.
- `/api/projects/{id}/subtopics/{clusterId}`: PATCH `name` and optional `description`.
- `/api/projects/{id}/subtopics`: POST to create; DELETE a cluster or POST
  `/{clusterId}/merge` with `targetClusterId` to merge.
- `/api/projects/{id}/papers/{paperId}/explanation`: POST cached or generated explanation.
- `/api/projects/{id}/references`: GET list and POST manual citation.
- `/api/projects/{id}/references/from-paper/{paperId}`: POST to save a search paper.
- `/api/projects/{id}/references/{referenceId}`: PATCH or DELETE a saved reference.
  Reference responses include `isCited`, `citationNumber`, and read-only
  `previousCitationNumber`; a number requires `isCited` and is unique per project.
  Reference responses include `readingStatus` (`TO_READ`, `READING`, `READ`); creation
  and PATCH accept it independently of publication `status`. Omitted PATCH fields
  remain unchanged; null or invalid reading statuses return 422.
- `/api/settings/status`: GET provider configuration flags without credentials.

Invalid input returns 422, missing resources 404, conflicts 409, and database failures
503. See `/docs` for schemas. The browser and provider tests use fake providers and
HTTPX mock transports; no paid provider calls are required.

## Remaining MVP work

The current MVP covers query expansion and selection, relevance filtering, manual
subtopic management, card-level explanations, and settings/navigation. Remaining
follow-up work is the requirements' end-to-end acceptance scenario and broader logging
coverage. See the [roadmap](docs/roadmap.md). Notes in `docs/features/` describe each
feature at the time it shipped; this README describes current behavior.
