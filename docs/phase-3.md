# Phase 3 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `analysis.py`: deterministic deduplication and lexical relevance ranking. Pure
  functions over `Paper` values; no I/O, no database, no provider or LLM calls.
- `search.py`: runs `deduplicate` then `rank_papers` on retrieved papers before
  persistence, and records the duplicate count on the search run.
- `search_persistence.py`: stores a per-association `relevanceScore` and a per-run
  `duplicateCount`; reads papers back joined to their score in rank order.
- `papers.py`: `ProjectPaper` extends `Paper` with a `relevanceScore` in `[0, 1]`;
  `SearchRun` gains `duplicateCount`.
- `api.py`: `GET /api/projects/{uuid}/papers` responds with `ProjectPaper` records.
- `frontend/app.js`: a relevance percentage on each paper row and a merged-duplicate
  note beneath the results, in the existing list.

Retrieval, the OpenAlex query, filters, timeouts, leases, and error mapping are
unchanged from Phase 2. Both new steps are deterministic and use no LLM.

## Deduplication

Records are grouped by normalized DOI, then by case-folded provider identity
(`source`, `sourceId`), then by normalized title, and groups that share any of
these keys are merged transitively. A DOI is normalized by stripping a
`doi:`/`https://doi.org/` prefix and lower-casing; a value that is not a `10.`
DOI is treated as absent. A title is normalized to lower-case ASCII alphanumeric
tokens joined by single spaces. An identical normalized title does not merge two
records that carry different explicit DOIs.

Merging fills gaps only. The record with more populated fields (then a longer
abstract, then more authors) is kept as primary; the other supplies values only
where the primary's are null, empty, or an empty collection. Authoritative fields
already present on the primary are never overwritten. `duplicateCount` is the number
of input papers removed by merging.

## Relevance ranking

Query and keyword terms are tokenized. Each term gets a weight of
`1 + ln((N + 1) / (df + 1))`, where `df` is the number of retrieved papers whose
title, abstract, or venue contains the term, multiplied by `1.4` for keyword terms
and by up to `1.4` more for terms repeated in the question. A paper scores the sum
over all terms of `term_weight * field_weight`, with field weight `3.0` for a title
hit, `1.5` for an abstract hit, `0.5` for a venue hit, and `0` otherwise. A verbatim
normalized-question substring in the title adds a fixed fraction of the denominator.
The score is divided by `sum(term_weights) * 3.0`, clamped to `1.0`, and rounded to
six places, so an empty query yields `0.0` for every paper.

Papers are ordered by descending score, then descending citation count, then
normalized title, then id, so ranking is stable for a given input.

## Storage

`003_deduplication_relevance.sql` adds `project_papers.relevanceScore`
(`DOUBLE PRECISION`, `0`–`1`) and `search_runs.duplicateCount` (`INTEGER`, `>= 0`).
Both are added with a temporary default so existing rows backfill, then the default
is dropped; Phase 2 associations read back as score `0`. A successful search still
replaces a project's associations atomically, now writing each surviving paper's
score and position. Failed searches leave the previous papers and their scores
intact. Shared `papers` metadata is unchanged by ranking.

## Deliberate omissions

No embeddings, clustering, subtopics, classification explanations, or research map.
No LLM query expansion or reranking, and no semantic similarity: ranking is lexical.
No cross-provider identifier reconciliation beyond DOI, no title fuzzy matching
beyond exact normalized equality, and no user relevance overrides or "mark
irrelevant" action. The explainable list lets users verify deduplication and
ranking now, ahead of the Phase 4 embedding pipeline.

## References

- https://help.openalex.org/data/works/attributes/
- https://en.wikipedia.org/wiki/Tf%E2%80%93idf
