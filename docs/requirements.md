# ResearchPilot — MVP Requirements

## 1. Product Overview

ResearchPilot is a web application for discovering academic research papers and automatically organizing them into meaningful subtopics.

A user enters a research topic or research question. The system searches trusted scholarly data sources, retrieves relevant papers, ranks them by relevance, and groups them into AI-generated subtopics.

The system must use real scholarly sources for paper discovery. The LLM must never invent papers or use its internal knowledge as the authoritative source of citations.

Example input:

> Large language models in software engineering

Possible output:

* LLMs for code generation
* Automated software testing
* Requirements engineering
* Developer productivity
* Program repair
* Human–AI collaboration

Each category contains relevant papers and information explaining why each paper belongs in that category.

---

# 2. Core Product Goals

The MVP should allow the user to:

1. Enter a research topic or research question.
2. Search real scholarly APIs for papers.
3. View normalized paper metadata.
4. Automatically rank papers by relevance.
5. Automatically organize papers into subtopics.
6. Understand why papers were categorized into each subtopic.
7. Manually modify the generated organization.
8. Open the original publication or available full text.
9. Save a research search/project for later use.

The architecture should also support future institutional library authentication without requiring a major redesign.

---

# 3. MVP User Flow

## 3.1 Start Research Project

The user should be able to create a research project by entering:

* Project name
* Research description (what the user wants to understand; not searched directly)
* Optional keywords
* Optional year range
* Maximum number of papers to retrieve

Example:

Research description:

> How are large language models currently being used in software engineering research?

Year range:

> 2022–2026

Maximum papers:

> 100

The user clicks:

> Search literature

---

# 4. Search Pipeline

The backend should execute the following pipeline:

```text
User research topic
        ↓
LLM generates short search queries from the research description
        ↓
Scholarly APIs queried
        ↓
Results normalized
        ↓
Duplicates removed
        ↓
Relevance calculated
        ↓
Low relevance papers removed
        ↓
Paper embeddings generated
        ↓
Papers clustered
        ↓
LLM interprets clusters
        ↓
LLM generates subtopic names/descriptions
        ↓
Research map returned to frontend
```

Each step should be implemented as a logically separate service/module.

---

# 5. Scholarly Data Sources

The system must retrieve papers from external scholarly sources rather than asking the LLM to generate citations.

The first implementation should support an abstraction such as:

```text
PaperProvider
```

Example implementations could eventually include:

* OpenAlex
* Semantic Scholar
* Crossref
* arXiv
* PubMed
* Scopus

The MVP only needs one or two providers.

Recommended first provider:

> OpenAlex

Providers should return data through a common normalized interface.

Example:

```text
Paper
- id
- doi
- title
- abstract
- authors
- publicationYear
- publicationDate
- journal
- publisher
- citationCount
- source
- sourceUrl
- doiUrl
- openAccessUrl
- isOpenAccess
```

---

# 6. Paper Deduplication

The same paper may appear in multiple scholarly databases.

The system should deduplicate papers using, in priority order:

1. DOI
2. External scholarly identifier
3. Normalized title comparison

Duplicate records should be merged rather than displayed multiple times.

---

# 7. Query Expansion

The original user query may be too narrow to retrieve representative literature.

The LLM should generate a small set of related scholarly search queries.

Example:

Input:

> LLMs in software engineering

Generated queries might include:

* large language models software engineering
* generative AI software development
* LLM code generation
* LLM automated testing
* LLM requirements engineering

Generated queries must remain visible in the project so the search process is transparent.

The research description itself is not sent to scholarly providers. The user can enable, disable, edit, add, and delete queries; queries the user wrote or edited are never replaced by regeneration. If query generation fails, the project's keywords (or, without keywords, the project name) are used as queries.

---

# 8. Relevance Ranking

Each retrieved paper should receive a relevance score based on how closely it relates to the user's original research topic.

Example:

```text
relevanceScore: 0.91
```

The relevance score may use:

* semantic similarity between the query and paper abstract/title
* embeddings
* keyword overlap
* publication metadata
* optional LLM reranking

The MVP should avoid sending every paper individually through an expensive LLM call where possible.

Prefer embeddings for initial ranking.

---

# 9. Paper Clustering

Relevant papers should be grouped into semantic clusters.

The LLM should NOT be responsible for the entire clustering process.

Preferred approach:

```text
paper title + abstract
        ↓
embedding
        ↓
vector representation
        ↓
clustering algorithm
        ↓
clusters
        ↓
LLM
        ↓
human-readable cluster/subtopic name
```

Possible clustering implementations include:

* K-means
* Agglomerative clustering
* HDBSCAN

The clustering implementation should be replaceable.

---

# 10. AI-Generated Subtopics

After clustering papers, send representative information about each cluster to the LLM.

The LLM should generate:

```text
Subtopic
- name
- description
- keywords
```

Example:

```text
name:
LLMs for Automated Software Testing

description:
Research investigating the use of large language models for generating,
executing, improving, and evaluating software tests.

keywords:
testing, test generation, unit tests, fuzzing, validation
```

The LLM should not generate paper metadata.

It should only interpret data provided by the application.

---

# 11. Explanation for Classification

Each paper should include a short explanation showing why it was placed into a particular subtopic.

Example:

> This paper evaluates GPT-based generation of unit tests for Java programs, making it directly relevant to automated software testing.

This explanation must be based only on available paper metadata or abstract content.

---

# 12. Research Map UI

The main project page should contain three primary areas.

## Left Sidebar

Contains:

* Project navigation
* Search history
* Saved research projects
* Settings

## Main Content

Contains:

* Research topic
* Search parameters
* Number of papers found
* Generated subtopics
* Paper lists

Example:

```text
Large Language Models in Software Engineering

124 papers found
6 subtopics

▼ Code Generation                     32 papers
▼ Software Testing                    21 papers
▼ Developer Productivity              18 papers
▼ Requirements Engineering            14 papers
▼ Program Repair                      13 papers
▼ Human–AI Collaboration              11 papers

Uncategorized                         15 papers
```

## Paper Details Panel

Clicking a paper opens a side panel containing:

* Title
* Authors
* Publication year
* Journal/conference
* DOI
* Citation count
* Abstract
* Relevance score
* Classification explanation
* Source database
* Full-text availability
* Link to publication

---

# 13. Paper Card

Each paper card should display at minimum:

```text
Title

Authors • Year

Journal / Conference

Relevance: 92%
Citations: 214

Why it belongs here:
Short classification explanation.

[View details] [Open publication]
```

---

# 14. Manual Organization

AI organization should always be editable by the user.

The user must be able to:

* Rename a subtopic
* Move a paper between subtopics
* Create a new subtopic
* Delete a subtopic
* Merge two subtopics
* Mark a paper as irrelevant

The user's manual changes should never be silently overwritten.

---

# 15. Uncategorized Papers

The system must support papers that do not clearly belong to any generated category.

These papers should appear under:

> Uncategorized

This is preferable to forcing every paper into a potentially inaccurate category.

---

# 16. Search Transparency

The application should make it possible to understand where results came from.

For each paper display:

* Provider
* DOI if available
* Original publication URL
* Open-access URL if available

For each project retain:

* Original research question
* Generated search queries
* Search filters
* Providers queried
* Search timestamp

---

# 17. Full-Text Access

Each paper should have an access status.

Use the following initial states:

```text
OPEN_ACCESS
INSTITUTIONAL_ACCESS
ABSTRACT_ONLY
UNKNOWN
```

For MVP:

### OPEN_ACCESS

The application may provide a direct full-text/open-access link.

### ABSTRACT_ONLY

Metadata and abstract are available, but full text is not.

### UNKNOWN

The application cannot determine access status.

### INSTITUTIONAL_ACCESS

Reserved for future institutional authentication support.

The MVP does not need to implement university SSO yet.

---

# 18. Institutional Access Architecture

Although not required for MVP, the architecture must allow future support for university/library authentication.

Potential technologies include:

* SAML
* Shibboleth
* OpenAthens
* eduGAIN
* EZproxy

Create an abstraction such as:

```text
InstitutionalAccessProvider
```

Possible future operations:

```text
findInstitution()
authenticate()
resolveAccess(paper)
getAccessUrl(paper)
```

The application must not assume that institutional authentication gives the backend permission to permanently download, store, or redistribute licensed publisher PDFs.

Initially institutional access should primarily provide users with authenticated access links.

---

# 19. Open Access Detection

The application should attempt to determine whether an openly available copy of a paper exists.

Paper metadata should support:

```text
isOpenAccess
openAccessUrl
accessStatus
```

A future Open Access resolver can be added independently from the scholarly search provider.

---

# 20. LLM Abstraction

The application must not depend directly on a single LLM vendor.

Create a provider abstraction such as:

```text
LlmProvider
```

Example operations:

```text
generateSearchQueries()
nameCluster()
describeCluster()
explainPaperClassification()
analyzeResearchCoverage()
```

Possible implementations could support:

* OpenAI
* Anthropic
* local models

LLM prompts should be stored separately from application business logic.

---

# 21. Structured LLM Responses

LLM responses used by the backend must use structured output.

Do not parse arbitrary prose when structured JSON can be used.

Example:

```json
{
  "name": "Automated Software Testing",
  "description": "Research on using LLMs for test generation and evaluation.",
  "keywords": [
    "testing",
    "test generation",
    "unit tests"
  ]
}
```

Validate LLM responses before storing them.

---

# 22. Hallucination Protection

The LLM must never be treated as the authoritative source for:

* Paper titles
* Authors
* DOI values
* Publication dates
* Journals
* Citation counts
* URLs

These fields must originate from scholarly providers.

LLM-generated output should only concern:

* search query expansion
* categorization
* cluster naming
* summaries
* explanations
* analysis

The system must avoid displaying invented citations.

---

# 23. Research Projects

Users should be able to save research sessions as projects.

Example project model:

```text
ResearchProject
- id
- title
- researchQuestion
- createdAt
- updatedAt
- searchParameters
- status
```

Projects contain:

```text
ResearchProject
  ├── SearchQueries
  ├── Papers
  ├── Subtopics
  └── UserOverrides
```

---

# 24. Persistence

The MVP should persist:

* Research projects
* Search queries
* Retrieved paper metadata
* Paper relevance scores
* Generated embeddings if appropriate
* Subtopics
* Paper/subtopic relationships
* User edits

A relational database is appropriate.

Recommended:

> PostgreSQL

---

# 25. Suggested Domain Model

```text
User
ResearchProject
SearchQuery
Paper
ProjectPaper
Subtopic
SubtopicPaper
PaperProviderResult
```

Possible relationships:

```text
User
 └── ResearchProject
       ├── SearchQuery
       ├── ProjectPaper ── Paper
       └── Subtopic
             └── SubtopicPaper ── Paper
```

`Paper` should represent globally reusable scholarly metadata.

`ProjectPaper` should contain project-specific data such as:

```text
relevanceScore
classificationExplanation
isRelevant
```

---

# 26. API Requirements

The backend should expose REST or equivalent endpoints.

Example:

```text
POST /api/projects
GET  /api/projects
GET  /api/projects/{id}

POST /api/projects/{id}/search

GET  /api/projects/{id}/papers
GET  /api/projects/{id}/subtopics

PATCH /api/subtopics/{id}
POST  /api/subtopics
DELETE /api/subtopics/{id}

POST /api/papers/{id}/move
POST /api/papers/{id}/irrelevant
```

Long-running searches should expose status.

Example:

```text
CREATED
SEARCHING
PROCESSING
CLUSTERING
ANALYZING
COMPLETED
FAILED
```

---

# 27. Search Progress

Literature searches may take several seconds.

The frontend should show progress rather than appearing frozen.

Example:

```text
Searching scholarly databases...
47 papers found

Removing duplicates...
41 unique papers

Analyzing relevance...
32 relevant papers

Discovering research themes...
5 subtopics identified
```

---

# 28. Error Handling

The system must gracefully handle:

* Scholarly API unavailable
* Rate limits
* No papers found
* Missing abstracts
* Duplicate papers
* LLM timeout
* Invalid LLM response
* Embedding service failure
* Clustering failure

A failure in one provider should not necessarily fail the entire research search.

Verified by NFR-REL-1..4.

---

# 29. Logging

Backend logs should record:

* provider requests
* provider errors
* number of papers returned
* number of duplicates removed
* relevance pipeline duration
* clustering duration
* LLM calls
* LLM token usage when available
* total search duration

Do not log full API keys or sensitive authentication credentials.

Verified by NFR-OBS-1..2.

---

# 30. Configuration

Secrets must come from environment variables.

Example:

```text
OPENAI_API_KEY
OPENALEX_EMAIL
DATABASE_URL
```

Provider-specific configuration should live outside business logic.

---

# 31. Non-Functional Requirements

## Performance

The application should support at least 100–250 papers in a research project without significant UI slowdown.

## Reliability

A provider failure should be handled gracefully.

## Maintainability

Search providers, LLM providers, embedding providers, and clustering algorithms should be replaceable.

## Security

API keys must never be exposed to the frontend.

## Explainability

Users should be able to understand:

* where a paper came from
* why it was considered relevant
* why it belongs to a subtopic

## Reproducibility

Store enough information about each search to understand how the result was generated.

## Measurable requirements

Every NFR in this table is enforced by the automated suite in `backend/tests/nfr/` and must
pass in CI. Performance tests fail above the CI ceiling (3 × target); measured values are
published in the CI `test-report` artifact.

| ID | Requirement | Target | CI ceiling | Test |
|---|---|---|---|---|
| NFR-PERF-1 | The research map for a 250-paper project (fixture: 252 papers, 6 × 42) loads, with all 250 paper rows visible, from navigation start | ≤ 1.5 s | 4.5 s | `test_nfr_perf_1_map_renders_250_papers` |
| NFR-PERF-2 | On that map, selecting a subtopic tab and toggling "Open access only" each re-render | ≤ 0.3 s | 0.9 s | `test_nfr_perf_2_tab_and_filter_rerender` |
| NFR-PERF-3 | Backend analysis of 250 papers (deduplication, lexical ranking, semantic ranking, filtering, clustering) with precomputed 512-dimension vectors | ≤ 1.0 s | 3.0 s | `test_nfr_perf_3_backend_analysis_of_250_papers` |
| NFR-PERF-4 | `GET` papers, subtopics, searches and queries for a 250-paper project, p95 over 20 calls each | ≤ 0.2 s | 0.6 s | `test_nfr_perf_4_read_endpoints_p95` |
| NFR-REL-1 | Each documented failure class returns its HTTP status and error code and leaves the previous completed results, subtopics and manual edits unchanged; a search that finds no papers completes empty instead of failing | pass/fail | — | `test_nfr_rel_1_failures_return_codes_and_preserve_results`, `test_nfr_rel_1_no_papers_completes_empty` |
| NFR-REL-2 | Optional LLM steps (query expansion, cluster naming, explanation) degrade instead of failing the search | pass/fail | — | `test_nfr_rel_2_expansion_failure_falls_back_to_keywords`, `test_nfr_rel_2_naming_failure_keeps_numbered_clusters`, `test_nfr_rel_2_explanation_timeout_is_504` |
| NFR-REL-3 | When some queries fail and at least one succeeds, the search completes with the surviving results; it fails only when every query fails, with the first failure's code | pass/fail | — | `test_nfr_rel_3_partial_query_failure_keeps_surviving_results`, `test_nfr_rel_3_all_queries_failing_fails_with_first_code` |
| NFR-REL-4 | No stage blocks past its deadline; a hanging provider at retrieval, embedding or naming ends the stage with its timeout behavior | pass/fail | — | `test_nfr_rel_4_hanging_retrieval_times_out`, `test_nfr_rel_4_hanging_embedding_times_out`, `test_nfr_rel_4_hanging_naming_falls_back` |
| NFR-SEC-1 | Distinctive fake `OPENAI_API_KEY` and `OPENALEX_API_KEY` values never appear in any API response body or header, any served page or asset, or any log record during a full run | pass/fail | — | `test_nfr_sec_1_api_keys_never_leave_the_server` |
| NFR-SEC-2 | HTML or script in provider metadata renders as inert text on the paper card and in the drawer | pass/fail | — | `test_nfr_sec_2_metadata_html_is_inert` |
| NFR-SEC-3 | A link is rendered only for an `http:` or `https:` URL; other schemes coming from a provider produce no `href` | pass/fail | — | `test_nfr_sec_3_only_http_links_survive_normalization`, `test_nfr_sec_3_manual_reference_rejects_script_urls`, `test_nfr_sec_3_rendered_links_are_http_or_local` |
| NFR-SEC-4 | Every write endpoint rejects unknown fields and out-of-range values with 422 | pass/fail | — | `test_nfr_sec_4_write_endpoints_reject_bad_input` |
| NFR-OBS-1 | One successful search emits a log record for each §29 item, including duplicates removed | pass/fail | — | `test_nfr_obs_1_search_logs_every_required_event` |
| NFR-OBS-2 | Provider and LLM failures log their error code and never the response payload, request URL or exception text | pass/fail | — | `test_nfr_obs_2_failures_log_codes_not_payloads` |
| NFR-TRACE-1 | Every completed run persists enough to reproduce it: description, keywords, generated and failed queries, year range, paper limit, provider, timestamps and counts | pass/fail | — | `test_nfr_trace_1_completed_run_is_reproducible` |
| NFR-TRACE-2 | Scholarly metadata comes only from the provider, even when LLM output contains metadata-like text | pass/fail | — | `test_nfr_trace_2_llm_output_never_becomes_metadata` |
| ACC-38 | The §38 MVP scenario is walked end to end with fake providers, from project creation through paper links | pass/fail | — | `test_acc_38_mvp_scenario` |

---

# 32. Initial Frontend Pages

The MVP should contain:

### `/`

Landing / project dashboard.

### `/projects/new`

Create research project.

### `/projects/{id}`

Main Research Map.

### `/settings`

LLM/provider configuration where appropriate.

---

# 33. Main Research Map Components

Suggested frontend component hierarchy:

```text
ResearchProjectPage

├── ProjectHeader
├── SearchProgress
├── SearchQueryList
├── ResearchSummary
│
├── SubtopicList
│   ├── SubtopicCard
│   │   └── PaperCard
│   ├── SubtopicCard
│   │   └── PaperCard
│   └── UncategorizedSection
│
└── PaperDetailDrawer
```

---

# 34. Future Feature: Research Coverage

Do not implement this in the initial MVP, but keep the architecture compatible with it.

A future LLM analysis could inspect the generated research map and identify:

* highly studied themes
* emerging themes
* underrepresented themes
* conflicting findings
* methodological gaps
* potential research questions

Example:

> Existing literature heavily focuses on code generation and automated testing, while substantially fewer studies evaluate long-term effects of LLM use on software maintainability.

These statements must be grounded in the papers contained in the project.

---

# 35. Future Feature: Exports

Future versions may support:

* BibTeX
* RIS
* CSV
* Zotero
* Markdown
* Literature review outlines

Keep the paper model sufficiently complete to support these formats.

---

# 36. Out of Scope for Initial MVP

Do NOT implement the following during the first version:

* Direct Scopus integration
* University SSO
* EZproxy authentication
* Publisher account authentication
* Automatic downloading of paywalled PDFs
* PDF vector databases
* Full automatic literature reviews
* Citation network visualization
* Collaborative projects
* Zotero synchronization
* Research-gap analysis
* Mobile application
* Multiple LLM providers

Design interfaces so these can be added later, but do not implement them yet.

---

# 37. Recommended MVP Implementation Order

Implement in approximately this order:

## Phase 1

Project creation and persistence.

## Phase 2

One scholarly provider.

Retrieve and normalize paper metadata.

## Phase 3

Deduplication and relevance ranking.

## Phase 4

Embedding generation and clustering.

## Phase 5

LLM cluster naming and descriptions.

## Phase 6

Research Map frontend.

## Phase 7

Paper details and classification explanations.

## Phase 8

Manual category editing.

## Phase 9

Open-access detection and external paper links.

---

# 38. MVP Definition of Done

The MVP is complete when the following scenario works end-to-end:

1. User creates a project.

2. User enters a research description:

   > Large language models in software engineering

3. Backend generates short search queries from the description.

4. A real scholarly API is queried.

5. At least several dozen papers are retrieved.

6. Duplicate papers are removed.

7. Papers receive relevance scores.

8. Irrelevant papers are removed or hidden.

9. Remaining papers are clustered using embeddings.

10. The LLM gives each cluster a useful human-readable name.

11. The Research Map displays the generated subtopics.

12. Papers appear underneath each subtopic.

13. Clicking a paper displays its metadata and abstract.

14. The UI explains why the paper belongs to that category.

15. The user can manually move a paper to another category.

16. The user can rename a generated category.

17. Each paper links to its real scholarly source.

18. No citation or paper shown to the user is invented by the LLM.

---

# 39. Core Engineering Principle

Use deterministic systems for facts and retrieval.

Use AI for interpretation.

In practice:

```text
Academic APIs
    ↓
FACTS

Embeddings / algorithms
    ↓
SIMILARITY + STRUCTURE

LLM
    ↓
INTERPRETATION + LANGUAGE

User
    ↓
FINAL CONTROL
```

This principle should guide implementation decisions throughout the project.

