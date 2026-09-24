# Multi-source Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one search query OpenAlex and Scopus together, merge the results with the existing deduplication, and complete with a warning when one source fails.

**Architecture:** A new `MultiSourceProvider` implements the existing `PaperProvider` protocol and fans each query out to its sources. `SearchService` therefore keeps a single provider. A new `failedSources` field carries partial failures from `SearchResult` through `CompletedSearch` to `search_runs`. After semantic ranking, the pipeline caps the unique papers at `maxPaperCount`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / httpx / pydantic, PostgreSQL migrations, vanilla JS frontend, pytest + Playwright (Chromium).

**Spec:** `docs/superpowers/specs/2026-09-24-multi-source-search-design.md`

## Global Constraints

- Sources are configured only by the server env var `SCHOLARLY_PROVIDER`, a comma list of `openalex`/`scopus`. The default is `openalex`.
- `scopus` in the list requires `ELSEVIER_API_KEY`. The key is never returned to the browser or logged.
- Never log query text or provider payloads. Log the source name and error code only.
- A merged paper keeps one `source`/`sourceId`. The `papers` schema does not change.
- Business logic depends on `PaperProvider`, never directly on the OpenAlex or Scopus classes. Only `api.py` wiring imports them.
- One additive numbered migration (`017_failed_sources.sql`) plus a `scripts/migrate.py` bootstrap entry.
- No new dependencies.
- Bump the minor version in `pyproject.toml` and in the two `ResearchPilot/0.N` User-Agent strings in `config.py`, then run `uv lock`.

## Coordination and prerequisite

- **Prerequisite (Task 0):** Scopus retrieval (`providers/scopus.py`, `scholarly_provider()`, `scopus_headers()`) must be on `main`. It currently exists only as uncommitted work in the main checkout.
- **Codex is editing the frontend layout, styles, and browser tests.** This feature touches only two frontend spots: the Settings "Scholarly papers" source panel in `renderSettings` (`app.js` ~206–230) and one line next to the failed-queries warning in the search panel (`app.js` ~1033). Tasks 1–4 are backend only. Task 5 runs **after Codex's refresh lands on `main`**: rebase first, then make the same semantic change in whatever markup Codex left.

## Deviation from the spec

The spec says `/api/settings/status` *replaces* `scholarlyProvider`. This plan keeps `scholarlyProvider`, which becomes the joined name, e.g. `OpenAlex+Scopus`, and adds `scholarlyProviders`, a list of display names. Existing UI and tests keep working, which avoids churn in files Codex is editing. The spec is updated in Task 6.

## Review Focus

1. **Both sources fail for every query.** The run must fail with the first error and keep the previous results, exactly as a single-source failure does today. The multi-source "all fail" test and the existing NFR-REL tests pin this (Task 2).
2. **A duplicate across sources where the Scopus copy has the richer record.** A Scopus record can have more fields filled but no abstract. `_merge` must still fill the abstract from the OpenAlex copy. The merge test is in Task 3.
3. **Mixed-case or padded env values (`" OpenAlex , scopus "`) and a repeated name (`openalex,openalex`).** These must parse to `["openalex", "scopus"]` and `["openalex"]` rather than crash or double-query (Task 1).
4. **More unique papers than `maxPaperCount` after merging.** The saved papers plus filtered papers must equal the limit, not exceed it (Task 3).
5. **A failed source on an old run in history.** Runs stored before migration 017 must read `failedSources == []` and render no warning. The migration backfill test is in Task 3, and the empty-list default is covered in the browser test (Task 5).

---

### Task 0: Rebase onto Scopus retrieval

**Files:** none changed.

- [ ] **Step 1: Confirm Scopus retrieval is on `main`**

Run: `git -C ../ResearchPilot log main --oneline -5 && git -C ../ResearchPilot show main:backend/researchpilot/providers/scopus.py | head -5`
Expected: the file exists on `main`. If it does not, stop and ask the user. Do not commit the main checkout's work-in-progress yourself.

- [ ] **Step 2: Rebase the feature branch**

Run (in `../ResearchPilot-multi-source-search`): `git rebase main`
Expected: the only branch commit is the spec and plan, and it rebases cleanly.

- [ ] **Step 3: Baseline**

Run: `uv run --extra dev pytest -q`
Expected: all pass. Record the count.

---

### Task 1: Parse a comma list of sources

**Files:**
- Modify: `backend/researchpilot/config.py` (`scholarly_provider` → `scholarly_providers`)
- Modify: `backend/researchpilot/api.py:20,62` (import and call site only; the full wiring is in Task 4)
- Test: `backend/tests/test_scopus.py` (`test_scopus_configuration`)

**Interfaces:**
- Produces: `config.scholarly_providers() -> list[str]`, an ordered and de-duplicated list of ids from `{"openalex", "scopus"}`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_scopus.py`, change the import to `from researchpilot.config import scholarly_providers, scopus_headers` and replace `test_scopus_configuration` with:

```python
def test_scopus_configuration(monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "scopus")
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    assert scholarly_providers() == ["scopus"]
    assert scopus_headers()["X-ELS-APIKey"] == "test-secret"
    monkeypatch.delenv("ELSEVIER_API_KEY")
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        scholarly_providers()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["openalex"]),
        ("openalex,scopus", ["openalex", "scopus"]),
        (" OpenAlex , SCOPUS ", ["openalex", "scopus"]),
        ("scopus,openalex", ["scopus", "openalex"]),
        ("openalex,openalex", ["openalex"]),
        ("openalex,,scopus", ["openalex", "scopus"]),
    ],
)
def test_scholarly_provider_lists(monkeypatch, value, expected):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    if value is None:
        monkeypatch.delenv("SCHOLARLY_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("SCHOLARLY_PROVIDER", value)
    assert scholarly_providers() == expected


@pytest.mark.parametrize("value", ["", " , ", "pubmed", "openalex,pubmed"])
def test_scholarly_provider_rejects_invalid_lists(monkeypatch, value):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", value)
    with pytest.raises(RuntimeError, match="SCHOLARLY_PROVIDER"):
        scholarly_providers()


def test_scopus_in_a_list_still_requires_its_key(monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "openalex,scopus")
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        scholarly_providers()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest backend/tests/test_scopus.py -q`
Expected: collection error, `ImportError: cannot import name 'scholarly_providers'`.

- [ ] **Step 3: Implement**

In `backend/researchpilot/config.py`, replace `scholarly_provider()` with:

```python
SCHOLARLY_PROVIDERS = ("openalex", "scopus")


def scholarly_providers():
    """Ordered, de-duplicated source ids from a comma list such as "openalex,scopus"."""
    names = []
    for value in os.environ.get("SCHOLARLY_PROVIDER", "openalex").split(","):
        name = value.strip().lower()
        if name and name not in names:
            names.append(name)
    if not names or any(name not in SCHOLARLY_PROVIDERS for name in names):
        raise RuntimeError("SCHOLARLY_PROVIDER must list openalex and/or scopus, comma-separated")
    if "scopus" in names and not os.environ.get("ELSEVIER_API_KEY", "").strip():
        raise RuntimeError("Set ELSEVIER_API_KEY to use the Scopus provider")
    return names
```

In `backend/researchpilot/api.py`, change the import `scholarly_provider,` to `scholarly_providers,`, and change line 62 to the following. It behaves the same as before; Task 4 replaces it:

```python
        selected_name = scholarly_providers()[0] if provider is None else "openalex"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest backend/tests/test_scopus.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/researchpilot/config.py backend/researchpilot/api.py backend/tests/test_scopus.py
git commit -m "Parse SCHOLARLY_PROVIDER as a comma list of sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `MultiSourceProvider` and the `failedSources` contract

**Files:**
- Modify: `backend/researchpilot/papers.py` (`SearchResult`, `SearchRun`)
- Create: `backend/researchpilot/providers/multi.py`
- Test: `backend/tests/test_multi_source.py`

**Interfaces:**
- Produces: `SearchResult.failedSources: list[str]` (default `[]`) and `SearchRun.failedSources: list[str]` (default `[]`).
- Produces: `MultiSourceProvider(providers: list[PaperProvider])` with attributes `.providers` and `.name` (names joined with `+`) and `async search(parameters) -> SearchResult`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_multi_source.py`:

```python
"""Several scholarly sources behind one PaperProvider."""

import asyncio
import logging

import pytest

from fakes import RecordingProvider, grouped_papers
from researchpilot.papers import ProviderError, SearchParameters
from researchpilot.providers.multi import MultiSourceProvider

PARAMETERS = SearchParameters(query="secret query text", maxPaperCount=10)


def source(name, papers=None, error=None):
    provider = RecordingProvider()
    provider.name = name
    provider.papers = grouped_papers(per_group=2) if papers is None else papers
    provider.error = error
    return provider


def run(provider):
    return asyncio.run(provider.search(PARAMETERS))


def test_combines_sources_and_joins_the_name():
    openalex, scopus = source("OpenAlex"), source("Scopus", grouped_papers(("alpha",), 1))
    multi = MultiSourceProvider([openalex, scopus])
    result = run(multi)
    assert multi.name == "OpenAlex+Scopus"
    assert len(result.papers) == 6 + 1
    assert result.totalFound == 7
    assert result.failedSources == []
    # Every source gets the full per-query budget.
    assert openalex.calls == [PARAMETERS] and scopus.calls == [PARAMETERS]


def test_partial_failure_keeps_survivors_and_names_the_failed_source(caplog):
    caplog.set_level(logging.WARNING)
    multi = MultiSourceProvider(
        [source("OpenAlex"), source("Scopus", error=ProviderError("RATE_LIMITED"))]
    )
    result = run(multi)
    assert len(result.papers) == 6
    assert result.failedSources == ["Scopus"]
    assert "source=Scopus code=RATE_LIMITED" in caplog.text
    assert "secret query text" not in caplog.text


def test_all_sources_failing_raises_the_first_error_in_order():
    multi = MultiSourceProvider(
        [
            source("OpenAlex", error=ProviderError("UNAVAILABLE")),
            source("Scopus", error=ProviderError("AUTHENTICATION")),
        ]
    )
    with pytest.raises(ProviderError) as error:
        run(multi)
    assert error.value.code == "UNAVAILABLE"


def test_failure_with_empty_survivors_raises():
    multi = MultiSourceProvider(
        [source("OpenAlex", papers=[]), source("Scopus", error=ProviderError("TIMEOUT"))]
    )
    with pytest.raises(ProviderError) as error:
        run(multi)
    assert error.value.code == "TIMEOUT"


def test_empty_results_without_failure_complete():
    result = run(MultiSourceProvider([source("OpenAlex", []), source("Scopus", [])]))
    assert result.papers == [] and result.failedSources == []


def test_programming_errors_propagate():
    multi = MultiSourceProvider([source("OpenAlex"), source("Scopus", error=KeyError("bug"))])
    with pytest.raises(KeyError):
        run(multi)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest backend/tests/test_multi_source.py -q`
Expected: `ModuleNotFoundError: No module named 'researchpilot.providers.multi'`.

- [ ] **Step 3: Implement the contract fields**

In `backend/researchpilot/papers.py`:

```python
class SearchResult(BaseModel):
    papers: list[Paper]
    totalFound: int
    skippedCount: int = 0
    failedSources: list[str] = Field(default_factory=list)
```

In `SearchRun`, add this after `failedQueries`:

```python
    failedSources: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement the provider**

Create `backend/researchpilot/providers/multi.py`:

```python
"""Several scholarly sources behind one PaperProvider; deduplication merges their papers."""

import asyncio
import logging

from ..papers import PaperProvider, ProviderError, SearchParameters, SearchResult

logger = logging.getLogger(__name__)


class MultiSourceProvider:
    def __init__(self, providers: list[PaperProvider]):
        self.providers = providers
        self.name = "+".join(provider.name for provider in providers)

    async def search(self, parameters: SearchParameters) -> SearchResult:
        """Query every source; keep survivors, fail when no papers survived a failure."""
        outcomes = await asyncio.gather(
            *(provider.search(parameters) for provider in self.providers),
            return_exceptions=True,
        )
        results, failed, first_error = [], [], None
        for provider, outcome in zip(self.providers, outcomes, strict=True):
            if isinstance(outcome, ProviderError):
                # Never log the query text: it can contain the user's own words.
                logger.warning(
                    "Scholarly source failed source=%s code=%s", provider.name, outcome.code
                )
                failed.append(provider.name)
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        if failed and sum(len(result.papers) for result in results) == 0:
            raise first_error
        return SearchResult(
            papers=[paper for result in results for paper in result.papers],
            totalFound=sum(result.totalFound for result in results),
            skippedCount=sum(result.skippedCount for result in results),
            failedSources=failed,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest backend/tests/test_multi_source.py -q`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/researchpilot/papers.py backend/researchpilot/providers/multi.py backend/tests/test_multi_source.py
git commit -m "Add a multi-source paper provider that reports failed sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Persist failed sources and cap merged results

**Files:**
- Create: `migrations/017_failed_sources.sql`
- Modify: `backend/researchpilot/search_persistence.py` (`SearchRunRow`, next to `failedQueries`)
- Modify: `scripts/migrate.py` (`requirements` and `required_columns`)
- Modify: `backend/researchpilot/search.py` (`CompletedSearch`, `_retrieve`, `_prepare`, `finish`)
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Consumes: `SearchResult.failedSources`, `SearchRun.failedSources`, `MultiSourceProvider` (Task 2).
- Produces: `CompletedSearch.failed_sources: list[str]`. Run JSON from `/search` and `/searches` includes `failedSources`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_search.py` (and add `from researchpilot.providers.multi import MultiSourceProvider` and `grouped_papers` to the existing imports; `uuid4` is already imported):

```python
def _multi_client(engine, *sources):
    return TestClient(
        create_app(
            engine,
            MultiSourceProvider(list(sources)),
            RecordingEmbeddingProvider(),
            RecordingLlmProvider(),
        )
    )


def _named(name, papers=None, error=None):
    provider = RecordingProvider()
    provider.name = name
    if papers is not None:
        provider.papers = papers
    provider.error = error
    return provider


def test_failed_source_is_persisted_and_returned(engine):
    with _multi_client(
        engine, _named("OpenAlex"), _named("Scopus", error=ProviderError("RATE_LIMITED"))
    ) as client:
        url = f"/api/projects/{client.post('/api/projects', json=DATA).json()['id']}"
        run = client.post(url + "/search").json()
        assert run["status"] == "COMPLETED"
        assert run["provider"] == "OpenAlex+Scopus"
        assert run["failedSources"] == ["Scopus"]
        assert client.get(url + "/searches").json()[0]["failedSources"] == ["Scopus"]


def test_single_source_runs_report_no_failed_sources(search_client):
    client, _, url = search_client
    assert client.post(url + "/search").json()["failedSources"] == []


def test_cross_source_duplicate_keeps_openalex_abstract_and_scopus_citations(engine):
    openalex_copy = normalize_work(WORK).model_copy(update={"citationCount": None})
    assert openalex_copy.abstract and openalex_copy.doi
    # The Scopus copy has more fields filled in but no abstract (STANDARD view).
    scopus_copy = openalex_copy.model_copy(
        update={
            "id": uuid4(),
            "source": "Scopus",
            "sourceId": "2-s2.0-85000000000",
            "sourceUrl": "https://www.scopus.com/record/display.uri?eid=2-s2.0-85000000000",
            "abstract": None,
            "citationCount": 99,
            "publisher": openalex_copy.publisher or "Elsevier",
            "venue": openalex_copy.venue or "Scopus venue",
        }
    )
    with _multi_client(
        engine, _named("OpenAlex", [openalex_copy]), _named("Scopus", [scopus_copy])
    ) as client:
        url = f"/api/projects/{client.post('/api/projects', json=DATA).json()['id']}"
        run = client.post(url + "/search").json()
        papers = client.get(url + "/papers").json()
    assert run["duplicateCount"] >= 1
    assert len(papers) == 1
    assert papers[0]["abstract"] == openalex_copy.abstract
    assert papers[0]["citationCount"] == 99


def test_merged_sources_are_capped_at_the_paper_limit(engine):
    # 30 unique on-topic papers across two sources; DATA["maxPaperCount"] is 25.
    papers = grouped_papers(per_group=10)
    with _multi_client(
        engine, _named("OpenAlex", papers[:15]), _named("Scopus", papers[15:])
    ) as client:
        url = f"/api/projects/{client.post('/api/projects', json=DATA).json()['id']}"
        run = client.post(url + "/search").json()
    assert run["paperCount"] + run["filteredCount"] == DATA["maxPaperCount"]
```

And add the PostgreSQL upgrade test (same pattern as `test_postgres_reading_status_upgrade` in `test_references.py`):

```python
def test_postgres_failed_sources_upgrade(search_client, engine):
    """Simulate a pre-017 run, then apply the real upgrade and check the backfill."""
    from pathlib import Path
    import runpy

    from sqlalchemy import inspect

    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL migration verification")
    client, _, url = search_client
    root = Path(__file__).parents[2]
    applied = runpy.run_path(str(root / "scripts/migrate.py"))["_already_applied"]
    client.post(url + "/search")
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE search_runs DROP COLUMN "failedSources"')
    assert not applied(inspect(engine), 17)
    with engine.begin() as connection:
        connection.exec_driver_sql((root / "migrations/017_failed_sources.sql").read_text())
    assert applied(inspect(engine), 17)
    assert client.get(url + "/searches").json()[0]["failedSources"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest backend/tests/test_search.py -q -k "failed_source or cross_source or capped"`
Expected: FAIL. `failedSources` is missing from run JSON (KeyError), and the cap test reports 30 ≠ 25. The cross-source test may already pass, because `_merge` already handles it. That is fine: it is a regression guard.

- [ ] **Step 3: Migration, row, and bootstrap**

Create `migrations/017_failed_sources.sql`:

```sql
ALTER TABLE search_runs ADD COLUMN "failedSources" JSONB NOT NULL DEFAULT '[]'::jsonb;
```

In `SearchRunRow` (`search_persistence.py`), add this after `failedQueries`:

```python
    failedSources: Mapped[list] = mapped_column(JSON, default=list)
```

In `scripts/migrate.py`, add `17: ("search_runs",),` to `requirements` and `17: {"search_runs": {"failedSources"}},` to `required_columns`.

- [ ] **Step 4: Pipeline**

In `backend/researchpilot/search.py`:

1. Add `failed_sources: list[str]` as the last field of `CompletedSearch`.
2. In `_retrieve`, return the ordered union of the failed sources in the combined result:

```python
        return (
            SearchResult(
                papers=[paper for result in results for paper in result.papers],
                totalFound=sum(result.totalFound for result in results),
                skippedCount=sum(result.skippedCount for result in results),
                failedSources=list(
                    dict.fromkeys(name for result in results for name in result.failedSources)
                ),
            ),
            failed,
        )
```

3. In `_prepare`, cap after semantic ranking and before relevance filtering. Replace

```python
        ranked_all = rank_semantically(lexical, question_vector, by_id)
        ranked = filter_relevant(ranked_all)
```

with

```python
        # Several sources may return more unique papers than the limit; keep the most relevant.
        ranked_all = rank_semantically(lexical, question_vector, by_id)[
            : run.parameters.maxPaperCount
        ]
        ranked = filter_relevant(ranked_all)
```

and pass `failed_sources=result.failedSources,` in the `CompletedSearch(...)` return.

4. In `finish`, add this after `latest.failedQueries = completed.failed_queries`:

```python
                latest.failedSources = completed.failed_sources
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest backend/tests/test_search.py backend/tests/test_multi_source.py backend/tests/nfr -q`
Expected: PASS (the Postgres test is skipped on SQLite).

- [ ] **Step 6: Commit**

```bash
git add migrations/017_failed_sources.sql backend/researchpilot/search_persistence.py scripts/migrate.py backend/researchpilot/search.py backend/tests/test_search.py
git commit -m "Record failed sources on search runs and cap merged results at the paper limit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Wire configured sources into the app and settings status

**Files:**
- Modify: `backend/researchpilot/api.py` (imports, `lifespan`, `/api/settings/status`)
- Test: `backend/tests/test_scopus.py`

**Interfaces:**
- Consumes: `scholarly_providers()` (Task 1) and `MultiSourceProvider` (Task 2).
- Produces: `/api/settings/status` returns `scholarlyProvider: str` (joined name) and `scholarlyProviders: list[str]` (display names in configured order).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_scopus.py`, extend `test_app_selects_scopus_without_exposing_key` by adding this after its `scholarlyProvider` assertion:

```python
    assert response.json()["scholarlyProviders"] == ["Scopus"]
```

and add:

```python
def test_app_combines_configured_sources(engine, monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "openalex,scopus")
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    with TestClient(create_app(engine)) as client:
        body = client.get("/api/settings/status").json()
        provider = client.app.state.search.provider
    assert body["scholarlyProvider"] == "OpenAlex+Scopus"
    assert body["scholarlyProviders"] == ["OpenAlex", "Scopus"]
    assert "test-secret" not in str(body)
    # Each source keeps its own client and headers.
    openalex, scopus = provider.providers
    assert "X-ELS-APIKey" not in openalex.client.headers
    assert scopus.client.headers["X-ELS-APIKey"] == "test-secret"
```

(`OpenAlexProvider` and `ScopusProvider` both store their httpx client as `self.client`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest backend/tests/test_scopus.py -q`
Expected: FAIL with `KeyError: 'scholarlyProviders'`.

- [ ] **Step 3: Implement the wiring**

In `api.py`, add `from contextlib import AsyncExitStack, asynccontextmanager` and `from .providers.multi import MultiSourceProvider`. Next to the provider imports, add:

```python
SOURCES = {
    "openalex": (openalex_headers, OpenAlexProvider),
    "scopus": (scopus_headers, ScopusProvider),
}
```

Replace the body of `lifespan` from `selected_name = ...` through the `SearchService(...)` construction with:

```python
        names = scholarly_providers() if provider is None else []
        async with AsyncExitStack() as stack:
            openai_client = await stack.enter_async_context(
                httpx.AsyncClient(headers=openai_headers(), timeout=30.0)
            )
            sources = []
            for name in names:
                headers, source = SOURCES[name]
                client = await stack.enter_async_context(
                    httpx.AsyncClient(headers=headers(), timeout=15.0)
                )
                sources.append(source(client))
            selected_provider = provider or (
                sources[0] if len(sources) == 1 else MultiSourceProvider(sources)
            )
            app.state.search = SearchService(
                app.state.engine,
                selected_provider,
                embedding_provider or OpenAIEmbeddingProvider(openai_client),
                llm_provider or OpenAILlmProvider(openai_client),
            )
```

Keep the existing `try: yield / finally: dispose` block, indented inside the new `async with`.

In `settings_status`, add the list next to `scholarlyProvider`:

```python
        search_provider = app.state.search.provider
        ...
            "scholarlyProvider": search_provider.name,
            "scholarlyProviders": [
                source.name for source in getattr(search_provider, "providers", [search_provider])
            ],
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q`
Expected: the whole SQLite suite passes (the browser tests are unaffected, since the field is additive).

- [ ] **Step 5: Commit**

```bash
git add backend/researchpilot/api.py backend/tests/test_scopus.py
git commit -m "Search every configured scholarly source and list them in the settings status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Settings "In use" for every source and the failed-source warning

**Run after Codex's frontend refresh is on `main`.** First run `git rebase main`, then apply these semantic changes to the markup Codex left. The code below targets the current `app.js`.

**Files:**
- Modify: `frontend/app.js` (Settings source panel in `renderSettings`; search panel next to the `failedQueries` warning)
- Test: `backend/tests/test_browser.py`

**Interfaces:**
- Consumes: `status.scholarlyProviders` (Task 4) and run fields `provider` and `failedSources` (Task 3).

- [ ] **Step 1: Write the failing browser tests**

Add to `backend/tests/test_browser.py`:

```python
def test_settings_marks_every_configured_source_in_use(browser_app):
    page, url, _, _, _ = browser_app
    page.route(
        "**/api/settings/status",
        lambda route: route.fulfill(
            json={
                "scholarlyProvider": "OpenAlex+Scopus",
                "scholarlyProviders": ["OpenAlex", "Scopus"],
                "openAlexApiKeyConfigured": False,
                "openAlexEmailConfigured": False,
                "elsevierApiKeyConfigured": True,
                "llmProvider": "OpenAI",
                "openAiApiKeyConfigured": False,
                "customOpenAiEndpointConfigured": False,
            }
        ),
    )
    page.goto(url.split("/api/projects/")[0] + "/settings")
    expect(page.locator(".settings-active-name")).to_have_text("OpenAlex + Scopus")
    for name in ("OpenAlex", "Scopus"):
        expect(page.locator(".settings-service-row").filter(has_text=name)).to_contain_text(
            "In use"
        )


def test_failed_source_warning(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")

    def with_failed_source(route):
        response = route.fetch()
        runs = response.json()
        runs[0] |= {"provider": "OpenAlex+Scopus", "failedSources": ["Scopus"]}
        route.fulfill(response=response, json=runs)

    page.route("**/searches", with_failed_source)
    page.reload()
    expect(
        page.get_by_text("Scopus was unavailable; results come from OpenAlex only.")
    ).to_be_visible()


def test_no_failed_source_warning_by_default(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    page.reload()
    expect(page.locator(".paper-row").first).to_be_visible()
    expect(page.get_by_text("was unavailable", exact=False)).to_have_count(0)
```

If Codex renamed `.settings-active-name`, `.settings-service-row`, or `.paper-row`, use the new selectors from the existing tests.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest backend/tests/test_browser.py -q -k "every_configured_source or failed_source"`
Expected: two failures. The active name shows `OpenAlex+Scopus` without spaces, and the warning is missing. The default-state test passes.

- [ ] **Step 3: Implement Settings**

In `renderSettings`, replace the `providerId`/`sourceName` lines and the two `providerId === ...` checks with:

```js
  const sourceNames = status.scholarlyProviders || [status.scholarlyProvider];
  const activeIds = sourceNames.map((name) => name.toLowerCase());
  const sourceLabel = (name) => ({scopus: 'Scopus', openalex: 'OpenAlex'})[name.toLowerCase()] || name;
  element('strong', sourceNames.map(sourceLabel).join(' + '), active, 'settings-active-name');
```

Then use `activeIds.includes('openalex')` in place of `providerId === 'openalex'` in the OpenAlex row, and `activeIds.includes('scopus')` in place of `providerId === 'scopus'` in the Scopus row, for both the badge text and the tone. If Codex changed the "CURRENT SOURCE" eyebrow copy, make it read correctly for multiple sources.

- [ ] **Step 4: Implement the warning**

Directly after the `failedQueries` warning block in the search panel, add:

```js
    if (latest?.failedSources?.length) {
      const joinNames = (names) => names.length < 2 ? names.join('')
        : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
      const remaining = latest.provider.split('+').filter((name) => !latest.failedSources.includes(name));
      element('p', `${joinNames(latest.failedSources)} ${latest.failedSources.length > 1 ? 'were' : 'was'} unavailable; results come from ${joinNames(remaining)} only.`, searchBody, 'field-help');
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --check frontend/app.js && uv run --extra dev pytest backend/tests/test_browser.py -q`
Expected: the syntax check passes and all browser tests pass, including the existing Scopus settings test (which sends no `scholarlyProviders`, so the fallback path runs).

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js backend/tests/test_browser.py
git commit -m "Show every configured source in Settings and warn when one fails

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Docs, version, and verification gate

**Files:**
- Create: `docs/features/multi-source-search.md`
- Modify: `docs/roadmap.md` (a row in "Projects and retrieval"), `README.md` (the Scopus paragraph near line 115), `.env.example`, `docs/superpowers/specs/2026-09-24-multi-source-search-design.md` (§5 settings-status wording and Status line), `pyproject.toml`, `backend/researchpilot/config.py` (the two User-Agent strings), `uv.lock`

- [ ] **Step 1: Feature note**

Create `docs/features/multi-source-search.md` in the short prose style of `docs/features/reading-status.md`. It should cover the `SCHOLARLY_PROVIDER=openalex,scopus` example, the full per-query budget per source, and merging through the existing deduplication (an OpenAlex abstract plus a Scopus citation count). It should also cover the cap at `maxPaperCount` after semantic ranking, and partial failure (the `failedSources` warning, and run failure when nothing survived). It ends with migration 017, which adds `search_runs.failedSources`, the additive `scholarlyProviders` status field, no provenance tracking, and no new dependencies.

- [ ] **Step 2: Roadmap, README, env, spec**

- Roadmap row: `| Multi-source search | Search OpenAlex and Scopus together; duplicates merge and a failed source is reported | [multi-source-search](features/multi-source-search.md) |`
- README: after the Scopus sentence, add ``Set `SCHOLARLY_PROVIDER=openalex,scopus` to search both; duplicates merge, and if one source fails the search completes with the other and says so.``
- `.env.example`: after `SCHOLARLY_PROVIDER=openalex`, add the comment `# openalex, scopus, or both: openalex,scopus`.
- Spec §5: `/api/settings/status` keeps `scholarlyProvider` (the joined name) and adds `scholarlyProviders` (display names). Set the status line to `implemented (v0.N.0)`.

- [ ] **Step 3: Version bump**

Increase the minor version in `pyproject.toml` by one from whatever `main` has after Task 0, and update both `ResearchPilot/0.N` strings in `config.py` to match. Then run `uv lock`.

- [ ] **Step 4: Verification gate**

Run, in order:
```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
node --check frontend/app.js
uv build
uv run --extra dev pytest
TEST_DATABASE_URL=postgresql+psycopg://researchpilot:local-development@localhost:5432/researchpilot_test uv run --extra dev pytest
```
Expected: all clean and passing. The PostgreSQL run needs the user's Docker Postgres; ask them to start it if it is down.

- [ ] **Step 5: Live smoke test** (needs keys in `.env`, with the user's go-ahead)

1. Set `SCHOLARLY_PROVIDER=openalex,scopus`, migrate the dev DB (`uv run python scripts/migrate.py`), start the server, and search a project with `maxPaperCount` 20. Expect provider `OpenAlex+Scopus` on the run, `duplicateCount > 0`, and abstracts on papers found by both sources.
2. Restart with `ELSEVIER_API_KEY=invalid` and search again. Expect `COMPLETED`, `failedSources == ["Scopus"]`, and the warning in the UI.

- [ ] **Step 6: Commit**

```bash
git add docs README.md .env.example pyproject.toml backend/researchpilot/config.py uv.lock
git commit -m "Document multi-source search and bump the version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Merging (`git merge --ff-only` into `main`) and pushing happen only after the user okays it.
