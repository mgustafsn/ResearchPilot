# Multi-source search

Date: 2026-09-24 · Status: implemented (v0.21.0)

## Problem

`SCHOLARLY_PROVIDER` selects exactly one source. OpenAlex has broad coverage and abstracts.
Scopus has curated indexing and citation counts, but with the current Elsevier key it returns
no abstracts, because only the `STANDARD` view is authorized. With Scopus alone, relevance
and clustering therefore work from titles only. A user who wants the Scopus corpus must give
up OpenAlex, and the other way round.

## Decision

A single search can query several sources. Their results go through the existing
deduplication, which already merges records by DOI, then provider identity, then normalized
title. It keeps the richer record and fills its gaps from the other, so an OpenAlex abstract
and a Scopus citation count end up on the same paper.

| Question | Decision |
|---|---|
| How are sources chosen? | A server-side comma list: `SCHOLARLY_PROVIDER=openalex,scopus`. No per-project setting. |
| One source fails, another succeeds | The search completes. The failed source is recorded on the run and shown as a warning. |
| Provenance | Not tracked. A merged paper keeps one `source`/`sourceId`, as today. |
| Paper budget | Each source gets the full per-query limit. After semantic ranking, unique papers are capped at `maxPaperCount`. |

**Dependency:** this builds on `providers/scopus.py` (the Scopus retrieval feature), so
Scopus retrieval must be on `main` before implementation starts.

## 1. `MultiSourceProvider`

New file: `backend/researchpilot/providers/multi.py`. It implements the existing
`PaperProvider` protocol, so `SearchService` does not need to know how many sources exist.

- `name` is the source names joined with `+`, in configured order, e.g. `OpenAlex+Scopus`. It is stored in `search_runs.provider` (`String(100)`).
- `search(parameters)` passes the same parameters to every source concurrently (`asyncio.gather(..., return_exceptions=True)`).
  - An exception other than `ProviderError` is re-raised unchanged, as in `SearchService._retrieve`.
  - If every source fails, it raises the first `ProviderError` in configured order. It does the same if some sources fail and the survivors return zero papers, which mirrors the per-query rule in `_retrieve`. The caller then counts the query as failed.
  - Otherwise it returns the concatenated papers, the summed `totalFound` and `skippedCount`, and `failedSources`: the `name` of each failed source, in configured order.
- It logs a failed source as `name` plus error code only, never the query text.

## 2. Contracts (`papers.py`)

- `SearchResult.failedSources: list[str] = []`
- `SearchRun.failedSources: list[str] = []`

Both default to empty, so the single-source providers and existing runs are unaffected.
The values are provider display names (`OpenAlex`, `Scopus`), so the UI can show them
without mapping.

## 3. Pipeline (`search.py`)

- `_retrieve` also returns the ordered union of `failedSources` across the surviving query results. `CompletedSearch` gains `failed_sources`, and `finish` stores it on the run.
- `_prepare` caps the semantically ranked list at `run.parameters.maxPaperCount`, after `rank_semantically` and before `filter_relevant`. `filteredCount` is counted over the capped list. With one source the cap never takes effect, because retrieval already requests at most the limit in total.
- `deduplicate` and `_merge` in `analysis.py` are unchanged.

## 4. Persistence

- `migrations/017_failed_sources.sql`:
  `ALTER TABLE search_runs ADD COLUMN "failedSources" JSONB NOT NULL DEFAULT '[]'::jsonb;`
- `SearchRunRow.failedSources` goes next to `failedQueries`. It also gets a bootstrap entry in `scripts/migrate.py` (`requirements` + `required_columns`).

## 5. Configuration and wiring

- `config.scholarly_provider()` becomes `scholarly_providers()`. It returns an ordered list, trims whitespace, lower-cases, and drops duplicates. An empty list or unknown names raise `RuntimeError`. If `scopus` is listed, `ELSEVIER_API_KEY` is still required. The default stays `openalex`.
- `api.create_app` opens one `httpx.AsyncClient` per selected source, because each source has its own headers, through an `AsyncExitStack`. With one source it uses the bare provider. With several, it wraps them in `MultiSourceProvider`. The `provider=` test injection is unchanged.
- `/api/settings/status` keeps `scholarlyProvider`, now the joined name such as `OpenAlex+Scopus`, and adds `scholarlyProviders`, the display names such as `["OpenAlex", "Scopus"]`. The change is additive, so the existing UI and tests keep working. In Settings, every listed source is marked **In use**.

## 6. Interface

Next to the existing failed-queries line in the search panel: when the latest run has
`failedSources`, it shows
*"Scopus was unavailable for one or more queries; results may be incomplete."*
`failedSources` lists every source that failed on at least one query, so the message does
not claim which source the results came from. Names are joined with "and".

## 7. Error handling summary

| Situation | Result |
|---|---|
| All sources fail for a query | That query fails, which is the existing failed-query behavior |
| Some sources fail, survivors have papers | Completes; `failedSources` warning |
| Some sources fail, survivors have zero papers | That query fails |
| All queries fail | The run fails with the first error and the previous results are kept, as today |
| Programming error in a source | Propagates and becomes `INTERNAL`, as today |

## 8. Testing

- New `test_multi_source.py` with fake sources. It covers combined papers and counts; the joined name; a partial failure that yields `failedSources`; all sources failing, which raises the first error; a failure alongside zero survivor papers, which raises; and non-provider exceptions, which propagate.
- `test_search.py`: `failedSources` is persisted and returned in history; a cross-source duplicate keeps the OpenAlex abstract and gains the Scopus citation count; the `maxPaperCount` cap applies.
- Config: comma lists, whitespace and case, duplicates, unknown names, and a missing Elsevier key. The existing `scholarly_provider()` tests move to the new name.
- API: the settings status returns the list.
- Browser (Chromium, fakes): the failed-source warning renders, and Settings marks both sources as in use.
- PostgreSQL: migration 017 applies and the default backfills existing runs.
- Live smoke test with `SCHOLARLY_PROVIDER=openalex,scopus` and a small limit, and again with a deliberately invalid Elsevier key, where the run completes with the warning.

## Out of scope

Per-project source selection, per-paper provenance, provider weighting, and any change to
deduplication rules.
