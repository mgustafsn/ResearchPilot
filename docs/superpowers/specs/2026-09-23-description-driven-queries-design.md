# Description-driven search queries

Date: 2026-09-23 · Status: implemented (v0.16.0)

## Problem

The project's "Research question or topic" is sent to OpenAlex verbatim, and query expansion makes
that mandatory in every search. OpenAlex search matches keywords, so a long conversational
topic retrieves poorly. A live run with *"Infrastructure as Code — from manual console work
to declarative provisioning, and where generative AI fits in"* returned 90 unique papers, of
which semantic relevance filtered 55 as off-topic, including stormwater "infrastructure" and "generative
AI in education" papers. Semantic relevance can filter bad papers, but it cannot recover good papers
that retrieval never returned.

## Decision

The topic becomes a **research description**: context for the LLM and the relevance anchor,
never a search query. OpenAlex is queried only with short keyword queries. The LLM generates
them, and the user can review, toggle, edit, and add to them.

## 1. Project fields

| Field (API name) | UI label | Role |
|---|---|---|
| `title` | Project name | Short label. Also the last-resort fallback query. |
| `researchQuestion` | Research description | Required, up to 5000 characters. Used for query generation, the relevance anchor (semantic relevance, unchanged), cluster naming, and explanations. **Never sent to OpenAlex.** |
| `keywords` | Keywords (optional) | Steer query generation and the relevance anchor. They are the fallback queries. |

The API and database name `researchQuestion` stays, which avoids a migration and a breaking
API change. A comment on `ProjectInput.researchQuestion` records that the UI calls it the
research description. The form placeholder becomes "Describe what you want to understand…".
The project page heading "Research topic summary" becomes "Research description".

## 2. Query generation

- The LLM receives the description and keywords and returns **3–6 short keyword queries**.
  Each is 2–6 words, uses scholarly terminology, and contains no sentences, questions, or
  punctuation beyond hyphens. The prompt lives in `prompts.py` and states this.
- `QueryExpansion` validation keeps its existing cleanup: whitespace collapse,
  case-insensitive dedupe, and a 160-character cap. It also **drops queries longer than 8
  words** and raises `QUERIES_MAX` from 5 to 6.
- **Fallback** applies when the LLM is unavailable, times out, or returns no valid queries.
  Each keyword becomes a query; with no keywords, the project name is the only query. The
  description is never a fallback. Fallback queries are saved as generated queries (not
  `userAdded`), so the user can see and edit them.
- The original research question is **no longer prepended** to the query list:
  `_expand_text`, `_selected_queries`, and the `expansion[1:]` slice in
  `expand_project_queries` all change.

## 3. Saved query list

The saved list is the only source of search queries.

- **Generated** queries come from the LLM or the fallback.
- **User** queries (`userAdded = true`) are ones the user added, or generated queries whose
  text the user edited.
- **Regenerate** (`POST /queries`) replaces generated queries only. User queries are kept, and
  a generated query that duplicates a user query (case-insensitively) is skipped.
- **Editing the description or keywords** (`ProjectService.update`) clears generated queries
  only. Today it clears all queries.
- **Add**: `POST /api/projects/{id}/queries/custom` with body `{"query": "..."}`, 1–160
  characters after whitespace collapse. The query is saved enabled with `userAdded = true`. A
  case-insensitive duplicate returns 409.
- **Edit**: `PATCH /api/projects/{id}/queries/{queryId}` with an optional `query`, an optional
  `enabled`, or both. `enabled` moves from the query string to a JSON body, and the frontend
  changes with it. A text change sets `userAdded = true`.
- **Delete**: `DELETE /api/projects/{id}/queries/{queryId}` removes one query. This is needed
  so a user can remove their own mistakes; generated queries can just be toggled off.
- A project holds **at most 10 queries**. Adding an 11th returns 422.
- All query edits return 409 during an active search, like other organization edits.

## 4. Search behavior

- With **no saved queries**, a search generates them first (with fallback), saves them, and
  uses them. This matches today's behavior.
- With saved queries but **none enabled**, the search is rejected with 422 and code
  `NO_ENABLED_QUERIES` before any provider call. Nothing is recorded as a failed run. The
  UI disables "Find papers" and says "Enable at least one search query."
- Otherwise, the enabled queries in saved order are used. Retrieval divides `maxPaperCount`
  across them, as today.
- The run's `generatedQueries` snapshot holds exactly the queries sent. The search panel
  already lists them, which covers §16 transparency.
- `parameters.query` in the run snapshot still records the description, as the project
  context the search ran under. The UI label for it becomes "Description".
- The rest is unchanged: deduplication, semantic relevance (description + keywords), the 40%
  filter, clustering, naming, and explanations.

## 5. Storage

Migration `013_user_queries.sql`:
`ALTER TABLE search_queries ADD COLUMN "userAdded" BOOLEAN NOT NULL DEFAULT FALSE;`
Existing rows are all generated, so the constant default is correct and stays. The column is
added to `SearchQueryRow`, and the `SearchQuery` API model gains `userAdded`.

## 6. Frontend

- Relabel the form field, the placeholder, and the project summary heading.
- The query panel:
  - lists each query with its enable toggle and a "Yours" tag on user queries
  - edits a query's text inline
  - deletes user queries
  - has an "Add query" input
  - keeps the existing "Regenerate suggestions" button, which now keeps user queries
- "Find papers" is disabled when no query is enabled, with the message above.

## 7. Requirements and docs

- `requirements.md`:
  - §3.1: "research topic or research question" becomes "project name and research
    description".
  - §4: the pipeline's first step reads "LLM generates short search queries from the
    research description".
  - §7: the description is not searched verbatim; users can enable, disable, edit, and add
    queries. This replaces "eventually".
  - §38 step 2: "User enters a research description".
- Add `docs/features/description-driven-queries.md`, update the README "Current behavior"
  section, and move the roadmap entry from Planned to Delivered (Projects and retrieval).
- The report can use this as a validation-driven specification change (§3.3, §7.2).

## 8. Testing

- **Unit (`test_openai.py`, `test_search.py`):**
  - queries over 8 words are dropped, and `QUERIES_MAX` is 6
  - the fallback order is keywords, then project name, and never the description
  - the expanded list does not contain the description
- **API (`test_search.py`):**
  - add, edit text, toggle, and delete, including 409 during a search, a duplicate returning
    409, and the 10-query cap
  - regenerate keeps user queries, and editing the project keeps user queries
  - a search with none enabled returns 422 and records no run
  - the retrieval parameters recorded by `RecordingProvider` never include the description
- **Browser (`test_browser.py`):** the relabeled form, adding and toggling a query, and the
  disabled search button when no query is enabled.
- **Migration:** the PostgreSQL suite applies 013.
- **Live check:** rerun the IaC description and compare how many papers are retrieved and
  how many semantic relevance keeps, against the earlier semantic-relevance run (90 unique, 35 kept).

## Out of scope

No second provider (Semantic Scholar), no per-query paper budgets, no query-level result
attribution in the UI, and no rename of the `researchQuestion` API field.
