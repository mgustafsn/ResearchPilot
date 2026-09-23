# Description-driven queries

The research question field is relabeled "Research description" and is never sent to a
scholarly provider directly. On the live IaC run (semantic relevance, `docs/features/
semantic-relevance.md`), the conversational description "Infrastructure as Code — from
manual console work to declarative provisioning, and where generative AI fits in" was
searched verbatim as one of six keyword queries; the mismatch between a long sentence and
OpenAlex's title/abstract matching left semantic relevance to filter 55 of the 90 unique
papers retrieved, keeping only 35. Description-driven queries removes the description
itself from retrieval so the queries that reach OpenAlex are short and keyword-shaped.

A structured LLM call turns the description and keywords into 3–6 short queries, each at
most 8 words; malformed, duplicate, or over-length candidates are dropped before saving.
If the call fails, times out, or returns nothing usable, the project's keywords are used
as queries instead, and if the project has no keywords, the project title is used. The
description is not part of any fallback.

The generated queries are saved per project (`search_queries`, migration 013 adds
`userAdded`). Regenerating suggestions replaces only rows the user did not add or edit;
queries the user wrote or edited are left alone. Users can also add a query directly
(`POST /queries/custom`, up to the saved-queries limit, case-insensitively unique),
disable/enable, edit, or delete any query. A search retrieves only the enabled queries,
dividing the configured paper limit across them. A search with no enabled query is
rejected with 422 `NO_ENABLED_QUERIES` and creates no run — the project's previous results
are untouched.

`PATCH /api/projects/{id}/queries/{queryId}` moved from a `?enabled=true|false` query
parameter to a JSON body accepting `query` and/or `enabled`, so a single call can rename
and toggle a query together.

Semantic relevance is unchanged: it still scores retrieved papers against the embedded
research description plus keywords, not against the generated queries. Only retrieval
input changed.

## Live check

Same description and keywords `["IaC"]` (year range and paper limit unset, matching the
semantic-relevance baseline project "IaC (Phase 15 check)"), run against the dev database
on 2026-09-23 with the OpenAlex/OpenAI providers behind `.env`.

| | Before (6 long queries, semantic relevance run) | After (description-driven queries) |
| --- | --- | --- |
| Generated queries | 6 restatements of the full description (up to 17 words each) | 5 short queries, 2–4 words each |
| totalFound | 200,144 | 2,940,542 |
| Unique (paperCount + filteredCount) | 90 | 98 |
| filteredCount | 55 | 46 |
| paperCount (kept) | 35 | 52 |
| Subtopics | 2: "infrastructure automation and compliance", "Generative AI in Infrastructure Management" | 4: "Infrastructure as Code Practices and Challenges", "ai-driven infrastructure automation", "generative ai applications and design", "declarative infrastructure provisioning" |

Generated queries (after): "Automation in cloud infrastructure", "Declarative provisioning",
"Generative AI applications", "Infrastructure as Code", "Manual console work transition".

Top 10 retrieved papers (all scored 100% — cosine similarity above the 0.60 ceiling used
for calibration; short, on-topic titles cluster at the top of the relevance range):

1. Infrastructure as Code
2. End-to-End Automation in Cloud Infrastructure Provisioning
3. Adoption, Support, and Challenges of Infrastructure-as-Code: Insights from Industry
4. Code Smells in Infrastructure as Code
5. Infrastructure as Code: Managing Servers in the Cloud
6. Infrastructure-as-Code for Data-Intensive Architectures: A Model-Driven Development Approach
7. GLITCH: Automated Polyglot Security Smell Detection in Infrastructure as Code
8. Static Analysis of Infrastructure as Code: a Survey
9. Testing practices for infrastructure as code
10. Infrastructure as Code

Short keyword queries retrieved more precisely on-topic papers (52 kept vs. 35) with fewer
duplicates (2 vs. 12) and more, more specific subtopics (4 vs. 2, one of which — "generative
ai applications and design" — reflects an off-topic cluster from the generic "Generative AI
applications" query, still caught downstream by relevance filtering). `totalFound` rose
because short, generic queries (e.g. "Infrastructure as Code") match far more of OpenAlex's
corpus by title/abstract than a full sentence does; it counts provider-reported hits per
query, not papers actually retrieved.
