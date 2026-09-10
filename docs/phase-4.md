# Phase 4 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `embeddings.py`: the `EmbeddingProvider` protocol (`name`, `model`, `dimension`,
  `embed`). No I/O.
- `providers/openai.py`: HTTP calls to the OpenAI embeddings endpoint, batching,
  and mapping failures to `ProviderError` codes. The only Phase 4 code that touches
  the network.
- `clustering.py`: deterministic k-means and the outlier rule. Pure functions over
  vectors; no I/O, no database, no provider calls.
- `search.py`: `_prepare` deduplicates, ranks, reads reusable embeddings, calls the
  provider for the rest, and clusters — all outside a transaction. `finish` is now
  pure persistence and status handling.
- `search_persistence.py`: the `embedding` / `embeddingModel` columns on `papers`,
  `clusterId` on `project_papers`, `clusterCount` on `search_runs`, the reuse
  lookup, and the conditional embedding write.
- `papers.py`: `ProjectPaper` gains `clusterId`; `SearchRun` gains `clusterCount`.
- `api.py`: a second HTTP client with the OpenAI key, an `embedding_provider`
  parameter, and the new `503` error codes.
- `frontend/app.js`: the papers list is grouped by cluster with an Uncategorized
  section; the search status line reports the cluster count.

Retrieval, the OpenAlex query, filters, and the claim/lease mechanics are unchanged
from Phases 2–3. Ranking still orders `GET .../papers`; clustering only annotates.

## Embeddings

`_embedding_text` joins a paper's title and abstract; an empty result becomes
`"untitled paper"` so the request is never rejected for a blank input. Text is sent
to OpenAI `text-embedding-3-small` with `dimensions: 512`, in batches of at most 256
and truncated to 30,000 characters each. Responses are reordered by their `index`
field and validated for count and vector shape before use.

`RETRIEVAL` and embedding each have a 60-second bound; the recovery lease is 240
seconds to cover the combined operation. HTTP `401`/`403` →
`EMBEDDING_UNAUTHORIZED`, `429` → `EMBEDDING_RATE_LIMITED`, other non-`200` and
transport errors → `EMBEDDING_UNAVAILABLE`, malformed bodies →
`EMBEDDING_INVALID_RESPONSE`. There are no retries. An embedding failure marks the
run `FAILED` and leaves the last successful papers and clusters in place.

Before calling the provider, the run looks up stored vectors for the same model and
embeds only the papers without one. New vectors are written to the shared `papers`
row with the model id; reused rows omit the embedding columns from the upsert, so a
stored vector is never overwritten. Changing the model is a manual re-run, not a
migration.

## Clustering

Vectors are L2-normalized. For `k` from 2 to `min(8, n // 2)`, seeded k-means++
initializes Lloyd's algorithm; the `k` with the highest mean silhouette wins.
Fewer than five papers, or fewer than two distinct vectors, skip straight to a
single cluster.

A cluster with fewer than two members becomes `None`. Within a kept cluster of at
least four members, a point more than `mean + 3.5 * std` from the centroid becomes
`None`. Surviving clusters are relabeled `0..k-1` by descending size, ties broken by
first appearance, so the labeling is canonical for a given set of vectors. If every
point is demoted, the result collapses to a single cluster.

Silhouette distances use the Gram matrix of the normalized vectors, keeping memory
at `O(n^2)` rather than `O(n^2 * dimension)`.

## Storage

`004_embeddings_clusters.sql` adds `papers.embedding` (`JSONB`),
`papers.embeddingModel` (`TEXT`), `project_papers.clusterId` (`INTEGER`, null =
Uncategorized), and `search_runs.clusterCount` (`INTEGER`, backfilled via a
temporary default). A successful search still replaces a project's associations
atomically, now writing each surviving paper's `clusterId`. Failed searches keep the
previous associations. Shared `papers` metadata is unchanged except for the
embedding columns.

## Deliberate omissions

No LLM cluster names, descriptions, or keywords. No research map, paper-detail
drawer, or search-progress stages. No manual re-clustering, paper moves, or "mark
irrelevant". No pgvector or nearest-neighbour search, no cross-project cluster
reuse, and no `PROCESSING`/`CLUSTERING` run statuses — a single `COMPLETED` as
before. The grouped list lets users verify embedding and clustering now, ahead of
the Phase 5 LLM naming.

## References

- https://platform.openai.com/docs/guides/embeddings
- https://platform.openai.com/docs/api-reference/embeddings
- https://en.wikipedia.org/wiki/Silhouette_(clustering)
- https://en.wikipedia.org/wiki/K-means%2B%2B
