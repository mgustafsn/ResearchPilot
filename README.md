# ResearchPilot

Phases 1–9: manage research projects, retrieve real scholarly papers from OpenAlex,
deduplicate and relevance-rank them with deterministic algorithms, embed and cluster
them into groups, have an LLM name each cluster and explain why a paper belongs in
it, browse the result as a research map with staged search progress and a
paper-detail drawer, manually rename subtopics, move papers, and set papers aside,
and see each paper's open-access status and links. Python 3.12+, FastAPI, SQLAlchemy,
PostgreSQL, NumPy, OpenAI (embeddings + a chat model), and a same-origin vanilla
JavaScript frontend.

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
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/004_embeddings_clusters.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/005_subtopics.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/006_search_stage.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/007_classification_explanations.sql
docker compose exec -T db psql -U researchpilot -d researchpilot -v ON_ERROR_STOP=1 < migrations/008_manual_edits.sql
uv run --env-file .env uvicorn researchpilot.api:app --host 127.0.0.1 --reload
```

Open http://127.0.0.1:8000. API documentation is at `/docs`.
Apply each numbered SQL migration once, in order; rerunning one fails without
changing existing tables. When upgrading, apply only the migrations after your last
applied number (for example, from Phase 7, apply only `008_manual_edits.sql`); Phase
9 adds no migration. Database startup never silently creates tables. Set `OPENAI_API_KEY` in `.env` before
running a search — see [Phase 4](#phase-4-embed-and-cluster).
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

## Phase 4: embed and cluster

After ranking, each successful search embeds its papers and groups them into
clusters before the run is marked complete. Clustering is deterministic; the LLM is
still not involved, and cluster names and the research map arrive in later phases.

Set an OpenAI key in `.env` — searches now require it:

```dotenv
OPENAI_API_KEY=sk-your-key
```

`OPENAI_BASE_URL` optionally points at an OpenAI-compatible embeddings endpoint. The
key is sent in the Authorization header, never in URLs or to the frontend. Restart
the server after changing configuration. Do not commit `.env`.

Each paper's title and abstract are embedded with OpenAI `text-embedding-3-small` at
512 dimensions, behind an `EmbeddingProvider` interface. Vectors are stored on the
shared `papers` table keyed by model; a later search reuses a stored vector instead
of paying to recompute it. Requests are batched; a `504` is a timeout, a `503` an
authentication or availability failure, a `502` an invalid response. A failed
embedding leaves the previous papers and clusters intact.

`clustering.py` runs k-means over the L2-normalized vectors in NumPy, choosing the
cluster count by mean silhouette. Small clusters and points far from their centroid
become **Uncategorized** (`clusterId` null). Kept clusters are relabeled by
descending size, so the assignment is stable for a given set of vectors. The
completed run reports `clusterCount`; `GET .../papers` carries each paper's
`clusterId`, and the frontend shows one tab per cluster, plus an Uncategorized tab.

`004_embeddings_clusters.sql` adds `papers.embedding` / `papers.embeddingModel`,
`project_papers.clusterId`, and `search_runs.clusterCount` without rewriting rows;
pre-Phase-4 papers re-embed on their next search.

Deliberate omissions: no research map or paper-detail UI, no manual re-clustering or
paper moves, no pgvector or nearest-neighbour search, no cross-project cluster reuse.
Clustering is lexical input turned geometric so the grouping can be verified now.

Provider tests use HTTPX mock transports; normal test runs make no external
requests. Embedding reuse and cluster persistence are covered by the search suite,
and `test_clustering.py` covers the algorithm directly.

Implementation details: [Phase 4](docs/phase-4.md).

## Phase 5: name the clusters

After clustering, an LLM labels each cluster (when there are two or more). This is
the project's first LLM call. It reuses `OPENAI_API_KEY`; no new configuration.

Each cluster's top ~6 papers by relevance (title + abstract) are sent to OpenAI
`gpt-4o-mini` behind an `LlmProvider` interface, one bounded request per cluster,
run concurrently, `temperature 0`, strict JSON-schema output. The response is
validated and trimmed into `{name, description, keywords}` (overlong fields are cut,
not rejected). Prompts live in `prompts.py`, apart from the pipeline.

Naming is best-effort: if any cluster's call fails, the search still `COMPLETED`,
those clusters keep their `Cluster N` label, and `search_runs.namingError` records
the first failure code. Unlike an embedding failure, naming never discards a result.

`005_subtopics.sql` adds a `subtopics` table keyed by `(projectId, clusterId)` and
`search_runs.namingError`. Subtopics are replaced atomically with the paper
associations on each successful search. `GET /api/projects/{uuid}/subtopics` returns
`[{clusterId, name, description, keywords}]`; the frontend shows the name on each
cluster tab and the description and keywords above that cluster's papers.

Deliberate omissions: no query expansion, no per-paper "why it belongs here"
explanations (Phase 7), no manual rename (Phase 8), no name reuse across searches
(cluster composition changes each run), no streaming, and a single vendor. The
`LlmProvider` interface leaves room for the rest.

Implementation details: [Phase 5](docs/phase-5.md).

## Phase 6: the research map

The project page is now the research map for a completed search: a summary line
(paper count, subtopic count, publication years), the cluster tab bar with a
leading **All** tab, the selected cluster's description and keywords, and its paper
list. Nothing about retrieval or the pipeline changes.

`search_runs.stage` (`006_search_stage.sql`) records pipeline progress —
`RETRIEVING`, `ANALYZING`, `EMBEDDING`, `CLUSTERING`, `NAMING` — written in a short
transaction between steps and cleared when the run finishes. The stage write is
guarded by `status = 'SEARCHING'`, so a superseded run's late writes are ignored.
The frontend already polls `GET .../searches` while a search runs and now shows the
current stage in words.

Clicking a paper opens a right-side drawer (`role="dialog"`, backdrop click / Esc /
close button, focus moved in and restored) with the full author list, publication
date and venue, publisher, citations, relevance, its cluster or subtopic name, the
DOI, source, publication, and open-access links, and the complete abstract. It
reads only fields already on `GET .../papers`; there is no new endpoint.

Deliberate omissions: no left-rail redesign, no access-status labels (Phase 9), no
manual editing (Phase 8), no settings page, no research-coverage analysis. Progress
is real but coarse: one stage at a time, no per-item counts.

Implementation details: [Phase 6](docs/phase-6.md).

## Phase 7: explain the classification

The paper drawer's "Why it's in *{subtopic}*" section is filled by an LLM, on
demand. Nothing is generated at search time.

`POST /api/projects/{uuid}/papers/{paperId}/explanation` reads the paper, its
subtopic, and the research question in one session; if the row already has an
explanation it is returned unchanged, otherwise `gpt-4o-mini` is asked (outside any
transaction, `temperature 0`, strict `{explanation}` schema) for one or two
sentences grounded only in the title and abstract, which is trimmed to 400
characters, stored on `project_papers.classificationExplanation`
(`007_classification_explanations.sql`), and returned. The endpoint is idempotent —
repeat calls cost nothing.

`404` if the paper is not in the project, `422` if it is Uncategorized or its
cluster was never named, and `502`/`503` on an LLM failure (this call is a direct
request, so unlike cluster naming the error does surface). A new search recreates
the paper associations, so stored explanations clear automatically.

The drawer requests the explanation when it opens for an eligible paper, showing a
placeholder then the text, or an error with a Retry button, and caches the result on
the in-memory paper for the session.

Deliberate omissions: no card-level explanation line (drawer only), no batch
precompute, nothing for Uncategorized papers, no regenerate beyond retry-on-error,
and the prompt gets the subtopic name but not its description.

Implementation details: [Phase 7](docs/phase-7.md).

## Phase 8: manual organization

Three edits to the AI's organization, none of which regenerate anything:

- `PATCH /api/projects/{uuid}/subtopics/{clusterId}` — `{name (1–80), description?
  (≤500)}` renames a subtopic and marks it `userModified`. `404` if that cluster has
  no subtopic.
- `PATCH /api/projects/{uuid}/papers/{paperId}` — `{clusterId?, isRelevant?}` (at
  least one). `clusterId` moves the paper to an existing cluster in the project or
  `null` for Uncategorized (`422` otherwise); `isRelevant: false` sets it aside.
  Either marks the association `userModified`. `404` for an unknown paper.
- `GET .../papers` now carries `isRelevant` and `userModified`; `GET .../subtopics`
  carries `userModified`.

`008_manual_edits.sql` adds `project_papers.isRelevant` / `.userModified` and
`subtopics.userModified` (added with a default, then the default dropped).

Manual edits are not merged across a re-clustering. `POST .../search` returns `409`
with `code: MANUAL_EDITS_PRESENT` when the project has any `userModified` subtopic or
paper; `POST .../search?force=true` proceeds and `replace_papers` /
`replace_subtopics` discard the edits as part of the normal replacement. The
frontend surfaces the `409` as "this project has manual changes — a new search will
replace them" with a **Run anyway** button.

In the UI: a **Rename subtopic** control on the selected cluster (with an "edited"
tag once changed), and, in the paper drawer, a subtopic `<select>` and a
Set aside / Restore button. Set-aside papers are hidden behind a
"Show N set aside" toggle and dimmed when shown; cluster tab counts follow the
visible papers.

Deliberate omissions: no create / delete / merge subtopics (needs subtopic
identities independent of the k-means labels — a later phase), no undo or edit
history, no per-edit attribution, and edits are discarded on re-search after
confirmation rather than reconciled.

Implementation details: [Phase 8](docs/phase-8.md).

## Phase 9: open-access status and links

Every paper carries `accessStatus`, a computed field on the API response:
`OPEN_ACCESS` when OpenAlex reports the work open or gives a free full-text URL,
`ABSTRACT_ONLY` when only an abstract is present, `UNKNOWN` otherwise.
`INSTITUTIONAL_ACCESS` (requirements §17) is reserved for future authenticated
access and is never emitted. It is derived from `isOpenAccess`, `openAccessUrl`, and
`abstract` — no storage, no migration, no extra network call. OpenAlex's
open-access data already aggregates Unpaywall and other sources, so an independent
resolver is left as a future addition.

The frontend shows an `OPEN ACCESS` / `ABSTRACT ONLY` / `UNKNOWN` pill on each paper
card and in the drawer, folds the DOI, source, publication, and free-full-text links
into one **Access & links** block, adds an **Open access only** list filter beside
the set-aside toggle, and reports the open-access count in the results summary.

Deliberate omissions: no Unpaywall or other independent resolver, no
`INSTITUTIONAL_ACCESS` / library authentication (§18), no PDF fetching or storage
(§36), and no per-paper access override.

Implementation details: [Phase 9](docs/phase-9.md).
