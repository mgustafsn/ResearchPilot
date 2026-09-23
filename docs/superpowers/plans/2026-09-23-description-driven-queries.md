# Description-Driven Search Queries (Phase 16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop sending the project's research description to OpenAlex. Search only with short keyword queries that the LLM generates and the user can toggle, edit, add, and delete.

**Architecture:** `QueryExpansion` validation and the prompt produce 3–6 short queries. The saved `search_queries` list becomes the only source of retrieval queries, and a `userAdded` flag protects the user's own queries from regeneration. `SearchService.start` rejects searches with no enabled query before a run is recorded. Relevance scoring (Phase 15), clustering, and naming are unchanged.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic 2, PostgreSQL/SQLite, vanilla JS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-23-description-driven-queries-design.md`

## Global Constraints

- The API/DB field name `researchQuestion` stays; the UI calls it "Research description".
- The research description is never sent to a `PaperProvider` as a query.
- LLM queries: 3–6 requested; validation drops any query over 8 words; `QUERIES_MAX = 6`; `QUERY_MAX = 160` characters.
- Fallback order: keywords, then the project `title`. Never the description.
- At most 10 saved queries per project (`SAVED_QUERIES_MAX = 10`).
- Duplicate query text (case-insensitive) → 409. Cap exceeded → 422. No enabled query → 422 with code `NO_ENABLED_QUERIES`, and no run recorded.
- All query edits return 409 during an active search (via `_editable`).
- Work in worktree `../ResearchPilot-phase16` on branch `phase-16`, branched from `main`.
- Gate before merge: `uv run --extra dev ruff check .`, `uv run --extra dev ruff format --check .`, `node --check frontend/app.js`, `uv build`, `uv run --extra dev pytest`, and `TEST_DATABASE_URL=postgresql+psycopg://researchpilot:local-development@localhost:5432/researchpilot_test uv run --extra dev pytest`.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 0: Worktree

- [ ] **Step 1: Create the worktree**

```bash
cd /home/mgustafsson/Projects/Personal/ResearchPilot
git worktree add -b phase-16 ../ResearchPilot-phase16 main
cd ../ResearchPilot-phase16 && uv run --extra dev pytest -q | tail -1
```
Expected: `185 passed, 2 skipped`.

---

### Task 1: Short-query LLM contract

**Files:**
- Modify: `backend/researchpilot/llm.py` (constants and `QueryExpansion._queries`)
- Modify: `backend/researchpilot/prompts.py` (`QUERY_EXPANSION_SYSTEM`, `query_expansion_messages`)
- Test: `backend/tests/test_openai.py`

**Interfaces:**
- Produces: `QueryExpansion.queries` holds at most 6 deduplicated queries of at most 8 words each. `llm.QUERY_WORDS_MAX = 8`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_openai.py`, and add `from researchpilot.llm import QueryExpansion` to the imports)

```python
def test_query_expansion_drops_long_queries_and_caps_at_six():
    long_query = "how are large language models used in modern software engineering practice"
    result = QueryExpansion(
        queries=[long_query, *(f"short query {n}" for n in range(8))]
    )
    assert long_query not in result.queries
    assert result.queries == [f"short query {n}" for n in range(6)]


def test_query_expansion_prompt_asks_for_short_keyword_queries():
    def handler(request):
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        assert "3 to 6" in system and "2 to 6 words" in system
        assert body["messages"][-1]["content"].startswith("Research description:")
        return _completion({"queries": ["LLM automated testing"]})

    assert expand_queries(handler).queries == ["LLM automated testing"]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run --extra dev pytest backend/tests/test_openai.py -q -k "query_expansion_drops or short_keyword"`
Expected: 2 failed.

- [ ] **Step 3: Implement**

In `backend/researchpilot/llm.py`, change the constants to:

```python
QUERY_MAX = 160
QUERY_WORDS_MAX = 8
QUERIES_MAX = 6
```

Then replace the loop body in `QueryExpansion._queries`:

```python
        for item in value:
            query = " ".join(str(item).split())[:QUERY_MAX]
            if len(query.split()) > QUERY_WORDS_MAX:
                continue
            if query and query.casefold() not in {other.casefold() for other in cleaned}:
                cleaned.append(query)
        return cleaned[:QUERIES_MAX]
```

In `backend/researchpilot/prompts.py`, replace the expansion prompt:

```python
QUERY_EXPANSION_SYSTEM = (
    "You write search queries for a scholarly keyword search engine. Given a research "
    "description and optional keywords, return a JSON object with a `queries` array "
    "containing 3 to 6 short keyword queries. Each query has 2 to 6 words, uses academic "
    "terminology, and is not a sentence or a question. Together the queries cover the main "
    "concepts of the description. Stay grounded in the description; do not add unrelated "
    "topics, claims, citations, or invented entities."
)


def query_expansion_messages(question: str, keywords: list[str]) -> list[dict]:
    keyword_text = ", ".join(keywords) if keywords else "(none)"
    return [
        {"role": "system", "content": QUERY_EXPANSION_SYSTEM},
        {
            "role": "user",
            "content": f"Research description: {question}\nKeywords: {keyword_text}",
        },
    ]
```

- [ ] **Step 4: Run and confirm they pass**

Run: `uv run --extra dev pytest backend/tests/test_openai.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/researchpilot/llm.py backend/researchpilot/prompts.py backend/tests/test_openai.py
git commit -m "Ask the LLM for short keyword queries and drop long ones"
```

---

### Task 2: User-owned saved queries (storage and CRUD API)

**Files:**
- Create: `migrations/013_user_queries.sql`
- Modify: `scripts/migrate.py` (bootstrap entries for 13)
- Modify: `backend/researchpilot/papers.py` (`SearchQuery.userAdded`)
- Modify: `backend/researchpilot/domain.py` (`QueryInput`, `QueryPatch`)
- Modify: `backend/researchpilot/search_persistence.py` (`SearchQueryRow.userAdded`, repository query methods)
- Modify: `backend/researchpilot/search.py` (exceptions, `add_query`, `update_query`, `delete_query`, `expand_project_queries`)
- Modify: `backend/researchpilot/service.py` (`update` clears generated queries only)
- Modify: `backend/researchpilot/api.py` (routes and exception handlers)
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Produces:
  - `SAVED_QUERIES_MAX = 10` in `search_persistence.py`
  - `SearchRepository.replace_generated_queries(project_id, queries: list[str]) -> None`
  - `SearchRepository.clear_generated_queries(project_id) -> None`
  - `SearchRepository.add_query(project_id, text: str) -> SearchQuery`
  - `SearchRepository.update_query(project_id, query_id, text: str | None, enabled: bool | None) -> SearchQuery | None`
  - `SearchRepository.delete_query(project_id, query_id) -> bool`
  - exceptions `InvalidQuery` (422), `DuplicateQuery` (409), `NoEnabledQueries` (422, code `NO_ENABLED_QUERIES`) in `search.py`
  - `SearchService.add_query(project_id, text)`, `SearchService.update_query(project_id, query_id, patch: QueryPatch)`, `SearchService.delete_query(project_id, query_id)`
- Removed: `SearchRepository.replace_queries`, `SearchRepository.clear_queries`, `SearchRepository.set_query_enabled`, `SearchService.set_query_enabled`. Task 2 replaces all their callers.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_search.py`, replace `test_disabled_saved_query_is_not_regenerated_or_retrieved` and `test_project_question_edit_clears_saved_queries` with the tests below. Task 3 rewrites the retrieval assertions, so these tests exercise only the query list.

```python
def _add(client, url, text):
    return client.post(url + "/queries/custom", json={"query": text})


def test_user_can_add_edit_toggle_and_delete_queries(search_client_named):
    client, _, _, _, url = search_client_named
    added = _add(client, url, "  terraform   provisioning ")
    assert added.status_code == 201
    query = added.json()
    assert query["query"] == "terraform provisioning"
    assert query["userAdded"] is True and query["enabled"] is True
    toggled = client.patch(f"{url}/queries/{query['id']}", json={"enabled": False})
    assert toggled.status_code == 200 and toggled.json()["enabled"] is False
    edited = client.patch(f"{url}/queries/{query['id']}", json={"query": "terraform modules"})
    assert edited.json()["query"] == "terraform modules"
    assert client.delete(f"{url}/queries/{query['id']}").status_code == 204
    assert client.get(url + "/queries").json() == []


def test_editing_a_generated_query_makes_it_the_users(search_client_named):
    client, _, _, llm, url = search_client_named
    llm.expansion = ["infrastructure as code"]
    generated = client.post(url + "/queries").json()[0]
    assert generated["userAdded"] is False
    edited = client.patch(f"{url}/queries/{generated['id']}", json={"query": "iac tooling"})
    assert edited.json()["userAdded"] is True


def test_query_validation_duplicates_and_cap(search_client_named):
    client, _, _, _, url = search_client_named
    assert _add(client, url, "   ").status_code == 422
    assert _add(client, url, "x" * 161).status_code == 422
    assert _add(client, url, "Cloud Automation").status_code == 201
    assert _add(client, url, "cloud automation").status_code == 409
    for n in range(9):
        assert _add(client, url, f"query {n}").status_code == 201
    assert _add(client, url, "one too many").status_code == 422
    assert client.patch(f"{url}/queries/{uuid4()}", json={"enabled": False}).status_code == 404
    first = client.get(url + "/queries").json()[0]
    assert client.patch(f"{url}/queries/{first['id']}", json={}).status_code == 422


def test_regenerate_keeps_user_queries_and_skips_duplicates(search_client_named):
    client, _, _, llm, url = search_client_named
    _add(client, url, "terraform")
    llm.expansion = ["Terraform", "policy as code"]
    queries = client.post(url + "/queries").json()
    assert [(q["query"], q["userAdded"]) for q in queries] == [
        ("policy as code", False),
        ("terraform", True),
    ]
    llm.expansion = ["cloud provisioning"]
    queries = client.post(url + "/queries").json()
    assert [q["query"] for q in queries] == ["cloud provisioning", "terraform"]


def test_project_edit_clears_generated_queries_only(search_client_named):
    client, _, _, llm, url = search_client_named
    llm.expansion = ["alternate query"]
    client.post(url + "/queries")
    _add(client, url, "my own query")
    changed = {**DATA, "researchQuestion": "new research description"}
    assert client.put(url, json=changed).status_code == 200
    assert [q["query"] for q in client.get(url + "/queries").json()] == ["my own query"]


def test_query_edits_are_blocked_during_a_search(search_client_named):
    client, _, _, _, url = search_client_named
    query = _add(client, url, "terraform").json()
    # Opens a real active run, as test_organization_search_lease does.
    client.app.state.search.start(UUID(url.split("/")[-1]))
    assert _add(client, url, "another").status_code == 409
    assert client.patch(f"{url}/queries/{query['id']}", json={"enabled": False}).status_code == 409
    assert client.delete(f"{url}/queries/{query['id']}").status_code == 409
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run --extra dev pytest backend/tests/test_search.py -q -k "queries or query"`
Expected: the new tests fail (404/405 on the new routes and missing `userAdded`).

- [ ] **Step 3: Migration and bootstrap**

`migrations/013_user_queries.sql`:

```sql
ALTER TABLE search_queries ADD COLUMN "userAdded" BOOLEAN NOT NULL DEFAULT FALSE;
```

In `scripts/migrate.py`, add `13: ("search_queries",),` to `requirements` after the `12` entry. Add `13: {"search_queries": {"userAdded"}},` to `required_columns` after the `12` entry.

- [ ] **Step 4: Models**

In `backend/researchpilot/papers.py`, add a field to `SearchQuery`:

```python
    enabled: bool = True
    userAdded: bool = False
```

In `backend/researchpilot/domain.py`, add these after `SubtopicMerge`:

```python
def _collapse_whitespace(value):
    return " ".join(value.split()) if isinstance(value, str) else value


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=160)

    _collapse = field_validator("query", mode="before")(_collapse_whitespace)


class QueryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: StrictBool | None = None

    _collapse = field_validator("query", mode="before")(_collapse_whitespace)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.query is None and self.enabled is None:
            raise ValueError("Provide query and/or enabled")
        return self
```

Also add a comment above `researchQuestion` in `ProjectInput`:

```python
    # Shown as "Research description": LLM context and relevance anchor, never searched.
    researchQuestion: str = Field(min_length=1, max_length=5000)
```

- [ ] **Step 5: Repository**

In `backend/researchpilot/search_persistence.py`, add a column to `SearchQueryRow`:

```python
    enabled: Mapped[bool] = mapped_column(default=True)
    userAdded: Mapped[bool] = mapped_column(default=False)
```

Add `SAVED_QUERIES_MAX = 10` at module level, above `class SearchRepository`.

SQL `ORDER BY query` sorts differently on SQLite (binary) and PostgreSQL (collation), so order the saved list case-insensitively in Python. Replace `queries` with:

```python
    def queries(self, project_id):
        rows = self.session.scalars(
            select(SearchQueryRow).where(SearchQueryRow.projectId == project_id)
        )
        return sorted(
            (SearchQuery.model_validate(row) for row in rows),
            key=lambda item: (item.query.casefold(), str(item.id)),
        )
```

Replace `replace_queries`, `clear_queries`, and `set_query_enabled` with:

```python
    def replace_generated_queries(self, project_id, queries):
        """Swap generated suggestions; the user's own queries are kept and never duplicated."""
        self.clear_generated_queries(project_id)
        self.session.flush()
        kept = {item.query.casefold() for item in self.queries(project_id)}
        rows = []
        for query in queries:
            if len(kept) >= SAVED_QUERIES_MAX:
                break
            if query.casefold() in kept:
                continue
            kept.add(query.casefold())
            rows.append(
                SearchQueryRow(
                    projectId=project_id, id=uuid4(), query=query, enabled=True, userAdded=False
                )
            )
        self.session.add_all(rows)
        self.session.flush()

    def clear_generated_queries(self, project_id):
        self.session.execute(
            delete(SearchQueryRow).where(
                SearchQueryRow.projectId == project_id, SearchQueryRow.userAdded.is_(False)
            )
        )

    def add_query(self, project_id, text):
        row = SearchQueryRow(
            projectId=project_id, id=uuid4(), query=text, enabled=True, userAdded=True
        )
        self.session.add(row)
        self.session.flush()
        return SearchQuery.model_validate(row)

    def update_query(self, project_id, query_id, text=None, enabled=None):
        row = self.session.get(SearchQueryRow, query_id)
        if row is None or row.projectId != project_id:
            return None
        if text is not None and text != row.query:
            row.query = text
            row.userAdded = True
        if enabled is not None:
            row.enabled = enabled
        self.session.flush()
        return SearchQuery.model_validate(row)

    def delete_query(self, project_id, query_id):
        row = self.session.get(SearchQueryRow, query_id)
        if row is None or row.projectId != project_id:
            return False
        self.session.delete(row)
        self.session.flush()
        return True
```

- [ ] **Step 6: Service**

In `backend/researchpilot/search.py`, add these exceptions after `UnknownCluster`:

```python
class InvalidQuery(Exception):
    """A query change that breaks the saved-query rules (e.g. the per-project cap)."""


class DuplicateQuery(Exception):
    """The query text already exists in the project's list (case-insensitive)."""


class NoEnabledQueries(Exception):
    """Saved queries exist but every one is disabled, so there is nothing to search."""
```

Import `SAVED_QUERIES_MAX` from `.search_persistence`, alongside the existing import from that module. Replace `set_query_enabled` with:

```python
    def add_query(self, project_id, text):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            repository = SearchRepository(session)
            saved = repository.queries(project_id)
            if any(item.query.casefold() == text.casefold() for item in saved):
                raise DuplicateQuery("That query is already in the list.")
            if len(saved) >= SAVED_QUERIES_MAX:
                raise InvalidQuery(
                    f"A project can have at most {SAVED_QUERIES_MAX} search queries."
                )
            return repository.add_query(project_id, text)

    def update_query(self, project_id, query_id, patch):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            repository = SearchRepository(session)
            if patch.query is not None and any(
                item.id != query_id and item.query.casefold() == patch.query.casefold()
                for item in repository.queries(project_id)
            ):
                raise DuplicateQuery("That query is already in the list.")
            updated = repository.update_query(project_id, query_id, patch.query, patch.enabled)
            if updated is None:
                raise ProjectNotFound()
            return updated

    def delete_query(self, project_id, query_id):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            if not SearchRepository(session).delete_query(project_id, query_id):
                raise ProjectNotFound()
```

In `expand_project_queries`, replace `SearchRepository(session).replace_queries(project_id, expansion[1:])` with `SearchRepository(session).replace_generated_queries(project_id, expansion[1:])`. Task 3 removes the `[1:]` slice once `_expand_text` stops prepending the description.

In `backend/researchpilot/service.py`, change `.clear_queries(project_id)` to `.clear_generated_queries(project_id)`.

- [ ] **Step 7: API**

In `backend/researchpilot/api.py`:
- import `QueryInput` and `QueryPatch` from `.domain`
- import `DuplicateQuery`, `InvalidQuery`, and `NoEnabledQueries` from `.search`
- add these handlers next to the `UnknownCluster` handler:

```python
    @app.exception_handler(InvalidQuery)
    async def invalid_query(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DuplicateQuery)
    async def duplicate_query(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(NoEnabledQueries)
    async def no_enabled_queries(request, exc):
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "code": "NO_ENABLED_QUERIES"}
        )
```

Replace the `set_query_enabled` route with:

```python
    @app.post(
        "/api/projects/{project_id}/queries/custom", response_model=SearchQuery, status_code=201
    )
    def add_query(project_id: UUID, body: QueryInput):
        return app.state.search.add_query(project_id, body.query)

    @app.patch("/api/projects/{project_id}/queries/{query_id}", response_model=SearchQuery)
    def update_query(project_id: UUID, query_id: UUID, patch: QueryPatch):
        return app.state.search.update_query(project_id, query_id, patch)

    @app.delete("/api/projects/{project_id}/queries/{query_id}", status_code=204)
    def delete_query(project_id: UUID, query_id: UUID):
        app.state.search.delete_query(project_id, query_id)
        return Response(status_code=204)
```

- [ ] **Step 8: Run and confirm the tests pass**

Run: `uv run --extra dev pytest -q`
Expected: all pass, including browser tests. The frontend still sends `?enabled=`, but no browser test toggles queries yet; Task 4 fixes the frontend.

- [ ] **Step 9: Commit**

```bash
git add migrations/013_user_queries.sql scripts/migrate.py backend/researchpilot backend/tests/test_search.py
git commit -m "Let users add, edit, and delete search queries; regeneration keeps theirs"
```

---

### Task 3: Search with saved queries only, never the description

**Files:**
- Modify: `backend/researchpilot/search.py` (`start`, `_selected_queries` → `_saved_queries`, `_expand_queries`, `_expand_text`, `expand_project_queries`)
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Consumes: `SearchRepository.replace_generated_queries`, `SearchRepository.queries`, and `NoEnabledQueries` from Task 2.
- Produces: `SearchService._expand_text(question, keywords, title) -> list[str]`, which never includes `question`.

- [ ] **Step 1: Write the failing tests**

In `RecordingLlmProvider`, add `self.expansion_error = None` in `__init__`. Change `expand_queries` to:

```python
    async def expand_queries(self, question, keywords):
        if self.expansion_error:
            raise self.expansion_error
        return QueryExpansion(queries=self.expansion)
```

Replace `test_query_expansion_is_persisted_and_retrieves_each_query` with:

```python
def _retrieved(provider):
    return [parameters.query for parameters in provider.calls]


def test_search_uses_generated_queries_never_the_description(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["generative AI software development", "LLM code generation"]
    run = client.post(url + "/search").json()
    # Saved queries are listed case-insensitively alphabetical.
    assert run["generatedQueries"] == ["generative AI software development", "LLM code generation"]
    assert _retrieved(provider) == run["generatedQueries"]
    assert DATA["researchQuestion"] not in _retrieved(provider)
    saved = client.get(url + "/queries").json()
    assert [(q["query"], q["userAdded"]) for q in saved] == [
        ("generative AI software development", False),
        ("LLM code generation", False),
    ]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run --extra dev pytest backend/tests/test_search.py -q -k "generated_queries or disabled_queries or no_enabled or falls_back"`
Expected: failures, because the description is still retrieved first and no 422 is raised.

- [ ] **Step 3: Implement**

In `SearchService.start`, directly after the `SearchConflict` check for an active search, add:

```python
            saved = repository.queries(project.id)
            if saved and not any(item.enabled for item in saved):
                raise NoEnabledQueries("Enable at least one search query.")
```

Replace `_selected_queries` with:

```python
    def _saved_queries(self, project_id):
        with Session(self.engine) as session:
            project = self._project(session, project_id)
            return SearchRepository(session).queries(project_id), project.title

    def _save_generated_queries(self, project_id, queries):
        with Session(self.engine) as session, session.begin():
            repository = SearchRepository(session)
            repository.replace_generated_queries(project_id, queries)
            return repository.queries(project_id)
```

In `expand_project_queries`, read `project.title` alongside the description and keywords. Pass all three to `_expand_text` and drop the slice:

```python
    async def expand_project_queries(self, project_id):
        with Session(self.engine) as session:
            project = self._editable(session, project_id)
            question, keywords, title = project.researchQuestion, project.keywords, project.title
        queries = await self._expand_text(question, keywords, title)
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            SearchRepository(session).replace_generated_queries(project_id, queries)
            return SearchRepository(session).queries(project_id)
```

Replace `_expand_queries` and `_expand_text` with:

```python
    async def _expand_queries(self, run):
        saved, title = await asyncio.to_thread(self._saved_queries, run.projectId)
        if not saved:
            generated = await self._expand_text(run.researchQuestion, run.keywords, title)
            saved = await asyncio.to_thread(
                self._save_generated_queries, run.projectId, generated
            )
            logger.info("Search generated queries run=%s count=%s", run.id, len(saved))
        selected = [item.query for item in saved if item.enabled]
        logger.info("Search using saved queries run=%s selected=%s", run.id, len(selected))
        return selected

    async def _expand_text(self, question, keywords, title):
        """Short keyword queries for the description; never the description itself."""
        fallback = list(keywords) or [title]
        expand = getattr(self.llm_provider, "expand_queries", None)
        if expand is None:
            return fallback
        try:
            expansion = await asyncio.wait_for(expand(question, keywords), NAMING_TIMEOUT_SECONDS)
        except (TimeoutError, ProviderError, TypeError, AttributeError):
            logger.warning("Query expansion unavailable; using keywords or project title")
            return fallback
        return expansion.queries or fallback
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run --extra dev pytest -q`
Expected: all pass. If an older test asserts that the description was retrieved, change it to assert the fallback (`DATA["keywords"]`), because that is the spec'd behavior now. Don't weaken any other assertion.

- [ ] **Step 5: Commit**

```bash
git add backend/researchpilot/search.py backend/tests/test_search.py
git commit -m "Search only saved short queries; fall back to keywords, then the project title"
```

---

### Task 4: Frontend query editor and relabeled description

**Files:**
- Modify: `frontend/app.js` (project form, overview summary heading, `setBusy`, `showSearch`)
- Modify: `frontend/styles.css` (query row styles)
- Test: `backend/tests/test_browser.py`

**Interfaces:**
- Consumes: `POST /queries/custom`, `PATCH /queries/{id}` (JSON body `{query?, enabled?}`), `DELETE /queries/{id}`, `POST /queries`, `GET /queries` (items include `userAdded`), and search 422 `NO_ENABLED_QUERIES`.

- [ ] **Step 1: Write the failing browser test** (append to `backend/tests/test_browser.py`)

```python
def test_query_editor_and_description_label(browser_app):
    page, url, _, _, llm = browser_app
    expect(page.get_by_text("Research description", exact=True)).to_be_visible()
    page.get_by_placeholder("Add a search query").fill("terraform provisioning")
    page.get_by_role("button", name="Add", exact=True).click()
    row = page.locator(".query-option").filter(has=page.locator("input[value='terraform provisioning']"))
    expect(row.locator(".query-tag")).to_have_text("Yours")
    row.get_by_role("checkbox").uncheck()
    expect(page.get_by_text("Enable at least one search query.")).to_be_visible()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_disabled()
    row.get_by_role("checkbox").check()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()
    queries = page.request.get(url + "/queries").json()
    assert [(q["query"], q["enabled"]) for q in queries] == [("terraform provisioning", True)]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run --extra dev pytest backend/tests/test_browser.py -q -k query_editor`
Expected: FAIL (no "Research description" label or add-query input yet).

- [ ] **Step 3: Implement the form and overview relabel**

In the project form template in `frontend/app.js`, replace these two lines:

```js
    <label for="researchQuestion">Research question or topic</label>
    <textarea id="researchQuestion" name="researchQuestion" required maxlength="5000" placeholder="What would you like to explore?"></textarea>
```

with:

```js
    <label for="researchQuestion">Research description</label>
    <textarea id="researchQuestion" name="researchQuestion" required maxlength="5000" aria-describedby="description-help" placeholder="Describe what you want to understand…"></textarea>
    <p id="description-help" class="field-help">Guides query suggestions, relevance, and subtopic names. It is not searched directly.</p>
```

In the project overview, change `panel(left, 'Research topic summary')` to `panel(left, 'Research description')`.

- [ ] **Step 4: Implement the busy/enabled gate**

After `let pendingSearch = false;`, add `let noEnabledQueries = false;`. In `setBusy`, change `searchButton.disabled = value;` to `searchButton.disabled = value || noEnabledQueries;`.

- [ ] **Step 5: Implement the query editor**

In `showSearch(history, savedQueries)`:
- Set `noEnabledQueries = Boolean(savedQueries?.length) && !savedQueries.some(item => item.enabled);` as the first line, before `setBusy(...)`.
- Replace the help paragraph with `'OpenAlex searches the enabled queries below with the saved year range. Your description guides suggestions and relevance but is never searched directly.'`.
- Change the `'Search query'` label to `'Description'`.
- Replace everything from `const queryControls = …` through the end of the `if (savedQueries?.length) { … }` block with:

```js
    const queryControls = element('div', '', searchBody, 'query-controls');
    element('span', 'Search queries', queryControls, 'query-label');
    const queryRequest = async (path, options) => {
      errorBox.hidden = true;
      try { await api(`${projectPath}/queries${path}`, {headers: {'Content-Type': 'application/json'}, ...options}); }
      catch (error) { showError(error); }
      await refresh();
    };
    if (!savedQueries?.length) {
      element('p', 'Queries are suggested from your description on the first search, or suggest them now.', queryControls, 'field-help');
    }
    for (const saved of savedQueries ?? []) {
      const row = element('div', '', queryControls, 'query-option');
      const checkbox = element('input', '', row);
      checkbox.type = 'checkbox';
      checkbox.checked = saved.enabled;
      checkbox.disabled = busy;
      checkbox.setAttribute('aria-label', `Include ${saved.query}`);
      checkbox.addEventListener('change', () => queryRequest(`/${saved.id}`, {method: 'PATCH', body: JSON.stringify({enabled: checkbox.checked})}));
      const text = element('input', '', row, 'query-text');
      text.value = saved.query;
      text.setAttribute('value', saved.query);
      text.maxLength = 160;
      text.disabled = busy;
      text.setAttribute('aria-label', 'Search query');
      text.addEventListener('change', () => {
        const value = text.value.trim();
        if (!value || value === saved.query) { text.value = saved.query; return; }
        queryRequest(`/${saved.id}`, {method: 'PATCH', body: JSON.stringify({query: value})});
      });
      if (saved.userAdded) {
        element('span', 'Yours', row, 'query-tag');
        const remove = element('button', '×', row, 'secondary query-remove');
        remove.type = 'button';
        remove.disabled = busy;
        remove.setAttribute('aria-label', `Remove ${saved.query}`);
        remove.addEventListener('click', () => queryRequest(`/${saved.id}`, {method: 'DELETE'}));
      }
    }
    if (noEnabledQueries) element('p', 'Enable at least one search query.', queryControls, 'search-failure');
    const addForm = element('form', '', queryControls, 'query-add');
    const addInput = element('input', '', addForm);
    addInput.placeholder = 'Add a search query';
    addInput.maxLength = 160;
    addInput.disabled = busy;
    const addButton = element('button', 'Add', addForm, 'secondary');
    addButton.disabled = busy;
    addForm.addEventListener('submit', event => {
      event.preventDefault();
      const value = addInput.value.trim();
      if (value) queryRequest('/custom', {method: 'POST', body: JSON.stringify({query: value})});
    });
    const suggest = element('button', savedQueries?.length ? 'Regenerate suggestions' : 'Suggest queries', queryControls, 'secondary');
    suggest.disabled = busy;
    suggest.addEventListener('click', async () => {
      suggest.disabled = true;
      try { await api(`${projectPath}/queries`, {method: 'POST'}); await refresh(); }
      catch (error) { showError(error); suggest.disabled = false; }
    });
```

Leave the existing "Queries used for this search" list unchanged.

- [ ] **Step 6: Styles** (in `frontend/styles.css`, replace the `.query-option` rule)

```css
.query-option { display: flex; gap: 7px; align-items: center; font-size: 12px; color: #52627a; }
.query-text { flex: 1; min-width: 0; font-size: 12px; padding: 4px 6px; }
.query-tag { font-size: 11px; padding: 1px 6px; border-radius: 999px; background: #eef2f8; color: #52627a; }
.query-remove { padding: 2px 8px; }
.query-add { display: flex; gap: 7px; }
.query-add input { flex: 1; min-width: 0; font-size: 12px; padding: 4px 6px; }
```

- [ ] **Step 7: Run the checks**

Run: `node --check frontend/app.js && uv run --extra dev pytest backend/tests/test_browser.py -q`
Expected: all browser tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/app.js frontend/styles.css backend/tests/test_browser.py
git commit -m "Add the search query editor and relabel the research description"
```

---

### Task 5: Requirements, docs, version, verification, live check

**Files:**
- Modify: `docs/requirements.md` (§3.1, §4, §7, §38 step 2)
- Create: `docs/phase-16.md`
- Modify: `README.md` ("Current behavior" query paragraph and API list), `docs/roadmap.md` (row 16, and the follow-up line now reads Phase 17)
- Modify: `pyproject.toml` (`0.16.0`), `uv.lock` (`uv lock`), `backend/researchpilot/config.py` (`ResearchPilot/0.16`, both occurrences)

- [ ] **Step 1: Requirements edits** (exact replacements in `docs/requirements.md`)

- §3.1: change "* Research topic or research question" to "* Research description (what the user wants to understand; not searched directly)".
- §4 pipeline: change "LLM generates search terms / related queries" to "LLM generates short search queries from the research description".
- §7: replace "The user should eventually be able to enable/disable individual generated queries." with:
  "The research description itself is not sent to scholarly providers. The user can enable, disable, edit, add, and delete queries; queries the user wrote or edited are never replaced by regeneration. If query generation fails, the project's keywords (or, without keywords, the project name) are used as queries."
- §38 step 2: change "User enters:" to "User enters a research description:".

- [ ] **Step 2: Phase note** (`docs/phase-16.md`, in the short prose style of `docs/phase-15.md`)

Cover these points:
- **Why:** the live IaC run, where a long conversational topic sent verbatim to keyword search let Phase 15 filter 55 of 90 unique papers.
- **Query rules:** 3–6 queries of at most 8 words, with the keyword → title fallback.
- **The saved list:** a `userAdded` flag via migration 013, with the rules for regenerate and edit.
- **Search rejection:** a search with no enabled query is rejected with 422 `NO_ENABLED_QUERIES` and no run.
- **API change:** `PATCH /queries/{id}` moves from `?enabled=` to a JSON body.
- **Unchanged:** Phase 15 relevance still uses the description plus keywords.
- **Live check:** the measured before/after numbers from Step 5.

- [ ] **Step 3: README and roadmap**

In the README "Current behavior" section, replace the sentence "The saved research question is always searched, and the LLM may add up to five grounded related queries." with "The research description is never searched directly. The LLM turns it and the keywords into 3–6 short keyword queries; if that fails, keywords (or the project name) are used." Update the `/queries` API bullet to list: GET the saved list, POST to regenerate suggestions (keeps user queries), POST `/custom` to add, PATCH `/{queryId}` with a JSON `query` and/or `enabled`, DELETE `/{queryId}`. Add roadmap row `| 16 | Description-driven short search queries with a user-editable query list |` and change the follow-up section to reference Phase 17.

- [ ] **Step 4: Version**

```bash
sed -i 's/^version = "0.15.0"/version = "0.16.0"/' pyproject.toml
sed -i 's#ResearchPilot/0.15#ResearchPilot/0.16#g' backend/researchpilot/config.py
uv lock
```

- [ ] **Step 5: Full gate plus live check**

Run the full gate from Global Constraints. Expected: everything passes, and the PostgreSQL suite applies 013. Then apply migration 013 to the dev database and run the live comparison on port 8001, leaving the user's server on :8000 alone:

```bash
uv run --env-file ../ResearchPilot/.env python scripts/migrate.py
uv run --env-file ../ResearchPilot/.env uvicorn researchpilot.api:app --host 127.0.0.1 --port 8001 --app-dir backend   # background
```

Create a project titled "IaC (Phase 16 check)" with the same description, keywords `["IaC"]`, and the same year range and paper limit as "IaC (Phase 15 check)". Run a search, then record the generated queries, `totalFound`, the unique count (`paperCount + filteredCount`), `filteredCount`, `paperCount`, the top 10 titles with scores, and the subtopic names. Compare against Phase 15: 90 unique, 55 filtered, 35 kept. Put the numbers in `docs/phase-16.md`.

- [ ] **Step 6: Commit**

```bash
git add docs/requirements.md docs/phase-16.md README.md docs/roadmap.md pyproject.toml uv.lock backend/researchpilot/config.py
git commit -m "Document Phase 16 description-driven queries and bump version to 0.16.0"
```

- [ ] **Step 7: Hand back**

Report the live comparison to the user. Merging `phase-16` into `main` and pushing wait for the user's go-ahead.
