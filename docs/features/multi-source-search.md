# Multi-source search

One search can query OpenAlex and Scopus together. Set
`SCHOLARLY_PROVIDER=openalex,scopus` (with `ELSEVIER_API_KEY`) in the backend environment.
The list is ordered, trimmed, case-insensitive, and de-duplicated. `openalex` alone stays
the default.

A `MultiSourceProvider` sits behind the existing `PaperProvider` contract, so the search
pipeline still sees one provider. Every query goes to every source with the full per-query
budget. The existing deduplication merges the results by DOI, provider identity, and
normalized title, keeping the richer record and filling its gaps from the other. A paper
both sources return can therefore keep the OpenAlex abstract and gain the Scopus citation
count. After semantic ranking, unique papers are capped at the project's paper limit.

If one source fails and another returns papers, the search completes. The run records
the failed source names in `failedSources`, and the search panel says, for example,
"Scopus was unavailable; results come from OpenAlex only." If the survivors find nothing,
that query fails as before. Logs name the source and error code, never the query text.

Migration 017 adds `search_runs.failedSources` (default empty). `/api/settings/status`
keeps `scholarlyProvider` (now the joined name, such as `OpenAlex+Scopus`) and adds
`scholarlyProviders`, the list of display names. Settings marks each one In use.

Merged papers keep a single `source`; per-paper provenance, per-project source choice,
and provider weighting are not included. No new dependencies.
