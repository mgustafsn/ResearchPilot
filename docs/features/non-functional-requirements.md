# Non-functional requirements

Requirements §31 used to describe quality attributes qualitatively — "without significant
UI slowdown", "handled gracefully" — so none of them could pass or fail. Each attribute now
has an ID, a measurable target, and at least one named test in `backend/tests/nfr/`, listed
in full in requirements §31's "Measurable requirements" table. `uv run --extra dev pytest -m
nfr` runs just the suite; plain `pytest` still runs it as part of the full run. Performance
tests fail only above a CI ceiling of 3× their target, so runner noise doesn't fail builds
but real regressions do. CI writes a JUnit report (`nfr-report.xml`) and uploads it as the
`test-report` artifact, so measured values are visible without re-running anything locally.

Shared fixtures live in `backend/tests/fakes.py` (fake providers) and
`backend/tests/live.py` (the Playwright browser helper); `test_search.py` and
`test_browser.py` import the fakes from there too, unchanged.

## Measured values

Locally measured, best of 3 runs, in seconds:

| NFR | Measured | Target | CI ceiling |
| --- | --- | --- | --- |
| NFR-PERF-1 | 0.313 | 1.5 | 4.5 |
| NFR-PERF-2 (tab) | 0.027 | 0.3 | 0.9 |
| NFR-PERF-2 (filter) | 0.158 | 0.3 | 0.9 |
| NFR-PERF-3 | 0.125 | 1.0 | 3.0 |
| NFR-PERF-4 (`/papers`, p95) | 0.014 | 0.2 | 0.6 |
| NFR-PERF-4 (`/subtopics`, p95) | 0.0016 | 0.2 | 0.6 |
| NFR-PERF-4 (`/searches`, p95) | 0.0020 | 0.2 | 0.6 |
| NFR-PERF-4 (`/queries`, p95) | 0.0014 | 0.2 | 0.6 |

## Initial failures and fixes

Two NFRs failed when their tests were first written, and both were fixed in the product,
test first:

- **NFR-REL-3.** `SearchService._retrieve` sent every query through `asyncio.gather` with
  no failure tolerance, so one failed query failed the whole search — a direct violation of
  §28 ("a failure in one provider should not necessarily fail the entire research search").
  `_retrieve` now gathers with `return_exceptions=True`, keeps the results of the queries
  that succeeded, and logs each failure's error code, never the query text. It raises only
  when every query fails, with the first failure's code. It also raises that first failure's
  code, keeping the project's previous results, when at least one query fails and the
  surviving queries together found zero papers, rather than completing with an empty result.
  Migration 015 adds
  `search_runs."failedQueries"` (`JSONB NOT NULL DEFAULT '[]'`) so the run records which
  queries failed, and the search panel shows "N of M queries failed; results come from the
  rest." when that list is non-empty.
- **NFR-OBS-1.** The "Search analyzed" log line was missing the §29 "duplicates removed"
  count. It now includes `duplicates=` alongside the other counts.

Every other NFR passed on first run. Some test-side hardening happened during review —
`junit_family = "xunit1"` to keep `record_property` output warning-free, and stronger
NFR-PERF-2/SEC/OBS assertions — but that was test-only, not a product fix.

Because neither `backend/tests/` nor `backend/tests/nfr/` has an `__init__.py`, and each
has its own `conftest.py`, pytest can lose track of which `conftest.py` applies partway
through an unusual explicit invocation: an NFR test node listed first, then a path outside
`backend/tests/nfr/`, then another NFR test file. For example,
`uv run --extra dev pytest backend/tests/nfr/test_nfr_security.py::test_nfr_sec_2_metadata_html_is_inert backend/tests/test_browser.py backend/tests/nfr/test_nfr_performance.py`
collects `test_nfr_performance.py`'s tests without ever loading
`backend/tests/nfr/conftest.py`, so its `large_browser` and `large_api` fixtures come back
"fixture not found". `-m nfr`, running the `backend/tests/nfr/` directory on its own, the
full suite, and CI are all unaffected — only that specific ordering of mixed paths trips
it.
