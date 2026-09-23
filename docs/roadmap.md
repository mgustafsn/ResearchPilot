# Roadmap

`docs/requirements.md` is the MVP target. Work is named by the feature it delivers, not by a
sequence number. Each feature gets a branch `feat/<name>`, a note in
`docs/features/<name>.md`, and one minor version bump when it ships.

## Delivered

### Projects and retrieval

| Feature | What it does | Note |
| --- | --- | --- |
| Projects | Create, edit, and delete research projects in PostgreSQL | — |
| OpenAlex retrieval | Fetch papers from OpenAlex and normalize their scholarly metadata | [openalex-retrieval](features/openalex-retrieval.md) |
| Query expansion | The LLM proposes related queries; the user can toggle them; retrieval runs every query | [query-expansion](features/query-expansion.md) |
| Open access | Open-access status, the open-access filter, and publication/full-text links | [open-access](features/open-access.md) |

### Relevance

| Feature | What it does | Note |
| --- | --- | --- |
| Deduplication and ranking | Merge duplicates by DOI, identifier, and title; lexical relevance ranking | [deduplication-and-ranking](features/deduplication-and-ranking.md) |
| Relevance filtering | Drop low-relevance papers before clustering and show the filtered count | [relevance-filtering](features/relevance-filtering.md) |
| Semantic relevance | Score relevance by embedding similarity between the question and each paper | [semantic-relevance](features/semantic-relevance.md) |

### Organization

| Feature | What it does | Note |
| --- | --- | --- |
| Embeddings and clustering | Embed title and abstract; deterministic clustering into subtopics | [embeddings-and-clustering](features/embeddings-and-clustering.md) |
| Cluster naming | Structured LLM subtopic names and descriptions | [cluster-naming](features/cluster-naming.md) |
| Classification explanations | On-demand "why is this paper here" explanations in the drawer | [classification-explanations](features/classification-explanations.md) |
| Explanations on paper cards | The same explanations inline on each card | [card-explanations](features/card-explanations.md) |
| Manual organization | Rename, move, set aside/restore, and confirm before a search replaces edits | [manual-organization](features/manual-organization.md) |
| Subtopic management | Create, delete, and merge subtopics with paper reassignment | [subtopic-management](features/subtopic-management.md) |

### Interface

| Feature | What it does | Note |
| --- | --- | --- |
| Research map | Research map, category tabs, staged search progress, paper drawer | [research-map](features/research-map.md) |
| Settings and navigation | Settings page and complete primary navigation | [settings-and-navigation](features/settings-and-navigation.md) |

### Demo stabilization

Search locks protect manual organization. Cache identities include their inputs;
explanation writes reject stale context. Empty named categories and filter-independent
move destinations remain usable. Regression coverage includes SQLite, Chromium with
fake providers, and PostgreSQL migrations/concurrency. PostgreSQL verification is
required before sign-off.

## Planned

| Feature | What it does | Design |
| --- | --- | --- |
| Description-driven queries | Search only short keyword queries, never the long research description; a user-editable query list | [spec](superpowers/specs/2026-09-23-description-driven-queries-design.md) |
| Acceptance test and logging | Automate the §38 end-to-end scenario; audit logging against §29 | — |

Requirements are not reduced to fit the demo. Institutional access, exports/Zotero, PDF
ingestion, citation graphs, research-gap analysis, and collaboration remain outside the
MVP.

## Phase history

Work up to version 0.15.0 was numbered by phase. Commits, `docs/prompts.md`, and the course
report still use those numbers.

| Phase | Feature | Phase | Feature |
| --- | --- | --- | --- |
| 1 | Projects | 9 | Open access |
| 2 | OpenAlex retrieval | 10 | Query expansion |
| 3 | Deduplication and ranking | 11 | Relevance filtering |
| 4 | Embeddings and clustering | 12 | Subtopic management |
| 5 | Cluster naming | 13 | Explanations on paper cards |
| 6 | Research map | 14 | Settings and navigation |
| 7 | Classification explanations | 15 | Semantic relevance |
| 8 | Manual organization | | |
