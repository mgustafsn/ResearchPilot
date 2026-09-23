# Non-functional requirements and acceptance test

Date: 2026-09-23 · Status: approved design, awaiting spec review

## Problem

Requirements §31 describes quality attributes qualitatively ("without significant UI
slowdown", "handled gracefully"). None of them can pass or fail, so none are enforced.
The course report template asks for measurable NFRs (§2.3) and test evidence with results
(§5.3). §28 (error handling) and §29 (logging) are also only partly verified. At least one
requirement is currently violated: a search sends 3–6 queries through `asyncio.gather`
with no failure tolerance, so one failed query fails the whole search, which contradicts
§28 ("a failure in one provider should not necessarily fail the entire research search").
The roadmap's remaining item, "Acceptance test and logging", also asks for an automated
§38 scenario.

## Decision

Each NFR gets an ID, a measurable target, and at least one named test in a dedicated
`backend/tests/nfr/` suite that runs in CI on SQLite and PostgreSQL. An NFR that fails
when its test is first written is fixed in code, test first. Performance NFRs fail only
above a CI ceiling of 3× their target, so runner noise doesn't fail builds but real
regressions do.

## 1. NFR catalogue

All tests use fake providers unless stated; no paid API calls. "250-paper project" means
the `large_project` fixture in §2.

### Performance

| ID | Requirement | Target | CI ceiling |
|---|---|---|---|
| NFR-PERF-1 | The research map for a 250-paper project loads, with all 250 paper rows visible, from navigation start | ≤ 1.5 s | 4.5 s |
| NFR-PERF-2 | On that map, selecting a subtopic tab and toggling "Open access only" each re-render | ≤ 0.3 s | 0.9 s |
| NFR-PERF-3 | Backend analysis of 250 papers (deduplication, lexical ranking, semantic ranking, filtering, clustering) with precomputed 512-dimension vectors | ≤ 1.0 s | 3.0 s |
| NFR-PERF-4 | `GET` papers, subtopics, searches and queries for a 250-paper project, p95 over 20 calls each | ≤ 0.2 s | 0.6 s |

### Reliability and errors (§28)

- **NFR-REL-1:** each failure class below returns its documented HTTP status and error
  code, and leaves the previous completed results, subtopics and manual edits unchanged
  (one parametrised test):
  - provider unavailable (503 `UNAVAILABLE`)
  - rate limited (503 `RATE_LIMITED`)
  - timeout (504 `TIMEOUT`)
  - invalid response (502 `INVALID_RESPONSE`)
  - embedding failure (503 `EMBEDDING_UNAVAILABLE`)
  - clustering failure (502 `INTERNAL`)

  A search that finds no papers completes with `paperCount` 0 and an empty map, without
  failing.
- **NFR-REL-2:** optional LLM steps degrade instead of failing the search:
  - Query-expansion failure or invalid output falls back to keywords, then the title.
  - Cluster-naming failure or invalid output leaves numbered clusters, sets
    `namingError`, and completes the search.
  - An explanation timeout returns 504 `EXPLANATION_TIMEOUT`.
- **NFR-REL-3:** when some queries fail and at least one succeeds, the search completes
  with the surviving results. Each failure is logged with its error code, and the failed
  queries are recorded on the run. The search fails only when every query fails, with
  the first failure's code.
- **NFR-REL-4:** no stage blocks past its deadline. A hanging provider at retrieval,
  embedding or naming ends the stage with its timeout behavior: `TIMEOUT` for retrieval
  and embedding, a naming fallback for naming. Tested with hanging fakes and shortened
  deadline constants (monkeypatched).

### Security and privacy

- **NFR-SEC-1:** distinctive fake values of `OPENAI_API_KEY` and `OPENALEX_API_KEY` never
  appear in any API response body or header, any served page or asset, or any log record
  during a full run:
  - project creation, query regeneration and search
  - reading papers, subtopics, searches and queries
  - an explanation, `/api/settings/status`, and loading the project page

  The run uses the real OpenAlex and OpenAI adapters over `httpx.MockTransport`, so the
  keys really travel in request headers.
- **NFR-SEC-2:** HTML or script in provider metadata (title, abstract, venue, authors)
  renders as inert text on the paper card and in the drawer. No injected element exists
  in the DOM and no dialog fires (browser test).
- **NFR-SEC-3:** a link is rendered only for an `http:` or `https:` URL. `javascript:`,
  `data:` and other schemes coming from a provider produce no `href`.
- **NFR-SEC-4:** every write endpoint rejects unknown fields and out-of-range values with
  422. This covers project create/update, subtopic create/rename/merge, paper patch,
  query add/patch, and references create/patch.

### Observability and traceability (§29, §16, §22, §31)

- **NFR-OBS-1:** one successful search emits a log record for each §29 item:
  - each provider request
  - papers returned
  - duplicates removed
  - relevance-pipeline duration
  - clustering duration
  - each LLM call
  - LLM token usage when the provider reports it
  - total search duration

  The real adapters run over a mock transport so request and usage logging is exercised.
- **NFR-OBS-2:** provider and LLM failures log their error code and never the response
  payload, request URL or exception text. A fake failure whose message contains a
  distinctive marker must not appear in any log record.
- **NFR-TRACE-1:** every completed run persists enough to reproduce it:
  - the description (`parameters.query`) and keywords
  - the exact queries sent (`generatedQueries`) and any failed queries (`failedQueries`)
  - year range and paper limit
  - provider, `startedAt` and `finishedAt`
  - total, duplicate, filtered and paper counts
- **NFR-TRACE-2:** scholarly metadata comes only from the provider. When a fake LLM
  returns names, explanations and queries that contain metadata-like text (a DOI, a title,
  author names), every stored and served paper's metadata fields still equal the provider
  values.

### Acceptance

- **ACC-38:** one browser test walks the §38 scenario end to end with fake providers:
  1. create a project with the description "Large language models in software
     engineering"
  2. generated queries appear, and the search retrieves at least 36 papers ("several
     dozen")
  3. duplicates are removed, papers have relevance scores, and low-relevance papers are
     filtered
  4. clusters are named, the map shows subtopics with papers under them, and opening a
     paper shows its metadata and abstract
  5. the explanation appears
  6. move a paper to another subtopic, and rename a subtopic
  7. each paper has a link to its provider source
  8. every displayed title exists in the provider fixture

## 2. Suite construction

- **Shared fakes.** `RecordingProvider`, `RecordingEmbeddingProvider`,
  `RecordingLlmProvider`, `WORK`, `DATA` and `_grouped_papers` move from `test_search.py`
  to `backend/tests/fakes.py`. `test_search.py` and `test_browser.py` import them from
  there, with no behavior change.
- **Layout.** `backend/tests/nfr/` contains:
  - `conftest.py`
  - `test_nfr_performance.py`, `test_nfr_reliability.py`, `test_nfr_security.py`,
    `test_nfr_observability.py`
  - `test_acceptance.py`

  Every test name starts with its ID, e.g. `test_nfr_perf_1_map_renders_250_papers`.
  Every module sets `pytestmark = pytest.mark.nfr`.
- **`large_project` fixture.** 250 deterministic papers derived from `WORK` with unique
  ids and DOIs, in 6 marker groups. The fake embedder turns each group into its own
  direction, so clustering yields 6 subtopics and every paper passes the relevance
  filter. The fixture runs one search through the API and yields the client, the
  project URL, and a browser-app variant for the Playwright tests.
- **`budget(nfr_id, target_s, record_property)` helper.** A context manager that times
  its block with `time.perf_counter()` and records `nfr_id`, `measured_s`, `target_s`
  and `ceiling_s` through `record_property`. It fails when the time exceeds
  `target_s * 3`. p95 measurements use the same helper around a computed value.
- **Browser timing** (PERF-1/2) uses wall-clock time around the Playwright navigation or
  action until the expected DOM state holds (all rows visible, tab active, list
  re-rendered).
- **Marker.** `nfr` is registered under `[tool.pytest.ini_options] markers` in
  `pyproject.toml`. `uv run --extra dev pytest -m nfr` runs only the suite. Plain
  `pytest` still runs everything, so both CI jobs enforce it.
- **CI.** The SQLite `uv run pytest` step becomes `uv run pytest --junitxml=nfr-report.xml`.
  A following `actions/upload-artifact@v4` step (`if: always()`) uploads it as
  `test-report`.

## 3. Code changes

- **REL-3 partial retrieval failure.**
  - `SearchService._retrieve` gathers with `return_exceptions=True`. It keeps the results
    of successful queries and logs each failed query's `ProviderError` code, never the
    query text (it can contain the user's words). It raises the first failure's
    `ProviderError` only when every query failed. Non-`ProviderError` exceptions still
    propagate as today.
  - Migration `015_failed_queries.sql`:
    `ALTER TABLE search_runs ADD COLUMN "failedQueries" JSONB NOT NULL DEFAULT '[]'::jsonb;`
    Add the `scripts/migrate.py` bootstrap entries for 15, `SearchRunRow.failedQueries`,
    and `SearchRun.failedQueries: list[str] = []`.
  - The search panel shows "N of M queries failed; results come from the rest." when
    `failedQueries` is non-empty.
- **Anything else the suite exposes** is fixed test-first within this work when the fix
  is local (a few lines, no new schema or API contract). A failure that needs a design
  decision stops the work and goes back to the user.

## 4. Requirements and docs

- `docs/requirements.md` §31 keeps its six attribute headings and gains a table: ID,
  requirement, target, CI ceiling, test name. It adds: "Every NFR in this table is
  enforced by the automated suite and must pass in CI." §28 and §29 each gain a line
  referencing their NFR IDs.
- `docs/features/non-functional-requirements.md`, in the short prose style, records the
  suite, the locally measured values from the first green run, and which NFRs failed at
  first and how they were fixed.
- `docs/roadmap.md`: "Acceptance test and logging" moves from Planned to Delivered as
  "Non-functional requirements and acceptance test". Version 0.18.0 in `pyproject.toml`,
  `uv.lock`, and both `ResearchPilot/0.18` User-Agent strings.
- `docs/report.md` and the untracked report files are not edited. The final hand-off
  tells the user that report §2.3 says query expansion "falls back to the original
  question", which is outdated.

## 5. Testing and verification

- Every NFR test is written first. A test that passes immediately documents existing
  behavior and needs no code change. A test that fails drives a fix.
- Gate: ruff check, ruff format, `node --check`, `uv build`, the full SQLite suite and the
  full PostgreSQL suite. The PostgreSQL run applies migration 015.
- The browser NFR tests run three times locally before merge to catch flakiness, the
  failure mode seen today in CI.

## Out of scope

Load and concurrency testing beyond the existing concurrent-search test, accessibility
audits, dependency CVE scanning, maintainability metrics, and real-provider (paid) runs.
