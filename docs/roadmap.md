# Implementation roadmap

The requirements remain the MVP target. Phases 1–9 deliver a working demo, with
partial scope in the research map and manual organization phases.

| Phase | Delivered |
| --- | --- |
| 1 | Project CRUD and PostgreSQL persistence |
| 2 | OpenAlex retrieval and normalized scholarly metadata |
| 3 | Deduplication and lexical relevance ranking |
| 4 | Embeddings and deterministic clustering |
| 5 | Structured LLM cluster names and descriptions |
| 6 | Research map, category tabs, and staged search progress |
| 7 | Paper drawer and on-demand classification explanations |
| 8 | Rename, move, set aside/restore, and confirmation before replacing edits |
| 9 | Provider-derived open-access status, filters, and external links |
| 10 | Structured query expansion, persisted query selection, and multi-query retrieval |
| 11 | Deterministic automatic relevance filtering with transparent counts |
| 12 | Create, delete, and merge subtopics with paper reassignment |
| 13 | On-demand classification explanations on paper cards |
| 14 | Settings page and complete primary navigation |

## Demo stabilization

Search locks protect manual organization. Cache identities include their inputs;
explanation writes reject stale context. Empty named categories and filter-independent
move destinations remain usable. Regression coverage includes SQLite, Chromium with
fake providers, and PostgreSQL migrations/concurrency. PostgreSQL verification is
required before sign-off.

## Missing MVP capabilities: follow-up work

- Semantic relevance scoring remains a target beyond the current lexical ranking.
- Complete the requirements' end-to-end MVP acceptance scenario and logging coverage.

These are not implemented as part of stabilization. Requirements are not reduced
to fit the demo. Future institutional access, exports/Zotero, PDF ingestion, citation
graphs, research-gap analysis, and collaboration remain outside this MVP work.
