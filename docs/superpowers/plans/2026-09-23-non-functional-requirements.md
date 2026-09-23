# Non-Functional Requirements and Acceptance Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every non-functional requirement an ID, a measurable target and a named test in a CI-enforced `backend/tests/nfr/` suite. Fix the code wherever an NFR fails, and automate the §38 acceptance scenario.

**Architecture:**
- Shared test fakes move to `backend/tests/fakes.py`, the shared API fixtures to `backend/tests/conftest.py`, and a reusable live-server/browser helper to `backend/tests/live.py`.
- The NFR suite adds a `budget` timing helper (`backend/tests/nfr/nfr_support.py`) and NFR fixtures (`backend/tests/nfr/conftest.py`), including a real-adapter harness in which `httpx.AsyncClient` is patched to a `MockTransport`.
- One real code change is known in advance: partial retrieval-failure tolerance, with a new `failedQueries` run field (migration 015).

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic 2, httpx, pytest, Playwright (Chromium), vanilla JS, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-23-non-functional-requirements-design.md`

## Global Constraints

- All NFR tests use fake providers or `httpx.MockTransport`; no network calls and no paid API calls.
- Test names start with their ID: `test_nfr_perf_1_…`, `test_nfr_rel_3_…`, `test_acc_38_…`. Every NFR module sets `pytestmark = pytest.mark.nfr`.
- Performance: the CI ceiling is exactly 3 × target (`BUDGET_FACTOR = 3`). The targets are PERF-1 1.5 s, PERF-2 0.3 s, PERF-3 1.0 s and PERF-4 0.2 s (p95 over 20 calls).
- A failing NFR is fixed in production code, never by weakening the test. A local fix (a few lines, no new schema or API contract) is done inside the task. A fix needing a design decision stops the task with status NEEDS_CONTEXT.
- Work in worktree `../ResearchPilot-non-functional-requirements` on branch `feat/non-functional-requirements`, branched from `main`.
- Gate before merge:
  - `uv run --extra dev ruff check .`
  - `uv run --extra dev ruff format --check .`
  - `node --check frontend/app.js`
  - `uv build`
  - `uv run --extra dev pytest -q`
  - `TEST_DATABASE_URL=postgresql+psycopg://researchpilot:local-development@localhost:5432/researchpilot_test uv run --extra dev pytest -q`
- End every commit message with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage only the files you changed; never `git add -A`.
- Never edit `docs/report.md` or any untracked report file (`docs/report.typ`, `docs/report.pdf`, `docs/Feats.md`, `docs/layout.typ`, `docs/report-*.xml|md`).

---

### Task 0: Worktree

- [ ] **Step 1**

```bash
cd /home/mgustafsson/Projects/Personal/ResearchPilot
git status --short   # must list only the untracked report files; otherwise stop and ask
git worktree add -b feat/non-functional-requirements ../ResearchPilot-non-functional-requirements main
cd ../ResearchPilot-non-functional-requirements && uv run --extra dev pytest -q | tail -1
```

Expected: `204 passed, 2 skipped`.

---

### Task 1: Shared test infrastructure, marker, CI report

**Files:**
- Create: `backend/tests/fakes.py`, `backend/tests/live.py`
- Modify: `backend/tests/conftest.py`, `backend/tests/test_search.py`, `backend/tests/test_browser.py`, `pyproject.toml` (`[tool.pytest.ini_options]`), `.github/workflows/checks.yml`

**Interfaces:**
- Produces:
  - `fakes.py`: `WORK`, `DATA`, `RecordingProvider`, `RecordingEmbeddingProvider`, `RecordingLlmProvider`, `grouped_papers(groups=("alpha", "bravo", "charlie"), per_group=5)`. Existing callers keep `_grouped_papers` as an alias.
  - `conftest.py` fixtures: `search_client`, `search_client_with_embedder`, `search_client_named`, all with the same yields as today.
  - `live.py`: `live_browser(app)`, a context manager that yields `(page, base_url)`.
  - The `nfr` pytest marker.

This is a pure move with no behavior change: the suite must pass with the same counts before and after.

- [ ] **Step 1: Create `backend/tests/fakes.py`**

Move these from `backend/tests/test_search.py`, verbatim, into the new file: the `WORK`/`DATA` constants, the three `Recording*` classes, and `_grouped_papers` (bodies unchanged). Then generalise `_grouped_papers`:

```python
"""Deterministic local providers shared by the API, browser and NFR tests."""

import json
from pathlib import Path

from researchpilot.llm import ClusterNaming, QueryExpansion
from researchpilot.papers import SearchResult
from researchpilot.providers.openalex import normalize_work

WORK = json.loads((Path(__file__).parent / "fixtures/openalex_work.json").read_text())
DATA = {...}  # exactly as in test_search.py today

# class RecordingProvider / RecordingEmbeddingProvider / RecordingLlmProvider: exactly as today


def grouped_papers(groups=("alpha", "bravo", "charlie"), per_group=5):
    return [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W1{groups.index(group)}{n}",
                "doi": f"https://doi.org/10.5000/{group}-{n}",
                "title": f"{group} paper {n} about large language models",
                "abstract_inverted_index": None,
            }
        )
        for group in groups
        for n in range(per_group)
    ]


_grouped_papers = grouped_papers
```

Replace `DATA = {...}` and the class comments with the real content moved from `test_search.py`. The default arguments reproduce today's output exactly: same ids, DOIs and titles.

- [ ] **Step 2: Move the three API fixtures into `backend/tests/conftest.py`**

Move `search_client`, `search_client_with_embedder` and `search_client_named` verbatim from `test_search.py` to the end of `conftest.py`, and add `from fakes import DATA, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider` to the conftest imports. In `test_search.py`, delete the moved definitions and import what it still uses:

```python
from fakes import (
    DATA,
    WORK,
    RecordingEmbeddingProvider,
    RecordingLlmProvider,
    RecordingProvider,
    _grouped_papers,
)
```

Remove any imports that ruff reports unused after the move.

- [ ] **Step 3: Create `backend/tests/live.py` and use it in `test_browser.py`**

```python
"""A real uvicorn server plus Chromium page for browser tests."""

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from playwright.sync_api import sync_playwright


@contextmanager
def live_browser(app, viewport=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport=viewport)
            try:
                yield page, f"http://127.0.0.1:{sock.getsockname()[1]}"
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
```

Rewrite the `browser_app` fixture in `test_browser.py` to use it. Everything before `app = create_app(...)` stays the same; the server/Playwright block becomes:

```python
    app = create_app(engine, provider, embedder, llm)
    with live_browser(app) as (page, base):
        project = page.request.post(base + "/api/projects", data=DATA).json()
        url = base + "/api/projects/" + project["id"]
        page.goto(base + "/projects/" + project["id"])
        yield page, url, gate, embedder, llm
        gate.set()
    engine.dispose()
```

Change the imports to `from fakes import DATA, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider, _grouped_papers` and `from live import live_browser`. Remove the now-unused `socket`, `threading`, `time`, `uvicorn` and `sync_playwright` imports if ruff flags them.

- [ ] **Step 4: Register the marker and the CI report**

In `pyproject.toml` under `[tool.pytest.ini_options]` add:

```toml
markers = ["nfr: non-functional requirement tests (docs/requirements.md §31)"]
```

In `.github/workflows/checks.yml`, replace the first `- run: uv run pytest` (the SQLite one, which has no `env:`) with:

```yaml
      - run: uv run pytest --junitxml=nfr-report.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-report
          path: nfr-report.xml
```

- [ ] **Step 5: Verify there is no behavior change**

Run `uv run --extra dev pytest -q`. Expected: `204 passed, 2 skipped`, the same as Task 0. Run the PostgreSQL suite (expected `206 passed`), `ruff check .` and `ruff format --check .`.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/fakes.py backend/tests/live.py backend/tests/conftest.py backend/tests/test_search.py backend/tests/test_browser.py pyproject.toml .github/workflows/checks.yml
git commit -m "Share test fakes, fixtures and the live browser helper; add the nfr marker and CI test report"
```

---

### Task 2: Performance NFRs (PERF-1..4)

**Files:**
- Create: `backend/tests/nfr/nfr_support.py`, `backend/tests/nfr/conftest.py`, `backend/tests/nfr/test_nfr_performance.py`

**Interfaces:**
- Consumes: `fakes.grouped_papers`, `fakes.Recording*`, `fakes.DATA`, `live.live_browser`.
- Produces:
  - `nfr_support.BUDGET_FACTOR = 3`
  - `nfr_support.check_budget(record_property, nfr_id: str, target_s: float, measured_s: float)`
  - `nfr_support.budget(record_property, nfr_id, target_s)` (a context manager)
  - `nfr_support.SIX_GROUPS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")`
  - `nfr_support.SixGroupEmbeddingProvider`
  - fixtures `large_api` → `(client, url)` and `large_browser` → `(page, base, project_id)`, each for a project already searched with 252 papers (6 × 42) in 6 groups.

- [ ] **Step 1: Write `backend/tests/nfr/nfr_support.py`**

```python
"""Helpers for measurable NFR tests (docs/requirements.md §31)."""

import time
from contextlib import contextmanager

from fakes import RecordingEmbeddingProvider

BUDGET_FACTOR = 3
SIX_GROUPS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")


def check_budget(record_property, nfr_id, target_s, measured_s):
    ceiling_s = target_s * BUDGET_FACTOR
    record_property(f"{nfr_id} measured_s", round(measured_s, 4))
    record_property(f"{nfr_id} target_s", target_s)
    record_property(f"{nfr_id} ceiling_s", ceiling_s)
    assert measured_s <= ceiling_s, (
        f"{nfr_id}: {measured_s:.3f}s exceeds the CI ceiling {ceiling_s:.3f}s "
        f"(target {target_s:.3f}s)"
    )


@contextmanager
def budget(record_property, nfr_id, target_s):
    started = time.perf_counter()
    yield
    check_budget(record_property, nfr_id, target_s, time.perf_counter() - started)


class SixGroupEmbeddingProvider(RecordingEmbeddingProvider):
    """Each group marker gets its own axis plus the shared on-topic axis 7."""

    def _vector(self, text):
        vector = [0.0] * self.dimension
        for index, marker in enumerate(SIX_GROUPS):
            if marker in text:
                vector[index] = 10.0
                vector[7] = 10.0
                return vector
        return [1.0] * self.dimension
```

The question text ("large language models software engineering") has no marker, so its vector is `[1.0] * 8`. Each group vector then has cosine 0.5 with it, about 71% relevance, so every paper passes the 40% filter. Marker indices 0–5 don't collide with the fake's "marine" axis 6.

- [ ] **Step 2: Write `backend/tests/nfr/conftest.py` (performance fixtures)**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from fakes import DATA, RecordingLlmProvider, RecordingProvider, grouped_papers
from live import live_browser
from nfr_support import SIX_GROUPS, SixGroupEmbeddingProvider
from researchpilot.api import create_app
from researchpilot.persistence import Base

LARGE = {**DATA, "maxPaperCount": 252}


def _large_app(engine):
    provider = RecordingProvider()
    provider.papers = grouped_papers(SIX_GROUPS, per_group=42)
    return create_app(engine, provider, SixGroupEmbeddingProvider(), RecordingLlmProvider())


@pytest.fixture
def large_api(engine):
    with TestClient(_large_app(engine)) as client:
        project = client.post("/api/projects", json=LARGE).json()
        url = f"/api/projects/{project['id']}"
        run = client.post(url + "/search").json()
        assert run["status"] == "COMPLETED" and run["paperCount"] == 252, run
        yield client, url


@pytest.fixture
def large_browser(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'large.db'}")
    Base.metadata.create_all(engine)
    with live_browser(_large_app(engine), viewport={"width": 1400, "height": 1000}) as (page, base):
        project = page.request.post(base + "/api/projects", data=LARGE).json()
        run = page.request.post(f"{base}/api/projects/{project['id']}/search").json()
        assert run["status"] == "COMPLETED" and run["paperCount"] == 252, run
        yield page, base, project["id"]
    engine.dispose()
```

`grouped_papers` ids are `W1` + one group digit + `n`, so they are unique for any `per_group`; DOIs include the group name.

- [ ] **Step 3: Write `backend/tests/nfr/test_nfr_performance.py`**

```python
"""NFR-PERF-1..4 (docs/requirements.md §31): 250-paper projects stay responsive."""

import re
import time

import numpy as np
import pytest
from playwright.sync_api import expect

from fakes import WORK
from nfr_support import budget, check_budget
from researchpilot.analysis import deduplicate, filter_relevant, rank_papers, rank_semantically
from researchpilot.clustering import cluster_papers
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr


def test_nfr_perf_1_map_renders_250_papers(large_browser, record_property):
    page, base, project_id = large_browser
    with budget(record_property, "NFR-PERF-1", 1.5):
        page.goto(f"{base}/projects/{project_id}")
        expect(page.locator(".paper-row")).to_have_count(252, timeout=10_000)


def test_nfr_perf_2_tab_and_filter_rerender(large_browser, record_property):
    page, base, project_id = large_browser
    page.goto(f"{base}/projects/{project_id}")
    expect(page.locator(".paper-row")).to_have_count(252, timeout=10_000)
    tab = page.locator(".cluster-tab").nth(1)
    expected = int(tab.locator(".count").inner_text())
    with budget(record_property, "NFR-PERF-2 tab", 0.3):
        tab.click()
        expect(tab).to_have_class(re.compile(r"\bactive\b"))
        expect(page.locator(".paper-row")).to_have_count(expected)
    toggle = page.get_by_role("button", name="Open access only", exact=True)
    with budget(record_property, "NFR-PERF-2 filter", 0.3):
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")


def test_nfr_perf_3_backend_analysis_of_250_papers(record_property):
    papers = [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W{5000 + n}",
                "doi": f"https://doi.org/10.6000/perf-{n % 245}",  # 5 DOI duplicates
                "title": f"study {n} of large language models in software engineering",
            }
        )
        for n in range(250)
    ]
    rng = np.random.default_rng(0)
    centres = rng.normal(size=(6, 512))
    with budget(record_property, "NFR-PERF-3", 1.0):
        unique, _ = deduplicate(papers)
        lexical = rank_papers(unique, "large language models software engineering", [])
        vectors = {
            item.paper.id: (centres[i % 6] + rng.normal(scale=0.3, size=512)).tolist()
            for i, item in enumerate(lexical)
        }
        question = centres.mean(axis=0).tolist()
        ranked = filter_relevant(rank_semantically(lexical, question, vectors))
        cluster_papers([vectors[item.paper.id] for item in ranked])


@pytest.mark.parametrize("endpoint", ["/papers", "/subtopics", "/searches", "/queries"])
def test_nfr_perf_4_read_endpoints_p95(large_api, record_property, endpoint):
    client, url = large_api
    timings = []
    for _ in range(20):
        started = time.perf_counter()
        assert client.get(url + endpoint).status_code == 200
        timings.append(time.perf_counter() - started)
    p95 = sorted(timings)[18]  # 19th of 20 samples
    check_budget(record_property, f"NFR-PERF-4 {endpoint}", 0.2, p95)
```

In PERF-3 the random semantic vectors may leave `ranked` short. That's fine: the budget covers the whole pipeline regardless of how many papers survive. If `ranked` would be empty, `cluster_papers([])` must still be fast, so no assertion is needed on its length.

- [ ] **Step 4: Run and record**

```bash
uv run --extra dev pytest backend/tests/nfr/test_nfr_performance.py -q -rA --junitxml=/tmp/perf.xml
```

Expected: pass. Collect the measured values with `grep -o 'measured_s" value="[^"]*"' /tmp/perf.xml` (property name includes the NFR id) and put them in the task report; Task 7 needs them. If a test **fails its ceiling**, profile the slow step and fix it in production code as a local fix. Likely candidates: frontend rendering of 252 rows, or an N+1 query in `SearchRepository.papers()`. Describe the fix in the report. Run the browser tests 3× to check stability.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/nfr
git commit -m "Add NFR-PERF-1..4 performance requirements tests"
```

(Add any production files a PERF fix touched to the `git add`.)

---

### Task 3: Reliability NFRs (REL-1..4) and partial retrieval failure

**Files:**
- Create: `backend/tests/nfr/test_nfr_reliability.py`, `migrations/015_failed_queries.sql`
- Modify: `backend/researchpilot/search.py` (`_retrieve`, `search`, `_prepare`, `CompletedSearch`, `finish`), `backend/researchpilot/search_persistence.py` (`SearchRunRow`), `backend/researchpilot/papers.py` (`SearchRun`), `scripts/migrate.py`, `frontend/app.js` (`showSearch`)

**Interfaces:**
- Consumes: the `search_client_named` fixture (from `conftest.py`) and `fakes.grouped_papers`.
- Produces:
  - `SearchRun.failedQueries: list[str]` (default `[]`)
  - `SearchService._retrieve(run, queries) -> tuple[SearchResult, list[str]]`
  - `CompletedSearch.failed_queries: list[str]`

- [ ] **Step 1: Write the failing tests** (`backend/tests/nfr/test_nfr_reliability.py`)

```python
"""NFR-REL-1..4 (docs/requirements.md §28, §31): failures degrade, never corrupt."""

import asyncio
import logging

import pytest

from fakes import grouped_papers
from researchpilot import search as search_module
from researchpilot.papers import ProviderError

pytestmark = pytest.mark.nfr


def _searched_with_edit(client, provider, url):
    provider.papers = grouped_papers()
    assert client.post(url + "/search").status_code == 200
    topic = client.get(url + "/subtopics").json()[0]
    client.patch(f"{url}/subtopics/{topic['clusterId']}", json={"name": "Kept by the user"})
    return client.get(url + "/papers").json(), client.get(url + "/subtopics").json()


@pytest.mark.parametrize(
    "stage,code,status",
    [
        ("provider", "UNAVAILABLE", 503),
        ("provider", "RATE_LIMITED", 503),
        ("provider", "TIMEOUT", 504),
        ("provider", "INVALID_RESPONSE", 502),
        ("embedding", "EMBEDDING_UNAVAILABLE", 503),
        ("clustering", "INTERNAL", 502),
    ],
)
def test_nfr_rel_1_failures_return_codes_and_preserve_results(
    search_client_named, monkeypatch, stage, code, status
):
    client, provider, embedder, _, url = search_client_named
    papers, subtopics = _searched_with_edit(client, provider, url)
    if stage == "provider":
        provider.error = ProviderError(code)
    elif stage == "embedding":
        embedder.error = ProviderError(code)
        embedder.model = "force-new-vectors"  # bypass the embedding cache
    else:
        monkeypatch.setattr(search_module, "cluster_papers", _raise_runtime_error)
        embedder.model = "force-new-vectors"
    response = client.post(url + "/search?force=true")
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert client.get(url + "/papers").json() == papers
    assert client.get(url + "/subtopics").json() == subtopics


def _raise_runtime_error(*args, **kwargs):
    raise RuntimeError("clustering blew up")


def test_nfr_rel_1_no_papers_completes_empty(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = []
    response = client.post(url + "/search")
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED" and response.json()["paperCount"] == 0
    assert client.get(url + "/papers").json() == []


def test_nfr_rel_2_expansion_failure_falls_back_to_keywords(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion_error = ProviderError("LLM_INVALID_RESPONSE")
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED"
    assert [p.query for p in provider.calls] == ["software engineering"]


@pytest.mark.parametrize("code", ["LLM_UNAVAILABLE", "LLM_INVALID_RESPONSE"])
def test_nfr_rel_2_naming_failure_keeps_numbered_clusters(search_client_named, code):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.error = ProviderError(code)
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED" and run["clusterCount"] >= 2
    assert run["namingError"] == code
    assert client.get(url + "/subtopics").json() == []


def test_nfr_rel_2_explanation_timeout_is_504(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    client.post(url + "/search")
    paper = next(p for p in client.get(url + "/papers").json() if p["clusterId"] is not None)
    llm.explain_error = ProviderError("TIMEOUT")
    response = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert (response.status_code, response.json()["code"]) == (504, "EXPLANATION_TIMEOUT")


def _fail_query(provider, bad_query, code):
    original = provider.search

    async def search(parameters):
        if parameters.query == bad_query:
            provider.calls.append(parameters)
            raise ProviderError(code)
        return await original(parameters)

    provider.search = search


def test_nfr_rel_3_partial_query_failure_keeps_surviving_results(search_client_named, caplog):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.expansion = ["good query", "secret bad query"]
    _fail_query(provider, "secret bad query", "RATE_LIMITED")
    caplog.set_level(logging.INFO)
    response = client.post(url + "/search")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETED" and run["paperCount"] == 15
    assert run["failedQueries"] == ["secret bad query"]
    assert client.get(url + "/searches").json()[0]["failedQueries"] == ["secret bad query"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("RATE_LIMITED" in m for m in messages)
    assert not any("secret bad query" in m for m in messages)


def test_nfr_rel_3_all_queries_failing_fails_with_first_code(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["first query", "second query"]
    provider.error = ProviderError("RATE_LIMITED")
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (503, "RATE_LIMITED")


async def _hang(*args, **kwargs):
    await asyncio.sleep(3600)


def test_nfr_rel_4_hanging_retrieval_times_out(search_client_named, monkeypatch):
    client, provider, _, _, url = search_client_named
    monkeypatch.setattr(search_module, "SEARCH_TIMEOUT_SECONDS", 0.2)
    provider.search = _hang
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (504, "TIMEOUT")


def test_nfr_rel_4_hanging_embedding_times_out(search_client_named, monkeypatch):
    client, provider, embedder, _, url = search_client_named
    monkeypatch.setattr(search_module, "EMBEDDING_TIMEOUT_SECONDS", 0.2)
    embedder.embed = _hang
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (504, "TIMEOUT")


def test_nfr_rel_4_hanging_naming_falls_back(search_client_named, monkeypatch):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    monkeypatch.setattr(search_module, "NAMING_TIMEOUT_SECONDS", 0.2)
    llm.name_cluster = _hang
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED" and run["namingError"]
```

Before changing any code, check two semantics against the real code:
- **Explanation paper:** `explain` needs a paper in a *named* subtopic. If `clusterId is not None` doesn't guarantee a named one, pick a paper whose `clusterId` matches a subtopic from `/subtopics`.
- **Invalid-response code:** if `namingError` stores a different code for `LLM_INVALID_RESPONSE`, read `_name_clusters` and assert what it actually records, because the spec requires only that it is set.

Record both checks in the report.

- [ ] **Step 2: Run them and confirm the expected failures**

Run: `uv run --extra dev pytest backend/tests/nfr/test_nfr_reliability.py -q`

Expected: the two REL-3 partial tests fail, with 502/503 instead of 200 and no `failedQueries`. Any other failure is an NFR violation: fix it locally, or stop with NEEDS_CONTEXT if it needs a design decision. Record every initial failure in the report.

- [ ] **Step 3: Migration and model**

`migrations/015_failed_queries.sql`:

```sql
ALTER TABLE search_runs ADD COLUMN "failedQueries" JSONB NOT NULL DEFAULT '[]'::jsonb;
```

In `scripts/migrate.py`, add `15: ("search_runs",),` to `requirements` and `15: {"search_runs": {"failedQueries"}},` to `required_columns`. In `search_persistence.py`, add this to `SearchRunRow` beside `generatedQueries`:

```python
    failedQueries: Mapped[list] = mapped_column(JSON, default=list)
```

In `papers.py`, add this to `SearchRun` after `generatedQueries`:

```python
    failedQueries: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Tolerate partial failure in `search.py`**

Replace `_retrieve`:

```python
    async def _retrieve(self, run, queries):
        """Retrieve every query; keep survivors, fail only when every query failed."""
        per_query = max(1, (run.parameters.maxPaperCount + len(queries) - 1) // len(queries))
        parameters = [
            run.parameters.model_copy(update={"query": query, "maxPaperCount": per_query})
            for query in queries
        ]
        outcomes = await asyncio.gather(
            *(self.provider.search(item) for item in parameters), return_exceptions=True
        )
        results, failed, first_error = [], [], None
        for query, outcome in zip(queries, outcomes, strict=True):
            if isinstance(outcome, ProviderError):
                # Never log the query text: it can contain the user's own words.
                logger.warning("Search query failed run=%s code=%s", run.id, outcome.code)
                failed.append(query)
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        if not results:
            raise first_error
        return (
            SearchResult(
                papers=[paper for result in results for paper in result.papers],
                totalFound=sum(result.totalFound for result in results),
                skippedCount=sum(result.skippedCount for result in results),
            ),
            failed,
        )
```

Add a `failed_queries: list[str]` field to the `CompletedSearch` dataclass, as the last field and without a default, matching the other fields. Give `_prepare` a new parameter, `async def _prepare(self, run, result, failed_queries) -> CompletedSearch:`, and pass `failed_queries=failed_queries` into the `CompletedSearch(...)` it returns. In `search()`:

```python
            result, failed_queries = await asyncio.wait_for(
                self._retrieve(run, queries), SEARCH_TIMEOUT_SECONDS
            )
            completed = await self._prepare(run, result, failed_queries)
```

In `finish()`, beside `latest.filteredCount = completed.filtered_count`, add `latest.failedQueries = completed.failed_queries`. Then update every other caller of `_prepare` that ruff or the tests reveal. `test_shared_paper_interleaved_searches_keep_vector_metadata` in `test_search.py` calls `service._prepare(first, SearchResult(...))`; pass `[]` as the third argument there.

- [ ] **Step 5: Show it in the search panel** (`frontend/app.js`, `showSearch`)

Directly after the block that renders "Queries used for this search", add:

```js
    if (latest?.failedQueries?.length) {
      element('p', `${latest.failedQueries.length} of ${latest.generatedQueries.length} queries failed; results come from the rest.`, searchBody, 'field-help');
    }
```

- [ ] **Step 6: Run everything**

- `uv run --extra dev pytest backend/tests/nfr/test_nfr_reliability.py -q`: all pass.
- The full SQLite suite and the PostgreSQL suite: the PostgreSQL run applies migration 015.
- `node --check frontend/app.js`, ruff check and ruff format.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/nfr/test_nfr_reliability.py migrations/015_failed_queries.sql scripts/migrate.py backend/researchpilot/search.py backend/researchpilot/search_persistence.py backend/researchpilot/papers.py frontend/app.js backend/tests/test_search.py
git commit -m "Keep searching when some queries fail; add NFR-REL-1..4 reliability tests"
```

---

### Task 4: Security NFRs (SEC-1..4) with a real-adapter harness

**Files:**
- Modify: `backend/tests/nfr/conftest.py` (add the harness)
- Create: `backend/tests/nfr/test_nfr_security.py`

**Interfaces:**
- Consumes: `fakes.WORK`, `fakes.DATA`, `fakes.grouped_papers`, `fakes.Recording*`, `live.live_browser`, and the `engine` fixture.
- Produces:
  - `OPENAI_KEY = "sk-nfr-openai-7f3c9e"` and `OPENALEX_KEY = "oa-nfr-openalex-4b2d81"` in `nfr/nfr_support.py`. Test modules import them from there, never from `conftest`, because two conftest modules exist.
  - fixture `real_adapter_app(engine, monkeypatch)` → `SimpleNamespace(client, url, requests, fail)`:
    - `client`: a `TestClient` over `create_app(engine)` with no injected providers, so the real OpenAlex and OpenAI adapters run.
    - `url`: the project API path.
    - `requests`: a list of every `httpx.Request` the adapters sent.
    - `fail`: a dict. Setting `fail["openalex"] = (status, body)` makes every OpenAlex call return that response.

- [ ] **Step 1: Add the harness to `backend/tests/nfr/conftest.py`**

First add these two constants to `backend/tests/nfr/nfr_support.py`:

```python
OPENAI_KEY = "sk-nfr-openai-7f3c9e"
OPENALEX_KEY = "oa-nfr-openalex-4b2d81"
```

Then add to `conftest.py`:

```python
import json as jsonlib
from types import SimpleNamespace

import httpx

from fakes import WORK
from nfr_support import OPENAI_KEY, OPENALEX_KEY


def _works(count=12):
    groups = ("alpha", "bravo", "charlie")
    return [
        WORK
        | {
            "id": f"https://openalex.org/W{7000 + n}",
            "doi": f"https://doi.org/10.7000/{groups[n % 3]}-{n}",
            "title": f"{groups[n % 3]} study {n} of large language models",
        }
        for n in range(count)
    ]


def _vector(text):
    vector = [0.0] * 512
    for index, marker in enumerate(("alpha", "bravo", "charlie")):
        if marker in text:
            vector[index] = 1.0
    vector[511] = 1.0
    return vector


@pytest.fixture
def real_adapter_app(engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("OPENALEX_API_KEY", OPENALEX_KEY)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    requests, fail = [], {}

    def handler(request):
        requests.append(request)
        if request.url.host == "api.openalex.org":
            if "openalex" in fail:
                status, body = fail["openalex"]
                return httpx.Response(status, text=body)
            return httpx.Response(200, json={"results": _works(), "meta": {"count": 12, "next_cursor": None}})
        body = jsonlib.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            data = [{"index": i, "embedding": _vector(t)} for i, t in enumerate(body["input"])]
            return httpx.Response(200, json={"data": data})
        schema = body["response_format"]["json_schema"]["name"]
        content = {
            "query_expansion": {"queries": ["llm code generation", "llm software testing"]},
            "subtopic": {"name": "Named topic", "description": "A topic.", "keywords": ["llm"]},
            "explanation": {"explanation": "It studies language models."},
        }[schema]
        return httpx.Response(200, json={
            "choices": [{"message": {"content": jsonlib.dumps(content)}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })

    real_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
    with TestClient(create_app(engine)) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield SimpleNamespace(client=client, url=f"/api/projects/{project['id']}", requests=requests, fail=fail)
```

Check the embeddings response shape against `_vectors()` in `providers/openai.py`, and the `SearchResult`/cursor handling against `OpenAlexProvider.search`, and adjust the fake payloads to what the real parsers accept. The fakes must satisfy the real parsers; the parsers must not change. `create_app(engine)` builds its clients with `httpx.AsyncClient(headers=..., timeout=...)`, so the patched constructor injects the transport.

- [ ] **Step 2: Write `backend/tests/nfr/test_nfr_security.py`**

```python
"""NFR-SEC-1..4 (docs/requirements.md §31): secrets stay server-side, input is inert."""

import logging

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine

from nfr_support import OPENAI_KEY, OPENALEX_KEY
from fakes import WORK, grouped_papers, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider
from live import live_browser
from researchpilot.api import create_app
from researchpilot.persistence import Base
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr
SECRETS = (OPENAI_KEY, OPENALEX_KEY)


def test_nfr_sec_1_api_keys_never_leave_the_server(real_adapter_app, caplog):
    app = real_adapter_app
    caplog.set_level(logging.DEBUG)
    client, url = app.client, app.url
    responses = [
        client.post(url + "/queries"),
        client.post(url + "/search"),
        client.get(url + "/papers"),
        client.get(url + "/subtopics"),
        client.get(url + "/searches"),
        client.get(url + "/queries"),
        client.get("/api/settings/status"),
        client.get(url.replace("/api/projects/", "/projects/")),
        client.get("/static/app.js"),
        client.get("/static/styles.css"),
    ]
    paper = next(p for p in client.get(url + "/papers").json() if p["clusterId"] is not None)
    responses.append(client.post(f"{url}/papers/{paper['id']}/explanation"))
    assert all(r.status_code < 400 for r in responses), [(r.url, r.status_code) for r in responses]
    # The keys really were used upstream...
    sent = " ".join(r.headers.get("authorization", "") for r in app.requests)  # repr masks it
    assert OPENAI_KEY in sent and OPENALEX_KEY in sent
    # ...but never reach a response, header or log line.
    for response in responses:
        exposed = response.text + " ".join(f"{k}:{v}" for k, v in response.headers.items())
        assert not any(secret in exposed for secret in SECRETS), response.url
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert not any(secret in logged for secret in SECRETS)


INJECTION = '<img src=x onerror="window.__xss=1">'


def _hostile_papers():
    hostile = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W8001",
            "doi": "https://doi.org/10.8000/hostile",
            "title": f"alpha {INJECTION} hostile title",
            "abstract_inverted_index": {"<script>window.__xss=1</script>": [0]},
        }
    )
    return [hostile, *grouped_papers()]


def test_nfr_sec_2_metadata_html_is_inert(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}")
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    provider.papers = _hostile_papers()
    app = create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    with live_browser(app) as (page, base):
        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog), dialog.dismiss()))
        project = page.request.post(base + "/api/projects", data={"title": "T", "researchQuestion": "q"}).json()
        page.request.post(f"{base}/api/projects/{project['id']}/search")
        page.goto(f"{base}/projects/{project['id']}")
        row = page.locator(".paper-row").filter(has_text="hostile title")
        expect(row).to_contain_text(INJECTION)
        row.click()
        expect(page.locator(".drawer-panel")).to_contain_text(INJECTION)
        assert page.locator("img[src='x']").count() == 0
        assert page.evaluate("window.__xss") is None
        assert dialogs == []
    engine.dispose()


@pytest.mark.parametrize("field", ["doi", "landing_page_url", "oa_url"])
@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://example.org/x"])
def test_nfr_sec_3_only_http_links_survive_normalization(field, url):
    work = dict(WORK)
    if field == "doi":
        work["doi"] = url
    elif field == "landing_page_url":
        work["primary_location"] = {**(WORK.get("primary_location") or {}), "landing_page_url": url}
    else:
        work["open_access"] = {**(WORK.get("open_access") or {}), "oa_url": url}
    paper = normalize_work(work)
    for value in (paper.doiUrl, paper.publicationUrl, paper.openAccessUrl, paper.sourceUrl):
        assert value is None or value.startswith(("http://", "https://"))


def test_nfr_sec_3_manual_reference_rejects_script_urls(search_client):
    client, _, url = search_client
    response = client.post(url + "/references", json={"title": "x", "url": "javascript:alert(1)"})
    assert response.status_code == 422


def test_nfr_sec_3_rendered_links_are_http_or_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'links.db'}")
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    provider.papers = grouped_papers()
    app = create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    with live_browser(app) as (page, base):
        project = page.request.post(base + "/api/projects", data={"title": "T", "researchQuestion": "q"}).json()
        page.request.post(f"{base}/api/projects/{project['id']}/search")
        page.goto(f"{base}/projects/{project['id']}")
        page.locator(".paper-row").first.click()
        expect(page.locator(".drawer-panel")).to_be_visible()
        hrefs = page.eval_on_selector_all("a[href]", "links => links.map(a => a.getAttribute('href'))")
        assert hrefs
        assert all(h.startswith(("http://", "https://", "/")) for h in hrefs), hrefs
    engine.dispose()
```

Also add SEC-4 to the same file:

```python
def _write_targets(client, url):
    papers = client.get(url + "/papers").json()
    query = client.post(url + "/queries/custom", json={"query": "valid query"}).json()
    reference = client.post(url + "/references", json={"title": "A reference"}).json()
    return papers[0]["id"], query["id"], reference["id"]


def test_nfr_sec_4_write_endpoints_reject_bad_input(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = grouped_papers()
    client.post(url + "/search")
    paper_id, query_id, reference_id = _write_targets(client, url)
    cases = [
        ("post", "/api/projects", {"title": "t", "researchQuestion": "q", "bogus": 1}),
        ("post", "/api/projects", {"title": "t", "researchQuestion": "q", "maxPaperCount": 0}),
        ("put", url, {"title": "", "researchQuestion": "q"}),
        ("post", url + "/subtopics", {"name": "n", "bogus": 1}),
        ("patch", url + "/subtopics/0", {"name": "x" * 81}),
        ("post", url + "/subtopics/0/merge", {"targetClusterId": -1}),
        ("patch", f"{url}/papers/{paper_id}", {"clusterId": -1}),
        ("patch", f"{url}/papers/{paper_id}", {"isRelevant": "yes"}),
        ("post", url + "/queries/custom", {"query": "x" * 161}),
        ("patch", f"{url}/queries/{query_id}", {}),
        ("post", url + "/references", {"title": "t", "bogus": 1}),
        ("patch", f"{url}/references/{reference_id}", {"number": 0}),
    ]
    for method, path, body in cases:
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 422, (method, path, body, response.status_code)
```

Check the subtopic name limit (`SubtopicPatch` in `domain.py`) and the reference patch model, and use the real limits in the cases. The rule is each case's *kind* (unknown field, value out of range, wrong type). If a case returns non-422, that is an NFR violation: add `extra="forbid"` or the missing constraint to the model.

- [ ] **Step 3: Run and handle the results**

Run `uv run --extra dev pytest backend/tests/nfr/test_nfr_security.py -q`. Record every initially failing case and its fix in the report. Run the browser tests 3×.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/nfr
git commit -m "Add NFR-SEC-1..4 security tests with a real-adapter mock-transport harness"
```

(Add any production files a fix touched.)

---

### Task 5: Observability and traceability NFRs (OBS-1..2, TRACE-1..2)

**Files:**
- Create: `backend/tests/nfr/test_nfr_observability.py`
- Modify (expected): `backend/researchpilot/search.py`, adding `duplicates=` to the "Search analyzed" log line

**Interfaces:**
- Consumes: the `real_adapter_app` fixture and the `search_client_named`, `engine` and `fakes.*` fixtures.

- [ ] **Step 1: Write the tests**

```python
"""NFR-OBS-1..2 and NFR-TRACE-1..2 (docs/requirements.md §16, §22, §29, §31)."""

import logging
import re

import pytest
from fastapi.testclient import TestClient

from fakes import DATA, grouped_papers
from researchpilot import search as search_module
from researchpilot.api import create_app
from researchpilot.llm import ClusterNaming, QueryExpansion

pytestmark = pytest.mark.nfr

REQUIRED_EVENTS = {
    "provider request": r"OpenAlex request page=\d+",
    "papers returned": r"OpenAlex results received=\d+",
    "duplicates removed": r"Search analyzed .*duplicates=\d+",
    "relevance duration": r"Search analyzed .*duration_ms=\d+",
    "clustering duration": r"Search clustering .*duration_ms=\d+",
    "LLM call": r"OpenAI (query expansion|cluster naming|embeddings batch)",
    "token usage": r"OpenAI completion usage .*total_tokens=\d+",
    "total duration": r"Search completed .*duration_ms=\d+",
}


def test_nfr_obs_1_search_logs_every_required_event(real_adapter_app, caplog):
    caplog.set_level(logging.INFO)
    assert real_adapter_app.client.post(real_adapter_app.url + "/search").status_code == 200
    logged = "\n".join(r.getMessage() for r in caplog.records)
    missing = [name for name, pattern in REQUIRED_EVENTS.items() if not re.search(pattern, logged)]
    assert not missing, f"§29 events not logged: {missing}"


def test_nfr_obs_2_failures_log_codes_not_payloads(real_adapter_app, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    real_adapter_app.fail["openalex"] = (500, "MARKER-PAYLOAD-5a1e")
    response = real_adapter_app.client.post(real_adapter_app.url + "/search")
    assert response.json()["code"] == "UNAVAILABLE"
    del real_adapter_app.fail["openalex"]

    def explode(*args, **kwargs):
        raise RuntimeError("MARKER-EXCEPTION-9c3b")

    monkeypatch.setattr(search_module, "cluster_papers", explode)
    assert real_adapter_app.client.post(real_adapter_app.url + "/search").json()["code"] == "INTERNAL"
    # The app's own loggers; httpx's INFO request log is not enabled in production.
    records = "\n".join(
        f"{r.getMessage()} {r.exc_text or ''}"
        for r in caplog.records
        if r.name.startswith("researchpilot")
    )
    assert "UNAVAILABLE" in records and "INTERNAL" in records
    for marker in ("MARKER-PAYLOAD-5a1e", "MARKER-EXCEPTION-9c3b", "api.openalex.org"):
        assert marker not in records, marker


def test_nfr_trace_1_completed_run_is_reproducible(search_client_named, engine):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.expansion = ["llm testing", "llm code generation"]
    client.post(url + "/search")
    with TestClient(create_app(engine, provider)) as restarted:
        run = restarted.get(url + "/searches").json()[0]
    assert run["parameters"]["query"] == DATA["researchQuestion"]
    assert run["keywords"] == DATA["keywords"]
    assert run["generatedQueries"] == ["llm code generation", "llm testing"]
    assert run["failedQueries"] == []
    assert (run["parameters"]["yearFrom"], run["parameters"]["yearTo"]) == (2021, 2026)
    assert run["parameters"]["maxPaperCount"] == DATA["maxPaperCount"]
    assert run["provider"] == provider.name
    assert run["startedAt"] and run["finishedAt"] and run["finishedAt"] >= run["startedAt"]
    for field in ("totalFound", "duplicateCount", "filteredCount", "paperCount"):
        assert isinstance(run[field], int), field


METADATA_FIELDS = ("title", "authors", "doi", "doiUrl", "venue", "journal", "publisher",
                   "publicationYear", "publicationDate", "citationCount", "sourceUrl",
                   "publicationUrl", "openAccessUrl", "isOpenAccess", "abstract")


def test_nfr_trace_2_llm_output_never_becomes_metadata(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    fake = "Invented Title by A. Hallucination, doi 10.9999/fake"

    async def name_cluster(question, papers):
        return ClusterNaming(name=fake[:80], description=fake, keywords=["10.9999/fake"])

    async def expand_queries(question, keywords):
        return QueryExpansion(queries=["10.9999/fake invented"])

    async def explain_paper(question, subtopic, paper):
        return fake

    llm.name_cluster, llm.expand_queries, llm.explain_paper = name_cluster, expand_queries, explain_paper
    client.post(url + "/search")
    served = client.get(url + "/papers").json()
    client.post(f"{url}/papers/{served[0]['id']}/explanation")
    served = {p["sourceId"]: p for p in client.get(url + "/papers").json()}
    for original in provider.papers:
        expected = original.model_dump(mode="json")
        actual = served[original.sourceId]
        for field in METADATA_FIELDS:
            if field in expected:
                assert actual[field] == expected[field], (original.sourceId, field)
```

Check `METADATA_FIELDS` against the `Paper` model in `papers.py` and use its real field names. Keep only fields that come from the provider. If `explain` needs a paper in a named subtopic, choose `served[0]` accordingly.

- [ ] **Step 2: Run and confirm the expected failure**

Run: `uv run --extra dev pytest backend/tests/nfr/test_nfr_observability.py -q`

Expected: OBS-1 fails with `§29 events not logged: ['duplicates removed']`, because the "Search analyzed" line has no `duplicates=`. Any other failure: fix it locally or stop, and record it.

- [ ] **Step 3: Fix** (`search.py`, the "Search analyzed" log in `_prepare`)

```python
        logger.info(
            "Search analyzed run=%s retrieved=%s unique=%s duplicates=%s filtered=%s duration_ms=%s",
            run.id,
            len(result.papers),
            len(ranked_all),
            duplicate_count,
            len(ranked_all) - len(ranked),
            round((time.perf_counter() - analysis_started) * 1000),
        )
```

- [ ] **Step 4: Run the file, the full suite and ruff; commit**

```bash
git add backend/tests/nfr/test_nfr_observability.py backend/researchpilot/search.py
git commit -m "Log removed duplicates; add NFR-OBS-1..2 and NFR-TRACE-1..2 tests"
```

---

### Task 6: ACC-38 end-to-end acceptance test

**Files:**
- Create: `backend/tests/nfr/test_acceptance.py`

**Interfaces:**
- Consumes: `fakes.*`, `live.live_browser`.

- [ ] **Step 1: Write the test**

```python
"""ACC-38 (docs/requirements.md §38): the MVP scenario, end to end in a real browser."""

import re

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine

from fakes import WORK, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider
from live import live_browser
from researchpilot.api import create_app
from researchpilot.persistence import Base
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr
GROUPS = ("alpha", "bravo", "charlie")


def _corpus():
    papers = [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W{9000 + n}",
                "doi": f"https://doi.org/10.9000/{GROUPS[n % 3]}-{n}",
                "title": f"{GROUPS[n % 3]} study {n} of large language models in software engineering",
            }
        )
        for n in range(40)
    ]
    duplicate = normalize_work(WORK | {"id": "https://openalex.org/W9999", "doi": "https://doi.org/10.9000/alpha-0", "title": "alpha study 0 duplicate record"})
    off_topic = [
        normalize_work(WORK | {"id": f"https://openalex.org/W{9900 + n}", "doi": f"https://doi.org/10.9900/m-{n}", "title": f"marine biology survey {n}"})
        for n in range(3)
    ]
    return [*papers, duplicate, *off_topic]


def test_acc_38_mvp_scenario(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'acc.db'}")
    Base.metadata.create_all(engine)
    provider, llm = RecordingProvider(), RecordingLlmProvider()
    provider.papers = _corpus()
    llm.expansion = ["llm code generation", "llm software testing"]
    titles = {p.title for p in provider.papers}
    app = create_app(engine, provider, RecordingEmbeddingProvider(), llm)
    with live_browser(app, viewport={"width": 1400, "height": 1000}) as (page, base):
        # 1. The user creates a project describing the topic.
        page.goto(base + "/projects/new")
        page.get_by_label("Project title").fill("LLMs in SE")
        page.get_by_label("Research description").fill("Large language models in software engineering")
        page.get_by_label(re.compile("^Keywords")).fill("software engineering")
        page.get_by_role("button", name=re.compile("Create project|Save project")).click()
        expect(page).to_have_url(re.compile(r"/projects/[0-9a-f-]{36}$"))
        # 2-4. Search: generated queries, several dozen papers, dedup, relevance, filtering.
        page.get_by_role("button", name="Find papers", exact=True).click()
        expect(page.locator(".generated-queries li")).to_have_count(2, timeout=15_000)
        expect(page.locator(".generated-queries")).to_contain_text("llm code generation")
        expect(page.get_by_text(re.compile(r"duplicate records? (was|were) merged"))).to_be_visible()
        expect(page.get_by_text(re.compile(r"low-relevance papers? (was|were) filtered"))).to_be_visible()
        rows = page.locator(".paper-row")
        expect(rows).to_have_count(40)  # §38: "at least several dozen" (≥ 36) after filtering
        assert len(provider.calls) == 2  # one retrieval per generated query
        expect(rows.first).to_contain_text(re.compile(r"Relevance: \d+%"))
        # 5-7. Clusters are named and papers sit under subtopics.
        tabs = page.locator(".cluster-tab")
        expect(tabs.filter(has_text="Topic alpha")).to_have_count(1)
        tabs.filter(has_text="Topic alpha").click()
        expect(rows.first).to_contain_text("alpha")
        # 8-9. Clicking a paper shows metadata and the abstract; the UI explains membership.
        rows.first.click()
        drawer = page.locator(".drawer-panel")
        expect(drawer).to_be_visible()
        expect(drawer).to_contain_text("DOI")
        expect(drawer).to_contain_text(" fits ")  # fake explanation text
        # 11. Each paper links to its real scholarly source.
        source = drawer.locator("a[href^='https://openalex.org/W']")
        expect(source.first).to_be_visible()
        # 10. Move the paper to another subtopic.
        select = page.locator(".drawer-organize select")
        target = select.locator("option", has_text="Topic bravo").get_attribute("value")
        select.select_option(target)
        expect(tabs.filter(has_text="Topic bravo")).to_contain_text("14")
        # 11. Rename a generated category.
        page.keyboard.press("Escape")
        tabs.filter(has_text="Topic alpha").click()
        page.locator(".subtopic-menu summary").click()
        page.get_by_role("button", name="Rename subtopic").click()
        page.locator(".rename-form input").fill("Renamed by user")
        page.locator(".rename-form").get_by_role("button", name="Save").click()
        expect(tabs.filter(has_text="Renamed by user")).to_have_count(1)
        # 12. No displayed paper is invented: every title comes from the provider.
        tabs.first.click()
        shown = page.locator(".paper-row h3").all_inner_texts()
        assert shown and set(shown) <= titles
    engine.dispose()
```

This test drives real UI. Where the actual UI differs from these selectors or strings, change the **selector** to the real one and keep the **assertion's meaning**. Examples: the label text of the keywords field, the create-button label, how the drawer closes, the drawer's abstract/DOI markup, or the count shown after a move (each group has 13–14 papers). Never delete an assertion to make it pass. If a scenario step is genuinely impossible in the UI, that is a §38 gap: stop with NEEDS_CONTEXT.

- [ ] **Step 2: Run it 3× and commit**

```bash
for i in 1 2 3; do uv run --extra dev pytest backend/tests/nfr/test_acceptance.py -q | tail -1; done
git add backend/tests/nfr/test_acceptance.py
git commit -m "Add the ACC-38 end-to-end MVP acceptance test"
```

---

### Task 7: Requirements table, docs, version, final gate

**Files:**
- Modify: `docs/requirements.md` (§28, §29, §31), `docs/roadmap.md`, `pyproject.toml`, `uv.lock`, `backend/researchpilot/config.py`
- Create: `docs/features/non-functional-requirements.md`

- [ ] **Step 1: `docs/requirements.md` §31**

Keep the six existing subsections and append:

```markdown
## Measurable requirements

Every NFR in this table is enforced by the automated suite in `backend/tests/nfr/` and must
pass in CI. Performance tests fail above the CI ceiling (3 × target); measured values are
published in the CI `test-report` artifact.

| ID | Requirement | Target | CI ceiling | Test |
|---|---|---|---|---|
| NFR-PERF-1 | 250-paper research map loads with all rows visible | ≤ 1.5 s | 4.5 s | `test_nfr_perf_1_map_renders_250_papers` |
| … one row per NFR from the spec, ending with ACC-38 … |
```

Fill in every row. The IDs and wording come from the spec's catalogue. The test names are the real names from Tasks 2–6; list them with `uv run --extra dev pytest -m nfr --collect-only -q`. Non-performance rows use "pass/fail" as the target and "—" as the ceiling. §28 gets the line "Verified by NFR-REL-1..4." and §29 gets "Verified by NFR-OBS-1..2."

- [ ] **Step 2: Feature note `docs/features/non-functional-requirements.md`**

Write it in the short prose style of `docs/features/semantic-relevance.md`. Cover:
- **The suite:** its location, the `pytest -m nfr` command, the 3× ceiling and the CI artifact.
- **Measured values:** a table of the locally measured values from Task 2.
- **Initial failures and fixes:** which NFRs failed when first written and how each was fixed. The partial query failure and `failedQueries` (migration 015), the missing duplicates log field, and anything the task reports list.

- [ ] **Step 3: Roadmap and version**

In `docs/roadmap.md`, remove the Planned row "Acceptance test and logging" and add to Delivered (a new "Quality" table, with the same columns as the others):

```markdown
### Quality

| Feature | What it does | Note |
| --- | --- | --- |
| Non-functional requirements | Measurable NFRs enforced in CI and the §38 acceptance test | [non-functional-requirements](features/non-functional-requirements.md) |
```

If Planned becomes empty, replace its table with "Nothing planned inside the MVP." Then bump the version:

```bash
sed -i 's/^version = "0.17.0"/version = "0.18.0"/' pyproject.toml
sed -i 's#ResearchPilot/0.17#ResearchPilot/0.18#g' backend/researchpilot/config.py
uv lock
```

- [ ] **Step 4: Full gate plus stability**

Run the full gate from Global Constraints, then `for i in 1 2 3; do uv run --extra dev pytest -m nfr -q | tail -1; done`. Expected: all pass every time.

- [ ] **Step 5: Commit**

```bash
git add docs/requirements.md docs/roadmap.md docs/features/non-functional-requirements.md pyproject.toml uv.lock backend/researchpilot/config.py
git commit -m "Document measurable NFRs and bump version to 0.18.0"
```
